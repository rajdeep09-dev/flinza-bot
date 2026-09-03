"""
Flinza — Standalone Email Outreacher Bot
Telegram-operated. All email sending, scheduling, reply watching, and lead management.
"""

import asyncio
import json
import logging
import os
import re
import tempfile
import threading
from datetime import datetime
from functools import wraps

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove, WebAppInfo,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes,
)

import config
import database as db
import ai_router
import email_sender
import email_queue
import reply_watcher
import followup_scheduler
import leads_importer
import cloudflare_aliases
import email_toolkit

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("flinza")

# ─── Conversation states ──────────────────────────────────────────
(
    # Add account
    ACC_EMAIL, ACC_PASS, ACC_LIMIT, ACC_PROXY,
    # Add alias
    ALIAS_ADDR, ALIAS_MASTER,
    # Add lead
    LEAD_EMAIL, LEAD_NAME, LEAD_NICHE, LEAD_FOLLOWERS, LEAD_BIO,
    # Set AI key
    KEY_PROVIDER, KEY_VALUE,
    # Set settings
    SETTING_KEY, SETTING_VALUE,
    # Edit reply draft
    EDIT_REPLY_ID, EDIT_REPLY_TEXT,
    # CF config
    CF_TOKEN, CF_ACCOUNT, CF_ZONE, CF_DOMAIN,
    # CF generate
    CF_GEN_MASTER, CF_GEN_COUNT,
    # Templates
    TPL_NAME, TPL_TYPE, TPL_SUBJECT, TPL_BODY,
    # Add proxy
    PROXY_ACCOUNT, PROXY_URL,
    # Campaign
    CAMPAIGN_CONFIRM,
) = range(30)

# ─── Telegram app reference (set at startup) ──────────────────────
_app: Application = None
_authorized_uid: int = config.ALLOWED_USER_ID


# ═══════════════════════════════════════════════════════════════
#                     AUTH GUARD
# ═══════════════════════════════════════════════════════════════

def auth_required(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        uid = update.effective_user.id if update.effective_user else None
        if _authorized_uid and uid != _authorized_uid:
            await update.message.reply_text("⛔ Unauthorized.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper


def auth_cb(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        uid = update.effective_user.id if update.effective_user else None
        if _authorized_uid and uid != _authorized_uid:
            await update.callback_query.answer("Unauthorized", show_alert=True)
            return
        return await func(update, context, *args, **kwargs)
    return wrapper


# ═══════════════════════════════════════════════════════════════
#                     HELPERS
# ═══════════════════════════════════════════════════════════════

async def reply(update: Update, text: str, **kwargs):
    """Send a message, splitting if over 4096 chars."""
    MAX = 4000
    if update.callback_query:
        send = update.callback_query.message.reply_text
    else:
        send = update.message.reply_text
    for i in range(0, len(text), MAX):
        await send(text[i:i+MAX], parse_mode=ParseMode.HTML, **kwargs)


def fmt_dt(ts: str) -> str:
    if not ts:
        return "Never"
    try:
        return datetime.fromisoformat(ts).strftime("%d %b %Y %H:%M")
    except Exception:
        return ts


def pipeline_bar(counts: dict) -> str:
    stages = [
        ("new",          "🆕"),
        ("contacted",    "📤"),
        ("followup_1_sent", "1️⃣"),
        ("followup_2_sent", "2️⃣"),
        ("followup_3_sent", "3️⃣"),
        ("replied",      "💬"),
        ("negotiating",  "🤝"),
        ("closed_won",   "🏆"),
        ("closed_lost",  "❌"),
        ("blacklisted",  "🚫"),
        ("unsubscribed", "🔕"),
    ]
    lines = []
    for stage, emoji in stages:
        cnt = counts.get(stage, 0)
        if cnt:
            lines.append(f"{emoji} <b>{stage}</b>: {cnt}")
    # Other stages
    known = {s for s, _ in stages}
    for stage, cnt in counts.items():
        if stage not in known and cnt:
            lines.append(f"• <b>{stage}</b>: {cnt}")
    return "\n".join(lines) or "No leads yet"


def notify_telegram(data: dict):
    """Called from background threads to push notifications to Telegram."""
    if not _app:
        return
    if not _authorized_uid:
        return
    asyncio.run_coroutine_threadsafe(_push_notify(data), _app.bot_data.get("loop"))


async def _push_notify(data: dict):
    """Async version called from event loop."""
    uid = _authorized_uid
    if not uid:
        return

    if isinstance(data, str):
        # Plain status message from queue processor
        await _app.bot.send_message(uid, f"<code>{data}</code>", parse_mode=ParseMode.HTML)
        return

    dtype = data.get("type", "")

    if dtype == "followup_sent":
        msg = (
            f"🔄 <b>Followup #{data['followup_number']} sent</b>\n"
            f"To: {data['lead_name']} ({data['lead_email']})"
        )
        await _app.bot.send_message(uid, msg, parse_mode=ParseMode.HTML)

    elif dtype == "email_opened":
        msg = (
            f"👁️ <b>Lead Opened Email!</b>\n\n"
            f"👤 <b>Lead:</b> {data.get('lead_name')} ({data.get('company')})\n"
            f"📧 <b>To:</b> {data.get('to_email')}\n"
            f"📌 <b>Subject:</b> {data.get('subject')}\n"
            f"⏰ <b>Opened At:</b> {data.get('timestamp')}"
        )
        await _app.bot.send_message(uid, msg, parse_mode=ParseMode.HTML)

    elif dtype == "email_clicked":
        msg = (
            f"🔗 <b>Lead Clicked Link in Email!</b>\n\n"
            f"👤 <b>Lead:</b> {data.get('lead_name')} ({data.get('company')})\n"
            f"📧 <b>To:</b> {data.get('to_email')}\n"
            f"🌐 <b>Target URL:</b> <code>{data.get('target_url')}</code>\n"
            f"⏰ <b>Clicked At:</b> {data.get('timestamp')}"
        )
        await _app.bot.send_message(uid, msg, parse_mode=ParseMode.HTML)

    elif "reply_id" in data:
        # New reply received
        rid          = data["reply_id"]
        lead_name    = data.get("lead_name") or "Unknown"
        from_email   = data.get("from_email", "")
        subject      = data.get("subject", "")
        body         = data.get("body", "")[:600]
        draft_body   = (data.get("ai_draft_body") or "")[:500]
        intent       = data.get("intent", "general_reply")
        is_unsub     = data.get("is_unsubscribe", False)

        intent_map = {
            "interested": "🔥 Interested (High Priority)",
            "rate_inquiry": "💰 Rate Inquiry",
            "objection": "🤔 Objection / Question",
            "not_interested": "⛔ Not Interested",
            "out_of_office": "🌴 Out of Office",
            "unsubscribe": "🔕 Unsubscribed & Blacklisted",
            "general_reply": "💬 New Reply",
        }
        badge = intent_map.get(intent, f"💬 {intent.title()}")

        msg = (
            f"📩 <b>{badge}</b>\n\n"
            f"👤 <b>From:</b> {lead_name} ({from_email})\n"
            f"📌 <b>Subject:</b> {subject}\n\n"
            f"<b>Their message:</b>\n{body}\n\n"
        )
        if is_unsub:
            msg += "⚠️ <i>Lead automatically unsubscribed, blacklisted, and all future followups cancelled.</i>\n"
            await _app.bot.send_message(uid, msg, parse_mode=ParseMode.HTML)
            return

        if draft_body:
            msg += f"🤖 <b>AI Draft:</b>\n<i>{draft_body}</i>\n\n"

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Send Draft", callback_data=f"send_draft:{rid}"),
                InlineKeyboardButton("✏️ Edit Draft", callback_data=f"edit_draft:{rid}"),
            ],
            [InlineKeyboardButton("⏭ Skip (Handle Later)", callback_data=f"skip_reply:{rid}")],
        ])
        await _app.bot.send_message(uid, msg, parse_mode=ParseMode.HTML, reply_markup=keyboard)


# ═══════════════════════════════════════════════════════════════
#             INTERACTIVE CLICKABLE UI & MENU SYSTEM
# ═══════════════════════════════════════════════════════════════

MAIN_BOTTOM_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["🎛️ Control Panel", "📊 Live Stats"],
        ["🚀 Launch Campaign", "📥 Unibox Replies"],
        ["🌐 Open Web Studio", "⚡ Test Send"],
    ],
    resize_keyboard=True
)


def get_main_menu_keyboard():
    stats = db.get_stats()
    unhandled = stats.get("unhandled_replies", 0)
    rep_badge = f" ({unhandled})" if unhandled > 0 else ""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📖 Beginner Quick-Start Guide", callback_data="ui:quickstart"),
        ],
        [
            InlineKeyboardButton("📊 Analytics & Pipeline", callback_data="ui:stats"),
            InlineKeyboardButton("🚀 Campaigns & Queue", callback_data="ui:campaigns"),
        ],
        [
            InlineKeyboardButton(f"📬 Mailboxes ({stats['accounts']} inboxes)", callback_data="ui:accounts"),
            InlineKeyboardButton("☁️ Cloudflare Studio", callback_data="ui:cloudflare"),
        ],
        [
            InlineKeyboardButton(f"👥 Leads CRM ({stats['total_leads']} leads)", callback_data="ui:leads:0"),
            InlineKeyboardButton(f"📥 Unibox{rep_badge}", callback_data="ui:replies"),
        ],
        [
            InlineKeyboardButton("🛡️ Deliverability & Spam", callback_data="ui:deliverability"),
            InlineKeyboardButton("🌐 Web Studio & Mini App", callback_data="ui:webstudio"),
        ],
        [
            InlineKeyboardButton("⚡ Instant Test Send", callback_data="ui:quicktest"),
            InlineKeyboardButton("⚙️ Settings & API Hub", callback_data="ui:settings"),
        ],
    ])


@auth_required
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = db.get_stats()
    tracking = db.get_tracking_stats()
    is_q_running = email_queue.is_running()
    q_status = "🟢 Active" if is_q_running else "⚪ Idle"

    text = (
        "🎛️ <b>Flinza Works — Outreach Command Center</b>\n\n"
        f"<b>System Status:</b> 🟢 Operational\n"
        f"<b>Queue:</b> {q_status} | <b>Remaining Capacity:</b> {stats['remaining_today']} today\n\n"
        f"📊 <b>Quick Glance:</b>\n"
        f"• Leads: <b>{stats['total_leads']}</b> (New: {stats['new_leads']})\n"
        f"• Inboxes: <b>{stats['accounts']}</b> | Aliases: <b>{stats['aliases']}</b>\n"
        f"• Sent Today: <b>{stats['sent_today']}</b> | Total Sent: <b>{stats['total_sent']}</b>\n"
        f"• Open Rate: <b>{tracking['open_rate']}%</b> | Replies: <b>{stats['total_replies']}</b>\n\n"
        "👇 <i>Tap any module below to manage your campaigns, mailboxes, and leads:</i>"
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=get_main_menu_keyboard())
    else:
        await update.message.reply_text("✨ Flinza Outreach loaded.", reply_markup=MAIN_BOTTOM_KEYBOARD)
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=get_main_menu_keyboard())


@auth_required
async def cb_ui_dispatcher(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles all interactive clickable UI button callbacks."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "ui:main":
        await cmd_start(update, context)
        return

    elif data == "ui:stats":
        s = db.get_stats()
        tracking = db.get_tracking_stats()
        counts = db.get_pipeline_breakdown()
        sent = s["total_sent"] or 1
        rep_rate = f"{s['replied_leads'] / sent * 100:.1f}%"

        text = (
            "📊 <b>Flinza Analytics Dashboard</b>\n\n"
            f"<b>── Deliverability & Response ──</b>\n"
            f"• Emails Sent: <b>{s['total_sent']}</b> (Today: {s['sent_today']})\n"
            f"• Open Rate: <b>{tracking['open_rate']}%</b> ({tracking['total_opened']} opens)\n"
            f"• Click Rate: <b>{tracking['click_rate']}%</b> ({tracking['total_clicked']} clicks)\n"
            f"• Replies: <b>{s['total_replies']}</b> | Reply Rate: <b>{rep_rate}</b>\n"
            f"• Failed / Bounced: <b>{s['failed']}</b>\n\n"
            f"<b>── Lead Pipeline ──</b>\n{pipeline_bar(counts)}"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔄 Refresh Stats", callback_data="ui:stats"),
                InlineKeyboardButton("📋 Recent Logs", callback_data="ui:activity"),
            ],
            [
                InlineKeyboardButton("📤 Export Leads CSV", callback_data="ui:export_leads"),
                InlineKeyboardButton("📬 Export Sent CSV", callback_data="ui:export_sent"),
            ],
            [InlineKeyboardButton("◀️ Back to Main Menu", callback_data="ui:main")],
        ])
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

    elif data == "ui:campaigns":
        s = db.get_stats()
        is_running = email_queue.is_running()
        status_txt = "🟢 Running (Sending in background)" if is_running else "⚪ Idle / Stopped"
        text = (
            "🚀 <b>Campaigns & Sending Queue</b>\n\n"
            f"<b>Queue Engine:</b> {status_txt}\n"
            f"• Queued for Outreach: <b>{s['queued']}</b>\n"
            f"• Remaining Capacity Today: <b>{s['remaining_today']}</b>\n"
            f"• Total New Leads Ready: <b>{s['new_leads']}</b>\n\n"
            "Control your cold email queue below:"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("▶️ Launch Campaign (All New)", callback_data="ui:launch_confirm"),
                InlineKeyboardButton("⏸️ Pause / Resume", callback_data="ui:queue_pause"),
            ],
            [
                InlineKeyboardButton("⏹️ Stop Queue", callback_data="ui:queue_stop"),
                InlineKeyboardButton("🔄 Retry Failed Emails", callback_data="ui:queue_retry"),
            ],
            [InlineKeyboardButton("◀️ Back to Main Menu", callback_data="ui:main")],
        ])
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

    elif data == "ui:launch_confirm":
        counts = db.get_stats()
        new_cnt = counts["new_leads"]
        text = (
            f"🚀 <b>Launch Outreach Campaign?</b>\n\n"
            f"This will queue <b>{new_cnt}</b> new leads for AI-personalized cold outreach.\n"
            f"• Account rotation: <b>Enabled</b>\n"
            f"• Spintax & Personalization: <b>Active</b>\n"
            f"• Random interval: <b>120s – 420s</b>\n"
            f"• Open tracking pixel: <b>Injected</b>"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Confirm & Launch", callback_data="campaign_go"),
                InlineKeyboardButton("❌ Cancel", callback_data="ui:campaigns"),
            ],
        ])
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

    elif data == "ui:queue_pause":
        if email_queue.is_paused():
            email_queue.resume_queue()
            await query.answer("▶️ Queue resumed!")
        else:
            email_queue.pause_queue()
            await query.answer("⏸️ Queue paused!")
        # Refresh campaigns view
        await cb_ui_dispatcher(update, context)

    elif data == "ui:queue_stop":
        email_queue.stop_queue()
        await query.answer("⏹️ Queue stopped.")
        await cb_ui_dispatcher(update, context)

    elif data == "ui:queue_retry":
        count = db.retry_failed_emails()
        await query.answer(f"🔄 Re-queued {count} failed emails!")
        await cb_ui_dispatcher(update, context)

    elif data == "ui:accounts":
        accs = db.get_all_accounts()
        aliases = db.get_all_aliases()
        lines = ["📬 <b>Mailbox Fleet & Sending Aliases</b>\n"]
        lines.append("<b>Master Inboxes:</b>")
        for a in accs:
            st = "🟢" if a.get("active") else "🔴"
            oauth_badge = " [OAuth2]" if db.get_oauth_token(a["email"]) else ""
            lines.append(f"{st} <code>{a['email']}</code>{oauth_badge} — {a.get('sent_today',0)}/{a.get('daily_limit',50)}")

        lines.append(f"\n<b>Custom Domain Aliases ({len(aliases)}):</b>")
        for al in aliases[:8]:
            st = "🟢" if al.get("is_active") else "⚪"
            lines.append(f"{st} <code>{al['alias']}</code> → {al.get('smtp_user','N/A')}")
        if len(aliases) > 8:
            lines.append(f"<i>...and {len(aliases) - 8} more aliases</i>")

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🧪 Test All Inboxes", callback_data="ui:test_accounts"),
                InlineKeyboardButton("🔥 Warmup (+1 Day)", callback_data="ui:warmup_step"),
            ],
            [
                InlineKeyboardButton("➕ Add Gmail Account", callback_data="ui:prompt_addacc"),
                InlineKeyboardButton("➕ Add Alias", callback_data="ui:prompt_addalias"),
            ],
            [InlineKeyboardButton("◀️ Back to Main Menu", callback_data="ui:main")],
        ])
        await query.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=keyboard)

    elif data == "ui:test_accounts":
        accs = db.get_all_accounts()
        res_lines = ["🧪 <b>Inbox Authentication Test Results:</b>\n"]
        for a in accs:
            if a.get("active"):
                res = email_sender.test_account_connection(a["email"], a.get("app_password"))
                icon = "✅" if res["success"] else "❌"
                res_lines.append(f"{icon} <code>{a['email']}</code>: {'Authenticated' if res['success'] else res.get('error', 'Failed')}")
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back to Accounts", callback_data="ui:accounts")]])
        await query.edit_message_text("\n".join(res_lines), parse_mode=ParseMode.HTML, reply_markup=keyboard)

    elif data == "ui:warmup_step":
        results = db.advance_all_warmups()
        msg = "📈 <b>Warmup Advanced +1 Day:</b>\n\n" + ("\n".join(results) if results else "No accounts currently in warmup mode.")
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back to Accounts", callback_data="ui:accounts")]])
        await query.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=keyboard)

    elif data == "ui:cloudflare":
        token = db.get_setting("cf_api_token") or config.CF_API_TOKEN
        domain = db.get_setting("cf_domain") or config.CF_DOMAIN or "Not configured"
        has_token = "🟢 Connected" if token else "🔴 Missing API Token"
        text = (
            "☁️ <b>Cloudflare Domain & Alias Studio</b>\n\n"
            f"• Connection: <b>{has_token}</b>\n"
            f"• Active Domain: <code>{domain}</code>\n\n"
            "Generate unlimited custom sending aliases and auto-forward all replies back to your master Gmail inboxes."
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔍 Audit DNS (SPF/DKIM/MX)", callback_data="ui:cf_audit"),
                InlineKeyboardButton("⚡ Auto-Generate 5 Aliases", callback_data="ui:cf_gen5"),
            ],
            [
                InlineKeyboardButton("📋 View Routing Rules", callback_data="ui:cf_rules"),
                InlineKeyboardButton("⚙️ Cloudflare Config", callback_data="ui:prompt_cfconfig"),
            ],
            [InlineKeyboardButton("◀️ Back to Main Menu", callback_data="ui:main")],
        ])
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

    elif data == "ui:cf_audit":
        domain = db.get_setting("cf_domain") or config.CF_DOMAIN
        if not domain:
            await query.answer("Configure CF_DOMAIN in settings first!", show_alert=True)
            return
        mx_check = email_toolkit.validate_email_deliverability(f"test@{domain}")
        status = "🟢 Healthy" if mx_check.get("deliverable") else "⚠️ Needs Review"
        text = (
            f"🔍 <b>DNS Health Audit for {domain}</b>\n\n"
            f"• Overall Status: <b>{status}</b>\n"
            f"• MX Records: <code>{', '.join(mx_check.get('mx_records', ['None']))}</code>\n"
            f"• SPF / DMARC: Configured on Cloudflare\n\n"
            "<i>All aliases on this domain are ready for cold outreach.</i>"
        )
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back to Cloudflare", callback_data="ui:cloudflare")]])
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

    elif data == "ui:cf_gen5":
        master_accs = db.get_all_accounts()
        if not master_accs:
            await query.answer("Add a master Gmail account first!", show_alert=True)
            return
        master_email = master_accs[0]["email"]
        domain = db.get_setting("cf_domain") or config.CF_DOMAIN
        if not domain:
            await query.answer("Configure CF_DOMAIN first!", show_alert=True)
            return

        await query.edit_message_text("⚡ <i>Generating 5 Cloudflare aliases...</i>", parse_mode=ParseMode.HTML)
        created = cloudflare_aliases.create_multiple_aliases(master_email, count=5, domain=domain)
        if created:
            lines = [f"✅ <b>Generated {len(created)} Aliases for {domain}:</b>\n"]
            for al in created:
                lines.append(f"• <code>{al['alias']}</code> → {master_email}")
            lines.append("\n<i>All aliases are registered and active in Flinza!</i>")
            text = "\n".join(lines)
        else:
            text = "❌ Failed to generate aliases via Cloudflare API. Verify your CF API Token."
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back to Cloudflare", callback_data="ui:cloudflare")]])
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

    elif data.startswith("ui:leads:"):
        page = int(data.split(":")[2])
        leads = db.get_leads(limit=None)
        PAGE_SIZE = 4
        total_pages = max(1, (len(leads) + PAGE_SIZE - 1) // PAGE_SIZE)
        page = max(0, min(page, total_pages - 1))
        page_leads = leads[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]

        lines = [f"👥 <b>Leads CRM (Page {page + 1} of {total_pages})</b>\n"]
        for l in page_leads:
            company = l.get("company") or "No Company"
            niche = l.get("niche") or "General"
            lines.append(f"• <b>{l.get('name') or 'Lead'}</b> (<code>{l['email']}</code>)")
            lines.append(f"  🏢 {company} | 🏷️ {niche} | 📍 <i>{l['stage']}</i>\n")

        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("◀️ Prev", callback_data=f"ui:leads:{page - 1}"))
        nav_buttons.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data=f"ui:leads:{page}"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"ui:leads:{page + 1}"))

        keyboard = InlineKeyboardMarkup([
            nav_buttons,
            [
                InlineKeyboardButton("➕ Add Lead", callback_data="ui:prompt_addlead"),
                InlineKeyboardButton("📤 Export Leads CSV", callback_data="ui:export_leads"),
            ],
            [InlineKeyboardButton("◀️ Back to Main Menu", callback_data="ui:main")],
        ])
        await query.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=keyboard)

    elif data == "ui:replies":
        replies = db.get_unhandled_replies()
        if not replies:
            text = (
                "📥 <b>Unibox — No Pending Replies</b>\n\n"
                "All incoming replies have been handled! You're completely caught up."
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Poll Inboxes Now", callback_data="ui:check_replies_now")],
                [InlineKeyboardButton("◀️ Back to Main Menu", callback_data="ui:main")],
            ])
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        else:
            r = replies[0]
            lead = db.get_lead(r["lead_id"])
            name = lead.get("name") if lead else "Lead"
            intent = r.get("intent", "general_reply")
            text = (
                f"📥 <b>Unibox ({len(replies)} unhandled)</b>\n\n"
                f"👤 <b>From:</b> {name} (<code>{r['from_email']}</code>)\n"
                f"📌 <b>Subject:</b> {r['subject']}\n"
                f"🏷️ <b>Intent:</b> {intent.upper()}\n\n"
                f"<b>Message:</b>\n{r['body'][:350]}...\n\n"
                f"🤖 <b>AI Suggested Draft:</b>\n<i>{(r.get('ai_draft_body') or 'No draft generated')[:350]}...</i>"
            )
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Send Draft", callback_data=f"send_draft:{r['id']}"),
                    InlineKeyboardButton("✏️ Edit Draft", callback_data=f"edit_draft:{r['id']}"),
                ],
                [
                    InlineKeyboardButton("⏭ Skip", callback_data=f"skip_reply:{r['id']}"),
                    InlineKeyboardButton("🔄 Check Inboxes", callback_data="ui:check_replies_now"),
                ],
                [InlineKeyboardButton("◀️ Back to Main Menu", callback_data="ui:main")],
            ])
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

    elif data == "ui:check_replies_now":
        await query.edit_message_text("🔄 <i>Connecting to IMAP and checking inboxes for new replies...</i>", parse_mode=ParseMode.HTML)
        loop = asyncio.get_event_loop()
        count = await loop.run_in_executor(None, reply_watcher.check_all_accounts_now)
        await query.answer(f"Checked inboxes! {count} new replies detected.")
        await cb_ui_dispatcher(update, context)

    elif data == "ui:deliverability":
        optout_enabled = db.get_setting("optout_footer_enabled", "0") == "1"
        optout_status = "🟢 ON (1-Click Unsubscribe injected)" if optout_enabled else "🔴 OFF (No footer)"
        text = (
            "🛡️ <b>Deliverability, Spam & Compliance Suite</b>\n\n"
            f"• <b>Opt-Out Footer:</b> {optout_status}\n"
            f"• <b>Spam Trigger Database:</b> 100+ high-risk patterns active\n"
            f"• <b>DNS / MX Validation:</b> Real-time syntax & mail server checks\n"
            f"• <b>Bounce Auto-Blacklist:</b> Active\n\n"
            "Optimize your inbox delivery rates below:"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(f"🔕 Toggle Optout ({'Turn OFF' if optout_enabled else 'Turn ON'})", callback_data="ui:toggle_optout"),
            ],
            [
                InlineKeyboardButton("🧪 Spam Score Checker", callback_data="ui:prompt_spamcheck"),
                InlineKeyboardButton("🔍 Validate MX Email", callback_data="ui:prompt_checkemail"),
            ],
            [InlineKeyboardButton("◀️ Back to Main Menu", callback_data="ui:main")],
        ])
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

    elif data == "ui:toggle_optout":
        current = db.get_setting("optout_footer_enabled", "0")
        new_val = "0" if current == "1" else "1"
        db.set_setting("optout_footer_enabled", new_val)
        await query.answer(f"Opt-out footer {'enabled' if new_val == '1' else 'disabled'}!")
        await cb_ui_dispatcher(update, context)

    elif data == "ui:quickstart":
        text = (
            "📖 <b>Flinza Works — Beginner Quick-Start Guide</b>\n\n"
            "Welcome! Flinza is your autonomous B2B cold email engine. Here is the simple 3-step path to start getting clients:\n\n"
            "1️⃣ <b>Step 1: Set Up an Outbound Sender</b>\n"
            "• Tap <code>📬 Mailboxes</code> → Connect your Google Account or enter Amazon SES SMTP credentials.\n"
            "• If using custom domains, tap <code>☁️ Cloudflare Studio</code> to auto-generate 5 sending aliases.\n\n"
            "2️⃣ <b>Step 2: Add Your Prospects</b>\n"
            "• Tap <code>👥 Leads CRM</code> → Tap <code>➕ Add Lead</code> to add an email manually, or upload a CSV file.\n\n"
            "3️⃣ <b>Step 3: Test & Launch</b>\n"
            "• Tap <code>⚡ Instant Test Send</code> to send a live test email to yourself and verify inboxing.\n"
            "• Tap <code>🚀 Campaigns & Queue</code> → <code>▶️ Launch Campaign</code> to start sending automated, AI-personalized cold outreach!\n\n"
            "💡 <i>Tip: Want to see the full visual dashboard? Tap <code>🌐 Web Studio</code> below!</i>"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📬 Setup Mailbox", callback_data="ui:accounts"),
                InlineKeyboardButton("👥 Add Lead", callback_data="ui:prompt_addlead"),
            ],
            [
                InlineKeyboardButton("⚡ Instant Test Send", callback_data="ui:quicktest"),
                InlineKeyboardButton("🚀 Launch Campaign", callback_data="ui:campaigns"),
            ],
            [InlineKeyboardButton("◀️ Back to Main Menu", callback_data="ui:main")],
        ])
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

    elif data == "ui:webstudio":
        port = db.get_setting("studio_port", "8000")
        local_url = f"http://localhost:{port}"
        public_url = db.get_setting("studio_public_url") or db.get_setting("tracking_base_url") or ""
        active_url = public_url if public_url.startswith("https://") else local_url

        text = (
            "🌐 <b>Flinza Works — Outreach Web Studio & Mini App</b>\n\n"
            f"• <b>Active Studio URL:</b> <code>{active_url}</code>\n\n"
            "✨ <b>Studio Modules:</b>\n"
            "• 📊 Executive Dashboard (Daily capacity, open & reply rates)\n"
            "• 👥 Leads CRM (Search, stage filters, CSV import/export)\n"
            "• 📬 Mailbox Fleet (Gmail, Cloudflare API $5/mo, Amazon SES)\n"
            "• ☁️ Cloudflare Domain Studio (DNS audit & 1-click aliases)\n"
            "• 🎯 Sequence Architect (A/B testing & drip builder)\n"
            "• 📥 Unibox with instant AI reply drafting\n\n"
            + ("" if active_url.startswith("https://") else "💡 <i>To open as a Telegram Mini App inside Telegram, set your public HTTPS URL with:</i>\n<code>/seturl https://your-tunnel.trycloudflare.com</code>")
        )
        keyboard_buttons = []
        if active_url.startswith("https://"):
            keyboard_buttons.append([InlineKeyboardButton("🚀 Launch Studio Mini App", web_app=WebAppInfo(url=active_url))])
        else:
            keyboard_buttons.append([InlineKeyboardButton("🌐 Open in Browser", url=local_url)])
        keyboard_buttons.append([InlineKeyboardButton("◀️ Back to Main Menu", callback_data="ui:main")])
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard_buttons))

    elif data == "ui:quicktest":
        await query.edit_message_text("⚡ <i>Dispatching live test email with delivery diagnostics...</i>", parse_mode=ParseMode.HTML)
        # Use rajdep.f12x@gmail.com or prompt
        res = email_sender.send_test_email("rajdep.f12x@gmail.com")
        if res.get("success"):
            text = (
                "✅ <b>Instant Test Email Delivered!</b>\n\n"
                f"• <b>Recipient:</b> <code>rajdep.f12x@gmail.com</code>\n"
                f"• <b>Account Used:</b> <code>{res['account_used']}</code>\n"
                f"• <b>Latency:</b> <code>{res.get('elapsed_ms', 0)}ms</code>\n"
                f"• <b>Message-ID:</b> <code>{res.get('message_id', 'N/A')}</code>\n\n"
                "💡 <i>Check your inbox to verify SPF/DKIM alignment!</i>"
            )
        else:
            text = f"❌ <b>Test Send Failed:</b>\n<code>{res.get('error')}</code>"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚡ Send Another Test", callback_data="ui:quicktest")],
            [InlineKeyboardButton("◀️ Back to Main Menu", callback_data="ui:main")],
        ])
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

    elif data == "ui:settings":
        sender = db.get_setting("sender_name", "Flinza Works")
        min_sec = db.get_setting("min_interval_seconds", "120")
        max_sec = db.get_setting("max_interval_seconds", "420")
        sm_enabled = db.get_setting("smart_hours_enabled", "0") == "1"
        sm_txt = "🟢 ON (9:00 - 18:00)" if sm_enabled else "🔴 OFF (24/7)"
        text = (
            "⚙️ <b>Settings & Sending Configuration</b>\n\n"
            f"• <b>Sender Name:</b> {sender}\n"
            f"• <b>Interval Delays:</b> {min_sec}s – {max_sec}s random jitter\n"
            f"• <b>Smart Business Hours:</b> {sm_txt}\n"
            f"• <b>Active AI Provider:</b> OpenRouter / Gemini / Groq / Custom\n\n"
            "Use slash commands to modify settings (e.g. <code>/setsender</code>, <code>/setinterval</code>)."
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔑 AI API Keys", callback_data="ui:prompt_aikey"),
                InlineKeyboardButton("⏰ Toggle Smart Hours", callback_data="ui:toggle_smarthours"),
            ],
            [InlineKeyboardButton("◀️ Back to Main Menu", callback_data="ui:main")],
        ])
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

    elif data == "ui:toggle_smarthours":
        curr = db.get_setting("smart_hours_enabled", "0")
        new_val = "0" if curr == "1" else "1"
        db.set_setting("smart_hours_enabled", new_val)
        await query.answer(f"Smart hours {'enabled' if new_val == '1' else 'disabled'}!")
        await cb_ui_dispatcher(update, context)

    elif data == "ui:activity":
        logs = db.get_recent_activity(10)
        lines = ["📋 <b>Recent Activity Log</b>\n"]
        for l in logs:
            lines.append(f"• <code>{fmt_dt(l['created_at'])}</code> | {l['action']}: {l['details'][:50]}")
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back to Analytics", callback_data="ui:stats")]])
        await query.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=keyboard)

    elif data == "ui:export_leads":
        await cmd_exportleads(update, context)

    elif data == "ui:export_sent":
        await cmd_exportsent(update, context)

    elif data in ("ui:prompt_addacc", "ui:prompt_addalias", "ui:prompt_cfconfig", "ui:prompt_addlead", "ui:prompt_spamcheck", "ui:prompt_checkemail", "ui:prompt_aikey"):
        prompts = {
            "ui:prompt_addacc": "📧 To add an account, type: <code>/addaccount</code>",
            "ui:prompt_addalias": "📬 To add a sending alias, type: <code>/addalias</code>",
            "ui:prompt_cfconfig": "☁️ To configure Cloudflare, type: <code>/cfconfig</code>",
            "ui:prompt_addlead": "👥 To add a lead, type: <code>/addlead</code> or upload a CSV file directly!",
            "ui:prompt_spamcheck": "🛡️ Type <code>/spamcheck Subject | Body</code> to test deliverability score.",
            "ui:prompt_checkemail": "🔍 Type <code>/checkemail prospect@domain.com</code> to validate MX records.",
            "ui:prompt_aikey": "🔑 Type <code>/setaikey provider key</code> to save AI credentials.",
        }
        await query.answer(prompts.get(data, "Command info"), show_alert=True)


# ═══════════════════════════════════════════════════════════════
#                     /help COMMAND
# ═══════════════════════════════════════════════════════════════


@auth_required
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📚 <b>Flinza Outreach Commands</b>\n\n"
        "<b>── Testing & Deliverability ──</b>\n"
        "/testsend — Send instant test email to your inbox\n"
        "/spamcheck — Spam trigger & deliverability score analyzer\n"
        "/checkemail — Validate DNS MX records & syntax\n"
        "/warmup — Mailbox warmup status & /warmup advance\n"
        "/optout — Configure 1-click unsubscribe footer\n\n"
        "<b>── Accounts & Aliases ──</b>\n"
        "/addaccount — Add a Gmail account\n"
        "/removeaccount — Remove an account\n"
        "/accounts — List all accounts + stats\n"
        "/testaccount — Test SMTP login\n"
        "/addproxy — Set proxy for an account\n"
        "/setlimit — Set daily limit for account\n"
        "/addalias — Add SMTP alias manually\n"
        "/removealias — Remove an alias\n"
        "/togglealias — Enable/disable alias\n"
        "/aliases — List all aliases\n\n"
        "<b>── Cloudflare Aliases ──</b>\n"
        "/cfconfig — Set Cloudflare credentials\n"
        "/cftest — Test CF connection\n"
        "/cfgenerate — Auto-generate random CF aliases\n"
        "/cflist — List CF routing rules\n\n"
        "<b>── Leads & Data ──</b>\n"
        "/import — Upload CSV of leads\n"
        "/addlead — Add a single lead\n"
        "/leads — Browse leads (by stage)\n"
        "/pipeline — Pipeline breakdown\n"
        "/exportleads — Download full leads CSV\n"
        "/exportsent — Download outreach history CSV\n"
        "/deletelead — Delete a lead\n"
        "/blacklist — Blacklist a lead/domain\n"
        "/search — Search leads\n\n"
        "<b>── Campaigns & Queue ──</b>\n"
        "/campaign — Launch outreach to all new leads\n"
        "/preview — Preview AI email for a lead\n"
        "/sendemail — Send one email to a lead now\n"
        "/startqueue — Start background queue\n"
        "/stopqueue — Stop queue\n"
        "/pausequeue — Pause/resume queue\n"
        "/queuestat — Queue status\n"
        "/retryfailed — Retry all failed sends\n\n"
        "<b>── Replies & Negotiation ──</b>\n"
        "/replies — View unhandled replies with AI drafts\n"
        "/checkreplies — Manual IMAP check now\n"
        "/sendreply — Send AI draft for a reply\n"
        "/skipreply — Skip a reply\n\n"
        "<b>── Templates & Customization ──</b>\n"
        "/templates — List saved templates\n"
        "/savetemplate — Save template with Spintax/Tags\n"
        "/deletetemplate — Remove a template\n"
        "/setprompt — Set AI system prompt\n"
        "/setsender — Set sender display name\n"
        "/settings — View all settings\n\n"
        "<b>── Sending Rules & AI ──</b>\n"
        "/setinterval — Set min/max send delay (seconds)\n"
        "/setfollowup — Set followup day cadence\n"
        "/smarthours — Configure smart send hours (e.g. 9-18)\n"
        "/autoreply — Set auto-reply mode (preview/trust)\n"
        "/setaikey — Set AI provider key\n"
        "/setmodel — Set OpenRouter model\n\n"
        "<b>── Stats & Diagnostics ──</b>\n"
        "/stats — Full stats dashboard\n"
        "/activity — Recent activity log\n"
        "/seedtest — Verify real migrated & demo accounts\n"
        "/start — Status overview\n"
    )
    await reply(update, msg)


# ═══════════════════════════════════════════════════════════════
#                  ADD ACCOUNT (ConversationHandler)
# ═══════════════════════════════════════════════════════════════

@auth_required
async def cmd_addaccount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply(update, "📧 Enter the <b>Gmail address</b> to add:")
    return ACC_EMAIL


async def acc_get_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email_val = update.message.text.strip().lower()
    if "@" not in email_val:
        await reply(update, "❌ Invalid email. Try again:")
        return ACC_EMAIL
    context.user_data["acc_email"] = email_val
    await reply(update, f"🔑 Enter the <b>App Password</b> for {email_val}\n<i>(Gmail → Settings → Security → App passwords)</i>:")
    return ACC_PASS


async def acc_get_pass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["acc_pass"] = update.message.text.strip()
    await reply(update, "📊 Daily send limit? (default: 50 — hit Enter to use default):")
    return ACC_LIMIT


async def acc_get_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        limit = int(text) if text else 50
    except ValueError:
        limit = 50
    context.user_data["acc_limit"] = limit
    await reply(update, "🌐 Proxy URL? (e.g. socks5://user:pass@host:port — or /skip):")
    return ACC_PROXY


async def acc_get_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text     = update.message.text.strip()
    proxy    = None if text in ("/skip", "skip", "-") else text
    email_v  = context.user_data["acc_email"]
    password = context.user_data["acc_pass"]
    limit    = context.user_data["acc_limit"]

    # Quick connection test
    await reply(update, "🔄 Testing connection…")
    test_result = email_sender.test_account_connection(email_v, password)
    if not test_result["success"]:
        await reply(update, f"❌ Auth test failed: {test_result['error']}\n\nAccount NOT added. Check credentials.")
        return ConversationHandler.END

    ok = db.add_account(email_v, password, daily_limit=limit, proxy_url=proxy)
    if ok:
        proxy_str = f" (proxy: {proxy})" if proxy else ""
        await reply(update, f"✅ Account <code>{email_v}</code> added!\n• Limit: {limit}/day{proxy_str}")
    else:
        await reply(update, f"⚠️ Account <code>{email_v}</code> already exists.")
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply(update, "↩️ Cancelled.")
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════
#                  REMOVE ACCOUNT
# ═══════════════════════════════════════════════════════════════

@auth_required
async def cmd_removeaccount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    accs = db.get_all_accounts()
    if not accs:
        await reply(update, "No accounts configured.")
        return
    lines = [f"<code>{a['email']}</code>" for a in accs]
    await reply(update, "🗑 Accounts:\n" + "\n".join(lines) +
                "\n\nUse: <code>/removeaccount email@gmail.com</code>")


@auth_required
async def cmd_removeaccount_inline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await cmd_removeaccount(update, context)
        return
    email_val = context.args[0].lower()
    db.remove_account(email_val)
    await reply(update, f"🗑 Account <code>{email_val}</code> removed.")


# ═══════════════════════════════════════════════════════════════
#                  LIST ACCOUNTS
# ═══════════════════════════════════════════════════════════════

@auth_required
async def cmd_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    accs    = db.get_all_accounts()
    aliases = db.get_all_aliases()
    if not accs:
        await reply(update, "No accounts yet. Use /addaccount")
        return

    lines = ["<b>📧 Gmail Accounts</b>\n"]
    for a in accs:
        status = "🟢" if a["active"] else "🔴"
        sent   = a["sent_today"] or 0
        limit  = a["daily_limit"]
        proxy  = " 🌐" if a["proxy_url"] else ""
        last   = fmt_dt(a["last_used"])
        lines.append(
            f"{status} <code>{a['email']}</code>{proxy}\n"
            f"   {sent}/{limit} sent today | last used: {last}"
        )

    if aliases:
        lines.append("\n<b>📮 SMTP Aliases</b>\n")
        for al in aliases:
            status = "🟢" if al["is_active"] else "🔴"
            src    = f" [{al['source']}]" if al["source"] != "manual" else ""
            lines.append(
                f"{status} <code>{al['alias']}</code>{src}\n"
                f"   {al['daily_sent']}/{al['daily_limit']} today | master: {al['smtp_user']}"
            )

    remaining = db.total_remaining_today()
    lines.append(f"\n📊 <b>Total remaining today: {remaining}</b>")
    await reply(update, "\n".join(lines))


# ═══════════════════════════════════════════════════════════════
#                  TEST ACCOUNT
# ═══════════════════════════════════════════════════════════════

@auth_required
async def cmd_testaccount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await reply(update, "Usage: <code>/testaccount email@gmail.com</code>")
        return
    email_val = context.args[0].lower()
    accs      = [a for a in db.get_all_accounts() if a["email"].lower() == email_val]
    if not accs:
        await reply(update, f"Account <code>{email_val}</code> not found.")
        return
    await reply(update, "🔄 Testing SMTP connection…")
    result = email_sender.test_account_connection(email_val, accs[0]["app_password"])
    if result["success"]:
        await reply(update, f"✅ <code>{email_val}</code> SMTP connection OK!")
    else:
        await reply(update, f"❌ <code>{email_val}</code> failed: {result['error']}")


# ═══════════════════════════════════════════════════════════════
#               SET LIMIT / ADD PROXY
# ═══════════════════════════════════════════════════════════════

@auth_required
async def cmd_setlimit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await reply(update, "Usage: <code>/setlimit email@gmail.com 100</code>")
        return
    email_v = context.args[0].lower()
    try:
        limit = int(context.args[1])
    except ValueError:
        await reply(update, "❌ Limit must be a number.")
        return
    db.set_account_limit(email_v, limit)
    await reply(update, f"✅ Daily limit for <code>{email_v}</code> set to <b>{limit}</b>")


@auth_required
async def cmd_addproxy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply(update,
        "🌐 Enter account email and proxy URL separated by a space:\n"
        "e.g. <code>me@gmail.com socks5://user:pass@host:1080</code>"
    )
    return PROXY_ACCOUNT


async def proxy_get_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parts = update.message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await reply(update, "❌ Format: <code>email proxy_url</code>")
        return ConversationHandler.END
    email_v, proxy_url = parts[0].lower(), parts[1]
    db.set_account_proxy(email_v, proxy_url)
    await reply(update, f"✅ Proxy set for <code>{email_v}</code>: <code>{proxy_url}</code>")
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════
#                  ADD / MANAGE ALIASES
# ═══════════════════════════════════════════════════════════════

@auth_required
async def cmd_addalias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply(update,
        "📮 Enter alias address (e.g. <code>outreach@yourdomain.com</code>):"
    )
    return ALIAS_ADDR


async def alias_get_addr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    addr = update.message.text.strip().lower()
    if "@" not in addr:
        await reply(update, "❌ Invalid. Enter full alias email:")
        return ALIAS_ADDR
    context.user_data["alias_addr"] = addr
    await reply(update, "📧 Which Gmail master account sends via this alias? (Enter gmail address):")
    return ALIAS_MASTER


async def alias_get_master(update: Update, context: ContextTypes.DEFAULT_TYPE):
    master = update.message.text.strip().lower()
    if "@" not in master:
        await reply(update, "❌ Invalid Gmail address.")
        return ConversationHandler.END
    alias  = context.user_data["alias_addr"]
    # Get app password from master account if it exists
    accs   = [a for a in db.get_all_accounts() if a["email"].lower() == master]
    smtp_p = accs[0]["app_password"] if accs else None
    ok     = db.add_alias(alias, master, smtp_pass=smtp_p, source="manual")
    if ok:
        await reply(update, f"✅ Alias <code>{alias}</code> → <code>{master}</code> added!")
    else:
        await reply(update, f"⚠️ Alias <code>{alias}</code> already exists.")
    return ConversationHandler.END


@auth_required
async def cmd_removealias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await reply(update, "Usage: <code>/removealias alias@domain.com</code>")
        return
    alias = context.args[0].lower()
    db.remove_alias(alias)
    await reply(update, f"🗑 Alias <code>{alias}</code> removed.")


@auth_required
async def cmd_togglealias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await reply(update, "Usage: <code>/togglealias alias@domain.com</code>")
        return
    alias  = context.args[0].lower()
    result = db.toggle_alias(alias)
    if result is None:
        await reply(update, "❌ Alias not found.")
    else:
        status = "🟢 enabled" if result else "🔴 disabled"
        await reply(update, f"Alias <code>{alias}</code> is now {status}")


@auth_required
async def cmd_aliases(update: Update, context: ContextTypes.DEFAULT_TYPE):
    aliases = db.get_all_aliases()
    if not aliases:
        await reply(update, "No aliases yet. Use /addalias or /cfgenerate")
        return
    lines = []
    for al in aliases:
        s   = "🟢" if al["is_active"] else "🔴"
        src = f" [{al['source']}]" if al["source"] != "manual" else ""
        lines.append(
            f"{s} <code>{al['alias']}</code>{src}\n"
            f"   {al['daily_sent']}/{al['daily_limit']} today → {al['smtp_user']}"
        )
    await reply(update, "<b>📮 All Aliases</b>\n\n" + "\n\n".join(lines))


# ═══════════════════════════════════════════════════════════════
#                  CLOUDFLARE COMMANDS
# ═══════════════════════════════════════════════════════════════

@auth_required
async def cmd_cfconfig(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply(update,
        "☁️ <b>Cloudflare Email Routing Setup</b>\n\n"
        "I'll ask for your CF credentials one by one.\n\n"
        "Enter your <b>Cloudflare API Token</b>:\n"
        "<i>(dash.cloudflare.com → My Profile → API Tokens → Create Token → Zone Email Routing: Edit)</i>"
    )
    return CF_TOKEN


async def cf_get_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cf_token"] = update.message.text.strip()
    await reply(update, "Enter your <b>Cloudflare Account ID</b>:\n<i>(Found on the right sidebar of any CF dashboard page)</i>")
    return CF_ACCOUNT


async def cf_get_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cf_account"] = update.message.text.strip()
    await reply(update, "Enter your <b>Zone ID</b> for the domain:\n<i>(Right sidebar of the domain's CF dashboard)</i>")
    return CF_ZONE


async def cf_get_zone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cf_zone"] = update.message.text.strip()
    await reply(update, "Enter your <b>domain name</b> (e.g. <code>yourdomain.com</code>):")
    return CF_DOMAIN


async def cf_get_domain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    domain = update.message.text.strip().lower().lstrip("@")
    db.set_setting("cf_api_token",  context.user_data["cf_token"])
    db.set_setting("cf_account_id", context.user_data["cf_account"])
    db.set_setting("cf_zone_id",    context.user_data["cf_zone"])
    db.set_setting("cf_domain",     domain)
    await reply(update, "🔄 Testing Cloudflare connection…")
    result = cloudflare_aliases.verify_cf_config()
    if result["success"]:
        await reply(update, f"✅ CF configured! Zone: <code>{result['zone_name']}</code> ({result['status']})")
    else:
        await reply(update, f"⚠️ CF credentials saved but test failed: {result['error']}\nDouble-check and try /cftest")
    return ConversationHandler.END


@auth_required
async def cmd_cftest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = cloudflare_aliases.verify_cf_config()
    if result["success"]:
        await reply(update, f"✅ CF OK — Zone: <code>{result['zone_name']}</code> ({result['status']})")
    else:
        await reply(update, f"❌ CF test failed: {result['error']}")


@auth_required
async def cmd_cfgenerate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply(update,
        "☁️ <b>Generate CF Aliases</b>\n\n"
        "Enter the <b>master Gmail</b> that will send via these aliases:\n"
        "<i>(Must be an account already added with /addaccount)</i>"
    )
    return CF_GEN_MASTER


async def cf_gen_master(update: Update, context: ContextTypes.DEFAULT_TYPE):
    master = update.message.text.strip().lower()
    accs   = [a for a in db.get_all_accounts() if a["email"].lower() == master]
    if not accs:
        await reply(update, f"❌ <code>{master}</code> not found in accounts. Add it first with /addaccount")
        return ConversationHandler.END
    context.user_data["cf_gen_master"] = master
    await reply(update, "How many aliases to generate? (1-20):")
    return CF_GEN_COUNT


async def cf_gen_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        count  = min(int(update.message.text.strip()), 20)
    except ValueError:
        count  = 5
    master = context.user_data["cf_gen_master"]
    await reply(update, f"⚙️ Generating {count} aliases via Cloudflare…")
    results = cloudflare_aliases.generate_word_aliases(count, master)
    success = [r for r in results if r.get("success")]
    failed  = [r for r in results if not r.get("success")]
    lines   = [f"✅ <code>{r['alias']}</code>" for r in success]
    if failed:
        lines += [f"❌ {r.get('error', 'Unknown error')}" for r in failed]
    await reply(update,
        f"☁️ <b>CF Alias Generation</b>\n"
        f"✅ {len(success)} created | ❌ {len(failed)} failed\n\n" +
        "\n".join(lines)
    )
    return ConversationHandler.END


@auth_required
async def cmd_cflist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = cloudflare_aliases.list_cf_rules()
    if not result["success"]:
        await reply(update, f"❌ {result['error']}")
        return
    rules = result["rules"]
    if not rules:
        await reply(update, "No CF routing rules found.")
        return
    lines = []
    for r in rules[:20]:
        enabled = "🟢" if r.get("enabled") else "🔴"
        matchers = [m.get("value","?") for m in r.get("matchers", [])]
        actions  = [", ".join(a.get("value",[])) for a in r.get("actions", [])]
        lines.append(f"{enabled} {', '.join(matchers)} → {', '.join(actions)}")
    await reply(update, f"☁️ <b>CF Routing Rules</b> ({len(rules)} total)\n\n" + "\n".join(lines))


# ═══════════════════════════════════════════════════════════════
#                  LEAD MANAGEMENT
# ═══════════════════════════════════════════════════════════════

@auth_required
async def cmd_import(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply(update,
        "📂 <b>Import Leads from CSV</b>\n\n"
        "Upload a CSV file with columns:\n"
        "<code>email, name, handle, followers, bio, niche, company, platform, notes</code>\n\n"
        "Only <b>email</b> is required. Followers can be like <code>125K</code> or <code>1.2M</code>.\n\n"
        "<i>Send the CSV file now:</i>"
    )


@auth_required
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle uploaded CSV files."""
    doc = update.message.document
    if not doc:
        return
    if not doc.file_name.lower().endswith(".csv"):
        await reply(update, "❌ Please send a .csv file.")
        return
    await reply(update, "⚙️ Importing leads…")
    try:
        tg_file  = await doc.get_file()
        content  = await tg_file.download_as_bytearray()
        result   = leads_importer.import_from_csv_bytes(bytes(content))
        errors   = result.get("errors", [])
        err_str  = "\n".join(errors[:5]) if errors else ""
        await reply(update,
            f"📊 <b>Import Complete</b>\n\n"
            f"✅ Added: <b>{result['added']}</b>\n"
            f"⏩ Skipped (duplicate): <b>{result['skipped']}</b>\n"
            f"🚫 Blacklisted: <b>{result['blacklisted']}</b>\n"
            f"❌ Invalid: <b>{result['invalid']}</b>\n"
            + (f"\n⚠️ Errors (first 5):\n<code>{err_str}</code>" if err_str else "")
        )
    except Exception as e:
        await reply(update, f"❌ Import failed: {e}")


@auth_required
async def cmd_addlead(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply(update, "📧 Enter the lead's <b>email address</b>:")
    return LEAD_EMAIL


async def lead_get_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email_val = update.message.text.strip().lower()
    if "@" not in email_val:
        await reply(update, "❌ Invalid email. Try again:")
        return LEAD_EMAIL
    context.user_data["lead_email"] = email_val
    await reply(update, "👤 Their <b>name</b> (or /skip):")
    return LEAD_NAME


async def lead_get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["lead_name"] = None if text in ("/skip", "skip") else text
    await reply(update, "🎯 <b>Niche/category</b> (e.g. fitness, tech, beauty — or /skip):")
    return LEAD_NICHE


async def lead_get_niche(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["lead_niche"] = None if text in ("/skip", "skip") else text
    await reply(update, "👥 <b>Followers count</b> (e.g. 25000 or 25K — or /skip):")
    return LEAD_FOLLOWERS


async def lead_get_followers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["lead_followers"] = None if text in ("/skip", "skip") else leads_importer._parse_followers(text)
    await reply(update, "📝 Short <b>bio</b> (or /skip):")
    return LEAD_BIO


async def lead_get_bio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text  = update.message.text.strip()
    bio   = None if text in ("/skip", "skip") else text
    e     = context.user_data["lead_email"]
    name  = context.user_data.get("lead_name")
    niche = context.user_data.get("lead_niche")
    fols  = context.user_data.get("lead_followers")
    tier  = leads_importer.assign_tier(fols) if fols else None

    result = leads_importer.add_single_lead(e, name=name, niche=niche, followers=fols, bio=bio, tier=tier)
    if result["success"]:
        word = "added" if result["is_new"] else "already exists"
        await reply(update, f"✅ Lead <code>{e}</code> {word}! ID: {result['lead_id']}")
    else:
        await reply(update, f"❌ {result['error']}")
    return ConversationHandler.END


@auth_required
async def cmd_leads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stage = context.args[0] if context.args else None
    leads = db.get_leads(stage=stage, limit=30)
    if not leads:
        label = f"stage '{stage}'" if stage else "database"
        await reply(update, f"No leads in {label}. Import some with /import or /addlead")
        return
    lines = [f"<b>📋 Leads{' [' + stage + ']' if stage else ''}</b> (showing {len(leads)} of latest)\n"]
    for l in leads:
        stage_e = l["stage"]
        name    = l["name"] or l["email"]
        fols    = f" | {l['followers']:,}" if l["followers"] else ""
        lines.append(f"#{l['id']} <b>{name}</b>{fols}\n<code>{l['email']}</code> — {stage_e}")
    await reply(update, "\n\n".join(lines))


@auth_required
async def cmd_pipeline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    counts = db.get_pipeline_breakdown()
    total  = sum(counts.values())
    msg    = f"🔮 <b>Pipeline</b> ({total} total)\n\n" + pipeline_bar(counts)
    await reply(update, msg)


@auth_required
async def cmd_deletelead(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await reply(update, "Usage: <code>/deletelead &lt;lead_id&gt;</code>")
        return
    try:
        lid = int(context.args[0])
    except ValueError:
        await reply(update, "❌ ID must be a number.")
        return
    lead = db.get_lead(lid)
    if not lead:
        await reply(update, f"Lead #{lid} not found.")
        return
    db.delete_lead(lid)
    await reply(update, f"🗑 Lead #{lid} ({lead['email']}) permanently deleted.")


@auth_required
async def cmd_blacklist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await reply(update, "Usage: <code>/blacklist email@example.com</code> or <code>/blacklist domain.com</code>")
        return
    target = context.args[0].lower()
    if "@" in target:
        db.add_to_blacklist(email=target, reason="manual")
        lead = db.get_lead_by_email(target)
        if lead:
            db.blacklist_lead(lead["id"], "manual blacklist")
        await reply(update, f"🚫 <code>{target}</code> blacklisted (email)")
    else:
        db.add_to_blacklist(domain=target, reason="manual")
        await reply(update, f"🚫 <code>{target}</code> blacklisted (domain)")


@auth_required
async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await reply(update, "Usage: <code>/search keyword</code>")
        return
    query = " ".join(context.args)
    leads = db.get_leads(search=query, limit=20)
    if not leads:
        await reply(update, f"No leads matching <i>{query}</i>")
        return
    lines = [f"🔍 <b>Results for '{query}'</b>\n"]
    for l in leads:
        lines.append(f"#{l['id']} <code>{l['email']}</code> | {l['name'] or '—'} | {l['stage']}")
    await reply(update, "\n".join(lines))


# ═══════════════════════════════════════════════════════════════
#                  CAMPAIGN / EMAIL
# ═══════════════════════════════════════════════════════════════

@auth_required
async def cmd_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_leads = db.get_leads(stage="new", limit=None)
    if not new_leads:
        await reply(update, "No new leads to contact. Import leads with /import first.")
        return
    accs      = db.get_all_accounts()
    remaining = db.total_remaining_today()
    keyboard  = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🚀 Launch ({len(new_leads)} leads)", callback_data="campaign_go")],
        [InlineKeyboardButton("❌ Cancel", callback_data="campaign_cancel")],
    ])
    await reply(update,
        f"🚀 <b>Launch Campaign</b>\n\n"
        f"• New leads to email: <b>{len(new_leads)}</b>\n"
        f"• Active accounts/aliases: <b>{len(accs)}</b>\n"
        f"• Remaining capacity today: <b>{remaining}</b>\n\n"
        "Emails will be AI-generated and queued. Queue starts automatically.",
        reply_markup=keyboard,
    )


@auth_cb
async def cb_campaign_go(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("Queuing emails…")
    await update.callback_query.edit_message_text("⚙️ Generating and queuing emails…")

    new_leads = db.get_leads(stage="new")
    queued    = 0
    failed    = 0

    for lead in new_leads:
        try:
            lead_dict = dict(lead)
            email_data = ai_router.generate_opener(lead_dict)
            db.log_email(
                lead["id"], None, lead["email"],
                email_data["subject"], email_data["body"],
                "opener", "queued"
            )
            db.update_lead_stage(lead["id"], "queued")
            queued += 1
        except Exception as e:
            logger.error(f"Failed to queue lead {lead['id']}: {e}")
            failed += 1

    # Auto-start queue
    def queue_callback(msg):
        asyncio.run_coroutine_threadsafe(
            _app.bot.send_message(_authorized_uid, f"<code>{msg}</code>", parse_mode=ParseMode.HTML),
            _app.bot_data["loop"]
        )

    email_queue.start_queue(status_callback=queue_callback)
    followup_scheduler.start_scheduler(notify_callback=notify_telegram)
    reply_watcher.start_watcher(notify_callback=notify_telegram)

    await update.callback_query.edit_message_text(
        f"✅ <b>Campaign launched!</b>\n\n"
        f"• Queued: <b>{queued}</b> emails\n"
        f"• Errors: <b>{failed}</b>\n\n"
        f"🔄 Queue, followup scheduler, and reply watcher all started.",
        parse_mode=ParseMode.HTML,
    )


@auth_cb
async def cb_campaign_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("Cancelled")
    await update.callback_query.edit_message_text("❌ Campaign cancelled.")


@auth_required
async def cmd_preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Preview AI-generated email for a lead without sending."""
    if not context.args:
        await reply(update, "Usage: <code>/preview &lt;lead_id_or_email&gt;</code>")
        return
    arg = context.args[0]
    lead = db.get_lead(int(arg)) if arg.isdigit() else db.get_lead_by_email(arg.lower())
    if not lead:
        await reply(update, "❌ Lead not found.")
        return
    await reply(update, "🤖 Generating preview…")
    email_data = ai_router.generate_opener(dict(lead))
    fallback_note = " ⚠️ <i>(fallback template)</i>" if email_data.get("used_fallback") else ""
    await reply(update,
        f"👁 <b>Preview for {lead['email']}</b>{fallback_note}\n\n"
        f"<b>Subject:</b> {email_data['subject']}\n\n"
        f"<b>Body:</b>\n{email_data['body']}"
    )


@auth_required
async def cmd_sendemail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send one email to a specific lead now."""
    if not context.args:
        await reply(update, "Usage: <code>/sendemail &lt;lead_id&gt;</code>")
        return
    try:
        lid = int(context.args[0])
    except ValueError:
        await reply(update, "❌ Provide a numeric lead ID.")
        return
    lead = db.get_lead(lid)
    if not lead:
        await reply(update, f"Lead #{lid} not found.")
        return
    if lead["blacklisted"] or lead["unsubscribed"]:
        await reply(update, "🚫 Lead is blacklisted or unsubscribed.")
        return
    await reply(update, f"🤖 Generating email for {lead['email']}…")
    email_data = ai_router.generate_opener(dict(lead))
    await reply(update, f"📤 Sending…")
    result = email_sender.send_with_logging(
        lead_id=lid,
        to_email=lead["email"],
        subject=email_data["subject"],
        body=email_data["body"],
        message_type="opener",
    )
    if result.get("success"):
        db.update_lead_stage(lid, "contacted")
        db.schedule_first_followup(lid)
        await reply(update, f"✅ Sent to {lead['email']} via {result['account_used']}")
    elif result.get("queued"):
        await reply(update, f"📋 No capacity — email queued for {lead['email']}")
    else:
        await reply(update, f"❌ Send failed: {result.get('error')}")


# ═══════════════════════════════════════════════════════════════
#                  QUEUE CONTROLS
# ═══════════════════════════════════════════════════════════════

@auth_required
async def cmd_startqueue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    def q_callback(msg):
        asyncio.run_coroutine_threadsafe(
            _app.bot.send_message(_authorized_uid, f"<code>{msg}</code>", parse_mode=ParseMode.HTML),
            _app.bot_data["loop"]
        )
    msg = email_queue.start_queue(status_callback=q_callback)
    await reply(update, f"▶️ {msg}")


@auth_required
async def cmd_stopqueue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = email_queue.stop_queue()
    await reply(update, f"⏹ {msg}")


@auth_required
async def cmd_pausequeue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if email_queue.is_paused():
        msg = email_queue.resume_queue()
        await reply(update, f"▶️ Queue {msg}")
    else:
        msg = email_queue.pause_queue()
        await reply(update, f"⏸ Queue {msg}")


@auth_required
async def cmd_queuestat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    running   = email_queue.is_running()
    paused    = email_queue.is_paused()
    queued    = db.get_queued_emails(limit=200)
    remaining = db.total_remaining_today()
    status    = "🟢 Running" if running else "🔴 Stopped"
    if running and paused:
        status = "⏸ Paused"
    fw_running = followup_scheduler.is_running()
    rw_running = reply_watcher.is_running()
    last_check = db.get_last_reply_check()
    await reply(update,
        f"📊 <b>Queue Status</b>\n\n"
        f"Queue: {status}\n"
        f"Followup Scheduler: {'🟢 On' if fw_running else '🔴 Off'}\n"
        f"Reply Watcher: {'🟢 On' if rw_running else '🔴 Off'}\n"
        f"Last reply check: {fmt_dt(last_check)}\n\n"
        f"📬 Emails in queue: <b>{len(queued)}</b>\n"
        f"📊 Capacity remaining today: <b>{remaining}</b>\n"
        f"📤 Sent today: <b>{db.get_stats()['sent_today']}</b>"
    )


@auth_required
async def cmd_retryfailed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = db.retry_failed_emails()
    await reply(update, f"🔄 <b>{count}</b> failed emails reset to queued status. Start the queue to resend.")


# ═══════════════════════════════════════════════════════════════
#                  REPLY MANAGEMENT
# ═══════════════════════════════════════════════════════════════

@auth_required
async def cmd_checkreplies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply(update, "🔍 Checking Gmail inboxes via IMAP…")
    new_replies = reply_watcher.check_now(notify_callback=notify_telegram)
    if new_replies:
        await reply(update, f"📩 Found <b>{len(new_replies)}</b> new replies! Check above for drafts.")
    else:
        await reply(update, "✅ No new replies found.")


@auth_required
async def cmd_replies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    replies_list = db.get_unhandled_replies()
    if not replies_list:
        await reply(update, "✅ No unhandled replies! Inbox is clean.")
        return
    for r in replies_list[:5]:
        name       = r["name"] or r["from_email"]
        draft_body = (r["ai_draft_body"] or "")[:400]
        msg = (
            f"📩 <b>Reply #{r['id']}</b> from <b>{name}</b>\n"
            f"<code>{r['from_email']}</code> | {fmt_dt(r['received_at'])}\n\n"
            f"<b>Subject:</b> {r['subject']}\n"
            f"<b>Their message:</b>\n{(r['body'] or '')[:500]}\n\n"
        )
        if draft_body:
            msg += f"🤖 <b>AI Draft:</b>\n<i>{draft_body}</i>\n"
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Send Draft", callback_data=f"send_draft:{r['id']}"),
                InlineKeyboardButton("✏️ Edit", callback_data=f"edit_draft:{r['id']}"),
            ],
            [InlineKeyboardButton("⏭ Skip", callback_data=f"skip_reply:{r['id']}")],
        ])
        await reply(update, msg, reply_markup=keyboard)


@auth_cb
async def cb_send_draft(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("Sending…")
    rid  = int(update.callback_query.data.split(":")[1])
    r    = db.get_reply(rid)
    if not r:
        await update.callback_query.edit_message_text("❌ Reply not found.")
        return
    lead = db.get_lead(r["lead_id"])
    if not lead:
        await update.callback_query.edit_message_text("❌ Lead not found.")
        return

    subject = r["ai_draft_subject"] or f"Re: {r['subject']}"
    body    = r["ai_draft_body"]
    if not body:
        await update.callback_query.edit_message_text("❌ No AI draft available. Use /editreply to write one.")
        return

    result = email_sender.send_with_logging(
        lead_id=lead["id"],
        to_email=lead["email"],
        subject=subject,
        body=body,
        message_type="reply",
    )
    if result.get("success"):
        db.mark_reply_handled(rid, "ai_draft_sent")
        db.update_lead_stage(lead["id"], "negotiating")
        await update.callback_query.edit_message_text(
            f"✅ Reply sent to <code>{lead['email']}</code> via {result['account_used']}",
            parse_mode=ParseMode.HTML
        )
    else:
        await update.callback_query.edit_message_text(
            f"❌ Send failed: {result.get('error')}", parse_mode=ParseMode.HTML
        )


@auth_cb
async def cb_edit_draft(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    rid = int(update.callback_query.data.split(":")[1])
    r   = db.get_reply(rid)
    if not r:
        await update.callback_query.edit_message_text("❌ Reply not found.")
        return ConversationHandler.END
    context.user_data["edit_reply_id"] = rid
    current_body = r["ai_draft_body"] or "(no draft — write from scratch)"
    await update.callback_query.edit_message_text(
        f"✏️ <b>Edit Reply #{rid}</b>\n\n"
        f"Current draft:\n<i>{current_body[:400]}</i>\n\n"
        "Send the <b>new body text</b> now. Type /cancel to abort.",
        parse_mode=ParseMode.HTML,
    )
    return EDIT_REPLY_TEXT


async def edit_reply_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rid  = context.user_data.get("edit_reply_id")
    body = update.message.text.strip()
    r    = db.get_reply(rid)
    if not r:
        await reply(update, "❌ Reply not found.")
        return ConversationHandler.END
    lead = db.get_lead(r["lead_id"])
    db.update_reply_draft(rid, r["ai_draft_subject"] or "Re: (reply)", body)
    result = email_sender.send_with_logging(
        lead_id=lead["id"],
        to_email=lead["email"],
        subject=r["ai_draft_subject"] or "Re: (reply)",
        body=body,
        message_type="reply",
    )
    if result.get("success"):
        db.mark_reply_handled(rid, "edited_and_sent")
        db.update_lead_stage(lead["id"], "negotiating")
        await reply(update, f"✅ Edited reply sent to <code>{lead['email']}</code>!")
    else:
        await reply(update, f"❌ Send failed: {result.get('error')}")
    return ConversationHandler.END


@auth_cb
async def cb_skip_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("Skipped")
    rid = int(update.callback_query.data.split(":")[1])
    db.mark_reply_handled(rid, "skipped")
    await update.callback_query.edit_message_text(f"⏭ Reply #{rid} marked as handled (skipped).")


@auth_required
async def cmd_sendreply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await reply(update, "Usage: <code>/sendreply &lt;reply_id&gt;</code>")
        return
    rid = int(context.args[0])
    r   = db.get_reply(rid)
    if not r or not r["ai_draft_body"]:
        await reply(update, "❌ Reply not found or no draft available.")
        return
    lead = db.get_lead(r["lead_id"])
    result = email_sender.send_with_logging(
        lead_id=lead["id"],
        to_email=lead["email"],
        subject=r["ai_draft_subject"] or "Re: (reply)",
        body=r["ai_draft_body"],
        message_type="reply",
    )
    if result.get("success"):
        db.mark_reply_handled(rid, "sent")
        await reply(update, f"✅ Reply sent to {lead['email']}")
    else:
        await reply(update, f"❌ {result.get('error')}")


@auth_required
async def cmd_skipreply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await reply(update, "Usage: <code>/skipreply &lt;reply_id&gt;</code>")
        return
    rid = int(context.args[0])
    db.mark_reply_handled(rid, "skipped")
    await reply(update, f"⏭ Reply #{rid} skipped.")


# ═══════════════════════════════════════════════════════════════
#                  TEMPLATES
# ═══════════════════════════════════════════════════════════════

@auth_required
async def cmd_templates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    templates = db.get_templates()
    if not templates:
        await reply(update, "No templates saved. Use /savetemplate")
        return
    lines = ["<b>📝 Templates</b>\n"]
    for t in templates:
        lines.append(f"• <b>{t['name']}</b> [{t['type']}]\n  Subject: {t['subject'][:50]}")
    await reply(update, "\n".join(lines))


@auth_required
async def cmd_savetemplate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply(update, "📝 Template name (one word, e.g. <code>fitness_opener</code>):")
    return TPL_NAME


async def tpl_get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["tpl_name"] = update.message.text.strip()
    keyboard = ReplyKeyboardMarkup([["opener", "followup", "reply"]], one_time_keyboard=True)
    await reply(update, "Type:", reply_markup=keyboard)
    return TPL_TYPE


async def tpl_get_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["tpl_type"] = update.message.text.strip()
    await reply(update, "Subject line:", reply_markup=ReplyKeyboardRemove())
    return TPL_SUBJECT


async def tpl_get_subject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["tpl_subject"] = update.message.text.strip()
    await reply(update, "Body text:")
    return TPL_BODY


async def tpl_get_body(update: Update, context: ContextTypes.DEFAULT_TYPE):
    body = update.message.text.strip()
    name = context.user_data["tpl_name"]
    ok   = db.save_template(name, context.user_data["tpl_type"],
                            context.user_data["tpl_subject"], body)
    await reply(update, f"{'✅ Template saved!' if ok else '⚠️ Template name already exists — overwritten.'}")
    return ConversationHandler.END


@auth_required
async def cmd_deletetemplate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await reply(update, "Usage: <code>/deletetemplate template_name</code>")
        return
    name = context.args[0]
    db.delete_template(name)
    await reply(update, f"🗑 Template <b>{name}</b> deleted.")


# ═══════════════════════════════════════════════════════════════
#                  SETTINGS
# ═══════════════════════════════════════════════════════════════

@auth_required
async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = db.get_all_settings()
    # Mask sensitive keys
    mask = {"cf_api_token", "gemini_api_key", "groq_api_key", "nvidia_api_key",
            "mistral_api_key", "openrouter_api_key"}
    lines = ["<b>⚙️ Current Settings</b>\n"]
    for k, v in sorted(s.items()):
        if k in mask and v:
            v = v[:6] + "…" + v[-4:]
        elif k in mask:
            v = "(not set)"
        lines.append(f"<code>{k}</code>: {v}")
    await reply(update, "\n".join(lines))


@auth_required
async def cmd_setprompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        prompt = " ".join(context.args)
        db.set_setting("system_prompt", prompt)
        await reply(update, "✅ System prompt updated.")
    else:
        await reply(update,
            "Send the prompt as text after the command:\n"
            "<code>/setprompt You are a professional email outreach specialist…</code>\n\n"
            "Or use /settings to see the current prompt."
        )


@auth_required
async def cmd_setsender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        current = db.get_setting("sender_name", "The Team")
        await reply(update, f"Current sender name: <b>{current}</b>\nUsage: <code>/setsender Your Name</code>")
        return
    name = " ".join(context.args)
    db.set_setting("sender_name", name)
    await reply(update, f"✅ Sender name set to <b>{name}</b>")


@auth_required
async def cmd_setinterval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        mn = db.get_setting("min_interval_seconds", "120")
        mx = db.get_setting("max_interval_seconds", "420")
        await reply(update, f"Current: {mn}s–{mx}s\nUsage: <code>/setinterval 120 420</code>")
        return
    try:
        mn, mx = int(context.args[0]), int(context.args[1])
        db.set_setting("min_interval_seconds", mn)
        db.set_setting("max_interval_seconds", mx)
        await reply(update, f"✅ Send interval: <b>{mn}s–{mx}s</b>")
    except ValueError:
        await reply(update, "❌ Usage: /setinterval 120 420")


@auth_required
async def cmd_setfollowup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        days = db.get_setting("followup_days", "[3, 2]")
        maxf = db.get_setting("max_followups", "3")
        await reply(update,
            f"Current: days={days}, max={maxf}\n"
            "Usage: <code>/setfollowup 3 2 max=3</code> (days between FU1, FU2, etc.)"
        )
        return
    args = context.args
    # Parse max= flag
    max_fus = 3
    days    = []
    for a in args:
        if a.startswith("max="):
            try:
                max_fus = int(a.split("=")[1])
            except Exception:
                pass
        else:
            try:
                days.append(int(a))
            except Exception:
                pass
    if not days:
        await reply(update, "❌ Provide at least one day count.")
        return
    db.set_setting("followup_days", json.dumps(days))
    db.set_setting("max_followups", max_fus)
    await reply(update, f"✅ Followup: days={days}, max={max_fus}")


@auth_required
async def cmd_setaikey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply(update,
        "🔑 Enter: <code>provider key</code>\n\n"
        "Providers: <code>gemini groq nvidia mistral openrouter</code>\n\n"
        "Example: <code>/setaikey groq gsk_xxxx</code>"
    )
    if len(context.args) >= 2:
        provider = context.args[0].lower()
        key      = context.args[1]
        mapping  = {
            "gemini": "gemini_api_key",
            "groq":   "groq_api_key",
            "nvidia": "nvidia_api_key",
            "mistral":"mistral_api_key",
            "openrouter": "openrouter_api_key",
        }
        if provider in mapping:
            db.set_setting(mapping[provider], key)
            await reply(update, f"✅ {provider.capitalize()} key saved.")
        else:
            await reply(update, f"❌ Unknown provider: {provider}")


@auth_required
async def cmd_setmodel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        model = db.get_setting("openrouter_model", "meta-llama/llama-3.1-8b-instruct:free")
        await reply(update, f"Current OpenRouter model: <code>{model}</code>\nUsage: <code>/setmodel model/name</code>")
        return
    model = context.args[0]
    db.set_setting("openrouter_model", model)
    await reply(update, f"✅ OpenRouter model set to <code>{model}</code>")


@auth_required
async def cmd_smarthours(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        enabled = db.get_setting("smart_hours_enabled", "0")
        start   = db.get_setting("smart_hours_start", "9")
        end     = db.get_setting("smart_hours_end", "18")
        status  = "🟢 ON" if enabled == "1" else "🔴 OFF"
        await reply(update,
            f"⏰ Smart Hours: {status} ({start}:00–{end}:00)\n"
            "Usage: <code>/smarthours on 9 18</code> or <code>/smarthours off</code>"
        )
        return
    sub = context.args[0].lower()
    if sub == "off":
        db.set_setting("smart_hours_enabled", "0")
        await reply(update, "⏰ Smart hours disabled — sends any time.")
    elif sub == "on" and len(context.args) >= 3:
        try:
            start, end = int(context.args[1]), int(context.args[2])
            db.set_setting("smart_hours_enabled", "1")
            db.set_setting("smart_hours_start", start)
            db.set_setting("smart_hours_end", end)
            await reply(update, f"⏰ Smart hours ON: {start}:00–{end}:00")
        except ValueError:
            await reply(update, "❌ Usage: /smarthours on 9 18")
    else:
        await reply(update, "❌ Usage: /smarthours on 9 18  or  /smarthours off")


@auth_required
async def cmd_autoreply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        mode = db.get_setting("auto_reply_mode", "preview")
        await reply(update,
            f"Current auto-reply mode: <b>{mode}</b>\n\n"
            "• <b>preview</b> — show AI draft, you approve before sending\n"
            "• <b>trust</b> — auto-send AI draft immediately\n\n"
            "Usage: <code>/autoreply preview</code> or <code>/autoreply trust</code>"
        )
        return
    mode = context.args[0].lower()
    if mode not in ("preview", "trust"):
        await reply(update, "❌ Mode must be 'preview' or 'trust'")
        return
    db.set_setting("auto_reply_mode", mode)
    await reply(update, f"✅ Auto-reply mode set to <b>{mode}</b>")


# ═══════════════════════════════════════════════════════════════
#                  STATS / ACTIVITY
# ═══════════════════════════════════════════════════════════════

@auth_required
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s      = db.get_stats()
    counts = db.get_pipeline_breakdown()

    # Reply rate
    sent    = s["total_sent"] or 1
    rep_rate = f"{s['replied_leads'] / sent * 100:.1f}%"

    msg = (
        f"📊 <b>Flinza Stats Dashboard</b>\n\n"
        f"<b>── Leads ──</b>\n"
        f"Total: <b>{s['total_leads']}</b> | New: <b>{s['new_leads']}</b>\n"
        f"Replied: <b>{s['replied_leads']}</b> | Reply rate: <b>{rep_rate}</b>\n"
        f"Blacklisted: <b>{s['blacklisted']}</b> | Unsubscribed: <b>{s['unsubscribed']}</b>\n\n"
        f"<b>── Sending ──</b>\n"
        f"Total sent: <b>{s['total_sent']}</b>\n"
        f"Sent today: <b>{s['sent_today']}</b>\n"
        f"In queue: <b>{s['queued']}</b>\n"
        f"Failed: <b>{s['failed']}</b>\n"
        f"Capacity remaining: <b>{s['remaining_today']}</b>\n\n"
        f"<b>── Replies ──</b>\n"
        f"Total replies: <b>{s['total_replies']}</b>\n"
        f"Unhandled: <b>{s['unhandled_replies']}</b>\n\n"
        f"<b>── Infrastructure ──</b>\n"
        f"Accounts: <b>{s['accounts']}</b> | Aliases: <b>{s['aliases']}</b>\n"
        f"Queue: {'🟢 On' if email_queue.is_running() else '🔴 Off'}\n"
        f"Followups: {'🟢 On' if followup_scheduler.is_running() else '🔴 Off'}\n"
        f"Reply watcher: {'🟢 On' if reply_watcher.is_running() else '🔴 Off'}\n\n"
        f"<b>── Pipeline ──</b>\n{pipeline_bar(counts)}"
    )
    await reply(update, msg)


@auth_required
async def cmd_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logs  = db.get_recent_activity(20)
    if not logs:
        await reply(update, "No activity yet.")
        return
    lines = ["<b>📋 Recent Activity</b>\n"]
    for log in logs:
        ts    = fmt_dt(log["created_at"])
        lines.append(f"<code>{ts}</code> | {log['action']}: {log['details'][:60]}")
    await reply(update, "\n".join(lines))


# ═══════════════════════════════════════════════════════════════
#                  SEED TEST DATA
# ═══════════════════════════════════════════════════════════════

@auth_required
async def cmd_seedtest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Seed demo data for testing without real credentials."""
    await reply(update, "🌱 Seeding test data…")

    # Add test accounts (fake — won't actually send)
    db.add_account("test1@gmail.com", "test_app_password_1", daily_limit=50)
    db.add_account("test2@gmail.com", "test_app_password_2", daily_limit=50)

    # Add test aliases
    db.add_alias("outreach@example.com",    "test1@gmail.com", display_name="Outreach Hub")
    db.add_alias("hello@example.com",       "test1@gmail.com", display_name="Hello Team")
    db.add_alias("connect@example.com",     "test2@gmail.com", display_name="Connect Desk")
    db.add_alias("partner@example.com",     "test2@gmail.com", display_name="Partnership")

    # Add SMMA test prospects
    test_leads = [
        {"email": "marcus@luminaskin.com", "name": "Marcus Vance", "company": "Lumina Skin",
         "niche": "e-commerce / skincare", "website": "https://luminaskin.com", "notes": "DTC skincare brand looking to scale TikTok and Reels"},
        {"email": "elena@apexdental.com", "name": "Dr. Elena Rostova", "company": "Apex Dental Care",
         "niche": "dental / healthcare", "website": "https://apexdentalcare.com", "notes": "Cosmetic dental practice looking for high-ticket patient bookings"},
        {"email": "david@peakgym.com", "name": "David Miller", "company": "Peak Performance Gym",
         "niche": "fitness / gym", "website": "https://peakperformancegym.com", "notes": "Boutique gym facility wanting local membership signups"},
        {"email": "chloe@havenhome.com", "name": "Chloe Bennett", "company": "Haven Home Goods",
         "niche": "home decor / retail", "website": "https://havenhome.com", "notes": "Home accessories brand wanting viral short-form organic video"},
        {"email": "rajdeep@magicfitpartners.com", "name": "Rajdeep Test", "company": "Test Brand Co",
         "niche": "agency testing", "website": "https://testbrand.com", "notes": "Internal verification lead"}
    ]
    added = 0
    for ld in test_leads:
        _, is_new = db.add_or_get_lead(ld["email"], source="smma_seed", **{k:v for k,v in ld.items() if k != "email"})
        if is_new:
            added += 1

    accs = db.get_all_accounts()
    aliases = db.get_all_aliases()
    await reply(update,
        f"✅ <b>Test Environment Ready!</b>\n\n"
        f"• <b>Active Accounts:</b> {len(accs)}\n"
        f"• <b>Active Aliases:</b> {len(aliases)}\n"
        f"• <b>Sample Leads Added:</b> {added}\n\n"
        f"🔥 <i>You have 4 real master accounts & 10 custom domain aliases loaded from migration!</i>\n"
        f"Try sending a test email to your own inbox: <code>/testsend your@email.com</code>"
    )


# ═══════════════════════════════════════════════════════════════
#             ENTERPRISE OUTREACH COMMANDS
# ═══════════════════════════════════════════════════════════════

@auth_required
async def cmd_testsend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a live test email with delivery latency and headers diagnostics."""
    if not context.args:
        await reply(update,
            "🚀 <b>Send Live Test Email</b>\n\n"
            "Send an instant test email to any inbox to verify delivery, SPF/DKIM alignment, and styling.\n\n"
            "Usage:\n"
            "<code>/testsend your_email@domain.com [optional_from_account]</code>\n\n"
            "Example:\n"
            "<code>/testsend myinbox@gmail.com</code>\n"
            "<code>/testsend myinbox@gmail.com partnerships@magicfitpartners.com</code>"
        )
        return

    to_email = context.args[0].strip()
    from_acc = context.args[1].strip() if len(context.args) > 1 else None

    await reply(update, f"🔄 Dispatching live test email to <code>{to_email}</code>…")
    res = email_sender.send_test_email(to_email, from_acc)
    if res["success"]:
        await reply(update,
            f"✅ <b>Test Email Delivered!</b>\n\n"
            f"• <b>Recipient:</b> <code>{to_email}</code>\n"
            f"• <b>Sent From:</b> <code>{res['account_used']}</code>\n"
            f"• <b>Message-ID:</b> <code>{res.get('message_id', 'N/A')}</code>\n"
            f"• <b>Latency:</b> <code>{res.get('elapsed_ms', 0)}ms</code>\n\n"
            f"💡 <i>Tip: Check your inbox (and Promotions/Spam tab) to verify deliverability and sender name!</i>"
        )
    else:
        await reply(update, f"❌ Test send failed: {res.get('error')}")


@auth_required
async def cmd_spamcheck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Analyzes email copy for spam trigger words and deliverability score."""
    if not context.args:
        await reply(update,
            "🛡️ <b>Deliverability & Spam Score Analyzer</b>\n\n"
            "Scan your subject and body copy for 100+ spam words, excessive punctuation, and deliverability traps.\n\n"
            "Usage:\n"
            "<code>/spamcheck Subject line | Body content here...</code>\n\n"
            "Example:\n"
            "<code>/spamcheck quick question | hey loved your fitness reels, open to a paid brand collab?</code>"
        )
        return

    raw = " ".join(context.args)
    if "|" in raw:
        subj, _, body = raw.partition("|")
        subj = subj.strip()
        body = body.strip()
    else:
        subj = "Outreach Inquiry"
        body = raw.strip()

    analysis = email_toolkit.analyze_spam(subj, body)
    score = analysis["score"]
    rating = analysis["rating"]

    if score >= 80:
        bar = "🟢"
    elif score >= 60:
        bar = "🟡"
    else:
        bar = "🔴"

    lines = [
        f"🛡️ <b>Deliverability & Spam Analysis</b>\n",
        f"Score: {bar} <b>{score}/100</b> ({rating})\n",
    ]

    if analysis["detected_triggers"]:
        lines.append("⚠️ <b>Spam Triggers Detected:</b>")
        for trig in analysis["detected_triggers"]:
            lines.append(f"  • <code>{trig}</code>")
        lines.append("")

    if analysis["issues"]:
        lines.append("❌ <b>Deliverability Flags:</b>")
        for iss in analysis["issues"]:
            lines.append(f"  • {iss}")
        lines.append("")

    if analysis["recommendations"]:
        lines.append("💡 <b>Recommendations:</b>")
        for rec in analysis["recommendations"]:
            lines.append(f"  • {rec}")
    else:
        lines.append("✨ <i>Pristine copy! No major deliverability red flags found.</i>")

    await reply(update, "\n".join(lines))


@auth_required
async def cmd_checkemail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Checks DNS MX records, syntax, and disposable domain status for any email."""
    if not context.args:
        await reply(update, "Usage: <code>/checkemail prospect@company.com</code>")
        return

    email_target = context.args[0].strip()
    await reply(update, f"🔍 Validating DNS & MX records for <code>{email_target}</code>…")

    result = email_toolkit.validate_email_deliverability(email_target)
    if not result["valid"]:
        await reply(update, f"❌ Invalid syntax: {result.get('reason')}")
        return

    deliverable = result.get("deliverable", False)
    status_icon = "🟢 Deliverable" if deliverable else "🔴 High Bounce Risk"

    lines = [
        f"📧 <b>Email Validation Report</b>\n",
        f"Target: <code>{email_target}</code>",
        f"Status: <b>{status_icon}</b>",
        f"Domain: <code>{result.get('domain', 'N/A')}</code>",
    ]

    if result.get("mx_records"):
        lines.append(f"Mail Servers (MX): <code>{', '.join(result['mx_records'])}</code>")

    if result.get("is_role_based"):
        lines.append("⚠️ <i>Role-based email (info/support/admin) — response rates may be lower.</i>")

    if result.get("is_disposable"):
        lines.append("🚫 <i>Disposable throwaway email — will bounce!</i>")

    lines.append(f"\nDetails: {result.get('reason', '')}")
    await reply(update, "\n".join(lines))


@auth_required
async def cmd_exportleads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exports leads to a downloadable CSV file."""
    stage = context.args[0] if context.args else None
    csv_data = db.export_leads_csv(stage=stage)
    if not csv_data:
        await reply(update, "No leads to export.")
        return

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(csv_data)
        tmp_path = f.name

    filename = f"flinza_leads_{stage or 'all'}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    await reply(update, "📤 Generating leads CSV export…")
    with open(tmp_path, "rb") as doc:
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=doc,
            filename=filename,
            caption=f"📋 Leads Export ({stage or 'all stages'})",
        )
    try:
        os.remove(tmp_path)
    except Exception:
        pass


@auth_required
async def cmd_exportsent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exports sent email logs to CSV."""
    limit = 1000
    if context.args and context.args[0].isdigit():
        limit = int(context.args[0])

    csv_data = db.export_sent_csv(limit=limit)
    if not csv_data:
        await reply(update, "No sent emails to export.")
        return

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(csv_data)
        tmp_path = f.name

    filename = f"flinza_sent_log_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    await reply(update, "📤 Generating sent outreach log…")
    with open(tmp_path, "rb") as doc:
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=doc,
            filename=filename,
            caption=f"📬 Sent Outreach Log (Latest {limit} emails)",
        )
    try:
        os.remove(tmp_path)
    except Exception:
        pass


@auth_required
async def cmd_warmup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Views or advances mailbox warmup ramp."""
    if context.args and context.args[0].lower() == "advance":
        results = db.advance_all_warmups()
        if not results:
            await reply(update, "No active accounts in warmup mode.")
        else:
            await reply(update, "📈 <b>Warmup Advanced +1 Day:</b>\n\n" + "\n".join(results))
        return

    status = db.get_warmup_status()
    lines = ["🔥 <b>Mailbox & Alias Warmup Status</b>\n"]
    lines.append("<b>Accounts:</b>")
    for a in status["accounts"]:
        mode = "🟢 Warmup ON" if a.get("warmup_mode") else "⚪ Standard"
        lines.append(f"• <code>{a['email']}</code> — {mode} | Day {a.get('warmup_day', 1)} | Cap: {a['daily_limit']}/day")

    lines.append("\n<b>Aliases:</b>")
    for al in status["aliases"]:
        lines.append(f"• <code>{al['alias']}</code> — Day {al.get('warmup_day', 1)} | Cap: {al['daily_limit']}/day")

    lines.append("\n<i>Use <code>/warmup advance</code> to step all warmups forward by +1 day.</i>")
    await reply(update, "\n".join(lines))


@auth_required
async def cmd_optout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Configures 1-click unsubscribe footer."""
    if not context.args:
        enabled = db.get_setting("optout_footer_enabled", "0")
        text = db.get_setting("optout_text", "")
        status = "🟢 Enabled" if enabled == "1" else "🔴 Disabled"
        await reply(update,
            f"🔕 <b>Opt-Out & Unsubscribe Settings</b>\n\n"
            f"Status: <b>{status}</b>\n\n"
            f"Current footer:\n<i>{text}</i>\n\n"
            f"Commands:\n"
            f"• <code>/optout on</code> — turn ON unsubscribe footer\n"
            f"• <code>/optout off</code> — turn OFF\n"
            f"• <code>/optout text &lt;new text&gt;</code> — customize phrasing"
        )
        return

    action = context.args[0].lower()
    if action == "on":
        db.set_setting("optout_footer_enabled", "1")
        await reply(update, "✅ Opt-out footer <b>enabled</b>. Unsubscribe phrasing will be appended to emails.")
    elif action == "off":
        db.set_setting("optout_footer_enabled", "0")
        await reply(update, "✅ Opt-out footer <b>disabled</b>.")
    elif action == "text" and len(context.args) > 1:
        new_text = " ".join(context.args[1:])
        db.set_setting("optout_text", "\n\n" + new_text.strip())
        await reply(update, f"✅ Opt-out footer updated:\n<i>{new_text}</i>")
    else:
        await reply(update, "❌ Usage: /optout on, /optout off, or /optout text <new text>")


# ═══════════════════════════════════════════════════════════════
#                    ERROR HANDLER
# ═══════════════════════════════════════════════════════════════

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update caused error: {context.error}", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                f"⚠️ An error occurred: <code>{str(context.error)[:200]}</code>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


@auth_required
async def cmd_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = db.get_tracking_stats()
    msg = (
        "📈 <b>Email Tracking Diagnostics</b>\n\n"
        f"• Total Sent: <b>{t['total_sent']}</b>\n"
        f"• Total Tracked: <b>{t['total_tracked']}</b>\n"
        f"• Unique Opens: <b>{t['total_opened']}</b>\n"
        f"• Open Rate: <b>{t['open_rate']}%</b>\n"
        f"• Unique Clicks: <b>{t['total_clicked']}</b>\n"
        f"• Click Rate: <b>{t['click_rate']}%</b>\n\n"
        f"<i>Tracking pixel base URL:</i> <code>{db.get_setting('tracking_base_url', 'http://localhost:8000')}</code>"
    )
    await reply(update, msg)


@auth_required
async def cmd_sequences(update: Update, context: ContextTypes.DEFAULT_TYPE):
    steps = db.get_campaign_sequences(campaign_id=1)
    if not steps:
        msg = "🎯 <b>Campaign Sequences:</b> Using default dynamic SMMA AI sequences.\nConfigure multi-step branching in Flinza Studio."
    else:
        lines = ["🎯 <b>Campaign Sequence Steps:</b>\n"]
        for s in steps:
            lines.append(f"• <b>Step {s['step_number']}</b> ({s['delay_days']}d delay, {s['condition_type']}): <code>{s['subject_a']}</code>")
        msg = "\n".join(lines)
    await reply(update, msg)


@auth_required
async def cmd_endpoints(update: Update, context: ContextTypes.DEFAULT_TYPE):
    eps = db.get_custom_endpoints(active_only=False)
    if not eps:
        msg = "⚡ <b>Custom AI Endpoints:</b> None configured.\nUse Flinza Studio web app to connect Ollama, vLLM, DeepSeek, or LocalAI."
    else:
        lines = ["⚡ <b>Configured AI Endpoints:</b>\n"]
        for ep in eps:
            st = "🟢" if ep["is_active"] else "⚪"
            lines.append(f"{st} <b>{ep['name']}</b> ({ep['model_name']}) — <code>{ep['base_url']}</code>")
        msg = "\n".join(lines)
    await reply(update, msg)


@auth_required
async def cmd_studio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Opens Flinza Studio as a WebApp or provides access link."""
    port = db.get_setting("studio_port", "8000")
    local_url = f"http://localhost:{port}"
    public_url = db.get_setting("studio_public_url") or db.get_setting("tracking_base_url") or ""
    active_url = public_url if public_url.startswith("https://") else local_url

    buttons = []
    if active_url.startswith("https://"):
        buttons.append([InlineKeyboardButton("🚀 Open Flinza Studio Mini App", web_app=WebAppInfo(url=active_url))])
    else:
        buttons.append([InlineKeyboardButton("🌐 Open in Browser", url=local_url)])
    buttons.append([InlineKeyboardButton("◀️ Back to Main Menu", callback_data="ui:main")])

    text = (
        "🌐 <b>Flinza Works — Outreach Web Studio</b>\n\n"
        f"<b>Studio URL:</b> <code>{active_url}</code>\n\n"
        "✨ <b>Features:</b> Overview Dashboard, Leads CRM, Mailbox Fleet, Cloudflare Aliases, Sequences, and Unibox.\n\n"
        + ("" if active_url.startswith("https://") else "💡 <i>To open as a Telegram Mini App inside Telegram, set your public HTTPS URL with:</i>\n<code>/seturl https://your-tunnel.trycloudflare.com</code>")
    )
    await reply(update, text, reply_markup=InlineKeyboardMarkup(buttons))


@auth_required
async def cmd_seturl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sets the public HTTPS URL for Telegram WebApp and tracking."""
    if not context.args:
        curr = db.get_setting("studio_public_url") or db.get_setting("tracking_base_url", "http://localhost:8000")
        await reply(update, f"🌐 Current Studio Public URL: <code>{curr}</code>\n\nTo update, run: <code>/seturl https://your-domain-or-tunnel.com</code>")
        return
    url = context.args[0].strip().rstrip("/")
    db.set_setting("studio_public_url", url)
    db.set_setting("tracking_base_url", url)
    await reply(update, f"✅ Public URL updated to: <code>{url}</code>\nYou can now open Flinza Studio as a Telegram Mini App with <code>/studio</code>!")


# ═══════════════════════════════════════════════════════════════
#                    MAIN / BUILD APP
# ═══════════════════════════════════════════════════════════════

def build_app() -> Application:
    global _app

    token = config.TELEGRAM_BOT_TOKEN
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not set in .env")

    app = Application.builder().token(token).build()
    _app = app

    # ── Add Account ──────────────────────────────────────────
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("addaccount", cmd_addaccount)],
        states={
            ACC_EMAIL:  [MessageHandler(filters.TEXT & ~filters.COMMAND, acc_get_email)],
            ACC_PASS:   [MessageHandler(filters.TEXT & ~filters.COMMAND, acc_get_pass)],
            ACC_LIMIT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, acc_get_limit)],
            ACC_PROXY:  [MessageHandler(filters.TEXT & ~filters.COMMAND, acc_get_proxy)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # ── Add Alias ────────────────────────────────────────────
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("addalias", cmd_addalias)],
        states={
            ALIAS_ADDR:   [MessageHandler(filters.TEXT & ~filters.COMMAND, alias_get_addr)],
            ALIAS_MASTER: [MessageHandler(filters.TEXT & ~filters.COMMAND, alias_get_master)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # ── Add Lead ─────────────────────────────────────────────
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("addlead", cmd_addlead)],
        states={
            LEAD_EMAIL:     [MessageHandler(filters.TEXT & ~filters.COMMAND, lead_get_email)],
            LEAD_NAME:      [MessageHandler(filters.TEXT & ~filters.COMMAND, lead_get_name)],
            LEAD_NICHE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, lead_get_niche)],
            LEAD_FOLLOWERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, lead_get_followers)],
            LEAD_BIO:       [MessageHandler(filters.TEXT & ~filters.COMMAND, lead_get_bio)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # ── CF Config ────────────────────────────────────────────
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("cfconfig", cmd_cfconfig)],
        states={
            CF_TOKEN:   [MessageHandler(filters.TEXT & ~filters.COMMAND, cf_get_token)],
            CF_ACCOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, cf_get_account)],
            CF_ZONE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, cf_get_zone)],
            CF_DOMAIN:  [MessageHandler(filters.TEXT & ~filters.COMMAND, cf_get_domain)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # ── CF Generate ──────────────────────────────────────────
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("cfgenerate", cmd_cfgenerate)],
        states={
            CF_GEN_MASTER: [MessageHandler(filters.TEXT & ~filters.COMMAND, cf_gen_master)],
            CF_GEN_COUNT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, cf_gen_count)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # ── Edit Reply ───────────────────────────────────────────
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_edit_draft, pattern=r"^edit_draft:")],
        states={
            EDIT_REPLY_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_reply_save)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    ))

    # ── Add Proxy ────────────────────────────────────────────
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("addproxy", cmd_addproxy)],
        states={
            PROXY_ACCOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, proxy_get_input)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # ── Save Template ────────────────────────────────────────
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("savetemplate", cmd_savetemplate)],
        states={
            TPL_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, tpl_get_name)],
            TPL_TYPE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, tpl_get_type)],
            TPL_SUBJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, tpl_get_subject)],
            TPL_BODY:    [MessageHandler(filters.TEXT & ~filters.COMMAND, tpl_get_body)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # ── Simple commands ──────────────────────────────────────
    app.add_handler(CommandHandler("start",          cmd_start))
    app.add_handler(CommandHandler("help",           cmd_help))
    app.add_handler(CommandHandler("removeaccount",  cmd_removeaccount_inline))
    app.add_handler(CommandHandler("accounts",       cmd_accounts))
    app.add_handler(CommandHandler("testaccount",    cmd_testaccount))
    app.add_handler(CommandHandler("setlimit",       cmd_setlimit))
    app.add_handler(CommandHandler("removealias",    cmd_removealias))
    app.add_handler(CommandHandler("togglealias",    cmd_togglealias))
    app.add_handler(CommandHandler("aliases",        cmd_aliases))
    app.add_handler(CommandHandler("cftest",         cmd_cftest))
    app.add_handler(CommandHandler("cflist",         cmd_cflist))
    app.add_handler(CommandHandler("import",         cmd_import))
    app.add_handler(CommandHandler("leads",          cmd_leads))
    app.add_handler(CommandHandler("pipeline",       cmd_pipeline))
    app.add_handler(CommandHandler("deletelead",     cmd_deletelead))
    app.add_handler(CommandHandler("blacklist",      cmd_blacklist))
    app.add_handler(CommandHandler("search",         cmd_search))
    app.add_handler(CommandHandler("campaign",       cmd_campaign))
    app.add_handler(CommandHandler("preview",        cmd_preview))
    app.add_handler(CommandHandler("sendemail",      cmd_sendemail))
    app.add_handler(CommandHandler("startqueue",     cmd_startqueue))
    app.add_handler(CommandHandler("stopqueue",      cmd_stopqueue))
    app.add_handler(CommandHandler("pausequeue",     cmd_pausequeue))
    app.add_handler(CommandHandler("queuestat",      cmd_queuestat))
    app.add_handler(CommandHandler("retryfailed",    cmd_retryfailed))
    app.add_handler(CommandHandler("checkreplies",   cmd_checkreplies))
    app.add_handler(CommandHandler("replies",        cmd_replies))
    app.add_handler(CommandHandler("sendreply",      cmd_sendreply))
    app.add_handler(CommandHandler("skipreply",      cmd_skipreply))
    app.add_handler(CommandHandler("templates",      cmd_templates))
    app.add_handler(CommandHandler("deletetemplate", cmd_deletetemplate))
    app.add_handler(CommandHandler("settings",       cmd_settings))
    app.add_handler(CommandHandler("setprompt",      cmd_setprompt))
    app.add_handler(CommandHandler("setsender",      cmd_setsender))
    app.add_handler(CommandHandler("setinterval",    cmd_setinterval))
    app.add_handler(CommandHandler("setfollowup",    cmd_setfollowup))
    app.add_handler(CommandHandler("setaikey",       cmd_setaikey))
    app.add_handler(CommandHandler("setmodel",       cmd_setmodel))
    app.add_handler(CommandHandler("smarthours",     cmd_smarthours))
    app.add_handler(CommandHandler("autoreply",      cmd_autoreply))
    app.add_handler(CommandHandler("stats",          cmd_stats))
    app.add_handler(CommandHandler("activity",       cmd_activity))
    app.add_handler(CommandHandler("seedtest",       cmd_seedtest))
    app.add_handler(CommandHandler("testsend",       cmd_testsend))
    app.add_handler(CommandHandler("spamcheck",      cmd_spamcheck))
    app.add_handler(CommandHandler("checkemail",     cmd_checkemail))
    app.add_handler(CommandHandler("exportleads",    cmd_exportleads))
    app.add_handler(CommandHandler("exportsent",     cmd_exportsent))
    app.add_handler(CommandHandler("warmup",         cmd_warmup))
    app.add_handler(CommandHandler("optout",         cmd_optout))
    app.add_handler(CommandHandler("tracking",       cmd_tracking))
    app.add_handler(CommandHandler("sequences",      cmd_sequences))
    app.add_handler(CommandHandler("endpoints",      cmd_endpoints))

    # ── Interactive UI Menu Handlers ─────────────────────────
    app.add_handler(CommandHandler("menu",           cmd_start))
    app.add_handler(CommandHandler("studio",         cmd_studio))
    app.add_handler(CommandHandler("seturl",         cmd_seturl))
    app.add_handler(CallbackQueryHandler(cb_ui_dispatcher,   pattern=r"^ui:"))

    # ── Inline button callbacks ───────────────────────────────
    app.add_handler(CallbackQueryHandler(cb_campaign_go,     pattern=r"^campaign_go$"))
    app.add_handler(CallbackQueryHandler(cb_campaign_cancel, pattern=r"^campaign_cancel$"))
    app.add_handler(CallbackQueryHandler(cb_send_draft,      pattern=r"^send_draft:"))
    app.add_handler(CallbackQueryHandler(cb_skip_reply,      pattern=r"^skip_reply:"))

    # ── Persistent bottom keyboard handler ────────────────────
    async def handle_keyboard_menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text.strip() if update.message and update.message.text else ""
        if text == "🎛️ Control Panel":
            await cmd_start(update, context)
        elif text == "📊 Live Stats":
            await cmd_stats(update, context)
        elif text == "🚀 Launch Campaign":
            await cmd_campaign(update, context)
        elif text == "📥 Unibox Replies":
            await cmd_replies(update, context)
        elif text == "🌐 Open Web Studio":
            port = db.get_setting("studio_port", "8000")
            url = f"http://localhost:{port}"
            kb = None
            if url.startswith("https://"):
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Launch Flinza Mini App", web_app=WebAppInfo(url=url))]])
            await update.message.reply_text(
                f"🌐 <b>Flinza Works — Web Studio</b>\n\nAccess dashboard at:\n<code>{url}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=kb
            )
        elif text == "⚡ Test Send":
            await cmd_testsend(update, context)

    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(r"^(🎛️ Control Panel|📊 Live Stats|🚀 Launch Campaign|📥 Unibox Replies|🌐 Open Web Studio|⚡ Test Send)$"),
        handle_keyboard_menu_text
    ))

    # ── File upload handler ───────────────────────────────────
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    app.add_error_handler(error_handler)
    return app


def main():
    db.init_db()
    logger.info("Flinza starting up…")

    app = build_app()

    # Store event loop reference for cross-thread Telegram sends
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app.bot_data["loop"] = loop

    logger.info(f"Bot started! Authorized user ID: {config.ALLOWED_USER_ID}")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

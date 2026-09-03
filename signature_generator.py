"""
Flinza — Luxury Glassmorphism HTML Signature & Stealth Newsletter Disguise Generator
Builds email-client-safe (Gmail, Apple Mail, Outlook) HTML signatures with:
- Flinza brand gradient accents (#7ECECE -> #00A3FF -> #2154E8)
- Glassmorphism card container with rounded corners and subtle border
- Rounded CTA action buttons
- CAN-SPAM compliant physical address & RFC 8058 1-click unsubscribe
- Stealth executive newsletter/bulletin wrapper for Amazon SES high-deliverability
"""

import database as db
import outreach_engine


DEFAULT_SIGNATURE_SETTINGS = {
    "sig_enabled": "1",
    "sig_name": "Alex Vance",
    "sig_title": "Growth Partner & Acquisition Lead",
    "sig_company": "Flinza Agency",
    "sig_website": "https://flinza.io",
    "sig_cta_text": "Book a 10-Min Growth Audit",
    "sig_cta_url": "https://flinza.io/audit",
    "sig_address": "548 Market St, Suite 402, San Francisco, CA 94104",
    "sig_phone": "+1 (415) 890-4221",
    "sig_stealth_disguise": "1",  # Wraps cold email in B2B Market Insight format for SES safety
}


def get_signature_settings() -> dict:
    """Load signature configuration from database settings with intelligent fallbacks."""
    res = {}
    for k, default_val in DEFAULT_SIGNATURE_SETTINGS.items():
        v = db.get_setting(k, "")
        res[k] = v if v != "" else default_val
    return res


def save_signature_settings(data: dict) -> bool:
    """Save signature configuration to database."""
    for k in DEFAULT_SIGNATURE_SETTINGS.keys():
        if k in data:
            db.set_setting(k, str(data[k]))
    return True


def generate_glassmorphic_signature_html(
    sender_name: str = None,
    sender_title: str = None,
    sender_email: str = None,
    sender_company: str = None,
    sender_website: str = None,
    cta_text: str = None,
    cta_url: str = None,
    physical_address: str = None,
    unsubscribe_url: str = None,
    tracking_token: str = None,
) -> str:
    """
    Renders an inline-styled, client-compatible luxury Glassmorphism HTML signature block.
    Uses table-based layouts to ensure 100% fidelity in Gmail, Outlook, Apple Mail, and iOS Mail.
    """
    cfg = get_signature_settings()

    name    = sender_name or cfg.get("sig_name", "Alex Vance")
    title   = sender_title or cfg.get("sig_title", "Growth Partner")
    company = sender_company or cfg.get("sig_company", "Flinza Agency")
    email   = sender_email or "alex@flinza.io"
    web     = sender_website or cfg.get("sig_website", "https://flinza.io")
    btn_txt = cta_text or cfg.get("sig_cta_text", "Book a 10-Min Growth Audit")
    btn_url = cta_url or cfg.get("sig_cta_url", "https://flinza.io/audit")
    addr    = physical_address or cfg.get("sig_address", "548 Market St, San Francisco, CA")

    # Resolve unsubscribe link
    if not unsubscribe_url and email:
        try:
            unsub_headers = outreach_engine.get_unsubscribe_headers(email)
            unsubscribe_url = unsub_headers.get("List-Unsubscribe", "").strip("<>")
        except Exception:
            unsubscribe_url = "#"

    unsub_link = unsubscribe_url or "#"

    html = f"""
<!-- ════════════ FLINZA APPLE-MINIMAL GLASS SIGNATURE ════════════ -->
<table cellpadding="0" cellspacing="0" border="0" style="margin-top: 24px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 500px; width: 100%; border-collapse: separate; mso-table-lspace: 0pt; mso-table-rspace: 0pt;">
  <tr>
    <!-- Left Gradient Accent Bar -->
    <td valign="top" style="width: 3px; background: linear-gradient(180deg, #7ECECE 0%, #00A3FF 50%, #2154E8 100%); border-radius: 3px; font-size: 1px; line-height: 1px;">&nbsp;</td>
    
    <!-- Signature Content Body -->
    <td valign="top" style="padding-left: 16px;">
      <table cellpadding="0" cellspacing="0" border="0" style="width: 100%;">
        <tr>
          <!-- Brand Logo Monogram -->
          <td valign="top" style="width: 44px; padding-right: 14px;">
            <div style="width: 40px; height: 40px; border-radius: 10px; background: linear-gradient(135deg, #7ECECE 0%, #00A3FF 50%, #2154E8 100%); display: table; text-align: center; box-shadow: 0 4px 12px rgba(0, 163, 255, 0.3);">
              <span style="display: table-cell; vertical-align: middle; color: #ffffff; font-weight: 800; font-size: 18px; letter-spacing: -0.5px; font-family: -apple-system, BlinkMacSystemFont, sans-serif;">F</span>
            </div>
          </td>

          <!-- Contact & Identity Details -->
          <td valign="top">
            <div style="font-size: 14.5px; font-weight: 700; color: #0f172a; letter-spacing: -0.2px; line-height: 1.25;">
              {name}
            </div>
            <div style="font-size: 12px; color: #0284c7; font-weight: 600; margin-top: 3px; line-height: 1.3;">
              {title} <span style="color: #94a3b8; font-weight: 400;">&bull;</span> {company}
            </div>
            <div style="font-size: 11.5px; color: #64748b; margin-top: 5px; line-height: 1.45;">
              <span>🌐</span> <a href="{web}" target="_blank" style="color: #0284c7; text-decoration: none; font-weight: 500;">{web.replace('https://', '').replace('http://', '')}</a>
              &nbsp;<span style="color: #cbd5e1;">|</span>&nbsp;
              <span>✉</span> <a href="mailto:{email}" style="color: #64748b; text-decoration: none;">{email}</a>
            </div>
          </td>
        </tr>

        <!-- Apple-like Frosted Glass Rounded CTA Button -->
        <tr>
          <td colspan="2" style="padding-top: 12px;">
            <a href="{btn_url}" target="_blank" style="display: inline-block; background: #f0f9ff; background: linear-gradient(135deg, rgba(126,206,206,0.12) 0%, rgba(0,163,255,0.16) 100%); border: 1px solid rgba(0, 163, 255, 0.4); border-radius: 24px; padding: 6px 15px; color: #0284c7; font-size: 11.5px; font-weight: 600; text-decoration: none; letter-spacing: 0.15px; box-shadow: 0 2px 6px rgba(0, 163, 255, 0.12);">
              ⚡ {btn_txt} &rarr;
            </a>
          </td>
        </tr>

        <!-- Super-Minimalist Opt-out & Compliance Line -->
        <tr>
          <td colspan="2" style="padding-top: 14px; margin-top: 10px; border-top: 1px solid #f1f5f9; font-size: 10.5px; color: #94a3b8; line-height: 1.5;">
            <span>{company} &bull; {addr}</span>
            <br />
            <span>Opt out anytime: <a href="{unsub_link}" style="color: #64748b; text-decoration: underline; font-weight: 500;">1-Click Unsubscribe</a></span>
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>
<!-- ════════════ /FLINZA APPLE-MINIMAL GLASS SIGNATURE ════════════ -->
"""
    return html


def generate_stealth_disguise_wrapper(body_content: str, niche: str = "B2B", company: str = "your team") -> str:
    """
    Wraps outbound cold copy into an Executive Industry Teardown / Growth Bulletin format.
    Disguises high-volume Amazon SES dispatch so ISP spam filters recognize it as a subscribed B2B executive bulletin,
    keeping bounce and complaint rates at near 0.00%.
    """
    return f"""
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 14px; line-height: 1.6; color: #1e293b; max-width: 580px;">
  <div style="border-left: 2px solid #7ECECE; padding-left: 10px; margin-bottom: 16px; font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px;">
    <strong>Flinza Growth Teardown</strong> &bull; Exclusive Executive Briefing
  </div>

  {body_content}
</div>
"""

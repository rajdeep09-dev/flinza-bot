"""
Flinza — AI Router
LLM chain: OpenRouter → Gemini → Groq → NVIDIA → Mistral
Generates personalized emails and reply drafts.
"""

import json
import time
import re
import logging
import requests
from config import (
    GEMINI_API_KEY as _CFG_GEMINI,
    MISTRAL_API_KEY as _CFG_MISTRAL,
    GROQ_API_KEY as _CFG_GROQ,
    NVIDIA_API_KEY as _CFG_NVIDIA,
    OPENROUTER_API_KEY as _CFG_OPENROUTER,
)
import database as db

logger = logging.getLogger(__name__)

# Module-level keys — can be hot-swapped from bot
GEMINI_API_KEY     = _CFG_GEMINI
MISTRAL_API_KEY    = _CFG_MISTRAL
GROQ_API_KEY       = _CFG_GROQ
NVIDIA_API_KEY     = _CFG_NVIDIA
OPENROUTER_API_KEY = _CFG_OPENROUTER


def _get_key(setting_name: str, fallback: str) -> str:
    val = db.get_setting(setting_name, "")
    return val if val else fallback


# ═══════════════════════════════════════════════════════════════
#                     HIGH-LEVEL GENERATORS
# ═══════════════════════════════════════════════════════════════

def generate_opener(lead_info: dict) -> dict:
    """Generate personalized SMMA agency outreach email. Returns {subject, body, used_fallback}."""
    if hasattr(lead_info, "keys"):
        lead_info = dict(lead_info)

    system_prompt = db.get_setting("system_prompt") or ""
    sender_name   = db.get_setting("sender_name", "The Team")
    company       = lead_info.get("company") or lead_info.get("name") or "your brand"

    user_prompt = f"""Write a cold B2B outreach email from our social media marketing agency (Flinza Works) to this business lead.

OBJECTIVE:
Reach out to offer social media marketing, organic short-form viral video (Reels/TikTok/Shorts), and paid customer acquisition campaigns to help them get more clients/customers.

RULES:
- Casual, peer-to-peer, human tone (NOT like a spammy agency pitch)
- Under 100 words total
- Point out a concrete observation about their brand or current socials
- Propose an idea (e.g. 3 high-hook short-form video concepts or paid traffic strategy)
- Low-friction CTA: Ask if you can send over 3 customized ideas or a 2-min breakdown video
- Do NOT mention pricing in email 1
- Sign off as: {sender_name}

Lead Details:
- Contact Name: {lead_info.get('name', 'there')}
- Company: {company}
- Industry/Niche: {lead_info.get('niche', 'business')}
- Social Handle: {lead_info.get('handle', '')}
- Website: {lead_info.get('website', '')}
- Notes: {lead_info.get('notes', '')}

Output (JSON only, no markdown):
{{"subject": "subject line", "body": "email body with \\n for line breaks"}}"""

    result, fail_reason = _try_chain(system_prompt, user_prompt, expect_json=True)
    if result and isinstance(result, dict) and result.get("subject") and result.get("body"):
        result["used_fallback"] = False
        return result

    logger.error(f"generate_opener: all providers failed ({fail_reason}), using fallback")
    return _fallback_opener(lead_info, sender_name, fail_reason)


def generate_followup(lead_info: dict, previous_emails: list, followup_num: int) -> dict:
    """Generate SMMA follow-up email. Returns {subject, body, used_fallback}."""
    if hasattr(lead_info, "keys"):
        lead_info = dict(lead_info)

    system_prompt = db.get_setting("system_prompt") or ""
    sender_name   = db.get_setting("sender_name", "The Team")
    company       = lead_info.get("company") or lead_info.get("name") or "your brand"

    prev_text = ""
    for em in previous_emails:
        prev_text += f"\n--- {em['message_type']} ---\nSubject: {em['subject']}\n{em['body']}\n"

    is_final = followup_num >= int(db.get_setting("max_followups", "3"))

    user_prompt = f"""Write follow-up #{followup_num} to this business lead who hasn't replied to our social media marketing outreach.

RULES:
- Very short: 2-3 sentences max
- {"Final check-in: close the loop gracefully, leave the door open for whenever they want to scale their socials" if is_final else "Friendly bump: quick nudge asking if they want to see the 3 social growth concepts we mapped out"}
- No pressure or pushy tone
- Sign off as: {sender_name}

Lead: {lead_info.get('name', 'there')} ({company})

Previous emails sent:
{prev_text or 'None'}

Output (JSON only):
{{"subject": "Re: [original subject]", "body": "follow-up body"}}"""

    result, fail_reason = _try_chain(system_prompt, user_prompt, expect_json=True)
    if result and isinstance(result, dict) and result.get("subject") and result.get("body"):
        result["used_fallback"] = False
        return result

    logger.error(f"generate_followup #{followup_num}: all providers failed ({fail_reason})")
    return _fallback_followup(lead_info, followup_num, sender_name, fail_reason)


def generate_reply_draft(lead_info: dict, conversation: list, their_reply: str, instruction: str = "") -> dict:
    """Generate contextual SMMA reply draft. Returns {subject, body, suggested_stage, used_fallback}."""
    if hasattr(lead_info, "keys"):
        lead_info = dict(lead_info)

    system_prompt = db.get_setting("system_prompt") or ""
    sender_name   = db.get_setting("sender_name", "The Team")
    company       = lead_info.get("company") or lead_info.get("name") or "your brand"

    convo_text = ""
    for msg in conversation:
        role_label = "Us" if msg["role"] == "us" else "Them"
        convo_text += f"\n{role_label}: {msg['content']}\n"

    user_prompt = f"""Write a reply email continuing this B2B conversation with a business prospect interested in or asking about our social media marketing agency services.

{"INSTRUCTION: " + instruction if instruction else "Answer their question directly and guide towards a quick 10-15 minute intro call to review custom ideas and strategy."}

Lead Details:
- Contact: {lead_info.get('name', 'Unknown')}
- Company: {company}
- Niche: {lead_info.get('niche', 'business')}

Conversation so far:
{convo_text or "(no prior history)"}

Their latest message:
{their_reply}

GUIDELINES:
- If they ask for pricing: mention our monthly agency growth packages are tailored to scope (organic video production, paid ads management, or full-funnel) and offer a quick 10-min chat to share case studies and give an exact number.
- If they say 'tell me more': give 2-3 concise bullet points of how we produce the content and drive customer acquisition, then offer a link or call.
- If they say 'we do this in-house': explain we often act as creative partners handling video editing and viral hooks to save their team time.
- Sign off as: {sender_name}

Output (JSON only):
{{"subject": "Re: [subject]", "body": "reply body", "suggested_stage": "negotiating|interested|closed_won|closed_lost|needs_info"}}"""

    result, fail_reason = _try_chain(system_prompt, user_prompt, expect_json=True)
    if result and isinstance(result, dict) and result.get("subject") and result.get("body"):
        result["used_fallback"] = False
        return result

    logger.error(f"generate_reply_draft: all providers failed ({fail_reason})")
    return {
        "subject": "Re: Social media growth ideas",
        "body": f"Hey {lead_info.get('name','there')},\n\nThanks for getting back to me! Would love to share a quick breakdown of how we help brands in your space scale customer acquisition through social media.\n\nDo you have 10 minutes sometime this week for a quick chat?\n\nBest,\n{sender_name}",
        "suggested_stage": "negotiating",
        "used_fallback": True,
        "fallback_reason": fail_reason,
    }


# ═══════════════════════════════════════════════════════════════
#                      PROVIDER CHAIN
# ═══════════════════════════════════════════════════════════════

def _try_chain(system_prompt: str, user_prompt: str, expect_json: bool = False):
    """
    Try providers in order:
    1. Active Custom Endpoints (Ollama, vLLM, DeepSeek, LocalAI, etc.)
    2. OpenRouter → Gemini → Groq → NVIDIA → Mistral.
    Retries once on transient network errors.
    Returns (result_or_None, failure_summary_or_None).
    """
    any_key = False
    failures = []

    # 1. Check custom endpoints first
    try:
        custom_eps = db.get_custom_endpoints(active_only=True)
        for ep in custom_eps:
            any_key = True
            ep_name = f"custom:{ep['name']}"
            for attempt in range(1, 3):
                try:
                    raw = _call_custom_endpoint(ep, system_prompt, user_prompt, expect_json)
                    if not raw:
                        failures.append(f"{ep_name}: empty response")
                        break
                    if expect_json:
                        parsed = _extract_json(raw)
                        if parsed and _valid_email_json(parsed):
                            logger.info(f"{ep_name}: success")
                            return parsed, None
                        failures.append(f"{ep_name}: invalid JSON")
                        break
                    else:
                        return raw, None
                except Exception as e:
                    failures.append(f"{ep_name}: {str(e)[:60]}")
                    break
    except Exception as e:
        logger.warning(f"Error querying custom endpoints: {e}")

    # 2. Built-in provider fallback chain
    providers = [
        ("openrouter", "openrouter_api_key", OPENROUTER_API_KEY),
        ("gemini",     "gemini_api_key",     GEMINI_API_KEY),
        ("groq",       "groq_api_key",       GROQ_API_KEY),
        ("nvidia",     "nvidia_api_key",     NVIDIA_API_KEY),
        ("mistral",    "mistral_api_key",    MISTRAL_API_KEY),
    ]

    for provider, setting_key, fallback_key in providers:
        key = _get_key(setting_key, fallback_key)
        if not key:
            continue
        any_key = True

        for attempt in range(1, 3):  # 2 attempts per provider
            try:
                raw = _call_provider(provider, key, system_prompt, user_prompt, expect_json)
                if not raw:
                    failures.append(f"{provider}: empty response")
                    break

                if expect_json:
                    parsed = _extract_json(raw)
                    if parsed and _valid_email_json(parsed):
                        logger.info(f"{provider}: success (attempt {attempt})")
                        return parsed, None
                    failures.append(f"{provider}: bad/incomplete JSON")
                    break
                else:
                    return raw, None

            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response else "?"
                failures.append(f"{provider}: HTTP {status}")
                break

            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                if attempt < 2:
                    time.sleep(2)
                    continue
                failures.append(f"{provider}: connection error")
                break

            except Exception as e:
                failures.append(f"{provider}: {str(e)[:80]}")
                break

    if not any_key:
        msg = "No AI keys configured. Use /setaikey to add one."
        logger.error(msg)
        return None, msg

    summary = " | ".join(failures) if failures else "unknown error"
    logger.error(f"All AI providers failed: {summary}")
    return None, summary


def _call_provider(provider: str, key: str, system: str, user: str, expect_json: bool) -> str | None:
    if provider == "openrouter":
        return _call_openrouter(key, system, user, expect_json)
    elif provider == "gemini":
        return _call_gemini(key, system, user, expect_json)
    elif provider == "groq":
        return _call_groq(key, system, user, expect_json)
    elif provider == "nvidia":
        return _call_nvidia(key, system, user, expect_json)
    elif provider == "mistral":
        return _call_mistral(key, system, user, expect_json)
    return None


def _call_custom_endpoint(ep: dict, system: str, user: str, expect_json: bool) -> str:
    """Invokes any custom OpenAI-compatible endpoint (Ollama, vLLM, DeepSeek, LocalAI, etc.)."""
    url = f"{ep['base_url'].rstrip('/')}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if ep.get("api_key"):
        headers["Authorization"] = f"Bearer {ep['api_key']}"
    if ep.get("custom_headers_json"):
        try:
            extra = json.loads(ep["custom_headers_json"])
            headers.update(extra)
        except Exception:
            pass

    payload = {
        "model": ep.get("model_name", "default"),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": float(ep.get("temperature", 0.85)),
        "max_tokens": int(ep.get("max_tokens", 2048)),
    }
    if expect_json:
        payload["response_format"] = {"type": "json_object"}

    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def test_custom_endpoint(endpoint_id: int) -> dict:
    """Pings a custom endpoint with a probe prompt to verify connectivity and latency."""
    ep = db.get_custom_endpoint(endpoint_id)
    if not ep:
        return {"success": False, "error": "Endpoint not found"}
    start_t = time.time()
    try:
        res = _call_custom_endpoint(ep, "You are a test ping bot.", "Reply with 'PONG' and nothing else.", False)
        elapsed = round((time.time() - start_t) * 1000, 1)
        return {"success": True, "latency_ms": elapsed, "response": res.strip(), "model": ep["model_name"]}
    except Exception as e:
        elapsed = round((time.time() - start_t) * 1000, 1)
        return {"success": False, "latency_ms": elapsed, "error": str(e)}



def _call_openrouter(key, system, user, expect_json):
    model = db.get_setting("openrouter_model", "meta-llama/llama-3.1-8b-instruct:free")
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.85,
    }
    if expect_json:
        payload["response_format"] = {"type": "json_object"}
    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "HTTP-Referer": "https://flinza.io", "X-Title": "Flinza"},
        json=payload, timeout=30
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _call_gemini(key, system, user, expect_json):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}"
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0.85, "maxOutputTokens": 2048},
    }
    r = requests.post(url, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def _call_groq(key, system, user, expect_json):
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.85, "max_tokens": 2048,
    }
    if expect_json:
        payload["response_format"] = {"type": "json_object"}
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=payload, timeout=30
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _call_nvidia(key, system, user, expect_json):
    payload = {
        "model": "moonshotai/kimi-k2.6",
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.85, "top_p": 1.0, "max_tokens": 4096, "stream": False,
    }
    r = requests.post(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=payload, timeout=45
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _call_mistral(key, system, user, expect_json):
    payload = {
        "model": "mistral-large-latest",
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.85, "max_tokens": 2048,
    }
    if expect_json:
        payload["response_format"] = {"type": "json_object"}
    r = requests.post(
        "https://api.mistral.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=payload, timeout=30
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


# ═══════════════════════════════════════════════════════════════
#                      JSON PARSING
# ═══════════════════════════════════════════════════════════════

def _extract_json(text: str):
    if not text:
        return None
    text = text.strip()
    # Strip code fences
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

    start = text.find("{")
    if start == -1:
        return None
    end = text.rfind("}")

    if end != -1:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    # Regex fallback for truncated responses
    candidate = text[start:]
    subj = re.search(r'"subject"\s*:\s*"((?:[^"\\]|\\.)*)"', candidate, re.DOTALL)
    body = re.search(r'"body"\s*:\s*"((?:[^"\\]|\\.)*)"', candidate, re.DOTALL)
    stage = re.search(r'"suggested_stage"\s*:\s*"((?:[^"\\]|\\.)*)"', candidate, re.DOTALL)

    def _unescape(s):
        return s.replace("\\n", "\n").replace('\\"', '"').replace("\\t", "\t")

    if subj and body:
        result = {"subject": _unescape(subj.group(1)), "body": _unescape(body.group(1))}
        if stage:
            result["suggested_stage"] = stage.group(1)
        return result

    return None


def _valid_email_json(parsed) -> bool:
    if not isinstance(parsed, dict):
        return False
    return bool(parsed.get("subject") and parsed.get("body") and len(str(parsed["body"])) > 10)


# ═══════════════════════════════════════════════════════════════
#                    FALLBACK TEMPLATES
# ═══════════════════════════════════════════════════════════════

def _fallback_opener(lead_info: dict, sender_name: str, reason: str) -> dict:
    name = lead_info.get("name") or "there"
    company = lead_info.get("company") or "your brand"
    niche = lead_info.get("niche") or "industry"
    return {
        "subject": f"Quick idea for {company}'s socials",
        "body": (
            f"Hey {name},\n\n"
            f"Came across {company} while researching leaders in the {niche} space and loved what you're building.\n\n"
            f"Noticed a couple of untapped angles on your social channels that could drive a lot more organic customer acquisition with short-form video.\n\n"
            f"Mind if I send over a quick 2-minute breakdown with 3 content concepts we mapped out for you?\n\n"
            f"Best,\n{sender_name}"
        ),
        "used_fallback": True,
        "fallback_reason": reason,
    }


def _fallback_followup(lead_info: dict, num: int, sender_name: str, reason: str) -> dict:
    name = lead_info.get("name") or "there"
    company = lead_info.get("company") or "your brand"
    is_final = num >= int(db.get_setting("max_followups", "3"))
    if is_final:
        body = (
            f"Hey {name}, just circling back one last time. Totally understand if social media marketing isn't a priority for {company} right now.\n\n"
            f"Feel free to reach out down the road if you ever want to explore scaling your socials.\n\n"
            f"Best,\n{sender_name}"
        )
    else:
        body = (
            f"Hey {name}, just bumping this up in case it got buried. Still have those 3 social media growth ideas ready for {company} if you'd like to take a look!\n\n"
            f"Let me know if you're open to seeing them.\n\n"
            f"Best,\n{sender_name}"
        )
    return {
        "subject": f"Re: Quick idea for {company}'s socials",
        "body": body,
        "used_fallback": True,
        "fallback_reason": reason,
    }

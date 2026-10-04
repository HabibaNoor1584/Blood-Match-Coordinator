"""Generative AI layer using the Groq API (gpt-oss models).

The model is only used to (1) read messy request text and (2) write messages.
It never decides compatibility or eligibility. If the API key is missing or a call fails,
the app falls back to regex extraction and message templates so it keeps working.
"""
import json
import os
import re

import rules

DEFAULT_MODEL = "openai/gpt-oss-20b"


# ---------------------------------------------------------------- config
def _secret(name):
    try:
        import streamlit as st
        v = st.secrets.get(name)
        if v:
            return str(v)
    except Exception:
        pass
    return os.environ.get(name, "")


def secret(name):
    """Public helper: read a Streamlit secret or environment variable."""
    return _secret(name)


def model_name():
    return _secret("GROQ_MODEL") or DEFAULT_MODEL


def status():
    """(is_configured, text for the sidebar)"""
    if _secret("GROQ_API_KEY"):
        return True, f"Groq connected ({model_name()})"
    return False, "No GROQ_API_KEY found. Using built-in fallback (regex + templates)."


def _chat(system, user, json_mode=False, max_tokens=1500):
    key = _secret("GROQ_API_KEY")
    if not key:
        raise RuntimeError("no api key")
    from groq import Groq
    client = Groq(api_key=key)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    base = dict(model=model_name(), messages=messages, temperature=0.2, max_completion_tokens=max_tokens)
    attempts = []
    full = dict(base, reasoning_effort="low")
    if json_mode:
        attempts.append(dict(full, response_format={"type": "json_object"}))
    attempts += [full, base]
    last_err = None
    for kwargs in attempts:
        try:
            resp = client.chat.completions.create(**kwargs)
            text = resp.choices[0].message.content
            if text and text.strip():
                return text.strip()
            last_err = RuntimeError("empty response")
        except Exception as e:  # try the next, simpler variant
            last_err = e
    raise RuntimeError(f"Groq call failed: {last_err}")


def _clean(text):
    return (text or "").replace("\u2014", ", ").replace("\u2013", "-").strip()


# ---------------------------------------------------------------- extraction
_CITY_ALIASES = {"pindi": "Rawalpindi", "isb": "Islamabad", "khi": "Karachi"}


def _match_city(text):
    t = (text or "").lower()
    for c in rules.CITIES:
        if c.lower() in t:
            return c
    for alias, city in _CITY_ALIASES.items():
        if re.search(rf"\b{alias}\b", t):
            return city
    return ""


def _regex_extract(text):
    t = text or ""
    out = {"blood_group": "", "units": None, "hospital": "", "city": _match_city(t),
           "contact_name": "", "contact_phone": "", "needed_in_hours": None}
    m = re.search(r"(?<![A-Za-z])(AB|A|B|O)\s*(\+|-|positive|negative|pos|neg|ve)(?![A-Za-z])", t, re.I)
    if m:
        out["blood_group"] = rules.normalize_group(m.group(1) + m.group(2))
    m = re.search(r"(\d+)\s*(units?|bags?|pints?)", t, re.I)
    if m:
        out["units"] = int(m.group(1))
    m = re.search(r"(?:\+?92|0)\s*3\d{2}[\s-]?\d{7}", t)
    if m:
        out["contact_phone"] = m.group(0)
    m = re.search(r"contact\s+(?:person\s+)?(?:is\s+)?([A-Z][a-z]+)", t)
    if m:
        out["contact_name"] = m.group(1)
    m = re.search(r"((?:[A-Z][\w.&']*\s+){1,4}(?:Hospital|Medical|Clinic|Institute|Centre|Center))", t)
    if m:
        out["hospital"] = m.group(1).strip()
    if re.search(r"urgent|emergency|asap|immediately|right now", t, re.I):
        out["needed_in_hours"] = 6
    elif re.search(r"tonight|today", t, re.I):
        out["needed_in_hours"] = 12
    return out


def _parse_json(raw):
    m = re.search(r"\{.*\}", raw, re.S)
    return json.loads(m.group(0) if m else raw)


_EXTRACT_SYSTEM = (
    "You extract structured fields from a blood request message. Return ONLY a JSON object with keys: "
    "blood_group (one of A+, A-, B+, B-, AB+, AB-, O+, O-, or empty string), units (integer or null), "
    "hospital (only if a specific hospital name is written, else empty string), city (city name or empty string), "
    "contact_name (string), contact_phone (as written, or empty string), "
    "needed_in_hours (integer or null; 'tonight' is about 8; 'urgent' or 'asap' with no other timing is 3). "
    "Never invent values that are not in the message. Give no medical advice.")


def extract_request(text):
    """Returns (fields dict, used_ai bool)."""
    fallback = _regex_extract(text)
    if not (text or "").strip():
        return fallback, False
    try:
        data = _parse_json(_chat(_EXTRACT_SYSTEM, text, json_mode=True))
    except Exception:
        return fallback, False
    out = dict(fallback)
    g = rules.normalize_group(data.get("blood_group"))
    if g:
        out["blood_group"] = g
    try:
        if data.get("units") not in (None, ""):
            out["units"] = max(0, int(data["units"]))
    except (TypeError, ValueError):
        pass
    city = _match_city(str(data.get("city") or ""))
    if city:
        out["city"] = city
    for k in ("hospital", "contact_name", "contact_phone"):
        v = str(data.get(k) or "").strip()
        if v:
            out[k] = v
    try:
        if data.get("needed_in_hours") not in (None, ""):
            out["needed_in_hours"] = int(data["needed_in_hours"])
    except (TypeError, ValueError):
        pass
    return out, True


# ---------------------------------------------------------------- message drafting
_WRITER_SYSTEM = (
    "You write short messages for a blood donation coordination team in Pakistan. Rules: plain and polite wording; "
    "no medical advice; never say anyone is eligible or safe to donate (say 'may be compatible' and that the "
    "blood bank does the final check); never include the requester's phone number in a message to donors; "
    "no emojis; no em dashes; do not invent facts. Output only the message text.")


def _urgency_text(ctx):
    h = ctx.get("needed_in_hours")
    return f"needed within about {h} hours" if h else "needed urgently"


def _template(kind, ctx, lang):
    g, u, h, c = ctx["blood_group"], ctx["units"], ctx["hospital"], ctx["city"]
    if kind == "donor_alert":
        if lang == "Urdu":
            return (f"السلام علیکم {{name}}، {c} میں {h} پر {g} خون کی {u} یونٹ کی فوری ضرورت ہے۔ "
                    "آپ کی معلومات کے مطابق آپ موزوں ڈونر ہو سکتے ہیں۔ اگر آپ دستیاب ہیں تو بلڈ میچ ایپ کھول کر "
                    "قبول کریں پر ٹیپ کریں۔ حتمی جانچ بلڈ بینک کرے گا۔ شکریہ۔")
        return (f"Hello {{name}}, a patient needs {u} unit(s) of {g} blood at {h}, {c} ({_urgency_text(ctx)}). "
                "Your registered details suggest you may be a compatible donor. If you are available, please open "
                "BloodMatch and tap Accept. The blood bank will do the final screening. Thank you.")
    if kind == "followup":
        items = ", ".join(ctx.get("missing", []))
        return (f"Hello, thank you for contacting us. To organize donors for your request we still need: {items}. "
                "Please reply with these details as soon as you can.")
    if kind == "bank_note":
        return (f"Handover note: request for {u} unit(s) of {g} at {h}, {c}, {_urgency_text(ctx)}. "
                f"Requester contact: {ctx.get('contact_name') or 'not given'}, {ctx.get('contact_phone')}. "
                f"BloodMatch has pooled {ctx.get('pool', 0)} potentially compatible donors by basic rules only. "
                "Please confirm stock availability and complete medical screening of any donor who arrives.")
    if kind == "requester_update":
        return (f"Update on your request for {g} blood at {h}: we are contacting registered donors near the hospital. "
                "We cannot guarantee a response. Please also contact the hospital blood bank directly, "
                "since they will do all medical checks.")
    return ""


def draft(kind, ctx, lang="English"):
    """Returns (message, used_ai)."""
    base = _template(kind, ctx, lang)
    facts = json.dumps({k: v for k, v in ctx.items() if k != "contact_phone" or kind == "bank_note"}, ensure_ascii=False)
    tasks = {
        "donor_alert": "Write a donor alert, under 70 words. Use the literal placeholder {name} for the donor's first name. "
                       "Ask them to open the BloodMatch app and tap Accept or Decline.",
        "followup": "Write a short follow-up to the requester asking only for the missing items listed.",
        "bank_note": "Write a short handover note for the blood bank (under 90 words) with the request details, "
                     "the requester contact, and how many donors were pooled by basic rules.",
        "requester_update": "Write a short status update to the requester (under 60 words). Say we are contacting nearby "
                            "registered donors, that there is no guarantee, and that the blood bank does all medical checks.",
    }
    try:
        prompt = f"Facts: {facts}\nLanguage: {lang}\nTask: {tasks[kind]}"
        text = _clean(_chat(_WRITER_SYSTEM, prompt, max_tokens=900))
        if kind == "donor_alert" and "{name}" not in text:
            text = "Hello {name}, " + text[0].lower() + text[1:] if text else base
        if kind == "donor_alert" and lang == "English" and "blood bank" not in text.lower():
            text += " The blood bank will do the final screening."
        return text or base, bool(text)
    except Exception:
        return base, False


def briefing(ctx):
    """Short situation summary for the coordinator. Returns (text, used_ai)."""
    base = (f"{ctx['units']} unit(s) of {ctx['blood_group']} needed at {ctx['hospital']}, {ctx['city']} "
            f"(urgency {ctx['urgency']}). {ctx['pool']} potentially eligible donors found within "
            f"{ctx['radius']:g} km; {ctx['excluded']} excluded by the rules. Review the action list and approve "
            "what should go out.")
    try:
        prompt = ("Write a 2 to 3 sentence situation summary for a blood coordinator using only these facts: "
                  + json.dumps(ctx) + ". Mention whether the donor pool looks sufficient (target is "
                  f"{ctx['target']}). No medical advice.")
        text = _clean(_chat(_WRITER_SYSTEM, prompt, max_tokens=600))
        return text or base, bool(text)
    except Exception:
        return base, False

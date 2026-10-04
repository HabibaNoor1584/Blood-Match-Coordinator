"""Predefined rules for BloodMatch Coordinator.

Everything the system "decides" lives here, in plain code, so it is easy to read,
test and change. The AI model never decides compatibility or eligibility.
A blood bank should adjust RULES to its own policy and local regulations.
"""
import math
from datetime import date

BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]

RULES = {
    "min_age": 18,
    "max_age": 60,
    "min_gap_days": 90,          # days since last whole blood donation
    "alert_radius_km": 3.0,      # donors inside this radius are alerted first
    "widen_steps_km": [5.0, 10.0],
    "pool_ratio": 3,             # aim for this many potential donors per unit needed
    "weekly_alert_cap": 3,       # max alerts per donor per 7 days
}

# recipient group -> donor groups whose red cells are compatible
COMPATIBLE_DONORS = {
    "O-": ["O-"],
    "O+": ["O-", "O+"],
    "A-": ["O-", "A-"],
    "A+": ["O-", "O+", "A-", "A+"],
    "B-": ["O-", "B-"],
    "B+": ["O-", "O+", "B-", "B+"],
    "AB-": ["O-", "A-", "B-", "AB-"],
    "AB+": ["O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"],
}

# Approximate city centres (lat, lon) used for distance in this demo
CITIES = {
    "Islamabad": (33.6844, 73.0479),
    "Rawalpindi": (33.5651, 73.0169),
    "Lahore": (31.5204, 74.3587),
    "Karachi": (24.8607, 67.0011),
    "Peshawar": (34.0151, 71.5249),
    "Abbottabad": (34.1688, 73.2215),
    "Quetta": (30.1798, 66.9750),
    "Multan": (30.1575, 71.4704),
    "Faisalabad": (31.4504, 73.1350),
}
CITY_WEIGHTS = {
    "Islamabad": 18, "Rawalpindi": 18, "Lahore": 18, "Karachi": 16, "Peshawar": 8,
    "Abbottabad": 5, "Quetta": 4, "Multan": 6, "Faisalabad": 7,
}

REQUIRED_FIELDS = {
    "blood_group": "patient blood group",
    "units": "number of units needed",
    "hospital": "hospital name",
    "city": "city",
    "contact_phone": "contact phone number",
}

REASON_LABELS = {
    "no_consent": "no consent to be contacted",
    "unavailable": "marked unavailable",
    "age": "outside allowed age range",
    "recent_donation": "donated too recently",
    "busy": "already accepted another request",
}

_GENERIC_HOSPITAL = {"", "hospital", "a hospital", "the hospital", "not specified", "unknown", "n/a", "none"}


def normalize_group(text):
    """'b positive' -> 'B+'. Returns '' if it is not a valid group."""
    if not text:
        return ""
    t = str(text).strip().upper().replace(" ", "")
    for a, b in (("POSITIVE", "+"), ("NEGATIVE", "-"), ("PLUS", "+"), ("MINUS", "-"),
                 ("POS", "+"), ("NEG", "-"), ("VE", "")):
        t = t.replace(a, b)
    return t if t in BLOOD_GROUPS else ""


def compatible_donor_groups(recipient_group):
    return COMPATIBLE_DONORS.get(recipient_group, [])


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def days_since(last_donation, today=None):
    if not last_donation:
        return None
    today = today or date.today()
    return (today - date.fromisoformat(last_donation)).days


def screen_donor(donor, busy_ids=(), today=None):
    """Returns a list of reason codes. Empty list = 'potentially eligible'.
    This is a basic screen only. The blood bank does the real screening."""
    reasons = []
    if not donor["consent"]:
        reasons.append("no_consent")
    if not donor["available"]:
        reasons.append("unavailable")
    if not (RULES["min_age"] <= donor["age"] <= RULES["max_age"]):
        reasons.append("age")
    d = days_since(donor["last_donation"], today)
    if d is not None and d < RULES["min_gap_days"]:
        reasons.append("recent_donation")
    if donor["id"] in busy_ids:
        reasons.append("busy")
    return reasons


def urgency_from_hours(hours):
    if hours is None:
        return "High"
    if hours <= 6:
        return "Critical"
    if hours <= 24:
        return "High"
    return "Normal"


def valid_phone(phone):
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    return len(digits) >= 10


def missing_fields(req):
    """Returns the keys of REQUIRED_FIELDS that are missing or unusable."""
    missing = []
    if req.get("blood_group") not in BLOOD_GROUPS:
        missing.append("blood_group")
    if not req.get("units") or int(req["units"]) < 1:
        missing.append("units")
    if str(req.get("hospital") or "").strip().lower() in _GENERIC_HOSPITAL:
        missing.append("hospital")
    if req.get("city") not in CITIES:
        missing.append("city")
    if not valid_phone(req.get("contact_phone")):
        missing.append("contact_phone")
    return missing

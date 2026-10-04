"""SQLite layer. All donor data here is SYNTHETIC unless someone registers in the demo."""
import os
import random
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone

import rules

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "data", "bloodmatch.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS donors(
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, phone TEXT, blood_group TEXT,
    age INTEGER, city TEXT, lat REAL, lon REAL, last_donation TEXT,
    available INTEGER DEFAULT 1, consent INTEGER DEFAULT 1,
    response_rate REAL DEFAULT 0.5, is_synthetic INTEGER DEFAULT 0, created TEXT);

CREATE TABLE IF NOT EXISTS requests(
    id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT, raw_text TEXT,
    blood_group TEXT, units INTEGER, hospital TEXT, city TEXT, lat REAL, lon REAL,
    contact_name TEXT, contact_phone TEXT, needed_in_hours INTEGER,
    urgency TEXT DEFAULT 'High', status TEXT DEFAULT 'New', briefing TEXT DEFAULT '');

CREATE TABLE IF NOT EXISTS matches(
    id INTEGER PRIMARY KEY AUTOINCREMENT, request_id INTEGER, donor_id INTEGER,
    distance_km REAL, status TEXT DEFAULT 'Pooled', updated TEXT);

CREATE TABLE IF NOT EXISTS notifications(
    id INTEGER PRIMARY KEY AUTOINCREMENT, donor_id INTEGER, request_id INTEGER,
    created TEXT, channel TEXT, message TEXT);

CREATE TABLE IF NOT EXISTS actions(
    id INTEGER PRIMARY KEY AUTOINCREMENT, request_id INTEGER, kind TEXT,
    description TEXT, message TEXT, payload TEXT DEFAULT '', status TEXT DEFAULT 'Pending',
    created TEXT);

CREATE TABLE IF NOT EXISTS audit_log(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, request_id INTEGER, event TEXT, detail TEXT);
"""

REQUEST_COLS = {
    "raw_text", "blood_group", "units", "hospital", "city", "lat", "lon",
    "contact_name", "contact_phone", "needed_in_hours", "urgency", "status", "briefing"
}
CLOSED = ("Fulfilled", "Closed")


def now():
    return datetime.now(timezone(timedelta(hours=5))).strftime("%Y-%m-%d %H:%M")


def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    return c


def q(sql, params=()):
    with closing(_conn()) as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def x(sql, params=()):
    with closing(_conn()) as c:
        cur = c.execute(sql, params)
        c.commit()
        return cur.lastrowid


def init_db():
    with closing(_conn()) as c:
        c.executescript(SCHEMA)
        c.commit()

    if q("SELECT COUNT(*) AS n FROM donors")[0]["n"] == 0:
        seed_donors()


def reset_all():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init_db()


# ---------------------------------------------------------------- synthetic data
FIRST = [
    "Ali", "Ahmed", "Usman", "Hamza", "Bilal", "Zain", "Hassan", "Omar", "Saad", "Faisal",
    "Ayesha", "Fatima", "Maryam", "Sana", "Hira", "Zainab", "Noor", "Amna", "Iqra", "Sadia",
    "Imran", "Kamran", "Rizwan", "Asad", "Talha", "Nadia", "Rabia", "Mehwish", "Shazia", "Umer"
]
LAST = [
    "Khan", "Malik", "Sheikh", "Butt", "Raza", "Qureshi", "Mirza", "Ansari", "Chaudhry", "Siddiqui",
    "Hussain", "Iqbal", "Abbasi", "Awan", "Baig", "Farooq", "Javed", "Nawaz", "Shah", "Yousaf"
]
GROUP_WEIGHTS = {"B+": 32, "O+": 27, "A+": 22, "AB+": 8, "O-": 3, "B-": 3, "A-": 3, "AB-": 2}


def seed_donors(n=300, seed=42):
    rnd = random.Random(seed)
    cities = list(rules.CITY_WEIGHTS)
    cw = [rules.CITY_WEIGHTS[c] for c in cities]
    groups = list(GROUP_WEIGHTS)
    gw = [GROUP_WEIGHTS[g] for g in groups]
    today = date.today()
    rows = []

    for i in range(1, n + 1):
        city = rnd.choices(cities, cw)[0]
        clat, clon = rules.CITIES[city]
        last = None

        if rnd.random() > 0.2:
            last = (today - timedelta(days=rnd.randint(10, 400))).isoformat()

        rows.append((
            f"{rnd.choice(FIRST)} {rnd.choice(LAST)}",
            f"0300-0000{i:03d}",
            rnd.choices(groups, gw)[0],
            rnd.randint(18, 62),
            city,
            clat + rnd.gauss(0, 0.03),
            clon + rnd.gauss(0, 0.03),
            last,
            1 if rnd.random() > 0.15 else 0,
            1 if rnd.random() > 0.05 else 0,
            round(rnd.uniform(0.3, 0.95), 2),
            1,
            now()
        ))

    with closing(_conn()) as c:
        c.executemany(
            "INSERT INTO donors(name,phone,blood_group,age,city,lat,lon,last_donation,available,"
            "consent,response_rate,is_synthetic,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows
        )
        c.commit()


# ---------------------------------------------------------------- audit
def audit(request_id, event, detail=""):
    x(
        "INSERT INTO audit_log(ts,request_id,event,detail) VALUES(?,?,?,?)",
        (now(), request_id, event, detail)
    )


def get_audit(request_id):
    return q("SELECT * FROM audit_log WHERE request_id=? ORDER BY id", (request_id,))


# ---------------------------------------------------------------- donors
def _digits(phone):
    return "".join(ch for ch in str(phone) if ch.isdigit())


def add_donor(d):
    return x(
        "INSERT INTO donors(name,phone,blood_group,age,city,lat,lon,last_donation,available,consent,"
        "response_rate,is_synthetic,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,0,?)",
        (
            d["name"], d["phone"], d["blood_group"], d["age"], d["city"],
            d["lat"], d["lon"], d.get("last_donation"), 1,
            1 if d.get("consent") else 0, 0.5, now()
        )
    )


def get_donor(donor_id):
    r = q("SELECT * FROM donors WHERE id=?", (donor_id,))
    return r[0] if r else None


def find_donor_by_phone(phone):
    d = _digits(phone)[-10:]
    if len(d) < 10:
        return None

    for r in q("SELECT * FROM donors"):
        if _digits(r["phone"])[-10:] == d:
            return r
    return None


def update_donor(donor_id, **fields):
    allowed = {"available", "city", "lat", "lon", "last_donation", "consent"}
    fields = {k: v for k, v in fields.items() if k in allowed}

    if fields:
        sets = ",".join(f"{k}=?" for k in fields)
        x(f"UPDATE donors SET {sets} WHERE id=?", (*fields.values(), donor_id))


def delete_donor(donor_id):
    x("DELETE FROM notifications WHERE donor_id=?", (donor_id,))
    x("DELETE FROM matches WHERE donor_id=?", (donor_id,))
    x("DELETE FROM donors WHERE id=?", (donor_id,))


def busy_donor_ids():
    rows = q(
        "SELECT m.donor_id FROM matches m JOIN requests r ON r.id=m.request_id "
        "WHERE m.status='Accepted' AND r.status NOT IN ('Fulfilled','Closed')"
    )
    return {r["donor_id"] for r in rows}


# ---------------------------------------------------------------- requests
def create_request(d):
    lat, lon = d.get("lat"), d.get("lon")

    if (lat is None or lon is None) and d.get("city") in rules.CITIES:
        lat, lon = rules.CITIES[d["city"]]

    return x(
        "INSERT INTO requests(created,raw_text,blood_group,units,hospital,city,lat,lon,contact_name,"
        "contact_phone,needed_in_hours,urgency,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            now(), d.get("raw_text", ""), d.get("blood_group", ""),
            d.get("units") or 0, d.get("hospital", ""), d.get("city", ""),
            lat, lon, d.get("contact_name", ""), d.get("contact_phone", ""),
            d.get("needed_in_hours"), "High", "New"
        )
    )


def get_request(rid):
    r = q("SELECT * FROM requests WHERE id=?", (rid,))
    return r[0] if r else None


def update_request(rid, fields):
    fields = {k: v for k, v in fields.items() if k in REQUEST_COLS}

    if "city" in fields and "lat" not in fields and fields["city"] in rules.CITIES:
        fields["lat"], fields["lon"] = rules.CITIES[fields["city"]]

    if fields:
        sets = ",".join(f"{k}=?" for k in fields)
        x(f"UPDATE requests SET {sets} WHERE id=?", (*fields.values(), rid))


def list_requests():
    order = "CASE urgency WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 ELSE 2 END"
    return q(
        f"SELECT * FROM requests "
        f"ORDER BY CASE WHEN status IN ('Fulfilled','Closed') THEN 1 ELSE 0 END, {order}, id DESC"
    )


# ---------------------------------------------------------------- matches
def add_matches(rid, rows):
    """rows: list of (donor_id, distance_km)"""
    with closing(_conn()) as c:
        c.executemany(
            "INSERT INTO matches(request_id,donor_id,distance_km,status,updated) VALUES(?,?,?,?,?)",
            [(rid, did, dist, "Pooled", now()) for did, dist in rows]
        )
        c.commit()


def get_matches(rid):
    return q(
        "SELECT m.*, d.name, d.blood_group, d.city, d.last_donation, d.response_rate, d.phone "
        "FROM matches m JOIN donors d ON d.id=m.donor_id WHERE m.request_id=? ORDER BY m.distance_km",
        (rid,)
    )


def accepted_donors(rid):
    """Requester-safe view of donors who accepted. Phone is intentionally not returned."""
    return q(
        "SELECT m.donor_id, m.distance_km, m.status, "
        "d.name, d.blood_group, d.city "
        "FROM matches m JOIN donors d ON d.id=m.donor_id "
        "WHERE m.request_id=? AND m.status='Accepted' "
        "ORDER BY m.distance_km",
        (rid,)
    )


def set_match_status(rid, donor_id, status):
    x(
        "UPDATE matches SET status=?, updated=? WHERE request_id=? AND donor_id=?",
        (status, now(), rid, donor_id)
    )


def clear_unsent(rid):
    """Before re-running: drop pooled-but-not-alerted matches and pending actions."""
    x("DELETE FROM matches WHERE request_id=? AND status='Pooled'", (rid,))
    x("DELETE FROM actions WHERE request_id=? AND status='Pending'", (rid,))


# ---------------------------------------------------------------- actions
def add_action(rid, kind, description, message="", payload=""):
    return x(
        "INSERT INTO actions(request_id,kind,description,message,payload,status,created) "
        "VALUES(?,?,?,?,?, 'Pending', ?)",
        (rid, kind, description, message, payload, now())
    )


def list_actions(rid):
    return q("SELECT * FROM actions WHERE request_id=? ORDER BY id", (rid,))


def get_action(aid):
    r = q("SELECT * FROM actions WHERE id=?", (aid,))
    return r[0] if r else None


def set_action(aid, **fields):
    sets = ",".join(f"{k}=?" for k in fields)
    x(f"UPDATE actions SET {sets} WHERE id=?", (*fields.values(), aid))


# ---------------------------------------------------------------- notifications and responses
def add_notification(donor_id, rid, message, channel="in-app + SMS (mock)"):
    x(
        "INSERT INTO notifications(donor_id,request_id,created,channel,message) VALUES(?,?,?,?,?)",
        (donor_id, rid, now(), channel, message)
    )


def alerts_this_week(donor_id):
    cutoff = (
        datetime.now(timezone(timedelta(hours=5))) - timedelta(days=7)
    ).strftime("%Y-%m-%d %H:%M")

    return q(
        "SELECT COUNT(*) AS n FROM notifications WHERE donor_id=? AND created>=?",
        (donor_id, cutoff)
    )[0]["n"]


def donor_notifications(donor_id):
    return q(
        "SELECT n.*, r.blood_group, r.units, r.hospital, r.city, r.status AS req_status, r.urgency, "
        "r.contact_name, r.contact_phone, m.status AS match_status "
        "FROM notifications n JOIN requests r ON r.id=n.request_id "
        "LEFT JOIN matches m ON m.request_id=n.request_id AND m.donor_id=n.donor_id "
        "WHERE n.donor_id=? ORDER BY n.id DESC",
        (donor_id,)
    )


def donors_with_notifications():
    return q(
        "SELECT DISTINCT d.id, d.name, d.blood_group, d.city, d.phone FROM donors d "
        "JOIN notifications n ON n.donor_id=d.id ORDER BY d.id"
    )


def respond(notification_id, accept):
    """Donor accepts or declines. Returns a short result code."""
    n = q("SELECT * FROM notifications WHERE id=?", (notification_id,))
    if not n:
        return "missing"

    n = n[0]
    rid, did = n["request_id"], n["donor_id"]
    req = get_request(rid)
    m = q(
        "SELECT * FROM matches WHERE request_id=? AND donor_id=?",
        (rid, did)
    )

    if not req or not m:
        return "missing"

    if req["status"] in CLOSED:
        return "closed"

    if m[0]["status"] != "Alerted":
        return "already_answered"

    if accept:
        if did in busy_donor_ids():
            return "busy"

        set_match_status(rid, did, "Accepted")
        audit(rid, "donor_accepted", f"donor #{did}")

        covered = q(
            "SELECT COUNT(*) AS n FROM matches WHERE request_id=? AND status='Accepted'",
            (rid,)
        )[0]["n"]

        if covered >= (req["units"] or 0):
            update_request(rid, {"status": "Fulfilled"})
            audit(
                rid,
                "request_fulfilled",
                f"{covered} donor(s) accepted for {req['units']} unit(s)"
            )

        return "accepted"

    set_match_status(rid, did, "Declined")
    audit(rid, "donor_declined", f"donor #{did}")
    return "declined"


def stats():
    return {
        "open": q(
            "SELECT COUNT(*) AS n FROM requests WHERE status NOT IN ('Fulfilled','Closed')"
        )[0]["n"],
        "donors": q("SELECT COUNT(*) AS n FROM donors")[0]["n"],
        "alerts": q("SELECT COUNT(*) AS n FROM notifications")[0]["n"],
        "accepted": q(
            "SELECT COUNT(*) AS n FROM matches WHERE status='Accepted'"
        )[0]["n"],
    }

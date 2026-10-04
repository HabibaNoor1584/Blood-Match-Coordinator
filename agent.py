"""Coordinator agent.

Bounded agentic workflow for the BloodMatch demo. Rules decide compatibility and basic
eligibility. Generative AI is used for communication drafts and the briefing. The agent
automatically sends in-app donor alerts after the requester submits a complete form.
No medical decision is made by the AI.
"""
import json
from collections import Counter

import db
import llm
import rules

MAX_STEPS = 8


class _Steps:
    def __init__(self, rid):
        self.rid, self.n = rid, 0

    def log(self, tool, detail):
        self.n += 1
        if self.n > MAX_STEPS:
            raise RuntimeError("Agent step limit reached")
        db.audit(self.rid, f"agent:{tool}", detail)


def search_pool(req, radius, skip_ids=()):
    """Find compatible, potentially eligible donors inside a radius."""
    groups = rules.compatible_donor_groups(req["blood_group"])
    busy = db.busy_donor_ids()
    marks = ",".join("?" * len(groups))
    donors = db.q(f"SELECT * FROM donors WHERE blood_group IN ({marks})", tuple(groups))

    pool, excluded = [], Counter()
    for d in donors:
        if d["id"] in skip_ids:
            continue

        dist = rules.haversine_km(req["lat"], req["lon"], d["lat"], d["lon"])
        if dist > radius:
            continue

        reasons = rules.screen_donor(d, busy)
        if reasons:
            excluded.update(reasons)
            continue

        pool.append((d, dist))

    def key(item):
        d, dist = item
        gap = rules.days_since(d["last_donation"])
        return (
            0 if d["blood_group"] == req["blood_group"] else 1,
            round(dist, 1),
            -(gap if gap is not None else 9999),
            -d["response_rate"],
        )

    pool.sort(key=key)
    return pool, excluded


def _ctx(req, **extra):
    return {
        "blood_group": req["blood_group"],
        "units": req["units"],
        "hospital": req["hospital"],
        "city": req["city"],
        "needed_in_hours": req["needed_in_hours"],
        "urgency": req["urgency"],
        "contact_name": req["contact_name"],
        "contact_phone": req["contact_phone"],
        **extra,
    }


def _excl_text(excluded):
    if not excluded:
        return "none"
    return ", ".join(f"{rules.REASON_LABELS[k]}: {v}" for k, v in excluded.items())


def _alert_pool(rid, donor_ids, donor_msg, radius):
    """Send donor alerts while respecting the existing weekly alert cap."""
    sent = 0
    skipped_cap = 0

    for did in donor_ids:
        matches = [m for m in db.get_matches(rid) if m["donor_id"] == did]
        donor = db.get_donor(did)

        if not matches or not donor or matches[0]["status"] != "Pooled":
            continue

        if db.alerts_this_week(did) >= rules.RULES["weekly_alert_cap"]:
            skipped_cap += 1
            continue

        db.add_notification(
            did,
            rid,
            donor_msg.replace("{name}", donor["name"].split()[0])
        )
        db.set_match_status(rid, did, "Alerted")
        sent += 1

    if sent or skipped_cap:
        db.audit(
            rid,
            "alerts_sent",
            f"{sent} alert(s) sent automatically, {skipped_cap} skipped by weekly cap"
        )

    return sent, skipped_cap


def run_agent(request_id, lang="English"):
    """
    Agentic workflow:
    1. validate request
    2. determine urgency
    3. determine compatible donor groups
    4. search nearby donors
    5. decide whether to widen within predefined radius steps
    6. use generative AI for communication drafts and briefing
    7. automatically alert compatible donors
    8. update request status and audit trail
    """
    db.clear_unsent(request_id)
    req = db.get_request(request_id)
    s = _Steps(request_id)
    ai_flags = []

    # 1. Validate
    missing = rules.missing_fields(req)
    labels = [rules.REQUIRED_FIELDS[k] for k in missing]
    s.log(
        "validate_request",
        ("Missing: " + ", ".join(labels)) if missing else "All required fields present"
    )

    # 2. Urgency
    urgency = rules.urgency_from_hours(req["needed_in_hours"])
    db.update_request(request_id, {"urgency": urgency})
    req["urgency"] = urgency
    s.log("set_urgency", f"{urgency} (needed within {req['needed_in_hours']} h)")

    if missing:
        msg, ai = llm.draft("followup", _ctx(req, missing=labels), lang)
        ai_flags.append(ai)

        # Keep a visible workflow record, but do not alert donors until the request is complete.
        db.add_action(request_id, "ask_requester", "Request is missing required details", msg)
        s.log("draft_messages", "Follow-up message drafted for missing details")

        brief = (
            f"Request is incomplete. Still needed: {', '.join(labels)}. "
            "Donor matching starts once these are added."
        )
        db.update_request(request_id, {"status": "Needs info", "briefing": brief})
        s.log("create_actions", "Incomplete request held safely; no donor alerts sent")

        return {
            "status": "Needs info",
            "pool": 0,
            "missing": labels,
            "ai_used": any(ai_flags),
        }

    # 3. Compatible groups
    groups = rules.compatible_donor_groups(req["blood_group"])
    s.log(
        "find_compatible_groups",
        f"{req['blood_group']} can receive from: {', '.join(groups)}"
    )

    # 4. Search donors at the initial alert radius
    radius = rules.RULES["alert_radius_km"]
    existing = {m["donor_id"] for m in db.get_matches(request_id)}
    pool, excluded = search_pool(req, radius, skip_ids=existing)

    if pool:
        db.add_matches(request_id, [(d["id"], dist) for d, dist in pool])

    total = len(db.get_matches(request_id))
    s.log(
        "search_donors",
        f"{len(pool)} potentially eligible within {radius:g} km. "
        f"Excluded by rules: {_excl_text(excluded)}"
    )

    # 5. Agent decides whether a wider search is needed.
    target = max(1, req["units"] * rules.RULES["pool_ratio"])
    current_radius = radius

    widen_steps = [r for r in rules.RULES["widen_steps_km"] if r > current_radius]

    while total < target and widen_steps and len(widen_steps) > 0:
        next_radius = widen_steps.pop(0)

        # Keep the bounded agent within its step budget.
        if s.n >= MAX_STEPS - 3:
            break

        s.log(
            "widen_radius",
            f"Pool is {total} vs target {target}; automatically expanding search to {next_radius:g} km."
        )

        existing = {m["donor_id"] for m in db.get_matches(request_id)}
        wider_pool, wider_excluded = search_pool(req, next_radius, skip_ids=existing)

        if wider_pool:
            db.add_matches(request_id, [(d["id"], dist) for d, dist in wider_pool])

        total = len(db.get_matches(request_id))
        excluded.update(wider_excluded)
        current_radius = next_radius

        s.log(
            "widen_result",
            f"{len(wider_pool)} new potentially eligible donor(s) found; total pool {total}."
        )

        if wider_pool:
            break

    s.log(
        "check_pool_size",
        f"{total} in pool, target {target}, final search radius {current_radius:g} km."
    )

    # 6. Generative AI drafts
    ctx = _ctx(req, pool=total, radius=current_radius)

    donor_msg, a1 = llm.draft("donor_alert", ctx, lang)
    bank_msg, a2 = llm.draft("bank_note", ctx, "English")
    req_msg, a3 = llm.draft("requester_update", ctx, lang)
    ai_flags += [a1, a2, a3]

    s.log(
        "draft_messages",
        "Drafted donor alert, blood bank note and requester update "
        + ("with Groq" if all([a1, a2, a3]) else "(some or all from templates)")
    )

    # 7. Automatically alert donors
    current_matches = db.get_matches(request_id)
    alertable_ids = [
        x["donor_id"] for x in current_matches
        if x["status"] == "Pooled"
    ]

    if alertable_ids:
        sent, skipped_cap = _alert_pool(
            request_id,
            alertable_ids,
            donor_msg,
            current_radius,
        )
        s.log(
            "alert_donors",
            f"Automatically alerted {sent} donor(s); {skipped_cap} skipped by weekly cap."
        )
    else:
        sent, skipped_cap = 0, 0
        s.log("alert_donors", "No potentially eligible donors available to alert.")

    # Keep AI-generated outputs as coordinator-visible records.
    if sent:
        db.add_action(
            request_id,
            "alert_donors",
            f"Automatically alerted {sent} donor(s) within {current_radius:g} km",
            donor_msg,
            json.dumps({"donor_ids": alertable_ids, "radius": current_radius}),
        )
        action_rows = db.list_actions(request_id)
        if action_rows:
            last_action = action_rows[-1]
            db.set_action(last_action["id"], status="Completed")

    db.add_action(
        request_id,
        "notify_bank",
        "Blood bank handover note prepared by AI",
        bank_msg,
    )
    bank_action = db.list_actions(request_id)[-1]
    db.set_action(bank_action["id"], status="Completed")

    db.add_action(
        request_id,
        "update_requester",
        "Requester status update prepared by AI",
        req_msg,
    )
    requester_action = db.list_actions(request_id)[-1]
    db.set_action(requester_action["id"], status="Completed")

    # 8. AI briefing
    brief, a4 = llm.briefing({
        "units": req["units"],
        "blood_group": req["blood_group"],
        "hospital": req["hospital"],
        "city": req["city"],
        "urgency": urgency,
        "pool": total,
        "radius": current_radius,
        "excluded": sum(excluded.values()),
        "target": target,
    })
    ai_flags.append(a4)

    if total == 0:
        status = "No donors found"
    else:
        status = "Awaiting donors"

    db.update_request(request_id, {
        "status": status,
        "briefing": brief,
    })
    s.log("briefing", "Generative AI situation summary written")

    return {
        "status": status,
        "pool": total,
        "missing": [],
        "ai_used": any(ai_flags),
    }


# ---------------------------------------------------------------- legacy/manual coordinator helpers
# These remain available for the dashboard/demo and preserve compatibility with the
# original project structure, but the New Request workflow no longer requires approval.

def send_alerts(action_id, text):
    act = db.get_action(action_id)
    rid = act["request_id"]
    payload = json.loads(act["payload"] or "{}")

    sent = skipped_cap = 0
    for did in payload.get("donor_ids", []):
        match = [m for m in db.get_matches(rid) if m["donor_id"] == did]
        donor = db.get_donor(did)

        if not match or not donor or match[0]["status"] != "Pooled":
            continue

        if db.alerts_this_week(did) >= rules.RULES["weekly_alert_cap"]:
            skipped_cap += 1
            continue

        db.add_notification(did, rid, text.replace("{name}", donor["name"].split()[0]))
        db.set_match_status(rid, did, "Alerted")
        sent += 1

    db.set_action(action_id, status="Approved", message=text)
    req = db.get_request(rid)

    if req["status"] not in db.CLOSED:
        db.update_request(rid, {"status": "Awaiting donors"})

    db.audit(
        rid,
        "alerts_sent",
        f"{sent} alert(s) sent, {skipped_cap} skipped by weekly cap"
    )

    note = f" {skipped_cap} skipped because they reached the weekly alert cap." if skipped_cap else ""
    return f"Sent {sent} alert(s) to donors (in-app inbox and logged mock SMS).{note}"


def expand_radius(action_id):
    act = db.get_action(action_id)
    rid = act["request_id"]
    radius = json.loads(act["payload"])["radius"]
    req = db.get_request(rid)

    existing = {m["donor_id"] for m in db.get_matches(rid)}
    pool, excluded = search_pool(req, radius, skip_ids=existing)

    db.set_action(action_id, status="Approved")
    db.audit(
        rid,
        "agent:widen_radius",
        f"{len(pool)} new donors between the previous radius and {radius:g} km. "
        f"Excluded by rules: {_excl_text(excluded)}"
    )

    if not pool:
        return f"No new potentially eligible donors found out to {radius:g} km."

    db.add_matches(rid, [(d["id"], dist) for d, dist in pool])

    msg = llm.draft("donor_alert", _ctx(req), "English")[0]
    sent, skipped = _alert_pool(
        rid,
        [d["id"] for d, _ in pool],
        msg,
        radius,
    )

    return f"Found {len(pool)} more donor(s) and automatically alerted {sent}; {skipped} skipped by weekly cap."


def approve(action_id, text):
    act = db.get_action(action_id)
    if text != act["message"]:
        db.audit(act["request_id"], "message_edited", f"action #{action_id}")

    db.audit(act["request_id"], "action_approved", f"{act['kind']} (#{action_id})")

    if act["kind"] == "alert_donors":
        return send_alerts(action_id, text)

    if act["kind"] == "widen_radius":
        return expand_radius(action_id)

    db.set_action(action_id, status="Approved", message=text)
    return "Marked as done."


def skip(action_id):
    act = db.get_action(action_id)
    db.set_action(action_id, status="Skipped")
    db.audit(act["request_id"], "action_skipped", f"{act['kind']} (#{action_id})")

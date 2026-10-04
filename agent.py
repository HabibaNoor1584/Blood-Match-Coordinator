"""Coordinator agent.

A bounded, tool-using pipeline (maximum 8 steps). Each tool call is logged to the audit
trail so the coordinator can see exactly what happened. Rules decide who is compatible and
eligible. Groq only reads text and writes messages. Nothing is sent to donors until a
human approves the action.
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
    """Tool: find compatible, potentially eligible donors inside a radius. Returns (ranked list, excluded Counter)."""
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
        return (0 if d["blood_group"] == req["blood_group"] else 1, round(dist, 1),
                -(gap if gap is not None else 9999), -d["response_rate"])

    pool.sort(key=key)
    return pool, excluded


def _ctx(req, **extra):
    return {"blood_group": req["blood_group"], "units": req["units"], "hospital": req["hospital"],
            "city": req["city"], "needed_in_hours": req["needed_in_hours"], "urgency": req["urgency"],
            "contact_name": req["contact_name"], "contact_phone": req["contact_phone"], **extra}


def _excl_text(excluded):
    if not excluded:
        return "none"
    return ", ".join(f"{rules.REASON_LABELS[k]}: {v}" for k, v in excluded.items())


def run_agent(request_id, lang="English"):
    """Validate -> urgency -> compatible groups -> search -> widen decision -> drafts -> actions -> briefing."""
    db.clear_unsent(request_id)
    req = db.get_request(request_id)
    s = _Steps(request_id)
    ai_flags = []

    # 1. validate
    missing = rules.missing_fields(req)
    labels = [rules.REQUIRED_FIELDS[k] for k in missing]
    s.log("validate_request", ("Missing: " + ", ".join(labels)) if missing else "All required fields present")

    # 2. urgency (rule based)
    urgency = rules.urgency_from_hours(req["needed_in_hours"])
    db.update_request(request_id, {"urgency": urgency})
    req["urgency"] = urgency
    s.log("set_urgency", f"{urgency} (needed within {req['needed_in_hours']} h)")

    if missing:
        msg, ai = llm.draft("followup", _ctx(req, missing=labels), lang)
        ai_flags.append(ai)
        db.add_action(request_id, "ask_requester", "Ask the requester for the missing details", msg)
        s.log("draft_messages", "Follow-up message drafted for missing details")
        brief = f"Request is incomplete. Still needed: {', '.join(labels)}. Donor matching starts once these are added."
        db.update_request(request_id, {"status": "Needs info", "briefing": brief})
        s.log("create_actions", "1 action created (ask requester)")
        return {"status": "Needs info", "pool": 0, "missing": labels, "ai_used": any(ai_flags)}

    # 3. compatible groups
    groups = rules.compatible_donor_groups(req["blood_group"])
    s.log("find_compatible_groups", f"{req['blood_group']} can receive from: {', '.join(groups)}")

    # 4. search donors at the alert radius
    radius = rules.RULES["alert_radius_km"]
    existing = {m["donor_id"] for m in db.get_matches(request_id)}
    pool, excluded = search_pool(req, radius, skip_ids=existing)
    db.add_matches(request_id, [(d["id"], dist) for d, dist in pool])
    total = len(db.get_matches(request_id))
    s.log("search_donors", f"{len(pool)} potentially eligible within {radius:g} km. Excluded by rules: {_excl_text(excluded)}")

    # 5. decide whether to propose widening (needs coordinator approval)
    target = req["units"] * rules.RULES["pool_ratio"]
    widen_to = next((r for r in rules.RULES["widen_steps_km"] if r > radius), None)
    propose = total < target and widen_to is not None
    s.log("check_pool_size", f"{total} in pool, target {target}. " + (f"Proposing {widen_to:g} km." if propose else "No widening needed."))

    # 6. drafts
    ctx = _ctx(req, pool=total)
    donor_msg, a1 = llm.draft("donor_alert", ctx, lang)
    bank_msg, a2 = llm.draft("bank_note", ctx, "English")
    req_msg, a3 = llm.draft("requester_update", ctx, lang)
    ai_flags += [a1, a2, a3]
    s.log("draft_messages", "Drafted donor alert, blood bank note and requester update "
          + ("with Groq" if all([a1, a2, a3]) else "(some or all from templates)"))

    # 7. actions for the coordinator
    if pool:
        ids = [d["id"] for d, _ in pool]
        db.add_action(request_id, "alert_donors", f"Alert {len(ids)} potentially eligible donor(s) within {radius:g} km",
                      donor_msg, json.dumps({"donor_ids": ids, "radius": radius}))
    if propose:
        db.add_action(request_id, "widen_radius",
                      f"Pool is below target ({total} of {target}). Widen the search to {widen_to:g} km?",
                      "", json.dumps({"radius": widen_to}))
    db.add_action(request_id, "notify_bank", "Send handover note to the blood bank", bank_msg)
    db.add_action(request_id, "update_requester", "Send a status update to the requester", req_msg)
    s.log("create_actions", "Action list created. Nothing is sent until the coordinator approves.")

    # 8. briefing
    brief, a4 = llm.briefing({"units": req["units"], "blood_group": req["blood_group"], "hospital": req["hospital"],
                              "city": req["city"], "urgency": urgency, "pool": total, "radius": radius,
                              "excluded": sum(excluded.values()), "target": target})
    ai_flags.append(a4)
    db.update_request(request_id, {"status": "Ready for review", "briefing": brief})
    s.log("briefing", "Situation summary written")
    return {"status": "Ready for review", "pool": total, "missing": [], "ai_used": any(ai_flags)}


# ---------------------------------------------------------------- approvals
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
    db.audit(rid, "alerts_sent", f"{sent} alert(s) sent, {skipped_cap} skipped by weekly cap")
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
    db.audit(rid, "agent:widen_radius", f"{len(pool)} new donors between the previous radius and {radius:g} km. "
             f"Excluded by rules: {_excl_text(excluded)}")
    msg_out = f"No new potentially eligible donors found out to {radius:g} km."
    if pool:
        db.add_matches(rid, [(d["id"], dist) for d, dist in pool])
        prev = [a for a in db.list_actions(rid) if a["kind"] == "alert_donors"]
        msg = prev[-1]["message"] if prev else llm.draft("donor_alert", _ctx(req), "English")[0]
        db.add_action(rid, "alert_donors", f"Alert {len(pool)} more donor(s) (up to {radius:g} km)", msg,
                      json.dumps({"donor_ids": [d["id"] for d, _ in pool], "radius": radius}))
        msg_out = f"Found {len(pool)} more donor(s). A new alert action is ready for your approval."
    total = len(db.get_matches(rid))
    target = req["units"] * rules.RULES["pool_ratio"]
    nxt = next((r for r in rules.RULES["widen_steps_km"] if r > radius), None)
    if total < target and nxt:
        db.add_action(rid, "widen_radius", f"Pool is still below target ({total} of {target}). Widen to {nxt:g} km?",
                      "", json.dumps({"radius": nxt}))
        msg_out += f" The agent suggests widening again to {nxt:g} km."
    return msg_out


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
    return "Marked as done. Copy the message and send it through your usual channel."


def skip(action_id):
    act = db.get_action(action_id)
    db.set_action(action_id, status="Skipped")
    db.audit(act["request_id"], "action_skipped", f"{act['kind']} (#{action_id})")


def alert_new_donor(donor_id):
    """A donor registered or came back online: alert them to open requests within the alert radius.
    Same rules as everywhere else (compatibility, screening, radius, weekly cap). Returns alerts sent."""
    donor = db.get_donor(donor_id)
    if not donor or rules.screen_donor(donor, db.busy_donor_ids()):
        return 0
    sent = 0
    open_reqs = db.q("SELECT * FROM requests WHERE status IN ('Ready for review','Awaiting donors')")
    for req in open_reqs:
        if req["lat"] is None or donor["blood_group"] not in rules.compatible_donor_groups(req["blood_group"]):
            continue
        if db.q("SELECT 1 AS x FROM matches WHERE request_id=? AND donor_id=?", (req["id"], donor_id)):
            continue
        dist = rules.haversine_km(req["lat"], req["lon"], donor["lat"], donor["lon"])
        if dist > rules.RULES["alert_radius_km"]:
            continue
        if db.alerts_this_week(donor_id) >= rules.RULES["weekly_alert_cap"]:
            break
        prev = [a for a in db.list_actions(req["id"]) if a["kind"] == "alert_donors" and a["message"]]
        text = prev[-1]["message"] if prev else llm._template("donor_alert", _ctx(req), "English")
        db.add_matches(req["id"], [(donor_id, dist)])
        db.set_match_status(req["id"], donor_id, "Alerted")
        db.add_notification(donor_id, req["id"], text.replace("{name}", donor["name"].split()[0]))
        db.update_request(req["id"], {"status": "Awaiting donors"})
        db.audit(req["id"], "alerts_sent", f"1 alert sent to donor #{donor_id} who registered or came online later")
        sent += 1
    return sent

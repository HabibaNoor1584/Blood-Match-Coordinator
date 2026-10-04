
"""BloodMatch Coordinator: Streamlit app.
Demo with SYNTHETIC data. Organizes information only. Makes no medical decisions.
"""
import json
from datetime import date

import pandas as pd
import streamlit as st

import agent
import db
import llm
import rules

st.set_page_config(page_title="BloodMatch Coordinator", page_icon="🩸", layout="wide")
st.markdown(
    """
    <style>
    .block-container {padding-top: 1.6rem;}
    h1, h2, h3 {color: #1F2A44;}
    .bm-banner {background:#FFF4F4; border-left:4px solid #9B1C1C; padding:.6rem .9rem;
                border-radius:4px; font-size:.88rem; margin-bottom:.8rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def _boot():
    db.init_db()
    return True


_boot()
PAGES = ["Coordinator Dashboard", "New Request", "Donor Portal", "About & Limits"]
URG = {"Critical": "🔴", "High": "🟠", "Normal": "🟢"}
ICON = {"ask_requester": "✉️", "alert_donors": "📣", "widen_radius": "🔭", "notify_bank": "🏥", "update_requester": "💬"}
HOURS = [3, 6, 12, 24, 48, 72]
FORM_DEFAULTS = {"f_group": "", "f_units": 1, "f_hospital": "", "f_city": "", "f_name": "", "f_phone": "", "f_hours": 6}

if "page" not in st.session_state:
    st.session_state.page = PAGES[0]


def banner():
    st.markdown(
        '<div class="bm-banner"><b>Demo with synthetic data.</b> This tool only organizes information. '
        "It makes no medical decisions and is not an emergency service. In a real emergency contact the hospital "
        "blood bank or local emergency services.</div>",
        unsafe_allow_html=True,
    )


def goto(rid=None):
    st.session_state.page = "Coordinator Dashboard"
    if rid:
        st.session_state.dashboard_request_selector = rid


# ================================================================ sidebar
with st.sidebar:
    st.markdown("## 🩸 BloodMatch")
    st.radio("Go to", PAGES, key="page")
    st.selectbox("Message language", ["English", "Urdu"], key="lang")
    ok, text = llm.status()
    (st.success if ok else st.warning)(text)


# ================================================================ new request
def page_new_request():
    st.title("New Blood Request")
    banner()

    for k, v in FORM_DEFAULTS.items():
        st.session_state.setdefault(k, v)

    last = st.session_state.get("last_created")
    if last:
        msg = f"Request #{last['id']} submitted. Status: {last['status']}."
        if last.get("missing"):
            msg += " Missing: " + ", ".join(last["missing"]) + "."
        else:
            msg += f" {last.get('pool', 0)} potentially eligible donors matched and alerted."
        if last.get("ai_used"):
            msg += " AI-generated messages/briefing were used."
        st.success(msg)

        if st.button("Refresh donor responses", key="refresh_request", type="primary"):
            st.rerun()

        accepted = db.accepted_donors(last["id"])
        matches = db.get_matches(last["id"])

        st.subheader(f"Request #{last['id']} status")
        if accepted:
            st.success(f"{len(accepted)} potential donor(s) have accepted the request.")
            rows = []
            for d in accepted:
                rows.append({
                    "Potential donor": d["name"],
                    "Blood group": d["blood_group"],
                    "Distance (km)": round(d["distance_km"], 2),
                    "Status": "Accepted",
                    "Screening": "Pending blood bank screening",
                })
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
            st.warning(
                "These are potentially eligible volunteers only. Final donor eligibility, compatibility "
                "and screening must be confirmed by the hospital blood bank."
            )
        else:
            alerted = sum(1 for x in matches if x["status"] == "Alerted")
            st.info(
                f"No donor has accepted yet. {alerted} compatible donor(s) have been alerted. "
                "This page checks the request again when you refresh."
            )

        st.divider()

    st.subheader("Request details")
    st.caption("The patient/requester enters the request directly. No WhatsApp message or AI extraction step is required.")

    with st.container(border=True):
        a, b, c = st.columns(3)
        a.selectbox("Patient blood group", [""] + rules.BLOOD_GROUPS, key="f_group", format_func=lambda g: g or "Select")
        b.number_input("Units needed", 1, 20, key="f_units")
        c.selectbox("Needed", HOURS, key="f_hours", format_func=lambda h: f"within {h} hours")

        d, e = st.columns(2)
        d.text_input("Hospital name", key="f_hospital")
        e.selectbox("City", [""] + list(rules.CITIES), key="f_city", format_func=lambda v: v or "Select")

        f, g = st.columns(2)
        f.text_input("Contact person", key="f_name")
        g.text_input("Contact phone", key="f_phone", placeholder="03XX-XXXXXXX")

        st.caption(
            "Distance is measured from the city centre in this demo. The system uses coded compatibility "
            "and screening rules before contacting donors."
        )

    if st.button("Submit Blood Request", type="primary"):
        required = {
            "blood_group": st.session_state.f_group,
            "units": st.session_state.f_units,
            "hospital": st.session_state.f_hospital.strip(),
            "city": st.session_state.f_city,
            "contact_name": st.session_state.f_name.strip(),
            "contact_phone": st.session_state.f_phone.strip(),
            "needed_in_hours": st.session_state.f_hours,
        }

        if not required["blood_group"]:
            st.warning("Please select the patient's blood group.")
            return
        if not required["hospital"]:
            st.warning("Please enter the hospital name.")
            return
        if not required["city"]:
            st.warning("Please select the city.")
            return
        if not required["contact_name"]:
            st.warning("Please enter a contact person's name.")
            return
        if not rules.valid_phone(required["contact_phone"]):
            st.warning("Please enter a valid contact phone number.")
            return

        data = {
            "raw_text": "",
            **required,
        }

        rid = db.create_request(data)
        db.audit(rid, "request_created", "Submitted directly by requester from the request form")

        with st.spinner("AI workflow is checking the request, matching donors, and sending alerts..."):
            res = agent.run_agent(rid, st.session_state.get("lang", "English"))

        st.session_state.last_created = {"id": rid, **res}
        for k, v in FORM_DEFAULTS.items():
            st.session_state[k] = v
        st.rerun()


# ================================================================ dashboard
def page_dashboard():
    st.title("Coordinator Dashboard")
    banner()

    if "flash" in st.session_state:
        st.success(st.session_state.pop("flash"))

    s = db.stats()
    m = st.columns(4)
    m[0].metric("Open requests", s["open"])
    m[1].metric("Registered donors", s["donors"])
    m[2].metric("Alerts sent", s["alerts"])
    m[3].metric("Donors accepted", s["accepted"])

    reqs = db.list_requests()
    if not reqs:
        st.info("No requests yet. Go to **New Request** and submit a request directly.")
        return

    labels = {
        r["id"]: f'#{r["id"]}  {URG.get(r["urgency"], "")} {r["urgency"]}  |  {r["units"] or "?"} x '
                 f'{r["blood_group"] or "?"}  |  {r["city"] or "?"}  |  {r["status"]}'
        for r in reqs
    }
    ids = list(labels)
if st.session_state.get("dashboard_request_selector") not in ids:
    st.session_state.dashboard_request_selector = ids[0]

 rid = st.selectbox(
    "Request",
    ids,
    format_func=lambda i: labels[i],
    key="dashboard_request_selector"
)
    req = db.get_request(rid)
    matches = db.get_matches(rid)
    covered = sum(1 for x in matches if x["status"] == "Accepted")

    # ================================================================
    # DONOR RESPONSE / REQUESTER UPDATE
    # ================================================================
    accepted_matches = [x for x in matches if x["status"] == "Accepted"]
    alerted_matches = [x for x in matches if x["status"] == "Alerted"]
    declined_matches = [x for x in matches if x["status"] == "Declined"]

    if st.button("🔄 Refresh donor responses", key=f"refresh_dashboard_{rid}"):
        st.rerun()

    if accepted_matches:
        st.subheader("🔔 Donor response updates")

        units_needed = req["units"] or 0

        if req["status"] == "Fulfilled":
            st.success(
                f"✅ Request fulfilled. {covered} donor(s) have accepted "
                f"the request for {units_needed} unit(s)."
            )
        else:
            remaining = max(units_needed - covered, 0)
            st.info(
                f"🩸 {covered} donor(s) have accepted this request. "
                f"{remaining} unit(s) still needed."
            )

        for donor in accepted_matches:
            with st.container(border=True):
                c1, c2 = st.columns([3, 2])

                with c1:
                    st.markdown(f"### ✅ {donor['name']} accepted")

                    st.write(
                        f"**Blood group:** {donor['blood_group']}  \n"
                        f"**Distance:** {donor['distance_km']:.2f} km  \n"
                        f"**Response:** Accepted"
                    )

                with c2:
                    st.success("Donor has confirmed availability.")
                    st.caption(
                        "The donor response has been recorded. "
                        "Final donor eligibility and screening must be "
                        "confirmed by the hospital blood bank."
                    )

    elif alerted_matches:
        st.info(
            f"📣 {len(alerted_matches)} compatible donor(s) have been alerted. "
            "Waiting for donor responses."
        )

    elif declined_matches:
        st.warning(
            "Donor alerts were sent, but no donor has accepted this request yet."
        )

    left, right = st.columns([3, 2])
    with left:
        st.subheader(f"Request #{rid}")
        st.markdown(
            f"**{req['units'] or '?'} unit(s) of {req['blood_group'] or '?'}** at **{req['hospital'] or '?'}**, "
            f"{req['city'] or '?'}  \nUrgency: {URG.get(req['urgency'], '')} {req['urgency']}  |  Status: **{req['status']}**  \n"
            f"Contact: {req['contact_name'] or 'not given'}, {req['contact_phone'] or 'no phone yet'}  \nCreated: {req['created']}"
        )

    with right:
        st.subheader("Units covered")
        units = req["units"] or 0
        st.progress(
            min(covered / units, 1.0) if units else 0.0,
            text=f"{covered} of {units} donors accepted"
        )
        st.caption(
            f"{len(matches)} donors in pool  |  "
            f"{sum(1 for x in matches if x['status'] == 'Alerted')} alerted, awaiting reply"
        )

    if req["briefing"]:
        st.info(req["briefing"])

    t1, t2, t3, t4 = st.tabs(
        ["AI Workflow", "Donor pool", "Edit request", "Agent trace and audit log"]
    )

    with t1:
        st.subheader("Automated workflow")
        st.write(
            "The requester submits the form directly. The bounded agent validates the request, applies coded donor rules, "
            "builds a donor pool, drafts AI messages/briefing, and automatically alerts eligible donors."
        )
        st.success(
            "Human review is still required for final medical donor screening. "
            "The system does not make medical decisions."
        )

        accepted = db.accepted_donors(rid)
        if accepted:
            st.subheader("Accepted potential donors")
            rows = [{
                "Donor": d["name"],
                "Group": d["blood_group"],
                "Distance (km)": round(d["distance_km"], 2),
                "Status": "Accepted",
                "Screening": "Pending blood bank screening",
            } for d in accepted]
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

        actions = db.list_actions(rid)
        completed = [a for a in actions if a["status"] != "Pending"]
        if completed:
            with st.expander(f"AI-generated workflow actions ({len(completed)})"):
                for a in completed:
                    st.write(f'**{a["status"]}**: {a["description"]}')

    with t2:
        if not matches:
            st.info("No donors pooled yet.")
        else:
            rows = []
            for x in matches:
                gap = rules.days_since(x["last_donation"])
                rows.append({
                    "Donor": x["name"],
                    "Group": x["blood_group"],
                    "Distance (km)": round(x["distance_km"], 2),
                    "Days since last donation": gap if gap is not None else "never",
                    "Past response rate": x["response_rate"],
                    "Status": x["status"],
                    "Label": "Potentially eligible, pending blood bank screening",
                })
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
            st.caption(
                "Ranked by exact group match, then distance, then longest rest since last donation, then response rate. "
                "Basic rules only. The blood bank does the real screening."
            )

        if any(x["status"] == "Alerted" for x in matches):
            if st.button("Demo helper: simulate the top alerted donor accepting"):
                top = next(x for x in matches if x["status"] == "Alerted")
                nid_rows = db.q(
                    "SELECT id FROM notifications WHERE request_id=? AND donor_id=?",
                    (rid, top["donor_id"])
                )
                if nid_rows:
                    st.session_state.flash = f"Simulated: {top['name']} -> {db.respond(nid_rows[0]['id'], True)}"
                    st.rerun()

    with t3:
        st.caption("Edit the request and rerun the AI workflow. Already alerted/accepted donors are preserved.")
        c1, c2, c3 = st.columns(3)
        group = c1.selectbox(
            "Blood group", [""] + rules.BLOOD_GROUPS,
            index=([""] + rules.BLOOD_GROUPS).index(req["blood_group"] or ""),
            key=f"e_g{rid}"
        )
        units_v = c2.number_input(
            "Units", 1, 20, int(req["units"] or 1), key=f"e_u{rid}"
        )
        hrs = c3.selectbox(
            "Needed", HOURS,
            index=HOURS.index(
                min(HOURS, key=lambda v: abs(v - (req["needed_in_hours"] or 12)))
            ),
            format_func=lambda h: f"within {h} hours",
            key=f"e_h{rid}"
        )

        d1, d2 = st.columns(2)
        hosp = d1.text_input(
            "Hospital", req["hospital"] or "", key=f"e_ho{rid}"
        )
        cities = [""] + list(rules.CITIES)
        city = d2.selectbox(
            "City",
            cities,
            index=cities.index(req["city"] or ""),
            key=f"e_c{rid}"
        )

        e1, e2 = st.columns(2)
        cname = e1.text_input(
            "Contact person", req["contact_name"] or "", key=f"e_n{rid}"
        )
        cphone = e2.text_input(
            "Contact phone", req["contact_phone"] or "", key=f"e_p{rid}"
        )

        b1, b2, _ = st.columns([2, 1.5, 3])

        if b1.button(
            "Save and re-run AI workflow",
            type="primary",
            key=f"save{rid}"
        ):
            db.update_request(rid, {
                "blood_group": group,
                "units": units_v,
                "hospital": hosp.strip(),
                "city": city,
                "contact_name": cname.strip(),
                "contact_phone": cphone.strip(),
                "needed_in_hours": hrs,
                "status": "New",
            })
            db.audit(
                rid,
                "request_edited",
                "Coordinator updated the details"
            )
            with st.spinner("Re-running the AI workflow..."):
                res = agent.run_agent(
                    rid,
                    st.session_state.get("lang", "English")
                )
            st.session_state.flash = (
                f"AI workflow re-run. Status: {res['status']}. "
                f"Pool: {res['pool']}."
            )
            st.rerun()

        if b2.button("Close request", key=f"close{rid}"):
            db.update_request(rid, {"status": "Closed"})
            db.audit(
                rid,
                "request_closed",
                "Closed by coordinator"
            )
            st.rerun()

    with t4:
        log = db.get_audit(rid)
        trace = [r for r in log if r["event"].startswith("agent:")]
        st.markdown("**Agent steps**")
        for i, r in enumerate(trace, 1):
            st.write(
                f"{i}. `{r['event'][6:]}`: {r['detail']}"
            )

        with st.expander("Full audit log"):
            st.dataframe(
                pd.DataFrame(log)[["ts", "event", "detail"]]
                if log else pd.DataFrame(),
                width="stretch",
                hide_index=True
            )


# ================================================================ donor portal

def _donor_form_register():
    st.subheader("Register as a volunteer donor")
    st.caption(
        "You will be alerted when a compatible request is within 3 km of your location. "
        "You can pause or delete your profile at any time."
    )

    city = st.selectbox("City", list(rules.CITIES), key="donor_register_city")
    clat, clon = rules.CITIES[city]

    with st.form("register"):
        a, b = st.columns(2)
        name = a.text_input("Full name")
        phone = b.text_input(
            "Phone number",
            placeholder="03XX-XXXXXXX"
        )

        c, d = st.columns(2)
        group = c.selectbox("Blood group", rules.BLOOD_GROUPS)
        age = d.number_input(
            "Age (adults only)",
            18,
            65,
            25
        )

        never = st.checkbox("I have never donated blood")

        last = st.date_input(
            "Date of last donation",
            value=None,
            max_value=date.today(),
            disabled=never
        )

        with st.expander("Fine-tune your location (optional)"):
            st.caption(
                "Defaults to your city centre. In a real deployment this would come "
                "from your device with your permission."
            )
            lat = st.number_input(
                "Latitude",
                value=float(clat),
                format="%.4f",
                key=f"lat_{city}"
            )
            lon = st.number_input(
                "Longitude",
                value=float(clon),
                format="%.4f",
                key=f"lon_{city}"
            )

        consent = st.checkbox(
            "I agree to be contacted about blood requests near me. "
            "I understand the blood bank will do the final medical screening "
            "and that I can delete my profile at any time."
        )

        if st.form_submit_button("Register", type="primary"):
            if not name.strip() or not rules.valid_phone(phone):
                st.error(
                    "Please enter your name and a valid phone number."
                )

            elif not consent:
                st.error(
                    "Consent is required so we can contact you."
                )

            elif db.find_donor_by_phone(phone):
                st.error(
                    "This phone number is already registered. "
                    "Use the Sign in tab."
                )

            else:
                did = db.add_donor({
                    "name": name.strip(),
                    "phone": phone.strip(),
                    "blood_group": group,
                    "age": int(age),
                    "city": city,
                    "lat": lat,
                    "lon": lon,
                    "last_donation": (
                        None
                        if never or not last
                        else last.isoformat()
                    ),
                    "consent": True,
                })

                st.session_state.donor_id = did
                st.rerun()


# ================================================================
# DONOR INBOX
# ================================================================

@st.fragment(run_every="5s")
def _inbox(donor_id):
    items = db.donor_notifications(donor_id)

    st.subheader("📬 Your Blood Donation Requests")
    st.caption(
        "New blood requests matching your donor profile appear here. "
        "Review each request and choose whether you are willing to donate."
    )

    if not items:
        st.info(
            "No blood requests are available for you right now. "
            "When a compatible request is created within the matching radius, "
            "it will appear here."
        )
        return

    for n in items:

        with st.container(border=True):

            # ---------------------------------------------------------
            # CASE INFORMATION
            # ---------------------------------------------------------
            st.markdown(
                f"## 🩸 {URG.get(n['urgency'], '')} "
                f"{n['urgency']} Blood Request"
            )

            c1, c2, c3 = st.columns(3)

            with c1:
                st.metric(
                    "Blood group needed",
                    n["blood_group"]
                )

            with c2:
                st.metric(
                    "Hospital",
                    n["hospital"]
                )

            with c3:
                st.metric(
                    "City",
                    n["city"]
                )

            st.markdown(
                f"**Request created:** {n['created']}  \n"
                f"**Alert channel:** {n['channel']}"
            )

            st.divider()

            # ---------------------------------------------------------
            # DONATION REQUEST
            # ---------------------------------------------------------
            st.subheader("📣 Donation Request")

            st.write(n["message"])

            ms = n["match_status"]

            # ---------------------------------------------------------
            # DONOR MUST ACCEPT OR DECLINE
            # ---------------------------------------------------------
            if ms == "Alerted" and n["req_status"] not in db.CLOSED:

                st.warning(
                    "🩸 This blood request is waiting for your response."
                )

                st.markdown(
                    """
                    ### Are you willing and available to donate blood for this case?

                    By selecting **I am willing to donate**, you are telling the
                    coordinator that you are willing to proceed with this donation
                    request.

                    Your acceptance does not replace hospital blood-bank screening.
                    Final donor eligibility will be confirmed by the hospital.
                    """
                )

                c1, c2, _ = st.columns([1.8, 1.8, 3])

                with c1:
                    if st.button(
                        "✅ I am willing to donate",
                        key=f"accept_{n['id']}",
                        type="primary",
                        use_container_width=True,
                    ):
                        res = db.respond(
                            n["id"],
                            True
                        )

                        if res == "busy":
                            st.error(
                                "You already accepted another active blood request."
                            )
                        else:
                            st.success(
                                "✅ Your willingness to donate has been recorded. "
                                "The coordinator has been notified."
                            )

                        st.rerun(scope="fragment")

                with c2:
                    if st.button(
                        "❌ I cannot donate",
                        key=f"decline_{n['id']}",
                        use_container_width=True,
                    ):
                        db.respond(
                            n["id"],
                            False
                        )

                        st.info(
                            "You have declined this blood request."
                        )

                        st.rerun(scope="fragment")

            # ---------------------------------------------------------
            # DONOR ACCEPTED
            # ---------------------------------------------------------
            elif ms == "Accepted":

                st.success(
                    "✅ You accepted this blood donation request."
                )

                st.markdown(
                    """
                    ### 🤝 Donation connection confirmed

                    You have indicated that you are willing to donate.
                    Your acceptance has been recorded and the coordinator
                    has been notified.
                    """
                )

                st.subheader("📞 Requester / Patient Contact")

                st.info(
                    f"**Requester / Patient representative:** "
                    f"{n['contact_name'] or 'Not provided'}  \n\n"
                    f"**Phone:** {n['contact_phone'] or 'Not provided'}"
                )

                st.subheader("🏥 Donation Location")

                st.info(
                    f"**Hospital:** {n['hospital']}  \n"
                    f"**City:** {n['city']}"
                )

                st.success(
                    "The requester can now contact you regarding the donation."
                )

                st.caption(
                    "Please confirm with the hospital blood bank before travelling. "
                    "The blood bank will perform the final donor screening."
                )

            # ---------------------------------------------------------
            # DONOR DECLINED
            # ---------------------------------------------------------
            elif ms == "Declined":

                st.error(
                    "❌ You declined this blood donation request."
                )

                st.caption(
                    "You can wait for another compatible blood request."
                )

            # ---------------------------------------------------------
            # REQUEST CLOSED
            # ---------------------------------------------------------
            elif n["req_status"] in db.CLOSED and ms != "Accepted":

                st.info(
                    "🔒 This blood request has been closed before you accepted it."
                )


def _donor_home(donor):
    top = st.columns([4, 1])
    top[0].subheader(
        f"Hello, {donor['name'].split()[0]}"
    )

    if top[1].button("Sign out"):
        st.session_state.pop(
            "donor_id",
            None
        )
        st.rerun()

    days = rules.days_since(
        donor["last_donation"]
    )

    st.caption(
        f"{donor['blood_group']}  |  {donor['city']}  |  last donation: "
        f"{'never' if days is None else f'{days} days ago'}  |  "
        f"alerts within {rules.RULES['alert_radius_km']:g} km"
    )

    avail = st.toggle(
        "I am available to donate",
        value=bool(donor["available"]),
        key=f"avail_{donor['id']}"
    )

    if avail != bool(donor["available"]):
        db.update_donor(
            donor["id"],
            available=1 if avail else 0
        )
        st.rerun()

    _inbox(donor["id"])

    with st.expander("Delete my profile"):
        st.caption(
            "This removes your details and alerts permanently."
        )

        if (
            st.checkbox("I understand", key="del_ok")
            and st.button("Delete my profile")
        ):
            db.delete_donor(
                donor["id"]
            )
            st.session_state.pop(
                "donor_id",
                None
            )
            st.rerun()


def page_donor():
    st.title("Donor Portal")
    banner()

    donor = (
        db.get_donor(st.session_state.get("donor_id"))
        if st.session_state.get("donor_id")
        else None
    )

    if donor:
        _donor_home(donor)
        return

    t1, t2 = st.tabs(
        ["Register", "Sign in"]
    )

    with t1:
        _donor_form_register()

    with t2:
        phone = st.text_input(
            "Phone number you registered with",
            key="si_phone"
        )

        st.caption(
            "Demo sign-in only. A real deployment needs OTP verification."
        )

        if st.button(
            "Sign in",
            type="primary"
        ):
            d = db.find_donor_by_phone(phone)

            if d:
                st.session_state.donor_id = d["id"]
                st.rerun()

            st.error(
                "No donor found with that number."
            )

        helpers = db.donors_with_notifications()

        if helpers:
            with st.expander(
                "Demo helper: sign in as a synthetic donor who has an alert"
            ):
                pick = st.selectbox(
                    "Donor",
                    helpers,
                    format_func=lambda d:
                        f"{d['name']} ({d['blood_group']}, {d['city']})"
                )

                if st.button(
                    "Sign in as this donor"
                ):
                    st.session_state.donor_id = pick["id"]
                    st.rerun()


# ================================================================ about
def page_about():
    st.title("About and Limits")
    st.markdown(
        """
**What it does.** A patient/requester submits a structured blood request directly. A bounded AI agent validates
the request, applies predefined compatibility and screening rules, organizes a pool of nearby potentially eligible
donors, drafts communications, and automatically alerts compatible donors.

**AI components.**
- **Agentic AI:** a bounded tool-using agent validates, searches, evaluates pool size, can widen the search within
  predefined limits, drafts communications, sends donor alerts, and logs its steps.
- **Generative AI:** Groq/gpt-oss drafts donor alerts, blood-bank handover notes, requester updates and a short briefing.
- **AI workflow / business process automation:** the complete request-to-donor-response process is automated through
  validation, rule checks, donor matching, alerting, response tracking and requester status updates.

**Safety boundary.** Rules written in code decide compatibility and basic demo eligibility. The AI model does not make
medical decisions. Donors are labelled potentially eligible pending blood-bank screening.

**Not included.** Final eligibility, cross-matching or lab work, blood stock management, payments, real patient data,
verification of donor claims, emergency dispatch, or a guarantee of donor response.

**Known limits of this demo.** Alerts are an in-app inbox plus a logged mock SMS. Location is a city centre or
manually entered coordinates. Sign-in is by phone number only. Streamlit with SQLite suits a demo or pilot, not
national traffic, and data resets when the cloud app restarts.
        """
    )

    st.subheader("Rules in use")
    st.json(rules.RULES)

    st.subheader("Reset demo data")
    st.caption(
        "Deletes all requests, alerts and registered donors, then reloads 300 synthetic donors."
    )

    if (
        st.checkbox("I understand this deletes everything")
        and st.button("Reset demo data")
    ):
        db.reset_all()

        for k in (
            "donor_id",
            "selected_request",
            "last_created"
        ):
            st.session_state.pop(
                k,
                None
            )

        st.success(
            "Demo data reset."
        )


# ================================================================
# APP ROUTING
# ================================================================

{
    "Coordinator Dashboard": page_dashboard,
    "New Request": page_new_request,
    "Donor Portal": page_donor,
    "About & Limits": page_about

}[st.session_state.page]()
{"Coordinator Dashboard": page_dashboard, "New Request": page_new_request,
 "Donor Portal": page_donor, "About & Limits": page_about}[st.session_state.page]()

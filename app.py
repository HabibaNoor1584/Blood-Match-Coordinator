"""BloodMatch Coordinator: Streamlit app.

Demo with SYNTHETIC data. Organizes information only. Makes no medical decisions.
"""
import hmac
import html
from datetime import date

import pandas as pd
import streamlit as st

import agent
import db
import llm
import rules

try:
    import pydeck as pdk
except Exception:  # the map falls back to st.map
    pdk = None

st.set_page_config(page_title="BloodMatch Coordinator", page_icon="🩸", layout="wide")

# ================================================================ styling
st.markdown(
    """
    <style>
    .stApp {background: linear-gradient(180deg,#FFF7F7 0%,#F5F7FB 55%,#EEF2F8 100%);}
    .block-container {padding-top: 1.2rem; max-width: 1200px;}
    section[data-testid="stSidebar"] {background: linear-gradient(180deg,#FFFFFF,#FDECEC); border-right: 1px solid #F3D1D1;}

    .bm-brand {display:flex; align-items:center; gap:.7rem; padding:.2rem 0 .9rem 0;}
    .bm-brand .logo {width:44px; height:44px; border-radius:13px; display:flex; align-items:center; justify-content:center;
        font-size:1.4rem; background:linear-gradient(135deg,#DC2626,#7F1D1D); box-shadow:0 4px 10px rgba(185,28,28,.35);}
    .bm-brand b {font-size:1.12rem; color:#7F1D1D; display:block; line-height:1.1;}
    .bm-brand small {color:#64748B;}

    .bm-hero {display:flex; gap:1rem; align-items:center; color:#fff; padding:1.3rem 1.6rem; margin-bottom:1rem;
        background:linear-gradient(120deg,#B91C1C 0%,#7F1D1D 48%,#1E293B 100%); border-radius:18px;
        box-shadow:0 10px 25px rgba(127,29,29,.25);}
    .bm-hero .icon {font-size:2.2rem; width:64px; height:64px; border-radius:16px; display:flex; align-items:center;
        justify-content:center; background:rgba(255,255,255,.16); flex-shrink:0;}
    .bm-hero h1 {color:#fff !important; margin:0 !important; padding:0 !important; font-size:1.8rem !important;}
    .bm-hero p {color:#FBD5D5; margin:.25rem 0 0 0; font-size:.97rem;}

    .bm-banner {background:#FFF1F1; border:1px solid #F8CACA; border-left:5px solid #B91C1C; color:#7F1D1D;
        padding:.6rem .9rem; border-radius:10px; font-size:.86rem; margin-bottom:.9rem;}

    .bm-card {background:#fff; border:1px solid #F1D5D5; border-radius:16px; padding:1rem 1.2rem;
        box-shadow:0 4px 14px rgba(15,23,42,.06); margin-bottom:.8rem;}
    .bm-row {display:flex; gap:1rem; align-items:center;}
    .bm-bt {min-width:58px; height:58px; border-radius:50%; display:flex; align-items:center; justify-content:center;
        color:#fff; font-weight:800; font-size:1.25rem; background:linear-gradient(135deg,#EF4444,#991B1B);
        box-shadow:0 4px 10px rgba(185,28,28,.35); flex-shrink:0;}
    .bm-title {font-size:1.12rem; font-weight:700; color:#1E293B;}
    .bm-muted {color:#64748B; font-size:.9rem;}
    .bm-kv {display:flex; flex-wrap:wrap; gap:1.4rem; margin-top:.7rem; font-size:.9rem; color:#334155;}
    .bm-kv span {color:#94A3B8; display:block; font-size:.74rem; text-transform:uppercase; letter-spacing:.04em;}

    .bm-pill {display:inline-block; padding:.12rem .65rem; border-radius:999px; font-size:.78rem; font-weight:700; margin:.25rem .3rem 0 0;}
    .bm-red {background:#FEE2E2; color:#991B1B;} .bm-orange {background:#FFEDD5; color:#9A3412;}
    .bm-green {background:#DCFCE7; color:#166534;} .bm-blue {background:#DBEAFE; color:#1E40AF;}
    .bm-grey {background:#F1F5F9; color:#475569;}

    .bm-steps {display:flex; gap:.5rem; margin:.4rem 0 1rem 0;}
    .bm-step {flex:1; text-align:center; padding:.6rem .3rem; border-radius:12px; background:#F1F5F9; color:#64748B;
        font-weight:600; font-size:.84rem; border:1px solid #E2E8F0;}
    .bm-step.done {background:#DCFCE7; color:#166534; border-color:#86EFAC;}
    .bm-step.now {background:#FEE2E2; color:#991B1B; border-color:#FCA5A5; box-shadow:0 0 0 3px rgba(220,38,38,.12);}

    .bm-msg {background:#F8FAFC; border-left:4px solid #CBD5E1; border-radius:8px; padding:.7rem .9rem; color:#334155;
        font-size:.93rem; margin:.5rem 0 .8rem 0;}
    .bm-donorhead {display:flex; gap:.9rem; align-items:center; padding:.8rem 1rem; border-radius:14px; margin-bottom:.4rem;
        background:linear-gradient(90deg,#FEF2F2,#FFFFFF); border:1px solid #FECACA;}
    .bm-donorhead.High {background:linear-gradient(90deg,#FFF7ED,#FFFFFF); border-color:#FED7AA;}
    .bm-donorhead.Normal {background:linear-gradient(90deg,#F0FDF4,#FFFFFF); border-color:#BBF7D0;}

    .bm-feature {background:#fff; border:1px solid #F1D5D5; border-top:5px solid #B91C1C; border-radius:14px;
        padding:1rem 1.1rem; height:100%; box-shadow:0 4px 14px rgba(15,23,42,.05);}
    .bm-feature h4 {margin:0 0 .4rem 0; color:#7F1D1D;} .bm-feature p {margin:0; color:#475569; font-size:.92rem;}

    [data-testid="stMetric"] {background:#fff; border:1px solid #F1D5D5; border-left:5px solid #B91C1C; border-radius:14px;
        padding:.8rem 1rem; box-shadow:0 2px 8px rgba(15,23,42,.05);}
    [data-testid="stMetricLabel"] {color:#64748B;}
    [data-testid="stVerticalBlockBorderWrapper"] {border-radius:16px;}
    .stButton > button, .stFormSubmitButton > button {border-radius:11px; font-weight:600; padding:.45rem 1.1rem;}
    button[data-testid="stBaseButton-primary"], button[data-testid="stBaseButton-primaryFormSubmit"] {
        background:linear-gradient(135deg,#DC2626,#991B1B); border:none; color:#fff; box-shadow:0 4px 10px rgba(185,28,28,.3);}
    button[data-testid="stBaseButton-primary"]:hover, button[data-testid="stBaseButton-primaryFormSubmit"]:hover {
        background:linear-gradient(135deg,#EF4444,#B91C1C); color:#fff;}
    .stTabs [data-baseweb="tab"] {font-weight:600;}
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def _boot():
    db.init_db()
    return True


_boot()

PAGES = ["New Request", "Donor Portal", "Coordinator Dashboard", "About & Limits"]
PAGE_ICON = {"New Request": "🩸", "Donor Portal": "🙋", "Coordinator Dashboard": "📊", "About & Limits": "ℹ️"}
URG = {"Critical": "🔴", "High": "🟠", "Normal": "🟢"}
URG_KIND = {"Critical": "red", "High": "orange", "Normal": "green"}
STATUS_KIND = {"Needs info": "orange", "Ready for review": "blue", "Awaiting donors": "blue",
               "Fulfilled": "green", "Closed": "grey", "New": "grey"}
MATCH_KIND = {"Pooled": "grey", "Alerted": "orange", "Accepted": "green", "Declined": "red"}
HOURS = [3, 6, 12, 24, 48, 72]
OTHER = "Other (type the name below)"
FORM_DEFAULTS = {"f_group": "", "f_units": 1, "f_hospital": "", "f_city": "", "f_name": "", "f_phone": "", "f_hours": 6}

if "page" not in st.session_state:
    st.session_state.page = PAGES[0]


# ================================================================ helpers
def esc(x):
    return html.escape(str(x if x is not None else ""))


def pill(text, kind="grey"):
    return f'<span class="bm-pill bm-{kind}">{esc(text)}</span>'


def hero(icon, title, subtitle):
    st.markdown(
        f'<div class="bm-hero"><div class="icon">{icon}</div><div><h1>{esc(title)}</h1><p>{esc(subtitle)}</p></div></div>',
        unsafe_allow_html=True,
    )


def banner():
    st.markdown(
        '<div class="bm-banner"><b>Demo with synthetic data.</b> This tool only organizes information. '
        "It makes no medical decisions and is not an emergency service. In a real emergency contact the hospital "
        "blood bank or local emergency services.</div>",
        unsafe_allow_html=True,
    )


def demo_mode():
    return llm.secret("DEMO_MODE").strip().lower() not in ("false", "0", "no", "off")


def coordinator_ok():
    """Optional PIN gate for coordinator-only screens (set COORDINATOR_PIN in secrets)."""
    pin = llm.secret("COORDINATOR_PIN")
    if not pin or st.session_state.get("coord_ok"):
        return True
    st.markdown("#### 🔒 Coordinator access")
    with st.form("pin_form"):
        entered = st.text_input("Coordinator PIN", type="password")
        if st.form_submit_button("Unlock", type="primary"):
            if hmac.compare_digest(entered.encode(), pin.encode()):
                st.session_state.coord_ok = True
                st.rerun()
            st.error("Wrong PIN.")
    return False


def accepted_donors(rid):
    return [m for m in db.get_matches(rid) if m["status"] == "Accepted"]


def auto_dispatch(rid):
    """Send donor alerts automatically, and widen the search (5 km, then 10 km) if the pool is too small."""
    for _ in range(5):
        pending = [a for a in db.list_actions(rid)
                   if a["status"] == "Pending" and a["kind"] in ("alert_donors", "widen_radius")]
        if not pending:
            break
        for a in pending:
            agent.approve(a["id"], a["message"])


def run_workflow(rid):
    res = agent.run_agent(rid, st.session_state.get("lang", "English"))
    if res["status"] != "Needs info":
        auto_dispatch(rid)
    return res


def stage_of(req, matches):
    contacted = sum(1 for m in matches if m["status"] in ("Alerted", "Accepted", "Declined"))
    accepted = sum(1 for m in matches if m["status"] == "Accepted")
    if req["status"] == "Fulfilled":
        return 4
    if accepted:
        return 3
    if contacted:
        return 2
    return 1


def stepper(stage):
    names = ["Request sent", "Donors alerted", "Donor accepted", "Fulfilled"]
    out = []
    for i, n in enumerate(names, 1):
        cls = "done" if i < stage or stage == 4 else ("now" if i == stage else "")
        mark = "✓ " if cls == "done" else ""
        out.append(f'<div class="bm-step {cls}">{mark}{n}</div>')
    st.markdown(f'<div class="bm-steps">{"".join(out)}</div>', unsafe_allow_html=True)


def request_card(req, show_phone=True):
    pills = pill(f"{URG.get(req['urgency'], '')} {req['urgency']}", URG_KIND.get(req["urgency"], "grey")) + \
        pill(req["status"], STATUS_KIND.get(req["status"], "grey"))
    phone = f'<div><span>Contact</span>{esc(req["contact_name"] or "not given")}'
    phone += f', {esc(req["contact_phone"])}</div>' if show_phone else "</div>"
    st.markdown(
        f"""
        <div class="bm-card">
          <div class="bm-row">
            <div class="bm-bt">{esc(req['blood_group'] or '?')}</div>
            <div>
              <div class="bm-title">{esc(req['units'] or '?')} unit(s) needed</div>
              <div class="bm-muted">{esc(req['hospital'] or '?')}, {esc(req['city'] or '?')}</div>
              <div>{pills}</div>
            </div>
          </div>
          <div class="bm-kv">
            <div><span>Request</span>#{req['id']}</div>
            <div><span>Needed</span>within {esc(req['needed_in_hours'])} h</div>
            {phone}
            <div><span>Created</span>{esc(req['created'])}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_map(req, matches):
    """Hospital, the 3 km alert radius, and donors coloured by status."""
    if req["lat"] is None or req["lon"] is None:
        st.info("This request has no map location yet.")
        return
    colors = {"Pooled": [37, 99, 235, 210], "Alerted": [245, 158, 11, 230],
              "Accepted": [22, 163, 74, 240], "Declined": [148, 163, 184, 170]}
    donors = pd.DataFrame([{
        "lat": m["dlat"], "lon": m["dlon"], "name": m["name"], "status": m["status"],
        "color": colors.get(m["status"], [100, 116, 139, 200]),
    } for m in matches if m.get("dlat") is not None])
    hosp = pd.DataFrame([{"lat": req["lat"], "lon": req["lon"], "name": f"{req['hospital']} (hospital)", "status": "Hospital"}])
    if pdk is None:
        pts = pd.concat([hosp[["lat", "lon"]], donors[["lat", "lon"]] if len(donors) else None])
        st.map(pts, latitude="lat", longitude="lon")
        return
    radius_m = rules.RULES["alert_radius_km"] * 1000
    layers = [
        pdk.Layer("ScatterplotLayer", hosp, get_position="[lon, lat]", get_radius=radius_m,
                  get_fill_color=[185, 28, 28, 28], get_line_color=[185, 28, 28, 170],
                  stroked=True, line_width_min_pixels=2, pickable=False),
        pdk.Layer("ScatterplotLayer", hosp, get_position="[lon, lat]", get_radius=140,
                  get_fill_color=[153, 27, 27, 255], pickable=True),
    ]
    if len(donors):
        layers.append(pdk.Layer("ScatterplotLayer", donors, get_position="[lon, lat]", get_radius=95,
                                get_fill_color="color", pickable=True))
    view = pdk.ViewState(latitude=float(req["lat"]), longitude=float(req["lon"]), zoom=12)
    st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=view,
                             tooltip={"text": "{name}\n{status}"}))
    st.caption("Red circle: 3 km alert radius around the hospital. Dots: blue pooled, orange alerted, green accepted, grey declined.")


# ================================================================ sidebar
with st.sidebar:
    st.markdown('<div class="bm-brand"><div class="logo">🩸</div><div><b>BloodMatch</b><small>Coordinator</small></div></div>',
                unsafe_allow_html=True)
    st.radio("Go to", PAGES, key="page", format_func=lambda p: f"{PAGE_ICON[p]}  {p}")
    st.selectbox("Message language", ["English", "Urdu"], key="lang")
    ok, text = llm.status()
    (st.success if ok else st.warning)(text)
    if llm.secret("COORDINATOR_PIN") and st.session_state.get("coord_ok"):
        if st.button("🔒 Lock coordinator screens"):
            st.session_state.coord_ok = False
            st.rerun()


# ================================================================ new request
@st.fragment(run_every="5s")
def _request_status(rid):
    req = db.get_request(rid)
    if not req:
        st.info("Request not found.")
        return
    matches = db.get_matches(rid)
    accepted = [m for m in matches if m["status"] == "Accepted"]
    contacted = sum(1 for m in matches if m["status"] in ("Alerted", "Accepted", "Declined"))

    st.subheader(f"Request #{rid} live status")
    st.caption("This panel updates by itself every few seconds.")
    stepper(stage_of(req, matches))
    request_card(req)

    if accepted:
        st.success(f"🎉 {len(accepted)} potential donor(s) have accepted your request. They will contact you on the number you gave.")
        rows = [{"Potential donor": d["name"], "Blood group": d["blood_group"],
                 "Distance (km)": round(d["distance_km"], 2), "Screening": "Pending blood bank screening"} for d in accepted]
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        st.warning("These are potentially eligible volunteers only. Final eligibility, compatibility and screening "
                   "must be confirmed by the hospital blood bank.")
    else:
        st.info(f"No donor has accepted yet. {contacted} compatible donor(s) have been alerted. "
                "Please also contact the hospital blood bank directly.")


def page_new_request():
    hero("🩸", "Request Blood", "Tell us what is needed. Compatible donors near the hospital are alerted within seconds.")
    banner()

    if st.session_state.pop("clear_form", False):
        for k, v in FORM_DEFAULTS.items():
            st.session_state[k] = v
        for k in [k for k in st.session_state if str(k).startswith("f_hosp_")]:
            del st.session_state[k]
    for k, v in FORM_DEFAULTS.items():
        st.session_state.setdefault(k, v)

    note = st.session_state.pop("submit_note", None)
    if note:
        st.success(note)

    current = st.session_state.get("current_request")
    if current:
        _request_status(current)
        st.divider()

    st.subheader("New request details")
    with st.container(border=True):
        a, b, c = st.columns(3)
        a.selectbox("Patient blood group", [""] + rules.BLOOD_GROUPS, key="f_group", format_func=lambda g: g or "Select")
        b.number_input("Units needed", 1, 20, key="f_units")
        c.selectbox("Needed", HOURS, key="f_hours", format_func=lambda h: f"within {h} hours")

        d, e = st.columns(2)
        d.selectbox("City", [""] + list(rules.CITIES), key="f_city", format_func=lambda v: v or "Select")
        city = st.session_state.f_city
        hosp_choice = None
        if city:
            opts = [h[0] for h in rules.HOSPITALS[city]] + [OTHER]
            hosp_choice = e.selectbox("Hospital", opts, key=f"f_hosp_{city}")
        else:
            e.selectbox("Hospital", ["Select a city first"], disabled=True)
        if hosp_choice == OTHER:
            st.text_input("Hospital name", key="f_hospital", placeholder="Type the hospital name")

        f, g = st.columns(2)
        f.text_input("Contact person", key="f_name")
        g.text_input("Contact phone", key="f_phone", placeholder="03XX-XXXXXXX")
        st.caption("Demo hospitals are fictional and sit near each city centre, so the 3 km radius is meaningful. "
                   "If you pick Other, distance is measured from the city centre.")

    if st.button("🩸 Submit Blood Request", type="primary"):
        hospital, lat, lon = "", None, None
        if city and hosp_choice and hosp_choice != OTHER:
            hospital, lat, lon = next(h for h in rules.HOSPITALS[city] if h[0] == hosp_choice)
        else:
            hospital = st.session_state.f_hospital.strip()
        required = {
            "blood_group": st.session_state.f_group, "units": st.session_state.f_units, "hospital": hospital,
            "city": city, "contact_name": st.session_state.f_name.strip(),
            "contact_phone": st.session_state.f_phone.strip(), "needed_in_hours": st.session_state.f_hours,
        }
        if not required["blood_group"]:
            st.warning("Please select the patient's blood group.")
            return
        if not required["city"]:
            st.warning("Please select the city.")
            return
        if not required["hospital"]:
            st.warning("Please choose a hospital or type its name.")
            return
        if not required["contact_name"]:
            st.warning("Please enter a contact person's name.")
            return
        if not rules.valid_phone(required["contact_phone"]):
            st.warning("Please enter a valid contact phone number.")
            return

        rid = db.create_request({"raw_text": "", "lat": lat, "lon": lon, **required})
        db.audit(rid, "request_created", "Submitted directly by requester from the request form")
        with st.spinner("Checking the request, matching donors and sending alerts..."):
            res = run_workflow(rid)
        st.session_state.current_request = rid
        st.session_state.submit_note = (f"Request #{rid} submitted. Keep this number to track it later."
                                        + (" AI-generated messages were used." if res.get("ai_used") else ""))
        st.session_state.clear_form = True
        st.rerun()

    with st.expander("Track an existing request"):
        t1, t2 = st.columns(2)
        tid = t1.text_input("Request number", key="track_id_in")
        tph = t2.text_input("Contact phone used in the request", key="track_ph_in")
        if st.button("Track request"):
            r = db.get_request(int(tid)) if tid.strip().isdigit() else None
            digits = lambda s: "".join(ch for ch in str(s) if ch.isdigit())[-10:]
            if r and digits(r["contact_phone"]) == digits(tph) and len(digits(tph)) == 10:
                st.session_state.current_request = r["id"]
                st.rerun()
            st.error("No request found with those details.")


# ================================================================ dashboard
def page_dashboard():
    hero("📊", "Coordinator Dashboard", "Monitor requests, the donor pool, responses and every step the agent took.")
    if not coordinator_ok():
        return
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
        st.info("No requests yet. Go to **New Request** and submit a request.")
        return

    labels = {
        r["id"]: f'#{r["id"]}  {URG.get(r["urgency"], "")} {r["urgency"]}  |  {r["units"] or "?"} x '
                 f'{r["blood_group"] or "?"}  |  {r["city"] or "?"}  |  {r["status"]}'
        for r in reqs
    }
    ids = list(labels)
    if st.session_state.get("dashboard_request_selector") not in ids:
        st.session_state.dashboard_request_selector = ids[0]
    rid = st.selectbox("Request", ids, format_func=lambda i: labels[i], key="dashboard_request_selector")

    req = db.get_request(rid)
    matches = db.get_matches(rid)
    accepted_matches = [x for x in matches if x["status"] == "Accepted"]
    alerted_matches = [x for x in matches if x["status"] == "Alerted"]
    declined_matches = [x for x in matches if x["status"] == "Declined"]
    covered = len(accepted_matches)
    units = req["units"] or 0

    left, right = st.columns([3, 2])
    with left:
        request_card(req)
    with right:
        st.markdown("##### Units covered")
        st.progress(min(covered / units, 1.0) if units else 0.0, text=f"{covered} of {units} donors accepted")
        st.caption(f"{len(matches)} donors in pool  |  {len(alerted_matches)} alerted, awaiting reply")
        if st.button("🔄 Refresh donor responses", key=f"refresh_dashboard_{rid}"):
            st.rerun()

    stepper(stage_of(req, matches))

    if accepted_matches:
        if req["status"] == "Fulfilled":
            st.success(f"✅ Request fulfilled. {covered} donor(s) accepted for {units} unit(s).")
        else:
            st.info(f"🩸 {covered} donor(s) have accepted. {max(units - covered, 0)} unit(s) still needed.")
        for donor in accepted_matches:
            with st.container(border=True):
                c1, c2 = st.columns([3, 2])
                c1.markdown(f"**✅ {esc(donor['name'])}** accepted  \n"
                            f"{esc(donor['blood_group'])}  |  {donor['distance_km']:.2f} km away")
                c2.caption("Final eligibility and screening must be confirmed by the hospital blood bank.")
    elif alerted_matches:
        st.info(f"📣 {len(alerted_matches)} compatible donor(s) alerted. Waiting for responses.")
    elif declined_matches:
        st.warning("Alerts were sent, but no donor has accepted this request yet.")

    if req["briefing"]:
        st.info(req["briefing"])

    t0, t1, t2, t3, t4 = st.tabs(["🗺️ Map", "👥 Donor pool", "🤖 AI workflow", "✏️ Edit request", "🧾 Agent trace"])

    with t0:
        render_map(req, matches)

    with t1:
        if not matches:
            st.info("No donors pooled yet.")
        else:
            rows = []
            for x in matches:
                gap = rules.days_since(x["last_donation"])
                rows.append({
                    "Donor": x["name"], "Group": x["blood_group"], "Distance (km)": round(x["distance_km"], 2),
                    "Days since last donation": str(gap) if gap is not None else "never",
                    "Past response rate": x["response_rate"], "Status": x["status"],
                    "Label": "Potentially eligible, pending blood bank screening",
                })
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
            st.caption("Ranked by exact group match, then distance, then longest rest since last donation, then response "
                       "rate. Basic rules only. The blood bank does the real screening.")
        if demo_mode() and alerted_matches:
            if st.button("Demo helper: simulate the top alerted donor accepting"):
                top = alerted_matches[0]
                nid_rows = db.q("SELECT id FROM notifications WHERE request_id=? AND donor_id=?", (rid, top["donor_id"]))
                if nid_rows:
                    st.session_state.flash = f"Simulated: {top['name']} -> {db.respond(nid_rows[0]['id'], True)}"
                    st.rerun()

    with t2:
        st.write("The requester submits the form directly. The bounded agent validates the request, applies coded donor "
                 "rules, builds a donor pool, drafts AI messages and a briefing, and alerts eligible donors. If the pool "
                 "is too small it widens the search within predefined limits (5 km, then 10 km). Donors who register "
                 "later are alerted too if they are within the radius.")
        st.success("Final medical donor screening is always done by the blood bank. The system does not make medical decisions.")
        actions = db.list_actions(rid)
        completed = [a for a in actions if a["status"] != "Pending"]
        if completed:
            with st.expander(f"Workflow actions ({len(completed)})"):
                for a in completed:
                    st.write(f'**{a["status"]}**: {a["description"]}')
        for a in [a for a in actions if a["status"] == "Pending" and a["kind"] in ("notify_bank", "update_requester", "ask_requester")]:
            with st.expander(f"Draft: {a['description']}"):
                st.text_area("Message", value=a["message"], key=f"draft_{a['id']}", height=130)

    with t3:
        st.caption("Edit the request and re-run the workflow. Donors who were already alerted or accepted are kept.")
        c1, c2, c3 = st.columns(3)
        group = c1.selectbox("Blood group", [""] + rules.BLOOD_GROUPS,
                             index=([""] + rules.BLOOD_GROUPS).index(req["blood_group"] or ""), key=f"e_g{rid}")
        units_v = c2.number_input("Units", 1, 20, int(req["units"] or 1), key=f"e_u{rid}")
        hrs = c3.selectbox("Needed", HOURS,
                           index=HOURS.index(min(HOURS, key=lambda v: abs(v - (req["needed_in_hours"] or 12)))),
                           format_func=lambda h: f"within {h} hours", key=f"e_h{rid}")
        d1, d2 = st.columns(2)
        hosp = d1.text_input("Hospital", req["hospital"] or "", key=f"e_ho{rid}")
        cities = [""] + list(rules.CITIES)
        city = d2.selectbox("City", cities, index=cities.index(req["city"] or ""), key=f"e_c{rid}")
        e1, e2 = st.columns(2)
        cname = e1.text_input("Contact person", req["contact_name"] or "", key=f"e_n{rid}")
        cphone = e2.text_input("Contact phone", req["contact_phone"] or "", key=f"e_p{rid}")

        b1, b2, _ = st.columns([2, 1.5, 3])
        if b1.button("Save and re-run workflow", type="primary", key=f"save{rid}"):
            db.update_request(rid, {
                "blood_group": group, "units": units_v, "hospital": hosp.strip(), "city": city,
                "contact_name": cname.strip(), "contact_phone": cphone.strip(),
                "needed_in_hours": hrs, "status": "New",
            })
            db.audit(rid, "request_edited", "Coordinator updated the details")
            with st.spinner("Re-running the workflow..."):
                res = run_workflow(rid)
            st.session_state.flash = f"Workflow re-run. Status: {res['status']}. Pool: {res['pool']}."
            st.rerun()
        if b2.button("Close request", key=f"close{rid}"):
            db.update_request(rid, {"status": "Closed"})
            db.audit(rid, "request_closed", "Closed by coordinator")
            st.rerun()

    with t4:
        log = db.get_audit(rid)
        st.markdown("**Agent steps**")
        for i, r in enumerate([r for r in log if r["event"].startswith("agent:")], 1):
            st.write(f"{i}. `{r['event'][6:]}`: {r['detail']}")
        with st.expander("Full audit log"):
            st.dataframe(pd.DataFrame(log)[["ts", "event", "detail"]] if log else pd.DataFrame(),
                         width="stretch", hide_index=True)


# ================================================================ donor portal
def _donor_form_register():
    st.subheader("Register as a volunteer donor")
    st.caption("You will be alerted when a compatible request is within 3 km of your location. "
               "You can pause or delete your profile at any time.")

    city = st.selectbox("City", list(rules.CITIES), key="donor_register_city")
    clat, clon = rules.CITIES[city]

    with st.form("register"):
        a, b = st.columns(2)
        name = a.text_input("Full name")
        phone = b.text_input("Phone number", placeholder="03XX-XXXXXXX")
        c, d = st.columns(2)
        group = c.selectbox("Blood group", rules.BLOOD_GROUPS)
        age = d.number_input("Age (adults only)", 18, 65, 25)
        never = st.checkbox("I have never donated blood")
        last = st.date_input("Date of last donation", value=None, max_value=date.today(), disabled=never)
        with st.expander("Fine-tune your location (optional)"):
            st.caption("Defaults to your city centre. In a real deployment this would come from your device with your permission.")
            lat = st.number_input("Latitude", value=float(clat), format="%.4f", key=f"lat_{city}")
            lon = st.number_input("Longitude", value=float(clon), format="%.4f", key=f"lon_{city}")
        consent = st.checkbox("I agree to be contacted about blood requests near me. I understand the blood bank "
                              "will do the final medical screening and that I can delete my profile at any time.")

        if st.form_submit_button("Register", type="primary"):
            if not name.strip() or not rules.valid_phone(phone):
                st.error("Please enter your name and a valid phone number.")
            elif not consent:
                st.error("Consent is required so we can contact you.")
            elif db.find_donor_by_phone(phone):
                st.error("This phone number is already registered. Use the Sign in tab.")
            else:
                did = db.add_donor({
                    "name": name.strip(), "phone": phone.strip(), "blood_group": group, "age": int(age),
                    "city": city, "lat": lat, "lon": lon,
                    "last_donation": None if never or not last else last.isoformat(), "consent": True,
                })
                st.session_state.donor_id = did
                st.rerun()


@st.fragment(run_every="5s")
def _inbox(donor_id):
    items = db.donor_notifications(donor_id)
    st.subheader("📬 Your blood donation requests")
    st.caption("Requests within 3 km that match your blood group appear here. This list refreshes every few seconds.")

    if not items:
        st.info("No requests for you right now. When a compatible request appears within 3 km of your location, "
                "it will show up here with an Accept button.")
        return

    for n in items:
        ms = n["match_status"]
        with st.container(border=True):
            st.markdown(
                f'<div class="bm-donorhead {esc(n["urgency"])}"><div class="bm-bt">{esc(n["blood_group"])}</div>'
                f'<div><div class="bm-title">{URG.get(n["urgency"], "")} {esc(n["urgency"])} blood request</div>'
                f'<div class="bm-muted">{esc(n["hospital"])}, {esc(n["city"])} &nbsp;|&nbsp; {esc(n["created"])}</div></div></div>',
                unsafe_allow_html=True,
            )
            st.markdown(f'<div class="bm-msg">{esc(n["message"]).replace(chr(10), "<br>")}</div>', unsafe_allow_html=True)

            if ms == "Alerted" and n["req_status"] not in db.CLOSED:
                st.markdown("**Are you willing and available to donate for this case?** Your acceptance does not replace "
                            "hospital blood bank screening. The hospital confirms final eligibility.")
                b1, b2, _ = st.columns([2, 2, 3])
                if b1.button("✅ I am willing to donate", key=f"accept_{n['id']}", type="primary"):
                    if db.respond(n["id"], True) == "busy":
                        st.session_state[f"busy_{n['id']}"] = True
                    st.rerun()
                if b2.button("❌ I cannot donate", key=f"decline_{n['id']}"):
                    db.respond(n["id"], False)
                    st.rerun()
                if st.session_state.get(f"busy_{n['id']}"):
                    st.error("You already accepted another active blood request.")

            elif ms == "Accepted":
                st.success("✅ You accepted this request. The coordinator and the requester can now see your response.")
                st.info(f"📞 **Requester:** {n['contact_name'] or 'Not provided'}  \n"
                        f"**Phone:** {n['contact_phone'] or 'Not provided'}  \n"
                        f"🏥 **Hospital:** {n['hospital']}, {n['city']}")
                st.caption("Please contact the requester and confirm with the hospital blood bank before travelling. "
                           "The blood bank will perform the final donor screening.")
            elif ms == "Declined":
                st.error("❌ You declined this request. You can wait for another compatible request.")
            elif n["req_status"] in db.CLOSED:
                st.info("🔒 This request was closed before you responded.")


def _donor_home(donor):
    agent.alert_new_donor(donor["id"])  # catch up on open requests nearby (idempotent)
    top = st.columns([5, 1])
    days = rules.days_since(donor["last_donation"])
    top[0].markdown(
        f'<div class="bm-card"><div class="bm-row"><div class="bm-bt">{esc(donor["blood_group"])}</div><div>'
        f'<div class="bm-title">Hello, {esc(donor["name"].split()[0])}</div>'
        f'<div class="bm-muted">{esc(donor["city"])} &nbsp;|&nbsp; last donation: '
        f'{"never" if days is None else f"{days} days ago"} &nbsp;|&nbsp; alerts within {rules.RULES["alert_radius_km"]:g} km</div>'
        f'</div></div></div>', unsafe_allow_html=True)
    if top[1].button("Sign out"):
        st.session_state.pop("donor_id", None)
        st.rerun()

    avail = st.toggle("I am available to donate", value=bool(donor["available"]), key=f"avail_{donor['id']}")
    if avail != bool(donor["available"]):
        db.update_donor(donor["id"], available=1 if avail else 0)
        st.rerun()

    _inbox(donor["id"])

    with st.expander("Delete my profile"):
        st.caption("This removes your details and alerts permanently.")
        if st.checkbox("I understand", key="del_ok") and st.button("Delete my profile"):
            db.delete_donor(donor["id"])
            st.session_state.pop("donor_id", None)
            st.rerun()


def page_donor():
    hero("🙋", "Donor Portal", "Register once. Get alerted when someone within 3 km needs your blood group.")
    banner()

    donor = db.get_donor(st.session_state.get("donor_id")) if st.session_state.get("donor_id") else None
    if donor:
        _donor_home(donor)
        return

    t1, t2 = st.tabs(["📝 Register", "🔑 Sign in"])
    with t1:
        _donor_form_register()
    with t2:
        phone = st.text_input("Phone number you registered with", key="si_phone")
        st.caption("Demo sign-in only. A real deployment needs OTP verification.")
        if st.button("Sign in", type="primary"):
            d = db.find_donor_by_phone(phone)
            if d:
                st.session_state.donor_id = d["id"]
                st.rerun()
            st.error("No donor found with that number.")

        helpers = db.donors_with_notifications() if demo_mode() else []
        if helpers:
            with st.expander("Demo helper: sign in as a synthetic donor who has an alert"):
                pick = st.selectbox("Donor", helpers, format_func=lambda d: f"{d['name']} ({d['blood_group']}, {d['city']})")
                if st.button("Sign in as this donor"):
                    st.session_state.donor_id = pick["id"]
                    st.rerun()


# ================================================================ about
def page_about():
    hero("ℹ️", "About and Limits", "What the system does, what the AI does, and what it does not do.")
    banner()
    c1, c2, c3 = st.columns(3)
    c1.markdown('<div class="bm-feature"><h4>🤖 Agentic AI</h4><p>A bounded agent (maximum 8 steps) validates the request, '
                'searches donors, checks pool size, widens the search within limits, and logs every step.</p></div>',
                unsafe_allow_html=True)
    c2.markdown('<div class="bm-feature"><h4>✍️ Generative AI</h4><p>Groq (gpt-oss) drafts donor alerts, blood bank notes, '
                'requester updates and a short briefing in English or Urdu.</p></div>', unsafe_allow_html=True)
    c3.markdown('<div class="bm-feature"><h4>⚙️ Automation</h4><p>Request, rules, donor matching, alerts, response tracking '
                'and live status run as one automated process.</p></div>', unsafe_allow_html=True)

    st.markdown(
        """
**Safety boundary.** Rules written in code decide compatibility and basic demo eligibility. The AI model does not make
medical decisions. Donors are labelled potentially eligible, pending blood bank screening. Alerts never include the
requester's phone number. The coordinator can monitor every step and close any request.

**Not included.** Final eligibility, cross-matching or lab work, blood stock management, payments, real patient data,
verification of donor claims, emergency dispatch, or a guarantee of donor response.

**Known limits of this demo.** Alerts are an in-app inbox plus a logged mock SMS. Location is a city centre, a fictional
demo hospital, or manually entered coordinates. Sign-in is by phone number only. Streamlit with SQLite suits a demo or
pilot, not national traffic, and data resets when the cloud app restarts.
        """
    )
    st.subheader("Rules in use")
    st.json(rules.RULES)

    st.subheader("Reset demo data")
    if not coordinator_ok():
        return
    st.caption("Deletes all requests, alerts and registered donors, then reloads 300 synthetic donors.")
    if st.checkbox("I understand this deletes everything") and st.button("Reset demo data"):
        db.reset_all()
        for k in ("donor_id", "dashboard_request_selector", "current_request"):
            st.session_state.pop(k, None)
        st.success("Demo data reset.")


# ================================================================ routing
{
    "New Request": page_new_request,
    "Donor Portal": page_donor,
    "Coordinator Dashboard": page_dashboard,
    "About & Limits": page_about,
}[st.session_state.page]()

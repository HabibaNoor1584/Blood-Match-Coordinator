# BloodMatch Coordinator

An AI-assisted coordination tool for urgent blood requests. A request arrives, the information is checked, predefined rules are applied, a pool of nearby potentially eligible donors is organized, and the coordinator receives an action list with drafted messages. Volunteers can register as donors and get an alert when a compatible request is within 3 km.

**This tool only organizes information. It makes no medical decisions and is not an emergency service.** The demo uses synthetic data.

## How the three AI components are used

| Component | What it does here |
|---|---|
| Business Process Automation | Fixed pipeline: intake, validation, rules, pool building, task creation |
| Agentic AI | A bounded agent (maximum 8 steps) that runs the tools, decides whether to propose a wider search, builds the action list, and logs every step. Nothing is sent without human approval |
| Generative AI (Groq, gpt-oss) | Reads messy request text into fields, drafts donor, requester and blood bank messages (English or Urdu), and writes a short briefing |

**Rules written in code decide compatibility and eligibility. The AI model never does.** If the Groq key is missing or a call fails, the app falls back to regex extraction and message templates, so the demo never breaks.

## Project structure

```
bloodmatch-coordinator/
  app.py              Streamlit interface (dashboard, new request, donor portal, about)
  agent.py            Coordinator agent, alert sending, radius widening
  rules.py            Compatibility table, screening rules, distance, urgency (edit RULES here)
  llm.py              Groq calls, regex fallback, message templates
  db.py               SQLite layer and synthetic data seeding (300 donors)
  requirements.txt
  tests/test_rules.py Unit tests for the rules
  .streamlit/
    config.toml            Theme
    secrets.toml.example   Template for your secrets (the real file is never committed)
```

## Run locally

```bash
pip install -r requirements.txt
mkdir -p .streamlit && cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# open .streamlit/secrets.toml and paste your Groq key
streamlit run app.py
```

Run the tests with `pip install pytest` then `pytest`.

## Deploy on Streamlit Community Cloud

1. Create a new GitHub repository and upload all files in this folder. Do **not** upload a real `secrets.toml`.
2. Go to share.streamlit.io and sign in with GitHub.
3. Click **Create app**, choose your repository and branch, and set the main file path to `app.py`.
4. Open **Advanced settings**, choose Python 3.11 or 3.12, and paste this into **Secrets**:
   ```toml
   GROQ_API_KEY = "gsk_your_key_here"
   GROQ_MODEL = "openai/gpt-oss-20b"
   ```
   You can use `openai/gpt-oss-120b` for better writing quality (slower).
5. Click **Deploy**. The sidebar shows "Groq connected" when the key works.

Get a free Groq key at console.groq.com. If you ever paste a key into a public place by mistake, delete it in the Groq console and create a new one.

## Demo script (about 3 minutes)

1. Open **New Request**, click **Load demo message**, then **Extract details**. The blood group, units, hospital and city fill in. The phone number is missing on purpose.
2. Click **Submit request and run the agent**. Status becomes *Needs info* and a follow-up message is drafted.
3. Open the dashboard. In **Edit request**, add a phone number (for example 0312-3456789) and click **Save and re-run agent**.
4. The agent finds donors within 3 km, applies the rules, and builds the action list. Check **Agent trace** to see each step and how many donors the rules excluded.
5. In **Action list**, edit if you like, then click **Approve and alert donors**.
6. Open **Donor Portal > Sign in > Demo helper**, sign in as an alerted donor, and tap **Accept**. The donor sees the requester contact only after accepting.
7. Back on the dashboard, the units-covered bar updates. When enough donors accept, the request becomes *Fulfilled*.
8. For a rare group (for example O- in Lahore), the pool is small and the agent proposes widening the search to 5 km, then 10 km, with your approval each time.

## Rules (editable in `rules.py`)

- Compatibility: standard red cell donor-to-recipient table for all 8 groups
- Screening defaults: age 18 to 60, at least 90 days since last donation, available, consented, not already committed to another active request
- Donors are always labelled "Potentially eligible, pending blood bank screening". Confirm all defaults with your blood bank and local regulations
- Alerts go to donors within 3 km first. Wider radius needs coordinator approval. Maximum 3 alerts per donor per week

## Limitations

- Notifications are an in-app inbox (refreshes every 5 seconds) plus a logged mock SMS. Real SMS or WhatsApp needs a provider such as Twilio and approvals
- Location is a city centre or manually entered coordinates. There is no live tracking
- Sign-in is by phone number only. A real deployment needs OTP verification
- SQLite on Streamlit Cloud is not permanent. Data resets when the app restarts. Use PostgreSQL for a real pilot
- Streamlit suits a demo or pilot, not national traffic. The scale path is an API backend, a managed database and a mobile app
- Not included: medical decisions or advice, final eligibility, cross-matching or lab work, blood stock management, payments, real patient data, verification of donor claims, and emergency dispatch

## Privacy notes

Donors give explicit consent, can pause or delete their profile, and other users never see their phone number. A requester's contact is shared only after a donor accepts. Do not enter real patient information in the public demo.

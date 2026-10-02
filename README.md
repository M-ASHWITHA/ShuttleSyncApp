# ShuttleSync — Smart Campus Shuttle & Mobility Optimization

Real-time shuttle tracking, capacity-aware routing, UPI / cash / Pay Later fare handling and fleet insights for the **VIT campus**.
One FastAPI backend, three web apps: **Student**, **Driver** and **Admin (Fleet Insights)** — built to match the final UI designs in [`docs/design/`](docs/design).

## Team
> Replace with your names / register numbers before submission.

| Name | Reg. No. | Role |
|------|----------|------|
| … | … | … |

## Run it

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows   (Mac/Linux: source .venv/bin/activate)
pip install -r requirements.txt
python -m uvicorn shuttle.main:app --reload
```

Open **http://localhost:8000** (use your phone-size browser window, or DevTools → device toolbar).

| App | URL |
|-----|-----|
| Student | `/` |
| Driver | `/driver.html` |
| Admin – Fleet Insights | `/admin.html` |
| API docs | `/docs` |

Demo controls (environment variables, optional): `SIM_SPEEDUP` (simulation speed, default 4), `CASH_TIMEOUT_SECONDS` (default 600 = 10 min; set `30` to see the timeout quickly), `PAY_NOW_GRACE_SECONDS` (default 120), `SIM_REALTIME=1` (follow the real clock).
Example (PowerShell): `$env:CASH_TIMEOUT_SECONDS=30; python -m uvicorn shuttle.main:app`

## Student app (7 screens)

Permissions → **Where to?** → **Live tracking** (closest shuttle + also on this route, Available / Full) → **Shuttle detail** (route progress, capacity ring, *I'm waiting here* / *I'm in the shuttle*) → **Payment** (UPI / Cash) → **Pay Later** → **Profile** (today's history).

## Payment rules (from the reference designs)

* **UPI** – Pay via UPI → choose Google Pay / PhonePe / Paytm → "Opening app…" → *Paid via <app> ✓* with timestamp, visible to the driver. *(Gateway is mocked.)*
* **Cash** – only when onboard ("Board the shuttle to pay by cash" otherwise). Request goes to the driver, **10-minute timer** starts (*Waiting*). Driver confirms → *Payment accepted*. No confirmation → *Payment unpaid*, the trip stays on **Pay Later** as due.
* **Pay Later** – boarding without paying at boarding. **Max 2 per day**, verified by the driver. A 3rd boarding is blocked until previous dues are cleared; that trip must then be paid now.

Details: [docs/PAYMENTS.md](docs/PAYMENTS.md).

## Driver & Admin

* **Driver** – onboard capacity, AI suggestion (skip an empty stop / alert control), Pay Later boardings today, upcoming stops with waiting counts, and a *Needs your confirmation* card (cash to confirm, Pay Later boardings to verify) that appears only when something is pending.
* **Admin** – avg wait, trips today, fleet utilization, Pay Later dues outstanding, route × hour demand heatmap, reallocation suggestion, efficiency gain.

## How it works

* `shuttle/simulator.py` – discrete-time campus loop simulator (arrivals, boarding, alighting, capacity: seated 30 / total 40, driver-skip).
* `shuttle/network.py` – 4 routes (1–4 for students, A–D for driver/admin), ETAs, closest-shuttle ranking, driver overview and AI hints.
* `shuttle/demand.py` – ML demand model (gradient boosting on synthetic campus timetables) feeding the simulator and admin heatmap.
* `shuttle/payments.py` – SQLite trips, UPI, cash timer, Pay Later limit.
* `shuttle/analytics.py` – heatmap shading, reallocation and efficiency messages.
* `web/` – plain HTML/CSS/JS (no build step). Design tokens sampled from the mockups (`web/style.css`).

## Tests

```bash
python -m unittest discover -s tests
```

## Notes & limitations

* Bluetooth auto-detection of "onboard" needs a native app; the web version uses the **I'm in the shuttle** button. Location permission uses the browser prompt.
* UPI is simulated (no real money moves). A production version needs a payment gateway with server-side verification.
* Demand data is synthetic (`scripts/generate_data.py`); replace with real campus logs when available.
* Replace `web/assets/vit-logo.png` with the official high-resolution VIT logo (same filename).
* The demo profile (name / ID on the Profile screen) comes from the design and is editable.

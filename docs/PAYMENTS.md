# Payments & Pay Later logic

Trip life-cycle: `unpaid` → (`waiting` for cash) → `paid`.  Every boarding ("I'm in the shuttle") creates today's trip as `unpaid`.

## UPI
1. Student taps **Pay via UPI**, picks Google Pay / PhonePe / Paytm.
2. UI shows *Opening <app>…*; the (mock) UPI app confirms.
3. Trip becomes `paid`, method `upi`, app name + timestamp stored and shown to the driver.

## Cash
1. **Pay with Cash** is available only while onboard (latest boarding, within `ONBOARD_WINDOW_SECONDS`). Otherwise the UI shows *Board the shuttle to pay by cash*.
2. Trip becomes `waiting`; the driver sees a **Confirm cash** request. Student sees *N min elapsed*.
3. Driver confirms → `paid` (*Payment accepted*).
4. No confirmation within `CASH_TIMEOUT_SECONDS` (10 min) → back to `unpaid` with `cash_expired`; shown as *Payment unpaid* and stays on the Pay Later page as due. The student may ask again.

## Pay Later
* Boarding without paying is Pay Later; the driver verifies it (*All verified at boarding*).
* A trip **uses** Pay Later if it is still unpaid, was verified by the driver, or was paid more than `PAY_NOW_GRACE_SECONDS` (2 min) after boarding.
* Limit: `PAYLATER_DAILY_LIMIT = 2` per day. On the 3rd boarding:
  * dues outstanding → **blocked** (`CLEAR_DUES_FIRST`, HTTP 402) – "Clear your previous dues first, then pay for this trip";
  * no dues → allowed, but the trip is marked *pay now* (`paylater = false`).

## API summary
| Endpoint | Purpose |
|----------|---------|
| `POST /api/students/{id}/board` | I'm in the shuttle |
| `GET /api/students/{id}/state` | today's trip, dues, history |
| `POST /api/students/{id}/trips/{trip}/pay-upi` | `{app}` |
| `POST /api/students/{id}/trips/{trip}/pay-cash` | request driver confirmation |
| `POST /api/driver/{shuttle}/trips/{trip}/confirm-cash` | driver confirms cash |
| `POST /api/driver/{shuttle}/trips/{trip}/verify` | driver verifies Pay Later boarding |
| `POST /api/students/{id}/pass` | digital pass (backend only – no screen in the final design) |

import unittest
from datetime import datetime, timedelta

from shuttle import config as C
from shuttle.payments import PaymentError, PaymentService


class Clock:
    def __init__(self):
        self.t = datetime(2026, 9, 21, 9, 0, 0)

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


class PaymentTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.pay = PaymentService(":memory:", now_fn=self.clock, cash_timeout=600)

    def board(self, sid="S1", shuttle="R1-1"):
        return self.pay.board(sid, shuttle, "1", "prp", "Route 1 · PRP → Main Gate")

    def test_boarding_creates_unpaid_pay_later_trip(self):
        t = self.board()
        self.assertEqual((t["status"], t["fare"], t["paylater"]), ("unpaid", C.FARE_INR, True))

    def test_double_tap_same_shuttle_is_one_trip(self):
        a = self.board(); b = self.board()
        self.assertEqual(a["id"], b["id"]); self.assertTrue(b["existing"])

    def test_upi_flow(self):
        t = self.board()
        r = self.pay.pay_upi("S1", t["id"], "Google Pay")
        self.assertEqual((r["status"], r["method"], r["upi_app"]), ("paid", "upi", "Google Pay"))
        with self.assertRaises(PaymentError) as e:
            self.pay.pay_upi("S1", t["id"], "PhonePe")
        self.assertEqual(e.exception.code, "ALREADY_PAID")

    def test_unknown_upi_app_rejected(self):
        t = self.board()
        with self.assertRaises(PaymentError):
            self.pay.pay_upi("S1", t["id"], "FakePay")

    def test_cash_confirmed_by_driver(self):
        t = self.board()
        w = self.pay.request_cash("S1", t["id"])
        self.assertEqual(w["status"], "waiting")
        self.assertEqual([q["kind"] for q in self.pay.driver_queue("R1-1")], ["cash"])
        self.clock.advance(minutes=6)
        self.assertEqual(self.pay.get_trip("S1", t["id"])["cash_elapsed_minutes"], 6)
        r = self.pay.confirm_cash(t["id"])
        self.assertEqual((r["status"], r["method"]), ("paid", "cash"))

    def test_cash_times_out_to_unpaid_and_stays_due(self):
        t = self.board()
        self.pay.request_cash("S1", t["id"])
        self.clock.advance(minutes=10, seconds=1)
        r = self.pay.get_trip("S1", t["id"])
        self.assertEqual((r["status"], r["cash_expired"]), ("unpaid", True))
        self.assertEqual(self.pay.state("S1")["dues_amount"], C.FARE_INR)
        with self.assertRaises(PaymentError) as e:          # driver can no longer confirm the expired request
            self.pay.confirm_cash(t["id"])
        self.assertEqual(e.exception.code, "NOT_WAITING")
        self.assertEqual(self.pay.request_cash("S1", t["id"])["status"], "waiting")   # can ask again

    def test_cash_needs_onboard(self):
        old = self.board(shuttle="R1-1")
        self.board(shuttle="R2-1")                            # boarded another shuttle -> first trip no longer onboard
        with self.assertRaises(PaymentError) as e:
            self.pay.request_cash("S1", old["id"])
        self.assertEqual(e.exception.code, "NOT_ONBOARD")

    def test_cash_not_available_long_after_boarding(self):
        t = self.board()
        self.clock.advance(seconds=C.ONBOARD_WINDOW_SECONDS + 60)
        with self.assertRaises(PaymentError) as e:
            self.pay.request_cash("S1", t["id"])
        self.assertEqual(e.exception.code, "NOT_ONBOARD")

    def test_third_pay_later_requires_clearing_dues(self):
        self.board(shuttle="R1-1"); self.board(shuttle="R2-1")
        with self.assertRaises(PaymentError) as e:
            self.board(shuttle="R3-1")
        self.assertEqual(e.exception.code, "CLEAR_DUES_FIRST")
        self.assertEqual(e.exception.extra["dues_amount"], 2 * C.FARE_INR)

    def test_after_clearing_dues_third_trip_must_be_paid_now(self):
        a = self.board(shuttle="R1-1"); b = self.board(shuttle="R2-1")
        self.clock.advance(minutes=30)                       # paid long after boarding -> Pay Later was used
        self.pay.pay_upi("S1", a["id"], "Paytm"); self.pay.pay_upi("S1", b["id"], "Paytm")
        c = self.board(shuttle="R3-1")
        self.assertFalse(c["paylater"])
        self.assertEqual(self.pay.paylater_used_today("S1"), 2)
        with self.assertRaises(PaymentError):                # third trip unpaid -> can't board a 4th
            self.board(shuttle="R4-1")

    def test_paying_at_boarding_does_not_use_pay_later(self):
        for sh in ("R1-1", "R2-1", "R3-1"):
            t = self.board(shuttle=sh)
            self.clock.advance(seconds=20)
            self.pay.pay_upi("S1", t["id"], "Google Pay")
        self.assertEqual(self.pay.paylater_used_today("S1"), 0)

    def test_driver_verifies_pay_later_boarding(self):
        t = self.board()
        self.assertEqual(self.pay.paylater_today_for_shuttle("R1-1"), {"verified": 0, "pending": 1, "total": 1})
        self.assertEqual(self.pay.driver_queue("R1-1")[0]["kind"], "boarding")
        self.pay.verify_boarding(t["id"])
        self.assertEqual(self.pay.paylater_today_for_shuttle("R1-1"), {"verified": 1, "pending": 0, "total": 1})
        self.assertEqual(self.pay.driver_queue("R1-1"), [])

    def test_pass_boards_free(self):
        self.pay.buy_pass("S2", "weekly")
        t = self.board("S2")
        self.assertEqual((t["status"], t["method"], t["fare"]), ("paid", "pass", 0))

    def test_summary_counts_dues(self):
        self.board("S1"); self.board("S2")
        self.assertEqual(self.pay.summary()["outstanding_dues"], 2 * C.FARE_INR)

    def test_students_are_isolated(self):
        t = self.board("S1")
        with self.assertRaises(PaymentError):
            self.pay.pay_upi("S2", t["id"], "Paytm")


if __name__ == "__main__":
    unittest.main()

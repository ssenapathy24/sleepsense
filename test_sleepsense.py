"""Tests for SleepSense - run with:  python3 -m unittest -v"""
import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone

import sleep_calc
import sleepsense_core as core
import sleepsense_metrics as metrics

GMT = timezone.utc
BST = timezone(timedelta(hours=1))
CFG = dict(core.DEFAULT_CONFIG)
NIGHT = date(2026, 10, 28)
HERE = os.path.dirname(os.path.abspath(__file__))


def ev(*items, tz=GMT):
    """ev("2026-10-27 23:00", ("2026-10-27 23:05", "charger_connected"), ...)"""
    out = []
    for item in items:
        stamp, kind = (item, "app") if isinstance(item, str) else item
        out.append((datetime.strptime(stamp, "%Y-%m-%d %H:%M").replace(tzinfo=tz), kind))
    return sorted(out, key=lambda e: e[0])


def hm(iso):
    return iso[11:16]


def every(start, end, step=5, day0="2026-10-27"):
    """Phone used every few minutes between two times (HH:MM), for 'scrolling' periods."""
    t = datetime.strptime(f"{day0} {start}", "%Y-%m-%d %H:%M")
    stop = datetime.strptime(f"{day0} {end}", "%Y-%m-%d %H:%M")
    if stop < t:
        stop += timedelta(days=1)
    out = []
    while t <= stop:
        out.append(t.strftime("%Y-%m-%d %H:%M"))
        t += timedelta(minutes=step)
    return out


class TestDetection(unittest.TestCase):
    def test_simple_night(self):
        r = core.detect_night(ev("2026-10-27 22:30", "2026-10-27 23:00", "2026-10-28 07:00"), NIGHT, CFG)
        self.assertEqual((hm(r["fell_asleep"]), hm(r["woke_up"])), ("23:10", "07:00"))
        self.assertEqual(r["total_sleep_minutes"], 7 * 60 + 50)

    def test_short_break_before_bed_is_ignored(self):
        # Your question: no phone 23:00-23:15, phone until 00:00, asleep until 07:00
        e = ev("2026-10-27 23:00", *every("23:15", "00:00"), "2026-10-28 07:00")
        r = core.detect_night(e, NIGHT, CFG)
        self.assertEqual((hm(r["fell_asleep"]), r["total_sleep_minutes"]), ("00:10", 6 * 60 + 50))

    def test_working_without_phone_is_not_sleep(self):
        # Working 22:30-23:45 with no phone, phone until 00:30, then asleep
        e = ev("2026-10-27 22:30", *every("23:45", "00:30"), "2026-10-28 07:00")
        r = core.detect_night(e, NIGHT, CFG)
        self.assertEqual(hm(r["fell_asleep"]), "00:40")
        self.assertEqual(r["wakeup_count"], 0)

    def test_real_split_sleep_with_charger(self):
        # Actually slept 22:30-23:45 with the phone on charge, awake until 00:30, slept again
        e = ev(("2026-10-27 22:30", "charger_connected"), *every("23:45", "00:30"), "2026-10-28 07:00")
        r = core.detect_night(e, NIGHT, CFG)
        self.assertEqual(hm(r["fell_asleep"]), "22:40")
        self.assertEqual(r["wakeup_count"], 1)
        self.assertEqual(hm(r["wakeups"][0]["start"]), "23:45")
        self.assertEqual(r["total_sleep_minutes"], 65 + 6 * 60 + 20)   # 22:40-23:45 + 00:40-07:00
        self.assertEqual(r["confidence"], "high")

    def test_split_sleep_with_button(self):
        e = ev(("2026-10-27 22:30", "sleep_button"), *every("23:45", "00:30"), "2026-10-28 07:00")
        r = core.detect_night(e, NIGHT, CFG)
        self.assertEqual(hm(r["in_bed_start"]), "22:30")
        self.assertEqual(r["wakeup_count"], 1)

    def test_sleep_focus_counts(self):
        e = ev(("2026-10-27 22:25", "sleep_focus_on"), "2026-10-27 22:30", *every("23:45", "00:30"),
               "2026-10-28 07:00")
        r = core.detect_night(e, NIGHT, CFG)
        self.assertEqual(hm(r["fell_asleep"]), "22:40")

    def test_bathroom_wake_up(self):
        e = ev("2026-10-27 23:30", "2026-10-28 03:10", "2026-10-28 03:15", "2026-10-28 07:30")
        r = core.detect_night(e, NIGHT, CFG)
        self.assertEqual(r["wakeup_count"], 1)
        self.assertEqual(r["wakeups"][0]["minutes"], 7)                 # 03:10 -> 03:15 + 2 min

    def test_steps_split_a_break(self):
        # No phone 00:00-07:00, but 300 steps at 03:00-03:20: you were up
        events = ev("2026-10-27 23:50", "2026-10-28 07:00")
        steps_file = os.path.join(tempfile.mkdtemp(), "steps.txt")
        with open(steps_file, "w") as f:
            f.write("2026-10-28T03:00:00+00:00,2026-10-28T03:20:00+00:00,300\n")
        events = sorted(events + core.load_steps(steps_file, CFG), key=lambda e: e[0])
        r = core.detect_night(events, NIGHT, CFG)
        self.assertEqual(r["wakeup_count"], 1)
        self.assertEqual(hm(r["wakeups"][0]["start"]), "03:00")

    def test_getting_up_ends_the_night(self):
        # Up at 06:00 for 2 hours - the nap after is not joined on
        e = ev("2026-10-27 23:30", *every("06:00", "08:00", 10, "2026-10-28"), "2026-10-28 09:40")
        r = core.detect_night(e, NIGHT, CFG)
        self.assertEqual(hm(r["woke_up"]), "06:00")

    def test_still_asleep(self):
        e = ev("2026-10-27 23:30", "2026-10-28 07:00")
        r = core.detect_night(e, NIGHT, CFG, now=datetime(2026, 10, 28, 8, 0, tzinfo=GMT))
        self.assertTrue(r.get("still_asleep"))
        r = core.detect_night(e, NIGHT, CFG, now=datetime(2026, 10, 28, 7, 5, tzinfo=GMT))
        self.assertTrue(r["found"])

    def test_not_enough_data(self):
        self.assertFalse(core.detect_night(ev("2026-10-28 08:00"), NIGHT, CFG)["found"])

    def test_clocks_going_back(self):
        e = ev("2026-10-24 23:50", tz=BST) + ev("2026-10-25 07:00")
        r = core.detect_night(e, date(2026, 10, 25), CFG)
        self.assertEqual(r["total_sleep_minutes"], 8 * 60)            # 00:00 BST -> 07:00 GMT

    def test_nap(self):
        e = ev(("2026-10-27 15:00", "sleep_button"), "2026-10-27 15:45")
        naps = core.detect_naps(e, NIGHT, CFG)
        self.assertEqual(naps[0]["minutes"], 40)

    def test_timestamp_formats(self):
        self.assertEqual(core.parse_timestamp("2026-10-28T08:05:00Z").hour, 8)


def row(night, asleep, wake, total, nap=0):
    return {"night": night, "fell_asleep": asleep, "woke_up": wake, "total_sleep_minutes": total,
            "nap_minutes": nap, "wakeup_count": 0, "performance": 90}


class TestMetrics(unittest.TestCase):
    def test_need_debt_performance(self):
        history = [row("2026-10-26", "2026-10-25T23:00:00+00:00", "2026-10-26T06:00:00+00:00", 360),
                   row("2026-10-27", "2026-10-26T23:00:00+00:00", "2026-10-27T06:00:00+00:00", 360)]
        # 2 nights x 2h short = 4h debt -> need 8h + min(60, 25% of 240) = 9h
        self.assertEqual(metrics.sleep_need(history, CFG), 540)
        self.assertEqual(metrics.performance(486, 540), 90)
        self.assertEqual(metrics.colour(90), "🟢")

    def test_consistency(self):
        same = [row(f"2026-10-2{i}", f"2026-10-1{i}T23:00:00+00:00", f"2026-10-2{i}T07:00:00+00:00", 480) for i in range(4)]
        self.assertEqual(metrics.consistency(same), 100)
        messy = same[:2] + [row("2026-10-24", "2026-10-24T02:00:00+00:00", "2026-10-24T10:00:00+00:00", 480)]
        self.assertLess(metrics.consistency(messy), 50)

    def test_tonight(self):
        history = [row("2026-10-28", "2026-10-27T23:00:00+00:00", "2026-10-28T07:00:00+00:00", 480)]
        t = metrics.tonight(history, CFG, date(2026, 10, 28), wake="07:00")
        self.assertEqual(t["in_bed_by"], "22:50")                       # 07:00 - 8h - 10 min


class TestCommandLine(unittest.TestCase):
    def run_cli(self, *extra):
        out = os.path.join(self.dir, "result.json")
        sleep_calc.main(["--log", os.path.join(HERE, "sample_log.txt"), "--steps", os.path.join(HERE, "sample_steps.txt"),
                         "--config", os.path.join(HERE, "config.json"),
                         "--history", os.path.join(self.dir, "history.csv"),
                         "--corrections", os.path.join(self.dir, "corrections.csv"),
                         "--learned", os.path.join(self.dir, "learned.json"),
                         "--output", out, "--quiet", *extra])
        with open(out) as f:
            return json.load(f)

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_sample_night_and_no_duplicates(self):
        r = self.run_cli("--night", "2026-10-28")
        self.assertEqual((hm(r["fell_asleep"]), hm(r["woke_up"])), ("00:41", "07:30"))
        self.assertEqual(r["wakeup_count"], 1)
        self.assertEqual(r["nap_minutes"], 32)
        self.assertEqual((r["save_to_health"], r["notify"]), ("yes", "yes"))
        self.assertEqual(len(r["health_asleep"]), 3)                   # 2 night segments + nap
        again = self.run_cli("--night", "2026-10-28")
        self.assertEqual((again["save_to_health"], again["notify"]), ("no", "no"))

    def test_fix_week_and_learning(self):
        self.run_cli("--night", "2026-10-28")
        fixed = self.run_cli("--fix", "--night", "2026-10-28", "--asleep", "00:45", "--wake", "07:30")
        self.assertEqual(fixed["total_sleep_minutes"], 405)
        self.assertEqual(metrics.read_history(os.path.join(self.dir, "history.csv"))[0]["source"], "fixed")
        week = self.run_cli("--week")
        self.assertIn("ai_prompt", week)
        tonight = self.run_cli("--tonight", "--wake", "07:00")
        self.assertIn("be in bed by", tonight["summary"])


if __name__ == "__main__":
    unittest.main()

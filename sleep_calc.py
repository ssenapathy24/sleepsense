#!/usr/bin/env python3
"""
SleepSense - WHOOP-style sleep tracking for iPhone, without a watch.

Commands (all print JSON and also save it to result.json for Shortcuts):

  python3 sleep_calc.py                          morning report for last night
  python3 sleep_calc.py --tonight [--wake 07:00] when to go to bed tonight
  python3 sleep_calc.py --week                   weekly report + AI prompt
  python3 sleep_calc.py --fix --asleep 23:10 --wake 07:00   correct last night
  python3 sleep_calc.py --explain                show how every break was scored

Testing on your laptop:
  python3 sleep_calc.py --log sample_log.txt --steps sample_steps.txt --night 2026-10-28 --no-save
"""

import argparse
import json
import os
import sys
from datetime import date, datetime

import sleepsense_core as core
import sleepsense_metrics as metrics

HERE = os.path.dirname(os.path.abspath(__file__))


def path(name):
    return os.path.join(HERE, name)


def morning(args, config, history):
    now = core.parse_timestamp(args.now) if args.now else datetime.now().astimezone()
    night = date.fromisoformat(args.night) if args.night else core.wall(now).date()
    check_now = now if (args.now or not args.night) else None   # testing an old night: no "still asleep" check

    events = sorted(core.load_events(args.log) + core.load_steps(args.steps, config), key=lambda e: e[0])
    result = core.detect_night(events, night, config, now=check_now)
    result["notify"] = "no"
    result["save_to_health"] = "no"
    result["already_logged"] = False
    if not result["found"]:
        result.setdefault("title", "SleepSense")
        result["summary"] = result["reason"]
        return result

    naps = core.detect_naps(events, night, config)
    metrics.add_metrics(result, naps, history, config)

    if not args.no_save:
        is_new = metrics.upsert_history(args.history, metrics.history_row(result))
        result["already_logged"] = not is_new
        result["notify"] = "yes" if is_new else "no"
        good_enough = result["confidence"] != "low" or config["auto_save_low_confidence"]
        result["save_to_health"] = "yes" if is_new and good_enough else "no"
    return result


def fix(args, config, history):
    night = date.fromisoformat(args.night) if args.night else datetime.now().date()
    result, old = metrics.build_fixed_night(night, args.asleep, args.wake, config, history)
    previous = [r for r in history if r["night"] != night.isoformat()]
    metrics.add_metrics(result, [], previous, config)
    metrics.upsert_history(args.history, metrics.history_row(result, source="fixed"), replace=True)
    metrics.save_correction(args.corrections, night.isoformat(), old, result)
    learned = metrics.learn(args.corrections, args.learned)
    result.update(title="Night updated ✏️", notify="yes", save_to_health="yes", already_logged=False)
    if learned:
        result["summary"] += f" (Learned: you fall asleep about {learned['fall_asleep_minutes']} min after your phone.)"
    if old and old.get("source") != "fixed":
        result["summary"] += " Delete the old entry in Health → Sleep → Show All Data if it was saved."
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description="SleepSense: sleep tracking from phone activity.")
    p.add_argument("--log", default=path("sleep_log.txt"))
    p.add_argument("--steps", default=path("steps.txt"))
    p.add_argument("--config", default=path("config.json"))
    p.add_argument("--history", default=path("history.csv"))
    p.add_argument("--corrections", default=path("corrections.csv"))
    p.add_argument("--learned", default=path("learned.json"))
    p.add_argument("--output", default=path("result.json"))
    p.add_argument("--night", help="date you woke up, YYYY-MM-DD (default: today)")
    p.add_argument("--now", help="pretend it is this time (ISO), for testing")
    p.add_argument("--no-save", action="store_true", help="don't save anything to history")
    p.add_argument("--tonight", action="store_true", help="bedtime advice for tonight")
    p.add_argument("--wake", help="wake-up time, HH:MM (for --tonight and --fix)")
    p.add_argument("--week", action="store_true", help="weekly report")
    p.add_argument("--fix", action="store_true", help="correct a night with --asleep and --wake")
    p.add_argument("--asleep", help="time you fell asleep, HH:MM (for --fix)")
    p.add_argument("--explain", action="store_true", help="print how each break was scored")
    p.add_argument("--quiet", action="store_true", help="only write result.json, print nothing")
    args = p.parse_args(argv)

    config = core.load_config(args.config, args.learned)
    history = metrics.read_history(args.history)

    if args.tonight:
        result = metrics.tonight(history, config, datetime.now().date(), args.wake)
    elif args.week:
        result = metrics.weekly(history, config)
    elif args.fix:
        if not (args.asleep and args.wake):
            p.error("--fix needs --asleep HH:MM and --wake HH:MM")
        result = fix(args, config, history)
    else:
        result = morning(args, config, history)

    text = json.dumps(result, indent=2, ensure_ascii=False)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(text)

    if args.quiet:
        pass
    elif args.explain and "breaks" in result:
        print(f"Night {result['night']} - {result.get('summary', '')}\n")
        for b in result["breaks"]:
            mark = "SLEEP" if b["counted_as_sleep"] else "awake"
            print(f"[{mark}] {b['start'][11:16]} → {b['end'][11:16]}  score {b['score']:>5}  " + "; ".join(b["reasons"]))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

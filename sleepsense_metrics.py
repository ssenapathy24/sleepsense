"""
SleepSense metrics - the WHOOP-style numbers and coaching.

  Sleep Need        your normal need + a share of your recent sleep debt
  Sleep Performance hours slept / sleep need (capped at 100%)
  Sleep Debt        how far behind you are over the last 7 nights
  Consistency       how similar your bedtime and wake time are (last 4 nights)
  Efficiency        time asleep / time in bed
"""

import csv
import json
import os
import statistics
from datetime import date, datetime, timedelta

from sleepsense_core import clock, hhmm, nice

HISTORY_FIELDS = ["night", "in_bed_start", "fell_asleep", "woke_up", "last_activity",
                  "total_sleep_minutes", "nap_minutes", "awake_minutes", "wakeup_count",
                  "efficiency", "need_minutes", "performance", "confidence", "source"]


# ---------------------------------------------------------------------------
# History file
# ---------------------------------------------------------------------------
def read_history(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return sorted(csv.DictReader(f), key=lambda r: r["night"])


def write_history(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in sorted(rows, key=lambda r: r["night"]):
            writer.writerow(row)


def upsert_history(path, row, replace=False):
    """Add a night. Returns False if it was already there (and replace is off)."""
    rows = read_history(path)
    if any(r["night"] == row["night"] for r in rows):
        if not replace:
            return False
        rows = [r for r in rows if r["night"] != row["night"]]
    write_history(path, rows + [row])
    return True


def slept(row):
    return int(row["total_sleep_minutes"]) + int(row.get("nap_minutes") or 0)


def nights_before(rows, night, days=7):
    start = night - timedelta(days=days)
    return [r for r in rows if start <= date.fromisoformat(r["night"]) < night]


# ---------------------------------------------------------------------------
# The numbers
# ---------------------------------------------------------------------------
def sleep_debt(rows, config):
    return sum(max(0, config["sleep_need_minutes"] - slept(r)) for r in rows)


def sleep_need(previous_rows, config):
    debt = sleep_debt(previous_rows, config)
    extra = min(config["max_debt_payback_minutes"], debt * config["debt_payback_fraction"])
    return round(config["sleep_need_minutes"] + extra)


def performance(slept_minutes, need_minutes):
    return min(100, round(100 * slept_minutes / need_minutes)) if need_minutes else 0


def colour(perf):
    return "🟢" if perf >= 85 else "🟡" if perf >= 70 else "🔴"


def minutes_after_6pm(iso):
    """Clock time as minutes after 18:00, so 23:30 and 00:30 are close together."""
    t = datetime.fromisoformat(iso)
    return (t.hour * 60 + t.minute - 18 * 60) % (24 * 60)


def consistency(rows):
    """100% = same bedtime and wake time every night. 90 min average difference = 0%."""
    if len(rows) < 2:
        return None
    devs = []
    for key in ("fell_asleep", "woke_up"):
        values = [minutes_after_6pm(r[key]) for r in rows]
        mean = statistics.mean(values)
        devs.append(statistics.mean(abs(v - mean) for v in values))
    return max(0, round(100 - statistics.mean(devs) * 100 / 90))


def average_clock(isos):
    m = statistics.mean(minutes_after_6pm(i) for i in isos) + 18 * 60
    h, mm = divmod(int(round(m)) % (24 * 60), 60)
    return f"{h:02d}:{mm:02d}"


# ---------------------------------------------------------------------------
# Morning report
# ---------------------------------------------------------------------------
def add_metrics(result, naps, history, config):
    night = date.fromisoformat(result["night"])
    previous = nights_before(history, night)
    need = sleep_need(previous, config)
    nap_minutes = sum(n["minutes"] for n in naps)
    total = result["total_sleep_minutes"] + nap_minutes
    perf = performance(total, need)
    row_now = {"fell_asleep": result["fell_asleep"], "woke_up": result["woke_up"],
               "total_sleep_minutes": result["total_sleep_minutes"], "nap_minutes": nap_minutes}
    last4 = previous[-3:] + [row_now]
    debt_after = sleep_debt(nights_before(history, night, 6) + [row_now], config)
    cons = consistency(last4)

    result.update({
        "naps": naps,
        "nap_minutes": nap_minutes,
        "total_sleep_text": nice(result["total_sleep_minutes"]),
        "need_minutes": need,
        "need_text": nice(need),
        "performance": perf,
        "performance_emoji": colour(perf),
        "sleep_debt_minutes": debt_after,
        "sleep_debt_text": nice(debt_after),
        "consistency": cons,
    })

    fell, woke = datetime.fromisoformat(result["fell_asleep"]), datetime.fromisoformat(result["woke_up"])
    title = f"Sleep Performance {perf}% {colour(perf)}"
    lines = [f"{nice(total)} of {nice(need)} needed. Asleep {hhmm(fell)} → {hhmm(woke)}."]
    if result["wakeups"]:
        times = ", ".join(f"{hhmm(datetime.fromisoformat(w['start']))} ({w['minutes']}m)" for w in result["wakeups"])
        lines.append(f"Woke {len(result['wakeups'])}x: {times}.")
    else:
        lines.append("No wake-ups 🎉")
    if nap_minutes:
        lines.append(f"Nap yesterday: {nice(nap_minutes)}.")
    if cons is not None:
        lines.append(f"Consistency {cons}%.")
    if debt_after:
        lines.append(f"Sleep debt {nice(debt_after)}.")
    if result["confidence"] == "low":
        lines.append("⚠️ Not sure about last night - run 'Edit last night' to confirm.")
    result["title"] = title
    result["summary"] = " ".join(lines)

    # Lists the Shortcut uses to write Apple Health
    result["health_asleep"] = [{"start": s["start"], "end": s["end"]} for s in result["segments"] + naps]
    result["health_in_bed"] = [{"start": result["in_bed_start"], "end": result["woke_up"]}]
    return result


def history_row(result, source="auto"):
    row = {k: result.get(k, "") for k in HISTORY_FIELDS}
    row.update(source=source)
    return row


# ---------------------------------------------------------------------------
# Evening coach: when should I go to bed tonight?
# ---------------------------------------------------------------------------
def tonight(history, config, today, wake=None):
    recent = nights_before(history, today + timedelta(days=1))
    if wake:
        wake_text = wake
    elif recent:
        wake_text = average_clock([r["woke_up"] for r in recent])
    else:
        wake_text = config["default_wake_time"]
    need = sleep_need(recent, config)
    wake_dt = datetime.combine(today + timedelta(days=1), clock(wake_text))
    asleep_by = wake_dt - timedelta(minutes=need)
    in_bed_by = asleep_by - timedelta(minutes=config["fall_asleep_minutes"])
    debt = sleep_debt(recent, config)
    summary = (f"To wake up at {wake_text} feeling 100%, be in bed by {hhmm(in_bed_by)} "
               f"({nice(need)} of sleep needed).")
    if debt:
        summary += f" You're {nice(debt)} behind this week."
    summary += f" Start winding down at {hhmm(in_bed_by - timedelta(minutes=30))} 🌙"
    return {"found": True, "title": "Tonight's bedtime 🌙", "summary": summary,
            "wake_time": wake_text, "in_bed_by": hhmm(in_bed_by), "asleep_by": hhmm(asleep_by),
            "need_minutes": need, "sleep_debt_minutes": debt}


# ---------------------------------------------------------------------------
# Weekly report (+ a prompt you can send to ChatGPT/Claude for an AI tip)
# ---------------------------------------------------------------------------
def weekly(history, config, days=7):
    rows = history[-days:]
    if not rows:
        return {"found": False, "title": "Weekly sleep", "summary": "No nights saved yet."}
    totals = [slept(r) for r in rows]
    perfs = [int(r["performance"]) for r in rows if r.get("performance")]
    weekday = [slept(r) for r in rows if date.fromisoformat(r["night"]).weekday() < 5]
    weekend = [slept(r) for r in rows if date.fromisoformat(r["night"]).weekday() >= 5]
    best = max(rows, key=slept)
    worst = min(rows, key=slept)
    avg = statistics.mean(totals)
    cons = consistency(rows)
    debt = sleep_debt(rows, config)
    summary = (f"Last {len(rows)} nights: average {nice(avg)}"
               + (f", performance {round(statistics.mean(perfs))}%" if perfs else "")
               + f". Usually asleep {average_clock([r['fell_asleep'] for r in rows])}, "
               f"up {average_clock([r['woke_up'] for r in rows])}."
               + (f" Consistency {cons}%." if cons is not None else "")
               + f" Best: {best['night']} ({nice(slept(best))}). Sleep debt {nice(debt)}.")
    if weekday and weekend:
        diff = statistics.mean(weekend) - statistics.mean(weekday)
        summary += f" Weekends: {nice(abs(diff))} {'more' if diff >= 0 else 'less'} than weekdays."

    table = "\n".join(f"{r['night']}: asleep {r['fell_asleep'][11:16]}, up {r['woke_up'][11:16]}, "
                      f"{nice(slept(r))}, {r['wakeup_count']} wake-ups" for r in rows)
    ai_prompt = ("You are a friendly sleep coach. Here is my sleep for the last week, tracked from my "
                 f"phone use (my sleep need is {nice(config['sleep_need_minutes'])}):\n{table}\n"
                 "Give me 2 short, specific tips (max 40 words in total) to sleep better next week.")
    return {"found": True, "title": "Your sleep this week 📊", "summary": summary,
            "average_sleep_minutes": round(avg), "consistency": cons, "sleep_debt_minutes": debt,
            "best_night": best["night"], "worst_night": worst["night"], "ai_prompt": ai_prompt}


# ---------------------------------------------------------------------------
# "Edit last night" + learning from your corrections
# ---------------------------------------------------------------------------
def build_fixed_night(night, asleep_text, wake_text, config, history):
    """Your own times for a night. Asleep times after 12:00 are the evening before."""
    asleep_t, wake_t = clock(asleep_text), clock(wake_text)
    asleep_day = night - timedelta(days=1) if asleep_t.hour >= 12 else night
    tz = datetime.now().astimezone().tzinfo
    fell = datetime.combine(asleep_day, asleep_t).replace(tzinfo=tz)
    woke = datetime.combine(night, wake_t).replace(tzinfo=tz)
    if woke <= fell:
        raise ValueError("Wake-up time must be after the time you fell asleep.")
    total = int((woke - fell).total_seconds() // 60)
    old = next((r for r in history if r["night"] == night.isoformat()), None)
    result = {"found": True, "night": night.isoformat(), "confidence": "high",
              "in_bed_start": (fell - timedelta(minutes=config["fall_asleep_minutes"])).isoformat(),
              "fell_asleep": fell.isoformat(), "woke_up": woke.isoformat(),
              "last_activity": old["last_activity"] if old else "",
              "total_sleep_minutes": total, "awake_minutes": 0, "wakeup_count": 0, "efficiency": 100,
              "segments": [{"start": fell.isoformat(), "end": woke.isoformat(), "minutes": total}],
              "wakeups": []}
    return result, old


def save_correction(path, night, old, fixed):
    new_file = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["night", "detected_asleep", "detected_wake", "last_activity", "fixed_asleep", "fixed_wake"])
        w.writerow([night, old["fell_asleep"] if old else "", old["woke_up"] if old else "",
                    old["last_activity"] if old else "", fixed["fell_asleep"], fixed["woke_up"]])


def learn(corrections_path, learned_path):
    """After 3+ corrections, learn how long YOU take to fall asleep after putting the phone down."""
    if not os.path.exists(corrections_path):
        return None
    with open(corrections_path, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["last_activity"]]
    gaps = []
    for r in rows:
        gap = (datetime.fromisoformat(r["fixed_asleep"]) - datetime.fromisoformat(r["last_activity"])).total_seconds() / 60
        if 0 <= gap <= 90:
            gaps.append(gap)
    if len(gaps) < 3:
        return None
    learned = {"fall_asleep_minutes": int(round(min(45, statistics.median(gaps))))}
    with open(learned_path, "w", encoding="utf-8") as f:
        json.dump(learned, f, indent=2)
    return learned

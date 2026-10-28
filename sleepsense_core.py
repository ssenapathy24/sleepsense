"""
SleepSense core - works out WHEN you slept from your phone activity.

Instead of a single "60 minutes = sleep" rule, every break in phone use gets a
SLEEP SCORE built from several clues (like WHOOP combines sensors):

    + longer break                         (up to 40 points)
    + break falls in the core night hours  (up to 25 points, 23:00-06:00)
    + phone was on charge                  (+25)
    + Sleep Focus was on                   (+30)
    + you tapped the "Going to sleep" button (+100, always sleep)
    + break ended with your alarm / Sleep Focus turning off (+10)
    - steps recorded by the iPhone split the break (you were up and walking)

A break with score >= sleep_threshold counts as sleep. The longest one is your
main sleep, and nearby sleep breaks are joined on (wake-ups / split nights).
Only the Python standard library is used, so it runs in a-Shell on the iPhone.
"""

import json
import os
from datetime import datetime, time, timedelta

DEFAULT_CONFIG = {
    # --- the night ---
    "window_start": "22:00",          # night starts at this time the evening before...
    "window_end": "12:00",            # ...and ends at this time on the day you wake up
    "core_start": "23:00",            # the hours you are most likely asleep
    "core_end": "06:00",

    # --- detecting sleep ---
    "min_break_minutes": 20,          # shorter breaks are ignored completely
    "sleep_threshold": 50,            # score needed for a break to be sleep
    "join_threshold": 35,             # lower score is fine for a break right next to your sleep
    "max_wake_minutes": 30,           # awake this long or less = a wake-up in the night
    "max_split_wake_minutes": 120,    # longer awake time allowed between two strong sleep breaks
    "min_join_break_minutes": 45,     # extra sleep must be at least this long to be joined on
    "fall_asleep_minutes": 10,        # time to fall asleep after putting the phone down
    "min_awake_minutes": 2,           # each wake-up counts as at least this long
    "min_total_sleep_minutes": 120,   # less than this = probably missing data
    "steps_awake_threshold": 15,      # this many steps in one Health sample = you were up
    "still_asleep_minutes": 45,       # no activity this long in the morning = maybe still asleep
    "button_window_minutes": 30,      # button/Sleep Focus counts if the break starts within this time

    # --- scoring points ---
    "points_length_max": 40,
    "points_core_max": 25,
    "points_charging": 25,
    "points_focus": 30,
    "points_button": 100,
    "points_wake_signal": 10,

    # --- naps ---
    "nap_fall_asleep_minutes": 5,
    "min_nap_minutes": 15,

    # --- coaching (see sleepsense_metrics.py) ---
    "sleep_need_minutes": 480,        # your normal sleep need (8h)
    "debt_payback_fraction": 0.25,    # add this share of your sleep debt to tonight's need
    "max_debt_payback_minutes": 60,
    "default_wake_time": "07:30",
    "auto_save_low_confidence": False,  # save "not sure" nights to Health automatically?
}

# Events that only describe a state - they don't mean you touched the phone
MARKER_KINDS = {"sleep_focus_on", "sleep_focus_off"}
WAKE_SIGNALS = {"alarm_stopped", "sleep_focus_off", "awake_button"}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def load_config(path, learned_path=None):
    config = dict(DEFAULT_CONFIG)
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            config.update(json.load(f))
    if learned_path and os.path.exists(learned_path):   # values learned from your corrections
        with open(learned_path, encoding="utf-8") as f:
            config.update(json.load(f))
    return config


def parse_timestamp(text):
    """ISO 8601 from Shortcuts, e.g. 2026-10-28T00:41:10+00:00 or ...Z"""
    text = text.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    return dt if dt.tzinfo else dt.astimezone()


def load_events(path):
    """sleep_log.txt -> sorted list of (time, kind)."""
    events = []
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                parts = [p.strip() for p in line.strip().split(",")]
                if not parts[0]:
                    continue
                try:
                    events.append((parse_timestamp(parts[0]), (parts[1] if len(parts) > 1 and parts[1] else "app").lower()))
                except ValueError:
                    continue
    events.sort(key=lambda e: e[0])
    return events


def load_steps(path, config):
    """steps.txt (start,end,count from Apple Health) -> 'steps' events when you were walking."""
    events = []
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                parts = [p.strip() for p in line.strip().split(",")]
                if len(parts) < 3:
                    continue
                try:
                    start, end, count = parse_timestamp(parts[0]), parse_timestamp(parts[1]), float(parts[2])
                except ValueError:
                    continue
                if count >= config["steps_awake_threshold"] and end >= start:
                    # mark the whole walking period as activity (a point every 5 minutes)
                    t = start
                    while t < end:
                        events.append((t, "steps"))
                        t += timedelta(minutes=5)
                    events.append((end, "steps"))
    return events


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def wall(dt):
    """Time as shown on the phone's clock (no timezone)."""
    return dt.replace(tzinfo=None)


def mins(td):
    return int(round(td.total_seconds() / 60))


def nice(total_minutes):
    total_minutes = int(round(total_minutes))
    sign = "-" if total_minutes < 0 else ""
    h, m = divmod(abs(total_minutes), 60)
    return f"{sign}{h}h {m:02d}m" if h else f"{sign}{m}m"


def hhmm(dt):
    return dt.strftime("%H:%M")


def clock(text):
    return time.fromisoformat(text)


def window_for(night, config):
    """(start, end) wall-clock datetimes of the night that ends on `night`."""
    start = datetime.combine(night - timedelta(days=1), clock(config["window_start"]))
    end = datetime.combine(night, clock(config["window_end"]))
    if end <= start:
        end += timedelta(days=1)
    return start, end


def core_for(night, config):
    s, e = clock(config["core_start"]), clock(config["core_end"])
    start = datetime.combine(night - timedelta(days=1) if s > e else night, s)
    return start, datetime.combine(night, e)


def overlap_minutes(a_start, a_end, b_start, b_end):
    return max(0.0, (min(a_end, b_end) - max(a_start, b_start)).total_seconds() / 60)


def state_at(events, t, on_kind, off_kind):
    """Was a state (charging / Sleep Focus) on at time t? Uses the last on/off event before t."""
    state = False
    for when, kind in events:
        if when > t:
            break
        if kind == on_kind:
            state = True
        elif kind == off_kind:
            state = False
    return state


def any_between(events, kinds, start, end):
    return any(start <= when <= end and kind in kinds for when, kind in events)


# ---------------------------------------------------------------------------
# Breaks and scoring
# ---------------------------------------------------------------------------
def score_break(brk, events, night, config):
    """Give one break a sleep score and a list of human-readable reasons."""
    length = brk["minutes"]
    score, reasons = 0.0, []

    pts = min(config["points_length_max"], length / 6)            # 4h -> 40 points
    score += pts
    reasons.append(f"{nice(length)} without phone (+{pts:.0f})")

    c_start, c_end = core_for(night, config)
    frac = overlap_minutes(wall(brk["start"]), wall(brk["end"]), c_start, c_end) / max(length, 1)
    if frac > 0:
        pts = config["points_core_max"] * frac
        score += pts
        reasons.append(f"{frac:.0%} in core night hours (+{pts:.0f})")

    soon = brk["start"] + timedelta(minutes=config["button_window_minutes"])
    before = brk["start"] - timedelta(minutes=config["button_window_minutes"])

    charging = (state_at(events, brk["start"], "charger_connected", "charger_disconnected")
                and not any_between(events, {"charger_disconnected"}, brk["start"], brk["end"] - timedelta(seconds=1)))
    if charging:
        score += config["points_charging"]
        reasons.append(f"phone charging (+{config['points_charging']})")

    focus = (state_at(events, brk["start"], "sleep_focus_on", "sleep_focus_off")
             or any_between(events, {"sleep_focus_on"}, brk["start"], soon))
    if focus:
        score += config["points_focus"]
        reasons.append(f"Sleep Focus on (+{config['points_focus']})")

    buttons = [w for w, k in events if k == "sleep_button" and before <= w <= brk["start"] + timedelta(minutes=1)]
    if buttons:
        score += config["points_button"]
        reasons.append(f"'Going to sleep' button (+{config['points_button']})")

    if any_between(events, WAKE_SIGNALS, brk["end"] - timedelta(minutes=5), brk["end"] + timedelta(minutes=5)):
        score += config["points_wake_signal"]
        reasons.append(f"ended with alarm/wake signal (+{config['points_wake_signal']})")

    brk.update(score=round(score, 1), reasons=reasons, charging=charging, focus=focus,
               button=buttons[-1] if buttons else None)
    return brk


def find_breaks(events, night, config, now=None):
    """Every break in phone activity (>= min_break_minutes) that touches the night window."""
    win_start, win_end = window_for(night, config)
    lookback = win_start - timedelta(hours=4)
    touches = [w for w, k in events
               if k not in MARKER_KINDS and lookback <= wall(w) <= win_end and (now is None or w <= now)]
    breaks = []
    for a, b in zip(touches, touches[1:]):
        if wall(b) <= win_start or b - a < timedelta(minutes=config["min_break_minutes"]):
            continue
        breaks.append({"start": a, "end": b, "minutes": mins(b - a)})
    return touches, [score_break(brk, events, night, config) for brk in breaks]


# ---------------------------------------------------------------------------
# The night
# ---------------------------------------------------------------------------
def detect_night(events, night, config, now=None):
    win_start, win_end = window_for(night, config)
    touches, breaks = find_breaks(events, night, config, now)
    result = {"found": False, "night": night.isoformat(),
              "breaks": [explain(b, False) for b in breaks]}

    # Maybe still asleep: it's still the night window and the phone has been quiet for a while
    if now is not None and wall(now) < win_end and touches and wall(touches[-1]) >= win_start:
        if now - touches[-1] >= timedelta(minutes=config["still_asleep_minutes"]):
            result["reason"] = f"No phone activity since {hhmm(touches[-1])} - you may still be asleep."
            result["still_asleep"] = True
            return result

    def qualifies(b, threshold):
        return b["score"] >= threshold and (b["minutes"] >= 45 or b["button"] is not None)

    main_options = [i for i, b in enumerate(breaks) if qualifies(b, config["sleep_threshold"])]
    if not main_options:
        result["reason"] = "No break in phone use looked like sleep last night."
        return result
    core = max(main_options, key=lambda i: breaks[i]["minutes"])

    def joins(b, awake):
        """Join a neighbouring break if you were only awake briefly, or if it was clearly sleep too."""
        awake_min = awake.total_seconds() / 60
        long_enough = b["minutes"] >= config["min_join_break_minutes"] or b["button"] is not None
        return long_enough and (
            (awake_min <= config["max_wake_minutes"] and b["score"] >= config["join_threshold"])
            or (awake_min <= config["max_split_wake_minutes"] and qualifies(b, config["sleep_threshold"])))

    lo = hi = core
    while lo > 0 and joins(breaks[lo - 1], breaks[lo]["start"] - breaks[lo - 1]["end"]):
        lo -= 1
    while hi < len(breaks) - 1 and joins(breaks[hi + 1], breaks[hi + 1]["start"] - breaks[hi]["end"]):
        hi += 1
    chain = breaks[lo:hi + 1]

    # Turn breaks into "asleep" segments
    fall_asleep = timedelta(minutes=config["fall_asleep_minutes"])
    segments = []
    for i, b in enumerate(chain):
        long_awake = i == 0 or (b["start"] - chain[i - 1]["end"]) > timedelta(minutes=config["max_wake_minutes"])
        begin = max(b["start"], b["button"] or b["start"])
        start = begin + (fall_asleep if long_awake else timedelta(minutes=config["min_awake_minutes"]))
        if start >= b["end"]:
            start = b["start"]
        segments.append((start, b["end"]))

    total = sum((e - s for s, e in segments), timedelta())
    if total < timedelta(minutes=config["min_total_sleep_minutes"]):
        result["reason"] = f"Only {nice(mins(total))} of sleep found - probably missing data."
        return result

    fell_asleep, woke_up = segments[0][0], segments[-1][1]
    first = chain[0]
    focus_on = [w for w, k in events if k == "sleep_focus_on" and first["start"] - timedelta(hours=1) <= w <= fell_asleep]
    in_bed = min([fell_asleep - fall_asleep] + ([first["button"]] if first["button"] else []) + focus_on)
    wakeups = [(a[1], b[0]) for a, b in zip(segments, segments[1:])]

    # Confidence: strong clues or a very high score = high
    main = breaks[core]
    if main["score"] >= 75 or main["charging"] or main["focus"] or main["button"]:
        confidence = "high"
    elif main["score"] >= 58:
        confidence = "medium"
    else:
        confidence = "low"

    in_chain = {id(b) for b in chain}
    result.update({
        "found": True,
        "confidence": confidence,
        "in_bed_start": in_bed.isoformat(),
        "fell_asleep": fell_asleep.isoformat(),
        "woke_up": woke_up.isoformat(),
        "last_activity": first["start"].isoformat(),
        "total_sleep_minutes": mins(total),
        "awake_minutes": sum(mins(b - a) for a, b in wakeups),
        "wakeup_count": len(wakeups),
        "efficiency": round(100 * total / (woke_up - in_bed)) if woke_up > in_bed else 100,
        "segments": [{"start": s.isoformat(), "end": e.isoformat(), "minutes": mins(e - s)} for s, e in segments],
        "wakeups": [{"start": a.isoformat(), "end": b.isoformat(), "minutes": mins(b - a)} for a, b in wakeups],
        "breaks": [explain(b, id(b) in in_chain) for b in breaks],
    })
    return result


def detect_naps(events, night, config):
    """Naps: you tapped 'Going to sleep' between 12:00 and the start of the night (the day before `night`)."""
    win_start, _ = window_for(night, config)
    day_start = datetime.combine(night - timedelta(days=1), clock(config["window_end"]))
    touches = [w for w, k in events if k not in MARKER_KINDS]
    naps = []
    for when, kind in events:
        if kind != "sleep_button" or not (day_start <= wall(when) < win_start):
            continue
        after = [t for t in touches if t > when + timedelta(seconds=30)]
        if not after:
            continue
        start = when + timedelta(minutes=config["nap_fall_asleep_minutes"])
        if after[0] - start >= timedelta(minutes=config["min_nap_minutes"]):
            naps.append({"start": start.isoformat(), "end": after[0].isoformat(), "minutes": mins(after[0] - start)})
    return naps


def explain(b, counted):
    return {"start": b["start"].isoformat(), "end": b["end"].isoformat(), "minutes": b["minutes"],
            "score": b["score"], "counted_as_sleep": counted, "reasons": b["reasons"]}

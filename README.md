# SleepSense 😴

**WHOOP-style sleep tracking for iPhone, without a watch.**

Samsung phones work out your sleep from your phone use at night. iPhones don't (Apple removed
"Track Time in Bed with iPhone" in iOS 18). SleepSense rebuilds it with **iPhone Shortcuts + Python**,
and adds WHOOP-style coaching: Sleep Performance, Sleep Need, Sleep Debt and Consistency.

```
 Clues from your iPhone                 SleepSense (Python)                     You see
 ──────────────────────                 ───────────────────                     ───────
 apps opened / closed      ─┐
 charger on / off          ─┤          score every break in phone use      ┌─► Morning notification
 Sleep Focus on / off      ─┼─► logs ─► find sleep, wake-ups, split nights ─┼─► Apple Health sleep chart
 alarm stopped             ─┤          Sleep Need / Performance / Debt     ├─► Evening bedtime coach
 "Going to sleep" button   ─┤          learn from your corrections         └─► Weekly report (+ AI tip)
 steps (from Apple Health) ─┘
```

**Morning notification example**

> **Sleep Performance 80% 🟡**
> 7h 14m of 9h 00m needed. Asleep 00:41 → 07:30. Woke 1x: 03:14 (7m). Nap yesterday: 32m.
> Consistency 69%. Sleep debt 4h 31m.

---

## How it decides when you slept

### 1. The night
Only **22:00 → 12:00** counts as night. You can change this in `config.json`.

### 2. Every break in phone use gets a sleep score

| Clue | Points |
|---|---|
| Length of the break | up to **+40** (4h or more) |
| Break is in the core night hours (23:00–06:00) | up to **+25** |
| 🔌 Phone was on charge | **+25** |
| 🌙 Sleep Focus was on | **+30** |
| 👆 You tapped **"Going to sleep"** | **+100** (always sleep) |
| ⏰ Break ended with your alarm / Sleep Focus turning off | **+10** |
| 🚶 Steps recorded by the iPhone | splits the break: you were up and walking |

A break with a **score of 50+** counts as sleep. The **longest** one is your main sleep.

### 3. Wake-ups and split nights
Another break is joined onto your sleep if:
- you were awake **30 min or less** in between (a wake-up), or
- it was clearly sleep too (score 50+) and you were awake **2h or less** (a split night).

### 4. Examples

| What happened | What SleepSense says |
|---|---|
| Phone down 23:00, alarm 07:00 | Asleep 23:10 → 07:00 |
| No phone 23:00–23:15, phone until 00:00, asleep | 15-min break ignored, so asleep **00:10** |
| **Working** 22:30–23:45 (no phone, not charging), phone until 00:30 | Work break scores only 26, so asleep **00:40** |
| **Slept** 22:30–23:45 with phone **on charge**, awake until 00:30 | Scores 52, so asleep **22:40**, woke 23:45–00:40, slept again |
| Same, but you tapped **"Going to sleep"** at 22:30 | Definitely sleep, so in bed from **22:30** |
| No phone 00:00–07:00 but walked 300 steps at 03:00 | Woke up at **03:00** |

To see exactly how each break was scored:

```bash
python3 sleep_calc.py --log sample_log.txt --steps sample_steps.txt --night 2026-10-28 --no-save --explain
```
```
[awake] 22:31 → 23:40  score  26.0  1h 09m without phone (+12); 58% in core night hours (+15)
[SLEEP] 00:31 → 03:14  score 107.1  2h 42m without phone (+27); 100% in core night hours (+25); phone charging (+25); Sleep Focus on (+30)
[SLEEP] 03:18 → 07:30  score 121.0  4h 11m without phone (+40); ... ended with alarm/wake signal (+10)
```

### 5. Confidence
Each night is rated **high**, **medium** or **low**. "Not sure" (low) nights are **not** saved to Health
automatically. The notification asks you to check them with **Edit last night** instead.

---

## The WHOOP-style numbers

| Number | How it's worked out |
|---|---|
| **Sleep Need** | Your normal need (8h) + 25% of your sleep debt (max +1h) |
| **Sleep Performance** | Sleep (including naps) ÷ Sleep Need. 🟢 85%+ · 🟡 70–84% · 🔴 under 70% |
| **Sleep Debt** | How far below 8h you were, added up over the last 7 nights |
| **Consistency** | How similar your bedtime and wake time were over the last 4 nights (100% = identical) |
| **Efficiency** | Time asleep ÷ time in bed |
| **Disturbances** | Number and length of wake-ups |

**Learning:** each time you correct a night with **Edit last night**, it's saved. After 3 corrections,
SleepSense learns how long **you** take to fall asleep after putting your phone down (`learned.json`).

---

## Files

| File | What it does |
|---|---|
| `sleep_calc.py` | The program you run (morning report, `--tonight`, `--week`, `--fix`, `--explain`) |
| `sleepsense_core.py` | Detection: breaks, sleep scores, wake-ups, naps, confidence |
| `sleepsense_metrics.py` | Need, performance, debt, consistency, bedtime coach, weekly report, learning |
| `config.json` | Your settings |
| `test_sleepsense.py` | 19 unit tests, including every example above |
| `sample_log.txt`, `sample_steps.txt` | A fake night for testing |
| `update.sh` | Downloads the latest code from GitHub onto your iPhone |

Files created while it runs (private, kept off GitHub by `.gitignore`): `sleep_log.txt`, `steps.txt`,
`history.csv`, `corrections.csv`, `learned.json`, `result.json`.

---

## Part 1: On your Mac (VS Code + GitHub)

```bash
python3 -m unittest -v                     # run the tests
python3 sleep_calc.py --log sample_log.txt --steps sample_steps.txt --night 2026-10-28 --no-save
python3 sleep_calc.py --tonight --wake 07:00
python3 sleep_calc.py --week
python3 sleep_calc.py --fix --asleep 23:30 --wake 07:00
```

Push to GitHub:
```bash
git init && git add . && git commit -m "SleepSense v2"
git branch -M main
git remote add origin https://github.com/ssenapathy24/sleepsense.git
git push -u origin main
```

---

## Part 2: On your iPhone

> Shortcuts action names can be worded slightly differently on your iOS version. Search the action
> list for the closest match. Allow access to **Health** and **Files** when asked.

### Step 1: a-Shell
1. Install **a-Shell** (free) from the App Store.
2. In a-Shell, download `update.sh` once:
   `curl -L -o update.sh https://raw.githubusercontent.com/ssenapathy24/sleepsense/main/update.sh`
3. Run `sh update.sh`. Do this again whenever you push new code.
4. Test it: `python3 sleep_calc.py --log sample_log.txt --steps sample_steps.txt --night 2026-10-28 --no-save`

### Step 2: Shortcut "Log Phone Activity"
1. **Date** (Current Date)
2. **Format Date**: Custom, `yyyy-MM-dd'T'HH:mm:ssZZZZZ`
3. **Text**: `[Formatted Date],[Shortcut Input]`
4. **Append to Text File**: `sleep_log.txt` in the Shortcuts folder, *Make New Line* on

### Step 3: Shortcut "Going to Sleep 🌙" (your button)
1. **Text** `sleep_button` → **Run Shortcut** "Log Phone Activity"
2. (Optional) **Set Focus**: Sleep → On

Put it on your Home Screen, in Control Centre or on the Action Button. Use it on nights you go to
bed early or **for naps**. Most nights you don't need it.

### Step 4: Automations (they log the clues)
Automation tab → **+**. For each one: **Run Immediately**, **Notify When Run** off.

| Trigger | Action: Text → Run Shortcut "Log Phone Activity" |
|---|---|
| **App**: Instagram, Snapchat, Clock, WhatsApp, Weather, Gmail, Outlook, Spotify, TikTok, Claude, ChatGPT, YouTube, Teams. Tick **Is Opened** and **Is Closed** | `app` |
| **Charger**: Is Connected | `charger_connected` |
| **Charger**: Is Disconnected | `charger_disconnected` |
| **Alarm**: Any, Is Stopped | `alarm_stopped` |
| **Focus**: Sleep, When Turning On | `sleep_focus_on` |
| **Focus**: Sleep, When Turning Off | `sleep_focus_off` |

### Step 5: Shortcut "Morning Sleep Check"
1. **Find Health Samples**: Type **Steps**, Start Date *is in the last* **1 day**
2. **Repeat with Each**:
   - **Get Details of Health Sample**: Start Date → **Format Date** (custom format as above)
   - **Get Details of Health Sample**: End Date → **Format Date**
   - **Get Details of Health Sample**: Value
   - **Text**: `[start],[end],[value]`
3. **End Repeat** → **Combine Text** with New Lines → **Save File** as `steps.txt` (Shortcuts folder, overwrite)
4. **Get File** `sleep_log.txt` → a-Shell **Put File**
5. **Get File** `steps.txt` → a-Shell **Put File**
6. a-Shell **Execute Command**: `python3 sleep_calc.py --quiet`
7. a-Shell **Get File**: `result.json` → **Get Dictionary from Input**
8. **If** `save_to_health` is `yes`:
   - **Repeat with Each** item in `health_asleep`: **Log Health Sample**, Sleep Analysis, **Asleep**,
     Start = `start`, End = `end` (use **Get Dates from Input** on each)
   - **Repeat with Each** item in `health_in_bed`: **Log Health Sample**, Sleep Analysis, **In Bed**
9. **If** `notify` is `yes`: **Show Notification**, title = `title`, body = `summary`

Automations: **Time of Day** at **09:00**, **10:30** and **12:15** → Run "Morning Sleep Check".
Running it several times is safe: if you might still be asleep it waits, and each night is saved
**once** only.

### Step 6: Shortcut "Tonight's Bedtime"
a-Shell Execute Command `python3 sleep_calc.py --tonight --wake 07:00 --quiet` → Get File `result.json`
→ Get Dictionary → **Show Notification** (`title`, `summary`).
Automation: **Time of Day 21:30**, daily. Change `07:00` to your usual alarm.

### Step 7: Shortcut "Edit Last Night"
1. **Ask for Input** (Time): "When did you fall asleep?" → **Format Date** `HH:mm`
2. **Ask for Input** (Time): "When did you wake up?" → **Format Date** `HH:mm`
3. a-Shell Execute Command: `python3 sleep_calc.py --fix --asleep [asleep] --wake [wake] --quiet`
4. Same as Morning Sleep Check steps 7–9 (writes the corrected night to Health)

If the wrong night was already saved, delete it in **Health → Sleep → Show All Data → Edit**.

### Step 8: Shortcut "Sleep Week" (+ optional AI tip)
1. a-Shell Execute Command `python3 sleep_calc.py --week --quiet` → Get File `result.json` → Get Dictionary
2. **Show Notification** with `summary`
3. Optional AI tip: send `ai_prompt` to the **ChatGPT** app's *Ask ChatGPT* action (or another AI app
   with a Shortcuts action) → **Show Notification** with the answer

Automation: **Sunday 19:00**.

---

## Where you see everything
- **Notifications** from the Shortcuts app: morning report, evening bedtime, Sunday summary.
- **Apple Health → Browse → Sleep**: your nights as **Asleep** and **In Bed** bars (day/week/month views).

## Limitations (being honest)
- iOS can't detect every unlock. Only the apps and events you set up are seen.
- No heart-rate sensor, so **no Recovery, HRV, Strain or REM/deep sleep** like a real WHOOP.
- Lying awake without your phone (and not walking) looks like sleep. The button and corrections help.

## Ideas for later
- Home-screen widget (e.g. Scriptable) showing last night's performance
- Learn the scoring weights from your corrections, not just the fall-asleep time
- Read your next alarm automatically for the bedtime coach

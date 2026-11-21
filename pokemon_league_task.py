#!/usr/bin/env python3
"""
Pokemon Remake / Pocket Pet (com.pocketpet.pocpet)
Daily Pokemon League Task Tracker (pokemon_league_task.py)

Maintains the daily 10-match completion goal:
  - Primary Morning Window: 09:30 AM – 10:30 AM IST
  - Afternoon Fallback Window: 04:30 PM – 05:30 PM IST (plays remaining matches if morning < 10)
  - Tracks completed, remaining, window details, and historical daily logs.
"""

import datetime
import json
import os
import sys
import zoneinfo

# Ensure workspace and scripts are in sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(SCRIPT_DIR).lower() == "scripts":
    PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
else:
    PROJECT_ROOT = SCRIPT_DIR

for p in [SCRIPT_DIR, PROJECT_ROOT]:
    if p not in sys.path:
        sys.path.insert(0, p)

DATA_DIR = os.path.join(PROJECT_ROOT, "data")
TASK_FILE = os.path.join(DATA_DIR, "pokemon_league_task.json")


def get_local_tz():
    """Returns Asia/Kolkata (IST, UTC+05:30) with fallback."""
    try:
        return zoneinfo.ZoneInfo("Asia/Kolkata")
    except Exception:
        return datetime.timezone(datetime.timedelta(hours=5, minutes=30), name="IST")


def get_now_ist() -> datetime.datetime:
    return datetime.datetime.now(get_local_tz())


def format_ist_timestamp(dt: datetime.datetime | None = None) -> str:
    if dt is None:
        dt = get_now_ist()
    return dt.strftime("%Y-%m-%d %H:%M:%S IST")


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def get_default_task_for_today(today_str: str | None = None) -> dict:
    if not today_str:
        today_str = get_now_ist().strftime("%Y-%m-%d")

    return {
        "date": today_str,
        "daily_target": 10,
        "completed_today": 0,
        "remaining_today": 10,
        "daily_status": "in_progress",  # "in_progress" | "completed"
        "updated_time": format_ist_timestamp(),
        "morning_window": {
            "from": "09:30",
            "to": "10:30",
            "status": "pending",  # "pending" | "running" | "finished" | "not_needed"
            "matches_cleared": 0,
            "last_run": None
        },
        "afternoon_window": {
            "from": "16:30",
            "to": "17:30",
            "status": "pending",  # "pending" | "running" | "finished" | "not_needed"
            "matches_cleared": 0,
            "last_run": None
        },
        "history": []
    }


def load_league_task() -> dict:
    """Loads the daily task. If day has rolled over, archives previous day and resets."""
    ensure_data_dir()
    today_str = get_now_ist().strftime("%Y-%m-%d")

    task = None
    if os.path.exists(TASK_FILE):
        try:
            with open(TASK_FILE, "r", encoding="utf-8") as f:
                task = json.load(f)
        except Exception:
            task = None

    if not task:
        task = get_default_task_for_today(today_str)
        save_league_task(task)
        return task

    # Check for day rollover
    recorded_date = task.get("date")
    if recorded_date != today_str:
        # Archive yesterday's outcome to history
        history = task.get("history", [])
        archive_entry = {
            "date": recorded_date,
            "daily_target": task.get("daily_target", 10),
            "completed_today": task.get("completed_today", 0),
            "remaining_today": task.get("remaining_today", 0),
            "daily_status": task.get("daily_status", "in_progress"),
            "morning_cleared": task.get("morning_window", {}).get("matches_cleared", 0),
            "afternoon_cleared": task.get("afternoon_window", {}).get("matches_cleared", 0),
            "closed_at": format_ist_timestamp()
        }
        history.insert(0, archive_entry)
        history = history[:30]  # Keep last 30 days

        # Preserve configured window times
        m_from = task.get("morning_window", {}).get("from", "09:30")
        m_to = task.get("morning_window", {}).get("to", "10:30")
        a_from = task.get("afternoon_window", {}).get("from", "16:30")
        a_to = task.get("afternoon_window", {}).get("to", "17:30")
        target = task.get("daily_target", 10)

        task = get_default_task_for_today(today_str)
        task["daily_target"] = target
        task["remaining_today"] = target
        task["morning_window"]["from"] = m_from
        task["morning_window"]["to"] = m_to
        task["afternoon_window"]["from"] = a_from
        task["afternoon_window"]["to"] = a_to
        task["history"] = history
        save_league_task(task)

    return task


def save_league_task(task: dict):
    ensure_data_dir()
    task["updated_time"] = format_ist_timestamp()
    temp_file = TASK_FILE + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(task, f, indent=2)
    os.replace(temp_file, TASK_FILE)


def record_matches_cleared(
    matches_cleared_in_session: int,
    window_name: str | None = None
) -> dict:
    """Records matches cleared in a session and recalculates remaining target."""
    task = load_league_task()

    if window_name == "morning":
        m_win = task.setdefault("morning_window", {})
        m_win["matches_cleared"] = m_win.get("matches_cleared", 0) + matches_cleared_in_session
        m_win["last_run"] = format_ist_timestamp()
        m_win["status"] = "finished"
    elif window_name == "afternoon":
        a_win = task.setdefault("afternoon_window", {})
        a_win["matches_cleared"] = a_win.get("matches_cleared", 0) + matches_cleared_in_session
        a_win["last_run"] = format_ist_timestamp()
        a_win["status"] = "finished"

    # Update overall day counters
    completed = task.get("completed_today", 0) + matches_cleared_in_session
    target = task.get("daily_target", 10)
    task["completed_today"] = completed
    task["remaining_today"] = max(0, target - completed)

    if task["remaining_today"] == 0:
        task["daily_status"] = "completed"
        # If target reached in morning, afternoon window is not needed
        if window_name == "morning":
            task.setdefault("afternoon_window", {})["status"] = "not_needed"
    else:
        task["daily_status"] = "in_progress"

    save_league_task(task)
    return task


def update_league_task_settings(
    morning_from: str = "09:30",
    morning_to: str = "10:30",
    afternoon_from: str = "16:30",
    afternoon_to: str = "17:30",
    daily_target: int = 10
) -> dict:
    """Updates time windows and daily match target."""
    task = load_league_task()
    task["daily_target"] = daily_target
    task.setdefault("morning_window", {})["from"] = morning_from.strip()
    task["morning_window"]["to"] = morning_to.strip()
    task.setdefault("afternoon_window", {})["from"] = afternoon_from.strip()
    task["afternoon_window"]["to"] = afternoon_to.strip()

    completed = task.get("completed_today", 0)
    task["remaining_today"] = max(0, daily_target - completed)
    task["daily_status"] = "completed" if task["remaining_today"] == 0 else "in_progress"

    save_league_task(task)
    return task


def compute_next_league_trigger(task: dict | None = None) -> tuple[datetime.datetime, str, int]:
    """
    Computes the upcoming trigger datetime in IST, which window it belongs to, and needed matches.
    Returns: (next_dt, window_name, matches_needed)
    """
    if task is None:
        task = load_league_task()

    now = get_now_ist()
    target = task.get("daily_target", 10)
    completed = task.get("completed_today", 0)
    remaining = max(0, target - completed)

    m_from_str = task.get("morning_window", {}).get("from", "09:30")
    m_to_str = task.get("morning_window", {}).get("to", "10:30")
    a_from_str = task.get("afternoon_window", {}).get("from", "16:30")
    a_to_str = task.get("afternoon_window", {}).get("to", "17:30")

    def parse_time_today(t_str: str) -> datetime.datetime:
        parts = t_str.strip().split(":")
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
        return now.replace(hour=h, minute=m, second=0, microsecond=0)

    m_from_dt = parse_time_today(m_from_str)
    m_to_dt = parse_time_today(m_to_str)
    a_from_dt = parse_time_today(a_from_str)
    a_to_dt = parse_time_today(a_to_str)

    # Case 1: Today's goal already completed -> Next run is tomorrow morning
    if remaining == 0:
        next_dt = m_from_dt + datetime.timedelta(days=1)
        return (next_dt, "morning", target)

    # Case 2: Currently inside Morning window [m_from, m_to)
    if m_from_dt <= now < m_to_dt:
        return (now, "morning", remaining)

    # Case 3: Before Morning window today
    if now < m_from_dt:
        return (m_from_dt, "morning", remaining)

    # Case 4: Currently inside Afternoon window [a_from, a_to)
    if a_from_dt <= now < a_to_dt:
        return (now, "afternoon", remaining)

    # Case 5: Between Morning and Afternoon windows
    if m_to_dt <= now < a_from_dt:
        return (a_from_dt, "afternoon", remaining)

    # Case 6: Past Afternoon window today -> Tomorrow morning
    next_dt = m_from_dt + datetime.timedelta(days=1)
    return (next_dt, "morning", target)


if __name__ == "__main__":
    t = load_league_task()
    print("Loaded Pokemon League Task:")
    print(json.dumps(t, indent=2))
    nxt_dt, win, needed = compute_next_league_trigger(t)
    print(f"\nNext trigger: {nxt_dt} ({win} window, {needed} matches needed)")

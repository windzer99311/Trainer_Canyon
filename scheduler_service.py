#!/usr/bin/env python3
"""
Pokemon Remake / Pocket Pet (com.pocketpet.pocpet)
Multi-Service Daily Automation Scheduler Daemon

Supports automated daily schedules:
  1. Pokemon League: Everyday at 9:30 AM IST (Runs until 10:30 AM IST or 10 matches cleared)
  2. Elite Battle: Everyday at 9:32 PM IST (3 battles)
Runs as an independent background daemon with persistent state and logging.
"""

import argparse
import datetime
import json
import os
import subprocess
import sys
import time
import zoneinfo

# Reconfigure stdout/stderr for UTF-8 on Windows
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

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
SCHEDULER_STATE_FILE = os.path.join(DATA_DIR, "scheduler_state.json")
SCHEDULER_LOG_FILE = os.path.join(DATA_DIR, "scheduler.log")


def get_local_tz():
    """Returns local timezone (Asia/Kolkata / IST, UTC+05:30) with fallback."""
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


def log_scheduler(msg: str):
    timestamp = format_ist_timestamp()
    formatted = f"[{timestamp}] {msg}"

    # 1. Write to scheduler log file
    try:
        ensure_data_dir()
        with open(SCHEDULER_LOG_FILE, "a", encoding="utf-8", errors="replace") as f:
            f.write(formatted + "\n")
            f.flush()
    except Exception:
        pass

    # 2. Print to stdout safely
    try:
        print(formatted, flush=True)
    except Exception:
        try:
            safe_msg = formatted.encode("ascii", errors="replace").decode("ascii")
            print(safe_msg, flush=True)
        except Exception:
            pass


def compute_next_run(target_time_str: str) -> datetime.datetime:
    """Computes the upcoming datetime in IST for the target HH:MM."""
    parts = target_time_str.strip().split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0

    now = get_now_ist()
    target_today = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if now >= target_today:
        return target_today + datetime.timedelta(days=1)
    else:
        return target_today


def get_default_schedules() -> dict:
    next_league = compute_next_run("09:30")
    next_elite = compute_next_run("21:32")
    return {
        "league": {
            "name": "Pokemon League (Morning Window)",
            "target_time": "09:30",
            "cutoff": "10:30",
            "matches": 10,
            "next_run": format_ist_timestamp(next_league),
            "last_run": None,
            "enabled": True,
            "description": "Daily 9:30 AM – 10:30 AM IST (Max 10 matches or 10:30 AM cutoff)"
        },
        "elite": {
            "name": "Elite Battle (Night Run)",
            "target_time": "21:32",
            "battles": 3,
            "next_run": format_ist_timestamp(next_elite),
            "last_run": None,
            "enabled": True,
            "description": "Daily 9:32 PM IST (3 Battles)"
        }
    }


def get_scheduler_state() -> dict:
    ensure_data_dir()
    if os.path.exists(SCHEDULER_STATE_FILE):
        try:
            with open(SCHEDULER_STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
                if "schedules" not in state:
                    state["schedules"] = get_default_schedules()
                return state
        except Exception:
            pass
    return {
        "status": "sleep",
        "pid": None,
        "start_time": None,
        "updated_time": None,
        "schedules": get_default_schedules(),
        "message": "Scheduler is idle (sleep)."
    }


def update_scheduler_state(**kwargs):
    ensure_data_dir()
    state = get_scheduler_state()
    state.update(kwargs)
    state["updated_time"] = format_ist_timestamp()
    temp_file = SCHEDULER_STATE_FILE + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(temp_file, SCHEDULER_STATE_FILE)


def resolve_service_script(service_name: str) -> str:
    if service_name == "league":
        candidates = [
            os.path.join(PROJECT_ROOT, "scripts", "pokemon_league_service.py"),
            os.path.join(PROJECT_ROOT, "pokemon_league_service.py"),
        ]
    elif service_name == "elite":
        candidates = [
            os.path.join(PROJECT_ROOT, "scripts", "elite_battle_service.py"),
            os.path.join(PROJECT_ROOT, "elite_battle_service.py"),
        ]
    else:
        candidates = [
            os.path.join(PROJECT_ROOT, "scripts", "legendary_trail_service.py"),
            os.path.join(PROJECT_ROOT, "legendary_trail_service.py"),
        ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[0]


def run_scheduler_daemon(
    target_service: str = "all",
    account: str = "tx263424183",
    password: str = "380746",
    server_id: int = 182,
    dry_run: bool = False
):
    my_pid = os.getpid()
    log_scheduler("=" * 65)
    log_scheduler(f"⏰ DAILY AUTOMATION SCHEDULER DAEMON STARTED (PID: {my_pid})")
    log_scheduler(f"   Mode: {target_service.upper()} | Timezone: IST (UTC+05:30)")
    log_scheduler("   Schedules active:")
    log_scheduler("     1. Pokemon League: Daily 09:30 AM IST (until 10:30 AM or 10 matches)")
    log_scheduler("     2. Elite Battle:   Daily 09:32 PM IST (3 battles)")
    log_scheduler("=" * 65)

    state = get_scheduler_state()
    schedules = state.get("schedules", get_default_schedules())

    # Initialize next run times
    for s_key, s_data in schedules.items():
        nxt = compute_next_run(s_data["target_time"])
        s_data["next_run"] = format_ist_timestamp(nxt)
        log_scheduler(f"[+] [{s_data['name']}] Next trigger: {s_data['next_run']}")

    update_scheduler_state(
        status="running",
        pid=my_pid,
        start_time=format_ist_timestamp(),
        schedules=schedules,
        message="Scheduler active: Monitoring daily schedules for Pokemon League & Elite Battle."
    )

    try:
        while True:
            now = get_now_ist()
            state = get_scheduler_state()
            schedules = state.get("schedules", schedules)

            for s_key in ["league", "elite"]:
                if target_service != "all" and target_service != s_key:
                    continue

                s_data = schedules.get(s_key)
                if not s_data or not s_data.get("enabled", True):
                    continue

                target_time = s_data["target_time"]
                # Parse or compute next run datetime
                next_run_dt = compute_next_run(target_time)

                # Check if current time is within 10 seconds of target or trigger is due
                now_str = now.strftime("%H:%M")
                if now_str == target_time and (now.second <= 10):
                    log_scheduler("=" * 65)
                    log_scheduler(f"🔔 TRIGGER TIME REACHED FOR {s_data['name'].upper()} ({target_time} IST)!")
                    log_scheduler("=" * 65)

                    if dry_run:
                        log_scheduler(f"[DRY-RUN] Simulated trigger for {s_key} completed successfully.")
                    else:
                        script_path = resolve_service_script(s_key)
                        if s_key == "league":
                            cmd = [
                                sys.executable,
                                script_path,
                                "--matches", str(s_data.get("matches", 10)),
                                "--cutoff", str(s_data.get("cutoff", "10:30")),
                                "--account", account,
                                "--password", password,
                                "--server-id", str(server_id)
                            ]
                        else:  # elite
                            cmd = [
                                sys.executable,
                                script_path,
                                "--battles", str(s_data.get("battles", 3)),
                                "--account", account,
                                "--password", password,
                                "--server-id", str(server_id)
                            ]

                        sub_env = os.environ.copy()
                        sub_env["PYTHONIOENCODING"] = "utf-8"
                        sub_env["PYTHONUTF8"] = "1"
                        sub_env["PYTHONUNBUFFERED"] = "1"

                        log_scheduler(f"[*] Spawning service: {' '.join(cmd)}")
                        proc = subprocess.Popen(cmd, env=sub_env)
                        proc.wait()
                        log_scheduler(f"[+] Service {s_key} finished with exit code: {proc.returncode}")

                    # Update last run and schedule next run (tomorrow)
                    last_run_str = format_ist_timestamp()
                    s_data["last_run"] = last_run_str
                    nxt = compute_next_run(target_time)
                    s_data["next_run"] = format_ist_timestamp(nxt)
                    log_scheduler(f"[+] Completed {s_key} run. Next trigger scheduled for: {s_data['next_run']}")

                    update_scheduler_state(schedules=schedules)
                    # Sleep through the rest of this trigger minute to avoid double firing
                    time.sleep(60)
                    break

            time.sleep(5)

    except (KeyboardInterrupt, SystemExit):
        log_scheduler("[*] Scheduler daemon received termination signal.")
    except Exception as e:
        log_scheduler(f"[-] Scheduler daemon error: {e}")
    finally:
        update_scheduler_state(
            status="sleep",
            pid=None,
            message="Scheduler daemon stopped (sleep)."
        )
        log_scheduler("💤 Scheduler daemon stopped.")


def main():
    parser = argparse.ArgumentParser(description="Multi-Service Daily Automation Scheduler")
    parser.add_argument("--service", default="all", choices=["all", "league", "elite"], help="Service(s) to schedule (default: all)")
    parser.add_argument("--account", default="tx263424183", help="Account name")
    parser.add_argument("--password", default="380746", help="Account password")
    parser.add_argument("--server-id", default=182, type=int, help="Server ID")
    parser.add_argument("--dry-run", action="store_true", help="Simulate execution without running real battle")
    args = parser.parse_args()

    run_scheduler_daemon(
        target_service=args.service,
        account=args.account,
        password=args.password,
        server_id=args.server_id,
        dry_run=args.dry_run
    )


if __name__ == "__main__":
    main()

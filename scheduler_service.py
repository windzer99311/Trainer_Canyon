#!/usr/bin/env python3
"""
Pokemon Remake / Pocket Pet (com.pocketpet.pocpet)
Daily Automation Scheduler Service

Schedules and automatically executes bot services (default: Elite Battle 3 battles)
every day at a designated local time (default: 9:32 PM / 21:32 IST, Asia/Kolkata).
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


def get_scheduler_state() -> dict:
    ensure_data_dir()
    if os.path.exists(SCHEDULER_STATE_FILE):
        try:
            with open(SCHEDULER_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "status": "sleep",
        "target_service": "elite",
        "target_time": "21:32",
        "battles": 3,
        "pid": None,
        "start_time": None,
        "next_run": None,
        "last_run": None,
        "updated_time": None,
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


def compute_next_run(target_time_str: str) -> datetime.datetime:
    """Computes the upcoming datetime in IST for the target HH:MM."""
    parts = target_time_str.strip().split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0

    now = get_now_ist()
    target_today = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if now >= target_today:
        # Target time already passed today, schedule for tomorrow
        return target_today + datetime.timedelta(days=1)
    else:
        return target_today


def resolve_service_script(service_name: str) -> str:
    if service_name == "elite":
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
    target_time_str: str = "21:32",
    target_service: str = "elite",
    battles: int = 3,
    account: str = "tx263424183",
    password: str = "380746",
    server_id: int = 182,
    dry_run: bool = False
):
    my_pid = os.getpid()
    log_scheduler("=" * 65)
    log_scheduler(f"⏰ DAILY SCHEDULER DAEMON STARTED (PID: {my_pid})")
    log_scheduler(f"   Target Service: {target_service.upper()} | Battles: {battles}")
    log_scheduler(f"   Scheduled Time: {target_time_str} IST (9:32 PM) Every Day")
    log_scheduler("=" * 65)

    next_run = compute_next_run(target_time_str)
    next_run_str = format_ist_timestamp(next_run)
    log_scheduler(f"[+] Next scheduled run: {next_run_str}")

    update_scheduler_state(
        status="running",
        target_service=target_service,
        target_time=target_time_str,
        battles=battles,
        pid=my_pid,
        start_time=format_ist_timestamp(),
        next_run=next_run_str,
        message=f"Waiting for {target_time_str} IST ({next_run_str})..."
    )

    try:
        while True:
            now = get_now_ist()
            remaining = (next_run - now).total_seconds()

            if remaining <= 0:
                log_scheduler("=" * 65)
                log_scheduler(f"🔔 TRIGGER TIME REACHED ({target_time_str} IST)!")
                log_scheduler(f"   Executing daily scheduled {target_service.upper()} service...")
                log_scheduler("=" * 65)

                if dry_run:
                    log_scheduler("[DRY-RUN] Simulated battle trigger completed successfully.")
                else:
                    script_path = resolve_service_script(target_service)
                    cmd = [
                        sys.executable,
                        script_path,
                        "--battles", str(battles),
                        "--account", account,
                        "--password", password,
                        "--server-id", str(server_id)
                    ]

                    # Run service and wait for completion
                    sub_env = os.environ.copy()
                    sub_env["PYTHONIOENCODING"] = "utf-8"
                    sub_env["PYTHONUTF8"] = "1"
                    sub_env["PYTHONUNBUFFERED"] = "1"

                    log_scheduler(f"[*] Spawning: {' '.join(cmd)}")
                    proc = subprocess.Popen(cmd, env=sub_env)
                    proc.wait()
                    log_scheduler(f"[+] Service finished with exit code: {proc.returncode}")

                last_run_str = format_ist_timestamp()
                next_run = compute_next_run(target_time_str)
                next_run_str = format_ist_timestamp(next_run)

                log_scheduler(f"[+] Completed scheduled execution. Next run set to: {next_run_str}")
                update_scheduler_state(
                    last_run=last_run_str,
                    next_run=next_run_str,
                    message=f"Last run: {last_run_str}. Next run: {next_run_str}."
                )

            # Sleep in 5-second intervals to remain responsive to state updates
            sleep_chunk = min(5.0, max(0.5, remaining))
            time.sleep(sleep_chunk)

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
    parser = argparse.ArgumentParser(description="REA Bot Daily Automation Scheduler")
    parser.add_argument("--target-time", default="21:32", help="Target time in 24hr HH:MM format (default: 21:32 for 9:32 PM IST)")
    parser.add_argument("--service", default="elite", choices=["elite", "trail"], help="Service to trigger (default: elite)")
    parser.add_argument("--battles", default=3, type=int, choices=[1, 2, 3, 4], help="Number of battles for elite (default: 3)")
    parser.add_argument("--account", default="tx263424183", help="Account name")
    parser.add_argument("--password", default="380746", help="Account password")
    parser.add_argument("--server-id", default=182, type=int, help="Server ID")
    parser.add_argument("--dry-run", action="store_true", help="Simulate execution without running real battle")
    args = parser.parse_args()

    run_scheduler_daemon(
        target_time_str=args.target_time,
        target_service=args.service,
        battles=args.battles,
        account=args.account,
        password=args.password,
        server_id=args.server_id,
        dry_run=args.dry_run
    )


if __name__ == "__main__":
    main()

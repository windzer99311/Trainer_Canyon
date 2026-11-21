#!/usr/bin/env python3
"""
Pokemon Remake / Pocket Pet (com.pocketpet.pocpet)
Multi-Service Daily Automation Scheduler Daemon (scheduler_service.py)

Provides independent daily scheduling for:
  1. Pokemon League Auto-Pilot: Daily customizable From -> To window (e.g. 09:30 AM -> 10:30 AM IST),
     runs matchmaking until target matches (default 10) or cutoff time is reached.
  2. Elite Battle Scheduler: Daily customizable trigger time (e.g. 21:32 IST),
     clears target battles (default 3).

Can run as an independent daemon for:
  - --service league : Pokemon League Auto-Pilot only
  - --service elite  : Elite Battle Scheduler only
  - --service all    : Both services simultaneously
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
GLOBAL_STATE_FILE = os.path.join(DATA_DIR, "scheduler_state.json")
GLOBAL_LOG_FILE = os.path.join(DATA_DIR, "scheduler.log")

SERVICE_FILES = {
    "league": {
        "state_file": os.path.join(DATA_DIR, "scheduler_league_state.json"),
        "log_file": os.path.join(DATA_DIR, "scheduler_league.log"),
    },
    "elite": {
        "state_file": os.path.join(DATA_DIR, "scheduler_elite_state.json"),
        "log_file": os.path.join(DATA_DIR, "scheduler_elite.log"),
    }
}


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


def log_scheduler(msg: str, service_key: str = "global"):
    timestamp = format_ist_timestamp()
    formatted = f"[{timestamp}] {msg}"

    # 1. Write to service-specific log file if applicable
    ensure_data_dir()
    if service_key in SERVICE_FILES:
        try:
            with open(SERVICE_FILES[service_key]["log_file"], "a", encoding="utf-8", errors="replace") as f:
                f.write(formatted + "\n")
                f.flush()
        except Exception:
            pass

    # 2. Write to global scheduler log file
    try:
        with open(GLOBAL_LOG_FILE, "a", encoding="utf-8", errors="replace") as f:
            f.write(formatted + "\n")
            f.flush()
    except Exception:
        pass

    # 3. Print to stdout safely
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


def is_within_window(from_time_str: str, to_time_str: str) -> bool:
    """Returns True if current IST time is within [from_time, to_time)."""
    now = get_now_ist()
    try:
        f_parts = from_time_str.strip().split(":")
        t_parts = to_time_str.strip().split(":")
        f_dt = now.replace(hour=int(f_parts[0]), minute=int(f_parts[1]), second=0, microsecond=0)
        t_dt = now.replace(hour=int(t_parts[0]), minute=int(t_parts[1]), second=0, microsecond=0)
        return f_dt <= now < t_dt
    except Exception:
        return False


def already_ran_today(last_run_str: str | None) -> bool:
    """Checks whether the last run occurred today in IST."""
    if not last_run_str:
        return False
    try:
        last_date = last_run_str.split()[0]
        today_date = get_now_ist().strftime("%Y-%m-%d")
        return last_date == today_date
    except Exception:
        return False


def get_default_service_state(service_key: str) -> dict:
    if service_key == "league":
        next_dt = compute_next_run("09:30")
        return {
            "service": "league",
            "name": "Pokemon League Daily Auto-Pilot",
            "status": "sleep",
            "pid": None,
            "start_time": None,
            "updated_time": None,
            "from_time": "09:30",
            "to_time": "10:30",
            "target_matches": 10,
            "next_run": format_ist_timestamp(next_dt),
            "last_run": None,
            "message": "League Auto-Pilot is idle (sleep)."
        }
    elif service_key == "elite":
        next_dt = compute_next_run("21:32")
        return {
            "service": "elite",
            "name": "Elite Battle Daily Scheduler",
            "status": "sleep",
            "pid": None,
            "start_time": None,
            "updated_time": None,
            "trigger_time": "21:32",
            "target_battles": 3,
            "next_run": format_ist_timestamp(next_dt),
            "last_run": None,
            "message": "Elite Battle scheduler is idle (sleep)."
        }
    return {}


def load_scheduler_state(service_key: str) -> dict:
    ensure_data_dir()
    if service_key in SERVICE_FILES:
        path = SERVICE_FILES[service_key]["state_file"]
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return get_default_service_state(service_key)

    # Global / legacy scheduler state
    if os.path.exists(GLOBAL_STATE_FILE):
        try:
            with open(GLOBAL_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "status": "sleep",
        "pid": None,
        "start_time": None,
        "updated_time": None,
        "message": "Scheduler daemon is idle (sleep)."
    }


def save_scheduler_state(service_key: str, state: dict):
    ensure_data_dir()
    state["updated_time"] = format_ist_timestamp()
    if service_key in SERVICE_FILES:
        path = SERVICE_FILES[service_key]["state_file"]
        temp_file = path + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(temp_file, path)

    # Also update global state file summary
    try:
        league_st = load_scheduler_state("league") if service_key != "league" else state
        elite_st = load_scheduler_state("elite") if service_key != "elite" else state
        summary = {
            "updated_time": format_ist_timestamp(),
            "league": league_st,
            "elite": elite_st
        }
        temp_global = GLOBAL_STATE_FILE + ".tmp"
        with open(temp_global, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        os.replace(temp_global, GLOBAL_STATE_FILE)
    except Exception:
        pass


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
    override_from: str | None = None,
    override_to: str | None = None,
    override_matches: int | None = None,
    override_time: str | None = None,
    override_battles: int | None = None,
    dry_run: bool = False
):
    my_pid = os.getpid()
    log_scheduler("=" * 65, target_service)
    log_scheduler(f"⏰ DAILY AUTOMATION SCHEDULER DAEMON STARTED (PID: {my_pid})", target_service)
    log_scheduler(f"   Target Service: {target_service.upper()} | Timezone: IST (UTC+05:30)", target_service)

    # Determine which services this daemon manages
    active_keys = ["league", "elite"] if target_service == "all" else [target_service]

    # Initialize states and apply CLI overrides if provided
    for s_key in active_keys:
        s_state = load_scheduler_state(s_key)
        if s_key == "league":
            if override_from:
                s_state["from_time"] = override_from
            if override_to:
                s_state["to_time"] = override_to
            if override_matches:
                s_state["target_matches"] = override_matches
            nxt = compute_next_run(s_state.get("from_time", "09:30"))
            s_state["next_run"] = format_ist_timestamp(nxt)
            s_state["status"] = "running"
            s_state["pid"] = my_pid
            s_state["start_time"] = format_ist_timestamp()
            s_state["message"] = (
                f"League Auto-Pilot active (Daily {s_state['from_time']} -> {s_state['to_time']} IST, "
                f"{s_state['target_matches']} matches max)."
            )
            save_scheduler_state("league", s_state)
            log_scheduler(
                f"[+] [League Auto-Pilot] Window: {s_state['from_time']} -> {s_state['to_time']} IST | "
                f"Next trigger: {s_state['next_run']}", "league"
            )

        elif s_key == "elite":
            if override_time:
                s_state["trigger_time"] = override_time
            if override_battles:
                s_state["target_battles"] = override_battles
            nxt = compute_next_run(s_state.get("trigger_time", "21:32"))
            s_state["next_run"] = format_ist_timestamp(nxt)
            s_state["status"] = "running"
            s_state["pid"] = my_pid
            s_state["start_time"] = format_ist_timestamp()
            s_state["message"] = (
                f"Elite Battle scheduler active (Daily {s_state['trigger_time']} IST, "
                f"{s_state['target_battles']} battles)."
            )
            save_scheduler_state("elite", s_state)
            log_scheduler(
                f"[+] [Elite Battle Scheduler] Trigger: {s_state['trigger_time']} IST | "
                f"Next trigger: {s_state['next_run']}", "elite"
            )

    log_scheduler("=" * 65, target_service)

    try:
        while True:
            now = get_now_ist()
            now_hhmm = now.strftime("%H:%M")

            for s_key in active_keys:
                s_state = load_scheduler_state(s_key)

                if s_key == "league":
                    from_time = s_state.get("from_time", "09:30")
                    to_time = s_state.get("to_time", "10:30")
                    matches = s_state.get("target_matches", 10)
                    last_run = s_state.get("last_run")

                    should_trigger = False
                    reason = ""

                    # 1. Exact minute trigger at from_time
                    if now_hhmm == from_time and not already_ran_today(last_run):
                        should_trigger = True
                        reason = f"scheduled start time reached ({from_time} IST)"
                    # 2. Currently inside window [from_time, to_time) and hasn't run yet today
                    elif is_within_window(from_time, to_time) and not already_ran_today(last_run):
                        should_trigger = True
                        reason = f"daemon started inside active window [{from_time} -> {to_time} IST]"

                    if should_trigger:
                        log_scheduler("=" * 65, "league")
                        log_scheduler(f"🔔 POKEMON LEAGUE AUTO-PILOT TRIGGERED ({reason})!", "league")
                        log_scheduler("=" * 65, "league")

                        if dry_run:
                            log_scheduler("[DRY-RUN] Simulated League run completed successfully.", "league")
                        else:
                            script_path = resolve_service_script("league")
                            cmd = [
                                sys.executable,
                                script_path,
                                "--matches", str(matches),
                                "--cutoff", str(to_time),
                                "--account", account,
                                "--password", password,
                                "--server-id", str(server_id)
                            ]
                            sub_env = os.environ.copy()
                            sub_env["PYTHONIOENCODING"] = "utf-8"
                            sub_env["PYTHONUTF8"] = "1"
                            sub_env["PYTHONUNBUFFERED"] = "1"

                            log_scheduler(f"[*] Spawning service: {' '.join(cmd)}", "league")
                            proc = subprocess.Popen(cmd, env=sub_env)
                            proc.wait()
                            log_scheduler(f"[+] League service process exited with code: {proc.returncode}", "league")

                        s_state["last_run"] = format_ist_timestamp()
                        nxt = compute_next_run(from_time)
                        s_state["next_run"] = format_ist_timestamp(nxt)
                        save_scheduler_state("league", s_state)
                        log_scheduler(f"[+] League Auto-Pilot run recorded. Next scheduled trigger: {s_state['next_run']}", "league")
                        # Sleep through current minute to prevent duplicate trigger
                        time.sleep(60)
                        break

                elif s_key == "elite":
                    trigger_time = s_state.get("trigger_time", "21:32")
                    battles = s_state.get("target_battles", 3)
                    last_run = s_state.get("last_run")

                    if now_hhmm == trigger_time and not already_ran_today(last_run):
                        log_scheduler("=" * 65, "elite")
                        log_scheduler(f"🔔 ELITE BATTLE SCHEDULER TRIGGERED ({trigger_time} IST)!", "elite")
                        log_scheduler("=" * 65, "elite")

                        if dry_run:
                            log_scheduler("[DRY-RUN] Simulated Elite Battle run completed successfully.", "elite")
                        else:
                            script_path = resolve_service_script("elite")
                            cmd = [
                                sys.executable,
                                script_path,
                                "--battles", str(battles),
                                "--account", account,
                                "--password", password,
                                "--server-id", str(server_id)
                            ]
                            sub_env = os.environ.copy()
                            sub_env["PYTHONIOENCODING"] = "utf-8"
                            sub_env["PYTHONUTF8"] = "1"
                            sub_env["PYTHONUNBUFFERED"] = "1"

                            log_scheduler(f"[*] Spawning service: {' '.join(cmd)}", "elite")
                            proc = subprocess.Popen(cmd, env=sub_env)
                            proc.wait()
                            log_scheduler(f"[+] Elite service process exited with code: {proc.returncode}", "elite")

                        s_state["last_run"] = format_ist_timestamp()
                        nxt = compute_next_run(trigger_time)
                        s_state["next_run"] = format_ist_timestamp(nxt)
                        save_scheduler_state("elite", s_state)
                        log_scheduler(f"[+] Elite Battle run recorded. Next scheduled trigger: {s_state['next_run']}", "elite")
                        # Sleep through current minute to prevent duplicate trigger
                        time.sleep(60)
                        break

            time.sleep(5)

    except (KeyboardInterrupt, SystemExit):
        log_scheduler("[*] Scheduler daemon received termination signal.", target_service)
    except Exception as e:
        log_scheduler(f"[-] Scheduler daemon error: {e}", target_service)
    finally:
        for s_key in active_keys:
            s_state = load_scheduler_state(s_key)
            s_state["status"] = "sleep"
            s_state["pid"] = None
            s_state["message"] = f"{s_state.get('name', s_key)} stopped (sleep)."
            save_scheduler_state(s_key, s_state)
        log_scheduler(f"💤 Scheduler daemon ({target_service}) stopped.", target_service)


def main():
    parser = argparse.ArgumentParser(description="Multi-Service Daily Automation Scheduler")
    parser.add_argument("--service", default="all", choices=["all", "league", "elite"], help="Service to schedule: league, elite, or all")
    parser.add_argument("--from-time", dest="from_time", default=None, help="League From time (HH:MM IST, e.g. 09:30)")
    parser.add_argument("--to-time", dest="to_time", default=None, help="League To/Cutoff time (HH:MM IST, e.g. 10:30)")
    parser.add_argument("--matches", type=int, default=None, help="League target matches (e.g. 10)")
    parser.add_argument("--time", dest="trigger_time", default=None, help="Elite trigger time (HH:MM IST, e.g. 21:32)")
    parser.add_argument("--battles", type=int, default=None, help="Elite target battles (1-4, e.g. 3)")
    parser.add_argument("--account", default="tx263424183", help="Account name")
    parser.add_argument("--password", default="380746", help="Account password")
    parser.add_argument("--server-id", default=182, type=int, help="Server ID")
    parser.add_argument("--dry-run", action="store_true", help="Simulate execution without running real battles")
    args = parser.parse_args()

    run_scheduler_daemon(
        target_service=args.service,
        account=args.account,
        password=args.password,
        server_id=args.server_id,
        override_from=args.from_time,
        override_to=args.to_time,
        override_matches=args.matches,
        override_time=args.trigger_time,
        override_battles=args.battles,
        dry_run=args.dry_run
    )


if __name__ == "__main__":
    main()

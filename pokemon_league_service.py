#!/usr/bin/env python3
"""
Pokemon Remake / Pocket Pet (com.pocketpet.pocpet)
Pokemon League Automated Service (pokemon_league_service.py)

Runs matchmaking and battles between 9:30 AM and 10:30 AM IST (or custom cutoff).
Terminates when:
  1. Target successful matches (default 10) are cleared, OR
  2. Current time exceeds cutoff time (default 10:30 AM IST), OR
  3. Device login kick packet is received (Cmd 101: 00 00 00 05 00 00 00 00 65), OR
  4. Manually stopped by user.
"""

import argparse
import datetime
import json
import os
import struct
import sys
import time
import traceback
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

# Ensure workspace and scripts are in sys.path (prioritizing SCRIPT_DIR over root stubs)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(SCRIPT_DIR).lower() == "scripts":
    PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
else:
    PROJECT_ROOT = SCRIPT_DIR

if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)
if SCRIPT_DIR in sys.path:
    sys.path.remove(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from login_account import gateway_login, xor_crypt
from pokemon_league import (
    PokemonLeagueBot,
    derive_battle_key_from_1902,
    DEFAULT_BATTLE_KEY,
    CMD_HEARTBEAT,
    CMD_LEAGUE_WINDOW,
    CMD_LEAGUE_RECORDS,
    CMD_MATCH_INIT,
    CMD_LEAGUE_CHALLENGE,
    PLAINTEXT_1911_INIT,
    PLAINTEXT_1901_LEAGUE,
)

# ==========================================
# FILE PATHS & CONSTANTS
# ==========================================
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
STATE_FILE = os.path.join(DATA_DIR, "league_state.json")
LOG_FILE = os.path.join(DATA_DIR, "league_activity.log")

KICK_SIGNATURE = b"\x00\x00\x00\x05\x00\x00\x00\x00\x65"


class DeviceLoginKickException(Exception):
    """Raised when the game server kicks the session due to login from mobile device."""
    pass


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


def log_activity(msg: str):
    """Logs message with timestamp in IST to activity log file and console safely."""
    timestamp = format_ist_timestamp()
    formatted = f"[{timestamp}] {msg}"

    # 1. Write to log file first
    try:
        ensure_data_dir()
        with open(LOG_FILE, "a", encoding="utf-8", errors="replace") as f:
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


def get_current_state() -> dict:
    ensure_data_dir()
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "status": "sleep",
        "service_name": "pokemon_league",
        "target_matches": 10,
        "completed_matches": 0,
        "queue_attempts": 0,
        "cutoff_time": "10:30",
        "pid": None,
        "start_time": None,
        "updated_time": None,
        "device_login_alert": False,
        "message": "Service is idle (sleep)."
    }


def update_state(**kwargs):
    ensure_data_dir()
    state = get_current_state()
    state.update(kwargs)
    state["updated_time"] = format_ist_timestamp()
    temp_file = STATE_FILE + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(temp_file, STATE_FILE)


def is_device_login_kick(resp_body: bytes) -> bool:
    """Checks if server response matches the mobile device login kick packet."""
    if not resp_body:
        return False
    if resp_body == KICK_SIGNATURE:
        return True
    return False


def compute_cutoff_datetime(cutoff_str: str = "10:30") -> datetime.datetime:
    """Computes the cutoff datetime for today in IST."""
    parts = cutoff_str.strip().split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0
    now = get_now_ist()
    cutoff_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    # If starting before cutoff, cutoff is today. If starting after cutoff, schedule for next occurrence.
    return cutoff_dt


class RobustLeagueBot(PokemonLeagueBot):
    """Enhanced PokemonLeagueBot that verifies device kick responses."""

    def send_game_cmd(self, cmd_id: int, plaintext: bytes = b"", desc: str = "") -> tuple[int, bytes]:
        st_code, resp = super().send_game_cmd(cmd_id, plaintext, desc)
        if is_device_login_kick(resp):
            raise DeviceLoginKickException("User logged into game from another device (Cmd 101 kick signature detected).")
        return st_code, resp


def run_single_league_encounter(
    bot: RobustLeagueBot,
    is_first_init: bool = False,
    timeout: float = 40.0,
    interval: float = 1.0,
    match_duration: float = 60.0,
) -> bool:
    """
    Attempts to queue and encounter a player.
    Returns True if an opponent was encountered and the battle finished, False if timed out without player.
    """
    if bot.sock is None:
        bot.connect()

    if is_first_init:
        # Pre-queue handshakes
        for _ in range(2):
            bot.send_game_cmd(CMD_HEARTBEAT, b"", desc="Pre-Queue Sync")
            time.sleep(0.3)
        bot.send_game_cmd(CMD_LEAGUE_WINDOW, b"", desc="League Window Query")
        time.sleep(0.3)
        bot.send_game_cmd(CMD_LEAGUE_RECORDS, b"", desc="League Ranking / Records")
        time.sleep(0.3)
        bot.send_game_cmd(CMD_HEARTBEAT, b"", desc="Pre-Queue Heartbeat")
        time.sleep(0.3)
        bot.send_game_cmd(CMD_MATCH_INIT, PLAINTEXT_1911_INIT, desc="Match Queue Init ('fr')")
        time.sleep(0.5)

    # Send challenge initiation
    bot.send_game_cmd(CMD_LEAGUE_CHALLENGE, PLAINTEXT_1901_LEAGUE, desc="League Challenge Initiation")
    time.sleep(0.5)

    # Poll heartbeats for match encounter (Cmd 1902)
    start_time = time.time()
    hb_count = 0
    matched = False
    battle_key = b""
    encounter_time = None

    while (time.time() - start_time) < timeout:
        hb_count += 1
        elapsed = time.time() - start_time

        st_code, resp = bot.send_game_cmd(CMD_HEARTBEAT, b"", desc=f"HB #{hb_count:02d} (+{elapsed:4.1f}s)")

        if b"\x00\x00\x07\x6e" in resp:
            derived = derive_battle_key_from_1902(resp, bot.session_token_str)
            if derived and len(derived) == 53:
                encounter_time = time.time()
                matched = True
                battle_key = derived
                log_activity(f"[🎯] PLAYER ENCOUNTERED! (Cmd 1902 verified on HB #{hb_count}, {len(resp)} bytes)")
                break

        time.sleep(interval)

    if not matched:
        log_activity(f"[⏱️] Queue attempt timed out: No opponent found within {timeout:.0f}s.")
        return False

    # Opponent found: Close Connection #1 and start Connection #3 Battle Protocol
    log_activity(f"[+] Verified battle room key ({len(battle_key)} B). Starting battle socket protocol ({match_duration:.0f}s)...")
    bot.close_world_socket()

    # Execute synchronous battle
    bot.run_battle_socket_protocol(
        battle_key=battle_key,
        encounter_time=encounter_time,
        total_duration_sec=match_duration
    )
    log_activity(f"[🏆] Match finished successfully ({match_duration:.0f}s elapsed)!")
    return True


def run_league_service(
    target_matches: int = 10,
    cutoff_time_str: str = "10:30",
    account: str = "tx263424183",
    password: str = "380746",
    server_id: int = 182,
    timeout: float = 40.0,
    interval: float = 1.0,
    match_duration: float = 60.0,
    dry_run: bool = False
):
    my_pid = os.getpid()
    log_activity("=" * 65)
    log_activity(f"🏆 POKEMON LEAGUE SERVICE STARTED (PID: {my_pid})")
    log_activity(f"   Target Matches: {target_matches} | Cutoff Time: {cutoff_time_str} IST")
    log_activity(f"   Account: {account} | Server ID: {server_id}")
    log_activity("=" * 65)

    cutoff_dt = compute_cutoff_datetime(cutoff_time_str)
    log_activity(f"[*] Session will run unlimited queues until 10 matches cleared or {cutoff_dt.strftime('%I:%M %p')} IST cutoff.")

    update_state(
        status="running",
        service_name="pokemon_league",
        target_matches=target_matches,
        completed_matches=0,
        queue_attempts=0,
        cutoff_time=cutoff_time_str,
        pid=my_pid,
        start_time=format_ist_timestamp(),
        device_login_alert=False,
        message=f"Starting Pokemon League session (Target: {target_matches} matches, Cutoff: {cutoff_time_str} IST)..."
    )

    completed_matches = 0
    queue_attempts = 0

    if dry_run:
        log_activity("[DRY-RUN] Simulating Pokemon League execution...")
        time.sleep(1)
        update_state(status="sleep", pid=None, message="Dry-run completed.")
        log_activity("[DRY-RUN] Finished.")
        return

    try:
        while completed_matches < target_matches:
            # Check cutoff condition
            now = get_now_ist()
            if now >= cutoff_dt:
                log_activity(f"[-] CUTOFF REACHED: Current time ({now.strftime('%I:%M:%S %p')} IST) reached or exceeded {cutoff_time_str} IST.")
                log_activity(f"    Ending Pokemon League run. Cleared: {completed_matches}/{target_matches} matches.")
                break

            queue_attempts += 1
            log_activity(f"\n--- [Queue Attempt #{queue_attempts}] Seeking Opponent (Matches Cleared: {completed_matches}/{target_matches}) ---")
            update_state(
                completed_matches=completed_matches,
                queue_attempts=queue_attempts,
                message=f"Queuing for match #{completed_matches + 1} ({completed_matches}/{target_matches} cleared)..."
            )

            # Fresh login for each attempt to keep sessions clean
            log_activity("[*] Authenticating with Gateway...")
            gw_token, s_ip, s_port = gateway_login(account, password, server_id)
            if not gw_token:
                log_activity("[!] Gateway login failed, retrying in 3.0s...")
                time.sleep(3.0)
                continue

            bot = RobustLeagueBot(
                s_ip,
                s_port,
                gw_token,
                server_id,
                account=account,
                password=password,
                battle_port=9861,
                worker_id=completed_matches + 1,
            )

            try:
                bot.login()
                is_first_attempt = (queue_attempts == 1 or completed_matches == 0)
                matched = run_single_league_encounter(
                    bot,
                    is_first_init=is_first_attempt,
                    timeout=timeout,
                    interval=interval,
                    match_duration=match_duration
                )

                if matched:
                    completed_matches += 1
                    update_state(
                        completed_matches=completed_matches,
                        message=f"Match #{completed_matches} cleared! ({completed_matches}/{target_matches})"
                    )
                    log_activity(f"[🎉] MATCH #{completed_matches}/{target_matches} OFFICIALLY LOGGED!")
                    if completed_matches < target_matches:
                        log_activity("[*] Waiting 2.0s before initiating next match search...")
                        time.sleep(2.0)
                else:
                    log_activity("[*] No opponent in this queue attempt. Continuing search...")
                    time.sleep(2.0)

            finally:
                bot.close()

        # Summary upon exit
        if completed_matches >= target_matches:
            summary = f"TARGET REACHED: Successfully completed all {completed_matches}/{target_matches} matches in {queue_attempts} queue attempts!"
        else:
            summary = f"Session concluded at cutoff: {completed_matches}/{target_matches} matches cleared in {queue_attempts} queue attempts."

        log_activity(f"[+] {summary}")
        update_state(
            status="sleep",
            completed_matches=completed_matches,
            pid=None,
            device_login_alert=False,
            message=summary
        )

    except DeviceLoginKickException as e:
        alert_msg = "DEVICE LOGIN DETECTED: You logged into the game from your mobile device! Service stopped immediately."
        log_activity(f"[ALERT] {alert_msg}")
        update_state(
            status="sleep",
            pid=None,
            device_login_alert=True,
            message=alert_msg
        )

    except Exception as e:
        tb = traceback.format_exc()
        err_msg = f"Pokemon League service encountered an error: {e}"
        log_activity(f"[-] {err_msg}")
        log_activity(f"Traceback:\n{tb}")
        update_state(
            status="sleep",
            pid=None,
            message=err_msg
        )

    finally:
        log_activity("[*] Pokemon League service entered SLEEP mode.")


def main():
    parser = argparse.ArgumentParser(description="Pokemon League Automated Service")
    parser.add_argument("--matches", "-n", dest="matches", type=int, default=10, help="Target successful matches (default: 10)")
    parser.add_argument("--cutoff", dest="cutoff", default="10:30", help="Cutoff time in 24hr HH:MM format (default: 10:30 IST)")
    parser.add_argument("--account", "-a", default="tx263424183", help="Account username")
    parser.add_argument("--password", "-p", default="380746", help="Account password")
    parser.add_argument("--server-id", "-s", default=182, type=int, help="Server ID (default: 182)")
    parser.add_argument("--timeout", "-t", default=40.0, type=float, help="Matchmaking queue timeout in seconds (default: 40.0)")
    parser.add_argument("--match-duration", "-d", default=60.0, type=float, help="Match duration in seconds (default: 60.0)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate run without real network calls")
    args = parser.parse_args()

    run_league_service(
        target_matches=args.matches,
        cutoff_time_str=args.cutoff,
        account=args.account,
        password=args.password,
        server_id=args.server_id,
        timeout=args.timeout,
        match_duration=args.match_duration,
        dry_run=args.dry_run
    )


if __name__ == "__main__":
    main()

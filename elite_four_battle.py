#!/usr/bin/env python3
"""
Pokemon Remake / Pocket Pet (com.pocketpet.pocpet)
Elite Four Battle Background Service

Runs independently of the Streamlit dashboard.
Maintains state in data/elite_state.json and logs to data/elite_activity.log.
Detects mobile device login kick (Cmd 101: 00 00 00 05 00 00 00 00 65) and stops immediately.
"""

import argparse
import datetime
import json
import os
import struct
import sys
import time
import traceback

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

from login_account import GameSession, gateway_login, xor_crypt
from elite_four_battle import (
    CMD_START_BATTLE,
    CMD_BATTLE_RESULT,
    CMD_RETURN_CITY,
    CMD_HEARTBEAT_BATTLE,
    PLAINTEXT_ELITE_S182_T1,
    PLAINTEXT_1203_T1,
    PLAINTEXT_ELITE_S182_T2,
    PLAINTEXT_1203_T2,
    PLAINTEXT_ELITE_WINDZER,
    PLAINTEXT_1203_WINDZER,
    PLAINTEXT_ELITE_ALT_1202,
    PLAINTEXT_1203_ALT,
    PLAINTEXT_1000,
)

# ==========================================
# FILE PATHS & CONSTANTS
# ==========================================
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
STATE_FILE = os.path.join(DATA_DIR, "elite_state.json")
LOG_FILE = os.path.join(DATA_DIR, "elite_activity.log")

KICK_SIGNATURE = b"\x00\x00\x00\x05\x00\x00\x00\x00\x65"
KICK_CMD_END = b"\x00\x00\x00\x00\x65"

TRAINER_NAMES = {
    1: "Fighting Bruno (0xce)",
    2: "Dragon Lance (0xb5)",
    3: "Extreme Challenger Windzer (0xb9)",
    4: "Alternate Day Extreme (0xba)",
}


class DeviceLoginKickException(Exception):
    """Raised when the game server kicks the session due to login from mobile device."""
    pass


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def get_local_tz():
    try:
        import zoneinfo
        return zoneinfo.ZoneInfo("Asia/Kolkata")
    except Exception:
        return datetime.timezone(datetime.timedelta(hours=5, minutes=30), name="IST")


def get_now_ist() -> datetime.datetime:
    return datetime.datetime.now(get_local_tz())


def format_ist_timestamp(dt: datetime.datetime | None = None) -> str:
    if dt is None:
        dt = get_now_ist()
    return dt.strftime("%Y-%m-%d %H:%M:%S IST")


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
        "service_name": "elite_battle",
        "target_battles": 3,
        "cleared_battles": 0,
        "current_trainer": None,
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
    """Checks if server response matches the device login kick packet."""
    if not resp_body:
        return False
    if resp_body == KICK_SIGNATURE:
        return True
    if len(resp_body) >= 5 and resp_body.endswith(KICK_CMD_END):
        return True
    if KICK_CMD_END in resp_body:
        return True
    return False


class EliteGameSession(GameSession):
    """
    Enhanced GameSession that handles TCP stream buffering and inspects all server responses
    for device login kicks (00 00 00 05 00 00 00 00 65).
    """

    def __init__(self, host: str, port: int, gateway_token: bytes, server_id: int):
        super().__init__(host, port, gateway_token, server_id)
        self._recv_buf = bytearray()

    def _recv_exact(self, n: int) -> bytes:
        while len(self._recv_buf) < n:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            self._recv_buf.extend(chunk)
        res = bytes(self._recv_buf[:n])
        del self._recv_buf[:n]
        return res

    def _recv_until(self, delimiter: bytes) -> bytes:
        while delimiter not in self._recv_buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            self._recv_buf.extend(chunk)
        pos = self._recv_buf.find(delimiter)
        if pos == -1:
            res = bytes(self._recv_buf)
            self._recv_buf.clear()
            return res
        res = bytes(self._recv_buf[: pos + len(delimiter)])
        del self._recv_buf[: pos + len(delimiter)]
        return res

    def send_http(self, body: bytes) -> tuple[bytes, bytes]:
        p = (
            b"POST / HTTP/1.1\r\n"
            b"Content-Type: application/x-www-form-urlencoded\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n"
            b"Expect: 100-continue\r\n"
            b"Connection: keep-alive\r\n"
            b"Host: " + f"{self.host}:{self.port}".encode() + b"\r\n\r\n"
        )
        self.sock.sendall(p)

        # Wait for 100 Continue
        c100 = self._recv_until(b"\r\n\r\n")

        # Check if kick packet arrived prematurely in the buffer
        if is_device_login_kick(bytes(self._recv_buf)):
            raise DeviceLoginKickException("User logged in from another device (premature kick in buffer)")

        self.sock.sendall(body)

        # Read HTTP response header (e.g. HTTP/1.1 200 OK)
        hdr = self._recv_until(b"\r\n\r\n")

        cl = 0
        for l in hdr.decode("ascii", errors="ignore").split("\r\n"):
            if l.lower().startswith("content-length:"):
                cl = int(l.split(":")[1].strip())
                break

        body_data = self._recv_exact(cl)

        # Inspect body for kick signature
        if is_device_login_kick(body_data):
            raise DeviceLoginKickException(
                "User logged in from device (Server returned kick signature: 00 00 00 05 00 00 00 00 65)"
            )

        return hdr, body_data


def send_combat_heartbeat(bot: EliteGameSession) -> bool:
    """Sends a single in-battle heartbeat (Cmd 1000) and verifies response."""
    enc_hb = xor_crypt(PLAINTEXT_1000, bot.session_token_str)
    body_hb = bot.token_prefix + struct.pack(">I", CMD_HEARTBEAT_BATTLE) + enc_hb
    _, resp_hb = bot.send_http(body_hb)
    return True


def execute_single_battle(bot: EliteGameSession, trainer_id: int, combat_seconds: int = 5) -> bool:
    """
    Executes a single battle against the specified trainer ID (1-4).
    Returns True if battle was won and rewards claimed, False if rejected/locked.
    """
    trainer_name = TRAINER_NAMES.get(trainer_id, f"Trainer {trainer_id}")
    log_activity(f"[*] Initiating battle with {trainer_name}...")
    update_state(current_trainer=trainer_name, message=f"Battling {trainer_name}")

    # 1. Select payload
    if trainer_id == 4:
        payload = PLAINTEXT_ELITE_ALT_1202
        win_payload = PLAINTEXT_1203_ALT
    elif trainer_id == 3:
        payload = PLAINTEXT_ELITE_WINDZER
        win_payload = PLAINTEXT_1203_WINDZER
    elif trainer_id == 2:
        payload = PLAINTEXT_ELITE_S182_T2
        win_payload = PLAINTEXT_1203_T2
    else:
        payload = PLAINTEXT_ELITE_S182_T1
        win_payload = PLAINTEXT_1203_T1

    # 2. Encrypt & Send Start Battle (Cmd 1202)
    enc_1202 = xor_crypt(payload, bot.session_token_str)
    body_1202 = bot.token_prefix + struct.pack(">I", CMD_START_BATTLE) + enc_1202
    _, resp_1202 = bot.send_http(body_1202)

    status_1202 = resp_1202[4] if len(resp_1202) >= 5 else -1
    if status_1202 != 0:
        log_activity(f"[-] {trainer_name} battle start rejected (Status: {status_1202}). (Limit reached, locked, or insufficient attempts)")
        return False

    log_activity(f"[+] Battle started with {trainer_name}! Simulating combat ({combat_seconds}s)...")

    # 3. Combat Heartbeats (Cmd 1000)
    start_t = time.time()
    hb_count = 0
    while time.time() - start_t < combat_seconds:
        time.sleep(2)
        hb_count += 1
        send_combat_heartbeat(bot)
        log_activity(f"    In-Combat Heartbeat #{hb_count} ACK")

    # 4. Victory Claim (Cmd 1203)
    enc_1203 = xor_crypt(win_payload, bot.session_token_str)
    body_1203 = bot.token_prefix + struct.pack(">I", CMD_BATTLE_RESULT) + enc_1203
    _, resp_res = bot.send_http(body_1203)

    status_1203 = resp_res[4] if len(resp_res) >= 5 else -1
    if status_1203 != 0:
        log_activity(f"[-] Victory claim rejected for {trainer_name} (Status: {status_1203})")
        return False

    log_activity(f"[+] Victory verified! Reward package: {len(resp_res)} bytes")

    # 5. Return to City Scene (Cmd 2002)
    body_2002 = bot.token_prefix + struct.pack(">I", CMD_RETURN_CITY)
    bot.send_http(body_2002)
    log_activity(f"[+] Returned to city scene. {trainer_name} battle completed successfully!")

    return True


def run_elite_service(
    target_battles: int = 3,
    target_trainer: int | None = None,
    account: str = "tx263424183",
    password: str = "380746",
    server_id: int = 182,
    combat_time: int = 5
):
    my_pid = os.getpid()
    log_activity("=" * 65)
    log_activity(f"ELITE BATTLE SERVICE STARTED (PID: {my_pid})")
    log_activity(f"Target Battles: {target_battles} | Specific Trainer: {target_trainer or 'Auto (4->3->2->1)'}")
    log_activity(f"Account: {account} | Server: {server_id}")
    log_activity("=" * 65)

    update_state(
        status="running",
        service_name="elite_battle",
        target_battles=target_battles,
        cleared_battles=0,
        current_trainer=None,
        pid=my_pid,
        start_time=format_ist_timestamp(),
        device_login_alert=False,
        message=f"Starting Elite Battle run ({target_battles} battles)..."
    )

    bot = None
    try:
        # Step 1: Gateway login
        log_activity("[*] Authenticating with game gateway...")
        token, srv_ip, srv_port = gateway_login(account, password, server_id)
        if not token:
            raise RuntimeError("Gateway login authentication failed.")

        # Step 2: World server login
        log_activity(f"[*] Connecting to World Server ({srv_ip}:{srv_port})...")
        bot = EliteGameSession(srv_ip, srv_port, token, server_id)
        bot.login()
        log_activity("[+] Session established and world data synced successfully.")

        # Step 3: Run Elite Battles
        cleared_count = 0

        if target_trainer is not None:
            # Single specific trainer targeted
            trainer_name = TRAINER_NAMES.get(target_trainer, f"Trainer {target_trainer}")
            log_activity(f"[*] Targeting specific trainer: {trainer_name}")
            for b_idx in range(target_battles):
                log_activity(f"\n>>> Battle {b_idx + 1}/{target_battles} against {trainer_name} <<<")
                ok = execute_single_battle(bot, target_trainer, combat_seconds=combat_time)
                if not ok:
                    log_activity(f"[-] {trainer_name} is no longer available.")
                    break
                cleared_count += 1
                update_state(cleared_battles=cleared_count)
                if cleared_count < target_battles:
                    log_activity("[*] Inter-battle rest: sending synchronization heartbeats...")
                    for _ in range(2):
                        time.sleep(2)
                        send_combat_heartbeat(bot)
        else:
            # Auto smart fallback: Trainer 4 -> Trainer 3 -> Trainer 2 -> Trainer 1
            challengers = [
                (4, "Alternate Day Extreme (0xba)"),
                (3, "Extreme Challenger Windzer (0xb9)"),
                (2, "Dragon Lance (0xb5)"),
                (1, "Fighting Bruno (0xce)"),
            ]
            for t_id, t_name in challengers:
                if cleared_count >= target_battles:
                    break
                log_activity(f"[*] Checking availability for {t_name}...")
                while cleared_count < target_battles:
                    log_activity(f"\n>>> Attempting Battle against {t_name} (Cleared: {cleared_count}/{target_battles}) <<<")
                    ok = execute_single_battle(bot, t_id, combat_seconds=combat_time)
                    if ok:
                        cleared_count += 1
                        update_state(cleared_battles=cleared_count)
                        if cleared_count < target_battles:
                            log_activity("[*] Inter-battle rest: sending synchronization heartbeats...")
                            for _ in range(2):
                                time.sleep(2)
                                send_combat_heartbeat(bot)
                    else:
                        log_activity(f"[-] {t_name} is not available (limit reached or locked). Trying next...")
                        break

        summary_msg = f"Completed Elite Battle run. Victories claimed: {cleared_count}/{target_battles}."
        log_activity(f"[+] {summary_msg}")
        update_state(
            status="sleep",
            cleared_battles=cleared_count,
            current_trainer=None,
            pid=None,
            device_login_alert=False,
            message=summary_msg
        )

    except DeviceLoginKickException as e:
        alert_msg = "DEVICE LOGIN DETECTED: You logged into your account from another device! Service stopped immediately."
        log_activity(f"[ALERT] {alert_msg}")
        log_activity(f"Details: {e}")
        update_state(
            status="sleep",
            pid=None,
            device_login_alert=True,
            message=alert_msg
        )

    except Exception as e:
        tb = traceback.format_exc()
        err_msg = f"Elite service encountered an error: {e}"
        log_activity(f"[-] {err_msg}")
        log_activity(f"Traceback:\n{tb}")
        update_state(
            status="sleep",
            pid=None,
            message=err_msg
        )

    finally:
        if bot:
            try:
                bot.close()
            except Exception:
                pass
        log_activity("[*] Elite Battle service entered SLEEP mode.")


def main():
    parser = argparse.ArgumentParser(description="Elite Four Battle Background Service")
    parser.add_argument("--battles", "-n", dest="battles", type=int, default=3, choices=[1, 2, 3, 4], help="Number of battles (1-4, default: 3)")
    parser.add_argument("--trainer", "-t", dest="trainer", type=int, default=None, choices=[1, 2, 3, 4], help="Target specific trainer (1-4)")
    parser.add_argument("--account", "-a", default="tx263424183", help="Account username")
    parser.add_argument("--password", "-p", default="380746", help="Account password")
    parser.add_argument("--server-id", "-s", default=182, type=int, help="Server ID (default: 182)")
    parser.add_argument("--combat-time", "-c", default=5, type=int, help="Combat wait time in seconds")
    args = parser.parse_args()

    run_elite_service(
        target_battles=args.battles,
        target_trainer=args.trainer,
        account=args.account,
        password=args.password,
        server_id=args.server_id,
        combat_time=args.combat_time
    )


if __name__ == "__main__":
    main()

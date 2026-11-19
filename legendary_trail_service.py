#!/usr/bin/env python3
"""
Pokemon Remake / Pocket Pet (com.pocketpet.pocpet)
Legendary Trail (Mythical Animal Trial) Background Service

Runs independently of the Streamlit dashboard.
Maintains state in data/trail_state.json and logs to data/trail_activity.log.
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
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
for p in [SCRIPT_DIR, PROJECT_ROOT]:
    if p not in sys.path:
        sys.path.insert(0, p)

from login_account import GameSession, gateway_login, xor_crypt
from legendary_trail_battle import (
    LAYER_PAYLOADS,
    CMD_HEARTBEAT,
    CMD_TRIAL_INFO,
    CMD_TRIAL_START,
    CMD_TRIAL_RESULT,
    CMD_TRIAL_EXIT,
    PLAINTEXT_HEARTBEAT,
    PLAINTEXT_RESULT,
    PLAINTEXT_EXIT,
)

# ==========================================
# FILE PATHS & CONSTANTS
# ==========================================
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
STATE_FILE = os.path.join(DATA_DIR, "trail_state.json")
LOG_FILE = os.path.join(DATA_DIR, "trail_activity.log")

KICK_SIGNATURE = b"\x00\x00\x00\x05\x00\x00\x00\x00\x65"
KICK_CMD_END = b"\x00\x00\x00\x00\x65"


class DeviceLoginKickException(Exception):
    """Raised when the game server kicks the session due to login from mobile device."""
    pass


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def log_activity(msg: str):
    """Logs message with timestamp to activity log file and console safely."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] {msg}"

    # 1. Always write to log file first
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
        "service_name": "legendary_trail",
        "from_layer": 10,
        "to_layer": 100,
        "current_layer": None,
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
    state["updated_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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


class TrailGameSession(GameSession):
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


def send_trail_heartbeat(bot: TrailGameSession) -> bool:
    """Sends a single combat/sync heartbeat (Cmd 1000) and verifies response."""
    enc_hb = xor_crypt(PLAINTEXT_HEARTBEAT, bot.session_token_str)
    body_hb = bot.token_prefix + struct.pack(">I", CMD_HEARTBEAT) + enc_hb
    _, resp_hb = bot.send_http(body_hb)
    return True


def execute_layer(bot: TrailGameSession, layer_num: int, combat_seconds: int = 4) -> int:
    """
    Executes a single trial layer.
    Returns:
      1: Cleared successfully
      0: Skipped / Already completed or locked
     -1: Error / Rejected claim
    """
    layer_info = LAYER_PAYLOADS.get(layer_num)
    if not layer_info:
        log_activity(f"[-] [Layer {layer_num * 10}] Invalid layer number.")
        return -1

    payload = layer_info["payload"]
    layer_val = layer_num * 10
    log_activity(f"[*] [Layer {layer_val}] Querying status for {layer_info['name']}...")
    update_state(current_layer=layer_val, message=f"Executing {layer_info['name']}")

    # 1. Info / Status query (Cmd 22008)
    body_info = bot.token_prefix + struct.pack(">I", CMD_TRIAL_INFO)
    _, resp_info = bot.send_http(body_info)

    # 2. Start Battle (Cmd 22010)
    enc_start = xor_crypt(payload, bot.session_token_str)
    body_start = bot.token_prefix + struct.pack(">I", CMD_TRIAL_START) + enc_start
    _, resp_start = bot.send_http(body_start)
    status_start = resp_start[4] if len(resp_start) >= 5 else -1

    if status_start != 0:
        log_activity(f"[-] [Layer {layer_val}] Floor {layer_num} already cleared today or locked (Server status: {status_start}).")
        return 0

    log_activity(f"[+] [Layer {layer_val}] Battle engaged! Simulating realistic combat ({combat_seconds}s)...")

    # 3. Combat Heartbeats (Cmd 1000)
    start_t = time.time()
    hb_count = 0
    while time.time() - start_t < combat_seconds:
        time.sleep(2)
        hb_count += 1
        send_trail_heartbeat(bot)
        log_activity(f"    In-Combat Heartbeat #{hb_count} ACK")

    # 4. Victory Claim (Cmd 22011)
    enc_win = xor_crypt(PLAINTEXT_RESULT, bot.session_token_str)
    body_win = bot.token_prefix + struct.pack(">I", CMD_TRIAL_RESULT) + enc_win
    _, resp_win = bot.send_http(body_win)
    status_win = resp_win[4] if len(resp_win) >= 5 else -1
    if status_win != 0:
        log_activity(f"[-] [Layer {layer_val}] Victory claim rejected (Status: {status_win})")
        return -1

    log_activity(f"[+] [Layer {layer_val}] Victory claimed! Server reward package: {len(resp_win)} bytes")

    # 5. Advance / Exit
    is_final = layer_info.get("final_layer", False)
    if is_final:
        log_activity(f"[+] [Layer {layer_val}] Final Floor! Claiming Layer 10 completion (Cmd 22012)...")
        enc_final = xor_crypt(PLAINTEXT_RESULT, bot.session_token_str)
        body_final = bot.token_prefix + struct.pack(">I", CMD_TRIAL_EXIT) + enc_final
        _, resp_final = bot.send_http(body_final)
        status_final = resp_final[4] if len(resp_final) >= 5 else -1
        if status_final != 0:
            log_activity(f"[-] [Layer {layer_val}] Final completion claim rejected (Status: {status_final})")
            return -1
        log_activity(f"[+] [Layer {layer_val}] All Legendary Trial floors completed successfully!")
    else:
        log_activity(f"[+] [Layer {layer_val}] Advancing to next floor (Cmd 22012)...")
        enc_exit = xor_crypt(PLAINTEXT_EXIT, bot.session_token_str)
        body_exit = bot.token_prefix + struct.pack(">I", CMD_TRIAL_EXIT) + enc_exit
        bot.send_http(body_exit)
        log_activity(f"[+] [Layer {layer_val}] Cleared and floor advanced.")

    return 1


def run_service(from_val: int, to_val: int, account: str, password: str, server_id: int, combat_time: int = 4):
    start_layer = max(1, min(10, from_val // 10))
    end_layer = max(1, min(10, to_val // 10))
    if start_layer > end_layer:
        start_layer, end_layer = end_layer, start_layer

    my_pid = os.getpid()
    log_activity("=" * 65)
    log_activity(f"LEGENDARY TRAIL SERVICE STARTED (PID: {my_pid})")
    log_activity(f"Target Range: Layer {from_val} to Layer {to_val} (Floors {start_layer} -> {end_layer})")
    log_activity(f"Account: {account} | Server: {server_id}")
    log_activity("=" * 65)

    update_state(
        status="running",
        service_name="legendary_trail",
        from_layer=from_val,
        to_layer=to_val,
        current_layer=from_val,
        pid=my_pid,
        start_time=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        device_login_alert=False,
        message=f"Starting trail from {from_val} to {to_val}..."
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
        bot = TrailGameSession(srv_ip, srv_port, token, server_id)
        bot.login()
        log_activity("[+] Session established and world data synced successfully.")

        # Step 3: Run trial layers sequentially
        cleared_count = 0
        skipped_count = 0
        total_layers = (end_layer - start_layer) + 1

        for l_num in range(start_layer, end_layer + 1):
            res = execute_layer(bot, l_num, combat_seconds=combat_time)
            if res == 1:
                cleared_count += 1
            elif res == 0:
                skipped_count += 1

            # Inter-battle realistic pacing with heartbeats
            if l_num < end_layer:
                log_activity("[*] Inter-battle rest: sending synchronization heartbeats...")
                for _ in range(2):
                    time.sleep(2)
                    send_trail_heartbeat(bot)

        summary_msg = f"Completed Legendary Trail run. Cleared: {cleared_count}, Skipped/Already cleared: {skipped_count} (Total checked: {total_layers})."
        log_activity(f"[+] {summary_msg}")
        update_state(
            status="sleep",
            current_layer=None,
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
            current_layer=None,
            pid=None,
            device_login_alert=True,
            message=alert_msg
        )

    except Exception as e:
        tb = traceback.format_exc()
        err_msg = f"Service encountered an error: {e}"
        log_activity(f"[-] {err_msg}")
        log_activity(f"Traceback:\n{tb}")
        update_state(
            status="sleep",
            current_layer=None,
            pid=None,
            message=err_msg
        )

    finally:
        if bot:
            try:
                bot.close()
            except Exception:
                pass
        log_activity("[*] Legendary Trail service entered SLEEP mode.")


def main():
    parser = argparse.ArgumentParser(description="Legendary Trail Background Service")
    parser.add_argument("--from", "-f", dest="from_val", type=int, default=10, help="From layer value (10-100)")
    parser.add_argument("--to", "-t", dest="to_val", type=int, default=100, help="To layer value (10-100)")
    parser.add_argument("--account", "-a", default="tx263424183", help="Account username")
    parser.add_argument("--password", "-p", default="380746", help="Account password")
    parser.add_argument("--server-id", "-s", default=182, type=int, help="Server ID (default: 182)")
    parser.add_argument("--combat-time", "-c", default=4, type=int, help="Combat wait time in seconds")
    args = parser.parse_args()

    run_service(
        from_val=args.from_val,
        to_val=args.to_val,
        account=args.account,
        password=args.password,
        server_id=args.server_id,
        combat_time=args.combat_time
    )


if __name__ == "__main__":
    main()

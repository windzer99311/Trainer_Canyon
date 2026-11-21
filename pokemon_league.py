#!/usr/bin/env python3
"""
Pokemon Remake / Pocket Pet (com.pocketpet.pocpet)
Pokemon League Matchmaking & Dual-Socket Battle Bot (pokemon_league.py)

Architecture:
  - Connection #1 (World Server: 43.135.45.211:9505):
      Handles Gateway Auth, Login, League Handshake (Cmd 1261 -> Cmd 1241 -> Cmd 2004 -> Cmd 1911 -> Cmd 1901),
      and keeps the main game session online with continuous background heartbeats (Cmd 2004).
  - Connection #3 (Battle Room Server: 43.135.45.211:9861):
      Dedicated raw TCP socket (pure binary length framing, no HTTP).
      Spawns upon match encounter (Cmd 1902) to join room, spawn Pokémon, and execute battle rounds.
"""

import argparse
import os
import socket
import struct
import sys
import threading
import time

# Ensure UTF-8 output on Windows consoles
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Ensure imports resolve whether running from root or scripts/
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from login_account import (
    GameSession,
    gateway_login,
    xor_crypt,
)

# ==========================================
# PROTOCOL COMMAND IDS
# ==========================================
CMD_BATTLE_PING = 1000              # 0x03e8 - Battle Ping / Keep-Alive ('fr')
CMD_LEAGUE_WINDOW = 1261            # 0x04ed - League Window Query
CMD_LEAGUE_RECORDS = 1241           # 0x04d9 - League Ranking / Records
CMD_MATCH_INIT = 1911               # 0x0777 - Match Queue Init ('fr')
CMD_LEAGUE_CHALLENGE = 1901         # 0x076d - League Match Challenge Initiation
CMD_LEAGUE_MATCH_EVENT = 1902       # 0x076e - League Match Found / Opponent Ready
CMD_HEARTBEAT = 2004                # 0x07d4 - Heartbeat Keep-Alive
CMD_CITY_STATUE = 2014              # 0x07de - Scene Presence / Keep Synchronized
CMD_BATTLE_ROOM_JOIN = 10001        # 0x2711 - Battle Room Join / Handshake
CMD_BATTLE_SPAWN = 10011            # 0x271b - Battle Room Spawn Pokémon ('fr')
CMD_BATTLE_ACTION = 10012           # 0x271c - Battle Move Selection ('fs')

# ==========================================
# DEFAULT PAYLOAD DEFINITIONS
# ==========================================
PLAINTEXT_1911_INIT = b"fr"
PLAINTEXT_1901_LEAGUE = bytes.fromhex(
    "7c7b7decec84366291bf6061667ac2ec9a2b7e950866697bc8e38c2c71a10e607d7ce388e32b65c64b61667afcfe822c71fb2d607d7cf1fe992a65b251"
)

# Default Battle Room Handshake Key (53 bytes fallback)
DEFAULT_BATTLE_KEY = bytes.fromhex(
    "6441474400120811164d4c150814435955155e1158165341565f411002400d14414156165f4b2a2b50445d2d444c51425d45424053"
)

# 53-byte XOR Mask to derive the exact Room Join Key from decrypted Cmd 1902 payload
BATTLE_KEY_XOR_MASK = bytes(
    [51, 6, 20, 7, 15, 1, 27, 6, 20, 7, 15, 1, 27, 6, 20, 7, 15, 1, 27, 6, 20, 7, 15, 1] + [0] * 29
)


def derive_battle_key_from_1902(encounter_resp: bytes, session_token: str) -> bytes:
    """
    Extracts and decrypts the dynamic 53-byte Battle Room Key from Cmd 1902.
    Matches 100% byte-for-byte against PCAPdroid captures.
    Returns empty bytes b"" if Cmd 1902 is missing or incomplete.
    """
    cmd_marker = b"\x00\x00\x07\x6e"
    idx = encounter_resp.find(cmd_marker)
    if idx == -1:
        return b""

    enc_payload = encounter_resp[idx + 4 :]
    if len(enc_payload) < 73:
        return b""

    dec = xor_crypt(enc_payload, session_token)
    if len(dec) < 73:
        return b""

    raw_key = dec[20:73]
    return bytes(a ^ b for a, b in zip(raw_key, BATTLE_KEY_XOR_MASK))



class PokemonLeagueBot(GameSession):
    """
    Manages Connection #1 (World Server HTTP on port 9505) and Connection #3 (Battle Room Raw TCP on port 9861).
    """

    def __init__(
        self,
        host: str,
        port: int,
        gateway_token: bytes,
        server_id: int,
        account: str = "",
        password: str = "",
        battle_port: int = 9861,
        worker_id: int = 0,
    ):
        super().__init__(host, port, gateway_token, server_id)
        self.account = account
        self.password = password
        self.battle_port = battle_port
        self.worker_id = worker_id
        self.bg_heartbeat_active = False
        self.bg_thread = None
        self.battle_settled_event = threading.Event()

    def create_worker(self, worker_id: int):
        """Creates an independent worker instance reusing the authenticated session."""
        worker = PokemonLeagueBot(
            self.host,
            self.port,
            self.gateway_token,
            self.server_id,
            account=self.account,
            password=self.password,
            battle_port=self.battle_port,
            worker_id=worker_id,
        )
        worker.session_token_str = self.session_token_str
        worker.token_prefix = self.token_prefix
        return worker

    def init_league_window(self):
        """Initializes the League Window on the World Server once per session."""
        print("\n" + "=" * 65)
        print(" [SETUP] INITIALIZING LEAGUE WINDOW ON WORLD SERVER")
        print("=" * 65)
        if self.sock is None:
            self.connect()
        for _ in range(2):
            self.send_game_cmd(CMD_HEARTBEAT, b"", desc="Pre-Queue Sync")
            time.sleep(0.3)
        self.send_game_cmd(CMD_LEAGUE_WINDOW, b"", desc="League Window Query")
        time.sleep(0.3)
        self.send_game_cmd(CMD_LEAGUE_RECORDS, b"", desc="League Ranking / Records")
        time.sleep(0.3)
        self.send_game_cmd(CMD_HEARTBEAT, b"", desc="Pre-Queue Heartbeat")
        time.sleep(0.3)
        self.send_game_cmd(CMD_MATCH_INIT, PLAINTEXT_1911_INIT, desc="Match Queue Init ('fr')")
        time.sleep(0.5)
        self.close_world_socket()

    def close_world_socket(self):
        """Closes Connection #1 socket cleanly and resets to None for seamless reconnection."""
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def connect(self):
        """Establishes or re-establishes TCP socket connection to world server (Connection #1)."""
        self.close_world_socket()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(20.0)
        self.sock.connect((self.host, self.port))

    def login(self):
        super().login()
        # Activate City Scene Presence (Cmd 2014)
        try:
            self.send_http(self.token_prefix + struct.pack(">I", CMD_CITY_STATUE))
        except Exception:
            pass

    def close(self):
        """Stops background heartbeats and cleanly disconnects sockets."""
        self.stop_background_heartbeats()
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
            print("[*] World server connection disconnected.")

    def send_http(self, body: bytes) -> tuple[bytes, bytes]:
        """
        Sends an HTTP/1.1 POST packet with 100-continue expectation on Connection #1.
        """
        p = (
            b"POST / HTTP/1.1\r\n"
            b"Content-Type: application/x-www-form-urlencoded\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n"
            b"Expect: 100-continue\r\n"
            b"Connection: keep-alive\r\n"
            b"Host: " + f"{self.host}:{self.port}".encode() + b"\r\n\r\n"
        )

        for attempt in range(2):
            try:
                if self.sock is None:
                    self.connect()
                self.sock.sendall(p)
                self.sock.recv(1024)  # 100 Continue
                self.sock.sendall(body)
                break
            except Exception:
                if attempt == 0:
                    self.connect()
                else:
                    raise

        hdr = b""
        while b"\r\n\r\n" not in hdr:
            b1 = self.sock.recv(1)
            if not b1:
                break
            hdr += b1

        cl = 0
        for l in hdr.decode("ascii", errors="ignore").split("\r\n"):
            if l.lower().startswith("content-length:"):
                cl = int(l.split(":")[1].strip())
                break

        received = 0
        body_data = bytearray()
        while received < cl:
            chunk = self.sock.recv(min(16384, cl - received))
            if not chunk:
                break
            received += len(chunk)
            body_data.extend(chunk)

        if b"connection: close" in hdr.lower() or not hdr:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

        return hdr, bytes(body_data)

    def send_game_cmd(self, cmd_id: int, plaintext: bytes = b"", desc: str = "") -> tuple[int, bytes]:
        """
        Sends an authenticated game command via HTTP POST on Connection #1.
        """
        enc_payload = xor_crypt(plaintext, self.session_token_str) if plaintext else b""
        body = self.token_prefix + struct.pack(">I", cmd_id) + enc_payload

        curr_str = time.strftime("%H:%M:%S")
        w_tag = f"[W{self.worker_id}] " if self.worker_id > 0 else ""
        for attempt in range(2):
            try:
                if self.sock is None:
                    self.connect()
                _, resp = self.send_http(body)
                status = resp[4] if len(resp) >= 5 else 0
                tag = f" ({desc})" if desc else ""
                print(f"[{curr_str}] {w_tag}[Conn #1 :9505] 📤 Cmd {cmd_id:5d}{tag} | Status: {status} | Resp: {len(resp)} bytes", flush=True)
                return status, resp
            except Exception as e:
                if attempt == 0:
                    try:
                        self.connect()
                        continue
                    except Exception:
                        pass
                tag = f" ({desc})" if desc else ""
                print(f"[{curr_str}] {w_tag}[Conn #1 :9505] [!] Cmd {cmd_id:5d}{tag} error: {e}", flush=True)
                return -1, b""

    def start_background_heartbeats(self, interval: float = 1.0):
        """
        Runs continuous heartbeats on Connection #1 in a background thread
        so the main game session stays alive during the battle.
        Stops immediately when settlement payload (Cmd 101 / 0x0065) is encountered.
        """
        self.bg_heartbeat_active = True
        self.battle_settled_event.clear()

        def _worker():
            hb_num = 0
            while self.bg_heartbeat_active and not self.battle_settled_event.is_set():
                hb_num += 1
                try:
                    st, resp = self.send_game_cmd(CMD_HEARTBEAT, b"", desc=f"Bg-HB #{hb_num:02d}")
                    if b"\x00\x00\x00\x00\x65" in resp or (len(resp) >= 9 and resp[-5:] == b"\x00\x00\x00\x00\x65"):
                        curr_str = time.strftime("%H:%M:%S")
                        print(f"\n[{curr_str}] [🏆] BATTLE SETTLEMENT RECEIVED ON CONN #1! (Cmd 101 / 0x0065, {len(resp)} bytes)")
                        print(f"[{curr_str}] [*] Stopping Connection #1 heartbeats as instructed.")
                        self.battle_settled_event.set()
                        break
                except Exception:
                    pass
                time.sleep(interval)

        self.bg_thread = threading.Thread(target=_worker, daemon=True)
        self.bg_thread.start()
        print("[+] Background heartbeats on Connection #1 (:9505) started.")

    def stop_background_heartbeats(self):
        """Stops the background heartbeat worker."""
        if self.bg_heartbeat_active:
            self.bg_heartbeat_active = False
            if self.bg_thread and self.bg_thread.is_alive():
                self.bg_thread.join(timeout=1.5)
            print("[*] Background heartbeats on Connection #1 stopped.")

    def run_battle_socket_protocol(
        self,
        battle_key: bytes = DEFAULT_BATTLE_KEY,
        encounter_time: float = None,
        total_duration_sec: float = 62.0,
    ):
        """
        Executes Connection #3 on 43.135.45.211:9861 (Raw TCP Battle Protocol).
        Sends handshake, spawn, move action, and keeps sending Cmd 1000 pings ('fr')
        until exactly total_duration_sec (62.0s) has elapsed since the player encounter moment.
        """
        if encounter_time is None:
            encounter_time = time.time()
        w_tag = f"[W{self.worker_id}] " if self.worker_id > 0 else ""
        print("\n" + "=" * 65)
        print(f" {w_tag}[CONNECTION #3] CONNECTING TO BATTLE ROOM SERVER ({self.host}:{self.battle_port})")
        print("=" * 65)

        battle_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        battle_sock.settimeout(12.0)

        try:
            t0 = time.time()
            battle_sock.connect((self.host, self.battle_port))
            curr_str = time.strftime("%H:%M:%S")
            print(f"[{curr_str}] {w_tag}[Conn #3 :{self.battle_port}] [+] TCP Connected to Battle Room Server!")

            # ----------------------------------------------------
            # 1. Packet #1: Cmd 10001 (Room Join / Handshake, 57 B)
            # ----------------------------------------------------
            pkt1 = struct.pack(">I", len(battle_key) + 4) + struct.pack(">I", CMD_BATTLE_ROOM_JOIN) + battle_key
            curr_str = time.strftime("%H:%M:%S")
            print(f"[{curr_str}] {w_tag}[Conn #3 :{self.battle_port}] 📤 Sending Cmd 10001 (Room Handshake, {len(pkt1)} bytes)...")
            battle_sock.sendall(pkt1)

            # Receive Handshake ACK: 00 00 00 07 00 00 00 27 11 66 72 (11 bytes)
            resp1 = battle_sock.recv(1024)
            curr_str = time.strftime("%H:%M:%S")
            print(f"[{curr_str}] {w_tag}[Conn #3 :{self.battle_port}] 📥 Handshake ACK received: {len(resp1)} bytes (hex: {resp1.hex()})")

            # ----------------------------------------------------
            # 2. Packet #2: Cmd 10011 (Room Spawn Pokémon: 'fr', 10 B)
            # ----------------------------------------------------
            time.sleep(0.14)
            pkt2 = struct.pack(">I", 6) + struct.pack(">I", CMD_BATTLE_SPAWN) + b"fr"
            curr_str = time.strftime("%H:%M:%S")
            print(f"[{curr_str}] {w_tag}[Conn #3 :{self.battle_port}] 📤 Sending Cmd 10011 (Room Spawn 'fr', {len(pkt2)} bytes)...")
            battle_sock.sendall(pkt2)

            # Receive Pokémon & Move Data (~3.7 KB + 2.2 KB = ~5.9 KB)
            def recv_framed_packet(sock, timeout=4.0):
                orig_timeout = sock.gettimeout()
                sock.settimeout(timeout)
                try:
                    raw_len = sock.recv(4)
                    if len(raw_len) < 4:
                        return b""
                    expected_len = struct.unpack(">I", raw_len)[0]
                    buf = bytearray()
                    while len(buf) < expected_len:
                        chunk = sock.recv(min(8192, expected_len - len(buf)))
                        if not chunk:
                            break
                        buf.extend(chunk)
                    return bytes(buf)
                except (socket.timeout, OSError):
                    return b""
                finally:
                    sock.settimeout(orig_timeout)

            curr_str = time.strftime("%H:%M:%S")
            p1 = recv_framed_packet(battle_sock, timeout=3.0)
            print(f"[{curr_str}] {w_tag}[Conn #3 :{self.battle_port}] [+] Received Pokémon State chunk 1 ({len(p1)} bytes).")
            p2 = recv_framed_packet(battle_sock, timeout=0.8)
            if p2:
                curr_str = time.strftime("%H:%M:%S")
                print(f"[{curr_str}] {w_tag}[Conn #3 :{self.battle_port}] [+] Received Pokémon State chunk 2 ({len(p2)} bytes). Moves displayed!")

            # ----------------------------------------------------
            # 3. Packet #3: At ~2.7s - Cmd 1000 Ping ('fr')
            # ----------------------------------------------------
            time.sleep(2.4)
            pkt_ping = struct.pack(">I", 6) + struct.pack(">I", CMD_BATTLE_PING) + b"fr"
            curr_str = time.strftime("%H:%M:%S")
            print(f"[{curr_str}] {w_tag}[Conn #3 :{self.battle_port}] 📤 Sending Cmd 1000 (Battle Ping 'fr')...")
            battle_sock.sendall(pkt_ping)

            # ----------------------------------------------------
            # 4. Packet #4: At ~5.0s - Cmd 10012 Move Selected ('fs')
            # ----------------------------------------------------
            time.sleep(2.3)
            pkt4 = struct.pack(">I", 6) + struct.pack(">I", CMD_BATTLE_ACTION) + b"fs"
            curr_str = time.strftime("%H:%M:%S")
            print(f"[{curr_str}] {w_tag}[Conn #3 :{self.battle_port}] 📤 Sending Cmd 10012 (Move Selected 'fs')...")
            battle_sock.sendall(pkt4)

            # ----------------------------------------------------
            # 5. Continuous Battle Ping Loop (Cmd 1000 'fr')
            #    Keeps sending pings until exactly total_duration_sec (62s)
            #    has elapsed from the encounter moment. No other condition!
            # ----------------------------------------------------
            curr_str = time.strftime("%H:%M:%S")
            elapsed = time.time() - encounter_time
            remaining = max(0.0, total_duration_sec - elapsed)
            print(f"\n[{curr_str}] {w_tag}[Conn #3 :{self.battle_port}] 🔄 Entering battle ping loop (Cmd 1000 'fr')...")
            print(f"[{curr_str}] {w_tag}[Conn #3 :{self.battle_port}] ⏱️ Master Countdown: {elapsed:4.1f}s elapsed, {remaining:4.1f}s remaining until {total_duration_sec:.0f}s termination.")
            ping_num = 1

            while (time.time() - encounter_time) < total_duration_sec:
                time.sleep(1.8)
                ping_num += 1
                curr_str = time.strftime("%H:%M:%S")
                elapsed = time.time() - encounter_time
                remaining = max(0.0, total_duration_sec - elapsed)
                print(f"[{curr_str}] {w_tag}[Conn #3 :{self.battle_port}] 📤 Sending Cmd 1000 (Ping #{ping_num:02d} 'fr' | {elapsed:4.1f}s / {total_duration_sec:.0f}s, {remaining:4.1f}s left)...")
                try:
                    battle_sock.sendall(pkt_ping)
                except Exception as send_err:
                    print(f"[{curr_str}] {w_tag}[Conn #3 :{self.battle_port}] [!] Battle ping send error: {send_err}")
                    break

            curr_str = time.strftime("%H:%M:%S")
            print(f"\n[{curr_str}] {w_tag}[Conn #3 :{self.battle_port}] [*] {total_duration_sec:.0f}s master countdown reached! Terminating connection as instructed.")
            print(f"{w_tag}[🎉] Connection #3 Battle Protocol finished successfully (Total duration since encounter: {time.time() - encounter_time:.1f}s)!")

        except Exception as e:
            curr_str = time.strftime("%H:%M:%S")
            print(f"[{curr_str}] {w_tag}[Conn #3 :{self.battle_port}] [!] Battle room socket error: {e}")
        finally:
            try:
                battle_sock.close()
            except Exception:
                pass
            print(f"{w_tag}[*] Connection #3 socket (:{self.battle_port}) closed.")

    def spawn_background_battle(
        self,
        battle_key: bytes,
        encounter_time: float,
        match_duration: float = 60.0,
    ) -> threading.Thread:
        """
        Spawns Connection #3 (Battle Room on port 9861) in an independent background thread.
        Runs full 60s battle protocol while the main pipeline continues to the next match login.
        """
        w_tag = f"[M{self.worker_id}] " if self.worker_id > 0 else ""
        curr_str = time.strftime("%H:%M:%S")
        print(f"[{curr_str}] {w_tag}[*] Spawning Battle on Connection #3 in background ({match_duration:.0f}s countdown)...")

        t = threading.Thread(
            target=self.run_battle_socket_protocol,
            kwargs={
                "battle_key": battle_key,
                "encounter_time": encounter_time,
                "total_duration_sec": match_duration,
            },
            name=f"BattleThread-{self.worker_id}",
        )
        t.daemon = True
        t.start()
        return t

    def run_single_match(
        self,
        is_first_init: bool = False,
        timeout: float = 40.0,
        interval: float = 1.0,
        match_duration: float = 60.0,
        async_battle: bool = False,
    ):
        """
        Executes a single Pokemon League match attempt.

        is_first_init=True  (first-ever queue attempt in this session):
          Full handshake: Cmd 1261 -> Cmd 1241 -> Cmd 2004 (x2 Pre-Queue Sync) ->
                          Cmd 2004 (Pre-Queue HB) -> Cmd 1911 -> Cmd 1901
        is_first_init=False (all retries and subsequent matches after the first):
          Fast path: Cmd 1901 only (League window already open on server)

        After the queue initiation, polls Cmd 2004 heartbeats until:
          - Cmd 1902 encounter marker found -> starts battle -> returns True (or (True, thread) if async_battle=True)
          - Timeout without encounter -> returns False (or (False, None) if async_battle=True)
        """
        # Ensure Connection #1 is ready
        if self.sock is None:
            self.connect()

        w_tag = f"[M{self.worker_id}] " if self.worker_id > 0 else ""
        if is_first_init:
            # ------------------------------------------------------------------
            # FIRST INIT: Full league window setup (Match #1, Attempt 1 only)
            # ------------------------------------------------------------------

            # Drain any stale responses
            for _ in range(2):
                self.send_game_cmd(CMD_HEARTBEAT, b"", desc="Pre-Queue Sync")
                time.sleep(0.3)

            # 1. League Window Query (Cmd 1261 / 0x04ed)
            self.send_game_cmd(CMD_LEAGUE_WINDOW, b"", desc="League Window Query")
            time.sleep(0.3)

            # 2. League Records / Ranking (Cmd 1241 / 0x04d9)
            self.send_game_cmd(CMD_LEAGUE_RECORDS, b"", desc="League Ranking / Records")
            time.sleep(0.3)

            # 3. Pre-Queue Heartbeat (Cmd 2004 / 0x07d4)
            self.send_game_cmd(CMD_HEARTBEAT, b"", desc="Pre-Queue Heartbeat")
            time.sleep(0.3)

            # 4. Match Queue Init (Cmd 1911 / 0x0777 with 'fr')
            self.send_game_cmd(CMD_MATCH_INIT, PLAINTEXT_1911_INIT, desc="Match Queue Init ('fr')")
            time.sleep(0.5)

            # 5. League Challenge Initiation (Cmd 1901 / 0x076d with 61 B PLAINTEXT_1901_LEAGUE)
            self.send_game_cmd(CMD_LEAGUE_CHALLENGE, PLAINTEXT_1901_LEAGUE, desc="League Challenge Initiation")
            time.sleep(0.5)

        else:
            # ------------------------------------------------------------------
            # FAST PATH: League window already open — send Cmd 1901 only
            # ------------------------------------------------------------------
            curr_str = time.strftime("%H:%M:%S")
            print(f"[{curr_str}] {w_tag}[⚡] Fast queue restart: sending Cmd 1901 only (window already open).")
            self.send_game_cmd(CMD_LEAGUE_CHALLENGE, PLAINTEXT_1901_LEAGUE, desc="League Challenge Initiation")
            time.sleep(0.5)

        # 6. Poll heartbeats until match encounter
        start_time = time.time()
        hb_count = 0
        matched = False
        battle_key = b""
        encounter_time = None

        while (time.time() - start_time) < timeout:
            hb_count += 1
            elapsed = time.time() - start_time

            try:
                st, resp = self.send_game_cmd(CMD_HEARTBEAT, b"", desc=f"HB #{hb_count:02d} (+{elapsed:4.1f}s)")
                resp_len = len(resp)

                # STRICT: Must contain Cmd 1902 marker (0x0000076e) and derive a valid 53-byte key!
                if b"\x00\x00\x07\x6e" in resp:
                    derived = derive_battle_key_from_1902(resp, self.session_token_str)
                    if derived and len(derived) == 53:
                        encounter_time = time.time()
                        curr_str = time.strftime("%H:%M:%S")
                        print(f"\n[{curr_str}] {w_tag}[🎯] PLAYER ENCOUNTERED! (Cmd 1902 verified on HB #{hb_count}, {resp_len} bytes)")
                        matched = True
                        battle_key = derived
                        break
                    else:
                        curr_str = time.strftime("%H:%M:%S")
                        print(f"[{curr_str}] {w_tag}[!] Cmd 1902 marker found but key payload incomplete, continuing polling...")
            except Exception as e:
                curr_str = time.strftime("%H:%M:%S")
                print(f"[{curr_str}] {w_tag}[!] Heartbeat #{hb_count} notice: {e}")

            time.sleep(interval)

        if not matched:
            curr_str = time.strftime("%H:%M:%S")
            print(f"[{curr_str}] {w_tag}[⏱️] QUEUE TIMEOUT: No enemy found within {timeout:.0f}s.")
            return (False, None) if async_battle else False

        curr_str = time.strftime("%H:%M:%S")
        print(f"[{curr_str}] {w_tag}[+] Dynamic battle room key verified ({len(battle_key)} B, prefix: {battle_key[:8].hex()}).")

        # Player encountered: Immediately stop Connection #1 heartbeats and close Connection #1
        print(f"[{curr_str}] {w_tag}[*] Player encountered! Stopping Connection #1 completely (no more heartbeats).")
        self.close_world_socket()

        # If async_battle requested, spawn in background thread and return immediately!
        if async_battle:
            battle_thread = self.spawn_background_battle(
                battle_key=battle_key,
                encounter_time=encounter_time,
                match_duration=match_duration,
            )
            return True, battle_thread
        else:
            # Synchronous execution
            self.run_battle_socket_protocol(battle_key=battle_key, encounter_time=encounter_time, total_duration_sec=match_duration)
            curr_str = time.strftime("%H:%M:%S")
            print(f"\n[{curr_str}] {w_tag}[🎉] {match_duration:.0f}s COUNTDOWN COMPLETE: MATCH FINISHED!")
            return True

    def play_matches(
        self,
        total_matches: int = 1,
        max_retries: int = 3,
        timeout: float = 40.0,
        interval: float = 1.0,
        match_duration: float = 62.0,
    ) -> int:
        """
        Plays N valid matches using a single login session:
          - Re-starts matchmaking if no enemy is found (up to max_retries = 3 times)
          - Only increments the valid match count when a player is encountered and match finishes
          - Automatically proceeds to next match after the 62-second match timer finishes
        """
        print("\n" + "=" * 65)
        print(f" 🎮 STARTING POKEMON LEAGUE SESSION: TARGET {total_matches} VALID MATCH(ES)")
        print(f" • Matchmaking queue timeout:         {timeout:.0f}s")
        print(f" • Max queue retries per match:       {max_retries}")
        print(f" • Battle duration per match:         {match_duration:.0f}s")
        print("=" * 65)

        completed_matches = 0

        while completed_matches < total_matches:
            target_match_idx = completed_matches + 1
            print("\n" + "#" * 65)
            print(f" ⚔️ STARTING MATCH #{target_match_idx} OF {total_matches}")
            print("#" * 65)

            match_played = False
            retry_attempt = 0

            while retry_attempt < max_retries and not match_played:
                retry_attempt += 1
                curr_str = time.strftime("%H:%M:%S")
                print(f"\n[{curr_str}] [🔍] Match #{target_match_idx}/{total_matches} -> Queue Attempt {retry_attempt}/{max_retries}...")

                # First-ever init: Match #1 AND first queue attempt only
                is_first_init = (completed_matches == 0 and retry_attempt == 1)
                match_played = self.run_single_match(
                    is_first_init=is_first_init,
                    timeout=timeout,
                    interval=interval,
                    match_duration=match_duration,
                )

                if not match_played:
                    if retry_attempt < max_retries:
                        curr_str = time.strftime("%H:%M:%S")
                        print(f"[{curr_str}] [!] No enemy found. Retrying matchmaking in 2.0s ({retry_attempt}/{max_retries})...")
                        time.sleep(2.0)
                    else:
                        curr_str = time.strftime("%H:%M:%S")
                        print(f"\n[{curr_str}] [❌] No enemy found after {max_retries} queue attempts for Match #{target_match_idx}.")
                        print(f"[*] Skipping to next match slot. Completed {completed_matches}/{total_matches} valid match(es) so far.")
                        break  # Abandon this match slot; outer loop moves to next

            if match_played:
                completed_matches += 1
                curr_str = time.strftime("%H:%M:%S")
                print(f"\n[{curr_str}] [🏆] MATCH #{completed_matches}/{total_matches} OFFICIALLY LOGGED!")
                if completed_matches < total_matches:
                    print(f"[{curr_str}] ⏸️ Waiting 2.0s before initiating Match #{completed_matches + 1}...")
                    time.sleep(2.0)

        print("\n" + "=" * 65)
        print(f" [🎉] ALL {completed_matches}/{total_matches} REQUESTED MATCHES COMPLETED SUCCESSFULLY!")
        print("=" * 65)
        return completed_matches

    def run_league_sequence(self, timeout: float = 40.0, interval: float = 1.0, match_duration: float = 62.0):
        """Backward-compatible entrypoint to play a single match."""
        return self.play_matches(total_matches=1, max_retries=3, timeout=timeout, interval=interval, match_duration=match_duration)


def run_pipelined_session(
    account: str,
    password: str,
    server_id: int,
    total_matches: int = 10,
    max_retries: int = 3,
    timeout: float = 40.0,
    interval: float = 1.0,
    match_duration: float = 60.0,
    battle_port: int = 9861,
    inter_delay: float = 2.0,
) -> int:
    """
    Executes a pipelined multi-match session:
      For match 1 .. N:
        1. Login (Gateway + World)
        2. Match start (Cmd 1901)
        3. Player found (Cmd 1902)
        4. Spawn battle pings on Connection #3 in independent background thread (runs for 60s)
        5. Wait 2 seconds
        6. Proceed immediately to next match login & queue!
      Finally: Wait for all background battle pings to conclude before exiting.
    """
    print("\n" + "=" * 65)
    print(" 🏆 POKEMON REMAKE - PIPELINED MULTI-BATTLE BOT")
    print("=" * 65)
    print(f" • Target Account:      {account}")
    print(f" • Server ID:           {server_id}")
    print(f" • Target Matches:      {total_matches}")
    print(f" • Inter-Match Stagger: {inter_delay:.1f}s after each player encounter")
    print(f" • Battle Duration:     {match_duration:.0f}s (independent background threads)")
    print(f" • Queue Timeout:       {timeout:.0f}s (max {max_retries} retries per slot)")
    print("=" * 65)

    active_battle_threads = []
    completed_encounters = 0
    slot_idx = 0

    while completed_encounters < total_matches:
        slot_idx += 1
        current_match_num = completed_encounters + 1
        print("\n" + "#" * 65)
        print(f" ⚔️ MATCH #{current_match_num} OF {total_matches} (SLOT #{slot_idx})")
        print("#" * 65)

        # 1. Gateway Authentication (fresh login for this match)
        gw_token, s_ip, s_port = gateway_login(account, password, server_id)
        if not gw_token:
            print(f"[!] Gateway login failed for Match #{current_match_num}.")
            time.sleep(2.0)
            continue

        # 2. Connect to World Server
        bot = PokemonLeagueBot(
            s_ip,
            s_port,
            gw_token,
            server_id,
            account=account,
            password=password,
            battle_port=battle_port,
            worker_id=current_match_num,
        )
        try:
            bot.login()
        except Exception as e:
            print(f"[!] World login error for Match #{current_match_num}: {e}")
            bot.close()
            time.sleep(2.0)
            continue

        # 3. Match queue & encounter
        matched = False
        battle_thread = None

        for attempt in range(1, max_retries + 1):
            curr_str = time.strftime("%H:%M:%S")
            print(f"\n[{curr_str}] [M{current_match_num}] [🔍] Queue Attempt {attempt}/{max_retries}...")
            is_first = (attempt == 1)
            matched, battle_thread = bot.run_single_match(
                is_first_init=is_first,
                timeout=timeout,
                interval=interval,
                match_duration=match_duration,
                async_battle=True,
            )
            if matched:
                break
            if attempt < max_retries:
                time.sleep(2.0)

        if matched and battle_thread:
            completed_encounters += 1
            active_battle_threads.append(battle_thread)

            curr_str = time.strftime("%H:%M:%S")
            print(f"\n[{curr_str}] [M{current_match_num}] [🏆] PLAYER #{current_match_num} FOUND & BATTLE STARTED! ({completed_encounters}/{total_matches})")

            # 4. Wait 2 seconds before starting next match login
            if completed_encounters < total_matches:
                print(f"[{curr_str}] [M{current_match_num}] ⏸️ Player #{current_match_num} found! Waiting {inter_delay:.1f}s before initiating Login #{completed_encounters + 1}...")
                time.sleep(inter_delay)
        else:
            bot.close()
            curr_str = time.strftime("%H:%M:%S")
            print(f"\n[{curr_str}] [❌] Match slot #{slot_idx} timed out after {max_retries} attempts.")
            print(f"[*] Moving to next match attempt. Total completed so far: {completed_encounters}/{total_matches}.")
            time.sleep(2.0)

    # All N matches have been dispatched!
    curr_str = time.strftime("%H:%M:%S")
    print("\n" + "=" * 65)
    print(f" [{curr_str}] 🎯 ALL {completed_encounters}/{total_matches} MATCHES HAVE BEEN SPAWNED!")
    print(f" [*] Waiting for all active background battle pings to finish...")
    print("=" * 65)

    for i, t in enumerate(active_battle_threads, 1):
        if t.is_alive():
            t.join()

    print("\n" + "=" * 65)
    print(f" [🎉] ALL {completed_encounters}/{total_matches} BATTLES FINISHED SUCCESSFULLY!")
    print("=" * 65)
    return completed_encounters


def main():
    parser = argparse.ArgumentParser(description="Pokemon Remake - Dual-Socket Pokemon League Multi-Match Bot")
    parser.add_argument("--matches", "-n", default=10, type=int, help="Number of valid matches to play (default: 10)")
    parser.add_argument("--retries", "-r", default=3, type=int, help="Max matchmaking queue retries if no enemy found (default: 3)")
    parser.add_argument("--account", "-a", default="tx263424183", help="Account username (default: tx263424183)")
    parser.add_argument("--password", "-p", default="380746", help="Account password (default: 380746)")
    parser.add_argument("--server-id", "-s", default=182, type=int, help="Server ID (default: 182)")
    parser.add_argument("--timeout", "-t", default=40.0, type=float, help="Heartbeat polling timeout in seconds (default: 40.0)")
    parser.add_argument("--interval", "-i", default=1.0, type=float, help="Heartbeat interval in seconds (default: 1.0)")
    parser.add_argument("--battle-port", default=9861, type=int, help="Battle room server TCP port (default: 9861)")
    parser.add_argument("--match-duration", default=60.0, type=float, help="Overall countdown duration after encounter in seconds (default: 60.0)")
    parser.add_argument("--inter-delay", "-d", default=2.0, type=float, help="Delay in seconds after player found before next login (default: 2.0)")
    parser.add_argument("--mode", choices=["pipelined", "sequential"], default="pipelined", help="Execution mode (default: pipelined)")
    args = parser.parse_args()

    try:
        if args.mode == "pipelined":
            run_pipelined_session(
                account=args.account,
                password=args.password,
                server_id=args.server_id,
                total_matches=args.matches,
                max_retries=args.retries,
                timeout=args.timeout,
                interval=args.interval,
                match_duration=args.match_duration,
                battle_port=args.battle_port,
                inter_delay=args.inter_delay,
            )
        else:
            # Sequential single login mode
            gw_token, s_ip, s_port = gateway_login(args.account, args.password, args.server_id)
            if not gw_token:
                print("[!] Gateway login failed.")
                sys.exit(1)
            bot = PokemonLeagueBot(
                s_ip,
                s_port,
                gw_token,
                args.server_id,
                account=args.account,
                password=args.password,
                battle_port=args.battle_port,
            )
            try:
                bot.login()
                bot.play_matches(
                    total_matches=args.matches,
                    max_retries=args.retries,
                    timeout=args.timeout,
                    interval=args.interval,
                    match_duration=args.match_duration,
                )
            finally:
                bot.close()
    except KeyboardInterrupt:
        print("\n[*] Interrupted by user.")
    print("[*] Program finished.")


if __name__ == "__main__":
    main()

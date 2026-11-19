#!/usr/bin/env python3
"""
Pokemon Remake / Pocket Pet (com.pocketpet.pocpet)
Unified Authentication & Game Session Client (login_account.py)

Provides:
  - Gateway Authentication (gateway_login)
  - Protobuf Encoding/Decoding Utilities
  - Session XOR Crypto (xor_crypt)
  - Reusable Game Session (GameSession)
"""

import argparse
import socket
import struct
import sys
import time
import urllib.request

# Ensure UTF-8 output on Windows consoles
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ==========================================
# 1. GATEWAY & PROTOCOL CONFIGURATION
# ==========================================
APP_PLATFORM = "Saturn"
APP_SUB_PLATFORM = "pp2005"
APP_VERSION = "3.0.0"
GATEWAY_URL = "http://chongzhihw.saturngame.com.cn/home/Code"

DEFAULT_SYSINFO = (
    "deviceModel=vivo I2410&deviceName=I2410&deviceUI=4452806f27689742bf5df17dc33a3a8f"
    "&gpuID=0&gpuName=Mali-G615 MC2&gpuVID=0&gpuVer=OpenGL ES 3.2 v1.r44p1-01eac0.148b774f93332d7e562320793fb6c4c9"
    "&gpuMem=2048&gpuPFR=-1&gpuSL=46&cpuCount=8&sysMem=7442&OS=Android OS 16 / API-36 "
    "(BP2A.250605.031.A3_V000L1/compiler260910160833)&dpi=440&screenSize=1080x1071"
)
DEFAULT_DEVICE_ID = "08c5a4901c1c8c00"

# Protocol Command IDs
CMD_LOGIN_GAME = 1001       # 0x03e9 - LoginCS / LoginSC
CMD_LOAD_GAMEDATA = 1005    # 0x03ed - LoadGameDataCS


# ==========================================
# 2. CRYPTO & PROTOBUF UTILITIES
# ==========================================
def xor_crypt(data: bytes, session_token_ascii: str) -> bytes:
    """Dynamically encrypts/decrypts in-game payloads using the session token key."""
    key = session_token_ascii.encode("ascii")
    return bytes([b ^ key[i % len(key)] for i, b in enumerate(data)])


def encode_varint(v: int) -> bytes:
    out = bytearray()
    while v > 0x7F:
        out.append((v & 0x7F) | 0x80)
        v >>= 7
    out.append(v & 0x7F)
    return bytes(out)


def encode_string_field(field_num: int, val: str | bytes) -> bytes:
    b = val.encode("utf-8") if isinstance(val, str) else val
    tag = (field_num << 3) | 2
    return encode_varint(tag) + encode_varint(len(b)) + b


def encode_int_field(field_num: int, val: int) -> bytes:
    tag = (field_num << 3) | 0
    return encode_varint(tag) + encode_varint(val)


def decode_protobuf(data: bytes) -> dict:
    """Decodes basic varint and length-delimited protobuf fields."""
    fields = {}
    pos = 0
    length_data = len(data)
    while pos < length_data:
        tag_val = 0
        shift = 0
        while pos < length_data:
            b = data[pos]
            pos += 1
            tag_val |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
        field_num = tag_val >> 3
        wire_type = tag_val & 7

        if wire_type == 0:  # Varint
            val = 0
            shift = 0
            while pos < length_data:
                b = data[pos]
                pos += 1
                val |= (b & 0x7F) << shift
                if not (b & 0x80):
                    break
                shift += 7
            fields.setdefault(field_num, []).append(val)
        elif wire_type == 2:  # Length-delimited
            length = 0
            shift = 0
            while pos < length_data:
                b = data[pos]
                pos += 1
                length |= (b & 0x7F) << shift
                if not (b & 0x80):
                    break
                shift += 7
            val = data[pos : pos + length]
            pos += length
            fields.setdefault(field_num, []).append(val)
        else:
            break
    return fields


# ==========================================
# 3. GATEWAY AUTHENTICATION
# ==========================================
def gateway_login(account: str, password: str, server_id: int):
    """
    Authenticates with the game gateway and returns (gateway_token, srv_ip, srv_port).
    """
    print("\n" + "=" * 65)
    print(" [STEP 1] AUTHENTICATING WITH GATEWAY")
    print("=" * 65)
    print(f"[*] Account:     {account}")
    print(f"[*] Password:    {'*' * len(password)}")
    print(f"[*] Server ID:   {server_id}")

    ext_query = f"pt={APP_PLATFORM}&account={account}&password={password}&subPt={APP_SUB_PLATFORM}&uid=&token="

    proto = (
        encode_string_field(1, account)
        + encode_string_field(2, ext_query)
        + encode_string_field(3, password)
        + encode_string_field(4, APP_PLATFORM)
        + encode_string_field(6, DEFAULT_SYSINFO)
        + encode_string_field(7, APP_VERSION)
        + encode_string_field(8, APP_SUB_PLATFORM)
        + encode_string_field(10, "Android")
        + encode_string_field(14, DEFAULT_DEVICE_ID)
        + encode_string_field(15, DEFAULT_DEVICE_ID)
    )

    body = b"\x09123456789\x00\x00\x27\x12" + proto
    req = urllib.request.Request(
        GATEWAY_URL,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Expect": "100-continue",
            "Connection": "keep-alive",
            "Host": "chongzhihw.saturngame.com.cn",
            "User-Agent": "UnityPlayer/2022.3.20f1 (UnityWebRequest/1.0, libcurl/7.84.0-DEV)",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = resp.read()
    except Exception as e:
        print(f"[!] Gateway request failed: {e}")
        return None, None, None

    if len(raw) < 10:
        print("[!] Gateway response too short.")
        return None, None, None

    payload = raw[9:]
    pos = 1
    while payload[pos] & 0x80:
        pos += 1
    pos += 1

    if payload[pos] != 0x12:
        print("[!] Invalid Gateway response format.")
        return None, None, None
    pos += 1

    tok_len = 0
    shift = 0
    while True:
        b = payload[pos]
        pos += 1
        tok_len |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7

    gateway_token = payload[pos : pos + tok_len]

    # Resolve Server IP and Character
    srv_ip = "43.135.45.211"
    srv_port = 9505
    srv_tag = f"S{server_id}-".encode()
    srv_pos = raw.find(srv_tag)
    char_desc = ""
    if srv_pos != -1:
        url_idx = raw.find(b"http://", srv_pos)
        if url_idx != -1 and url_idx - srv_pos < 100:
            url_end = raw.find(b" ", url_idx)
            if url_end == -1:
                url_end = url_idx + 35
            srv_url = raw[url_idx:url_end].decode("utf-8", errors="ignore").strip()
            clean_url = srv_url.replace("http://", "")
            if ":" in clean_url:
                srv_ip, srv_port_str = clean_url.split(":", 1)
                srv_port = int(srv_port_str.split("/")[0])
        char_idx = raw.find(b"\x12\x07", srv_pos)
        if char_idx != -1 and char_idx - srv_pos < 120:
            char_desc = f" (Character: {raw[char_idx + 2 : char_idx + 9].decode('utf-8', errors='ignore')})"

    print(f"[+] Gateway Auth Token acquired: {len(gateway_token)} bytes")
    print(f"[*] Target Server: {srv_ip}:{srv_port} [S{server_id}{char_desc}]")
    return gateway_token, srv_ip, srv_port


# ==========================================
# 4. GAME SESSION MANAGER
# ==========================================
class GameSession:
    """
    Manages active TCP socket, binary HTTP framing, world server login, and encryption.
    """

    def __init__(self, host: str, port: int, gateway_token: bytes, server_id: int):
        self.host = host
        self.port = port
        self.gateway_token = gateway_token
        self.server_id = server_id
        self.sock = None
        self.session_token_str = None
        self.token_prefix = None

    def connect(self):
        """Establishes TCP socket connection to world server."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(20.0)
        self.sock.connect((self.host, self.port))

    def send_http(self, body: bytes) -> tuple[bytes, bytes]:
        """
        Sends an HTTP/1.1 POST packet with 100-continue expectation and returns (header, body).
        """
        p = (
            b"POST / HTTP/1.1\r\n"
            b"Content-Type: application/x-www-form-urlencoded\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n"
            b"Expect: 100-continue\r\n"
            b"Connection: keep-alive\r\n"
            b"Host: " + f"{self.host}:{self.port}".encode() + b"\r\n\r\n"
        )
        self.sock.sendall(p)
        self.sock.recv(1024)  # 100 Continue
        self.sock.sendall(body)

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

        return hdr, bytes(body_data)

    def login(self):
        """
        Logs into the World Server using Cmd 1001 (LoginCS) and initializes Cmd 1005 (LoadGameDataCS).
        Extracts and activates the dynamic session XOR token.
        """
        print("\n" + "=" * 65)
        print(" [STEP 2] LOGGING INTO WORLD SERVER")
        print("=" * 65)
        self.connect()

        login_cs_proto = encode_string_field(1, self.gateway_token) + encode_int_field(3, self.server_id)
        login_cs_body = b"\x09123456789\x00\x00\x03\xe9" + login_cs_proto

        hdr, sc_body = self.send_http(login_cs_body)
        pos_token = sc_body.find(b"\x12\x2c")
        if pos_token == -1:
            raise RuntimeError("Failed to obtain session token from LoginSC")

        self.session_token_str = sc_body[pos_token + 2 : pos_token + 2 + 44].decode("ascii")
        self.token_prefix = bytes([len(self.session_token_str)]) + self.session_token_str.encode("ascii")
        print(f"[+] Active Session Token: {self.session_token_str}")

        print("[*] Loading Character & World Data (Cmd 1005)...")
        _, gdata = self.send_http(self.token_prefix + b"\x00\x00\x03\xed\x17\x2a")
        print(f"[+] World data loaded ({len(gdata)} bytes).")

    def close(self):
        """Closes the socket cleanly."""
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            print("[*] Game session disconnected.")


# Backward compatibility alias
BattleBot = GameSession


def login_and_connect(account: str, password: str, server_id: int) -> GameSession | None:
    """
    Convenience helper that executes Gateway authentication and World Server login in one shot.
    """
    token, ip, port = gateway_login(account, password, server_id)
    if not token:
        return None
    session = GameSession(ip, port, token, server_id)
    session.login()
    return session


def main():
    parser = argparse.ArgumentParser(description="Pokemon Remake - Unified Account Login Client")
    parser.add_argument("--account", "-a", default="tx263424183", help="Account username (default: tx263424183)")
    parser.add_argument("--password", "-p", default="380746", help="Account password (default: 380746)")
    parser.add_argument("--server-id", "-s", default=182, type=int, help="Server ID (default: 182)")
    args = parser.parse_args()

    session = login_and_connect(args.account, args.password, args.server_id)
    if not session:
        print("[!] Login failed.")
        sys.exit(1)

    print("\n[+] Login verified successfully!")
    print(f"[*] Session Token: {session.session_token_str}")
    session.close()


if __name__ == "__main__":
    main()

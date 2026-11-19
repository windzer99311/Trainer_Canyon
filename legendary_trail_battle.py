#!/usr/bin/env python3
"""
Pokemon Remake / Pocket Pet (com.pocketpet.pocpet)
Legendary Trial (Mythical Animal Trial) Auto-Battle Bot
Interactive layer-by-layer challenge & victory runner
"""

import argparse
import struct
import sys
import time

# Ensure UTF-8 output on Windows consoles
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from login_account import GameSession, gateway_login, xor_crypt

# ==========================================
# PROTOCOL CONSTANTS
# ==========================================
CMD_HEARTBEAT = 1000       # 0x03e8 - Combat Heartbeat
CMD_TRIAL_INFO = 22008     # 0x55f8 - Trial Info & Status
CMD_TRIAL_START = 22010    # 0x55fa - Start Trial Battle
CMD_TRIAL_RESULT = 22011   # 0x55fb - Claim Victory & Rewards
CMD_TRIAL_EXIT = 22012     # 0x55fc - Advance / Return

# Universal universal responses across all layers
PLAINTEXT_HEARTBEAT = bytes.fromhex("6672")  # 2 bytes
PLAINTEXT_RESULT = bytes.fromhex("6673")     # 2 bytes (Victory Claim)
PLAINTEXT_EXIT = bytes.fromhex("6670")       # 2 bytes (Advance / Return)

# ==========================================
# LAYER START PAYLOAD REGISTRY
# ==========================================
# Layer 1 = Lvl 1-10, Layer 2 = Lvl 10-20, ... Layer 10 = Lvl 90-100
LAYER_PAYLOADS = {
    1: {
        "name": "Layer 1 (Lvl 1 - 10)",
        "payload": bytes.fromhex(
            "66b3c5b15163f6ff822c71c4f6892d64c7e2972a65c8ae893662d59bec2a7ececef93869677aedf9962b7eecbd736f7d69c4f6892d64baf86f687d7cc7e2972a65cf0e69667ac9bb9b2b7ed9346e697bce9df82d71f76b68667ac9cfec2a7ee970"
        ),
    },
    2: {
        "name": "Layer 2 (Lvl 10 - 20)",
        "payload": bytes.fromhex(
            "66b0c5b15163f6ff822c71c4f6892d64c7e2972a65c8dafe3762d39de32a7ed29af93869677aedf9962b7e91a5736f7c69c4f6892d64860e747a7dd2f08a3662a7147b7b66cecef93863d8776f7c69d587f02c64c165747a66d29af93863ce77"
        ),
    },
    3: {
        "name": "Layer 3 (Lvl 20 - 30)",
        "payload": bytes.fromhex(
            "66b1c5b15163f6ff822c71c4f6892d64c7e2972a65c8dafe3762d39de32a7ed29af93869677aedf9962b7e91a5736f7c69c4f6892d64860e747a7dd2f08a3662a7147b7b66cecef93863d8776f7c69d587f02c64c165747a66d29af93863ce77"
        ),
    },
    4: {
        "name": "Layer 4 (Lvl 30 - 40)",
        "payload": bytes.fromhex(
            "66b6c5b15163f6ff822c71c4f6892d64c7e2972a65c8dafe3762d39de32a7ed29af93869677aedf9962b7e91a5736f7c69c4f6892d64860e747a7dd2f08a3662a7147b7b66cecef93863d8776f7c69d587f02c64c165747a66d29af93863ce77"
        ),
    },
    5: {
        "name": "Layer 5 (Lvl 40 - 50)",
        "payload": bytes.fromhex(
            "66b7c5b15163f6ff822c71c4f6892d64c7e2972a65c8dafe3762d39de32a7ed29af93869677aedf9962b7e91a5736f7c69c4f6892d64860e747a7dd2f08a3662a7147b7b66cecef93863d8776f7c69d587f02c64c165747a66d29af93863ce77"
        ),
    },
    6: {
        "name": "Layer 6 (Lvl 50 - 60)",
        "payload": bytes.fromhex(
            "66b4c5b15163f6ff822c71c4f6892d64c7e2972a65c8dafe3762d39de32a7ed29af93869677aedf9962b7e91a5736f7c69c4f6892d64860e747a7dd2f08a3662a7147b7b66cecef93863d8776f7c69d587f02c64c165747a66d29af93863ce77"
        ),
    },
    7: {
        "name": "Layer 7 (Lvl 60 - 70)",
        "payload": bytes.fromhex(
            "66b5c5b15163f6ff822c71c4f6892d64c7e2972a65c8dafe3762d39de32a7ed29af93869677aedf9962b7e91a5736f7c69c4f6892d64860e747a7dd2f08a3662a7147b7b66cecef93863d8776f7c69d587f02c64c165747a66d29af93863ce77"
        ),
    },
    8: {
        "name": "Layer 8 (Lvl 70 - 80)",
        "payload": bytes.fromhex(
            "66bac5b15163f6ff822c71c4f6892d64c7e2972a65c8dafe3762d39de32a7ed29af93869677aedf9962b7e91a5736f7c69c4f6892d64860e747a7dd2f08a3662a7147b7b66cecef93863d8776f7c69d587f02c64c165747a66d29af93863ce77"
        ),
    },
    9: {
        "name": "Layer 9 (Lvl 80 - 90)",
        "payload": bytes.fromhex(
            "66bbc5b15163f6ff822c71c4f6892d64c7e2972a65c8dafe3762d39de32a7ed29af93869677aedf9962b7e91a5736f7c69c4f6892d64860e747a7dd2f08a3662a7147b7b66cecef93863d8776f7c69d587f02c64c165747a66d29af93863ce77"
        ),
    },
    10: {
        "name": "Layer 10 (Lvl 90 - 100)",
        "payload": bytes.fromhex(
            "66b8c5b15163f6ff822c71c4f6892d64c7e2972a65c8dafe3762d39de32a7ed29af93869677aedf9962b7e91a5736f7c69c4f6892d64860e747a7dd2f08a3662a7147b7b66cecef93863d8776f7c69d587f02c64c165747a66d29af93863ce77"
        ),
        # Layer 10 is the FINAL floor: server uses Cmd 22012 (EXIT) instead of
        # Cmd 22011 to claim the completion reward. Plaintext is still 6673.
        "final_layer": True,
    },
}


def run_trial_layer(bot: GameSession, layer_num: int, combat_seconds: int = 4) -> bool:
    layer_info = LAYER_PAYLOADS.get(layer_num)
    if not layer_info:
        print(f"[!] Invalid layer number {layer_num}. Must be 1 to 10.")
        return False

    payload = layer_info["payload"]
    if payload is None:
        print(f"\n[!] Layer {layer_num} ({layer_info['name']}) payload is NOT yet configured!")
        print("    Please capture and provide the Start Battle packet for this layer.")
        return False

    print("\n" + "=" * 65)
    print(f" [LEGENDARY TRIAL] INITIATING: {layer_info['name']}")
    print("=" * 65)

    # 1. Info / Status query (Cmd 22008)
    body_info = bot.token_prefix + struct.pack(">I", CMD_TRIAL_INFO)
    _, resp_info = bot.send_http(body_info)
    status_info = resp_info[4] if len(resp_info) >= 5 else -1
    print(f"[*] Trial Status initialized (code: {status_info})")

    # 2. Start Battle (Cmd 22010)
    print(f"[*] Sending Start Battle request for {layer_info['name']} (Cmd 22010)...")
    enc_start = xor_crypt(payload, bot.session_token_str)
    body_start = bot.token_prefix + struct.pack(">I", CMD_TRIAL_START) + enc_start
    _, resp_start = bot.send_http(body_start)
    status_start = resp_start[4] if len(resp_start) >= 5 else -1

    if status_start != 0:
        print(f"[!] BATTLE START REJECTED! Server status: {status_start}")
        print("    Possible causes: Already completed, floor locked, or daily attempts reached.")
        return False

    print(f"[+] BATTLE STARTED SUCCESSFULLY! Server state: {len(resp_start)} bytes.")

    # 3. Combat Heartbeat (Cmd 1000)
    print(f"[*] Simulating combat ({combat_seconds}s)...")
    start_t = time.time()
    hb = 0
    while time.time() - start_t < combat_seconds:
        time.sleep(2)
        hb += 1
        enc_hb = xor_crypt(PLAINTEXT_HEARTBEAT, bot.session_token_str)
        body_hb = bot.token_prefix + struct.pack(">I", CMD_HEARTBEAT) + enc_hb
        try:
            bot.send_http(body_hb)
            print(f"    In-Combat Heartbeat #{hb} ACK")
        except Exception:
            break

    # 4. Victory Claim (Cmd 22011) — universal for ALL layers including layer 10
    print("\n[*] Sending Victory Claim (Cmd 22011)...")
    enc_win = xor_crypt(PLAINTEXT_RESULT, bot.session_token_str)
    body_win = bot.token_prefix + struct.pack(">I", CMD_TRIAL_RESULT) + enc_win
    _, resp_win = bot.send_http(body_win)
    status_win = resp_win[4] if len(resp_win) >= 5 else -1
    if status_win != 0:
        print(f"[!] VICTORY CLAIM REJECTED! Server status: {status_win}")
        return False
    print(f"[+] [VICTORY] Server reward package: {len(resp_win)} bytes")

    is_final = layer_info.get("final_layer", False)

    if is_final:
        # 5. Layer 10 only: send Cmd 22012 with 6673 as ADDITIONAL final completion claim
        print("[*] Sending Final Completion Claim (Cmd 22012 — Layer 10 completion)...")
        enc_final = xor_crypt(PLAINTEXT_RESULT, bot.session_token_str)
        body_final = bot.token_prefix + struct.pack(">I", CMD_TRIAL_EXIT) + enc_final
        _, resp_final = bot.send_http(body_final)
        status_final = resp_final[4] if len(resp_final) >= 5 else -1
        if status_final != 0:
            print(f"[!] FINAL COMPLETION CLAIM REJECTED! Server status: {status_final}")
            return False
        print(f"[+] [COMPLETE] Final completion reward package: {len(resp_final)} bytes")
        print(f"[+] {layer_info['name']} FULLY COMPLETED & ALL REWARDS CLAIMED!")
    else:
        # 5. Normal layers: advance to next floor (Cmd 22012)
        print("[*] Advancing to next floor (Cmd 22012)...")
        enc_exit = xor_crypt(PLAINTEXT_EXIT, bot.session_token_str)
        body_exit = bot.token_prefix + struct.pack(">I", CMD_TRIAL_EXIT) + enc_exit
        bot.send_http(body_exit)
        print(f"[+] {layer_info['name']} COMPLETED & REWARDS CLAIMED!")
    return True


def main():
    parser = argparse.ArgumentParser(description="Pokemon Remake - Legendary Trial Auto Runner")
    parser.add_argument("--account", "-a", default="tx263424183", help="Account username")
    parser.add_argument("--password", "-p", default="380746", help="Account password")
    parser.add_argument("--server-id", "-s", default=182, type=int, help="Server ID (default: 182)")
    parser.add_argument("--combat-time", "-t", default=4, type=int, help="Combat wait time in seconds")
    parser.add_argument("--layer", "-l", default=None, type=int, help="Directly run layer (1-10) without prompt")
    args = parser.parse_args()

    print("=" * 65)
    print(" [*] POKEMON REMAKE - LEGENDARY TRIAL AUTO-BATTLE")
    print("=" * 65)

    # 1. Login
    token, srv_ip, srv_port = gateway_login(args.account, args.password, args.server_id)
    if not token:
        print("[!] Gateway login failed.")
        sys.exit(1)

    bot = GameSession(srv_ip, srv_port, token, args.server_id)
    try:
        bot.login()

        # If a specific layer was passed via CLI, run it and exit
        if args.layer is not None:
            run_trial_layer(bot, args.layer, combat_seconds=args.combat_time)
            return

        # Interactive Layer Selector Loop
        while True:
            print("\n" + "-" * 65)
            print(" Available Layers:")
            for l_idx in range(1, 11):
                status_str = "READY" if LAYER_PAYLOADS[l_idx]["payload"] else "PENDING PAYLOAD"
                print(f"   [{l_idx:2d}] {LAYER_PAYLOADS[l_idx]['name']:<25} [{status_str}]")
            print("   [ q] Quit program")
            print("-" * 65)

            try:
                choice = input("\n[?] Enter the layer number (1-10, or 'q' to quit): ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n[*] Exiting...")
                break

            if choice.lower() in ["q", "quit", "exit"]:
                print("[*] Goodbye!")
                break

            if not choice.isdigit():
                print("[!] Please enter a valid number between 1 and 10.")
                continue

            layer_sel = int(choice)
            if not (1 <= layer_sel <= 10):
                print("[!] Layer must be between 1 and 10.")
                continue

            success = run_trial_layer(bot, layer_sel, combat_seconds=args.combat_time)
            if success:
                print(f"\n[+] Successfully cleared Layer {layer_sel}!")
            time.sleep(1)

    finally:
        bot.close()


if __name__ == "__main__":
    main()

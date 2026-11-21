#!/usr/bin/env python3
"""
Pokemon Remake / Pocket Pet (com.pocketpet.pocpet)
Automated Elite Four Battle Bot (battle_bot.py)

Dedicated solely to Elite Four challenger battles:
  - Trainer 1: Fighting Bruno (0xce)
  - Trainer 2: Dragon Lance (0xb5)
  - Trainer 3: Extreme Challenger Windzer (0xb9)
  - Trainer 4: Alternate Day Extreme (0xba)

Uses login_account.py for authentication and session management.
"""

import argparse
import struct
import sys
import time

# Ensure UTF-8 output on Windows consoles
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from login_account import (
    GameSession,
    gateway_login,
    login_and_connect,
    xor_crypt,
)

# Command IDs
CMD_START_BATTLE = 1202        # 0x04b2 - Start Battle (Elite Four)
CMD_BATTLE_RESULT = 1203       # 0x04b3 - Claim Battle Victory & Rewards
CMD_RETURN_CITY = 2002         # 0x07d2 - Return to City Scene
CMD_HEARTBEAT_BATTLE = 1000    # 0x03e8 - In-Battle Heartbeat Keep-Alive

# Elite Four Challenger Payloads
# Trainer 1: Fighting Bruno (0xce)
PLAINTEXT_ELITE_S182_T1 = bytes.fromhex(
    "66ce93845569667ae298942b7eae736e697bf69e802c71d369687d7cec9e9b2a65f065"
)
PLAINTEXT_1203_T1 = bytes.fromhex("6674657479de725273")

# Trainer 2: Dragon Lance (0xb5)
PLAINTEXT_ELITE_S182_T2 = bytes.fromhex(
    "66b593845569667aa4ef9a2b7ef04a6e697bd7fc822c71ce76687d7cfacc972a65f97269667aacec982b7e8a5a687d7cf1e3992a65f94469667adddae12a7ec66e"
)
PLAINTEXT_1203_T2 = bytes.fromhex("6679657479dc4d527e")

# Trainer 3: Extreme Challenger Windzer (0xb9)
PLAINTEXT_ELITE_WINDZER = bytes.fromhex(
    "66b993845569677aedf9962b7eabbe757b7b66d4e48d3963ae126f7c69c4f6892d64860e747a7de6ed843662e6316f7c69ba9d892d648a26747a7dc8ae893662ba34"
)
PLAINTEXT_1203_WINDZER = bytes.fromhex("66746574798a515273")

# Trainer 4: Alternate Day Extreme (0xba)
PLAINTEXT_ELITE_ALT_1202 = bytes.fromhex(
    "66ba93845569677aedf9962b7e91be757b7b66d4e48d3963bc126f7c69c4f6892d64860e747a7de6ed843662e6316f7c69ba9d892d648a26747a7dc8ae893662ba34"
)
PLAINTEXT_1203_ALT = bytes.fromhex("66746574799b555273")

# In-Battle Heartbeat
PLAINTEXT_1000 = bytes.fromhex("6672")


class EliteBattleBot(GameSession):
    """
    Automates Elite Four battles and rewards claims on top of GameSession.
    """

    def run_battle(self, combat_seconds: int = 5, trainer: int = 1) -> bool:
        """Executes a single Elite Four battle against the specified trainer ID (1-4)."""
        trainer_names = {
            1: "Fighting Bruno (0xce)",
            2: "Dragon Lance (0xb5)",
            3: "Extreme Challenger Windzer (0xb9)",
            4: "Alternate Day Extreme (0xba)",
        }
        mode_name = f"Elite Four ({trainer_names.get(trainer, f'Trainer {trainer}')})"
        print("\n" + "=" * 65)
        print(f" [STEP 3] INITIATING BATTLE: {mode_name}")
        print("=" * 65)

        # 1. Select payload
        if trainer == 4:
            payload = PLAINTEXT_ELITE_ALT_1202
            win_payload = PLAINTEXT_1203_ALT
        elif trainer == 3:
            payload = PLAINTEXT_ELITE_WINDZER
            win_payload = PLAINTEXT_1203_WINDZER
        elif trainer == 2:
            payload = PLAINTEXT_ELITE_S182_T2
            win_payload = PLAINTEXT_1203_T2
        else:
            payload = PLAINTEXT_ELITE_S182_T1
            win_payload = PLAINTEXT_1203_T1

        # 2. Encrypt & Send Start Battle (Cmd 1202)
        enc_1202 = xor_crypt(payload, self.session_token_str)
        body_1202 = self.token_prefix + struct.pack(">I", CMD_START_BATTLE) + enc_1202
        print(f"[*] Sending Start Battle request ({mode_name})...")
        _, resp_1202 = self.send_http(body_1202)

        status_1202 = resp_1202[4] if len(resp_1202) >= 5 else -1
        if status_1202 != 0:
            print(f"[!] BATTLE START REJECTED! Server returned status code: {status_1202}")
            print("    Possible reasons: Daily challenge limit reached, insufficient stamina, or stage locked.")
            return False
        print(f"[+] BATTLE STARTED SUCCESSFULLY! Server state received ({len(resp_1202)} bytes).")

        # 3. Simulate combat with In-Battle Heartbeats (Cmd 1000)
        print(f"\n[*] Simulating combat ({combat_seconds}s)...")
        start = time.time()
        hb_count = 0
        while time.time() - start < combat_seconds:
            time.sleep(2)
            hb_count += 1
            enc_1000 = xor_crypt(PLAINTEXT_1000, self.session_token_str)
            body_1000 = self.token_prefix + struct.pack(">I", CMD_HEARTBEAT_BATTLE) + enc_1000
            try:
                _, resp_hb = self.send_http(body_1000)
                curr = time.strftime("%H:%M:%S")
                print(f"    [{curr}] In-Combat Heartbeat #{hb_count} ACK")
            except Exception:
                break

        # 4. Send Battle Result / Victory Claim (Cmd 1203)
        print("\n" + "=" * 65)
        print(" [STEP 4] CLAIMING VICTORY & REWARDS (Cmd 1203)")
        print("=" * 65)
        enc_1203 = xor_crypt(win_payload, self.session_token_str)
        body_1203 = self.token_prefix + struct.pack(">I", CMD_BATTLE_RESULT) + enc_1203
        _, resp_res = self.send_http(body_1203)

        status_1203 = resp_res[4] if len(resp_res) >= 5 else -1
        if status_1203 != 0:
            print(f"[!] VICTORY CLAIM REJECTED! Server status code: {status_1203}")
            return False

        print(f"[+] VICTORY VERIFIED! Server reward package: {len(resp_res)} bytes")

        # 5. Return to City Scene (Cmd 2002)
        print("[*] Returning to City Scene (Cmd 2002)...")
        body_2002 = self.token_prefix + struct.pack(">I", CMD_RETURN_CITY)
        self.send_http(body_2002)
        print("[+] Character back in main city.")

        print("\n" + "*" * 65)
        print(f" 🏆 {mode_name.upper()} BATTLE COMPLETED & REWARDS CLAIMED! 🏆")
        print("*" * 65)
        return True

    def run_elite_four_auto(self, max_battles: int = 3, combat_seconds: int = 5) -> int:
        """
        Automates Elite Four battles with smart fallback:
        Tries Trainer 4 -> Trainer 3 -> Trainer 2 -> Trainer 1.
        """
        print("\n" + "=" * 65)
        print(" [ELITE FOUR AUTO-CLEARIER] Checking Challenger Availability...")
        print("=" * 65)

        cleared_count = 0
        challengers = [
            (4, "Alternate Day Extreme (0xba)"),
            (3, "Extreme Challenger Windzer (0xb9)"),
            (2, "Dragon Lance (0xb5)"),
            (1, "Fighting Bruno (0xce)"),
        ]

        for trainer_id, name in challengers:
            if cleared_count >= max_battles:
                break

            print(f"\n[*] Probing availability for {name}...")
            while cleared_count < max_battles:
                print(f"\n>>> Attempting Battle against {name} (Victories claimed: {cleared_count}/{max_battles}) <<<")
                success = self.run_battle(combat_seconds=combat_seconds, trainer=trainer_id)
                if success:
                    cleared_count += 1
                    time.sleep(3)
                else:
                    print(f"[*] {name} is not available (limit reached or locked).")
                    break

        if cleared_count == 0:
            print("\n" + "!" * 65)
            print(" [!] All Elite Four challenges exhausted. Daily limit reached or locked!")
            print("!" * 65)
        else:
            print("\n" + "=" * 65)
            print(f" [✓] Elite Four complete: {cleared_count} victory/victories claimed!")
            print("=" * 65)

        return cleared_count


# Compatibility alias
BattleBot = EliteBattleBot


def main():
    parser = argparse.ArgumentParser(description="Pokemon Remake - Elite Four Automated Battle Bot")
    parser.add_argument("--account", "-a", default="tx263424183", help="Account name (default: tx263424183)")
    parser.add_argument("--password", "-p", default="380746", help="Account password (default: 380746)")
    parser.add_argument("--server-id", "-s", default=182, type=int, help="Server ID (default: 182)")
    parser.add_argument("--battles", "-n", default=3, type=int, help="Number of battles to run in sequence (default: 3)")
    parser.add_argument("--combat-time", "-t", default=5, type=int, help="Combat simulation seconds (default: 5)")
    parser.add_argument("--trainer", default=None, type=int, choices=[1, 2, 3, 4], help="Target specific trainer (1-4)")
    args = parser.parse_args()

    print("=" * 65)
    print(" ⚔️ POKEMON REMAKE - ELITE FOUR BATTLE BOT")
    print("=" * 65)

    token, srv_ip, srv_port = gateway_login(args.account, args.password, args.server_id)
    if not token:
        print("[!] Gateway login failed.")
        sys.exit(1)

    bot = EliteBattleBot(srv_ip, srv_port, token, args.server_id)
    try:
        bot.login()
        if args.trainer:
            for b in range(args.battles):
                ok = bot.run_battle(combat_seconds=args.combat_time, trainer=args.trainer)
                if not ok:
                    break
                if b + 1 < args.battles:
                    time.sleep(3)
        else:
            bot.run_elite_four_auto(max_battles=args.battles, combat_seconds=args.combat_time)
    finally:
        bot.close()


if __name__ == "__main__":
    main()

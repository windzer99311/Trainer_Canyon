#!/usr/bin/env python3
"""
Streamlit Dashboard for Pokemon Remake - Multi-Service Bot
Provides stateless control with persistent background execution for:
  1. Legendary Trail (Mythical Animal Trial)
  2. Elite Battle (Elite Four Auto-Battler - Daily 9:32 PM)
  3. Pokemon League (Matchmaking & Dual-Socket Battle - Daily 9:30 AM – 10:30 AM)
  4. Multi-Service Daily Automation Scheduler
"""

import datetime
import json
import os
import subprocess
import sys
import time
import zoneinfo
import psutil
import streamlit as st

# ==========================================
# TIMEZONE & REGIONAL CONFIGURATION
# ==========================================
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


# ==========================================
# CONFIGURATION & DYNAMIC PATHS
# ==========================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(SCRIPT_DIR).lower() == "scripts":
    PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
else:
    PROJECT_ROOT = SCRIPT_DIR

DATA_DIR = os.path.join(PROJECT_ROOT, "data")

SERVICE_CONFIGS = {
    "trail": {
        "title": "Legendary_trail",
        "name": "Legendary Trail",
        "script_candidates": [
            os.path.join(PROJECT_ROOT, "scripts", "legendary_trail_service.py"),
            os.path.join(PROJECT_ROOT, "legendary_trail_service.py"),
        ],
        "state_file": os.path.join(DATA_DIR, "trail_state.json"),
        "log_file": os.path.join(DATA_DIR, "trail_activity.log"),
        "process_pattern": "legendary_trail_service",
    },
    "elite": {
        "title": "Elite_battle",
        "name": "Elite Battle",
        "script_candidates": [
            os.path.join(PROJECT_ROOT, "scripts", "elite_battle_service.py"),
            os.path.join(PROJECT_ROOT, "elite_battle_service.py"),
        ],
        "state_file": os.path.join(DATA_DIR, "elite_state.json"),
        "log_file": os.path.join(DATA_DIR, "elite_activity.log"),
        "process_pattern": "elite_battle_service",
    },
    "league": {
        "title": "Pokemon_league",
        "name": "Pokemon League",
        "script_candidates": [
            os.path.join(PROJECT_ROOT, "scripts", "pokemon_league_service.py"),
            os.path.join(PROJECT_ROOT, "pokemon_league_service.py"),
        ],
        "state_file": os.path.join(DATA_DIR, "league_state.json"),
        "log_file": os.path.join(DATA_DIR, "league_activity.log"),
        "process_pattern": "pokemon_league_service",
    },
    "scheduler_league": {
        "title": "League_Scheduler",
        "name": "Pokemon League Auto-Pilot",
        "script_candidates": [
            os.path.join(PROJECT_ROOT, "scripts", "scheduler_service.py"),
            os.path.join(PROJECT_ROOT, "scheduler_service.py"),
        ],
        "state_file": os.path.join(DATA_DIR, "scheduler_league_state.json"),
        "log_file": os.path.join(DATA_DIR, "scheduler_league.log"),
        "process_pattern": "scheduler_service",
        "service_arg": "league",
    },
    "scheduler_elite": {
        "title": "Elite_Scheduler",
        "name": "Elite Battle Scheduler",
        "script_candidates": [
            os.path.join(PROJECT_ROOT, "scripts", "scheduler_service.py"),
            os.path.join(PROJECT_ROOT, "scheduler_service.py"),
        ],
        "state_file": os.path.join(DATA_DIR, "scheduler_elite_state.json"),
        "log_file": os.path.join(DATA_DIR, "scheduler_elite.log"),
        "process_pattern": "scheduler_service",
        "service_arg": "elite",
    },
    "scheduler": {
        "title": "Daily_Scheduler",
        "name": "Daily Schedulers",
        "script_candidates": [
            os.path.join(PROJECT_ROOT, "scripts", "scheduler_service.py"),
            os.path.join(PROJECT_ROOT, "scheduler_service.py"),
        ],
        "state_file": os.path.join(DATA_DIR, "scheduler_state.json"),
        "log_file": os.path.join(DATA_DIR, "scheduler.log"),
        "process_pattern": "scheduler_service",
        "service_arg": "all",
    },
}

LAYER_OPTIONS = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
ELITE_BATTLE_OPTIONS = [1, 2, 3, 4]
LEAGUE_MATCH_OPTIONS = [5, 10, 15, 20]

st.set_page_config(
    page_title="REA Bot Services",
    page_icon="⚡",
    layout="centered"
)


# ==========================================
# STATE & PROCESS MANAGEMENT
# ==========================================
def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def resolve_script_path(service_key: str) -> str:
    cfg = SERVICE_CONFIGS[service_key]
    for candidate in cfg["script_candidates"]:
        if os.path.exists(candidate):
            return candidate
    return cfg["script_candidates"][0]


def is_service_alive(pid: int, pattern: str, required_arg: str | None = None) -> bool:
    if not pid:
        return False
    try:
        p = psutil.Process(pid)
        if not p.is_running():
            return False
        cmd = " ".join(p.cmdline()).lower()
        if "python" in p.name().lower() and pattern.lower() in cmd:
            if required_arg and required_arg.lower() not in cmd:
                return False
            return True
        return False
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False


def load_service_state(service_key: str) -> dict:
    ensure_data_dir()
    cfg = SERVICE_CONFIGS[service_key]
    state_file = cfg["state_file"]
    if os.path.exists(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state = json.load(f)
                pid = state.get("pid")
                if state.get("status") == "running" and pid:
                    # Verify if the process is actually running our service
                    req_arg = cfg.get("service_arg")
                    if not is_service_alive(pid, cfg["process_pattern"], req_arg):
                        state["status"] = "sleep"
                        state["pid"] = None
                        save_service_state(service_key, state)
                return state
        except Exception:
            pass

    default_state = {
        "status": "sleep",
        "service_name": service_key,
        "pid": None,
        "start_time": None,
        "updated_time": None,
        "device_login_alert": False,
        "message": "Service is idle (sleep)."
    }
    if service_key == "trail":
        default_state.update({"from_layer": 10, "to_layer": 100, "current_layer": None})
    elif service_key == "elite":
        default_state.update({"target_battles": 3, "cleared_battles": 0, "current_trainer": None})
    elif service_key == "league":
        default_state.update({"target_matches": 10, "completed_matches": 0, "queue_attempts": 0, "cutoff_time": "10:30"})
    elif service_key == "scheduler_league":
        next_dt = compute_next_run("09:30")
        default_state.update({
            "service": "league",
            "name": "Pokemon League Daily Auto-Pilot",
            "from_time": "09:30",
            "to_time": "10:30",
            "target_matches": 10,
            "next_run": format_ist_timestamp(next_dt),
            "last_run": None,
            "message": "League Auto-Pilot is idle (sleep)."
        })
    elif service_key == "scheduler_elite":
        next_dt = compute_next_run("21:32")
        default_state.update({
            "service": "elite",
            "name": "Elite Battle Daily Scheduler",
            "trigger_time": "21:32",
            "target_battles": 3,
            "next_run": format_ist_timestamp(next_dt),
            "last_run": None,
            "message": "Elite Battle scheduler is idle (sleep)."
        })
    elif service_key == "scheduler":
        default_state.update({"schedules": {}})
    return default_state


def save_service_state(service_key: str, state: dict):
    ensure_data_dir()
    state["updated_time"] = format_ist_timestamp()
    state_file = SERVICE_CONFIGS[service_key]["state_file"]
    temp_file = state_file + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(temp_file, state_file)


def read_service_logs(service_key: str, max_lines: int = 35) -> str:
    log_file = SERVICE_CONFIGS[service_key]["log_file"]
    if not os.path.exists(log_file):
        return "No activity logged yet."
    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            return "".join(lines[-max_lines:])
    except Exception as e:
        return f"Error reading logs: {e}"


def stop_service_process(pid: int):
    try:
        p = psutil.Process(pid)
        for child in p.children(recursive=True):
            child.terminate()
        p.terminate()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass


def compute_next_run(target_time_str: str) -> datetime.datetime:
    parts = target_time_str.strip().split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0

    now = get_now_ist()
    target_today = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if now >= target_today:
        return target_today + datetime.timedelta(days=1)
    else:
        return target_today


def format_countdown(next_run_dt: datetime.datetime) -> str:
    now = get_now_ist()
    diff_sec = (next_run_dt - now).total_seconds()
    if diff_sec <= 0:
        return "due now"
    h = int(diff_sec // 3600)
    m = int((diff_sec % 3600) // 60)
    s = int(diff_sec % 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    return f"{m}m {s}s"


# ==========================================
# SIDEBAR NAVIGATION & REAL-TIME STATUS
# ==========================================
trail_state = load_service_state("trail")
elite_state = load_service_state("elite")
league_state = load_service_state("league")
sched_league_state = load_service_state("scheduler_league")
sched_elite_state = load_service_state("scheduler_elite")

trail_running = (trail_state.get("status") == "running")
elite_running = (elite_state.get("status") == "running")
league_running = (league_state.get("status") == "running")
sched_league_running = (sched_league_state.get("status") == "running")
sched_elite_running = (sched_elite_state.get("status") == "running")

st.sidebar.title("⚡ Game Bot Services")
selected_service_name = st.sidebar.radio(
    "Choose Service:",
    ["Legendary Trail", "Elite Battle", "Pokemon League", "Daily Schedulers"],
    index=3
)

st.sidebar.markdown("---")
st.sidebar.markdown("### Manual Services")
st.sidebar.markdown(f"**Legendary Trail:** {'🟢 running' if trail_running else '⚪ sleep'}")
st.sidebar.markdown(f"**Elite Battle:** {'🟢 running' if elite_running else '⚪ sleep'}")
st.sidebar.markdown(f"**Pokemon League:** {'🟢 running' if league_running else '⚪ sleep'}")
st.sidebar.markdown("---")
st.sidebar.markdown("### Daily Schedulers")
st.sidebar.markdown(f"**🏆 League Auto-Pilot:** {'🟢 running' if sched_league_running else '⚪ sleep'}")
st.sidebar.markdown(f"**🛡️ Elite Scheduler:** {'🟢 running' if sched_elite_running else '⚪ sleep'}")

now_ist = get_now_ist()
st.sidebar.markdown("---")
st.sidebar.caption(f"🕒 **Current Local Time:**\n{now_ist.strftime('%I:%M:%S %p')} IST (UTC+5:30)")

# Current selected state
if selected_service_name == "Legendary Trail":
    current_service_key = "trail"
elif selected_service_name == "Elite Battle":
    current_service_key = "elite"
elif selected_service_name == "Pokemon League":
    current_service_key = "league"
else:
    current_service_key = "scheduler"

current_state = load_service_state(current_service_key)
is_running = (current_state.get("status") == "running")


# ==========================================
# SERVICE UI: 1. LEGENDARY TRAIL
# ==========================================
if current_service_key == "trail":
    st.title("Legendary_trail")

    # Status Display
    if is_running:
        curr_layer = current_state.get("current_layer")
        layer_txt = f" (Floor: Layer {curr_layer})" if curr_layer else ""
        st.markdown(
            f"""
            <div style="background-color:#0e2a18; border:2px solid #28a745; border-radius:8px; padding:12px; margin-bottom:15px;">
                <h3 style="color:#28a745; margin:0; display:flex; align-items:center;">
                    <span style="display:inline-block; width:12px; height:12px; background-color:#28a745; border-radius:50%; margin-right:10px;"></span>
                    Status: running {layer_txt}
                </h3>
                <p style="color:#a5d6a7; margin:5px 0 0 22px; font-size:14px;">PID: {current_state.get('pid')} | Started: {current_state.get('start_time')}</p>
            </div>
            """,
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            """
            <div style="background-color:#1c2024; border:1px solid #495057; border-radius:8px; padding:12px; margin-bottom:15px;">
                <h3 style="color:#ced4da; margin:0; display:flex; align-items:center;">
                    <span style="display:inline-block; width:12px; height:12px; background-color:#6c757d; border-radius:50%; margin-right:10px;"></span>
                    Status: sleep
                </h3>
                <p style="color:#adb5bd; margin:5px 0 0 22px; font-size:14px;">Service is idle and ready.</p>
            </div>
            """,
            unsafe_allow_html=True
        )

    # Device Login Alert Banner
    if current_state.get("device_login_alert"):
        st.error(
            "🚨 **DEVICE LOGIN DETECTED**: You logged into the game from your mobile device! "
            "The service was automatically stopped and put into **sleep** mode to avoid session conflict. "
            "Click **Start Trail** whenever you are ready to resume."
        )

    # From & To Dropdowns
    col_from, col_to = st.columns(2)
    with col_from:
        default_from_idx = LAYER_OPTIONS.index(current_state.get("from_layer", 10)) if current_state.get("from_layer") in LAYER_OPTIONS else 0
        from_selection = st.selectbox("From:", options=LAYER_OPTIONS, index=default_from_idx, disabled=is_running)

    with col_to:
        default_to_idx = LAYER_OPTIONS.index(current_state.get("to_layer", 100)) if current_state.get("to_layer") in LAYER_OPTIONS else len(LAYER_OPTIONS) - 1
        to_selection = st.selectbox("To:", options=LAYER_OPTIONS, index=default_to_idx, disabled=is_running)

    # Start / Stop Buttons
    col_btn1, col_btn2 = st.columns([2, 1])

    with col_btn1:
        if st.button("Start Trail", type="primary", use_container_width=True, disabled=is_running):
            if is_running:
                st.warning("Trail is already running!")
            else:
                ensure_data_dir()
                sub_env = os.environ.copy()
                sub_env["PYTHONIOENCODING"] = "utf-8"
                sub_env["PYTHONUTF8"] = "1"
                sub_env["PYTHONUNBUFFERED"] = "1"

                log_file = SERVICE_CONFIGS["trail"]["log_file"]
                log_handle = open(log_file, "a", encoding="utf-8", errors="replace")

                creation_flags = 0
                if sys.platform == "win32":
                    creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

                script_path = resolve_script_path("trail")
                cmd = [
                    sys.executable,
                    script_path,
                    "--from", str(from_selection),
                    "--to", str(to_selection)
                ]

                proc = subprocess.Popen(
                    cmd,
                    stdout=log_handle,
                    stderr=log_handle,
                    stdin=subprocess.DEVNULL,
                    creationflags=creation_flags,
                    env=sub_env
                )
                log_handle.close()

                current_state["status"] = "running"
                current_state["pid"] = proc.pid
                current_state["from_layer"] = from_selection
                current_state["to_layer"] = to_selection
                current_state["current_layer"] = from_selection
                current_state["start_time"] = format_ist_timestamp()
                current_state["device_login_alert"] = False
                current_state["message"] = f"Started trail from {from_selection} to {to_selection}."
                save_service_state("trail", current_state)
                st.rerun()

    with col_btn2:
        if st.button("Stop Trail", type="secondary", use_container_width=True, disabled=not is_running):
            if is_running and current_state.get("pid"):
                stop_service_process(current_state["pid"])
                current_state["status"] = "sleep"
                current_state["pid"] = None
                current_state["message"] = "Service stopped manually by user."
                save_service_state("trail", current_state)
                st.rerun()

    st.markdown("---")
    st.markdown("#### Live Activity Logs")
    st.code(read_service_logs("trail", max_lines=35), language="text")


# ==========================================
# SERVICE UI: 2. ELITE BATTLE
# ==========================================
elif current_service_key == "elite":
    st.title("Elite_battle")

    # Status Display
    if is_running:
        cleared_b = current_state.get("cleared_battles", 0)
        target_b = current_state.get("target_battles", 3)
        curr_t = current_state.get("current_trainer")
        trainer_txt = f" | {curr_t}" if curr_t else ""
        st.markdown(
            f"""
            <div style="background-color:#0e2a18; border:2px solid #28a745; border-radius:8px; padding:12px; margin-bottom:15px;">
                <h3 style="color:#28a745; margin:0; display:flex; align-items:center;">
                    <span style="display:inline-block; width:12px; height:12px; background-color:#28a745; border-radius:50%; margin-right:10px;"></span>
                    Status: running (Cleared: {cleared_b}/{target_b}{trainer_txt})
                </h3>
                <p style="color:#a5d6a7; margin:5px 0 0 22px; font-size:14px;">PID: {current_state.get('pid')} | Started: {current_state.get('start_time')}</p>
            </div>
            """,
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            """
            <div style="background-color:#1c2024; border:1px solid #495057; border-radius:8px; padding:12px; margin-bottom:15px;">
                <h3 style="color:#ced4da; margin:0; display:flex; align-items:center;">
                    <span style="display:inline-block; width:12px; height:12px; background-color:#6c757d; border-radius:50%; margin-right:10px;"></span>
                    Status: sleep
                </h3>
                <p style="color:#adb5bd; margin:5px 0 0 22px; font-size:14px;">Service is idle and ready.</p>
            </div>
            """,
            unsafe_allow_html=True
        )

    # Device Login Alert Banner
    if current_state.get("device_login_alert"):
        st.error(
            "🚨 **DEVICE LOGIN DETECTED**: You logged into the game from your mobile device! "
            "Elite Battle was automatically stopped and put into **sleep** mode to avoid session conflict. "
            "Click **Start Battle** whenever you are ready to resume."
        )

    # Scheduled 9:32 PM Card
    next_sched_dt = compute_next_run("21:32")
    countdown_str = format_countdown(next_sched_dt)
    sched_status_icon = "🟢 Active" if scheduler_running else "⚪ Idle"

    st.markdown(
        f"""
        <div style="background-color:#161d2b; border:1px solid #3b82f6; border-radius:8px; padding:14px; margin-bottom:16px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div>
                    <h4 style="color:#60a5fa; margin:0 0 4px 0;">⏰ Daily 9:32 PM Auto-Scheduler</h4>
                    <p style="color:#bfdbfe; margin:0; font-size:14px;">
                        Fires 3 Elite Battles automatically every day at <b>9:32 PM IST</b> (21:32).
                    </p>
                    <p style="color:#93c5fd; margin:4px 0 0 0; font-size:13px;">
                        Status: <b>{sched_status_icon}</b> | Next Trigger: <b>{next_sched_dt.strftime('%b %d, %I:%M %p')} IST</b> (in {countdown_str})
                    </p>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    # Battles Selector (Default: 3, choices: 1, 2, 3, 4)
    col_opt1, col_opt2 = st.columns(2)
    with col_opt1:
        target_val = current_state.get("target_battles", 3)
        default_b_idx = ELITE_BATTLE_OPTIONS.index(target_val) if target_val in ELITE_BATTLE_OPTIONS else 2
        battle_selection = st.selectbox(
            "Number of Battles:",
            options=ELITE_BATTLE_OPTIONS,
            index=default_b_idx,
            disabled=is_running
        )

    with col_opt2:
        trainer_choice_map = {
            "Auto (Fallback: 4 -> 3 -> 2 -> 1)": None,
            "Trainer 1: Bruno (Fighting)": 1,
            "Trainer 2: Lance (Dragon)": 2,
            "Trainer 3: Windzer (Extreme)": 3,
            "Trainer 4: Alternate Day Extreme": 4,
        }
        trainer_selection = st.selectbox(
            "Target Challenger:",
            options=list(trainer_choice_map.keys()),
            index=0,
            disabled=is_running
        )

    # Start / Stop Buttons
    col_btn1, col_btn2 = st.columns([2, 1])

    with col_btn1:
        if st.button("Start Battle (Manual)", type="primary", use_container_width=True, disabled=is_running):
            if is_running:
                st.warning("Elite Battle is already running!")
            else:
                ensure_data_dir()
                sub_env = os.environ.copy()
                sub_env["PYTHONIOENCODING"] = "utf-8"
                sub_env["PYTHONUTF8"] = "1"
                sub_env["PYTHONUNBUFFERED"] = "1"

                log_file = SERVICE_CONFIGS["elite"]["log_file"]
                log_handle = open(log_file, "a", encoding="utf-8", errors="replace")

                creation_flags = 0
                if sys.platform == "win32":
                    creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

                script_path = resolve_script_path("elite")
                cmd = [
                    sys.executable,
                    script_path,
                    "--battles", str(battle_selection)
                ]
                selected_trainer_id = trainer_choice_map.get(trainer_selection)
                if selected_trainer_id is not None:
                    cmd.extend(["--trainer", str(selected_trainer_id)])

                proc = subprocess.Popen(
                    cmd,
                    stdout=log_handle,
                    stderr=log_handle,
                    stdin=subprocess.DEVNULL,
                    creationflags=creation_flags,
                    env=sub_env
                )
                log_handle.close()

                current_state["status"] = "running"
                current_state["pid"] = proc.pid
                current_state["target_battles"] = battle_selection
                current_state["cleared_battles"] = 0
                current_state["start_time"] = format_ist_timestamp()
                current_state["device_login_alert"] = False
                current_state["message"] = f"Started Elite Battle ({battle_selection} battles)..."
                save_service_state("elite", current_state)
                st.rerun()

    with col_btn2:
        if st.button("Stop Battle", type="secondary", use_container_width=True, disabled=not is_running):
            if is_running and current_state.get("pid"):
                stop_service_process(current_state["pid"])
                current_state["status"] = "sleep"
                current_state["pid"] = None
                current_state["message"] = "Service stopped manually by user."
                save_service_state("elite", current_state)
                st.rerun()

    st.markdown("---")
    st.markdown("#### Live Activity Logs")
    st.code(read_service_logs("elite", max_lines=35), language="text")


# ==========================================
# SERVICE UI: 3. POKEMON LEAGUE
# ==========================================
elif current_service_key == "league":
    st.title("Pokemon_league")

    # Status Display
    if is_running:
        cleared_m = current_state.get("completed_matches", 0)
        target_m = current_state.get("target_matches", 10)
        q_attempts = current_state.get("queue_attempts", 0)
        cutoff_val = current_state.get("cutoff_time", "10:30")
        st.markdown(
            f"""
            <div style="background-color:#0e2a18; border:2px solid #28a745; border-radius:8px; padding:12px; margin-bottom:15px;">
                <h3 style="color:#28a745; margin:0; display:flex; align-items:center;">
                    <span style="display:inline-block; width:12px; height:12px; background-color:#28a745; border-radius:50%; margin-right:10px;"></span>
                    Status: running (Matches: {cleared_m}/{target_m} | Queues: {q_attempts})
                </h3>
                <p style="color:#a5d6a7; margin:5px 0 0 22px; font-size:14px;">PID: {current_state.get('pid')} | Started: {current_state.get('start_time')} | Cutoff: {cutoff_val} IST</p>
            </div>
            """,
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            """
            <div style="background-color:#1c2024; border:1px solid #495057; border-radius:8px; padding:12px; margin-bottom:15px;">
                <h3 style="color:#ced4da; margin:0; display:flex; align-items:center;">
                    <span style="display:inline-block; width:12px; height:12px; background-color:#6c757d; border-radius:50%; margin-right:10px;"></span>
                    Status: sleep
                </h3>
                <p style="color:#adb5bd; margin:5px 0 0 22px; font-size:14px;">Pokemon League service is idle and ready.</p>
            </div>
            """,
            unsafe_allow_html=True
        )

    # Device Login Alert Banner
    if current_state.get("device_login_alert"):
        st.error(
            "🚨 **DEVICE LOGIN DETECTED**: You logged into the game from your mobile device! "
            "Pokemon League was automatically stopped and put into **sleep** mode to avoid session conflict. "
            "Click **Start League Run** whenever you are ready to resume."
        )

    # Daily Schedule Information Banner
    next_league_dt = compute_next_run("09:30")
    league_countdown = format_countdown(next_league_dt)
    sched_status_icon = "🟢 Active" if scheduler_running else "⚪ Idle"

    st.markdown(
        f"""
        <div style="background-color:#161d2b; border:1px solid #10b981; border-radius:8px; padding:14px; margin-bottom:16px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div>
                    <h4 style="color:#34d399; margin:0 0 4px 0;">⏰ Daily Morning Auto-Schedule: 9:30 AM – 10:30 AM IST</h4>
                    <p style="color:#d1fae5; margin:0; font-size:14px;">
                        Runs matchmaking continuously between <b>9:30 AM and 10:30 AM IST</b>. Stops immediately when <b>10 successful player matches</b> are cleared or time exceeds <b>10:30 AM</b>.
                    </p>
                    <p style="color:#a7f3d0; margin:4px 0 0 0; font-size:13px;">
                        Master Scheduler: <b>{sched_status_icon}</b> | Next Trigger: <b>{next_league_dt.strftime('%b %d, %I:%M %p')} IST</b> (in {league_countdown})
                    </p>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    # Parameters
    col_l1, col_l2 = st.columns(2)
    with col_l1:
        target_val = current_state.get("target_matches", 10)
        default_m_idx = LEAGUE_MATCH_OPTIONS.index(target_val) if target_val in LEAGUE_MATCH_OPTIONS else 1
        matches_selection = st.selectbox(
            "Target Successful Matches:",
            options=LEAGUE_MATCH_OPTIONS,
            index=default_m_idx,
            disabled=is_running
        )

    with col_l2:
        cutoff_selection = st.text_input(
            "Cutoff Time (24-Hour IST):",
            value=current_state.get("cutoff_time", "10:30"),
            disabled=is_running,
            help="Session stops if current time reaches or exceeds this cutoff."
        )

    # Start / Stop Buttons
    col_btn1, col_btn2 = st.columns([2, 1])

    with col_btn1:
        if st.button("Start League Run (Manual)", type="primary", use_container_width=True, disabled=is_running):
            if is_running:
                st.warning("Pokemon League is already running!")
            else:
                ensure_data_dir()
                sub_env = os.environ.copy()
                sub_env["PYTHONIOENCODING"] = "utf-8"
                sub_env["PYTHONUTF8"] = "1"
                sub_env["PYTHONUNBUFFERED"] = "1"

                log_file = SERVICE_CONFIGS["league"]["log_file"]
                log_handle = open(log_file, "a", encoding="utf-8", errors="replace")

                creation_flags = 0
                if sys.platform == "win32":
                    creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

                script_path = resolve_script_path("league")
                cmd = [
                    sys.executable,
                    script_path,
                    "--matches", str(matches_selection),
                    "--cutoff", str(cutoff_selection).strip()
                ]

                proc = subprocess.Popen(
                    cmd,
                    stdout=log_handle,
                    stderr=log_handle,
                    stdin=subprocess.DEVNULL,
                    creationflags=creation_flags,
                    env=sub_env
                )
                log_handle.close()

                current_state["status"] = "running"
                current_state["pid"] = proc.pid
                current_state["target_matches"] = matches_selection
                current_state["completed_matches"] = 0
                current_state["queue_attempts"] = 0
                current_state["cutoff_time"] = cutoff_selection
                current_state["start_time"] = format_ist_timestamp()
                current_state["device_login_alert"] = False
                current_state["message"] = f"Started League run (Target: {matches_selection} matches, Cutoff: {cutoff_selection} IST)..."
                save_service_state("league", current_state)
                st.rerun()

    with col_btn2:
        if st.button("Stop League Run", type="secondary", use_container_width=True, disabled=not is_running):
            if is_running and current_state.get("pid"):
                stop_service_process(current_state["pid"])
                current_state["status"] = "sleep"
                current_state["pid"] = None
                current_state["message"] = "Pokemon League stopped manually by user."
                save_service_state("league", current_state)
                st.rerun()

    st.markdown("---")
    st.markdown("#### Live Activity Logs")
    st.code(read_service_logs("league", max_lines=35), language="text")


# ==========================================
# SERVICE UI: 4. DAILY SCHEDULERS
# ==========================================
else:
    st.title("Daily_Schedulers")

    sched_league_state = load_service_state("scheduler_league")
    sched_elite_state = load_service_state("scheduler_elite")
    sched_league_running = (sched_league_state.get("status") == "running")
    sched_elite_running = (sched_elite_state.get("status") == "running")

    # Top Overview / Quick Summary
    next_l_dt = compute_next_run(sched_league_state.get("from_time", "09:30"))
    next_e_dt = compute_next_run(sched_elite_state.get("trigger_time", "21:32"))
    countdown_l = format_countdown(next_l_dt)
    countdown_e = format_countdown(next_e_dt)

    # -------------------------------------------------------------
    # SECTION 1: POKEMON LEAGUE DAILY AUTO-PILOT
    # -------------------------------------------------------------
    st.markdown("## 🏆 Pokemon League Daily Auto-Pilot")

    if sched_league_running:
        st.markdown(
            f"""
            <div style="background-color:#0e2a18; border:2px solid #28a745; border-radius:8px; padding:12px; margin-bottom:15px;">
                <h3 style="color:#28a745; margin:0; display:flex; align-items:center;">
                    <span style="display:inline-block; width:12px; height:12px; background-color:#28a745; border-radius:50%; margin-right:10px;"></span>
                    Status: running (League Auto-Pilot Active)
                </h3>
                <p style="color:#a5d6a7; margin:5px 0 0 22px; font-size:14px;">
                    PID: {sched_league_state.get('pid')} | Window: {sched_league_state.get('from_time', '09:30')} → {sched_league_state.get('to_time', '10:30')} IST | Max: {sched_league_state.get('target_matches', 10)} matches
                </p>
            </div>
            """,
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            """
            <div style="background-color:#1c2024; border:1px solid #495057; border-radius:8px; padding:12px; margin-bottom:15px;">
                <h3 style="color:#ced4da; margin:0; display:flex; align-items:center;">
                    <span style="display:inline-block; width:12px; height:12px; background-color:#6c757d; border-radius:50%; margin-right:10px;"></span>
                    Status: sleep (League Auto-Pilot Idle)
                </h3>
                <p style="color:#adb5bd; margin:5px 0 0 22px; font-size:14px;">The Pokemon League daily scheduler is idle. Configure window below and click Start.</p>
            </div>
            """,
            unsafe_allow_html=True
        )

    # League Settings (From -> To and Target Matches)
    st.markdown("#### Schedule Settings (Daily Window & Target)")
    col_lf, col_lt, col_lm = st.columns([1.5, 1.5, 1.2])

    with col_lf:
        cur_from = sched_league_state.get("from_time", "09:30")
        from_input = st.text_input(
            "From Time (Start IST):",
            value=cur_from,
            disabled=sched_league_running,
            help="Daily start time in 24-hr format (e.g. 09:30)"
        )

    with col_lt:
        cur_to = sched_league_state.get("to_time", "10:30")
        to_input = st.text_input(
            "To Time (Cutoff IST):",
            value=cur_to,
            disabled=sched_league_running,
            help="Daily cutoff time in 24-hr format (e.g. 10:30)"
        )

    with col_lm:
        cur_matches = sched_league_state.get("target_matches", 10)
        match_idx = LEAGUE_MATCH_OPTIONS.index(cur_matches) if cur_matches in LEAGUE_MATCH_OPTIONS else 1
        matches_choice = st.selectbox(
            "Target Matches:",
            options=LEAGUE_MATCH_OPTIONS,
            index=match_idx,
            disabled=sched_league_running,
            help="Target successful player encounters"
        )

    # Save Settings Button
    if st.button("💾 Save League Schedule Settings", use_container_width=True, disabled=sched_league_running):
        clean_from = from_input.strip()
        clean_to = to_input.strip()
        # Basic validation
        if ":" in clean_from and ":" in clean_to:
            sched_league_state["from_time"] = clean_from
            sched_league_state["to_time"] = clean_to
            sched_league_state["target_matches"] = matches_choice
            nxt = compute_next_run(clean_from)
            sched_league_state["next_run"] = format_ist_timestamp(nxt)
            sched_league_state["message"] = f"Settings saved: Daily {clean_from} -> {clean_to} IST (Target: {matches_choice} matches)."
            save_service_state("scheduler_league", sched_league_state)
            st.success(f"League schedule saved! Daily window: {clean_from} – {clean_to} IST (Next run: {sched_league_state['next_run']})")
            st.rerun()
        else:
            st.error("Please provide valid times in 24-hour HH:MM format (e.g. 09:30 and 10:30).")

    # League Next Run Info Box
    st.caption(
        f"📅 **Next Scheduled Run:** {next_l_dt.strftime('%b %d, %Y at %I:%M %p')} IST (in {countdown_l}) | "
        f"**Last Run:** {sched_league_state.get('last_run') or 'None recorded yet'}"
    )

    # Start / Stop League Auto-Pilot
    col_lbtn1, col_lbtn2 = st.columns([2, 1])

    with col_lbtn1:
        if st.button("▶️ Start League Auto-Pilot", type="primary", use_container_width=True, disabled=sched_league_running):
            ensure_data_dir()
            sub_env = os.environ.copy()
            sub_env["PYTHONIOENCODING"] = "utf-8"
            sub_env["PYTHONUTF8"] = "1"
            sub_env["PYTHONUNBUFFERED"] = "1"

            log_file = SERVICE_CONFIGS["scheduler_league"]["log_file"]
            log_handle = open(log_file, "a", encoding="utf-8", errors="replace")

            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

            script_path = resolve_script_path("scheduler_league")
            from_val = sched_league_state.get("from_time", "09:30")
            to_val = sched_league_state.get("to_time", "10:30")
            matches_val = sched_league_state.get("target_matches", 10)

            cmd = [
                sys.executable,
                script_path,
                "--service", "league",
                "--from-time", str(from_val),
                "--to-time", str(to_val),
                "--matches", str(matches_val)
            ]

            proc = subprocess.Popen(
                cmd,
                stdout=log_handle,
                stderr=log_handle,
                stdin=subprocess.DEVNULL,
                creationflags=creation_flags,
                env=sub_env
            )
            log_handle.close()

            sched_league_state["status"] = "running"
            sched_league_state["pid"] = proc.pid
            sched_league_state["start_time"] = format_ist_timestamp()
            sched_league_state["message"] = f"League Auto-Pilot running: Daily {from_val} -> {to_val} IST."
            save_service_state("scheduler_league", sched_league_state)
            st.rerun()

    with col_lbtn2:
        if st.button("⏹️ Stop League Auto-Pilot", type="secondary", use_container_width=True, disabled=not sched_league_running):
            if sched_league_running and sched_league_state.get("pid"):
                stop_service_process(sched_league_state["pid"])
                sched_league_state["status"] = "sleep"
                sched_league_state["pid"] = None
                sched_league_state["message"] = "League Auto-Pilot stopped manually by user."
                save_service_state("scheduler_league", sched_league_state)
                st.rerun()

    with st.expander("📄 League Auto-Pilot Logs", expanded=False):
        st.code(read_service_logs("scheduler_league", max_lines=35), language="text")

    st.markdown("---")

    # -------------------------------------------------------------
    # SECTION 2: ELITE BATTLE DAILY SCHEDULER
    # -------------------------------------------------------------
    st.markdown("## 🛡️ Elite Battle Daily Scheduler")

    if sched_elite_running:
        st.markdown(
            f"""
            <div style="background-color:#0e2a18; border:2px solid #28a745; border-radius:8px; padding:12px; margin-bottom:15px;">
                <h3 style="color:#28a745; margin:0; display:flex; align-items:center;">
                    <span style="display:inline-block; width:12px; height:12px; background-color:#28a745; border-radius:50%; margin-right:10px;"></span>
                    Status: running (Elite Battle Scheduler Active)
                </h3>
                <p style="color:#a5d6a7; margin:5px 0 0 22px; font-size:14px;">
                    PID: {sched_elite_state.get('pid')} | Daily Trigger: {sched_elite_state.get('trigger_time', '21:32')} IST | Battles: {sched_elite_state.get('target_battles', 3)}
                </p>
            </div>
            """,
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            """
            <div style="background-color:#1c2024; border:1px solid #495057; border-radius:8px; padding:12px; margin-bottom:15px;">
                <h3 style="color:#ced4da; margin:0; display:flex; align-items:center;">
                    <span style="display:inline-block; width:12px; height:12px; background-color:#6c757d; border-radius:50%; margin-right:10px;"></span>
                    Status: sleep (Elite Scheduler Idle)
                </h3>
                <p style="color:#adb5bd; margin:5px 0 0 22px; font-size:14px;">The Elite Battle daily scheduler is idle. Configure trigger time below and click Start.</p>
            </div>
            """,
            unsafe_allow_html=True
        )

    # Elite Settings
    st.markdown("#### Schedule Settings (Trigger Time & Battles)")
    col_et, col_eb = st.columns([2, 1.2])

    with col_et:
        cur_etime = sched_elite_state.get("trigger_time", "21:32")
        etime_input = st.text_input(
            "Trigger Time (IST):",
            value=cur_etime,
            disabled=sched_elite_running,
            help="Daily trigger time in 24-hr format (e.g. 21:32)"
        )

    with col_eb:
        cur_ebattles = sched_elite_state.get("target_battles", 3)
        ebattle_idx = ELITE_BATTLE_OPTIONS.index(cur_ebattles) if cur_ebattles in ELITE_BATTLE_OPTIONS else 2
        ebattles_choice = st.selectbox(
            "Target Battles:",
            options=ELITE_BATTLE_OPTIONS,
            index=ebattle_idx,
            disabled=sched_elite_running,
            help="Number of challenger battles"
        )

    # Save Settings Button
    if st.button("💾 Save Elite Schedule Settings", use_container_width=True, disabled=sched_elite_running):
        clean_etime = etime_input.strip()
        if ":" in clean_etime:
            sched_elite_state["trigger_time"] = clean_etime
            sched_elite_state["target_battles"] = ebattles_choice
            nxt = compute_next_run(clean_etime)
            sched_elite_state["next_run"] = format_ist_timestamp(nxt)
            sched_elite_state["message"] = f"Settings saved: Daily {clean_etime} IST (Battles: {ebattles_choice})."
            save_service_state("scheduler_elite", sched_elite_state)
            st.success(f"Elite Battle schedule saved! Daily at {clean_etime} IST (Next run: {sched_elite_state['next_run']})")
            st.rerun()
        else:
            st.error("Please provide a valid time in 24-hour HH:MM format (e.g. 21:32).")

    # Elite Next Run Info Box
    st.caption(
        f"📅 **Next Scheduled Run:** {next_e_dt.strftime('%b %d, %Y at %I:%M %p')} IST (in {countdown_e}) | "
        f"**Last Run:** {sched_elite_state.get('last_run') or 'None recorded yet'}"
    )

    # Start / Stop Elite Scheduler
    col_ebtn1, col_ebtn2 = st.columns([2, 1])

    with col_ebtn1:
        if st.button("▶️ Start Elite Scheduler", type="primary", use_container_width=True, disabled=sched_elite_running):
            ensure_data_dir()
            sub_env = os.environ.copy()
            sub_env["PYTHONIOENCODING"] = "utf-8"
            sub_env["PYTHONUTF8"] = "1"
            sub_env["PYTHONUNBUFFERED"] = "1"

            log_file = SERVICE_CONFIGS["scheduler_elite"]["log_file"]
            log_handle = open(log_file, "a", encoding="utf-8", errors="replace")

            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

            script_path = resolve_script_path("scheduler_elite")
            t_val = sched_elite_state.get("trigger_time", "21:32")
            b_val = sched_elite_state.get("target_battles", 3)

            cmd = [
                sys.executable,
                script_path,
                "--service", "elite",
                "--time", str(t_val),
                "--battles", str(b_val)
            ]

            proc = subprocess.Popen(
                cmd,
                stdout=log_handle,
                stderr=log_handle,
                stdin=subprocess.DEVNULL,
                creationflags=creation_flags,
                env=sub_env
            )
            log_handle.close()

            sched_elite_state["status"] = "running"
            sched_elite_state["pid"] = proc.pid
            sched_elite_state["start_time"] = format_ist_timestamp()
            sched_elite_state["message"] = f"Elite Battle scheduler running: Daily {t_val} IST."
            save_service_state("scheduler_elite", sched_elite_state)
            st.rerun()

    with col_ebtn2:
        if st.button("⏹️ Stop Elite Scheduler", type="secondary", use_container_width=True, disabled=not sched_elite_running):
            if sched_elite_running and sched_elite_state.get("pid"):
                stop_service_process(sched_elite_state["pid"])
                sched_elite_state["status"] = "sleep"
                sched_elite_state["pid"] = None
                sched_elite_state["message"] = "Elite Battle scheduler stopped manually by user."
                save_service_state("scheduler_elite", sched_elite_state)
                st.rerun()

    with st.expander("📄 Elite Scheduler Logs", expanded=False):
        st.code(read_service_logs("scheduler_elite", max_lines=35), language="text")

    st.markdown("---")

    # -------------------------------------------------------------
    # SECTION 3: MASTER CONTROLS
    # -------------------------------------------------------------
    st.markdown("#### Quick Master Controls")
    col_m1, col_m2 = st.columns(2)
    with col_m1:
        if st.button("🚀 Start Both Schedulers", use_container_width=True, disabled=(sched_league_running and sched_elite_running)):
            # Start league if not running
            if not sched_league_running:
                ensure_data_dir()
                sub_env = os.environ.copy()
                sub_env["PYTHONIOENCODING"] = "utf-8"
                sub_env["PYTHONUTF8"] = "1"
                sub_env["PYTHONUNBUFFERED"] = "1"
                log_file = SERVICE_CONFIGS["scheduler_league"]["log_file"]
                log_handle = open(log_file, "a", encoding="utf-8", errors="replace")
                creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS if sys.platform == "win32" else 0
                cmd = [
                    sys.executable, resolve_script_path("scheduler_league"),
                    "--service", "league",
                    "--from-time", str(sched_league_state.get("from_time", "09:30")),
                    "--to-time", str(sched_league_state.get("to_time", "10:30")),
                    "--matches", str(sched_league_state.get("target_matches", 10))
                ]
                proc = subprocess.Popen(cmd, stdout=log_handle, stderr=log_handle, stdin=subprocess.DEVNULL, creationflags=creation_flags, env=sub_env)
                log_handle.close()
                sched_league_state["status"] = "running"
                sched_league_state["pid"] = proc.pid
                sched_league_state["start_time"] = format_ist_timestamp()
                save_service_state("scheduler_league", sched_league_state)

            # Start elite if not running
            if not sched_elite_running:
                ensure_data_dir()
                sub_env = os.environ.copy()
                sub_env["PYTHONIOENCODING"] = "utf-8"
                sub_env["PYTHONUTF8"] = "1"
                sub_env["PYTHONUNBUFFERED"] = "1"
                log_file = SERVICE_CONFIGS["scheduler_elite"]["log_file"]
                log_handle = open(log_file, "a", encoding="utf-8", errors="replace")
                creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS if sys.platform == "win32" else 0
                cmd = [
                    sys.executable, resolve_script_path("scheduler_elite"),
                    "--service", "elite",
                    "--time", str(sched_elite_state.get("trigger_time", "21:32")),
                    "--battles", str(sched_elite_state.get("target_battles", 3))
                ]
                proc = subprocess.Popen(cmd, stdout=log_handle, stderr=log_handle, stdin=subprocess.DEVNULL, creationflags=creation_flags, env=sub_env)
                log_handle.close()
                sched_elite_state["status"] = "running"
                sched_elite_state["pid"] = proc.pid
                sched_elite_state["start_time"] = format_ist_timestamp()
                save_service_state("scheduler_elite", sched_elite_state)

            st.rerun()

    with col_m2:
        if st.button("🛑 Stop All Schedulers", use_container_width=True, disabled=(not sched_league_running and not sched_elite_running)):
            if sched_league_running and sched_league_state.get("pid"):
                stop_service_process(sched_league_state["pid"])
                sched_league_state["status"] = "sleep"
                sched_league_state["pid"] = None
                save_service_state("scheduler_league", sched_league_state)
            if sched_elite_running and sched_elite_state.get("pid"):
                stop_service_process(sched_elite_state["pid"])
                sched_elite_state["status"] = "sleep"
                sched_elite_state["pid"] = None
                save_service_state("scheduler_elite", sched_elite_state)
            st.rerun()


# ==========================================
# AUTO-REFRESH LOOP
# ==========================================
if is_running or sched_league_running or sched_elite_running:
    time.sleep(2)
    st.rerun()

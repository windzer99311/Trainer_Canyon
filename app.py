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


def is_service_alive(pid: int, pattern: str) -> bool:
    if not pid:
        return False
    try:
        p = psutil.Process(pid)
        if not p.is_running():
            return False
        cmd = " ".join(p.cmdline()).lower()
        if "python" in p.name().lower() and pattern.lower() in cmd:
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
                    if not is_service_alive(pid, cfg["process_pattern"]):
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
scheduler_state = load_service_state("scheduler")

trail_running = (trail_state.get("status") == "running")
elite_running = (elite_state.get("status") == "running")
league_running = (league_state.get("status") == "running")
scheduler_running = (scheduler_state.get("status") == "running")

st.sidebar.title("⚡ Game Bot Services")
selected_service_name = st.sidebar.radio(
    "Choose Service:",
    ["Legendary Trail", "Elite Battle", "Pokemon League", "Daily Schedulers"],
    index=2
)

st.sidebar.markdown("---")
st.sidebar.markdown("### Live Monitors")
st.sidebar.markdown(f"**Legendary Trail:** {'🟢 running' if trail_running else '⚪ sleep'}")
st.sidebar.markdown(f"**Elite Battle:** {'🟢 running' if elite_running else '⚪ sleep'}")
st.sidebar.markdown(f"**Pokemon League:** {'🟢 running' if league_running else '⚪ sleep'}")
st.sidebar.markdown(f"**Daily Schedulers:** {'🟢 active' if scheduler_running else '⚪ sleep'}")

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

    next_l_dt = compute_next_run("09:30")
    next_e_dt = compute_next_run("21:32")
    countdown_l = format_countdown(next_l_dt)
    countdown_e = format_countdown(next_e_dt)

    if scheduler_running:
        st.markdown(
            f"""
            <div style="background-color:#0e2a18; border:2px solid #28a745; border-radius:8px; padding:12px; margin-bottom:15px;">
                <h3 style="color:#28a745; margin:0; display:flex; align-items:center;">
                    <span style="display:inline-block; width:12px; height:12px; background-color:#28a745; border-radius:50%; margin-right:10px;"></span>
                    Status: running (Master Scheduler Daemon Active)
                </h3>
                <p style="color:#a5d6a7; margin:5px 0 0 22px; font-size:14px;">
                    PID: {scheduler_state.get('pid')} | All daily automated timers are running in the background.
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
                    Status: sleep (Schedulers Inactive)
                </h3>
                <p style="color:#adb5bd; margin:5px 0 0 22px; font-size:14px;">The scheduler daemon is currently idle. Enable it below to automate both schedules.</p>
            </div>
            """,
            unsafe_allow_html=True
        )

    # Active Automated Tasks Overview
    st.markdown("### Configured Daily Automations")

    col_t1, col_t2 = st.columns(2)
    with col_t1:
        st.markdown(
            f"""
            <div style="background-color:#1a2332; border:1px solid #10b981; border-radius:8px; padding:12px;">
                <h4 style="color:#34d399; margin:0 0 6px 0;">🏆 Pokemon League</h4>
                <p style="color:#e2e8f0; margin:0; font-size:14px;"><b>Daily Window:</b> 9:30 AM – 10:30 AM IST</p>
                <p style="color:#cbd5e1; margin:4px 0; font-size:13px;"><b>Rule:</b> Unlimited queueing until 10 successful player matches or 10:30 AM cutoff.</p>
                <p style="color:#6ee7b7; margin:6px 0 0 0; font-size:13px;"><b>Next Run:</b> {next_l_dt.strftime('%b %d, %I:%M %p')} IST (in {countdown_l})</p>
            </div>
            """,
            unsafe_allow_html=True
        )

    with col_t2:
        st.markdown(
            f"""
            <div style="background-color:#1a2332; border:1px solid #3b82f6; border-radius:8px; padding:12px;">
                <h4 style="color:#60a5fa; margin:0 0 6px 0;">🛡️ Elite Battle</h4>
                <p style="color:#e2e8f0; margin:0; font-size:14px;"><b>Daily Time:</b> 9:32 PM IST</p>
                <p style="color:#cbd5e1; margin:4px 0; font-size:13px;"><b>Rule:</b> Auto-clears 3 challenger battles (4->3->2->1 fallback).</p>
                <p style="color:#93c5fd; margin:6px 0 0 0; font-size:13px;"><b>Next Run:</b> {next_e_dt.strftime('%b %d, %I:%M %p')} IST (in {countdown_e})</p>
            </div>
            """,
            unsafe_allow_html=True
        )

    st.markdown("---")

    # Master Scheduler Controls
    col_sc1, col_sc2 = st.columns([2, 1])

    with col_sc1:
        if st.button("Start Master Scheduler Daemon", type="primary", use_container_width=True, disabled=scheduler_running):
            ensure_data_dir()
            sub_env = os.environ.copy()
            sub_env["PYTHONIOENCODING"] = "utf-8"
            sub_env["PYTHONUTF8"] = "1"
            sub_env["PYTHONUNBUFFERED"] = "1"

            log_file = SERVICE_CONFIGS["scheduler"]["log_file"]
            log_handle = open(log_file, "a", encoding="utf-8", errors="replace")

            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

            script_path = resolve_script_path("scheduler")
            cmd = [
                sys.executable,
                script_path,
                "--service", "all"
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

            scheduler_state["status"] = "running"
            scheduler_state["pid"] = proc.pid
            scheduler_state["start_time"] = format_ist_timestamp()
            scheduler_state["message"] = "Master Scheduler active: Pokemon League (9:30 AM) & Elite Battle (9:32 PM)."
            save_service_state("scheduler", scheduler_state)
            st.rerun()

    with col_sc2:
        if st.button("Stop Master Scheduler", type="secondary", use_container_width=True, disabled=not scheduler_running):
            if scheduler_running and scheduler_state.get("pid"):
                stop_service_process(scheduler_state["pid"])
                scheduler_state["status"] = "sleep"
                scheduler_state["pid"] = None
                scheduler_state["message"] = "Master Scheduler stopped manually by user."
                save_service_state("scheduler", scheduler_state)
                st.rerun()

    st.markdown("---")
    st.markdown("#### Master Scheduler Logs")
    st.code(read_service_logs("scheduler", max_lines=35), language="text")


# ==========================================
# AUTO-REFRESH LOOP
# ==========================================
if is_running or scheduler_running:
    time.sleep(2)
    st.rerun()

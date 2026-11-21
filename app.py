#!/usr/bin/env python3
"""
Streamlit Dashboard for Pokemon Remake - Multi-Service Bot
Provides stateless control with persistent background execution for:
  1. Legendary Trail (Mythical Animal Trial)
  2. Elite Battle (Elite Four Auto-Battler)
"""

import datetime
import json
import os
import subprocess
import sys
import time
import psutil
import streamlit as st

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
}

LAYER_OPTIONS = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
ELITE_BATTLE_OPTIONS = [1, 2, 3, 4]

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
    return default_state


def save_service_state(service_key: str, state: dict):
    ensure_data_dir()
    state["updated_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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


# ==========================================
# SIDEBAR NAVIGATION & STATUS
# ==========================================
trail_state = load_service_state("trail")
elite_state = load_service_state("elite")
trail_running = (trail_state.get("status") == "running")
elite_running = (elite_state.get("status") == "running")

st.sidebar.title("⚡ Game Bot Services")
selected_service_name = st.sidebar.radio(
    "Choose Service:",
    ["Legendary Trail", "Elite Battle"],
    index=0
)

st.sidebar.markdown("---")
st.sidebar.markdown("### Service Monitors")
st.sidebar.markdown(f"**Legendary Trail:** {'🟢 running' if trail_running else '⚪ sleep'}")
st.sidebar.markdown(f"**Elite Battle:** {'🟢 running' if elite_running else '⚪ sleep'}")

current_service_key = "trail" if selected_service_name == "Legendary Trail" else "elite"
current_state = trail_state if current_service_key == "trail" else elite_state
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
                current_state["start_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
else:
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

    # Battles Selector (Default: 3, choices: 1, 2, 3, 4)
    col_opt1, col_opt2 = st.columns(2)
    with col_opt1:
        # Default index 2 corresponds to 3 battles
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
        if st.button("Start Battle", type="primary", use_container_width=True, disabled=is_running):
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
                current_state["start_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
# AUTO-REFRESH LOOP
# ==========================================
if is_running:
    time.sleep(2)
    st.rerun()

#!/usr/bin/env python3
"""
Streamlit Dashboard for Pokemon Remake - Legendary Trail
Provides stateless control with persistent background execution.
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
# CONFIGURATION & CONSTANTS
# ==========================================
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
STATE_FILE = os.path.join(DATA_DIR, "trail_state.json")
LOG_FILE = os.path.join(DATA_DIR, "trail_activity.log")
SERVICE_SCRIPT_CANDIDATES = [
    os.path.join(PROJECT_ROOT, "scripts", "legendary_trail_service.py"),
    os.path.join(PROJECT_ROOT, "legendary_trail_service.py")
]
SERVICE_SCRIPT = next((s for s in SERVICE_SCRIPT_CANDIDATES if os.path.exists(s)), SERVICE_SCRIPT_CANDIDATES[0])

LAYER_OPTIONS = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]

st.set_page_config(
    page_title="Legendary_trail",
    page_icon="⚔️",
    layout="centered"
)


# ==========================================
# STATE MANAGEMENT
# ==========================================
def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def load_state() -> dict:
    ensure_data_dir()
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
                # Verify process liveness
                pid = state.get("pid")
                if state.get("status") == "running" and pid:
                    if not psutil.pid_exists(pid):
                        # Process terminated outside or finished
                        state["status"] = "sleep"
                        state["pid"] = None
                        save_state(state)
                return state
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


def save_state(state: dict):
    ensure_data_dir()
    state["updated_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    temp_file = STATE_FILE + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(temp_file, STATE_FILE)


def read_recent_logs(max_lines: int = 40) -> str:
    if not os.path.exists(LOG_FILE):
        return "No activity logged yet."
    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            return "".join(lines[-max_lines:])
    except Exception as e:
        return f"Error reading logs: {e}"


def stop_service(pid: int):
    try:
        p = psutil.Process(pid)
        for child in p.children(recursive=True):
            child.terminate()
        p.terminate()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass


# ==========================================
# STREAMLIT UI
# ==========================================
state = load_state()
is_running = (state.get("status") == "running")

st.title("Legendary_trail")

# Status Display
if is_running:
    curr_layer = state.get("current_layer")
    layer_txt = f" (Executing Floor: Layer {curr_layer})" if curr_layer else ""
    st.markdown(
        f"""
        <div style="background-color:#0e2a18; border:2px solid #28a745; border-radius:8px; padding:12px; margin-bottom:15px;">
            <h3 style="color:#28a745; margin:0; display:flex; align-items:center;">
                <span style="display:inline-block; width:12px; height:12px; background-color:#28a745; border-radius:50%; margin-right:10px; animation:blink 1.2s infinite;"></span>
                Status: running {layer_txt}
            </h3>
            <p style="color:#a5d6a7; margin:5px 0 0 22px; font-size:14px;">PID: {state.get('pid')} | Started: {state.get('start_time')}</p>
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
if state.get("device_login_alert"):
    st.error(
        "🚨 **DEVICE LOGIN DETECTED**: You logged in from your mobile device! "
        "The service was automatically stopped to protect your account and is now in **sleep** mode. "
        "When ready, click **Start Trail** to resume."
    )

# From & To Dropdowns
col_from, col_to = st.columns(2)
with col_from:
    default_from_idx = LAYER_OPTIONS.index(state.get("from_layer", 10)) if state.get("from_layer") in LAYER_OPTIONS else 0
    from_selection = st.selectbox("From:", options=LAYER_OPTIONS, index=default_from_idx, disabled=is_running)

with col_to:
    default_to_idx = LAYER_OPTIONS.index(state.get("to_layer", 100)) if state.get("to_layer") in LAYER_OPTIONS else len(LAYER_OPTIONS) - 1
    to_selection = st.selectbox("To:", options=LAYER_OPTIONS, index=default_to_idx, disabled=is_running)

# Buttons
col_btn1, col_btn2 = st.columns([2, 1])

with col_btn1:
    if st.button("Start Trail", type="primary", use_container_width=True, disabled=is_running):
        if is_running:
            st.warning("Trail is already running!")
        else:
            # Prepare background process
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

            cmd = [
                sys.executable,
                SERVICE_SCRIPT,
                "--from", str(from_selection),
                "--to", str(to_selection)
            ]

            proc = subprocess.Popen(
                cmd,
                creationflags=creation_flags,
                close_fds=True
            )

            # Update state immediately
            state["status"] = "running"
            state["pid"] = proc.pid
            state["from_layer"] = from_selection
            state["to_layer"] = to_selection
            state["current_layer"] = from_selection
            state["start_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            state["device_login_alert"] = False
            state["message"] = f"Started trail from {from_selection} to {to_selection}."
            save_state(state)

            st.rerun()

with col_btn2:
    if st.button("Stop Trail", type="secondary", use_container_width=True, disabled=not is_running):
        if is_running and state.get("pid"):
            stop_service(state["pid"])
            state["status"] = "sleep"
            state["pid"] = None
            state["message"] = "Service stopped manually by user."
            save_state(state)
            st.rerun()

st.markdown("---")

# Real-time Activity Logs
st.markdown("#### Live Activity Logs")
log_content = read_recent_logs(max_lines=35)
st.code(log_content, language="text")

# Auto-refresh loop while running
if is_running:
    time.sleep(2)
    st.rerun()

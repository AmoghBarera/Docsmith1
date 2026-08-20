import json
import os
from pathlib import Path

def get_container_dir(cid: str) -> Path:
    from .utils import docksmith_home
    d = docksmith_home() / "containers" / cid
    d.mkdir(parents=True, exist_ok=True)
    return d

def save_state(cid: str, state: dict) -> None:
    state_file = get_container_dir(cid) / "state.json"
    state_file.write_text(json.dumps(state, indent=2))

def load_state(cid: str) -> dict | None:
    state_file = get_container_dir(cid) / "state.json"
    if not state_file.exists():
        return None
    try:
        return json.loads(state_file.read_text())
    except json.JSONDecodeError:
        return None

def update_state_status(cid: str, status: str) -> None:
    state = load_state(cid)
    if state is not None:
        state["status"] = status
        save_state(cid, state)

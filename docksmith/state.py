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
    if not state_file.exists():
        state_file.write_text("{}")
    with open(state_file, "r+") as f:
        try:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX)
        except ImportError:
            pass
        f.seek(0)
        f.truncate()
        json.dump(state, f, indent=2)
        try:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_UN)
        except ImportError:
            pass

def load_state(cid: str) -> dict | None:
    state_file = get_container_dir(cid) / "state.json"
    if not state_file.exists():
        return None
    try:
        with open(state_file, "r") as f:
            try:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_SH)
            except ImportError:
                pass
            state = json.load(f)
            try:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_UN)
            except ImportError:
                pass
            return state
    except (json.JSONDecodeError, OSError):
        return None

def update_state_status(cid: str, status: str) -> None:
    state_file = get_container_dir(cid) / "state.json"
    if not state_file.exists():
        return
    with open(state_file, "r+") as f:
        try:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX)
        except ImportError:
            pass
        content = f.read()
        if content:
            state = json.loads(content)
            state["status"] = status
            f.seek(0)
            f.truncate()
            json.dump(state, f, indent=2)
        try:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_UN)
        except ImportError:
            pass

"""
Parse Docksmithfile / Dockerfile-like syntax into structured instructions.

Robust handling: comments, blank lines, line continuations, JSON-like CMD/ENV.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Union


@dataclass(frozen=True)
class Instruction:
    """Single parsed instruction."""

    name: str
    raw: str
    # Instruction-specific fields (normalized)
    value: Union[str, List[str], None] = None
    # COPY: src, dest
    copy_src: str | None = None
    copy_dest: str | None = None
    # ENV: key -> value (single ENV line may set multiple)
    env: dict[str, str] | None = None


def _strip_comment(line: str) -> str:
    # Remove # comments unless inside quotes (simplified: split on # not in quotes)
    in_single = False
    in_double = False
    out = []
    i = 0
    while i < len(line):
        c = line[i]
        if c == "'" and not in_double:
            in_single = not in_single
            out.append(c)
        elif c == '"' and not in_single:
            in_double = not in_double
            out.append(c)
        elif c == "#" and not in_single and not in_double:
            break
        else:
            out.append(c)
        i += 1
    return "".join(out).rstrip()


def _join_continued_lines(lines: List[str]) -> List[str]:
    """Join lines ending with backslash (Docker-style continuation)."""
    result: List[str] = []
    parts: List[str] = []
    for line in lines:
        raw = line.rstrip("\n\r")
        cont = len(raw) > 0 and raw.endswith("\\") and not raw.endswith("\\\\")
        segment = raw[:-1].rstrip() if cont else raw
        parts.append(segment)
        if not cont:
            result.append(" ".join(parts))
            parts = []
    if parts:
        result.append(" ".join(parts))
    return result


def _parse_cmd_value(rest: str) -> List[str]:
    rest = rest.strip()
    if not rest:
        return []
    # JSON array
    if rest.startswith("["):
        try:
            val = json.loads(rest)
            if isinstance(val, list):
                return [str(x) for x in val]
        except json.JSONDecodeError:
            pass
    # shell form
    try:
        return shlex.split(rest)
    except ValueError:
        return [rest]


def _parse_env_line(rest: str) -> dict[str, str]:
    """
    ENV KEY=value or ENV KEY=value KEY2=value2
    Values may be quoted.
    """
    rest = rest.strip()
    if not rest:
        return {}
    out: dict[str, str] = {}
    # Try KEY=value pairs with shlex
    try:
        parts = shlex.split(rest)
    except ValueError:
        parts = rest.split()
    i = 0
    while i < len(parts):
        p = parts[i]
        if "=" in p:
            k, _, v = p.partition("=")
            out[k] = v
            i += 1
        elif i + 1 < len(parts) and parts[i + 1].startswith("="):
            # malformed
            i += 1
        else:
            # KEY value (legacy docker: two tokens)
            if i + 1 < len(parts):
                out[p] = parts[i + 1]
                i += 2
            else:
                i += 1
    return out


def _split_copy(rest: str) -> tuple[str, str]:
    rest = rest.strip()
    if not rest:
        raise ValueError("COPY requires source and destination")
    try:
        parts = shlex.split(rest)
    except ValueError:
        parts = rest.split()
    if len(parts) < 2:
        raise ValueError("COPY requires at least source and destination")
    dest = parts[-1]
    src = " ".join(parts[:-1])
    return src, dest


def parse_docksmithfile(content: str) -> List[dict[str, Any]]:
    """
    Parse file content into list of dicts (JSON-serializable), e.g.:
    [{"instruction": "FROM", "value": "ubuntu:latest"}, ...]
    """
    instructions = parse_instructions(content)
    result: List[dict[str, Any]] = []
    for ins in instructions:
        d: dict[str, Any] = {"instruction": ins.name, "raw": ins.raw}
        if ins.value is not None:
            d["value"] = ins.value
        if ins.copy_src is not None:
            d["copy_src"] = ins.copy_src
            d["copy_dest"] = ins.copy_dest
        if ins.env is not None:
            d["env"] = ins.env
        result.append(d)
    return result


def parse_instructions(content: str) -> List[Instruction]:
    """Parse into Instruction objects."""
    raw_lines = content.splitlines()
    joined = _join_continued_lines(raw_lines)
    out: List[Instruction] = []
    for line in joined:
        line = _strip_comment(line).strip()
        if not line:
            continue
        upper = line.split(None, 1)
        if not upper:
            continue
        key = upper[0].upper()
        rest = upper[1] if len(upper) > 1 else ""

        if key == "FROM":
            out.append(Instruction("FROM", line, value=rest.strip()))
        elif key == "WORKDIR":
            out.append(Instruction("WORKDIR", line, value=rest.strip() or "/"))
        elif key == "COPY":
            src, dst = _split_copy(rest)
            out.append(Instruction("COPY", line, copy_src=src, copy_dest=dst))
        elif key == "RUN":
            out.append(Instruction("RUN", line, value=rest.strip()))
        elif key == "ENV":
            out.append(Instruction("ENV", line, env=_parse_env_line(rest)))
        elif key == "CMD":
            out.append(Instruction("CMD", line, value=_parse_cmd_value(rest)))
        else:
            raise ValueError(f"Unsupported instruction: {key} in line: {line}")

    return out


def load_docksmithfile(path: Path) -> List[Instruction]:
    if not path.is_file():
        raise FileNotFoundError(f"Docksmithfile not found: {path}")
    return parse_instructions(path.read_text(encoding="utf-8", errors="replace"))

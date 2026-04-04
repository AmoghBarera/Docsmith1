"""Tests for Docksmithfile parsing."""

from __future__ import annotations

import pytest

from docksmith.parser import parse_docksmithfile, parse_instructions


SAMPLE = """
FROM ubuntu:latest
WORKDIR /app
COPY . /app
RUN pip install -r requirements.txt
ENV PORT=5000
CMD ["python", "app.py"]
"""


def test_parse_docksmithfile_structure() -> None:
    out = parse_docksmithfile(SAMPLE)
    assert out[0] == {"instruction": "FROM", "raw": "FROM ubuntu:latest", "value": "ubuntu:latest"}
    assert out[1]["instruction"] == "WORKDIR"
    assert out[1]["value"] == "/app"
    assert out[2]["instruction"] == "COPY"
    assert out[2]["copy_src"] == "."
    assert out[2]["copy_dest"] == "/app"
    assert out[3]["instruction"] == "RUN"
    assert out[3]["value"] == "pip install -r requirements.txt"
    assert out[4]["instruction"] == "ENV"
    assert out[4]["env"] == {"PORT": "5000"}
    assert out[5]["instruction"] == "CMD"
    assert out[5]["value"] == ["python", "app.py"]


def test_comments_and_blanks() -> None:
    text = """
    # comment
    FROM scratch

    WORKDIR /tmp  # inline
    """
    ins = parse_instructions(text)
    assert [i.name for i in ins] == ["FROM", "WORKDIR"]


def test_cmd_shell_form() -> None:
    out = parse_docksmithfile("FROM scratch\nCMD python app.py\n")
    assert out[-1]["value"] == ["python", "app.py"]


def test_continuation() -> None:
    text = "RUN echo \\\n  hello\n"
    ins = parse_instructions(text)
    assert ins[0].name == "RUN"
    assert "hello" in ins[0].value


def test_invalid_instruction() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        parse_instructions("FROM scratch\nMAINTAINER x\n")

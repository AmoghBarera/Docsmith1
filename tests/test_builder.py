"""Build smoke tests (isolated DOCKSMITH_HOME)."""

from __future__ import annotations

import textwrap

import pytest

from docksmith.builder import build_image
from docksmith.manifest import load_manifest


def test_build_scratch_copy_only(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DOCKSMITH_HOME", str(tmp_path / "ds"))

    ctx = tmp_path / "ctx"
    ctx.mkdir()
    (ctx / "hello.txt").write_text("world", encoding="utf-8")

    df = ctx / "Docksmithfile"
    df.write_text(
        textwrap.dedent(
            """
            FROM scratch
            WORKDIR /app
            COPY . /app
            ENV MSG=hi
            CMD ["cat", "/app/hello.txt"]
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    build_image(ctx.resolve(), df.resolve(), "testimg", log=lambda _: None)

    m = load_manifest("testimg")
    assert m["base"] == "scratch"
    assert len(m["layers"]) == 2  # FROM + COPY
    assert m["env"]["MSG"] == "hi"
    assert m["cmd"] == ["cat", "/app/hello.txt"]
    assert m["workdir"] == "/app"


def test_layer_cache_hit_second_build(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DOCKSMITH_HOME", str(tmp_path / "ds"))

    ctx = tmp_path / "ctx"
    ctx.mkdir()
    (ctx / "hello.txt").write_text("same", encoding="utf-8")
    df = ctx / "Docksmithfile"
    df.write_text(
        "FROM scratch\nCOPY . /app\nCMD [\"echo\", \"x\"]\n",
        encoding="utf-8",
    )

    log: list[str] = []

    def capture(msg: str) -> None:
        log.append(msg)

    build_image(ctx.resolve(), df.resolve(), "a", log=capture)
    log.clear()
    build_image(ctx.resolve(), df.resolve(), "b", log=capture)
    assert "CACHE HIT" in log

"""Tests for the async subprocess + timeout helper."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.harness.process import run_subprocess_with_timeout


def _make_proc(returncode=0, stdout=b"", stderr=b"", communicate_side_effect=None):
    proc = MagicMock()
    proc.returncode = returncode
    if communicate_side_effect is not None:
        proc.communicate = AsyncMock(side_effect=communicate_side_effect)
    else:
        proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.kill = MagicMock()
    proc.wait = AsyncMock(return_value=0)
    return proc


async def test_normal_completion():
    proc = _make_proc(returncode=0, stdout=b"hello", stderr=b"warn")
    with patch(
        "src.harness.process.asyncio.create_subprocess_exec",
        AsyncMock(return_value=proc),
    ):
        rc, out, err, timed_out = await run_subprocess_with_timeout(
            ["echo", "hi"], timeout_s=5.0
        )
    assert rc == 0
    assert out == "hello"
    assert err == "warn"
    assert timed_out is False


async def test_timeout_triggers_kill_cmd():
    # First communicate() raises TimeoutError; the drain communicate() returns partial.
    main_proc = _make_proc(
        returncode=0,
        communicate_side_effect=[asyncio.TimeoutError(), (b"partial", b"")],
    )
    killer_proc = _make_proc(returncode=0)

    create_mock = AsyncMock(side_effect=[main_proc, killer_proc])
    with patch("src.harness.process.asyncio.create_subprocess_exec", create_mock):
        rc, out, err, timed_out = await run_subprocess_with_timeout(
            ["docker", "run", "x"],
            timeout_s=0.01,
            kill_cmd=["docker", "kill", "c"],
        )

    assert timed_out is True
    assert rc is None
    assert out == "partial"
    # kill_cmd must have been launched, and the local proc killed.
    assert create_mock.call_count == 2
    main_proc.kill.assert_called_once()

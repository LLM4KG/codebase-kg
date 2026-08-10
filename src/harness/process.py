"""Generic async subprocess + timeout helper.

The one wrapper around asyncio.create_subprocess_exec used identically by
`docker build` (docker_build.py) and `docker run` (runner.py). Shelling out to
the docker CLI keeps the Python layer a thin, auditable mirror of what a human
would type manually to reproduce a result.
"""

from __future__ import annotations

import asyncio


async def run_subprocess_with_timeout(
    cmd: list[str],
    timeout_s: float,
    kill_cmd: list[str] | None = None,
) -> tuple[int | None, str, str, bool]:
    """Run ``cmd`` via asyncio.create_subprocess_exec.

    On timeout, runs ``kill_cmd`` (e.g. ["docker", "kill", container_name]) to
    tear down the container, then drains output. Returns
    ``(returncode_or_None, stdout, stderr, timed_out)``.
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        return (
            proc.returncode,
            stdout_b.decode(errors="replace"),
            stderr_b.decode(errors="replace"),
            False,
        )
    except (asyncio.TimeoutError, TimeoutError):
        if kill_cmd is not None:
            try:
                killer = await asyncio.create_subprocess_exec(
                    *kill_cmd,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await killer.wait()
            except Exception:
                pass

        # Terminate the local process and drain whatever output is available.
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        try:
            stdout_b, stderr_b = await proc.communicate()
        except Exception:
            stdout_b, stderr_b = b"", b""
        return (
            None,
            stdout_b.decode(errors="replace"),
            stderr_b.decode(errors="replace"),
            True,
        )

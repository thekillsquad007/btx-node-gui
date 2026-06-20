from __future__ import annotations

import subprocess
from typing import Sequence

from .settings import Settings


class WslError(RuntimeError):
    pass


def _base_cmd(settings: Settings) -> list[str]:
    cmd = ["wsl"]
    if settings.wsl_distro:
        cmd.extend(["-d", settings.wsl_distro])
    cmd.extend(["-e", "bash", "-lc"])
    return cmd


def run_bash(settings: Settings, script: str, timeout: float | None = 600) -> subprocess.CompletedProcess[str]:
    cmd = _base_cmd(settings) + [script]
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as e:
        raise WslError(f"WSL command timed out after {timeout}s") from e


def btx_cli(settings: Settings, *args: str, timeout: float = 30) -> str:
    btx_cli_bin = f"{settings.btx_bin}/btx-cli"
    conf = f"{settings.datadir}/btx.conf"
    inner = " ".join(
        [
            btx_cli_bin,
            f'-datadir="{settings.datadir}"',
            f'-conf="{conf}"',
            *args,
        ]
    )
    result = run_bash(settings, inner, timeout=timeout)
    if result.returncode != 0:
        raise WslError((result.stderr or result.stdout or "btx-cli failed").strip())
    return (result.stdout or "").strip()


def node_script(settings: Settings, action: str, timeout: float | None = None) -> str:
    script = f'bash "{settings.pool_scripts}/ensure-btxd.sh" {action}'
    result = run_bash(settings, script, timeout=timeout)
    output = "\n".join(part for part in [result.stdout, result.stderr] if part).strip()
    if result.returncode != 0 and action not in {"status", "ensure"}:
        raise WslError(output or f"ensure-btxd.sh {action} failed")
    return output


def tail_log(settings: Settings, path: str, lines: int = 40) -> str:
    result = run_bash(settings, f'tail -n {lines} "{path}" 2>/dev/null || true', timeout=15)
    return (result.stdout or "").strip()


def process_running(settings: Settings, pattern: str) -> bool:
    result = run_bash(settings, f'pgrep -f "{pattern}" >/dev/null && echo yes || echo no', timeout=10)
    return (result.stdout or "").strip() == "yes"


def spawn_terminal(settings: Settings, title: str, bash_script: str) -> None:
    """Open a new console window running a bash script in WSL."""
    wsl_args = ["wsl.exe"]
    if settings.wsl_distro:
        wsl_args.extend(["-d", settings.wsl_distro])
    wsl_args.extend(["-e", "bash", "-lc", bash_script])
    subprocess.Popen(
        ["cmd", "/c", "start", title, *wsl_args],
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )


def start_node_detached(settings: Settings) -> None:
    script = (
        f'bash "{settings.pool_scripts}/start-node-detached.sh"; '
        'echo.; echo Press Enter to close this window.; read _'
    )
    spawn_terminal(settings, "BTX Node", script)


def wsl_home(settings: Settings) -> str:
    if "/.local/" in settings.btx_bin:
        return settings.btx_bin.split("/.local/")[0]
    if settings.btx_bin.startswith("/home/"):
        parts = settings.btx_bin.strip("/").split("/")
        if len(parts) >= 2:
            return f"/home/{parts[1]}"
    return "/home/aravindthana"


def pool_state_log(settings: Settings) -> str:
    return f"{wsl_home(settings)}/.local/share/btxpool/ensure-btxd.log"


def rebootstrap_detached(settings: Settings) -> None:
    script = (
        f'bash "{settings.pool_scripts}/ensure-btxd.sh" rebootstrap; '
        'echo.; echo Rebootstrap finished. Press Enter to close.; read _'
    )
    spawn_terminal(settings, "BTX Rebootstrap", script)
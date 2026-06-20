from __future__ import annotations

import socket
import subprocess
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from .settings import Settings


class NodeError(RuntimeError):
    pass


def _log(settings: Settings, message: str) -> None:
    settings.manager_log_path().parent.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] {message}\n"
    with settings.manager_log_path().open("a", encoding="utf-8") as handle:
        handle.write(line)


def ensure_conf(settings: Settings) -> None:
    conf = settings.conf_path()
    if conf.is_file():
        return
    settings.resolved_datadir().mkdir(parents=True, exist_ok=True)
    conf.write_text(
        "\n".join(
            [
                "server=1",
                "listen=1",
                "daemon=1",
                "prune=4096",
                "rpcuser=miner",
                "rpcpassword=miner",
                f"rpcport={settings.rpc_port}",
                "rpcbind=0.0.0.0",
                "rpcallowip=127.0.0.1",
                "rpcallowip=172.16.0.0/12",
                "rpcallowip=192.168.0.0/16",
                "walletdir=wallet",
                "",
            ]
        ),
        encoding="utf-8",
    )
    _log(settings, f"Created default config at {conf}")


def run_cli(settings: Settings, *args: str, timeout: float = 30) -> subprocess.CompletedProcess[str]:
    cli = settings.btx_cli_path()
    if not cli.is_file():
        raise NodeError(f"btx-cli not found at {cli}. Install node binaries from the Updates tab.")
    ensure_conf(settings)
    cmd = [
        str(cli),
        f"-datadir={settings.resolved_datadir()}",
        f"-conf={settings.conf_path()}",
        *args,
    ]
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        raise NodeError(f"btx-cli timed out after {timeout}s") from exc


def btx_cli(settings: Settings, *args: str, timeout: float = 30) -> str:
    result = run_cli(settings, *args, timeout=timeout)
    if result.returncode != 0:
        raise NodeError((result.stderr or result.stdout or "btx-cli failed").strip())
    return (result.stdout or "").strip()


def process_running(settings: Settings) -> bool:
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq btxd.exe", "/NH"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = result.stdout or ""
    return "btxd.exe" in output and "No tasks are running" not in output


def start_node(settings: Settings) -> str:
    btxd = settings.btxd_path()
    if not btxd.is_file():
        raise NodeError(f"btxd.exe not found at {btxd}. Install node binaries from the Updates tab.")
    if process_running(settings):
        try:
            btx_cli(settings, "getblockchaininfo", timeout=10)
            return "Node already running and RPC is up."
        except NodeError:
            pass
    ensure_conf(settings)
    settings.resolved_datadir().mkdir(parents=True, exist_ok=True)
    cmd = [
        str(btxd),
        f"-datadir={settings.resolved_datadir()}",
        f"-conf={settings.conf_path()}",
        "-daemon",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise NodeError((result.stderr or result.stdout or "btxd failed to start").strip())
    _log(settings, "Started btxd")
    for _ in range(30):
        if not process_running(settings):
            time.sleep(1)
            continue
        try:
            btx_cli(settings, "getblockchaininfo", timeout=5)
            return "Node started."
        except NodeError:
            time.sleep(1)
    return "btxd launched; waiting for RPC…"


def stop_node(settings: Settings, timeout: float = 120) -> str:
    if not process_running(settings):
        return "Node already stopped."
    try:
        run_cli(settings, "stop", timeout=30)
    except NodeError as exc:
        raise NodeError(f"Failed to stop node: {exc}") from exc
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not process_running(settings):
            _log(settings, "Stopped btxd")
            return "Node stopped cleanly."
        time.sleep(1)
    raise NodeError("btxd still running after stop request.")


def tail_log(path: Path, lines: int = 80) -> str:
    if not path.is_file():
        return "(log file not found)"
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return "".join(deque(handle, maxlen=lines)).strip() or "(empty)"
    except OSError as exc:
        return str(exc)


def health_summary(settings: Settings) -> str:
    running = process_running(settings)
    rpc = "no"
    try:
        if running:
            btx_cli(settings, "getblockcount", timeout=10)
            rpc = "yes"
    except NodeError:
        rpc = "no"
    return f"btxd_running: {'yes' if running else 'no'} · rpc_ok: {rpc}"


def lan_rpc_hint(settings: Settings) -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            host_ip = sock.getsockname()[0]
    except OSError:
        host_ip = "127.0.0.1"
    return f"http://{host_ip}:{settings.rpc_port}"
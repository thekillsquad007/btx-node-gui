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


_PRUNED_DEFAULTS: dict[str, str] = {
    "server": "1",
    "listen": "1",
    "daemon": "1",
    "prune": "4096",
    "rpcuser": "miner",
    "rpcpassword": "miner",
    "rpcbind": "0.0.0.0",
    "rpcallowip": "127.0.0.1",
    "walletdir": "wallet",
}


def _parse_conf_lines(text: str) -> tuple[list[str], dict[str, str]]:
    lines = text.splitlines()
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    return lines, values


def ensure_pruned_conf(settings: Settings) -> None:
    """Always run the node pruned — create or patch btx.conf accordingly."""
    settings.resolved_datadir().mkdir(parents=True, exist_ok=True)
    conf = settings.conf_path()
    prune_value = str(settings.prune_target)

    defaults = dict(_PRUNED_DEFAULTS)
    defaults["prune"] = prune_value
    defaults["rpcport"] = str(settings.rpc_port)

    if not conf.is_file():
        extra_allow = ["rpcallowip=172.16.0.0/12", "rpcallowip=192.168.0.0/16"]
        body = [f"{key}={value}" for key, value in defaults.items()] + extra_allow + [""]
        conf.write_text("\n".join(body), encoding="utf-8")
        _log(settings, f"Created pruned node config at {conf}")
        return

    text = conf.read_text(encoding="utf-8")
    lines, values = _parse_conf_lines(text)
    changed = False

    for key, value in defaults.items():
        if values.get(key) != value:
            values[key] = value
            changed = True

    if values.get("prune") == "0" or values.get("prune", "").lower() in {"", "false"}:
        values["prune"] = prune_value
        changed = True

    for forbidden in ("txindex",):
        if values.get(forbidden) == "1":
            values[forbidden] = "0"
            changed = True

    allow_ips = {"127.0.0.1", "172.16.0.0/12", "192.168.0.0/16"}
    existing_allow = {v for k, v in values.items() if k == "rpcallowip"}
    for ip in allow_ips:
        if ip not in existing_allow:
            lines.append(f"rpcallowip={ip}")
            changed = True

    if changed:
        preserved = []
        seen_keys = set(defaults) | {"rpcallowip"}
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                preserved.append(line)
                continue
            key = stripped.split("=", 1)[0].strip()
            if key in seen_keys:
                continue
            preserved.append(line)
        merged = preserved + [f"{key}={values[key]}" for key in defaults] + [
            "rpcallowip=127.0.0.1",
            "rpcallowip=172.16.0.0/12",
            "rpcallowip=192.168.0.0/16",
            "",
        ]
        conf.write_text("\n".join(merged), encoding="utf-8")
        _log(settings, f"Updated config to pruned mode (prune={prune_value})")


def ensure_conf(settings: Settings) -> None:
    ensure_pruned_conf(settings)


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


def start_node(settings: Settings, log_cb=None) -> str:
    btxd = settings.btxd_path()
    if not btxd.is_file():
        raise NodeError(f"btxd.exe not found at {btxd}. Install node binaries from the Updates tab.")
    if process_running(settings):
        try:
            btx_cli(settings, "getblockchaininfo", timeout=10)
            return "Node already running and RPC is up."
        except NodeError:
            pass

    ensure_pruned_conf(settings)
    settings.resolved_datadir().mkdir(parents=True, exist_ok=True)

    from .snapshots import chainstate_needs_bootstrap, download_snapshots, snapshot_status

    if settings.auto_download_snapshots:
        snap = snapshot_status(settings)
        if not snap.ready:
            download_snapshots(settings, log_cb=log_cb)

    if chainstate_needs_bootstrap(settings):
        from .snapshots import bootstrap_from_snapshot

        return bootstrap_from_snapshot(settings, log_cb=log_cb)

    cmd = [
        str(btxd),
        f"-datadir={settings.resolved_datadir()}",
        f"-conf={settings.conf_path()}",
        f"-prune={settings.prune_target}",
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
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .installer import installed_version as binary_installed_version
from .native import NodeError, btx_cli, process_running
from .settings import Settings


@dataclass
class NodeStatus:
    running: bool
    rpc_ok: bool
    synced: bool
    blocks: int
    headers: int
    progress: float
    peers: int
    ibd: bool
    version: str
    prune_height: int | None
    error: str = ""

    @property
    def summary(self) -> str:
        if self.error:
            return self.error
        if not self.running:
            return "Node stopped"
        if self.ibd:
            return f"Syncing {self.blocks:,} / {self.headers:,} ({self.progress:.1f}%)"
        return f"Synced at block {self.blocks:,} · {self.peers} peers"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def fetch_status(settings: Settings) -> NodeStatus:
    running = process_running(settings)
    if not settings.btxd_path().is_file():
        return NodeStatus(
            running=False,
            rpc_ok=False,
            synced=False,
            blocks=0,
            headers=0,
            progress=0.0,
            peers=0,
            ibd=True,
            version="",
            prune_height=None,
            error="Node binaries not installed — use Updates → Install latest build",
        )
    try:
        info = json.loads(btx_cli(settings, "getblockchaininfo", timeout=15))
        net = json.loads(btx_cli(settings, "getnetworkinfo", timeout=15))
        rpc_ok = True
    except (NodeError, json.JSONDecodeError) as exc:
        return NodeStatus(
            running=running,
            rpc_ok=False,
            synced=False,
            blocks=0,
            headers=0,
            progress=0.0,
            peers=0,
            ibd=True,
            version="",
            prune_height=None,
            error=str(exc),
        )

    ibd = bool(info.get("initialblockdownload", True))
    progress = float(info.get("verificationprogress", 0.0)) * 100.0
    return NodeStatus(
        running=running,
        rpc_ok=True,
        synced=not ibd,
        blocks=_safe_int(info.get("blocks")),
        headers=_safe_int(info.get("headers")),
        progress=progress,
        peers=_safe_int(net.get("connections")),
        ibd=ibd,
        version=str(net.get("subversion", "")),
        prune_height=_safe_int(info.get("pruneheight")) if info.get("pruned") else None,
    )


def installed_version(settings: Settings) -> str:
    return binary_installed_version(settings)
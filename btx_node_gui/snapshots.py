from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .native import NodeError, _log, btx_cli, process_running, run_cli, stop_node
from .settings import Settings

SNAPSHOT_FILES = ("snapshot.dat", "snapshot.manifest.json")


@dataclass
class SnapshotStatus:
    dat_file: bool
    manifest_file: bool
    dat_bytes: int
    manifest_height: int | None
    manifest_blockhash: str
    source_tag: str

    @property
    def ready(self) -> bool:
        return self.dat_file and self.manifest_file


def _github_release_assets(repo: str, tag: str | None = None) -> tuple[str, list[dict]]:
    if tag:
        url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    else:
        url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "btx-node-gui"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    return data.get("tag_name", ""), data.get("assets") or []


def _download(url: str, destination: Path, log_cb=None) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if log_cb:
        log_cb(f"Downloading {destination.name} ({url})…")
    tmp = destination.with_suffix(destination.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=600) as resp, tmp.open("wb") as handle:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
        tmp.replace(destination)
    finally:
        tmp.unlink(missing_ok=True)


def _pick_snapshot_source(settings: Settings) -> tuple[str, str, dict[str, dict]]:
    repos = []
    for repo in (settings.github_release_repo, settings.github_btx_repo):
        if repo and repo not in repos:
            repos.append(repo)
    errors: list[str] = []
    for repo in repos:
        try:
            tag, assets = _github_release_assets(repo)
            by_name = {a.get("name", ""): a for a in assets}
            if all(name in by_name for name in SNAPSHOT_FILES):
                return repo, tag, by_name
            missing = [name for name in SNAPSHOT_FILES if name not in by_name]
            errors.append(f"{repo}@{tag} missing {', '.join(missing)}")
        except Exception as exc:
            errors.append(f"{repo}: {exc}")
    raise NodeError("No snapshot assets found. Tried: " + "; ".join(errors))


def download_snapshots(settings: Settings, log_cb=None, force: bool = False) -> str:
    repo, tag, by_name = _pick_snapshot_source(settings)

    datadir = settings.resolved_datadir()
    datadir.mkdir(parents=True, exist_ok=True)
    downloaded: list[str] = []

    for name in SNAPSHOT_FILES:
        dest = datadir / name
        if dest.is_file() and not force:
            continue
        asset = by_name[name]
        _download(asset["browser_download_url"], dest, log_cb=log_cb)
        downloaded.append(name)

    if downloaded:
        _log(settings, f"Downloaded snapshot files from {repo}@{tag}: {', '.join(downloaded)}")
        return f"Downloaded {', '.join(downloaded)} from {repo} release {tag}"
    return f"Snapshots already present (source {repo}@{tag})"


def read_manifest(settings: Settings) -> dict:
    path = settings.resolved_datadir() / "snapshot.manifest.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def snapshot_status(settings: Settings) -> SnapshotStatus:
    datadir = settings.resolved_datadir()
    dat_path = datadir / "snapshot.dat"
    manifest = read_manifest(settings)
    blockhash = str(
        manifest.get("blockhash")
        or manifest.get("base_block_hash")
        or manifest.get("snapshot_blockhash")
        or ""
    )
    height = manifest.get("height")
    try:
        height_val = int(height) if height is not None else None
    except (TypeError, ValueError):
        height_val = None

    tag = ""
    try:
        tag, _ = _github_release_assets(settings.github_btx_repo)
    except Exception:
        tag = "unknown"

    return SnapshotStatus(
        dat_file=dat_path.is_file(),
        manifest_file=(datadir / "snapshot.manifest.json").is_file(),
        dat_bytes=dat_path.stat().st_size if dat_path.is_file() else 0,
        manifest_height=height_val,
        manifest_blockhash=blockhash,
        source_tag=tag,
    )


def chainstate_needs_bootstrap(settings: Settings) -> bool:
    datadir = settings.resolved_datadir()
    blocks = datadir / "blocks"
    chainstate = datadir / "chainstate"
    if not blocks.is_dir() and not chainstate.is_dir():
        return True
    if chainstate.is_dir():
        try:
            size = sum(f.stat().st_size for f in chainstate.rglob("*") if f.is_file())
            if size < 2_000_000:
                return True
        except OSError:
            return True
    return False


def _manifest_blockhash(settings: Settings) -> str:
    manifest = read_manifest(settings)
    for key in ("blockhash", "base_block_hash", "snapshot_blockhash"):
        value = manifest.get(key)
        if value:
            return str(value)
    raise NodeError("snapshot.manifest.json is missing blockhash / base_block_hash")


def _wipe_chain_data(settings: Settings) -> None:
    datadir = settings.resolved_datadir()
    for name in ("blocks", "chainstate", "chainstate_snapshot", "shielded_state", "indexes"):
        path = datadir / name
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)


def _wait_for_rpc(settings: Settings, timeout: int = 120) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not process_running(settings):
            raise NodeError("btxd exited while waiting for RPC")
        try:
            btx_cli(settings, "getblockcount", timeout=10)
            return
        except NodeError:
            time.sleep(2)
    raise NodeError("RPC did not become ready in time")


def _wait_for_header(settings: Settings, blockhash: str, timeout: int = 240) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = run_cli(settings, "getblockheader", blockhash, "false", timeout=30)
        if result.returncode == 0:
            return
        time.sleep(2)
    raise NodeError(f"Snapshot anchor header {blockhash} not reached before timeout")


def bootstrap_from_snapshot(settings: Settings, log_cb=None) -> str:
    def log(msg: str) -> None:
        if log_cb:
            log_cb(msg)
        _log(settings, msg)

    status = snapshot_status(settings)
    if not status.ready:
        log("Snapshots missing — downloading from upstream BTX release…")
        download_snapshots(settings, log_cb=log_cb)

    datadir = settings.resolved_datadir()
    snap_dat = datadir / "snapshot.dat"
    if not snap_dat.is_file():
        raise NodeError("snapshot.dat missing after download")

    if process_running(settings):
        log("Stopping node before snapshot bootstrap…")
        stop_node(settings)

    log("Wiping broken or empty chain data…")
    _wipe_chain_data(settings)

    btxd = settings.btxd_path()
    if not btxd.is_file():
        raise NodeError("btxd.exe not installed")

    from .native import ensure_pruned_conf

    ensure_pruned_conf(settings)

    log("Starting btxd with pruneduringinit=8192 for snapshot load…")
    cmd = [
        str(btxd),
        f"-datadir={datadir}",
        f"-conf={settings.conf_path()}",
        "-pruneduringinit=8192",
        "-daemon",
    ]
    result = subprocess_run(cmd)
    if result.returncode != 0:
        raise NodeError((result.stderr or result.stdout or "btxd failed to start").strip())

    log("Waiting for RPC…")
    _wait_for_rpc(settings)

    blockhash = _manifest_blockhash(settings)
    log(f"Waiting for snapshot anchor header {blockhash[:16]}…")
    _wait_for_header(settings, blockhash)

    log("Loading snapshot via loadtxoutset (this can take a while)…")
    load = run_cli(settings, "-rpcclienttimeout=0", "loadtxoutset", str(snap_dat), timeout=3600)
    if load.returncode != 0:
        raise NodeError((load.stderr or load.stdout or "loadtxoutset failed").strip())

    log("Snapshot loaded — node will sync remaining blocks as a pruned node.")
    return "Snapshot bootstrap complete. Node is syncing to tip in pruned mode."


def subprocess_run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def rebootstrap_from_snapshot(settings: Settings, log_cb=None) -> str:
    return bootstrap_from_snapshot(settings, log_cb=log_cb)
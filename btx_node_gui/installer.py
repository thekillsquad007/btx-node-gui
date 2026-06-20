from __future__ import annotations

import json
import re
import shutil
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .native import NodeError, stop_node
from .settings import Settings


WINDOWS_ARCHIVE_SUFFIX = "-x86_64-w64-mingw32.zip"


@dataclass
class ReleaseAsset:
    tag: str
    version: str
    name: str
    archive_name: str
    download_url: str
    published_at: str


def _parse_version(tag: str) -> str:
    return tag.lstrip("v").removeprefix("node-v")


def _github_get(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "btx-node-gui"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def _pick_windows_asset(assets: list[dict]) -> dict | None:
    for asset in assets:
        name = asset.get("name", "")
        if name.endswith(WINDOWS_ARCHIVE_SUFFIX):
            return asset
    for asset in assets:
        name = asset.get("name", "")
        if name.endswith(".zip") and "w64-mingw32" in name:
            return asset
    return None


def fetch_latest_release(settings: Settings) -> ReleaseAsset:
    repo = settings.github_release_repo
    data = _github_get(f"https://api.github.com/repos/{repo}/releases/latest")
    tag = data.get("tag_name", "")
    asset = _pick_windows_asset(data.get("assets") or [])
    if not asset:
        raise RuntimeError(
            f"No Windows zip found in latest release of {repo}. "
            "Run the 'Build Windows BTX Node' GitHub Action and publish a release first."
        )
    return ReleaseAsset(
        tag=tag,
        version=_parse_version(tag),
        name=data.get("name", tag),
        archive_name=asset["name"],
        download_url=asset["browser_download_url"],
        published_at=data.get("published_at", ""),
    )


def list_releases(settings: Settings, limit: int = 8) -> list[ReleaseAsset]:
    repo = settings.github_release_repo
    data = _github_get(f"https://api.github.com/repos/{repo}/releases?per_page={limit}")
    releases: list[ReleaseAsset] = []
    for entry in data:
        asset = _pick_windows_asset(entry.get("assets") or [])
        if not asset:
            continue
        tag = entry.get("tag_name", "")
        releases.append(
            ReleaseAsset(
                tag=tag,
                version=_parse_version(tag),
                name=entry.get("name", tag),
                archive_name=asset["name"],
                download_url=asset["browser_download_url"],
                published_at=entry.get("published_at", ""),
            )
        )
    return releases


def _download(url: str, destination: Path, log_cb=None) -> None:
    if log_cb:
        log_cb(f"Downloading {destination.name}…")
    with urllib.request.urlopen(url, timeout=600) as resp, destination.open("wb") as handle:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)


def _find_bin_dir(root: Path) -> Path:
    direct = root / "bin"
    if (direct / "btxd.exe").is_file():
        return direct
    for candidate in root.rglob("btxd.exe"):
        return candidate.parent
    raise NodeError(f"No btxd.exe found inside {root}")


def install_release(settings: Settings, release: ReleaseAsset, log_cb=None) -> str:
    def log(msg: str) -> None:
        if log_cb:
            log_cb(msg)

    bin_dir = settings.resolved_bin_dir()
    backup_root = bin_dir.parent / "backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    backup_dir = backup_root / f"gui-{release.version}"
    if bin_dir.is_dir():
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        shutil.copytree(bin_dir, backup_dir, dirs_exist_ok=True)
        log(f"Backed up existing binaries to {backup_dir}")

    try:
        if process_running_safe(settings):
            log("Stopping running node before upgrade…")
            stop_node(settings)
    except NodeError as exc:
        log(f"Warning: could not stop node cleanly: {exc}")

    with tempfile.TemporaryDirectory(prefix="btx-install-") as tmp:
        tmp_path = Path(tmp)
        archive = tmp_path / release.archive_name
        _download(release.download_url, archive, log_cb=log)
        extract_root = tmp_path / "extract"
        extract_root.mkdir()
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(extract_root)
        source_bin = _find_bin_dir(extract_root)
        bin_dir.mkdir(parents=True, exist_ok=True)
        for name in ("btxd.exe", "btx-cli.exe", "btx-util.exe"):
            src = source_bin / name
            if src.is_file():
                shutil.copy2(src, bin_dir / name)
                log(f"Installed {name}")

    from .native import ensure_pruned_conf
    from .snapshots import download_snapshots

    ensure_pruned_conf(settings)
    log(f"Node will run pruned with prune={settings.prune_target}")
    if settings.auto_download_snapshots:
        try:
            snap_msg = download_snapshots(settings, log_cb=log)
            log(snap_msg)
        except Exception as exc:
            log(f"Warning: snapshot download failed: {exc}")

    version_out = settings.btxd_path()
    if not version_out.is_file():
        raise NodeError("Install finished but btxd.exe is missing.")
    return f"Installed {release.tag} into {bin_dir} (pruned mode, prune={settings.prune_target})"


def process_running_safe(settings: Settings) -> bool:
    from .native import process_running

    return process_running(settings)


def compare_versions(current: str, latest: str) -> int:
    def parts(text: str) -> list[int]:
        nums = re.findall(r"\d+", text)
        return [int(n) for n in nums[:3]] + [0, 0, 0]

    cur = parts(current)
    lat = parts(latest)
    for a, b in zip(cur, lat):
        if a < b:
            return -1
        if a > b:
            return 1
    return 0


def installed_version(settings: Settings) -> str:
    btxd = settings.btxd_path()
    if not btxd.is_file():
        return "not installed"
    result = subprocess_run_version(btxd)
    return result.splitlines()[0] if result else "unknown"


def subprocess_run_version(binary: Path) -> str:
    import subprocess

    proc = subprocess.run(
        [str(binary), "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return (proc.stdout or proc.stderr or "").strip()
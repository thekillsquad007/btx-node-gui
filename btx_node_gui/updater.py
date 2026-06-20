from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass

from .settings import Settings
from .wsl import WslError, run_bash


@dataclass
class ReleaseInfo:
    tag: str
    version: str
    name: str
    tarball_url: str
    published_at: str


def _parse_version(tag: str) -> str:
    return tag.lstrip("v")


def fetch_latest_release(settings: Settings) -> ReleaseInfo:
    url = f"https://api.github.com/repos/{settings.github_repo}/releases/latest"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "btx-node-gui"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode())

    tag = data.get("tag_name", "")
    assets = data.get("assets") or []
    tarball = ""
    for asset in assets:
        name = asset.get("name", "")
        if name.endswith("x86_64-linux-gnu.tar.gz"):
            tarball = asset.get("browser_download_url", "")
            break
    if not tarball:
        raise RuntimeError("No Linux x86_64 tarball found in latest release")

    return ReleaseInfo(
        tag=tag,
        version=_parse_version(tag),
        name=data.get("name", tag),
        tarball_url=tarball,
        published_at=data.get("published_at", ""),
    )


def upgrade_node(settings: Settings, release: ReleaseInfo, log_cb=None) -> str:
    def log(msg: str) -> None:
        if log_cb:
            log_cb(msg)

    version = release.version
    url = release.tarball_url
    bin_dir = settings.btx_bin
    libexec = f"{bin_dir}/../libexec"
    backup = f"{bin_dir}/../backups/gui-{version}"
    tarball = f"/tmp/btx-{version}-x86_64-linux-gnu.tar.gz"

    script = f"""
set -euo pipefail
BIN="{bin_dir}"
LIBEXEC="{libexec}"
BACKUP="{backup}"
TARBALL="{tarball}"
URL="{url}"
mkdir -p "$BACKUP" "$BIN" "$LIBEXEC"
if pgrep -f "btxd.real.*-datadir=" >/dev/null; then
  bash "{settings.pool_scripts}/ensure-btxd.sh" stop
fi
cp -a "$BIN"/* "$BACKUP/" 2>/dev/null || true
mkdir -p "$BACKUP/libexec"
cp -a "$LIBEXEC"/* "$BACKUP/libexec/" 2>/dev/null || true
curl -fsSL -o "$TARBALL" "$URL"
EXTRACT=/tmp/btx-{version}-install
rm -rf "$EXTRACT" && mkdir -p "$EXTRACT"
tar -xzf "$TARBALL" -C "$EXTRACT"
ROOT=$(cd "$(dirname "$(find "$EXTRACT" -name btxd -type f | head -1)")/.." && pwd)
cp -a "$ROOT/bin/btxd" "$ROOT/bin/btx-cli" "$ROOT/bin/btx-util" "$BIN/"
cp -a "$ROOT/libexec/"* "$LIBEXEC/" 2>/dev/null || true
chmod +x "$BIN/btxd" "$BIN/btx-cli" "$BIN/btx-util"
"$BIN/btxd" --version | head -1
echo UPGRADE_OK
"""
    log(f"Downloading {release.tag}...")
    result = run_bash(settings, script, timeout=900)
    output = "\n".join(part for part in [result.stdout, result.stderr] if part).strip()
    if result.returncode != 0 or "UPGRADE_OK" not in output:
        raise WslError(output or "Upgrade failed")
    return output


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
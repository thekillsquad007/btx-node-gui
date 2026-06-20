from __future__ import annotations

from .installer import (
    ReleaseAsset,
    compare_versions,
    fetch_latest_release,
    install_release,
)
from .settings import Settings

__all__ = [
    "ReleaseAsset",
    "compare_versions",
    "fetch_latest_release",
    "upgrade_node",
]


def upgrade_node(settings: Settings, release: ReleaseAsset, log_cb=None) -> str:
    return install_release(settings, release, log_cb=log_cb)
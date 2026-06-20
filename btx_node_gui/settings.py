from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

CONFIG_DIR = Path.home() / ".btx-node-gui"
CONFIG_FILE = CONFIG_DIR / "config.json"

_DEFAULT_LOCAL = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))


def _default_bin_dir() -> str:
    return str(_DEFAULT_LOCAL / "BTX" / "bin")


def _default_datadir() -> str:
    return str(_DEFAULT_LOCAL / "BTX")


@dataclass
class Settings:
    bin_dir: str = ""
    datadir: str = ""
    rpc_port: int = 19334
    refresh_seconds: int = 5
    github_release_repo: str = "thekillsquad007/btx-node-gui"
    pool_folder: str = r"E:\Business\btxpool"

    @classmethod
    def load(cls) -> Settings:
        if not CONFIG_FILE.is_file():
            return cls()
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        cleaned = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        settings = cls(**cleaned)
        # Drop legacy WSL-only config keys silently.
        return settings

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    def resolved_bin_dir(self) -> Path:
        return Path(self.bin_dir or _default_bin_dir())

    def resolved_datadir(self) -> Path:
        return Path(self.datadir or _default_datadir())

    def btxd_path(self) -> Path:
        return self.resolved_bin_dir() / "btxd.exe"

    def btx_cli_path(self) -> Path:
        return self.resolved_bin_dir() / "btx-cli.exe"

    def conf_path(self) -> Path:
        return self.resolved_datadir() / "btx.conf"

    def debug_log_path(self) -> Path:
        return self.resolved_datadir() / "debug.log"

    def manager_log_path(self) -> Path:
        return CONFIG_DIR / "node-manager.log"
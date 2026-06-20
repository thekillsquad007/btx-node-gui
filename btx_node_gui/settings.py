from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

CONFIG_DIR = Path.home() / ".btx-node-gui"
CONFIG_FILE = CONFIG_DIR / "config.json"


@dataclass
class Settings:
    wsl_distro: str = ""
    pool_scripts: str = "/mnt/e/Business/btxpool/scripts"
    btx_bin: str = "/home/aravindthana/.local/btx/bin"
    datadir: str = "/home/aravindthana/.bitcoin"
    rpc_port: int = 19334
    refresh_seconds: int = 5
    github_repo: str = "btxchain/btx"

    @classmethod
    def load(cls) -> Settings:
        if not CONFIG_FILE.is_file():
            return cls()
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
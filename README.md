# BTX Node Manager

Windows GUI for managing a **BTX full/pruned node** running in WSL. Controls `btxd` only — the mining pool stays a separate process.

## What it does

- **Status** — block height, sync progress, peers, RPC health
- **Start / stop** — start opens a dedicated WSL window (safe for long sync/rebootstrap); stop runs cleanly via `btx-cli`
- **Rebootstrap** — snapshot rebuild in its own window (~45–70 min)
- **Logs** — tail `debug.log` and `ensure-btxd.log`
- **Updates** — download latest Linux binaries from GitHub releases and install into WSL

The node itself remains the official Linux `btxd` build inside WSL. This app is a Windows front-end, not a native Windows port of the chain daemon.

## Requirements

- Windows 10/11 with **WSL2** and a Linux distro where BTX is already set up
- Python 3.10+ on Windows (for the GUI only)
- Existing pool scripts at `E:\Business\btxpool` (or adjust paths in Settings)

## Quick start

1. Double-click **`BTX Node Manager.bat`** (creates `.venv` and installs deps on first run).
2. Confirm paths under the **Settings** tab match your WSL layout.
3. Click **Start node** — a separate WSL terminal runs `ensure-btxd.sh ensure`.
4. Wait until status shows **Synced**, then start the pool with `E:\Business\btxpool\start-pool.bat`.

Do **not** use Windows scheduled tasks or the old coupled `supervise-wsl.sh` session for the node.

## Fork / upstream

Node binaries and release metadata come from [btxchain/btx](https://github.com/btxchain/btx). To use your own fork:

1. Fork `btxchain/btx` on GitHub and publish Linux release assets (`*-x86_64-linux-gnu.tar.gz`).
2. In the GUI **Settings**, set **GitHub repo** to `youruser/btx`.
3. Or clone this GUI repo separately and point upgrades at your fork.

This repository is the **Windows manager**; fork it to customize the GUI while keeping node releases on your BTX fork.

## Project layout

```
btx-node-gui/
  BTX Node Manager.bat
  btx_node_gui/
    app.py          # CustomTkinter UI
    wsl.py          # WSL / ensure-btxd bridge
    rpc.py          # btx-cli status
    updater.py      # GitHub release upgrade
    settings.py     # %USERPROFILE%\.btx-node-gui\config.json
```

Config is stored at `%USERPROFILE%\.btx-node-gui\config.json`.

## Development

```bat
cd E:\Business\btx-node-gui
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m btx_node_gui
```
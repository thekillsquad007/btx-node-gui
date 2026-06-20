# BTX Node Manager

Native **Windows** GUI for `btxd`. Binaries are built in **GitHub Actions** — you do not need Visual Studio, CMake, or vcpkg on your PC.

## How it works

| Piece | Where it runs |
|-------|----------------|
| **BTX Node Manager** (this app) | Windows — start/stop, status, logs |
| **btxd / btx-cli** | Windows — downloaded from your fork's GitHub Releases |
| **Mining pool** (optional) | Can stay in WSL — point `rpc_url` at the Windows host IP |

```
GitHub Actions (windows-latest)
    └── builds btxd.exe from btxchain/btx
    └── publishes btx-*-x86_64-w64-mingw32.zip

BTX Node Manager (your PC)
    └── Updates tab → download zip → %LOCALAPPDATA%\BTX\bin
    └── Overview tab → start/stop native btxd
```

## One-time setup

### 1. Fork and push this repo

```bat
cd E:\Business\btx-node-gui
git remote add origin https://github.com/YOURUSER/btx-node-gui.git
git push -u origin master
```

### 2. Trigger the Windows node build on GitHub

1. Open your fork on GitHub → **Actions** → **Build Windows BTX Node** → **Run workflow**
2. Leave defaults (`btxchain/btx` @ `v0.32.12`) or pick another ref
3. Check **Publish release** to create a GitHub Release with the zip (~1–3 hours first run; vcpkg is cached after that)

Or push a tag:

```bat
git tag node-v0.32.12
git push origin node-v0.32.12
```

### 3. Run the GUI

Double-click **`BTX Node Manager.bat`**.

1. **Settings** → set **GitHub repo for CI releases** to `YOURUSER/btx-node-gui`
2. **Updates** → **Check for builds** → **Install / upgrade**
3. **Overview** → **Start node**
4. Wait for **Synced**, then start the pool separately

Config: `%USERPROFILE%\.btx-node-gui\config.json`  
Node datadir: `%LOCALAPPDATA%\BTX\`

## Pool in WSL

Native node's RPC listens on `0.0.0.0:19334`. The Overview tab shows **Pool RPC URL (WSL)** — use that in `btxpool/config.yaml` instead of `127.0.0.1` when the pool runs inside WSL.

## CI workflow

`.github/workflows/build-windows-node.yml`:

- Checks out `btxchain/btx` (or your chosen repo/ref)
- Runs upstream `contrib/devtools/build-btx-windows.ps1` on `windows-latest`
- Packages `btx-<version>-x86_64-w64-mingw32.zip`
- Uploads artifact; publishes release on `node-v*` tags or when **Publish release** is checked

## Development

```bat
cd E:\Business\btx-node-gui
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m btx_node_gui
```
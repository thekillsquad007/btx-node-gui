from __future__ import annotations

import os
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox
from typing import Callable

import customtkinter as ctk

from . import __version__
from .installer import fetch_latest_release, installed_version
from .native import (
    NodeError,
    health_summary,
    lan_rpc_hint,
    start_node,
    stop_node,
    tail_log,
)
from .rpc import NodeStatus, fetch_status
from .settings import Settings
from .updater import compare_versions, upgrade_node


class BtxNodeApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.settings = Settings.load()
        self._refresh_job: str | None = None
        self._busy = False
        self._latest_release = None
        self._last_status = NodeStatus(
            running=False,
            rpc_ok=False,
            synced=False,
            blocks=0,
            headers=0,
            progress=0.0,
            peers=0,
            ibd=True,
            version="",
        )

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("BTX Node Manager")
        self.geometry("940x660")
        self.minsize(800, 540)

        self._build_ui()
        self.after(200, self.refresh_status)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self) -> None:
        if self._refresh_job:
            self.after_cancel(self._refresh_job)
        self.destroy()

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 8))
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(header, text="BTX Node Manager", font=ctk.CTkFont(size=22, weight="bold")).grid(
            row=0, column=0, sticky="w"
        )
        ctk.CTkLabel(
            header,
            text=f"v{__version__}  ·  native Windows node",
            text_color="gray70",
        ).grid(row=1, column=0, sticky="w")

        self.status_badge = ctk.CTkLabel(
            header,
            text="Checking…",
            font=ctk.CTkFont(size=14, weight="bold"),
            corner_radius=8,
            fg_color="#3b3b3b",
            width=180,
            height=36,
        )
        self.status_badge.grid(row=0, column=2, rowspan=2, padx=(12, 0))

        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=1, column=0, sticky="nsew", padx=16, pady=8)
        self.tab_overview = self.tabview.add("Overview")
        self.tab_logs = self.tabview.add("Logs")
        self.tab_updates = self.tabview.add("Updates")
        self.tab_settings = self.tabview.add("Settings")

        self._build_overview()
        self._build_logs()
        self._build_updates()
        self._build_settings()

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 14))
        footer.grid_columnconfigure(0, weight=1)
        self.footer_label = ctk.CTkLabel(footer, text="", text_color="gray60")
        self.footer_label.grid(row=0, column=0, sticky="w")
        ctk.CTkButton(footer, text="Refresh", width=100, command=self.refresh_status).grid(
            row=0, column=1, padx=(8, 0)
        )

    def _build_overview(self) -> None:
        frame = self.tab_overview
        frame.grid_columnconfigure((0, 1), weight=1)

        metrics = ctk.CTkFrame(frame)
        metrics.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=4, pady=4)
        metrics.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.metric_labels: dict[str, ctk.CTkLabel] = {}
        for idx, (key, title) in enumerate(
            [
                ("blocks", "Block height"),
                ("headers", "Headers"),
                ("progress", "Sync progress"),
                ("peers", "Peers"),
            ]
        ):
            box = ctk.CTkFrame(metrics)
            box.grid(row=0, column=idx, sticky="nsew", padx=6, pady=10)
            ctk.CTkLabel(box, text=title, text_color="gray70").pack(anchor="w", padx=12, pady=(10, 0))
            lbl = ctk.CTkLabel(box, text="—", font=ctk.CTkFont(size=20, weight="bold"))
            lbl.pack(anchor="w", padx=12, pady=(0, 12))
            self.metric_labels[key] = lbl

        info = ctk.CTkFrame(frame)
        info.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=4, pady=4)
        info.grid_columnconfigure(1, weight=1)

        self.info_labels: dict[str, ctk.CTkLabel] = {}
        for row, (key, title) in enumerate(
            [
                ("running", "Process"),
                ("rpc", "RPC"),
                ("version", "Version"),
                ("prune", "Prune height"),
                ("summary", "Status"),
                ("health", "Health"),
                ("pool_rpc", "Pool RPC URL (WSL)"),
            ]
        ):
            ctk.CTkLabel(info, text=title, text_color="gray70").grid(row=row, column=0, sticky="w", padx=12, pady=6)
            lbl = ctk.CTkLabel(info, text="—", anchor="w", justify="left")
            lbl.grid(row=row, column=1, sticky="ew", padx=12, pady=6)
            self.info_labels[key] = lbl

        actions = ctk.CTkFrame(frame, fg_color="transparent")
        actions.grid(row=2, column=0, columnspan=2, sticky="ew", padx=4, pady=12)
        for idx, (text, cmd, color) in enumerate(
            [
                ("Start node", self._action_start, "#1f6aa5"),
                ("Stop node", self._action_stop, "#8b3a3a"),
                ("Open datadir", self._open_datadir, "#444444"),
                ("Open pool folder", self._open_pool_folder, "#444444"),
            ]
        ):
            ctk.CTkButton(actions, text=text, command=cmd, fg_color=color, hover_color=color).grid(
                row=0, column=idx, padx=6, sticky="ew"
            )
            actions.grid_columnconfigure(idx, weight=1)

        ctk.CTkLabel(
            frame,
            text=(
                "Binaries are built in GitHub Actions — no Visual Studio on your PC. "
                "Install from the Updates tab, then start the node here. "
                "If the pool still runs in WSL, point its rpc_url at the Pool RPC URL above."
            ),
            text_color="gray60",
            wraplength=860,
            justify="left",
        ).grid(row=3, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 8))

    def _build_logs(self) -> None:
        frame = self.tab_logs
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        bar = ctk.CTkFrame(frame, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", pady=(4, 8))
        ctk.CTkButton(bar, text="Refresh logs", command=self._refresh_logs).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="debug.log", command=lambda: self._show_log("debug")).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="manager.log", command=lambda: self._show_log("manager")).pack(side="left", padx=4)

        self.log_text = ctk.CTkTextbox(frame, font=ctk.CTkFont(family="Consolas", size=12))
        self.log_text.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        self._active_log = "debug"

    def _build_updates(self) -> None:
        frame = self.tab_updates
        frame.grid_columnconfigure(0, weight=1)

        self.update_current = ctk.CTkLabel(frame, text="Installed: checking…", anchor="w")
        self.update_current.grid(row=0, column=0, sticky="ew", padx=8, pady=8)

        self.update_latest = ctk.CTkLabel(frame, text="Latest CI build: not checked", anchor="w")
        self.update_latest.grid(row=1, column=0, sticky="ew", padx=8, pady=8)

        self.update_hint = ctk.CTkLabel(
            frame,
            text="Downloads Windows btxd.exe from your GitHub fork's releases (built by Actions).",
            text_color="gray60",
            anchor="w",
            wraplength=860,
            justify="left",
        )
        self.update_hint.grid(row=2, column=0, sticky="ew", padx=8, pady=4)

        btns = ctk.CTkFrame(frame, fg_color="transparent")
        btns.grid(row=3, column=0, sticky="w", padx=8, pady=8)
        ctk.CTkButton(btns, text="Check for builds", command=self._check_updates).pack(side="left", padx=4)
        self.install_btn = ctk.CTkButton(
            btns, text="Install / upgrade", command=self._action_install, state="disabled"
        )
        self.install_btn.pack(side="left", padx=4)

        self.update_log = ctk.CTkTextbox(frame, height=240, font=ctk.CTkFont(family="Consolas", size=12))
        self.update_log.grid(row=4, column=0, sticky="nsew", padx=8, pady=8)
        frame.grid_rowconfigure(4, weight=1)

    def _build_settings(self) -> None:
        frame = self.tab_settings
        frame.grid_columnconfigure(1, weight=1)

        fields = [
            ("bin_dir", "btx binaries folder", self.settings.resolved_bin_dir()),
            ("datadir", "Node datadir", self.settings.resolved_datadir()),
            ("github_release_repo", "GitHub repo for CI releases (owner/name)", self.settings.github_release_repo),
            ("pool_folder", "Pool folder (Windows path)", self.settings.pool_folder),
        ]
        self.setting_entries: dict[str, ctk.CTkEntry] = {}
        for row, (key, label, default) in enumerate(fields):
            ctk.CTkLabel(frame, text=label, anchor="w").grid(row=row, column=0, sticky="w", padx=12, pady=8)
            entry = ctk.CTkEntry(frame, width=460)
            entry.insert(0, str(getattr(self.settings, key) or default))
            entry.grid(row=row, column=1, sticky="ew", padx=12, pady=8)
            self.setting_entries[key] = entry

        ctk.CTkLabel(frame, text="Refresh interval (seconds)").grid(
            row=len(fields), column=0, sticky="w", padx=12, pady=8
        )
        self.refresh_entry = ctk.CTkEntry(frame, width=120)
        self.refresh_entry.insert(0, str(self.settings.refresh_seconds))
        self.refresh_entry.grid(row=len(fields), column=1, sticky="w", padx=12, pady=8)

        ctk.CTkButton(frame, text="Save settings", command=self._save_settings).grid(
            row=len(fields) + 1, column=1, sticky="w", padx=12, pady=16
        )

    def _run_async(self, work: Callable[[], None], on_done: Callable[[], None] | None = None) -> None:
        if self._busy:
            return

        def runner() -> None:
            self._busy = True
            try:
                work()
            finally:
                self._busy = False
                if on_done:
                    self.after(0, on_done)

        threading.Thread(target=runner, daemon=True).start()

    def refresh_status(self) -> None:
        def work() -> None:
            status = fetch_status(self.settings)
            health = health_summary(self.settings)
            version = installed_version(self.settings)
            pool_rpc = lan_rpc_hint(self.settings)
            self.after(0, lambda: self._apply_status(status, health, version, pool_rpc))

        self._run_async(work, on_done=self._schedule_refresh)

    def _schedule_refresh(self) -> None:
        if self._refresh_job:
            self.after_cancel(self._refresh_job)
        delay = max(3, self.settings.refresh_seconds) * 1000
        self._refresh_job = self.after(delay, self.refresh_status)

    def _apply_status(
        self,
        status: NodeStatus,
        health: str,
        version: str,
        pool_rpc: str,
    ) -> None:
        self._last_status = status
        self.metric_labels["blocks"].configure(text=f"{status.blocks:,}")
        self.metric_labels["headers"].configure(text=f"{status.headers:,}")
        self.metric_labels["progress"].configure(text=f"{status.progress:.1f}%")
        self.metric_labels["peers"].configure(text=str(status.peers))

        self.info_labels["running"].configure(text="Running" if status.running else "Stopped")
        self.info_labels["rpc"].configure(text="OK" if status.rpc_ok else "Unavailable")
        self.info_labels["version"].configure(text=version or status.version or "—")
        prune = str(status.prune_height) if status.prune_height is not None else "—"
        self.info_labels["prune"].configure(text=prune)
        self.info_labels["summary"].configure(text=status.summary)
        self.info_labels["health"].configure(text=health)
        self.info_labels["pool_rpc"].configure(text=pool_rpc)

        badge_text, badge_color = self._badge_for(status)
        self.status_badge.configure(text=badge_text, fg_color=badge_color)
        self.footer_label.configure(
            text=f"Last refresh: block {status.blocks:,} · RPC {'up' if status.rpc_ok else 'down'}"
        )

        if self.tabview.get() == "Logs" and self._active_log == "debug":
            self._set_log_text(tail_log(self.settings.debug_log_path()))

    def _badge_for(self, status: NodeStatus) -> tuple[str, str]:
        if "not installed" in status.error.lower():
            return "No binaries", "#5c4a1e"
        if status.error and not status.running:
            return "Error", "#6b2c2c"
        if not status.running:
            return "Stopped", "#4a4a4a"
        if status.rpc_ok and status.synced:
            return "Synced", "#1f6f46"
        if status.running:
            return "Syncing", "#7a5c1e"
        return "Unknown", "#3b3b3b"

    def _action_start(self) -> None:
        def work() -> None:
            try:
                msg = start_node(self.settings)
                self.after(0, lambda: messagebox.showinfo("Node", msg))
            except NodeError as exc:
                self.after(0, lambda: messagebox.showerror("Start failed", str(exc)))
            finally:
                self.after(0, self.refresh_status)

        self._run_async(work)

    def _action_stop(self) -> None:
        if not messagebox.askyesno("Stop node", "Stop btxd cleanly via btx-cli?"):
            return

        def work() -> None:
            try:
                msg = stop_node(self.settings)
                self.after(0, lambda: messagebox.showinfo("Node stopped", msg))
            except NodeError as exc:
                self.after(0, lambda: messagebox.showerror("Stop failed", str(exc)))
            finally:
                self.after(0, self.refresh_status)

        self._run_async(work)

    def _open_datadir(self) -> None:
        path = self.settings.resolved_datadir()
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(path)

    def _open_pool_folder(self) -> None:
        path = self.settings.pool_folder
        if os.path.isdir(path):
            subprocess.Popen(["explorer", path])

    def _show_log(self, kind: str) -> None:
        self._active_log = kind
        if kind == "manager":
            text = tail_log(self.settings.manager_log_path())
        else:
            text = tail_log(self.settings.debug_log_path())
        self._set_log_text(text)

    def _set_log_text(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.insert("1.0", text)
        self.log_text.configure(state="disabled")
        self.log_text.see(tk.END)

    def _refresh_logs(self) -> None:
        self._show_log(self._active_log)

    def _check_updates(self) -> None:
        def work() -> None:
            current = installed_version(self.settings)
            try:
                release = fetch_latest_release(self.settings)
                cmp = compare_versions(current, release.version)
                can_install = current == "not installed" or cmp < 0 or current == "unknown"
                latest_text = f"Latest CI build: {release.tag} ({release.archive_name})"
                self._latest_release = release
            except Exception as exc:
                release = None
                can_install = current == "not installed"
                latest_text = f"Check failed: {exc}"

            def done() -> None:
                self.update_current.configure(text=f"Installed: {current}")
                self.update_latest.configure(text=latest_text)
                self.install_btn.configure(state="normal" if can_install and release else "disabled")

            self.after(0, done)

        self._run_async(work)

    def _action_install(self) -> None:
        if not self._latest_release:
            messagebox.showwarning("Install", "Check for builds first.")
            return
        release = self._latest_release
        if not messagebox.askyesno(
            "Install node",
            f"Install {release.tag} from GitHub CI?\n\n"
            f"Archive: {release.archive_name}\n"
            f"Target: {self.settings.resolved_bin_dir()}",
        ):
            return

        def log_cb(msg: str) -> None:
            self.after(0, lambda: self._append_update_log(msg))

        def work() -> None:
            self.after(0, lambda: self._append_update_log("Installing…"))
            try:
                output = upgrade_node(self.settings, release, log_cb=log_cb)
                self.after(0, lambda: self._append_update_log(output))
                self.after(0, lambda: messagebox.showinfo("Install complete", output))
            except Exception as exc:
                self.after(0, lambda: self._append_update_log(str(exc)))
                self.after(0, lambda: messagebox.showerror("Install failed", str(exc)))
            finally:
                self.after(0, self._check_updates)
                self.after(0, self.refresh_status)

        self._run_async(work)

    def _append_update_log(self, line: str) -> None:
        self.update_log.configure(state="normal")
        self.update_log.insert(tk.END, line + "\n")
        self.update_log.configure(state="disabled")
        self.update_log.see(tk.END)

    def _save_settings(self) -> None:
        for key, entry in self.setting_entries.items():
            setattr(self.settings, key, entry.get().strip())
        try:
            self.settings.refresh_seconds = max(3, int(self.refresh_entry.get().strip()))
        except ValueError:
            messagebox.showerror("Settings", "Refresh interval must be a number.")
            return
        self.settings.save()
        messagebox.showinfo("Settings", "Saved.")
        self.refresh_status()


def main() -> None:
    app = BtxNodeApp()
    app.mainloop()
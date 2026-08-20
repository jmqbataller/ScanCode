from __future__ import annotations

import time
from pathlib import Path
import tkinter as tk

import cv2

import scancode_app_v50_runtime as runtime
from scancode_core import pending_bundles, waybill_crop
from scancode_v5_services import best_frame

APP_VERSION = "5.0.0"
runtime.APP_VERSION = APP_VERSION


class ScanCodeApp(runtime.ScanCodeApp):
    """Thread-safe final production entrypoint for ScanCode v5."""

    def __init__(self, root: tk.Tk, start_services: bool = True):
        self._suppress_parent_prebuffer = False
        self._protected_snapshot = None
        super().__init__(root, start_services=start_services)
        self.supervisor_locked = bool(self.settings.get("supervisor_lock", False))
        self._capture_protected_settings()

    def _capture_protected_settings(self):
        try:
            self._protected_snapshot = {
                "camera_mode": self.mode_var.get(),
                "camera_index": self.camera_var.get(),
                "network_url": self.network_var.get(),
                "server_folder": self.server_var.get(),
                "auto_sync": bool(self.auto_sync_var.get()),
                "auto_start": bool(self.auto_start_var.get()),
                "bigseller_url": self.bigseller_var.get(),
                "retention_days": self.retention_var.get(),
            }
        except Exception:
            self._protected_snapshot = None

    def _restore_protected_settings(self):
        p = self._protected_snapshot or {}
        try:
            self.mode_var.set(p.get("camera_mode", self.mode_var.get()))
            self.camera_var.set(str(p.get("camera_index", self.camera_var.get())))
            self.network_var.set(p.get("network_url", self.network_var.get()))
            self.server_var.set(p.get("server_folder", self.server_var.get()))
            self.auto_sync_var.set(bool(p.get("auto_sync", self.auto_sync_var.get())))
            self.auto_start_var.set(bool(p.get("auto_start", self.auto_start_var.get())))
            self.bigseller_var.set(p.get("bigseller_url", self.bigseller_var.get()))
            self.retention_var.set(str(p.get("retention_days", self.retention_var.get())))
        except Exception:
            pass

    def save_settings(self):
        if self._protected_snapshot is not None and self.supervisor_locked:
            self._restore_protected_settings()
        result = super().save_settings()
        if not self.supervisor_locked:
            self._capture_protected_settings()
        return result

    def toggle_supervisor(self):
        result = super().toggle_supervisor()
        self.supervisor_locked = bool(self.settings.get("supervisor_lock", self.supervisor_locked))
        if not self.supervisor_locked:
            self._capture_protected_settings()
        return result

    def _decode_buffer_frames(self):
        if self._suppress_parent_prebuffer:
            return []
        return runtime.ScanCodeApp._decode_buffer_frames(self)

    def submit_scan_target(self, code):
        # accept_scan creates the video session first, then the v5 evidence row.
        # Wait briefly so a very fast BigSeller automation cannot update a row
        # that has not been inserted yet.
        deadline = time.time() + 0.8
        while hasattr(self, "db") and not self.db.exists(code) and time.time() < deadline:
            time.sleep(0.02)
        target = str(self.settings.get("scan_target") or "BigSeller")
        if target == "BigSeller":
            return self.submit_bigseller(code)
        return self.submit_active_app(code)

    def accept_scan(self, raw_code):
        # Decode pre-record frames once before parent processing. Suppress the
        # older unlocked injection in the feature layer, then inject under the
        # session lock so VideoWriter is never written from two threads at once.
        preframes = runtime.ScanCodeApp._decode_buffer_frames(self)
        self._suppress_parent_prebuffer = True
        try:
            result = super().accept_scan(raw_code)
        finally:
            self._suppress_parent_prebuffer = False

        session = self.current_session
        if not session:
            return result

        if preframes:
            with self.sessions_lock:
                for frame in preframes:
                    try:
                        session.write(frame)
                    except Exception:
                        break

            if self.settings.get("best_waybill_shot", True):
                best = best_frame(preframes[-30:])
                if best is not None:
                    try:
                        zoom = float(self.settings.get("scanner_zoom", 1.35) or 1.35)
                        cv2.imwrite(str(session.waybill_path), waybill_crop(best, zoom))
                    except Exception:
                        pass

            if hasattr(self, "db"):
                self.db.event(session.code, "PREBUFFER_INJECTED", f"{len(preframes)} compressed history frames")
                self.db.event(session.code, "BEST_WAYBILL_SELECTED", "Sharpest buffered frame selected")
        return result

    def _bundle_needs_sync(self, meta: Path):
        if not hasattr(self, "db"):
            return True
        row = self.db.get(meta.stem)
        return not row or row.get("sync_status") != "SYNCED"

    def one_sync(self):
        server = Path(self.server_var.get().strip()) if self.server_var.get().strip() else None
        if not server or not server.exists():
            return self.events.put(("sync", ("SERVER OFFLINE", "Server not reachable", len(pending_bundles(self.local_root)))))
        copied = 0
        pending = 0
        for meta, video, waybill in pending_bundles(self.local_root):
            if not self._bundle_needs_sync(meta):
                continue
            pending += 1
            try:
                self._copy_bundle_keep_local(meta, video, waybill, server)
                copied += 1
            except Exception as exc:
                self.events.put(("error", str(exc)))
                break
        self.events.put(("sync", ("SERVER ONLINE", f"Verified {copied} new bundle(s); local retention enabled", max(0, pending - copied))))

    def sync_worker(self):
        while not self.sync_stop.is_set():
            try:
                bundles = pending_bundles(self.local_root)
                server = Path(self.settings.get("server_folder") or "") if self.settings.get("server_folder") else None
                unsynced = [(m, v, w) for m, v, w in bundles if self._bundle_needs_sync(m)]
                if not server:
                    self.events.put(("sync", ("SERVER NOT SET", "Configure server folder", len(unsynced))))
                elif not server.exists():
                    self.events.put(("sync", ("SERVER OFFLINE", "Files remain local", len(unsynced))))
                elif not self.settings.get("auto_sync", True):
                    self.events.put(("sync", ("SYNC OFF", "Auto Sync disabled", len(unsynced))))
                else:
                    remaining = len(unsynced)
                    for meta, video, waybill in unsynced:
                        if self.sync_stop.is_set():
                            break
                        try:
                            self._copy_bundle_keep_local(meta, video, waybill, server)
                            remaining -= 1
                        except Exception as exc:
                            self.events.put(("error", f"Sync failed: {exc}"))
                            break
                    self.events.put(("sync", ("SERVER ONLINE", "Verified copy retained locally", max(0, remaining))))
            except Exception as exc:
                self.events.put(("error", f"Server sync error: {exc}"))
            self.sync_stop.wait(15)


def main():
    root = tk.Tk()
    ScanCodeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

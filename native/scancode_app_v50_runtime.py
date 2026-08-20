from __future__ import annotations

import json
import os
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np
import tkinter as tk

import scancode_app_v46 as v46
import scancode_app_v50 as v50
from scancode_v5_services import patch_metadata

APP_VERSION = "5.0.0"
v50.APP_VERSION = APP_VERSION


class ScanCodeApp(v50.ScanCodeApp):
    """Final v5 runtime with v4.6 compatibility fixes and live counters."""

    def __init__(self, root: tk.Tk, start_services: bool = True):
        self._last_buffer_sample = 0.0
        super().__init__(root, start_services=start_services)
        self.root.after(1200, self._ops_tick)

    def load_settings(self):
        data = super().load_settings()
        raw = {}
        try:
            if self.settings_path.exists():
                raw = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except Exception:
            raw = {}

        # v4.6 only knew Near/Far and would coerce Auto to Near. Restore the
        # explicit v5 choice after the inherited migration has completed.
        raw_focus = raw.get("waybill_focus_mode")
        if raw_focus in {"Auto", "Near", "Far"}:
            data["waybill_focus_mode"] = raw_focus
        elif "waybill_focus_mode" not in raw:
            data["waybill_focus_mode"] = "Auto"

        # One-time production migration: existing v4.x installs may have Active
        # App saved as their target. V5 is specifically the packing + BigSeller
        # workstation, so first v5 launch moves to BigSeller once. The marker is
        # then retained; if the operator later chooses Active App and saves, that
        # explicit choice is respected on future launches.
        if not bool(raw.get("v5_bigseller_target_migrated", False)):
            data["scan_target"] = "BigSeller"
            data["v5_bigseller_target_migrated"] = True
        return data

    def save_settings(self):
        super().save_settings()
        try:
            mode = self.waybill_focus_mode_var.get() or "Auto"
            if mode not in {"Auto", "Near", "Far"}:
                mode = "Auto"
            self.settings["waybill_focus_mode"] = mode
            self.settings["v5_bigseller_target_migrated"] = True
            if self.settings.get("waybill_focus", True):
                if mode == "Far":
                    self.settings["scanner_zoom"] = 2.15
                elif mode == "Near":
                    self.settings["scanner_zoom"] = 1.35
                else:
                    self.settings["scanner_zoom"] = 1.35
            self.settings_path.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
        except Exception:
            pass

    def build_side(self):
        super().build_side()
        panel = self.panel(self.side)
        self.label(panel, "LIVE PACKING SCORECARD", 8, True, v50.base_app.MUTED).pack(anchor="w", padx=14, pady=(10, 3))
        self.ops_counter = self.label(panel, "Packed 0 • Submitted 0 • Rate 0/hr", 9, True, v50.base_app.TEXT)
        self.ops_counter.pack(anchor="w", padx=14, pady=(0, 10))

    def write_sessions(self, frame, fps):
        try:
            seconds = max(0, min(10, int(self.settings.get("pre_record_seconds", 5) or 5)))
            max_items = max(1, seconds * 8)
            if self._frame_buffer.maxlen != max_items:
                self._frame_buffer = deque(self._frame_buffer, maxlen=max_items)
            now = time.time()
            if seconds and now - self._last_buffer_sample >= 0.125:
                self._last_buffer_sample = now
                h, w = frame.shape[:2]
                scale = min(1.0, 1280.0 / max(1, w))
                small = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else frame
                ok, buf = cv2.imencode(".jpg", small, [int(cv2.IMWRITE_JPEG_QUALITY), 68])
                if ok:
                    self._frame_buffer.append(buf.tobytes())
        except Exception:
            pass
        return v46.ScanCodeApp.write_sessions(self, frame, fps)

    def _decode_buffer_frames(self):
        frames = []
        target_size = None
        try:
            with self.frame_lock:
                if self.latest_frame is not None:
                    h, w = self.latest_frame.shape[:2]
                    target_size = (w, h)
        except Exception:
            pass
        for raw in list(self._frame_buffer):
            try:
                arr = np.frombuffer(raw, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is not None:
                    if target_size and (frame.shape[1], frame.shape[0]) != target_size:
                        frame = cv2.resize(frame, target_size, interpolation=cv2.INTER_LINEAR)
                    frames.append(frame)
            except Exception:
                pass
        return frames

    def finalize_session(self, session):
        result = super().finalize_session(session)
        self._refresh_quality(session.code)
        return result

    def submit_bigseller(self, code):
        result = super().submit_bigseller(code)
        self._refresh_quality(code)
        return result

    def _refresh_quality(self, code):
        if not hasattr(self, "db"):
            return
        row = self.db.get(code)
        if not row or not row.get("ended_at"):
            return
        min_sec = int(self.settings.get("minimum_record_seconds", 3) or 3)
        status = str(row.get("bigseller_status") or "PENDING")
        checks = {
            "waybill_scanned": bool(row.get("code")),
            "video_recorded": bool(row.get("video_path") and Path(row.get("video_path")).exists()),
            "minimum_duration": int(row.get("duration_ms") or 0) >= min_sec * 1000,
            "waybill_photo": bool(row.get("waybill_path") and Path(row.get("waybill_path")).exists()),
            "bigseller_submitted": status in {"SUBMITTED", "VERIFIED"},
        }
        quality = "PASS" if all(checks.values()) else "REVIEW"
        self.db.update_status(code, quality_status=quality)
        meta = Path(row.get("metadata_path") or "")
        if meta.exists():
            patch_metadata(meta, packingQuality=quality, packingChecks=checks, bigSellerStatus=status)
        self.db.event(code, "QUALITY_CHECK", quality)

    def _ops_tick(self):
        try:
            if hasattr(self, "db") and hasattr(self, "ops_counter"):
                stats24 = self.db.dashboard(24)
                stats1 = self.db.dashboard(1)
                queue_count = self.submit_queue.count() if hasattr(self, "submit_queue") else 0
                self.ops_counter.configure(
                    text=f"Packed {stats24['total']} • Submitted {stats24['submitted']} • Rate {stats1['total']}/hr • Queue {queue_count}"
                )
        except Exception:
            pass
        self.root.after(2500, self._ops_tick)

    def open_history_item(self):
        try:
            sel = self.history.curselection()
            if sel and hasattr(self, "db"):
                text = self.history.get(sel[0])
                parts = text.split()
                code = parts[1] if len(parts) > 1 else ""
                row = self.db.get(code)
                if row:
                    local = Path(row.get("video_path") or "")
                    if local.exists() and os.name == "nt":
                        os.startfile(str(local))
                        return
                    server = Path(self.settings.get("server_folder") or "")
                    if server.exists():
                        stamp = time.localtime(float(row.get("started_at") or 0))
                        server_file = server / time.strftime("%Y-%m-%d", stamp) / local.name
                        if server_file.exists() and os.name == "nt":
                            os.startfile(str(server_file))
                            return
        except Exception:
            pass
        return super().open_history_item()

    def _maintenance_worker(self):
        while not self._cleanup_stop.wait(3600):
            if not self.settings.get("auto_cleanup", True) or not hasattr(self, "db"):
                continue
            try:
                from scancode_v5_services import cleanup_verified
                days = max(1, int(self.settings.get("retention_days", 14) or 14))
                cleanup_verified(self.db.search("", 10000), days)
            except Exception:
                pass


def main():
    root = tk.Tk()
    ScanCodeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

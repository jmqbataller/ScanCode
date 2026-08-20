from __future__ import annotations

import time
import tkinter as tk

import cv2

import scancode_app_v50_runtime as runtime
from scancode_core import waybill_crop
from scancode_v5_services import best_frame

APP_VERSION = "5.0.0"
runtime.APP_VERSION = APP_VERSION


class ScanCodeApp(runtime.ScanCodeApp):
    """Thread-safe final production entrypoint for ScanCode v5."""

    def __init__(self, root: tk.Tk, start_services: bool = True):
        self._suppress_parent_prebuffer = False
        super().__init__(root, start_services=start_services)

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


def main():
    root = tk.Tk()
    ScanCodeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

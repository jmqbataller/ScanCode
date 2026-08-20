from __future__ import annotations

import os
import time
import tkinter as tk

import scancode_app as base_app
import scancode_app_v50_final as v50
from scancode_v5_services import detect_courier, normalize_code

APP_VERSION = "5.0.1"
v50.APP_VERSION = APP_VERSION


class ScanCodeApp(v50.ScanCodeApp):
    """v5.0.1: restore reliable scan -> text -> paste -> submit behavior."""

    def _foreground_is_bigseller(self):
        try:
            info = self._foreground_window_info()
            title = str((info or {}).get("title") or "").lower()
            return bool(info and "bigseller" in title), info
        except Exception:
            return False, None

    def _paste_to_focused_bigseller(self, code):
        """Fast keyboard-emulation path used when BigSeller already has focus.

        This intentionally mirrors a physical barcode scanner: the decoded text is
        copied to the clipboard, the focused input is selected, then the configured
        suffix key (Enter/Tab/None) is sent.
        """
        clean = normalize_code(code)
        base_app.pyperclip.copy(clean)
        if os.name != "nt" or base_app.send_keys is None:
            return False, "Windows keyboard automation unavailable"

        is_bigseller, info = self._foreground_is_bigseller()
        if not is_bigseller:
            return False, "BigSeller is not the foreground window"

        try:
            # Replace any stale tracking number in the currently focused field.
            base_app.send_keys("^a", pause=.015)
            base_app.send_keys(self._output_keys(), pause=.025)
            title = (info or {}).get("title") or "BigSeller"
            return True, f"Pasted and submitted to focused BigSeller window: {title}"
        except Exception as exc:
            return False, str(exc)

    def submit_scan_target(self, code):
        # Preserve Active App behavior, but make BigSeller the production default.
        deadline = time.time() + 0.8
        while hasattr(self, "db") and not self.db.exists(code) and time.time() < deadline:
            time.sleep(0.02)
        target = str(self.settings.get("scan_target") or "BigSeller")
        if target == "BigSeller":
            return self.submit_bigseller(code)
        return self.submit_active_app(code)

    def submit_bigseller(self, code):
        clean = normalize_code(code)
        courier = detect_courier(clean)

        # Stage the queue/evidence state first so every scan remains traceable.
        if hasattr(self, "submit_queue"):
            self.submit_queue.enqueue(clean, courier)
            self.submit_queue.update(clean, "SUBMITTING", increment_attempt=True)
        if hasattr(self, "db"):
            self.db.event(clean, "BIGSELLER_ATTEMPT", "Foreground paste / UI Automation fallback")
            row = self.db.get(clean) or {}
            self.db.update_status(
                clean,
                bigseller_status="SUBMITTING",
                bigseller_attempts=int(row.get("bigseller_attempts") or 0) + 1,
            )

        # 1) Preferred fast path: if operator already has BigSeller focused, behave
        # exactly like a hardware scanner and paste + Enter immediately.
        ok, detail = self._paste_to_focused_bigseller(clean)
        if ok:
            status = "PENDING_VERIFY" if self.settings.get("bigseller_verify", True) else "SUBMITTED"
            self._last_submission_status[clean] = status
            if hasattr(self, "submit_queue"):
                self.submit_queue.update(clean, status)
            if hasattr(self, "db"):
                self.db.update_status(clean, bigseller_status=status)
                self.db.event(clean, "BIGSELLER_" + status, detail)
            self.events.put(("bigseller", f"AUTO PASTE+SUBMIT: {clean} — {detail}"))
            self._feedback("submitted")
            return

        # 2) Fallback to the v5 UI-Automation locator. This can focus BigSeller and
        # find its tracking edit when the operator is working in another window.
        win = self._find_bigseller_window()
        if not win:
            return self._submission_failed(clean, "BigSeller is not open. Scan held in retry queue.")

        base_app.pyperclip.copy(clean)
        if base_app.Desktop is None or base_app.send_keys is None:
            return self._submission_failed(clean, "Windows UI Automation unavailable")

        try:
            win.set_focus()
            target = self._choose_bigseller_input(win)
            if target:
                target.click_input()
                base_app.send_keys("^a", pause=.015)
                base_app.send_keys(self._output_keys(), pause=.025)
                status, verify_detail = self._verify_bigseller(win, target, clean)
                self._last_submission_status[clean] = status
                if hasattr(self, "submit_queue"):
                    self.submit_queue.update(clean, status)
                if hasattr(self, "db"):
                    self.db.update_status(clean, bigseller_status=status)
                    self.db.event(clean, "BIGSELLER_" + status, verify_detail)
                self.events.put(("bigseller", f"BigSeller {status}: {clean} — {verify_detail}"))
                self._feedback("submitted" if status in {"SUBMITTED", "VERIFIED"} else "warning")
                return

            # 3) Last-resort fallback: if BigSeller is now foreground but its input
            # isn't exposed to UI Automation, send the scan to the currently focused
            # control instead of silently losing the old paste behavior.
            time.sleep(.08)
            ok, fallback_detail = self._paste_to_focused_bigseller(clean)
            if ok:
                status = "PENDING_VERIFY"
                self._last_submission_status[clean] = status
                if hasattr(self, "submit_queue"):
                    self.submit_queue.update(clean, status)
                if hasattr(self, "db"):
                    self.db.update_status(clean, bigseller_status=status)
                    self.db.event(clean, "BIGSELLER_PENDING_VERIFY", fallback_detail)
                self.events.put(("bigseller", f"AUTO PASTE+SUBMIT FALLBACK: {clean} — {fallback_detail}"))
                self._feedback("submitted")
                return

            return self._submission_failed(clean, "BigSeller input is not focused/exposed; click the scan field once and rescan.")
        except Exception as exc:
            return self._submission_failed(clean, str(exc))


def main():
    root = tk.Tk()
    ScanCodeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

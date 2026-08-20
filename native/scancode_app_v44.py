from __future__ import annotations

import json
import os
import tkinter as tk

import scancode_app as base

APP_VERSION = "4.4.0"
base.APP_VERSION = APP_VERSION


class ScanCodeApp(base.ScanCodeApp):
    """v4.4 production runtime: v4.3 camera/recording + Active App scan output."""

    def __init__(self, root: tk.Tk, start_services: bool = True):
        # Exists before base build_ui() runs because combo_row() injects this
        # option while the base Station/Scanner panel is being created.
        self.active_app_enter_var = tk.BooleanVar(master=root, value=True)
        super().__init__(root, start_services=start_services)

    def defaults(self):
        data = super().defaults()
        data.update({
            "scan_target": "Active App",
            "active_app_enter": True,
        })
        return data

    def load_settings(self):
        data = super().load_settings()
        # Seamless migration from v4.2/v4.3 where Notepad Test was the default.
        if data.get("scan_target") == "Notepad Test":
            data["scan_target"] = "Active App"
        data.setdefault("active_app_enter", True)
        return data

    def save_settings(self):
        super().save_settings()
        self.settings["scan_target"] = self.target_var.get() or "Active App"
        self.settings["active_app_enter"] = bool(self.active_app_enter_var.get())
        try:
            self.settings_path.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
        except Exception:
            pass

    def combo_row(self, parent, label, variable, values):
        if label == "Scan output target":
            super().combo_row(parent, label, variable, ["Active App", "BigSeller"])
            self.check(parent, "Press Enter after paste", self.active_app_enter_var)
            tk.Label(
                parent,
                text="Active App: focus any textbox, cell, browser field, ERP/WMS field, or desktop app. Accepted QR/barcode scans paste there automatically.",
                bg=base.PANEL,
                fg=base.MUTED,
                font=("Segoe UI", 8),
                wraplength=285,
                justify="left",
            ).pack(anchor="w", padx=14, pady=(3, 5))
            return
        return super().combo_row(parent, label, variable, values)

    def build_side(self):
        super().build_side()
        if hasattr(self, "bigseller_status"):
            self.bigseller_status.configure(text="Scan output: Active App")
        self._replace_legacy_notepad_copy(self.side)

    def _replace_legacy_notepad_copy(self, widget):
        try:
            if isinstance(widget, tk.Label):
                text = str(widget.cget("text") or "")
                if "Use Notepad Test while validating scans" in text:
                    widget.configure(
                        text="Use Active App for any focused Windows input. Choose BigSeller only for the dedicated BigSeller bridge."
                    )
            for child in widget.winfo_children():
                self._replace_legacy_notepad_copy(child)
        except Exception:
            pass

    def apply_settings_to_ui(self):
        super().apply_settings_to_ui()
        target = self.settings.get("scan_target", "Active App")
        if target == "Notepad Test":
            target = "Active App"
        self.target_var.set(target)
        self.active_app_enter_var.set(bool(self.settings.get("active_app_enter", True)))

    def submit_scan_target(self, code):
        # Called from a worker thread after an accepted QR/barcode. Read the
        # plain settings dict instead of tkinter variables for thread safety.
        target = str(self.settings.get("scan_target") or "Active App")
        if target == "Notepad Test":
            target = "Active App"
        if target == "BigSeller":
            return self.submit_bigseller(code)
        return self.submit_active_app(code)

    def _foreground_window_info(self):
        if os.name != "nt":
            return None
        try:
            import ctypes

            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return None

            pid = ctypes.c_ulong(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            length = int(user32.GetWindowTextLengthW(hwnd))
            title_buf = ctypes.create_unicode_buffer(max(1, length + 1))
            user32.GetWindowTextW(hwnd, title_buf, len(title_buf))
            return {
                "hwnd": int(hwnd),
                "pid": int(pid.value),
                "title": title_buf.value.strip(),
            }
        except Exception:
            return None

    def submit_active_app(self, code):
        clean = str(code or "").strip()
        if not clean:
            return

        # Clipboard paste preserves the barcode exactly and works across normal
        # Windows text inputs, spreadsheets, browsers, ERP/WMS apps, etc.
        base.pyperclip.copy(clean)

        if os.name != "nt" or base.send_keys is None:
            return self.events.put(("bigseller", f"Copied {clean}. Focus the target app and paste manually."))

        try:
            target = self._foreground_window_info()
            if not target:
                return self.events.put(("bigseller", f"Copied {clean}; no active Windows target was detected."))

            # Never inject the scan into ScanCode's own controls.
            if int(target.get("pid") or 0) == os.getpid():
                return self.events.put(("bigseller", f"Copied {clean}; focus another app/input before scanning."))

            press_enter = bool(self.settings.get("active_app_enter", True))
            base.send_keys("^v{ENTER}" if press_enter else "^v", pause=.02)

            title = target.get("title") or "active app"
            suffix = " + Enter" if press_enter else ""
            self.events.put(("bigseller", f"Pasted {clean} → {title}{suffix}."))
        except Exception as exc:
            self.events.put(("bigseller", f"Copied {clean}; active-app paste failed: {exc}"))

    # Old integrations may still call this name.
    def submit_notepad(self, code):
        return self.submit_active_app(code)


def main():
    root = tk.Tk()
    ScanCodeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

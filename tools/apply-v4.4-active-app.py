from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "native" / "scancode_app.py"
text = APP.read_text(encoding="utf-8")


def must_replace(old: str, new: str, label: str):
    global text
    if old not in text:
        raise RuntimeError(f"Patch anchor not found: {label}")
    text = text.replace(old, new, 1)


must_replace('APP_VERSION = "4.3.0"', 'APP_VERSION = "4.4.0"', 'version')

must_replace(
'''            "bigseller_auto": True,\n            "scan_target": "Notepad Test",\n''',
'''            "bigseller_auto": True,\n            "scan_target": "Active App",\n            "active_app_enter": True,\n''',
'default active app target')

must_replace(
'''            "bigseller_auto": bool(self.bigseller_auto_var.get()),\n            "scan_target": self.target_var.get() or "Notepad Test",\n''',
'''            "bigseller_auto": bool(self.bigseller_auto_var.get()),\n            "scan_target": self.target_var.get() or "Active App",\n            "active_app_enter": bool(self.active_app_enter_var.get()),\n''',
'save active app settings')

must_replace(
'''        self.confirm_var = tk.StringVar(); self.filter_var = tk.StringVar(); self.overlap_var = tk.StringVar(value="0")\n        self.target_var = tk.StringVar()\n        self.combo_row(settings, "Scan confirmation", self.confirm_var, ["1","2","3"])\n        self.combo_row(settings, "Barcode filter", self.filter_var, ["shipping","qr","all"])\n        self.combo_row(settings, "Scan output target", self.target_var, ["Notepad Test","BigSeller"])\n        tk.Label(settings, text="Next accepted scan instantly closes the previous parcel video and starts the new parcel.", bg=PANEL, fg=MUTED, font=("Segoe UI",8), wraplength=285, justify="left").pack(anchor="w", padx=14, pady=(4,6))\n''',
'''        self.confirm_var = tk.StringVar(); self.filter_var = tk.StringVar(); self.overlap_var = tk.StringVar(value="0")\n        self.target_var = tk.StringVar(); self.active_app_enter_var = tk.BooleanVar(value=True)\n        self.combo_row(settings, "Scan confirmation", self.confirm_var, ["1","2","3"])\n        self.combo_row(settings, "Barcode filter", self.filter_var, ["shipping","qr","all"])\n        self.combo_row(settings, "Scan output target", self.target_var, ["Active App","BigSeller"])\n        self.check(settings, "Press Enter after paste", self.active_app_enter_var)\n        tk.Label(settings, text="Active App: focus any text box, cell, browser field, or desktop app. Accepted QR/barcode scans paste there automatically.", bg=PANEL, fg=MUTED, font=("Segoe UI",8), wraplength=285, justify="left").pack(anchor="w", padx=14, pady=(4,4))\n        tk.Label(settings, text="Next accepted scan instantly closes the previous parcel video and starts the new parcel.", bg=PANEL, fg=MUTED, font=("Segoe UI",8), wraplength=285, justify="left").pack(anchor="w", padx=14, pady=(0,6))\n''',
'active app target UI')

must_replace(
'''        tk.Label(big, text="Choose BigSeller in Scan output target for production. Use Notepad Test while validating scans.", bg=PANEL, fg=MUTED, font=("Segoe UI",8), wraplength=285, justify="left").pack(anchor="w", padx=14, pady=(4,6))\n''',
'''        tk.Label(big, text="Use Active App for any focused Windows input. Choose BigSeller only when you want the dedicated BigSeller UI Automation bridge.", bg=PANEL, fg=MUTED, font=("Segoe UI",8), wraplength=285, justify="left").pack(anchor="w", padx=14, pady=(4,6))\n''',
'BigSeller guidance')

must_replace(
'''        self.bigseller_status = self.label(big, "Scan output: Notepad Test", 8, False, MUTED); self.bigseller_status.pack(anchor="w", padx=14, pady=(0,10))\n''',
'''        self.bigseller_status = self.label(big, "Scan output: Active App", 8, False, MUTED); self.bigseller_status.pack(anchor="w", padx=14, pady=(0,10))\n''',
'output status label')

old_apply = '''        self.sound_var.set(s["sound"]);self.quality_var.set(s["quality"]);self.server_var.set(s["server_folder"]);self.auto_sync_var.set(s["auto_sync"]);self.auto_start_var.set(s["auto_start"]);self.bigseller_var.set(s["bigseller_url"]);self.bigseller_auto_var.set(s["bigseller_auto"]);self.target_var.set(s.get("scan_target","Notepad Test"));self.overlap_var.set("0")\n'''
new_apply = '''        self.sound_var.set(s["sound"]);self.quality_var.set(s["quality"]);self.server_var.set(s["server_folder"]);self.auto_sync_var.set(s["auto_sync"]);self.auto_start_var.set(s["auto_start"]);self.bigseller_var.set(s["bigseller_url"]);self.bigseller_auto_var.set(s["bigseller_auto"])\n        target=s.get("scan_target","Active App")\n        if target=="Notepad Test":target="Active App"\n        self.target_var.set(target);self.active_app_enter_var.set(bool(s.get("active_app_enter",True)));self.overlap_var.set("0")\n'''
must_replace(old_apply, new_apply, 'apply active app settings')

start = text.find('    def submit_scan_target(self, code):\n')
end = text.find('    def open_bigseller(self):\n', start)
if start < 0 or end < 0:
    raise RuntimeError('Scan target method block not found')

new_methods = '''    def submit_scan_target(self, code):\n        # This runs on a worker thread after an accepted QR/barcode scan. Read\n        # plain settings instead of tkinter variables so scan output is thread-safe.\n        target = str(self.settings.get("scan_target") or "Active App")\n        if target == "Notepad Test":\n            target = "Active App"\n        if target == "BigSeller":\n            return self.submit_bigseller(code)\n        return self.submit_active_app(code)\n\n    def _foreground_window_info(self):\n        if os.name != "nt":\n            return None\n        try:\n            import ctypes\n            user32 = ctypes.windll.user32\n            hwnd = user32.GetForegroundWindow()\n            if not hwnd:\n                return None\n            pid = ctypes.c_ulong(0)\n            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))\n            length = int(user32.GetWindowTextLengthW(hwnd))\n            title_buf = ctypes.create_unicode_buffer(max(1, length + 1))\n            user32.GetWindowTextW(hwnd, title_buf, len(title_buf))\n            return {"hwnd": int(hwnd), "pid": int(pid.value), "title": title_buf.value.strip()}\n        except Exception:\n            return None\n\n    def submit_active_app(self, code):\n        clean = str(code or "").strip()\n        if not clean:\n            return\n\n        # Clipboard paste is more reliable than typing barcode characters one by\n        # one and works with Notepad, Excel, browsers, ERP/WMS fields, etc.\n        pyperclip.copy(clean)\n\n        if os.name != "nt" or send_keys is None:\n            return self.events.put(("bigseller", f"Copied {clean}. Focus the target app and paste manually."))\n\n        try:\n            target = self._foreground_window_info()\n            if not target:\n                return self.events.put(("bigseller", f"Copied {clean}; no active Windows target was detected."))\n\n            # Never paste into ScanCode itself. Keep ScanCode in the background\n            # and focus the textbox/cell/input in the app that should receive scans.\n            if int(target.get("pid") or 0) == os.getpid():\n                return self.events.put(("bigseller", f"Copied {clean}; focus another app/input before scanning."))\n\n            keys = "^v{ENTER}" if bool(self.settings.get("active_app_enter", True)) else "^v"\n            send_keys(keys, pause=.02)\n            title = target.get("title") or "active app"\n            suffix = " + Enter" if bool(self.settings.get("active_app_enter", True)) else ""\n            self.events.put(("bigseller", f"Pasted {clean} → {title}{suffix}."))\n        except Exception as exc:\n            self.events.put(("bigseller", f"Copied {clean}; active-app paste failed: {exc}"))\n\n    # Backward-compatible alias for old v4.2/v4.3 settings or integrations.\n    def submit_notepad(self, code):\n        return self.submit_active_app(code)\n\n'''
text = text[:start] + new_methods + text[end:]

APP.write_text(text, encoding="utf-8")
print('Applied ScanCode v4.4 Active App output: QR/barcode -> clipboard -> focused Windows app, optional Enter.')

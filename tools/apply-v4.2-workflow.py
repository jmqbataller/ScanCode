from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
app_path = ROOT / 'native' / 'scancode_app.py'
text = app_path.read_text(encoding='utf-8')


def must_replace(old, new, label):
    global text
    if old not in text:
        raise RuntimeError(f'Patch anchor not found: {label}')
    text = text.replace(old, new, 1)


must_replace('import queue\nimport sys', 'import queue\nimport subprocess\nimport sys', 'subprocess import')
must_replace('APP_VERSION = "4.1.0"', 'APP_VERSION = "4.2.0"', 'version')

must_replace(
'''        self.preview_photo = None\n\n        recovered = recover_recordings(self.local_root)''',
'''        self.preview_photo = None\n        # Master workflow state: camera may stay live, but barcode automation and\n        # parcel recording are disabled until the operator presses Start.\n        self.system_running = False\n        self.system_paused = False\n\n        recovered = recover_recordings(self.local_root)''',
'master system state')

must_replace('            "overlap_ms": 900,', '            "overlap_ms": 0,', 'instant parcel cut default')
must_replace('            "bigseller_url": "",\n            "bigseller_auto": True,', '            "bigseller_url": "",\n            "bigseller_auto": True,\n            "scan_target": "Notepad Test",', 'scan target default')

must_replace(
'''            "bigseller_url": self.bigseller_var.get().strip(),\n            "bigseller_auto": bool(self.bigseller_auto_var.get()),''',
'''            "bigseller_url": self.bigseller_var.get().strip(),\n            "bigseller_auto": bool(self.bigseller_auto_var.get()),\n            "scan_target": self.target_var.get() or "Notepad Test",''',
'save scan target')

must_replace('        self.record_badge = self.make_badge(badges, "NOT RECORDING")', '        self.record_badge = self.make_badge(badges, "SYSTEM STOPPED")', 'system badge')
must_replace('        self.transport_status = self.label(transport, "Waiting for scan", 9, True, MUTED)', '        self.transport_status = self.label(transport, "System stopped • press Start", 9, True, MUTED)', 'initial transport status')

must_replace(
'''        self.confirm_var = tk.StringVar(); self.filter_var = tk.StringVar(); self.overlap_var = tk.StringVar()\n        self.combo_row(settings, "Scan confirmation", self.confirm_var, ["1","2","3"])\n        self.combo_row(settings, "Barcode filter", self.filter_var, ["shipping","qr","all"])\n        self.combo_row(settings, "Overlap ms", self.overlap_var, ["500","900","1500","2000"])''',
'''        self.confirm_var = tk.StringVar(); self.filter_var = tk.StringVar(); self.overlap_var = tk.StringVar(value="0")\n        self.target_var = tk.StringVar()\n        self.combo_row(settings, "Scan confirmation", self.confirm_var, ["1","2","3"])\n        self.combo_row(settings, "Barcode filter", self.filter_var, ["shipping","qr","all"])\n        self.combo_row(settings, "Scan output target", self.target_var, ["Notepad Test","BigSeller"])\n        tk.Label(settings, text="Next accepted scan instantly closes the previous parcel video and starts the new parcel.", bg=PANEL, fg=MUTED, font=("Segoe UI",8), wraplength=285, justify="left").pack(anchor="w", padx=14, pady=(4,6))''',
'scanner target UI')

must_replace(
'''        self.bigseller_var = tk.StringVar(); self.bigseller_auto_var = tk.BooleanVar()\n        self.entry_row(big, "Page URL", self.bigseller_var)\n        self.check(big, "Auto-submit scanned code", self.bigseller_auto_var)\n        self.button(big, "Open BigSeller", self.open_bigseller).pack(fill="x", padx=14, pady=(4,6))''',
'''        self.bigseller_var = tk.StringVar(); self.bigseller_auto_var = tk.BooleanVar()\n        self.entry_row(big, "Page URL", self.bigseller_var)\n        tk.Label(big, text="Choose BigSeller in Scan output target for production. Use Notepad Test while validating scans.", bg=PANEL, fg=MUTED, font=("Segoe UI",8), wraplength=285, justify="left").pack(anchor="w", padx=14, pady=(4,6))\n        self.button(big, "Open BigSeller", self.open_bigseller).pack(fill="x", padx=14, pady=(4,6))''',
'BigSeller target guidance')

must_replace(
'''        self.sound_var.set(s["sound"]);self.quality_var.set(s["quality"]);self.server_var.set(s["server_folder"]);self.auto_sync_var.set(s["auto_sync"]);self.auto_start_var.set(s["auto_start"]);self.bigseller_var.set(s["bigseller_url"]);self.bigseller_auto_var.set(s["bigseller_auto"])''',
'''        self.sound_var.set(s["sound"]);self.quality_var.set(s["quality"]);self.server_var.set(s["server_folder"]);self.auto_sync_var.set(s["auto_sync"]);self.auto_start_var.set(s["auto_start"]);self.bigseller_var.set(s["bigseller_url"]);self.bigseller_auto_var.set(s["bigseller_auto"]);self.target_var.set(s.get("scan_target","Notepad Test"));self.overlap_var.set("0")''',
'apply scan target')

must_replace(
'''    def handle_barcode(self,code,fmt):\n        now=time.time();needed=max(1,int(self.confirm_var.get() or 2))''',
'''    def handle_barcode(self,code,fmt):\n        # Camera preview remains live, but the scanner is intentionally gated by\n        # Start/Stop so opening ScanCode cannot accidentally submit a parcel.\n        if not self.system_running or self.system_paused:\n            return\n        now=time.time();needed=max(1,int(self.confirm_var.get() or 2))''',
'barcode system gate')

start = text.index('    def accept_scan(self,raw_code):')
end = text.index('    def manual_scan(self):', start)
new_accept = '''    def accept_scan(self,raw_code):\n        if not self.system_running:\n            return self.toast("Press Start first.")\n        if self.system_paused:\n            return self.toast("System is paused. Press Resume first.")\n\n        code = str(raw_code).strip()\n        if len(code) < 3:\n            return\n        now = time.time()\n        if self.current_session and self.current_session.code == code:\n            return\n        if self.last_accepted["code"] == code and now - self.last_accepted["at"] < 1.4:\n            return\n\n        with self.frame_lock:\n            frame = None if self.latest_frame is None else self.latest_frame.copy()\n        if frame is None:\n            return self.toast("Camera frame not ready.")\n\n        self.last_accepted = {"code": code, "at": now}\n\n        old = None\n        with self.sessions_lock:\n            old = self.current_session\n            self.current_session = None\n            if old in self.ending_sessions:\n                self.ending_sessions.remove(old)\n        if old:\n            old.stop_at = time.time()\n            self.finalize_session(old)\n\n        day = self.local_root / day_name()\n        day.mkdir(parents=True, exist_ok=True)\n        base = unique_base(day, code)\n        h, w = frame.shape[:2]\n        fps = 25.0\n        if self.capture:\n            v = float(self.capture.get(cv2.CAP_PROP_FPS) or 25)\n            fps = v if 5 <= v <= 60 else 25\n\n        try:\n            new = ParcelSession(code, base, day, w, h, fps, self.station_var.get().strip() or "Station 01", self.operator_var.get().strip())\n        except Exception as exc:\n            return self.toast(str(exc))\n\n        crop = waybill_crop(frame, float(self.scanner_zoom_var.get() or 1.75))\n        cv2.imwrite(str(new.waybill_path), crop)\n        with self.sessions_lock:\n            self.current_session = new\n\n        self.current_code.configure(text=code)\n        self.detail_status.configure(text="RECORDING", fg=RED)\n        self.transport_status.configure(text=f"System active • Recording {code}", fg=TEXT)\n        self.video_border.configure(bg=RED)\n        self.set_badge(self.record_badge, "● RECORDING", "bad")\n        self.update_transport_controls()\n\n        if self.sound_var.get() and winsound:\n            threading.Thread(target=lambda: (winsound.Beep(880,70), winsound.Beep(1180,80)), daemon=True).start()\n\n        threading.Thread(target=self.submit_scan_target, args=(code,), daemon=True).start()\n\n'''
text = text[:start] + new_accept + text[end:]

must_replace(
'''    def manual_scan(self):\n        code=self.manual_var.get().strip()\n        if code:self.manual_var.set("");self.accept_scan(code)''',
'''    def manual_scan(self):\n        if not self.system_running:\n            return self.toast("Press Start first.")\n        code=self.manual_var.get().strip()\n        if code:self.manual_var.set("");self.accept_scan(code)''',
'manual scan system gate')

start = text.index('    def update_transport_controls(self):')
end = text.index('    def finalize_session(self,s):', start)
new_controls = '''    def update_transport_controls(self):\n        if not hasattr(self, "start_stop_btn"):\n            return\n        if not self.system_running:\n            self.start_stop_btn.configure(text="Start", bg=RED, activebackground=DARK_RED, state="normal")\n            self.pause_resume_btn.configure(text="Pause", state="disabled", disabledforeground=MUTED)\n            return\n\n        self.start_stop_btn.configure(text="Stop", bg=RED, activebackground=DARK_RED, state="normal")\n        self.pause_resume_btn.configure(\n            text="Resume" if self.system_paused else "Pause",\n            state="normal",\n            bg=PANEL2,\n            activebackground="#24242b",\n        )\n\n    def start_stop(self):\n        if not self.system_running:\n            self.system_running = True\n            self.system_paused = False\n            self.scan_candidate = {"code": None, "count": 0, "at": 0.0}\n            self.transport_status.configure(text="System active • waiting for QR/barcode", fg=GREEN)\n            self.set_badge(self.record_badge, "SYSTEM READY", "good")\n            self.update_transport_controls()\n            self.toast("ScanCode started. Scanner is active.")\n            return\n        self.stop_system()\n\n    def start_resume(self):\n        self.start_stop()\n\n    def pause_resume(self):\n        if not self.system_running:\n            return self.toast("Press Start first.")\n        self.system_paused = not self.system_paused\n        with self.sessions_lock:\n            if self.current_session:\n                self.current_session.paused = self.system_paused\n\n        if self.system_paused:\n            self.set_badge(self.record_badge, "SYSTEM PAUSED", "warn")\n            self.transport_status.configure(text="System paused • scanning and recording paused", fg=AMBER)\n        else:\n            if self.current_session:\n                self.set_badge(self.record_badge, "● RECORDING", "bad")\n                self.transport_status.configure(text=f"System active • Recording {self.current_session.code}", fg=TEXT)\n            else:\n                self.set_badge(self.record_badge, "SYSTEM READY", "good")\n                self.transport_status.configure(text="System active • waiting for QR/barcode", fg=GREEN)\n        self.update_transport_controls()\n\n    def stop_system(self):\n        self.system_running = False\n        self.system_paused = False\n        old = None\n        with self.sessions_lock:\n            old = self.current_session\n            self.current_session = None\n        if old:\n            old.stop_at = time.time()\n            self.finalize_session(old)\n\n        self.current_code.configure(text="Waiting for scan")\n        self.detail_status.configure(text="IDLE", fg=MUTED)\n        self.transport_status.configure(text="System stopped • press Start", fg=MUTED)\n        self.video_border.configure(bg=BORDER)\n        self.set_badge(self.record_badge, "SYSTEM STOPPED", "neutral")\n        self.update_transport_controls()\n        self.toast("ScanCode stopped.")\n\n    def stop_recording(self):\n        self.stop_system()\n\n'''
text = text[:start] + new_controls + text[end:]

anchor = '    def open_bigseller(self):\n'
if anchor not in text:
    raise RuntimeError('open_bigseller anchor missing')
new_target_methods = '''    def submit_scan_target(self, code):\n        target = self.target_var.get() or "Notepad Test"\n        if target == "BigSeller":\n            return self.submit_bigseller(code)\n        return self.submit_notepad(code)\n\n    def submit_notepad(self, code):\n        pyperclip.copy(code)\n        if Desktop is None or send_keys is None:\n            return self.events.put(("bigseller", f"TEST: copied {code}; UI Automation unavailable."))\n        try:\n            def find_notepad():\n                return [w for w in Desktop(backend="uia").windows()\n                        if "notepad" in (w.window_text() or "").lower() and w.is_visible()]\n\n            wins = find_notepad()\n            if not wins:\n                subprocess.Popen(["notepad.exe"])\n                deadline = time.time() + 4.0\n                while time.time() < deadline and not wins:\n                    time.sleep(.2)\n                    wins = find_notepad()\n            if not wins:\n                return self.events.put(("bigseller", f"TEST: copied {code}; could not open Notepad."))\n\n            win = wins[0]\n            win.set_focus()\n            time.sleep(.08)\n            send_keys("^v{ENTER}", pause=.03)\n            self.events.put(("bigseller", f"TEST OK: pasted {code} to Notepad."))\n        except Exception as exc:\n            self.events.put(("bigseller", f"TEST: copied {code}; Notepad paste failed: {exc}"))\n\n'''
text = text.replace(anchor, new_target_methods + anchor, 1)

must_replace('        self.bigseller_status = self.label(big, "UI Automation beta", 8, False, MUTED); self.bigseller_status.pack(anchor="w", padx=14, pady=(0,10))', '        self.bigseller_status = self.label(big, "Scan output: Notepad Test", 8, False, MUTED); self.bigseller_status.pack(anchor="w", padx=14, pady=(0,10))', 'target status label')

app_path.write_text(text, encoding='utf-8')
print('Applied ScanCode v4.2 warehouse workflow: Start gate, Notepad/BigSeller paste, instant parcel cutover.')

import os
import queue

import scancode_app as appmod


def main():
    app = appmod.ScanCodeApp.__new__(appmod.ScanCodeApp)
    app.settings = {"scan_target": "Active App", "active_app_enter": True}
    app.events = queue.Queue()

    copied = []
    sent = []
    old_copy = appmod.pyperclip.copy
    old_send = appmod.send_keys

    try:
        appmod.pyperclip.copy = lambda value: copied.append(value)
        appmod.send_keys = lambda keys, pause=.0: sent.append((keys, pause))
        app._foreground_window_info = lambda: {
            "hwnd": 101,
            "pid": os.getpid() + 500,
            "title": "Fake Warehouse App",
        }

        app.submit_scan_target("QR-ABC-123")
        assert copied[-1] == "QR-ABC-123", copied
        assert sent[-1][0] == "^v{ENTER}", sent
        kind, status = app.events.get_nowait()
        assert kind == "bigseller"
        assert "Fake Warehouse App" in status

        app.settings["active_app_enter"] = False
        app.submit_scan_target("BARCODE-456")
        assert copied[-1] == "BARCODE-456"
        assert sent[-1][0] == "^v", sent
        app.events.get_nowait()

        # ScanCode must never paste into its own focused window.
        before = len(sent)
        app._foreground_window_info = lambda: {
            "hwnd": 202,
            "pid": os.getpid(),
            "title": "ScanCode",
        }
        app.submit_scan_target("SELF-BLOCK")
        assert copied[-1] == "SELF-BLOCK"
        assert len(sent) == before, sent
        kind, status = app.events.get_nowait()
        assert "focus another app/input" in status.lower(), status

        # Old saved Notepad Test setting migrates logically to Active App.
        app.settings["scan_target"] = "Notepad Test"
        app._foreground_window_info = lambda: {
            "hwnd": 303,
            "pid": os.getpid() + 700,
            "title": "Legacy Target",
        }
        app.submit_scan_target("LEGACY-789")
        assert sent[-1][0] == "^v", sent

    finally:
        appmod.pyperclip.copy = old_copy
        appmod.send_keys = old_send

    print("ACTIVE APP V4.4 PASS: scan -> clipboard -> foreground app, optional Enter, self-paste protection, legacy migration.")


if __name__ == "__main__":
    main()

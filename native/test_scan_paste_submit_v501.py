import os

import scancode_app as base_app
import scancode_app_v501 as appmod


class FakeClipboard:
    value = None

    @classmethod
    def copy(cls, value):
        cls.value = value


def main():
    app = appmod.ScanCodeApp.__new__(appmod.ScanCodeApp)
    app.settings = {"output_action": "Enter", "bigseller_verify": True}

    original_copy = base_app.pyperclip.copy
    original_send = base_app.send_keys
    original_os_name = appmod.os.name
    calls = []
    try:
        base_app.pyperclip.copy = FakeClipboard.copy
        base_app.send_keys = lambda keys, pause=0: calls.append(keys)
        appmod.os.name = "nt"
        app._foreground_window_info = lambda: {"pid": 99999, "title": "BigSeller - Scan Package"}

        ok, detail = app._paste_to_focused_bigseller(" jt 123456789 ph ")
        assert ok is True, detail
        assert FakeClipboard.value == "JT123456789PH", FakeClipboard.value
        assert calls == ["^a", "^v{ENTER}"], calls
        assert "BigSeller" in detail

        calls.clear()
        app.settings["output_action"] = "Tab"
        ok, _ = app._paste_to_focused_bigseller("SPXPH123456")
        assert ok is True
        assert calls == ["^a", "^v{TAB}"], calls

        calls.clear()
        app._foreground_window_info = lambda: {"pid": 99999, "title": "Notepad"}
        ok, reason = app._paste_to_focused_bigseller("SPXPH123456")
        assert ok is False
        assert calls == []
        assert "not the foreground" in reason
    finally:
        base_app.pyperclip.copy = original_copy
        base_app.send_keys = original_send
        appmod.os.name = original_os_name

    print("V5.0.1 PASS: QR/barcode text -> clipboard -> focused BigSeller -> paste -> submit key restored.")


if __name__ == "__main__":
    main()

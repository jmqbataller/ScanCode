import tempfile
import time
from pathlib import Path

import cv2
import numpy as np
import tkinter as tk

import scancode_app as appmod


def main():
    root = tk.Tk()
    root.withdraw()
    app = appmod.ScanCodeApp(root, start_services=False)

    with tempfile.TemporaryDirectory() as td:
        app.local_root = Path(td)
        app.latest_frame = np.full((360, 640, 3), 180, dtype=np.uint8)
        app.capture = None
        submitted = []
        app.submit_scan_target = lambda code: submitted.append(code)

        # Must not accept scans before Start.
        app.accept_scan('PRESTART')
        assert app.current_session is None

        app.start_stop()
        assert app.system_running is True
        assert app.start_stop_btn.cget('text') == 'Stop'
        assert str(app.pause_resume_btn.cget('state')) == 'normal'

        app.accept_scan('PARCEL-001')
        assert app.current_session is not None
        assert app.current_session.code == 'PARCEL-001'
        first_video = app.current_session.final_path

        # Second scan must finalize first immediately, then start second.
        app.accept_scan('PARCEL-002')
        assert app.current_session is not None
        assert app.current_session.code == 'PARCEL-002'
        assert first_video.exists(), first_video

        time.sleep(0.1)
        assert submitted[:2] == ['PARCEL-001', 'PARCEL-002'], submitted

        app.pause_resume()
        assert app.system_paused is True
        assert app.current_session.paused is True
        assert app.pause_resume_btn.cget('text') == 'Resume'

        # Scans while paused must not replace current parcel.
        app.accept_scan('PARCEL-003')
        assert app.current_session.code == 'PARCEL-002'

        app.pause_resume()
        assert app.system_paused is False
        assert app.current_session.paused is False

        second_video = app.current_session.final_path
        app.start_stop()  # Stop system
        assert app.system_running is False
        assert app.current_session is None
        assert second_video.exists(), second_video
        assert app.start_stop_btn.cget('text') == 'Start'
        assert str(app.pause_resume_btn.cget('state')) == 'disabled'

    root.destroy()
    print('WORKFLOW V4.2 PASS: Start gate, scan -> recording, instant next-scan cutover, Pause/Resume, Stop finalize, target dispatch.')


if __name__ == '__main__':
    main()

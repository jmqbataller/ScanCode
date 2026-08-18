import tkinter as tk
from types import SimpleNamespace

from scancode_app import ScanCodeApp


def main():
    root = tk.Tk()
    root.geometry('1200x760')
    app = ScanCodeApp(root, start_services=False)
    root.update_idletasks()
    root.update()

    assert hasattr(app, 'body_canvas') and hasattr(app, 'body_scroll')
    assert app.start_stop_btn.cget('text') == 'Start'
    assert app.pause_resume_btn.cget('state') == 'disabled'
    assert app.video_border.winfo_height() <= 505

    # v4.2 master Start enables the scanner workflow without creating a fake parcel.
    app.start_stop()
    root.update_idletasks()
    assert app.system_running is True
    assert app.current_session is None
    assert app.start_stop_btn.cget('text') == 'Stop'
    assert app.pause_resume_btn.cget('text') == 'Pause'
    assert app.pause_resume_btn.cget('state') == 'normal'

    # Pause/Resume is system-wide and also applies to a current parcel when present.
    dummy = SimpleNamespace(code='QA-001', paused=False, stop_at=None)
    app.current_session = dummy
    app.pause_resume()
    assert app.system_paused is True
    assert dummy.paused is True
    assert app.pause_resume_btn.cget('text') == 'Resume'
    app.pause_resume()
    assert app.system_paused is False
    assert dummy.paused is False
    assert app.pause_resume_btn.cget('text') == 'Pause'

    # Narrow window must stack, not hide, the side panel and search panel.
    root.geometry('800x600')
    root.update_idletasks(); root.update()
    app._reflow_layout(); root.update_idletasks()
    assert app.side.winfo_ismapped()
    assert int(app.side.grid_info()['row']) == 1
    assert app.search_panel.winfo_ismapped()
    assert int(app.search_panel.grid_info()['row']) == 1
    assert app.video_border.winfo_height() <= 505

    # Content must expose a scroll region larger than the viewport on compact height.
    bbox = app.body_canvas.bbox('all')
    assert bbox is not None and bbox[3] > app.body_canvas.winfo_height()

    # Avoid finalizing dummy session in teardown.
    app.current_session = None
    app.system_running = False
    app.ending_sessions = []
    app.camera_stop.set(); app.sync_stop.set()
    root.destroy()
    print('UI PASS: scrollable layout + master Start/Stop + system Pause/Resume states')


if __name__ == '__main__':
    main()

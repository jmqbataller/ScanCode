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

    # Simulate a live recording to test Start/Stop and Pause/Resume button states.
    dummy = SimpleNamespace(code='QA-001', paused=False, stop_at=None)
    app.current_session = dummy
    app.update_transport_controls()
    assert app.start_stop_btn.cget('text') == 'Stop'
    assert app.pause_resume_btn.cget('text') == 'Pause'
    assert app.pause_resume_btn.cget('state') == 'normal'
    app.pause_resume()
    assert dummy.paused is True
    assert app.pause_resume_btn.cget('text') == 'Resume'

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

    # Restore dummy state without finalization work and exit cleanly.
    app.current_session = None
    app.ending_sessions = []
    app.camera_stop.set(); app.sync_stop.set()
    root.destroy()
    print('UI PASS: fixed camera preview, scrollable workspace, responsive stacking, Start/Stop + Pause/Resume states')


if __name__ == '__main__':
    main()

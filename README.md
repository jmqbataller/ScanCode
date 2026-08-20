# ScanCode v4.3.0 — Automatic Camera Startup

Warehouse parcel QR/barcode scanner and video evidence recorder.

**Author:** John Mark Bataller  
**Platform:** Windows 10/11 x64  
**Production build:** Native Python/OpenCV + ZXing-C++

## Download

Use the GitHub Release installer:

`ScanCode-Setup-4.3.0-x64.exe`

A portable `ScanCode.exe` is also included in the v4.3.0 release.

## v4.3 camera startup behavior

- The Setup EXE launches ScanCode after installation.
- ScanCode automatically starts the PC/USB camera after the Windows/Tk UI is ready.
- The saved camera is tried first.
- If that camera index does not work, ScanCode automatically probes Camera 0–5.
- Each camera is tried through DirectShow, Media Foundation, and Windows Auto backends.
- A camera is considered live only after a real video frame is received.
- The detected working camera index is saved for the next launch.
- The camera worker no longer reads tkinter variables from its background thread, reducing packaged-EXE startup failures.
- Camera reconnect/retry remains active if the webcam temporarily fails.

The **camera preview starts automatically**. The operator still presses **Start** to enable QR/barcode automation and parcel recording, preventing an accidental parcel scan just because the application opened.

## Why v4 is different

The old Electron/Chromium camera pipeline was removed from the production build after repeated webcam regressions. ScanCode v4 uses native Windows/OpenCV camera backends and ZXing-C++ for QR/barcode scanning.

## Core features

- Native built-in / USB webcam capture
- Automatic local camera detection and fallback
- Phone / network MJPEG camera URL support
- QR and multi-format barcode scanning
- Scan confirmation and duplicate protection
- One camera with FAR recording view and NEAR scanner crop
- Start-gated scanner automation
- First accepted parcel scan starts evidence recording
- Next accepted parcel scan finalizes the previous parcel and starts the next recording
- Start / Stop and Pause / Resume workflow
- Scan success sound
- Date/time, station, operator and parcel-code video watermark
- QR/barcode-based video filenames
- Daily folders under `Documents\ScanCode\YYYY-MM-DD`
- Waybill screenshot with automatic bright-label crop
- Evidence JSON metadata per parcel
- Failed / exception marking
- Automatic camera quality status
- Camera reconnect/watch behavior
- Server auto-sync with SHA-256 verification before local evidence deletion
- Server queue status
- Server parcel/evidence search
- End-of-shift verification
- Optional auto-start with Windows
- Notepad Test / BigSeller scan-output workflow
- Responsive small-window mode
- Red / black UI

## Evidence bundle

A completed parcel creates files such as:

- `TRACKING123.avi`
- `TRACKING123_waybill.png`
- `TRACKING123.json`

Only finalized bundles are eligible for server transfer. ScanCode verifies copied files before deleting the local evidence copy.

## Build verification

The v4.3 Windows workflow validates:

- native QR/barcode and evidence core
- UI layout regression
- Start/Pause/Stop warehouse workflow
- automatic camera fallback when the saved camera index fails
- Python syntax before packaging
- successful creation of the portable EXE and Windows installer

The clean v4.3 production build passed all checks and generated `ScanCode-Setup-4.3.0-x64.exe`.

GitHub CI cannot access the physical warehouse webcam, so the final hardware check still needs to be performed on the target Windows PC.

## Source layout

- `native/scancode_app.py` — v4.3 production Windows application and automatic camera runtime
- `native/scancode_core.py` — barcode, recording, evidence and sync core
- `native/test_camera_startup_v43.py` — production camera auto-detection regression test
- `native/test_workflow_v42.py` — parcel workflow regression test
- `.github/workflows/native-v4.3-camera-release.yml` — v4.3 Windows test/build/release pipeline

The older Electron files remain in the repository only as development history and are **not the recommended production build**.

## Uninstall and evidence safety

The Setup EXE installs ScanCode into Program Files and registers a normal Windows uninstaller. Uninstalling the application does not intentionally delete `Documents\ScanCode` warehouse evidence.

## Publisher

Application publisher metadata is **John Mark Bataller**. Windows may show `Unknown publisher` until the installer is digitally signed with a trusted Windows code-signing certificate.

# ScanCode v4.0.0 — Native Windows Rebuild

Warehouse parcel QR/barcode scanner and video evidence recorder.

**Author:** John Mark Bataller  
**Platform:** Windows 10/11 x64  
**Production build:** Native Python/OpenCV + ZXing-C++

## Download

Use the GitHub Release installer:

`ScanCode-Setup-4.0.0-x64.exe`

A portable `ScanCode.exe` is also included in the v4.0.0 release.

## Why v4 is different

The old Electron/Chromium camera pipeline was removed from the production build after repeated webcam regressions. ScanCode v4 opens built-in and USB webcams through native Windows/OpenCV camera backends (DirectShow, Media Foundation fallback) and scans QR/barcodes with ZXing-C++.

## Core features

- Native built-in / USB webcam capture
- Phone / network MJPEG camera URL support
- QR and multi-format barcode scanning
- Scan confirmation and duplicate protection
- One camera with FAR recording view and NEAR scanner crop
- Automatic parcel recording on accepted scan
- Next scan starts the next parcel and finishes the previous recording with configurable overlap
- Start / Resume / Pause / Stop
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
- Auto-start with Windows
- BigSeller browser bridge with Windows UI Automation beta and clipboard fallback
- Responsive small-window mode: camera and recording controls remain while side panels hide
- Red / black UI

## Evidence bundle

A completed parcel creates files such as:

- `TRACKING123.avi`
- `TRACKING123_waybill.png`
- `TRACKING123.json`

Only finalized bundles are eligible for server transfer. ScanCode verifies copied files before deleting the local evidence copy.

## Build verification

The Windows release workflow runs native core tests before publishing the installer. The tests verify:

- QR/barcode decoding
- camera-frame quality processing
- waybill crop processing
- video creation
- metadata creation
- SHA-256 verified server transfer

The physical warehouse webcam still has to be verified on the target PC because GitHub CI does not have access to that PC's real camera hardware.

## Source layout

- `native/scancode_app.py` — current production Windows application
- `native/scancode_core.py` — barcode, recording, evidence and sync core
- `native/test_native_core.py` — native runtime/core tests
- `.github/workflows/native-v4-release.yml` — Windows test/build/release pipeline

The older Electron files remain in the repository only as development history and are **not the recommended production build**.

## Uninstall and evidence safety

The Setup EXE installs ScanCode into Program Files and registers a normal Windows uninstaller. Uninstalling the application does not intentionally delete `Documents\ScanCode` warehouse evidence.

## Publisher

Application publisher metadata is **John Mark Bataller**. Windows may show `Unknown publisher` until the installer is digitally signed with a trusted Windows code-signing certificate.

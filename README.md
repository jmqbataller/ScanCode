# ScanCode v4.6.0 — Performance + Focus Controls

Windows warehouse parcel QR/barcode scanner, active-app scan output, and video evidence recorder.

**Author:** John Mark Bataller  
**Platform:** Windows 10/11 x64  
**Production build:** Native Python/OpenCV + ZXing-C++

## Download

Use the GitHub Release installer:

`ScanCode-Setup-4.6.0-x64.exe`

A portable `ScanCode.exe` is also included in the v4.6.0 release.

## v4.6 highlights

- Lighter progressive decoder to reduce idle CPU usage.
- QR + Barcode is now the default scan format.
- Common 1D/2D formats are accepted, including Code128, Code39, EAN, UPC, ITF, Codabar, DataMatrix, PDF417, Aztec and QR.
- Optional **Enable camera autofocus** control for webcams that support hardware autofocus.
- **Waybill Focus** control with **Near** and **Far** presets.
  - Near: wider scan area for a close/large label.
  - Far: tighter center crop/digital zoom for a smaller/farther label.
- Manual scanner zoom remains available when Waybill Focus is disabled.
- Preview refresh is reduced to about 22 FPS to reduce UI/Pillow CPU usage; camera capture and evidence recording remain full-rate.
- Expensive threshold/upscale recovery runs less often while fast QR/barcode detection still runs every scan cycle.

> Autofocus is hardware-dependent. Enabling it requests autofocus through OpenCV; a fixed-focus A4Tech webcam will simply continue operating as a fixed-focus camera.

## Scan output

The default output mode is **Active App**:

1. Open ScanCode and press **Start**.
2. Focus any textbox/cell/input in Notepad, Excel, a browser, BigSeller, ERP/WMS software, etc.
3. Show a QR or barcode to the camera.
4. ScanCode copies the decoded value, pastes it into the active Windows app, and optionally presses Enter.

ScanCode blocks accidental paste into its own window.

## Camera behavior

- Camera preview starts automatically after the application UI is ready.
- Saved camera index is tried first, then Camera 0–5 automatically.
- DirectShow, Media Foundation and Windows Auto backends are supported.
- v4.5+ prefers 1920×1080 MJPG at 30 FPS, with 1280×720 fallback.
- Software enhancement is used by the decoder only; normal preview and evidence video are not over-sharpened.
- Camera reconnect/retry remains active.

## Core warehouse features

- QR and multi-format barcode scanning
- Active App paste + optional Enter
- Dedicated BigSeller mode
- Scan confirmation and duplicate protection
- FAR recording view + scanner/waybill crop
- Start / Stop and Pause / Resume workflow
- Evidence video per parcel
- Waybill screenshot
- Date/time, station, operator and parcel-code watermark
- Daily folders under `Documents\ScanCode\YYYY-MM-DD`
- Evidence JSON metadata
- Exception marking
- Camera quality status
- Server auto-sync with verification
- Server queue/evidence search
- End-of-shift verification
- Optional auto-start with Windows
- Responsive UI

## Evidence bundle

A completed parcel creates files such as:

- `TRACKING123.avi`
- `TRACKING123_waybill.png`
- `TRACKING123.json`

Only finalized bundles are eligible for server transfer.

## v4.6 build verification

The Windows workflow validates:

- native core
- UI layout
- warehouse Start/Pause/Stop workflow
- automatic camera startup/fallback
- Active App output
- v4.5 fixed-focus 1080p behavior
- softened QR recovery
- Code128 acceptance in QR + Barcode mode
- Near/Far waybill focus presets
- optional autofocus request
- v4.6 lightweight decoder
- portable EXE + Windows installer generation

GitHub CI cannot physically test the user's webcam, so final camera positioning/lighting still needs to be validated on the warehouse PC.

## Source layout

- `native/scancode_app.py` — stable native base application
- `native/scancode_app_v44.py` — Active App output
- `native/scancode_app_v45.py` — 1080p fixed-focus camera profile
- `native/scancode_app_v46.py` — v4.6 performance and focus controls
- `native/scancode_enhanced_v46.py` — lightweight QR/barcode decoder
- `native/scancode_core.py` — evidence, barcode and recording core
- `native/test_performance_focus_v46.py` — v4.6 regression test
- `.github/workflows/native-v4.6-performance-focus-release.yml` — v4.6 Windows test/build/release pipeline

Older Electron files remain only as development history and are not the recommended production build.

## Publisher

Application publisher metadata is **John Mark Bataller**. Windows may show `Unknown publisher` until the installer is digitally signed with a trusted Windows code-signing certificate.

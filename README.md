# ScanCode v5.0.0 — Warehouse Packing Suite

Windows warehouse parcel waybill scanner, packing-video evidence recorder, and BigSeller submission workstation.

**Author:** John Mark Bataller  
**Platform:** Windows 10/11 x64  
**Production build:** Native Python/OpenCV + ZXing-C++ + SQLite

## Primary workflow

1. Scan the parcel waybill using QR or a supported 1D/2D barcode.
2. ScanCode identifies the best tracking candidate and courier.
3. A parcel evidence session starts automatically and includes an optional pre-scan video buffer.
4. Packing is recorded and the sharpest recent waybill frame is saved as evidence.
5. The tracking number is sent to BigSeller through the dedicated Windows UI Automation bridge.
6. ScanCode records BigSeller status as VERIFIED, SUBMITTED, PENDING_VERIFY, or QUEUED/FAILED instead of assuming success.
7. The next accepted parcel finalizes the previous evidence session and starts the next one.
8. Video, waybill image, JSON metadata, checksums, timeline, operator/station, courier and submission state stay linked in the Evidence Center.

## V5 warehouse features

1. Automatic Packing Session
2. BigSeller Submit Confirmation
3. Wrong Parcel / Duplicate Protection
4. Best Waybill Photo
5. Smart Scan Zone
6. Courier Detection
7. Packing Quality Checklist
8. Minimum Recording Time
9. Video Pre-Recording Buffer
10. Exception Workflow
11. Packing Station / Operator Tracking
12. Searchable Evidence Center
13. One-Click Play Evidence
14. Daily Packing Dashboard
15. Live Packing Counter / Parcels-per-hour
16. Failed BigSeller Queue
17. BigSeller Submit Retry
18. Scan → Paste → Verify workflow
19. Wrong Window Protection
20. Multi-Barcode Intelligence
21. Tracking Pattern Validation
22. Audio Feedback
23. Optional Voice Feedback
24. Auto Cleanup / Storage Manager
25. SHA-256 Evidence Integrity
26. Crash Recovery
27. Automatic Camera Reconnect
28. Camera Health Indicator
29. Parcel Timeline
30. Supervisor Mode

The machine-readable implementation map is in `native/v5_feature_manifest.json` and is verified by the v5 release test suite.

## Scanner and camera

- QR + Barcode is the production default.
- Supported formats include Code128, Code39, Code93, EAN, UPC, ITF, Codabar, DataMatrix, PDF417, Aztec and QR.
- Smart Scan Zone prioritizes the center waybill area and periodically uses a full-frame rescue scan.
- Multi-barcode scoring prefers plausible courier tracking numbers over short SKU/order-style codes.
- Waybill Focus supports Auto, Near and Far.
- Optional hardware autofocus remains available for webcams that support it.
- Fixed-focus webcams such as A4Tech models retain the 1080p MJPG profile and software decoding enhancement from v4.5/v4.6.
- Camera capture/recording remains full-rate while the preview and heavy decoder recovery are throttled for lower CPU use.

## BigSeller safety

Dedicated BigSeller mode does not paste into an unrelated foreground application. If BigSeller is closed or its tracking field cannot be reached, the parcel is placed in a persistent retry queue.

When verification is enabled, ScanCode checks the visible BigSeller UI after submission. If BigSeller exposes an explicit success state the parcel becomes `VERIFIED`; if the input clearly changes/clears it becomes `SUBMITTED`; if no reliable confirmation is visible it remains `PENDING_VERIFY`. ScanCode does not falsely label an ambiguous UI state as verified success.

## Packing evidence

A completed parcel can create:

- `TRACKING123.avi` — packing evidence video
- `TRACKING123_waybill.png` — waybill evidence image
- `TRACKING123.json` — parcel metadata

V5 also stores a local SQLite evidence index under ScanCode application data. The index tracks courier, operator, station, timestamps, duration, evidence paths, SHA-256 hashes, exceptions, BigSeller status, sync status, quality status and integrity state.

### Pre-record buffer

The pre-record buffer stores compressed, reduced-resolution history frames in memory rather than raw 1080p frames. When a parcel begins, those history frames are resized to the evidence-video dimensions and injected while holding the session lock. This captures activity immediately before the waybill scan without excessive RAM use or concurrent VideoWriter access.

### Packing quality

The v5 checklist tracks:

- waybill scanned
- video created
- minimum recording duration met
- waybill photo present
- BigSeller submission status

A parcel becomes `PASS` only when the required evidence and submission checks are satisfied; otherwise it is flagged `REVIEW`.

## Evidence Center

The in-app Evidence Center provides:

- tracking/courier/operator search
- parcel status list
- one-click video playback
- evidence paths and hashes
- BigSeller state
- quality and integrity state
- full parcel event timeline
- rolling 24-hour packing dashboard

The main ScanCode screen also shows a live packing scorecard with packed count, submitted count, parcels/hour and BigSeller retry queue size.

## Server retention and storage

V5 changes server sync behavior so a verified server copy does not immediately delete the local evidence. The evidence database records the parcel as `SYNCED`, later sync cycles skip it, and the Storage Manager may remove local files only after both:

- server sync is verified; and
- local evidence has reached the configured retention age.

Default retention is 14 days.

## Compatibility retained from v4

- Native Windows/OpenCV camera pipeline
- 1080p fixed-focus optimization
- optional autofocus request
- automatic camera detection/fallback/reconnect
- Start/Stop and Pause/Resume controls
- Active App output as an alternate target
- camera quality checks
- exception marking
- video watermark with station/operator/time/tracking
- interrupted recording recovery
- Windows auto-start option
- verified server copying

## Download

Use the GitHub v5.0.0 release installer:

`ScanCode-Setup-5.0.0-x64.exe`

A portable `ScanCode.exe` is also published with the release.

## Build verification

The v5 Windows workflow runs the existing v4 regression suites plus:

- 30-feature manifest verification
- courier/tracking candidate intelligence
- QR + Code128 pass-through in the smart scanner
- Smart Scan Zone / adaptive Near-Far path
- evidence SQLite lifecycle and dashboard
- persistent BigSeller queue
- SHA-256 tamper detection
- Python syntax for every v5 production module
- portable EXE generation
- Windows installer generation

GitHub CI cannot physically interact with the warehouse A4Tech webcam or a live authenticated BigSeller account. Physical camera positioning/lighting and final BigSeller page-field behavior still need to be validated on the target Windows packing station.

## Source layout

- `native/scancode_app_v50_final.py` — v5 production entrypoint
- `native/scancode_app_v50.py` — v5 warehouse feature layer
- `native/scancode_app_v50_runtime.py` — runtime compatibility, counters and memory optimizations
- `native/scancode_scanner_v50.py` — Smart Scan Zone, Auto Near/Far and multi-code pipeline
- `native/scancode_v5_services.py` — evidence database, queue, courier/tracking logic, integrity and retention
- `native/v5_feature_manifest.json` — 30-feature implementation map
- `native/test_v5_warehouse_suite.py` — v5 regression suite
- `.github/workflows/native-v5.0-warehouse-suite-release.yml` — Windows test/build/release pipeline

Older v4 modules remain because v5 deliberately inherits the proven camera, recording and scanner behavior instead of replacing the stable native core.

## Publisher

Application publisher metadata is **John Mark Bataller**. Windows may show `Unknown publisher` until the installer is digitally signed with a trusted Windows code-signing certificate.

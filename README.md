# ScanCode v1.6.1

Warehouse parcel QR/barcode evidence scanner.

**Author:** John Mark Bataller  
**Windows:** 10/11 x64

## Recommended install

1. Extract this folder.
2. Double-click `INSTALL_SCANCODE.bat`.
3. Approve the Windows Administrator prompt.
4. The script checks/installs Node.js LTS when needed, installs build dependencies, builds the Setup + Portable EXEs, then silently installs ScanCode for the whole PC.

Generated files are placed in `dist`:

- `ScanCode-Setup-1.6.1-x64.exe`
- `ScanCode-Portable-1.6.1-x64.exe`

The Setup build installs ScanCode per-machine and creates Desktop/Start Menu shortcuts. ScanCode appears in Windows Installed Apps and has an uninstaller.

## Storage safety

Parcel evidence remains under `Documents\\ScanCode`. Normal app uninstall removes the application/settings but intentionally keeps warehouse evidence files.

## Build optimization

- ASAR packaging enabled
- Maximum installer compression
- English Electron locale only
- Runtime package includes only `main.js`, `src`, and `package.json`
- Old duplicate installer/test BAT files removed

## Publisher note

The application metadata is set to **John Mark Bataller**. Windows may still display **Unknown publisher** in UAC until the EXE is digitally code-signed with a trusted certificate.


## v1.6.1 build fix

- Removed obsolete/unsupported `win.publisherName` from electron-builder configuration.
- Author remains `John Mark Bataller` in package/application metadata.
- Removed unnecessary assisted-installer-only elevation option from the one-click NSIS config.
- Installer BAT now discovers the generated Setup EXE dynamically instead of relying on an old hardcoded version filename.


## v1.6.2 — Standalone uninstall script

The deployment folder now includes:

- `INSTALL_SCANCODE.bat` — builds and installs ScanCode.
- `UNINSTALL_SCANCODE.bat` — removes the installed ScanCode application, Program Files leftovers, application settings/cache, desktop/Start Menu shortcuts, and ScanCode startup entry.

For warehouse safety, the standalone uninstaller intentionally keeps `Documents\ScanCode` recordings and evidence.


## v1.7 QA / Stabilization

- Removed the in-app Uninstall button. Use `UNINSTALL_SCANCODE.bat` or Windows Installed Apps.
- Fixed Compact View when the main window is maximized by unmaximizing before resizing.
- Compact View now shows only the camera and Start / Pause / Stop; F4 toggles compact/full, Esc exits compact.
- Added F1 Start/Resume, F2 Pause, F3 Stop, F4 Compact.
- Improved phone/network camera Connect behavior.
- BigSeller now reports NEEDS SETUP when its URL is missing instead of opening a blank window.
- Added `QA_SCANCODE.bat` and `qa/qa.js`; the installer runs software QA before downloading/building dependencies.
- Hardware/service-dependent tests are explicitly marked NEEDS SETUP rather than falsely reported as working.


## v1.8 — Compact Removed + Camera Selector Fixed

- Compact View has been removed completely from the app and runtime.
- The camera device selector now displays a readable camera name or a clear fallback such as `No camera detected`.
- Camera permission is requested before device enumeration so Windows camera names are available when allowed.
- Camera source/device/restart controls now use a stable responsive grid and the device dropdown can no longer collapse into a tiny arrow-only control.
- F1/F2/F3 remain Start/Resume, Pause, and Stop.


## v1.9 — Built-in Camera Recovery Fix

The local webcam pipeline was simplified for reliability. ScanCode now opens a built-in/USB webcam exactly once with `getUserMedia`, attaches that stream to the live video, and runs barcode recognition from frames of that same stream. The previous temporary permission probe and ZXing-owned second camera stream were removed because rapid open/close/reopen behavior can leave some laptop webcams in a busy/locked state.

Camera startup also retries the Windows default camera automatically if a saved device ID is stale or invalid. Camera errors now explain permission, busy-camera, and no-device conditions more clearly.


## v2.0 — Camera Rescue

Camera startup was simplified and hardened:
- Electron now configures both `setPermissionCheckHandler` and `setPermissionRequestHandler` for media access.
- Startup does not enumerate cameras before opening one.
- ScanCode first calls the simplest possible `getUserMedia({video:true})` path for the Windows default/built-in camera.
- Camera requests have an 8-second timeout instead of staying on “Starting camera…” forever.
- Device names are enumerated only after a live stream exists.
- Selected-camera and 720p fallback attempts are available.
- Windows camera-access status can be queried from Electron.
- A Diagnose button shows OS permission/device information.
- `CAMERA_DIAGNOSTICS.bat` lists Windows camera devices and can open Camera Privacy settings.
- The UI displays `v2.0` so the tested build can be confirmed visually.


## v2.0.3 — Camera Stabilization

- Renderer is now served from a secure `scancode://app` origin instead of `file://`.
- Camera permission handlers are restricted to the trusted ScanCode renderer.
- Fixed a watchdog race that could restart/cancel the webcam while it was still opening.
- Camera startup no longer stacks redundant default-camera requests after a timeout/busy error.
- Camera request timeout cleanup was hardened.
- Failed camera startup pauses automatic watchdog retries for 30 seconds; manual Restart remains available immediately.
- Diagnose now shows Windows camera access, camera enumeration, secure-context state, renderer origin, and Electron version.

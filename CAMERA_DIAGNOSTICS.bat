@echo off
setlocal
color 0C
title ScanCode Camera Diagnostics

echo ============================================================
echo              SCANCODE CAMERA DIAGNOSTICS
echo ============================================================
echo.
echo [1] Windows camera / imaging devices:
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-PnpDevice | Where-Object { $_.Class -in @('Camera','Image') } | Format-Table -AutoSize Status,Class,FriendlyName,InstanceId"
echo.
echo [2] If your camera is listed above but ScanCode cannot open it,
echo     check Windows Camera Privacy settings.
echo.
choice /C YN /N /M "Open Windows Camera Privacy settings now? [Y/N]: "
if errorlevel 2 goto :done
start "" ms-settings:privacy-webcam
:done
echo.
echo Also close Windows Camera, Zoom, Teams, Discord, OBS, browser tabs,
echo or other software that may already be using the webcam.
echo.
pause
endlocal

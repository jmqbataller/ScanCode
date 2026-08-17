@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
title ScanCode - Automatic System Installer

:: Request Administrator rights because ScanCode is installed per-machine in Program Files.
net session >nul 2>&1
if not "%errorlevel%"=="0" (
  echo Requesting Administrator permission...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

cls
echo ============================================================
echo              SCANCODE AUTOMATIC INSTALLER
echo                 Author: John Mark Bataller
echo ============================================================
echo.

echo [1/7] Checking Node.js...
where node >nul 2>&1
if errorlevel 1 (
  echo Node.js LTS is not installed. Attempting automatic install via winget...
  where winget >nul 2>&1
  if errorlevel 1 (
    echo.
    echo ERROR: Node.js is required and winget is not available.
    echo Install Node.js LTS, then run this installer again.
    pause
    exit /b 1
  )
  winget install --id OpenJS.NodeJS.LTS -e --source winget --accept-package-agreements --accept-source-agreements --silent
  if errorlevel 1 (
    echo ERROR: Node.js installation failed.
    pause
    exit /b 1
  )
  set "PATH=%ProgramFiles%\nodejs;%PATH%"
)

where npm >nul 2>&1
if errorlevel 1 (
  set "PATH=%ProgramFiles%\nodejs;%PATH%"
)
where npm >nul 2>&1
if errorlevel 1 (
  echo ERROR: npm was not found after Node.js setup. Restart Windows and run this BAT again.
  pause
  exit /b 1
)

echo [2/7] Running ScanCode software QA...
node qa\qa.js
if errorlevel 1 goto :failed

echo [3/7] Installing ScanCode build dependencies...
call npm install --no-audit --no-fund
if errorlevel 1 goto :failed

echo [4/7] Cleaning previous build output...
if exist dist rmdir /s /q dist

echo [5/7] Building ScanCode Windows EXE files...
echo Using electron-builder compatible Windows configuration...
call npm run dist
if errorlevel 1 goto :failed

echo [6/7] Locating ScanCode Setup...
set "SETUP_EXE="
if not defined SETUP_EXE (
  for /f "delims=" %%F in ('dir /b /a:-d /o:-d "dist\ScanCode-Setup-*.exe" 2^>nul') do if not defined SETUP_EXE set "SETUP_EXE=%CD%\dist\%%F"
)
if not defined SETUP_EXE (
  echo ERROR: Setup EXE was not generated.
  goto :failed
)

echo [7/7] Installing ScanCode to this PC...
echo Installer: !SETUP_EXE!
start /wait "" "!SETUP_EXE!" /S
if errorlevel 1 goto :failed

echo.
echo ============================================================
echo              SCANCODE INSTALLATION SUCCESSFUL
echo ============================================================
echo Installed application : ScanCode
echo Author                : John Mark Bataller
echo Program               : Program Files\ScanCode
echo Local evidence        : Documents\ScanCode
echo.
echo Setup and Portable EXE files are available in the dist folder.
echo.
start "" "%ProgramFiles%\ScanCode\ScanCode.exe" 2>nul
pause
exit /b 0

:failed
echo.
echo ============================================================
echo                 INSTALLATION FAILED
echo ============================================================
echo Review the error shown above and run INSTALL_SCANCODE.bat again.
pause
exit /b 1

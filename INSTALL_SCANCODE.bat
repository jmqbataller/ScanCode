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

echo [0/8] Checking for a broken previous ScanCode installation...
set "SCANCODE_REG_COUNT=0"
for /f %%R in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "$n=0; $roots=@(''HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall'',''HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall'',''HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall''); foreach($r in $roots){ if(Test-Path $r){ Get-ChildItem $r -ErrorAction SilentlyContinue ^| ForEach-Object { try { $p=Get-ItemProperty $_.PSPath -ErrorAction Stop; if(([string]$p.DisplayName) -like ''ScanCode*''){ $n++ } } catch{} } } }; $n"') do set "SCANCODE_REG_COUNT=%%R"

set "HAS_UNINSTALLER=0"
if exist "%ProgramFiles%\ScanCode\Uninstall ScanCode.exe" set "HAS_UNINSTALLER=1"
if defined ProgramFiles(x86) if exist "%ProgramFiles(x86)%\ScanCode\Uninstall ScanCode.exe" set "HAS_UNINSTALLER=1"
if exist "%LOCALAPPDATA%\Programs\ScanCode\Uninstall ScanCode.exe" set "HAS_UNINSTALLER=1"
if exist "%LOCALAPPDATA%\Programs\scancode\Uninstall ScanCode.exe" set "HAS_UNINSTALLER=1"

if not "!SCANCODE_REG_COUNT!"=="0" if "!HAS_UNINSTALLER!"=="0" (
  echo Found an orphaned Windows Installed Apps entry.
  echo Running ScanCode force cleanup before installation...
  if exist "%~dp0UNINSTALL_SCANCODE.bat" (
    call "%~dp0UNINSTALL_SCANCODE.bat" /silent
  ) else (
    echo WARNING: UNINSTALL_SCANCODE.bat is missing; stale entry may remain.
  )
) else (
  echo Previous install state is OK.
)

echo [1/8] Checking Node.js...
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
if errorlevel 1 set "PATH=%ProgramFiles%\nodejs;%PATH%"
where npm >nul 2>&1
if errorlevel 1 (
  echo ERROR: npm was not found after Node.js setup. Restart Windows and run this BAT again.
  pause
  exit /b 1
)

echo [2/8] Running ScanCode software QA...
node qa\qa.js
if errorlevel 1 goto :failed

echo [3/8] Installing ScanCode build dependencies...
call npm install --no-audit --no-fund
if errorlevel 1 goto :failed

echo [4/8] Cleaning previous build output...
if exist dist rmdir /s /q dist

echo [5/8] Building ScanCode Windows EXE files...
call npm run dist
if errorlevel 1 goto :failed

echo [6/8] Locating ScanCode Setup...
set "SETUP_EXE="
for /f "delims=" %%F in ('dir /b /a:-d /o:-d "dist\ScanCode-Setup-*.exe" 2^>nul') do if not defined SETUP_EXE set "SETUP_EXE=%CD%\dist\%%F"
if not defined SETUP_EXE (
  echo ERROR: Setup EXE was not generated.
  goto :failed
)

echo [7/8] Installing ScanCode to this PC...
echo Installer: !SETUP_EXE!
start /wait "" "!SETUP_EXE!" /S
if errorlevel 1 goto :failed

echo [8/8] Verifying installed application...
set "INSTALLED_EXE="
if exist "%ProgramFiles%\ScanCode\ScanCode.exe" set "INSTALLED_EXE=%ProgramFiles%\ScanCode\ScanCode.exe"
if not defined INSTALLED_EXE if defined ProgramFiles(x86) if exist "%ProgramFiles(x86)%\ScanCode\ScanCode.exe" set "INSTALLED_EXE=%ProgramFiles(x86)%\ScanCode\ScanCode.exe"
if not defined INSTALLED_EXE if exist "%LOCALAPPDATA%\Programs\ScanCode\ScanCode.exe" set "INSTALLED_EXE=%LOCALAPPDATA%\Programs\ScanCode\ScanCode.exe"
if not defined INSTALLED_EXE if exist "%LOCALAPPDATA%\Programs\scancode\ScanCode.exe" set "INSTALLED_EXE=%LOCALAPPDATA%\Programs\scancode\ScanCode.exe"
if not defined INSTALLED_EXE (
  echo ERROR: Setup finished but ScanCode.exe was not found.
  goto :failed
)

echo.
echo ============================================================
echo              SCANCODE INSTALLATION SUCCESSFUL
echo ============================================================
echo Installed application : ScanCode
echo Author                : John Mark Bataller
echo Program               : !INSTALLED_EXE!
echo Local evidence        : Documents\ScanCode
echo.
start "" "!INSTALLED_EXE!"
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

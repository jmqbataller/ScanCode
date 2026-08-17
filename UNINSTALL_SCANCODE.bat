@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title ScanCode - Complete Uninstaller

:: Request Administrator rights because the installed app lives in Program Files.
net session >nul 2>&1
if not "%errorlevel%"=="0" (
  echo Requesting Administrator permission...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

cls
echo ============================================================
echo                 SCANCODE UNINSTALLER
echo                 Author: John Mark Bataller
echo ============================================================
echo.
echo This will remove ScanCode program files, shortcuts,
echo startup entries, application settings and cache.
echo.
echo IMPORTANT: Warehouse evidence in Documents\ScanCode will NOT
echo be deleted by this script.
echo.
choice /C YN /N /M "Continue uninstall? [Y/N]: "
if errorlevel 2 exit /b 0

echo.
echo [1/6] Closing ScanCode...
taskkill /F /IM ScanCode.exe >nul 2>&1

echo [2/6] Looking for the Windows ScanCode uninstaller...
set "UNINSTALLER="
if exist "%ProgramFiles%\ScanCode\Uninstall ScanCode.exe" set "UNINSTALLER=%ProgramFiles%\ScanCode\Uninstall ScanCode.exe"
if not defined UNINSTALLER if defined ProgramFiles(x86) if exist "%ProgramFiles(x86)%\ScanCode\Uninstall ScanCode.exe" set "UNINSTALLER=%ProgramFiles(x86)%\ScanCode\Uninstall ScanCode.exe"
if not defined UNINSTALLER if exist "%LOCALAPPDATA%\Programs\ScanCode\Uninstall ScanCode.exe" set "UNINSTALLER=%LOCALAPPDATA%\Programs\ScanCode\Uninstall ScanCode.exe"

if defined UNINSTALLER (
  echo Found: !UNINSTALLER!
  echo [3/6] Running the official ScanCode uninstaller...
  start /wait "" "!UNINSTALLER!" /S
) else (
  echo Official uninstaller was not found. Continuing with cleanup.
  echo [3/6] Skipping official uninstaller...
)

echo [4/6] Removing ScanCode program leftovers...
if exist "%ProgramFiles%\ScanCode" rmdir /s /q "%ProgramFiles%\ScanCode" >nul 2>&1
if defined ProgramFiles(x86) if exist "%ProgramFiles(x86)%\ScanCode" rmdir /s /q "%ProgramFiles(x86)%\ScanCode" >nul 2>&1
if exist "%LOCALAPPDATA%\Programs\ScanCode" rmdir /s /q "%LOCALAPPDATA%\Programs\ScanCode" >nul 2>&1

echo [5/6] Removing app settings, cache, shortcuts and startup entry...
if exist "%APPDATA%\ScanCode" rmdir /s /q "%APPDATA%\ScanCode" >nul 2>&1
if exist "%LOCALAPPDATA%\ScanCode" rmdir /s /q "%LOCALAPPDATA%\ScanCode" >nul 2>&1
if exist "%USERPROFILE%\Desktop\ScanCode.lnk" del /f /q "%USERPROFILE%\Desktop\ScanCode.lnk" >nul 2>&1
if exist "%PUBLIC%\Desktop\ScanCode.lnk" del /f /q "%PUBLIC%\Desktop\ScanCode.lnk" >nul 2>&1
if exist "%APPDATA%\Microsoft\Windows\Start Menu\Programs\ScanCode.lnk" del /f /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\ScanCode.lnk" >nul 2>&1
if exist "%ProgramData%\Microsoft\Windows\Start Menu\Programs\ScanCode.lnk" del /f /q "%ProgramData%\Microsoft\Windows\Start Menu\Programs\ScanCode.lnk" >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "ScanCode" /f >nul 2>&1

:: Remove leftover Add/Remove Programs entries whose DisplayName begins with ScanCode.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$roots=@('HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall','HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall','HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall'); foreach($r in $roots){ if(Test-Path $r){ Get-ChildItem $r -ErrorAction SilentlyContinue ^| ForEach-Object { try { $p=Get-ItemProperty $_.PSPath -ErrorAction Stop; if($p.DisplayName -like 'ScanCode*'){ Remove-Item $_.PSPath -Recurse -Force -ErrorAction SilentlyContinue } } catch{} } } }" >nul 2>&1

echo [6/6] Verifying removal...
set "LEFTOVER=0"
if exist "%ProgramFiles%\ScanCode\ScanCode.exe" set "LEFTOVER=1"
if defined ProgramFiles(x86) if exist "%ProgramFiles(x86)%\ScanCode\ScanCode.exe" set "LEFTOVER=1"
if exist "%LOCALAPPDATA%\Programs\ScanCode\ScanCode.exe" set "LEFTOVER=1"

echo.
if "!LEFTOVER!"=="0" (
  echo ============================================================
  echo               SCANCODE UNINSTALL COMPLETE
  echo ============================================================
  echo Program files       : Removed
  echo App settings/cache  : Removed
  echo Shortcuts/startup   : Removed
  echo Warehouse evidence  : KEPT in Documents\ScanCode
) else (
  echo ============================================================
  echo             SCANCODE CLEANUP NEEDS ATTENTION
  echo ============================================================
  echo Some installed files may still be locked.
  echo Restart Windows and run UNINSTALL_SCANCODE.bat again.
)
echo.
pause
exit /b 0

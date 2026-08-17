@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title ScanCode - Force Uninstaller

:: Elevate to Administrator.
net session >nul 2>&1
if not "%errorlevel%"=="0" (
  echo Requesting Administrator permission...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
  exit /b
)

set "SILENT=0"
if /I "%~1"=="/silent" set "SILENT=1"

cls
echo ============================================================
echo              SCANCODE FORCE UNINSTALLER
echo              Author: John Mark Bataller
echo ============================================================
echo.
echo This repairs/removes broken ScanCode installs even when the
echo original Uninstall ScanCode.exe is already missing.
echo.
echo Warehouse evidence under Documents\ScanCode is KEPT.
echo.
if "%SILENT%"=="0" (
  choice /C YN /N /M "Continue force uninstall? [Y/N]: "
  if errorlevel 2 exit /b 0
)

echo.
echo [1/7] Closing ScanCode processes...
taskkill /F /IM ScanCode.exe >nul 2>&1
taskkill /F /IM scancode.exe >nul 2>&1

echo [2/7] Running an official uninstaller if one still exists...
set "UNINSTALLER="
if exist "%ProgramFiles%\ScanCode\Uninstall ScanCode.exe" set "UNINSTALLER=%ProgramFiles%\ScanCode\Uninstall ScanCode.exe"
if not defined UNINSTALLER if defined ProgramFiles(x86) if exist "%ProgramFiles(x86)%\ScanCode\Uninstall ScanCode.exe" set "UNINSTALLER=%ProgramFiles(x86)%\ScanCode\Uninstall ScanCode.exe"
if not defined UNINSTALLER if exist "%LOCALAPPDATA%\Programs\ScanCode\Uninstall ScanCode.exe" set "UNINSTALLER=%LOCALAPPDATA%\Programs\ScanCode\Uninstall ScanCode.exe"
if not defined UNINSTALLER if exist "%LOCALAPPDATA%\Programs\scancode\Uninstall ScanCode.exe" set "UNINSTALLER=%LOCALAPPDATA%\Programs\scancode\Uninstall ScanCode.exe"

if defined UNINSTALLER (
  echo Found: !UNINSTALLER!
  start /wait "" "!UNINSTALLER!" /S >nul 2>&1
) else (
  echo Original uninstaller is missing - force cleanup will continue.
)

echo [3/7] Removing installed program folders...
for %%D in (
  "%ProgramFiles%\ScanCode"
  "%LOCALAPPDATA%\Programs\ScanCode"
  "%LOCALAPPDATA%\Programs\scancode"
) do (
  if exist "%%~D" rmdir /s /q "%%~D" >nul 2>&1
)
if defined ProgramFiles(x86) if exist "%ProgramFiles(x86)%\ScanCode" rmdir /s /q "%ProgramFiles(x86)%\ScanCode" >nul 2>&1

echo [4/7] Removing ScanCode settings and cache...
for %%D in (
  "%APPDATA%\ScanCode"
  "%APPDATA%\scancode"
  "%LOCALAPPDATA%\ScanCode"
  "%LOCALAPPDATA%\scancode"
  "%LOCALAPPDATA%\scancode-updater"
) do (
  if exist "%%~D" rmdir /s /q "%%~D" >nul 2>&1
)

echo [5/7] Removing shortcuts and auto-start entries...
del /f /q "%USERPROFILE%\Desktop\ScanCode.lnk" >nul 2>&1
del /f /q "%PUBLIC%\Desktop\ScanCode.lnk" >nul 2>&1
del /f /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\ScanCode.lnk" >nul 2>&1
del /f /q "%ProgramData%\Microsoft\Windows\Start Menu\Programs\ScanCode.lnk" >nul 2>&1
rmdir /s /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\ScanCode" >nul 2>&1
rmdir /s /q "%ProgramData%\Microsoft\Windows\Start Menu\Programs\ScanCode" >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "ScanCode" /f >nul 2>&1
reg delete "HKLM\Software\Microsoft\Windows\CurrentVersion\Run" /v "ScanCode" /f >nul 2>&1

powershell -NoProfile -ExecutionPolicy Bypass -Command "$roots=@('HKCU:\Software\Microsoft\Windows\CurrentVersion\Run','HKLM:\Software\Microsoft\Windows\CurrentVersion\Run'); foreach($r in $roots){ if(Test-Path $r){ $p=Get-ItemProperty $r -ErrorAction SilentlyContinue; foreach($prop in $p.PSObject.Properties){ if($prop.Name -notmatch '^PS' -and [string]$prop.Value -match '(?i)scancode'){ Remove-ItemProperty -Path $r -Name $prop.Name -Force -ErrorAction SilentlyContinue } } } }" >nul 2>&1

echo [6/7] Removing broken Windows Installed Apps entries...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$roots=@('HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall','HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall','HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'); foreach($r in $roots){ if(Test-Path $r){ Get-ChildItem $r -ErrorAction SilentlyContinue | ForEach-Object { try { $p=Get-ItemProperty $_.PSPath -ErrorAction Stop; $display=[string]$p.DisplayName; $uninstall=[string]$p.UninstallString; $quiet=[string]$p.QuietUninstallString; $loc=[string]$p.InstallLocation; if($display -like 'ScanCode*' -or $uninstall -match '(?i)scancode' -or $quiet -match '(?i)scancode' -or $loc -match '(?i)[\\/]scancode([\\/]|$)'){ Write-Host ('Removing Installed Apps entry: ' + $display); Remove-Item $_.PSPath -Recurse -Force -ErrorAction SilentlyContinue } } catch{} } } }"

echo [7/7] Verifying cleanup...
set "LEFTOVER=0"
if exist "%ProgramFiles%\ScanCode\ScanCode.exe" set "LEFTOVER=1"
if defined ProgramFiles(x86) if exist "%ProgramFiles(x86)%\ScanCode\ScanCode.exe" set "LEFTOVER=1"
if exist "%LOCALAPPDATA%\Programs\ScanCode\ScanCode.exe" set "LEFTOVER=1"
if exist "%LOCALAPPDATA%\Programs\scancode\ScanCode.exe" set "LEFTOVER=1"

set "REGLEFT=0"
for /f %%R in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "$n=0; $roots=@(''HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall'',''HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall'',''HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall''); foreach($r in $roots){ if(Test-Path $r){ Get-ChildItem $r -ErrorAction SilentlyContinue ^| ForEach-Object { try { $p=Get-ItemProperty $_.PSPath -ErrorAction Stop; if(([string]$p.DisplayName) -like ''ScanCode*''){ $n++ } } catch{} } } }; $n"') do set "REGLEFT=%%R"

echo.
if "!LEFTOVER!"=="0" if "!REGLEFT!"=="0" (
  echo ============================================================
  echo             SCANCODE FORCE UNINSTALL COMPLETE
  echo ============================================================
  echo Program files       : Removed
  echo Installed Apps entry: Removed
  echo App settings/cache  : Removed
  echo Shortcuts/startup   : Removed
  echo Warehouse evidence  : KEPT in Documents\ScanCode
  echo.
  echo Close and reopen Windows Settings if ScanCode is still shown.
) else (
  echo ============================================================
  echo           SCANCODE CLEANUP NEEDS ATTENTION
  echo ============================================================
  echo Program leftover flag: !LEFTOVER!
  echo Registry entries left : !REGLEFT!
  echo.
  echo Restart Windows, then run this BAT again as Administrator.
)

if "%SILENT%"=="0" pause
exit /b 0

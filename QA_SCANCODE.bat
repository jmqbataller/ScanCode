@echo off
setlocal
cd /d "%~dp0"
title ScanCode QA
where node >nul 2>&1
if errorlevel 1 (
  echo Node.js is required to run the ScanCode QA checks.
  pause
  exit /b 1
)
node qa\qa.js
set "RC=%errorlevel%"
echo.
if "%RC%"=="0" (
  echo SOFTWARE QA PASSED. Items marked NEEDS SETUP require warehouse hardware/services.
) else (
  echo QA FAILED. Do not install until FAIL items are corrected.
)
pause
exit /b %RC%

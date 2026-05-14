@echo off
setlocal enabledelayedexpansion
cd /d %~dp0

if not exist ".env" (
  echo [ERROR] .env not found. Copy .env.example to .env and fill values first.
  exit /b 1
)

where py >nul 2>nul
if %errorlevel%==0 (
  set PY=py -3
) else (
  where python >nul 2>nul
  if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Install Python 3 first.
    exit /b 1
  )
  set PY=python
)

echo [1/3] Install dependencies...
%PY% -m pip install -r requirements.txt || exit /b 1

echo [2/3] Install Playwright Chromium...
%PY% -m playwright install chromium || exit /b 1

echo [3/3] Run check-in...
%PY% checkin.py
exit /b %errorlevel%

@echo off
setlocal
chcp 65001 >nul
title eDEX-Deck

cd /d "%~dp0"

echo.
echo   eDEX-Deck
echo   non-invasive UI layer for eDEX-UI
echo   ------------------------------------------
echo.

rem ---------- locate python ----------
set "PY="
for %%C in (python.exe) do (
  for /f "delims=" %%P in ('where %%C 2^>nul') do (
    if not defined PY set "PY=%%P"
  )
)
if not defined PY (
  if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
)
if not defined PY (
  if exist "C:\Python313\python.exe" set "PY=C:\Python313\python.exe"
)
if not defined PY (
  echo   [x] Python not found.
  echo       Install Python 3.8+ from https://www.python.org/downloads/
  echo       and make sure "Add python.exe to PATH" is checked.
  echo.
  pause
  exit /b 1
)
echo   [i] python: %PY%

rem ---------- dependency ----------
"%PY%" -c "import websocket" >nul 2>&1
if errorlevel 1 (
  echo   [i] installing dependency: websocket-client
  "%PY%" -m pip install --quiet --disable-pip-version-check websocket-client
  "%PY%" -c "import websocket" >nul 2>&1
  if errorlevel 1 (
    echo   [x] could not install websocket-client. Run manually:
    echo       "%PY%" -m pip install websocket-client
    echo.
    pause
    exit /b 1
  )
)

rem ---------- go ----------
echo   [i] launching eDEX and injecting the dock...
echo.

"%PY%" "src\inject.py" --keep %*

echo.
echo   eDEX has exited. Press any key to close.
pause >nul
endlocal

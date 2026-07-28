@echo off
REM ===================================================================
REM  Build a standalone Windows .exe for the Jersey Stock Checker.
REM  Double-click this file. It finds Python, installs what's needed,
REM  downloads the stealth browser, and builds the app.
REM ===================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ============================================================
echo   Jersey Stock Checker - EXE builder
echo ============================================================
echo.

REM --- Find a working Python -----------------------------------------
REM Try the 'py' launcher first, then 'python'. Whichever runs wins.
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY (
    python --version >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo [ERROR] Python was not found.
    echo Install it from https://www.python.org/downloads/ and CHECK the box
    echo "Add python.exe to PATH" on the first screen of the installer.
    echo Then run this again.
    echo.
    pause
    exit /b 1
)

echo Using Python: %PY%
%PY% --version
echo.

REM --- Install dependencies ------------------------------------------
echo Installing dependencies (patchright, pyinstaller)...
%PY% -m pip install --upgrade pip
%PY% -m pip install patchright pyinstaller
if errorlevel 1 (
    echo [ERROR] Failed to install packages.
    pause
    exit /b 1
)

REM --- Download the stealth browser into a LOCAL folder --------------
echo.
echo Downloading the browser (first build only, ~150MB)...
set PLAYWRIGHT_BROWSERS_PATH=0
%PY% -m patchright install chromium
if errorlevel 1 (
    echo [ERROR] Browser download failed. Check your internet connection.
    pause
    exit /b 1
)

REM --- Build the exe -------------------------------------------------
echo.
echo Building JerseyChecker.exe ...
%PY% -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onedir ^
    --windowed ^
    --name JerseyChecker ^
    --collect-all patchright ^
    jersey_checker.py
if errorlevel 1 (
    echo [ERROR] Build failed.
    pause
    exit /b 1
)

REM --- Bundle the browser + config next to the exe ------------------
echo.
echo Bundling the browser and config with the app...
if exist "ms-playwright" (
    xcopy /E /I /Y "ms-playwright" "dist\JerseyChecker\ms-playwright" >nul
)
if exist "config.json" (
    copy /Y "config.json" "dist\JerseyChecker\config.json" >nul
) else (
    copy /Y "config.example.json" "dist\JerseyChecker\config.json" >nul
)

echo.
echo ============================================================
echo   DONE!
echo   Your app is in:  dist\JerseyChecker\
echo   Double-click:    dist\JerseyChecker\JerseyChecker.exe
echo.
echo   Edit  dist\JerseyChecker\config.json  to change what's watched.
echo   You can move the whole JerseyChecker folder anywhere; just keep
echo   the folder together - the exe needs the files next to it.
echo ============================================================
echo.
pause

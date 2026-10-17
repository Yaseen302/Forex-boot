@echo off
setlocal
cd /d "%~dp0"
echo.
echo ForexLab - choose a local workflow
echo 1. Synthetic chart preview - no broker
echo 2. MT5 read-only analysis - no orders
echo 3. Check MT5 connection - no orders
echo 4. Demo execution controls - account must be DEMO
echo.
set /p "choice=Enter 1, 2, 3 or 4: "
if "%choice%"=="1" goto preview
if "%choice%"=="2" goto analysis
if "%choice%"=="3" goto check
if "%choice%"=="4" goto demo
echo No workflow selected.
goto finish
:preview
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-windows.ps1"
goto finish
:analysis
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-windows.ps1" -Source mt5
goto finish
:check
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\check-mt5.ps1"
goto finish
:demo
echo This enables demo controls only. The app still requires a confirmed DEMO
echo account, calendar clearance, valid signals and every risk check.
set /p "confirm=Type DEMO to continue: "
if not "%confirm%"=="DEMO" goto finish
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-windows.ps1" -Source mt5 -EnableDemo
:finish
pause
endlocal

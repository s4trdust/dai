@echo off
rem Double-click to put the DC Motor Speed Controller showcase item into the library.
cd /d "%~dp0.."
python showcase\showcase_item.py %*
echo.
pause

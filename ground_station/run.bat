@echo off
rem GOLbase - start. The first run installs the libraries (numpy, sounddevice, pyserial).
cd /d "%~dp0"
where python >nul 2>nul || (echo Python not found. Install it from python.org ^(tick "Add python.exe to PATH"^) & pause & exit /b)
python -c "import numpy, sounddevice, serial" 2>nul || python -m pip install --user numpy sounddevice pyserial
start "" pythonw golbase.py

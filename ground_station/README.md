# GOLbase - ground station program for the R20 / GOLkf tracker

A Windows program (Python + Tkinter) that talks to the balloon over FT8 through an ordinary HF transceiver.
It is the ground side of the GOLkf firmware. **The user interface is in Polish.**

**Status: the protocol and log code are covered by tests (`test_robot.py`, `test_qo.py`); the balloon tab has only been
exercised against the firmware core in simulation, never against a real R20 board.**

## What it does
- **"FT8 balon" tab** - decodes the balloon's data frames (status, log of contacts), keeps the list of the balloon's contacts,
  asks for missing log entries, sends signed commands (band + WSPR channel, callsigns, fixed locator, mode, power thresholds,
  no-transmit zones, TX on/off). After each command it sends a normal FT8 frame with the operator's callsign.
- **Balloon contacts go to an ADIF file** `robot_<balloon call>_log.adi` (STATION_CALLSIGN = balloon, OPERATOR = you).
  Sending them to Log4OM over UDP is optional (a checkbox in the "new contacts" window, off by default).
- **"FT8 QO-100" tab** - ordinary FT8 contacts through the QO-100 satellite with correct uplink/downlink frequencies in the log.
- **CW** - CW decoder with waterfall and CW transmit through CI-V (written for the IC-7300).
- Your own contacts are saved to `golbase_log.adi`; Log4OM (UDP, same message as WSJT-X "Logged ADIF") is optional.

## Radio
- Icom IC-7300 directly over CI-V (USB), or any radio through **OmniRig** (Rig 1 / Rig 2).
- Audio through the radio's USB sound card.

## Run from source (Windows)
1. Python 3.10+ from python.org ("Add python.exe to PATH").
2. Build the FT8 library once: in an MSYS2/MinGW shell run `ft8/buduj.sh` - it downloads kgoba/ft8_lib (MIT, pinned version)
   and builds `ft8shim.dll` next to the program. Without it the FT8 tabs show an error; CW still works.
3. Double-click `run.bat` (installs numpy, sounddevice, pyserial on first run). For OmniRig also `pip install pywin32`.

Settings are stored in `golbase.json` next to the script (or in `Documents\GOLbase` for a packaged build).

## First setup
- Set **your callsign** and locator in the settings (the defaults are placeholders: `N0CALL`, `AA00AA`, balloon `QQ0Q`).
- **Command key**: the "FT8 balon" tab creates `robot_klucz.txt` (16 random bytes) on first use. Write the same key into
  the tracker over USB with the console command `klucz <32 hex chars>`. Keep the file private - whoever has it can command the balloon.
- The balloon only accepts a command in the window it was signed for, so the PC clock must be right (NTP).

## Files
`golbase.py` (main window, CW), `ft8_tab.py` (balloon), `ft8_qo_tab.py` + `ft8_qso.py` (QO-100 FT8), `robot_proto.py` (frame and
command format, version 1), `robot_log.py` (balloon log), `ft8silnik.py` + `ft8/ft8shim.c` (FT8 encode/decode via ft8_lib),
`civ.py`, `omnirig.py` (radio control), `logbook.py` (ADIF, Log4OM UDP), `wsjtx_udp.py` (decodes for GridTracker),
`kraje.py` (DXCC from cty.dat), `motyw.py` (dark theme).

## Tests
`./ft8/buduj.sh && python3 test_robot.py && python3 test_qo.py` (Linux builds `libft8shim.so`).

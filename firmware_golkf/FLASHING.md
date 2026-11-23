# GOLkf v0.2 for the R20 board - building, flashing, first power-up

**Status: written and compiled, never run on hardware.** Only the parts that do not touch hardware were tested on a PC
(see "What was tested"). Expect several rounds of fixes on the first real board.

Folders: `rdzen/` - hardware-independent core (logic), `sprzet/` - hardware layer for the RP2354A on R20 (Pico SDK 2.3.1),
`uf2/` - prebuilt images with placeholder callsigns.

## Build
```
cd sprzet && ./buduj.sh
```
Needs `cmake`, `gcc-arm-none-eabi`, `libnewlib-arm-none-eabi`. The script downloads Pico SDK 2.3.1 and kgoba/ft8_lib (pinned).
Result: `wynik/golkf_r20_v02.uf2` and `wynik/golkf_r20_v02_zapasowy.uf2` (fallback, see below).

## Flash
PROG tab on the board: `B0`, `EN`, `V+`, `D+`, `D-`, `G`.
1. Connect a USB cable to the tab (V+ = 5 V, D+, D-, G).
2. **Short `B0` to `G`**, then plug USB into the computer. Release `B0`.
3. A drive named **RP2350** appears. Copy `golkf_r20_v02.uf2` onto it. The drive disappears and the board starts.
4. A USB serial port appears. Open it with any terminal (speed does not matter), press Enter, type `pomoc` (help; commands are in Polish).
5. Later updates: console command `wgraj` brings the RP2350 drive back without shorting `B0`.

## After flashing the tracker does NOT transmit
Bench mode (`praca 0`) is the default: nothing is transmitted on its own, GPS is on, the console works.
Only the commands marked NADAJE transmit (`test nosna`, `test ft8`, `test wspr`) - use a dummy load.
Set your callsigns first: `znak ft8 <CALL>` and `znak wspr <CALL>` (the images contain placeholders `QQ0Q` / `QQ0QQQ`).
Autonomous operation: `praca 1` (remembered after power-off).

## First power-up, in this order
Before flashing, with a current-limited supply (about 100 mA) on `V+`: measure **3.3 V** and the core rail (**1.1 V** at U8).
1. `stan` - version and settings. `test napiecia` - panel input voltage and temperature.
2. `test si` - does the Si5351 answer on I2C and see the TCXO.
3. `test gps 60` - NMEA sentences; after a fix `stan` shows time, position and locator.
4. `test odbior` - 15 s of reception on 14.074 MHz with an antenna. Prints ADC range, I and Q levels, I-Q correlation and decodes.
   - correlation near 0 is good; near +-1 means the local oscillator does not give four phases (fix in `si5351.c`);
   - signals but no decodes: `wstega -1` and try again (sideband sign depends on phase order, unknown without hardware);
   - the mean dt of decodes should be near 0; correct a constant offset with `gpsdt <ms>` (default 50).
5. `test nosna 14074000 10` into a dummy load - check the frequency on a receiver; enter the correction with `tcxo <Hz>`.
6. `test ft8` - one CQ frame; WSJT-X should decode it with DT near 0.
7. `test wspr` - one WSPR frame in the next even minute.
8. `klucz <32 hex chars>` - command key, generated locally, the same on the ground side. Never publish it.
9. Before a flight: `kasuj log`, set callsigns, `praca 1`.

## If the board does not start (no serial port after flashing)
The normal image switches the on-chip regulator of the RP2350 to high impedance at start (the core is fed by the external LDO).
This could not be checked without hardware. If no port appears, enter the bootloader again and flash
`golkf_r20_v02_zapasowy.uf2` - the same program without that step.

## What the hardware layer does
- `main.c` - 15 s window loop; asks the core what to do about 0.25 s before each window; receiver powered 3.5 s before a window; watchdog.
- `si5351.c`, `si_licz.c` - Si5351A + 26 MHz TCXO. TX on CLK0, exact tone spacing (FT8 6.25 Hz, WSPR 1.4648 Hz).
  **Local oscillator: CLK1 = 2 x f on mixer input S0, CLK2 = f on S1** (binary count of 4 phases).
- `odbior.c`, `dsp.c`, `dekoder.c` - ADC reads I and Q alternately (48 kHz per channel, DMA), decimation to 12 kHz,
  90-degree phase shifter -> one sideband -> ft8_lib decoder (up to 70 candidates, done by 14.6 s into the window).
- `nadaj.c`, `wspr.c` - FT8 and WSPR transmit (own WSPR encoder).
- `gps.c` - ATGM336H, RMC and GGA. **No PPS line on the board**: second start = moment the GPS starts sending, minus `gpsdt`.
- `pamiec.c` - last 40 kB of flash: log (16 bytes per entry, up to 2048 entries) and settings.
- `konsola.c` - USB console.

## What was tested (PC only, `sprzet/test/test.sh`)
- Si5351 dividers for 60-6 m, also with the TCXO off by +-4 ppm: tone spacing error below 0.01 Hz;
- receive chain on synthetic I/Q samples: wanted stations decode, the image-sideband one does not; the same audio decodes in
  `jt9` (WSJT-X) with the same reports within 1 dB;
- WSPR encoder: frames decoded by `wsprd` (WSJT-X).

## Not done / not tested
- **Nothing has run on hardware**: I2C, ADC + DMA, GPS, flash writes, USB, window timing.
- **No power saving yet**: the CPU runs at 150 MHz all the time. On solar cells alone this will not be enough.
- 160 m and 80 m (Si5351 divider range), FT4.
- Timing accuracy without PPS, phase order of the local oscillator after a PLL reset, sideband sign, receiver gain and noise.

## Ground side
The ground station program is GOLbase in `../ground_station/`; the frame and command format is `robot_proto.py` (version 1).

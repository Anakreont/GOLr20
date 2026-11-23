#!/bin/bash
# podglad.sh warstwy plik.png [szerokosc]
cd "$(dirname "$0")"
kicad-cli pcb export svg --layers "$1" --page-size-mode 2 --exclude-drawing-sheet -o /tmp/r20.svg pcb/r20.kicad_pcb >/dev/null 2>&1
/usr/bin/python3 -c "import cairosvg; cairosvg.svg2png(url='/tmp/r20.svg', write_to='$2', output_width=${3:-1400}, background_color='white')"

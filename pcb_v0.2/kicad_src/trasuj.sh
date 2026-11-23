#!/bin/bash
# trasuj.sh [przebiegi]: buduje plytke bez stref, trasuje Freeroutingiem (takze mase - sciezkami), importuje, DRC
cd "$(dirname "$0")"
/usr/bin/python3 buduj.py 2>&1 | grep -v leak | tail -2
# wstepne.txt: krotkie polaczenia przy procesorze i zakladka PROG - wlasnym A* przed Freeroutingiem, zablokowane
/usr/bin/python3 polacz.py --blokuj $(cat wstepne.txt | grep -v "^#") 2>&1 | grep -v leak
/usr/bin/python3 -c "
import pcbnew
b=pcbnew.LoadBoard('pcb/r20.kicad_pcb'); pcbnew.ExportSpecctraDSN(b,'pcb/r20.dsn')" 2>&1 | grep -v leak
/usr/bin/python3 dsn_fix.py pcb/r20.dsn
cd pcb && rm -f r20.ses && timeout ${2:-900} xvfb-run -a java -jar /tmp/freerouting.jar -de r20.dsn -do r20.ses -mp ${1:-30} > fr.out 2>&1; cd ..
ls -la pcb/r20.ses || exit 1
/usr/bin/python3 import_drc.py pcb/r20.ses --zastap 2>&1 | grep -v "leak"
./drc_skrot.sh

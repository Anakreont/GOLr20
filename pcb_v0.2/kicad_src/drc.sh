#!/bin/bash
# wypelnia strefy, robi DRC i pokazuje skrot (bez uwag o opisach i bibliotece)
cd "$(dirname "$0")"
/usr/bin/python3 -c "
import pcbnew
b=pcbnew.LoadBoard('pcb/r20.kicad_pcb'); pcbnew.ZONE_FILLER(b).Fill(b.Zones()); pcbnew.SaveBoard('pcb/r20.kicad_pcb',b)
b=pcbnew.LoadBoard('pcb/r20.kicad_pcb')
pcbnew.WriteDRCReport(b,'pcb/drc.txt',pcbnew.EDA_UNITS_MILLIMETRES,True)" 2>&1 | grep -v leak
./drc_skrot.sh ${1:-40}

#!/bin/bash
cd "$(dirname "$0")"
grep -E "^\*\* Found" pcb/drc.txt
grep -E "^\[" pcb/drc.txt | sed 's/\]:.*/]/' | sort | uniq -c | sort -rn | grep -v "lib_footprint\|silk\|courtyard\|text_height"
grep -A4 "^\[unconnected\|^\[clearance\|^\[hole\|^\[copper_edge\|^\[solder_mask\|^\[shorting\|^\[items_not\|^\[tracks_cross\|^\[starved\|^\[via\|^\[annular\|^\[track" pcb/drc.txt | grep "@\|^\[" | cut -c1-130 | head -${1:-40}

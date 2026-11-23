# -*- coding: utf-8 -*-
"""Poprawia plik DSN przed Freeroutingiem: klasa PWR (0,2 mm) dla sieci zasilania i masy."""
import re, sys
p = sys.argv[1]; s = open(p).read()
PWR = ["VSC", "+3V3", "GND", "GPS_VCC", "RF_VCC", "+1V1", "RX_PWR"]
a = s.index("(class kicad_default"); b = s.index("(circuit", a)
names = s[a + len('(class kicad_default ""'):b].split()
keep = [n for n in names if n.strip('"') not in PWR]
s = s[:a] + '(class kicad_default "" ' + " ".join(keep) + "\n      " + s[b:]
if "(class PWR" in s:
    i = s.index("(class PWR"); j = s.index("(circuit", i)
    s = s[:i] + "(class PWR " + " ".join('"%s"' % n if n.startswith("+") else n for n in PWR) + "\n      " + s[j:]
else:
    i = s.index("(class kicad_default"); j = s.index("(circuit", i); k = s.index("    )\n", j) + 6
    blok = s[i:k].replace('(class kicad_default "" ' + " ".join(keep), "(class PWR " + " ".join(PWR))
    blok = re.sub(r"\(width [\d.]+\)", "(width 200)", blok)
    s = s[:k] + "    " + blok.lstrip() + s[k:]
open(p, "w").write(s)

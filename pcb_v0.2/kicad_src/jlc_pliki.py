# -*- coding: utf-8 -*-
"""Pliki dla JLCPCB z pcb/r20.kicad_pcb: Gerbery + wiercenia (zip), BOM, CPL -> katalog jlcpcb/.
Obrot w CPL dla ukladow wielonozkowych (MSOP, TSSOP, VSSOP, SOT-23, SOT-23-5) liczony z polozenia pol 1 i 2:
przyjete, ze w bibliotece JLC przy 0 st. pin 1 jest w lewym dolnym rogu, a rzad pinow 1, 2, ... biegnie w prawo.
Sprawdzone na podgladzie JLC 22.11.2026: U3, U4, U5, U6, U8 zgodne; SOT-23 (Q1, Q2) ma inna konwencje - poprawka nizej."""
import csv, os, subprocess, sys, zipfile, collections, math
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import pcbnew
from projekt import PARTS, PAS
NAZWA = sys.argv[1] if len(sys.argv) > 1 else "R20_v0_2"
PCB = os.path.join(HERE, "pcb", "r20.kicad_pcb"); OUT = os.path.join(HERE, "jlcpcb")
os.makedirs(OUT + "/gerber", exist_ok=True)
for f in os.listdir(OUT + "/gerber"): os.remove(OUT + "/gerber/" + f)
layers = "F.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts"
subprocess.run(["kicad-cli", "pcb", "export", "gerbers", "-o", OUT + "/gerber/", "-l", layers, "--subtract-soldermask", "--no-x2", PCB], check=True, capture_output=True)
subprocess.run(["kicad-cli", "pcb", "export", "drill", "-o", OUT + "/gerber/", "--format", "excellon", "--drill-origin", "absolute",
                "--excellon-units", "mm", "--excellon-separate-th", "--generate-map", "--map-format", "gerberx2", PCB], check=True, capture_output=True)
zp = "%s/%s_gerber.zip" % (OUT, NAZWA)
with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted(os.listdir(OUT + "/gerber")): z.write(OUT + "/gerber/" + f, f)
dane = {r[0]: (r[2], r[3], r[1]) for r in PARTS}; dane.update({r[0]: (r[2], r[3], r[1]) for r in PAS})
WIELO = ("MSOP-10", "TSSOP-16", "VSSOP-8", "SOT-23-5", "SOT-23")
b = pcbnew.LoadBoard(PCB); rows, bom, popr = [], collections.OrderedDict(), []
for fp in sorted(b.GetFootprints(), key=lambda f: (f.GetReference()[0], int("".join(c for c in f.GetReference() if c.isdigit()) or 0))):
    ref = fp.GetReference()
    if ref not in dane or dane[ref][0].startswith("NC") or not dane[ref][1]: continue
    pos = fp.GetPosition(); rot = fp.GetOrientationDegrees() % 360
    if dane[ref][2] in WIELO:
        p = {q.GetNumber(): q.GetPosition() for q in fp.Pads()}
        kier = math.degrees(math.atan2(-(p["2"].y - p["1"].y), p["2"].x - p["1"].x)) % 360     # kierunek pin 1 -> pin 2 na plytce (os Y w gore)
        if dane[ref][2] == "SOT-23": kier -= 90      # SOT-23 (C10487) ma w bibliotece JLC przy 0 st. piny 1, 2 w prawej kolumnie, pin 1 na dole (podglad JLC 22.11)
        nowy = round(kier / 90) * 90 % 360
        popr.append("%s %s: KiCad %d -> CPL %d" % (ref, dane[ref][2], rot, nowy)); rot = nowy
    rows.append([ref, "%.3f" % pcbnew.ToMM(pos.x), "%.3f" % -pcbnew.ToMM(pos.y), "Bottom" if fp.IsFlipped() else "Top", "%.1f" % rot])
    bom.setdefault(dane[ref][1], {"v": dane[ref][0].split(" (")[0], "fp": dane[ref][2], "refs": []})["refs"].append(ref)
with open("%s/CPL_%s.csv" % (OUT, NAZWA), "w", newline="") as f:
    w = csv.writer(f); w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"]); w.writerows(rows)
with open("%s/BOM_%s.csv" % (OUT, NAZWA), "w", newline="") as f:
    w = csv.writer(f); w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
    for l, e in bom.items(): w.writerow([e["v"], ",".join(e["refs"]), e["fp"], l])
print("\n".join(popr))
print("spod:", [r[0] for r in rows if r[3] == "Bottom"])
print("gerber zip:", zp, os.path.getsize(zp), "B; elementow w CPL:", len(rows), "; pozycji BOM:", len(bom))

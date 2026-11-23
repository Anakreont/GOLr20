# -*- coding: utf-8 -*-
"""Po trasowaniu: wylewa mase na gorze i na spodzie (masa jest tez poprowadzona sciezkami - wylewki sa dodatkiem),
zszywa obie wylewki przelotkami GND co ok. 2,5 mm, wypelnia i robi DRC. Uruchamiac raz, po dokonczeniu polaczen."""
import os, sys, math, pcbnew
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from uklad import W, H
P = os.path.join(HERE, "pcb", "r20.kicad_pcb"); OX = OY = 100.0
mm = pcbnew.FromMM
b = pcbnew.LoadBoard(P)
gnd = b.GetNetsByName()["GND"]
for z in list(b.Zones()):
    if not z.GetIsRuleArea(): b.Remove(z)
def zone(layer):
    z = pcbnew.ZONE(b); z.SetLayer(layer); z.SetNet(gnd); o = z.Outline(); o.NewOutline()
    for x, y in [(0.2, 0.2), (W - 0.2, 0.2), (W - 0.2, H - 0.2), (0.2, H - 0.2)]: o.Append(mm(OX + x), mm(OY + y))
    z.SetLocalClearance(mm(0.2)); z.SetMinThickness(mm(0.2)); z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
    z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS); z.SetThermalReliefGap(mm(0.2)); z.SetThermalReliefSpokeWidth(mm(0.25)); b.Add(z); return z
for f in b.GetFootprints():          # otwory masy (ogniwa -, antena GND, zlacze): pelne polaczenie z wylewka zamiast mostkow
    for p in f.Pads():
        if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH and p.GetNetname() == "GND": p.SetZoneConnection(pcbnew.ZONE_CONNECTION_FULL)
zf, zb = zone(pcbnew.F_Cu), zone(pcbnew.B_Cu)
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
ff, fb = zf.GetFilledPolysList(pcbnew.F_Cu), zb.GetFilledPolysList(pcbnew.B_Cu)
holes = [(t.GetPosition().x, t.GetPosition().y) for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T]
pads = []
for f in b.GetFootprints():
    for p in f.Pads():
        bb = p.GetBoundingBox()
        if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD: pads.append((bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom()))
        else: holes.append((p.GetPosition().x, p.GetPosition().y))
R = [(mm(0.5) * math.cos(a * math.pi / 6), mm(0.5) * math.sin(a * math.pi / 6)) for a in range(12)] + [(0, 0)]
def wolne(x, y):
    for dx, dy in R:
        v = pcbnew.VECTOR2I(int(x + dx), int(y + dy))
        if not (ff.Contains(v) and fb.Contains(v)): return False
    if any(math.hypot(x - hx, y - hy) < mm(1.2) for hx, hy in holes): return False
    m = mm(0.55)
    return not any(l - m < x < r + m and t - m < y < bt + m for l, t, r, bt in pads)
dod = 0; krok = 2.5
yy = 1.0
while yy < H - 0.9:
    xx = 1.0
    while xx < W - 0.9:
        ok = None
        for dx, dy in [(0, 0), (0.4, 0), (-0.4, 0), (0, 0.4), (0, -0.4), (0.4, 0.4), (-0.4, -0.4), (0.8, 0), (0, 0.8), (-0.8, 0), (0, -0.8)]:
            x, y = mm(OX + xx + dx), mm(OY + yy + dy)
            if wolne(x, y): ok = (x, y); break
        if ok:
            v = pcbnew.PCB_VIA(b); v.SetPosition(pcbnew.VECTOR2I(*ok)); v.SetWidth(mm(0.6)); v.SetDrill(mm(0.3))
            v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu); v.SetNet(gnd); b.Add(v); holes.append(ok); dod += 1
        xx += krok
    yy += krok
pcbnew.ZONE_FILLER(b).Fill(b.Zones()); pcbnew.SaveBoard(P, b)
b = pcbnew.LoadBoard(P)
pcbnew.WriteDRCReport(b, os.path.join(HERE, "pcb", "drc.txt"), pcbnew.EDA_UNITS_MILLIMETRES, True)
for z in b.Zones():
    if z.GetIsRuleArea(): continue
    fp = z.GetFilledPolysList(z.GetLayer()); print(b.GetLayerName(z.GetLayer()), "wysp:", fp.OutlineCount(), "pole mm2: %.0f" % (sum(fp.Outline(k).Area() for k in range(fp.OutlineCount())) / 1e12))
print("przelotek zszywajacych:", dod)

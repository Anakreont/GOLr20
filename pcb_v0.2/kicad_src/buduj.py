# -*- coding: utf-8 -*-
"""Buduje pcb/r20.kicad_pcb z projekt.py + uklad.py (KiCad 7, pcbnew). Opcje: --strefy (masa takze na gorze)."""
import sys, os, pcbnew
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import projekt as P
from uklad import *
OX, OY = 100.0, 100.0
mm = pcbnew.FromMM
b = pcbnew.BOARD(); b.SetCopperLayerCount(2)
ds = b.GetDesignSettings(); ds.SetBoardThickness(mm(0.8))     # wariant A (decyzja autora 21.11 18:13): 0,8 mm, montaz Economic
ds.m_TrackMinWidth = mm(0.127); ds.m_MinClearance = mm(0.127); ds.m_HoleClearance = mm(0.2); ds.m_HoleToHoleMin = mm(0.25)
ds.m_ViasMinSize = mm(0.6); ds.m_MinThroughDrill = mm(0.3); ds.m_CopperEdgeClearance = mm(0.3)
nc = ds.m_NetSettings.m_DefaultNetClass
nc.SetTrackWidth(mm(0.15)); nc.SetClearance(mm(0.127)); nc.SetViaDiameter(mm(0.6)); nc.SetViaDrill(mm(0.3))
PWR = pcbnew.NETCLASS("PWR"); PWR.SetTrackWidth(mm(0.2)); PWR.SetClearance(mm(0.127)); PWR.SetViaDiameter(mm(0.6)); PWR.SetViaDrill(mm(0.3))
ds.m_NetSettings.m_NetClasses["PWR"] = PWR
PWR_NETS = {"VSC", "+3V3", "GND", "GPS_VCC", "RF_VCC", "+1V1", "ANT", "ANT_F", "TX_OUT", "GPS_ANT"}
nets = {}
def net(name):
    if name is None: return None
    if name not in nets:
        n = pcbnew.NETINFO_ITEM(b, name); b.Add(n); nets[name] = n
        if name in PWR_NETS: n.SetNetClass(PWR)
    return nets[name]
FP = {}
def place(ref, fpdef, value, x, y, rot, lcsc=None):
    fp = pcbnew.FootprintLoad(fpdef[0], fpdef[1])
    if fp is None: raise SystemExit("brak footprintu " + str(fpdef))
    fp.SetReference(ref); fp.SetValue(value); b.Add(fp)
    fp.SetLocalClearance(0)                      # MSOP-10 z biblioteki ma wpisany odstep 0,2 mm - obowiazuja reguly plytki
    fp.SetPosition(pcbnew.VECTOR2I(mm(OX + x), mm(OY + y))); fp.SetOrientationDegrees(rot)
    fp.Reference().SetLayer(pcbnew.F_Fab); fp.Reference().SetTextSize(pcbnew.VECTOR2I(mm(0.45), mm(0.45))); fp.Reference().SetTextThickness(mm(0.07))
    fp.Reference().SetPosition(fp.GetPosition()); fp.Value().SetVisible(False)
    for g in fp.GraphicalItems():
        if g.GetClass() == "MTEXT" or "TEXT" in g.GetClass(): g.SetVisible(False)   # zdublowane napisy ${REFERENCE}
    FP[ref] = (fp, lcsc); return fp
for ref, fpn, val, lcsc, pads in P.PARTS:
    x, y, rot = POS[ref]; fp = place(ref, FPMAP[fpn], val, x, y, rot, lcsc)
    if val.startswith("NC"): fp.SetAttributes(fp.GetAttributes() | pcbnew.FP_EXCLUDE_FROM_BOM | pcbnew.FP_EXCLUDE_FROM_POS_FILES | getattr(pcbnew, "FP_DNP", 0))
    for p in fp.Pads():
        try: num = int(p.GetNumber())
        except ValueError: continue
        n = pads.get(num)
        if n: p.SetNet(net(n))
for ref, fpn, val, lcsc, n1, n2 in P.PAS:
    x, y, rot = POS[ref]
    fpd = FPMAP[fpn] if ref[0] == "C" else (R0402 if fpn == "0402" else R0603)
    fp = place(ref, fpd, val, x, y, rot, lcsc if not val.startswith("NC") else None)
    if val.startswith("NC"): fp.SetAttributes(fp.GetAttributes() | pcbnew.FP_EXCLUDE_FROM_BOM | pcbnew.FP_EXCLUDE_FROM_POS_FILES | getattr(pcbnew, "FP_DNP", 0))
    for p in fp.Pads(): p.SetNet(net(n1 if p.GetNumber() == "1" else n2))
def napis(txt, x, y, h=0.7, ang=0, layer=pcbnew.F_SilkS):
    t = pcbnew.PCB_TEXT(b); t.SetText(txt); t.SetLayer(layer); t.SetMirrored(layer == pcbnew.B_SilkS)
    t.SetTextSize(pcbnew.VECTOR2I(mm(h), mm(h))); t.SetTextThickness(mm(max(0.1, 0.15 * h))); t.SetTextAngleDegrees(ang)
    t.SetPosition(pcbnew.VECTOR2I(mm(OX + x), mm(OY + y))); b.Add(t)
def otwor(ref, x, y, drill, pad, netname=None, npth=False):
    fp = pcbnew.FOOTPRINT(b); fp.SetReference(ref); fp.Reference().SetVisible(False); fp.Value().SetVisible(False)
    fp.SetAttributes(pcbnew.FP_EXCLUDE_FROM_BOM | pcbnew.FP_EXCLUDE_FROM_POS_FILES | (pcbnew.FP_BOARD_ONLY if npth else 0))
    p = pcbnew.PAD(fp); p.SetNumber("" if npth else "1")
    p.SetAttribute(pcbnew.PAD_ATTRIB_NPTH if npth else pcbnew.PAD_ATTRIB_PTH); p.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
    p.SetSize(pcbnew.VECTOR2I(mm(pad), mm(pad))); p.SetDrillSize(pcbnew.VECTOR2I(mm(drill), mm(drill)))
    ls = pcbnew.LSET.AllCuMask(); ls.AddLayer(pcbnew.F_Mask); ls.AddLayer(pcbnew.B_Mask); p.SetLayerSet(ls)
    fp.Add(p); b.Add(fp); fp.SetPosition(pcbnew.VECTOR2I(mm(OX + x), mm(OY + y)))
    if netname: p.SetNet(net(netname))
    FP[ref] = (fp, None); return fp
PADNET = {n: s for n, s, o in P.PADS}
for i, (x, y) in enumerate(HOLES_NPTH): otwor("H%d" % (i + 1), x, y, 1.0, 1.0, npth=True)
for name, (x, y) in PTH.items(): otwor(name, x, y, PTH_DRILL, PTH_PAD, PADNET[name[:-1] if name.endswith("2") else name])
napis("ANT", PTH["ANT"][0] - 2.2, PTH["ANT"][1], 0.8); napis("GPS", PTH["GPS_ANT"][0] - 2.0, PTH["GPS_ANT"][1], 0.8)
napis("+", PTH["PV+"][0], PTH["PV+"][1] - 1.25, 0.9); napis("-", PTH["PV-"][0], PTH["PV-"][1] - 1.25, 0.9)
napis("GND", PTH["ANT_GND"][0] - 2.0, PTH["ANT_GND"][1], 0.8)
otwor("STAB", STAB[0], STAB[1], 0.8, 2.2)
for name, (x, y) in SC.items():
    fp = pcbnew.FootprintLoad(STD + "TestPoint.pretty", "TestPoint_Pad_2.0x2.0mm"); fp.SetReference(name); fp.Reference().SetVisible(False); fp.Value().SetVisible(False)
    fp.SetAttributes(fp.GetAttributes() | pcbnew.FP_EXCLUDE_FROM_BOM | pcbnew.FP_EXCLUDE_FROM_POS_FILES); b.Add(fp)
    fp.SetPosition(pcbnew.VECTOR2I(mm(OX + x), mm(OY + y))); fp.Flip(fp.GetPosition(), False)
    for p in fp.Pads(): p.SetNet(net(PADNET[name]))
    napis(name, x, y + 1.8, 0.8, layer=pcbnew.B_SilkS); FP[name] = (fp, None)
for k, y in enumerate(MOUSE): otwor("MB%d" % (k + 1), MOUSE_X, y, 0.5, 0.5, npth=True)
j = pcbnew.FootprintLoad(STD + "Connector_PinHeader_2.54mm.pretty", "PinHeader_2x03_P2.54mm_Vertical")
j.SetReference("J1"); j.SetValue("PROG 2x3"); j.Reference().SetVisible(False); j.Value().SetVisible(False)
j.SetAttributes(j.GetAttributes() | pcbnew.FP_EXCLUDE_FROM_BOM | pcbnew.FP_EXCLUDE_FROM_POS_FILES)
b.Add(j); j.SetPosition(pcbnew.VECTOR2I(mm(OX + J1["x"]), mm(OY + J1["y"]))); FP["J1"] = (j, None)
JP = {int(n.split(".")[1]): (s, o) for n, s, o in P.PADS if n.startswith("J1.")}
for p in j.Pads():
    n_, opis = JP[int(p.GetNumber())]; p.SetNet(net(n_))
    px, py = p.GetPosition().x / 1e6 - OX, p.GetPosition().y / 1e6 - OY
    napis(opis, px - 1.32 if int(p.GetNumber()) % 2 else px + 1.32, py, 0.8, 90)
napis("PROG", (TAB["x0"] + TAB["x1"]) / 2, TAB["y1"] - 0.9, 0.8)
napis(P.NAPIS, W / 2, 20.0, 1.0, layer=pcbnew.B_SilkS)
def seg(x1, y1, x2, y2):
    s = pcbnew.PCB_SHAPE(b); s.SetShape(pcbnew.SHAPE_T_SEGMENT); s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(mm(0.1))
    s.SetStart(pcbnew.VECTOR2I(mm(OX + x1), mm(OY + y1))); s.SetEnd(pcbnew.VECTOR2I(mm(OX + x2), mm(OY + y2))); b.Add(s)
def arc(cx, cy, sx, sy, ang):
    s = pcbnew.PCB_SHAPE(b); s.SetShape(pcbnew.SHAPE_T_ARC); s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(mm(0.1))
    s.SetCenter(pcbnew.VECTOR2I(mm(OX + cx), mm(OY + cy))); s.SetStart(pcbnew.VECTOR2I(mm(OX + sx), mm(OY + sy)))
    s.SetArcAngleAndEnd(pcbnew.EDA_ANGLE(ang, pcbnew.DEGREES_T)); b.Add(s)
r = 1.0
seg(r, 0, W - r, 0); seg(0, r, 0, H - r); seg(W - r, H, r, H)
_p = [(W, r), (W, BRIDGE["y0"]), (TAB["x0"], BRIDGE["y0"]), (TAB["x0"], TAB["y0"]), (TAB["x1"], TAB["y0"]),
      (TAB["x1"], TAB["y1"]), (TAB["x0"], TAB["y1"]), (TAB["x0"], BRIDGE["y1"]), (W, BRIDGE["y1"]), (W, H - r)]
for _a, _c in zip(_p, _p[1:]): seg(_a[0], _a[1], _c[0], _c[1])
arc(r, r, 0, r, 90); arc(W - r, r, W - r, 0, 90); arc(W - r, H - r, W, H - r, 90); arc(r, H - r, r, H, 90)
# przelotki masy w polu srodkowym procesora
_u1 = FP["U1"][0].GetPosition()
for dx, dy in EP_VIAS:
    v = pcbnew.PCB_VIA(b); v.SetPosition(pcbnew.VECTOR2I(_u1.x + mm(dx), _u1.y + mm(dy))); v.SetWidth(mm(0.6)); v.SetDrill(mm(0.3))
    v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu); v.SetNet(net("GND")); v.SetLocked(True); b.Add(v)
def zone(layer, netname):
    z = pcbnew.ZONE(b); z.SetLayer(layer); z.SetNet(net(netname)); o = z.Outline(); o.NewOutline()
    for x, y in [(0.2, 0.2), (W - 0.2, 0.2), (W - 0.2, H - 0.2), (0.2, H - 0.2)]: o.Append(mm(OX + x), mm(OY + y))
    z.SetLocalClearance(mm(0.15)); z.SetMinThickness(mm(0.15)); z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
    z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS); z.SetThermalReliefGap(mm(0.2)); z.SetThermalReliefSpokeWidth(mm(0.2)); b.Add(z)
if "--strefy" in sys.argv: zone(pcbnew.B_Cu, "GND"); zone(pcbnew.F_Cu, "GND")
# obszary zakazu sciezek i przelotek przy krawedziach i w rogach (Freerouting nie zna odstepu 0,3 mm od krawedzi ani lukow w rogach)
def zakaz(pts):
    z = pcbnew.ZONE(b); z.SetIsRuleArea(True); z.SetDoNotAllowTracks(True); z.SetDoNotAllowVias(True); z.SetDoNotAllowCopperPour(False)
    z.SetDoNotAllowPads(False); z.SetDoNotAllowFootprints(False)
    z.SetLayerSet(pcbnew.LSET.AllCuMask(2)); o = z.Outline(); o.NewOutline()
    for x, y in pts: o.Append(mm(OX + x), mm(OY + y))
    b.Add(z)
if "--strefy" not in sys.argv:
    k_ = 0.19
    zakaz([(-0.3, 0), (k_, 0), (k_, H), (-0.3, H)]); zakaz([(0, -0.3), (W, -0.3), (W, k_), (0, k_)]); zakaz([(0, H - k_), (W, H - k_), (W, H + 0.3), (0, H + 0.3)])
    zakaz([(W - k_, 0), (W + 0.3, 0), (W + 0.3, BRIDGE["y0"] - 0.1), (W - k_, BRIDGE["y0"] - 0.1)])
    zakaz([(W - k_, BRIDGE["y1"] + 0.1), (W + 0.3, BRIDGE["y1"] + 0.1), (W + 0.3, H), (W - k_, H)])
    for cx, cy, sx, sy in [(0, 0, 1, 1), (W, 0, -1, 1), (W, H, -1, -1), (0, H, 1, -1)]:
        zakaz([(cx, cy), (cx + sx * 1.6, cy), (cx, cy + sy * 1.6)])
os.makedirs(os.path.join(HERE, "pcb"), exist_ok=True)
out = os.path.join(HERE, "pcb", "r20.kicad_pcb"); pcbnew.SaveBoard(out, b)
print("plytka %.1f x %.1f mm" % (W, H))
# --- kontrola: kolizje obrysow elementow i odleglosc od krawedzi ---
import itertools
def bbox(fp):
    bb = fp.GetBoundingBox(False, False); return (pcbnew.ToMM(bb.GetLeft()) - OX, pcbnew.ToMM(bb.GetTop()) - OY, pcbnew.ToMM(bb.GetRight()) - OX, pcbnew.ToMM(bb.GetBottom()) - OY)
BB = {r: bbox(f) for r, (f, l) in FP.items() if r in POS}
kol = 0
for (a, ba), (c, bc) in itertools.combinations(BB.items(), 2):
    ox = min(ba[2], bc[2]) - max(ba[0], bc[0]); oy = min(ba[3], bc[3]) - max(ba[1], bc[1])
    if ox > 0.02 and oy > 0.02: print("KOLIZJA %s / %s: %.2f x %.2f mm" % (a, c, ox, oy)); kol += 1
for r_, bb_ in BB.items():
    if bb_[0] < 0.25 or bb_[1] < 0.25 or bb_[2] > W - 0.25 or bb_[3] > H - 0.25: print("KRAWEDZ %s: %s" % (r_, ["%.2f" % v for v in bb_])); kol += 1
brak = [r for r, *_ in P.PARTS if r not in POS] + [x[0] for x in P.PAS if x[0] not in POS]
print("zapisano %s; elementow %d, sieci %d, kolizji/uwag %d, bez polozenia: %s" % (out, len(BB), len(nets), kol, brak))

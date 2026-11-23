# -*- coding: utf-8 -*-
"""Dotrasowanie wskazanych polaczen pole-pole wlasnym A* (gora / spod + przelotki 0,6/0,3).
uzycie: /usr/bin/python3 polacz.py J1.1:R4.2[:szerokosc] ...   opcja --usun=SIEC1,SIEC2 kasuje najpierw sciezki tych sieci."""
import math, heapq, sys, os
import numpy as np
import pcbnew
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from uklad import TAB, BRIDGE as BR, W, H
P = os.path.join(HERE, "pcb", "r20.kicad_pcb")
OX = OY = 100.0
mm = lambda v: int(round(v * 1e6))
V = lambda x, y: pcbnew.VECTOR2I(mm(x + OX), mm(y + OY))
u = lambda v: v / 1e6
b = pcbnew.LoadBoard(P)
NETS = b.GetNetsByName()
def padof(ref, num="1"):
    return [p for p in b.FindFootprintByReference(ref).Pads() if p.GetNumber() == num][0]
JOBS = []; BLOKUJ = "--blokuj" in sys.argv
for a in sys.argv[1:]:
    if a == "--blokuj": continue
    if a.startswith("--usun="):
        for t in list(b.GetTracks()):
            if t.GetNetname() in set(a[7:].split(",")) and not t.IsLocked(): b.Delete(t)
        continue
    q = a.split(":"); s1, s2 = q[0].split("."), q[1].split(".")
    JOBS.append((padof(*s1), padof(*s2), float(q[2]) if len(q) > 2 else 0.15))
    if JOBS[-1][0].GetNetname() != JOBS[-1][1].GetNetname(): raise SystemExit('rozne sieci: %s (%s / %s)' % (a, JOBS[-1][0].GetNetname(), JOBS[-1][1].GetNetname()))
RNETS = {j[0].GetNetname() for j in JOBS}
RES, CLR, HCLR, ECLR, VIAD = 0.025, 0.14, 0.22, 0.3, 0.6
LAYS = [pcbnew.F_Cu, pcbnew.B_Cu]; NL = 2
LCOST = [1.0, 1.2]
x0, y0, x1, y1 = -0.1, -0.1, TAB["x1"] + 0.1, H + 0.1
nx, ny = int((x1 - x0) / RES) + 1, int((y1 - y0) / RES) + 1
X, Y = np.meshgrid(x0 + np.arange(nx) * RES, y0 + np.arange(ny) * RES, indexing="ij")
D = np.full((NL, nx, ny), 99.0, np.float32)
PADX = {n: np.full((NL, nx, ny), 99.0, np.float32) for n in RNETS}
def seg_dist(ax, ay, bx, by):
    dx, dy = bx - ax, by - ay; L2 = dx * dx + dy * dy
    if L2 < 1e-12: return np.hypot(X - ax, Y - ay)
    t = np.clip(((X - ax) * dx + (Y - ay) * dy) / L2, 0, 1)
    return np.hypot(X - (ax + t * dx), Y - (ay + t * dy))
def rect_dist(l, t, r, bt):
    return np.hypot(np.maximum(np.maximum(l - X, 0), X - r), np.maximum(np.maximum(t - Y, 0), Y - bt))
def obst(lay, d, net=None):
    tg = [D] if net not in RNETS else [A for n, A in PADX.items() if n != net]
    for T in tg:
        for li in (range(NL) if lay == "all" else [LAYS.index(lay)]): np.minimum(T[li], d, out=T[li])
def obst_track(lay, ax, ay, bx, by, w, net=None):
    obst("all" if lay == "via" else lay, seg_dist(ax, ay, bx, by) - w / 2, net)
for t in b.GetTracks():
    if t.Type() == pcbnew.PCB_VIA_T:
        p = t.GetPosition(); obst_track("via", u(p.x) - OX, u(p.y) - OY, u(p.x) - OX, u(p.y) - OY, u(t.GetWidth()), t.GetNetname())
    elif t.GetLayer() in LAYS:
        s, e = t.GetStart(), t.GetEnd()
        obst_track(t.GetLayer(), u(s.x) - OX, u(s.y) - OY, u(e.x) - OX, u(e.y) - OY, u(t.GetWidth()), t.GetNetname())
def obst_pad(p):
    bb = p.GetBoundingBox(); l, tp, r, bt = u(bb.GetLeft()) - OX, u(bb.GetTop()) - OY, u(bb.GetRight()) - OX, u(bb.GetBottom()) - OY
    c = p.GetPosition()
    if p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
        obst("all", np.hypot(X - (u(c.x) - OX), Y - (u(c.y) - OY)) - u(p.GetDrillSize().x) / 2 - HCLR + CLR); return
    if p.GetShape() == pcbnew.PAD_SHAPE_CIRCLE: d = np.hypot(X - (u(c.x) - OX), Y - (u(c.y) - OY)) - u(p.GetSize().x) / 2
    else: d = rect_dist(l, tp, r, bt)
    th = p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH; n = p.GetNetname()
    for li, L in enumerate(LAYS):
        if th or p.IsOnLayer(L):
            for nn_, A in PADX.items():
                if nn_ != n: np.minimum(A[li], d, out=A[li])
            if n not in RNETS: np.minimum(D[li], d, out=D[li])
for f in b.GetFootprints():
    for p in f.Pads(): obst_pad(p)
# obrys: plytka z zaokraglonymi rogami + mostek + zakladka
r_ = 1.0
dx_, dy_ = np.minimum(X, W - X), np.minimum(Y, H - Y)
glowna = np.where((dx_ < r_) & (dy_ < r_), r_ - np.hypot(r_ - dx_, r_ - dy_), np.minimum(dx_, dy_))
rects = [(W - 3.0, BR["y0"], TAB["x0"] + 3.0, BR["y1"]), (TAB["x0"], TAB["y0"], TAB["x1"], TAB["y1"])]
inside = np.max([glowna] + [np.minimum.reduce([X - a, c - X, Y - bb_, dd - Y]) for a, bb_, c, dd in rects], axis=0)
EDGE = (inside - ECLR + CLR).astype(np.float32)
for li in range(NL): np.minimum(D[li], EDGE, out=D[li])
SMD = np.full((nx, ny), 99.0, np.float32)       # przelotka nie moze wchodzic w pole SMD (takze tej samej sieci)
for f in b.GetFootprints():
    for p in f.Pads():
        if p.GetAttribute() != pcbnew.PAD_ATTRIB_SMD: continue
        bb = p.GetBoundingBox()
        np.minimum(SMD, rect_dist(u(bb.GetLeft()) - OX, u(bb.GetTop()) - OY, u(bb.GetRight()) - OX, u(bb.GetBottom()) - OY), out=SMD)
VIASD = np.full((nx, ny), 99.0, np.float32)     # odleglosc od srodka istniejacych przelotek (takze tej samej sieci) - otwory nie moga na siebie wchodzic
for t in b.GetTracks():
    if t.Type() == pcbnew.PCB_VIA_T:
        p = t.GetPosition(); np.minimum(VIASD, np.hypot(X - (u(p.x) - OX), Y - (u(p.y) - OY)), out=VIASD)
def cell(x, y): return int(round((x - x0) / RES)), int(round((y - y0) / RES))
def route(net, sp, gp, w):
    Dn = np.minimum(D, PADX[net])
    ok = Dn >= w / 2 + CLR - 1e-6
    via_ok = np.all(Dn >= VIAD / 2 + CLR - 1e-6, axis=0) & (EDGE >= VIAD / 2 + CLR) & (SMD >= VIAD / 2 + 0.1) & (VIASD >= VIAD + 0.15)
    sc = sp.GetPosition(); gc = gp.GetPosition()
    si, sj = cell(u(sc.x) - OX, u(sc.y) - OY); gi, gj = cell(u(gc.x) - OX, u(gc.y) - OY)
    on = lambda p, L: p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH or p.IsOnLayer(L)
    starts = [(li, si, sj) for li, L in enumerate(LAYS) if on(sp, L)]
    goals = {(li, gi, gj) for li, L in enumerate(LAYS) if on(gp, L)}
    h = lambda i, j: math.hypot(i - gi, j - gj) * RES
    dist = {}; prev = {}; pq = []
    for s in starts: dist[s] = 0.0; heapq.heappush(pq, (h(s[1], s[2]), 0.0, s))
    dirs = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]
    while pq:
        f_, g, uu = heapq.heappop(pq)
        if g > dist.get(uu, 1e9): continue
        if uu in goals:
            path = [uu]
            while uu in prev: uu = prev[uu]; path.append(uu)
            return path[::-1]
        l, i, j = uu
        for di, dj in dirs:
            a, c = i + di, j + dj
            if not (0 <= a < nx and 0 <= c < ny) or not ok[l, a, c]: continue
            v = (l, a, c); ng = g + math.hypot(di, dj) * RES * LCOST[l] * (1 + 1.0 * (Dn[l, a, c] < w / 2 + CLR + 0.1))
            if ng < dist.get(v, 1e9): dist[v] = ng; prev[v] = uu; heapq.heappush(pq, (ng + h(a, c), ng, v))
        if via_ok[i, j]:
            l2 = 1 - l
            if ok[l2, i, j]:
                v = (l2, i, j); ng = g + 1.5
                if ng < dist.get(v, 1e9): dist[v] = ng; prev[v] = uu; heapq.heappush(pq, (ng + h(i, j), ng, v))
    return None
def commit(path, net, w):
    nn = NETS[net]; P_ = [(x0 + i * RES, y0 + j * RES, l) for (l, i, j) in path]
    segs = []; vias = []; st = P_[0]
    for k in range(1, len(P_)):
        a, c = P_[k - 1], P_[k]
        if c[2] != a[2]:
            if (st[0], st[1]) != (a[0], a[1]): segs.append((st, a))
            vias.append(a); st = c; continue
        if k + 1 < len(P_) and P_[k + 1][2] == c[2]:
            d1 = (round((c[0] - a[0]) / RES), round((c[1] - a[1]) / RES)); n_ = P_[k + 1]
            if d1 == (round((n_[0] - c[0]) / RES), round((n_[1] - c[1]) / RES)): continue
        segs.append((st, c)); st = c
    for v in vias:
        o = pcbnew.PCB_VIA(b); o.SetPosition(V(v[0], v[1])); o.SetWidth(mm(VIAD)); o.SetDrill(mm(0.3))
        o.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu); o.SetNet(nn); o.SetLocked(BLOKUJ); b.Add(o)
        obst_track("via", v[0], v[1], v[0], v[1], VIAD, net); np.minimum(VIASD, np.hypot(X - v[0], Y - v[1]), out=VIASD)
    for s, e in segs:
        t = pcbnew.PCB_TRACK(b); t.SetStart(V(s[0], s[1])); t.SetEnd(V(e[0], e[1])); t.SetWidth(mm(w))
        t.SetLayer(LAYS[s[2]]); t.SetNet(nn); t.SetLocked(BLOKUJ); b.Add(t)
        obst_track(LAYS[s[2]], s[0], s[1], e[0], e[1], w, net)
    return len(segs), len(vias)
zle = 0
for sp, gp, w in JOBS:
    net = sp.GetNetname()
    path = route(net, sp, gp, w)
    if path is None: print("NIE UDALO SIE", net); zle += 1; continue
    print(net, "segm/przel", commit(path, net, w))
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
pcbnew.SaveBoard(P, b)
b = pcbnew.LoadBoard(P)
pcbnew.WriteDRCReport(b, os.path.join(HERE, "pcb", "drc.txt"), pcbnew.EDA_UNITS_MILLIMETRES, True)
print("zapisano, nieudanych:", zle)

# -*- coding: utf-8 -*-
"""Plytka R20 v0.1 - rozmieszczenie (21.11.2026). ref: (x, y, obrot) w mm od lewego gornego rogu plytki. Wszystko na gorze."""
import os as _os
# 21.11.2026 22:50 (decyzja autora): plytka szersza. DXL = przesuniecie lewego bloku, DXR = prawego (wzgledem ukladu 24 mm).
DXL, DXR, MR = [float(v) for v in _os.environ.get("R20_DX", "0.6,3,1").split(",")]     # MR = dodatkowy margines z prawej
W0 = 24.0
W, H = W0 + DXR + MR, 35.6
PRAWE = set("U7 C39 C38 R24 Q2 U1 Y1 C17 C18 R5 C13 R3 C7 C6 C8 C15 C16 R2 C9 C14 C10 C5 R1 R7 R6 C12 R4 C11 U8 C3 C4".split())
STD = "/usr/share/kicad/footprints/"
import os
LOC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib", "r20.pretty")
FPMAP = {"QFN-60-1EP_7x7mm_P0.4mm": (LOC, "RP2354A_QFN-60"), "SOT-23-5": (LOC, "ME6211_SOT23-5"), "SOT-23": (LOC, "SI2301_SOT23"),
         "ATGM336H": (LOC, "ATGM336H"), "MSOP-10": (STD + "Package_SO.pretty", "MSOP-10_3x3mm_P0.5mm"),
         "TSSOP-16": (STD + "Package_SO.pretty", "TSSOP-16_4.4x5mm_P0.65mm"), "VSSOP-8": (STD + "Package_SO.pretty", "VSSOP-8_3.0x3.0mm_P0.65mm"),
         "SMD3225-4P": (STD + "Crystal.pretty", "Crystal_SMD_3225-4Pin_3.2x2.5mm"), "SOD-123": (STD + "Diode_SMD.pretty", "D_SOD-123"),
         "0402": (STD + "Capacitor_SMD.pretty", "C_0402_1005Metric"), "0603": (STD + "Capacitor_SMD.pretty", "C_0603_1608Metric")}
R0402 = (STD + "Resistor_SMD.pretty", "R_0402_1005Metric"); R0603 = (STD + "Resistor_SMD.pretty", "R_0603_1608Metric")
POS = {
 # --- nadajnik: Si5351 + TCXO (lewy gorny rog) ---
 "U3": (6.0, 7.2, 0), "Y2": (2.5, 10.9, 0), "Q1": (8.4, 11.0, 0), "R10": (11.2, 9.0, 90),
 "C21": (5.6, 10.2, 0), "C22": (5.6, 11.6, 0), "R12": (1.2, 6.2, 90), "R11": (1.2, 8.2, 90),
 "C23": (10.4, 5.4, 90), "L2": (8.6, 2.9, 0), "C24": (11.4, 3.9, 90), "C25": (4.2, 3.0, 0), "C26": (2.0, 3.0, 0),
 # --- zasilanie 3,3 V ---
 "D1": (3.0, 14.2, 0), "C1": (6.4, 14.4, 90), "U6": (9.4, 14.4, 0), "C2": (11.6, 17.6, 90),
 # --- GPS (prawy gorny rog) ---
 "U7": (17.6, 8.4, 180), "C39": (13.0, 15.3, 0), "C38": (19.9, 15.3, 0), "R24": (20.9, 19.7, 90), "Q2": (22.9, 17.3, 0),
 # --- odbiornik (lewa strona) ---
 "R13": (1.6, 16.6, 0), "R14": (3.7, 16.6, 0), "C27": (5.8, 16.6, 0), "R15": (7.9, 16.6, 0),
 "U4": (5.7, 20.4, 0), "C36": (10.3, 20.0, 90), "C37": (10.3, 22.0, 90),
 "C28": (2.2, 24.3, 0), "C29": (4.3, 24.3, 0), "C30": (6.4, 24.3, 0), "C31": (8.5, 24.3, 0),
 "C40": (2.2, 25.8, 0), "C42": (4.3, 25.8, 0), "C41": (6.4, 25.8, 0), "C43": (8.5, 25.8, 0),
 "R16": (2.2, 27.3, 0), "R20": (4.3, 27.3, 0), "R17": (6.4, 27.3, 0), "R21": (8.5, 27.3, 0),
 "U5": (5.4, 30.0, 0), "R18": (1.0, 29.0, 90), "C32": (1.0, 31.0, 90), "R22": (9.8, 29.0, 90), "C34": (9.8, 31.0, 90),
 "R19": (1.6, 32.9, 0), "C33": (3.7, 32.9, 0), "R23": (5.8, 32.9, 0), "C35": (7.9, 32.9, 0),
 "R8": (1.6, 34.4, 0), "R9": (3.7, 34.4, 0), "C20": (5.8, 34.4, 0),
 # --- procesor (prawa dolna czesc), U1 obrocony o 180 st.; kondensatory tuz przy swoich pinach (21.11 23:20) ---
 "U1": (16.8, 25.6, 180),
 "C6": (13.4, 20.3, 90), "C13": (16.2, 20.3, 90), "R3": (17.25, 20.3, 90), "C7": (18.6, 20.3, 90),         # nad gornym rzedem pinow
 "Y1": (16.85, 17.15, 90), "C18": (14.15, 16.05, 180), "C17": (19.55, 18.25, 0),     # kwarc obrocony: pole masy nad C13, XIN nad pinem 21
 "R5": (23.3, 23.1, 180),                                                        # podciaganie RUN przy drodze do zakladki PROG
 "C8": (11.6, 24.9, 180), "C15": (11.6, 25.9, 180), "C16": (12.0, 28.7, 270), "R2": (10.9, 28.5, 90), "C11": (11.9, 30.45, 180),
 "C9": (22.6, 24.6, 0), "C14": (22.6, 26.4, 0), "C10": (22.6, 28.4, 0),
 "C5": (13.75, 30.9, 270), "R1": (14.95, 30.9, 90), "R7": (16.0, 31.5, 270), "R6": (17.0, 31.5, 270), "C12": (18.2, 30.9, 270), "R4": (20.6, 30.6, 0),
 "U8": (21.2, 33.6, 0), "C3": (18.4, 33.6, 180), "C4": (23.6, 33.1, 270),
}
POS = {r: (x + (DXR if r in PRAWE else DXL), y, a) for r, (x, y, a) in POS.items()}
# otwory i pola: nazwa: (x, y)
HOLES_NPTH = [(1.2, 1.4), (W - 1.2, 1.4)]                       # nitka do balonu
PTH = {"ANT": (6.0 + DXL, 1.3), "GPS_ANT": (20.9 + DXR, 1.4), "PV+": (W - 1.0, 19.9), "PV+2": (W - 1.0, 21.6), "PV-": (1.0, 19.9), "PV-2": (1.0, 21.6),
       "ANT_GND": (W / 2, 34.3)}
STAB = (W / 2, 1.5)     # otwor metalizowany 0,8 mm bez sieci - drut stabilizujacy panele
PTH_DRILL, PTH_PAD = 0.6, 1.3
SC = {"SC+": (6.0 + DXL, 6.0), "SC-": (18.0 + DXR, 8.0)}        # pola 2x2 mm na spodzie
# zakladka PROG z PRAWEJ strony (blizej USB procesora; z lewej linie USB szlyby przez odbiornik)
TAB = dict(x0=W + 1.0, x1=W + 7.5, y0=23.6, y1=33.2); BRIDGE = dict(y0=24.4, y1=32.4)
MOUSE = [24.9, 26.1, 27.3, 28.4, 29.5, 30.7, 31.9]; MOUSE_X = W
J1 = dict(x=W + 2.98, y=25.6)                                    # goldpin 2x3, uklad pinow jak T433: 1 B0, 2 EN, 3 V+, 4 D+, 5 D-, 6 G
EP_VIAS = [(-0.9, -0.9), (0.9, -0.9), (-0.9, 0.9), (0.9, 0.9)]    # przelotki masy w polu srodkowym U1 (jedyna masa procesora)

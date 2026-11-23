#!/usr/bin/env python3
"""Tracker-robot FT8: bilans pradu na 6 ogniwach 52 x 23 mm (szeregowo, plasko) i masa calosci. 21.11.2026.
Model zgrubny - wszystkie prady elementow to wartosci typowe z kart / z pamieci, NIE pomiary. Uruchom: python3 bilans.py"""
import math

# ---------- ogniwa ----------
A_REF, I_REF = 52 * 26, 400.0      # oferta AliExpress z notatek: 52 x 26 mm, 0,5 V, 400 mA przy 1000 W/m2 (dane sprzedawcy)
A = 52 * 23                         # mm2 jednego ogniwa; 6 szeregowo -> prad = prad jednego ogniwa, napiecie ok. 3,0-3,6 V
def naslonecznienie(h):             # W/m2 wiazki bezposredniej na 13 km: masa powietrza = 0,16 / sin(h)
    return 1361 * 0.7 ** ((0.16 / math.sin(math.radians(h))) ** 0.678)
def iam(h):                         # straty odbicia przy plaskim padaniu (ASHRAE b0 = 0,05), kat padania = 90 - h
    return max(0.0, 1 - 0.05 * (1 / math.sin(math.radians(h)) - 1))
def prad(h, wsp, a=A):              # mA z panelu plasko przy wysokosci Slonca h
    return I_REF * a / A_REF * wsp * naslonecznienie(h) / 1000 * math.sin(math.radians(h)) * iam(h)
# wspolczynnik "ostrozny" dopasowany do lotow: trackery na 6 x 52 x 19 plasko ruszaja przy Sloncu 16-18 st.,
# a potrzebuja wtedy ok. 40 mA (GPS szuka + procesor) -> prad(17 st., 52x19) = 40 mA
WSP_OSTR = 40 / (I_REF * (52 * 19) / A_REF * naslonecznienie(17) / 1000 * math.sin(math.radians(17)) * iam(17))
WSP_OPT = 0.8                       # "optymistyczny": dane sprzedawcy x 0,8

# ---------- pobory (mA przy 3,3 V) ----------
MCU_DSP, MCU_FULL, MCU_SEN = 12, 30, 0.3      # RP2350: 48 MHz liczenie widma / 150 MHz dekodowanie / uspienie
SI_RX, SI_TX = 28, 45                          # Si5351: heterodyna odbiornika (2 wyjscia) / nadajnik 8 mA
ODB, GPS = 3, 30                               # mieszacz + wzmacniacz / ATGM336H szukanie-sledzenie
RX_OKNO = MCU_DSP + SI_RX + ODB                # 43 mA przez 15 s
TX = SI_TX + 5                                 # 50 mA
def srednia(zdarzenia):                        # [(mA, sekund na godzine)] -> srednia mA; reszta czasu = uspienie
    s = sum(t for _, t in zdarzenia); return (sum(i * t for i, t in zdarzenia) + MCU_SEN * (3600 - s)) / 3600
WSPR = [(TX, 6 * 110.6), (GPS + 5, 6 * 35)]    # co 10 min: ramka WSPR + 35 s GPS
def robot(okien_rx_h, okien_tx_h):             # okna FT8 po 15 s (nadawanie 12,64 s), dekodowanie 1 s po kazdym odbiorze
    return srednia(WSPR + [(RX_OKNO, okien_rx_h * 15), (MCU_FULL, okien_rx_h * 1.0), (TX, okien_tx_h * 12.64)])
TRYBY = [("sam WSPR co 10 min", srednia(WSPR)),
         ("oszczedny: CQ co 2 min + 1 okno nasluchu", robot(30, 30)),
         ("sredni: CQ co minute + 1 okno nasluchu", robot(60, 60)),
         ("pelny: nasluch ciagly, 15 QSO/h", robot(240 - 6 * 8 - 45, 45))]

print("wspolczynnik ostrozny (z lotow): %.2f, optymistyczny: %.2f" % (WSP_OSTR, WSP_OPT))
print("\nPrad z panelu 6 x 52 x 23 plasko [mA] (napiecie ok. 3,3 V):")
print(" Slonce  ostroznie  optymistycznie   moc ostroznie")
for h in (10, 13, 15, 17, 20, 25, 30, 40, 60):
    print("  %2d st.   %5.0f       %5.0f          %4.0f mW" % (h, prad(h, WSP_OSTR), prad(h, WSP_OPT), prad(h, WSP_OSTR) * 3.3))
print("\nPobor sredni [mA] i od jakiej wysokosci Slonca starcza (ostroznie / optymistycznie):")
for n, i in TRYBY:
    def prog(w): return next((h for h in [x / 2 for x in range(10, 181)] if prad(h, w) >= i), None)
    print("  %-42s %5.1f mA = %3.0f mW   od %s st. / %s st." % (n, i, i * 3.3, prog(WSP_OSTR), prog(WSP_OPT)))
print("  szczyt chwilowy: nadawanie %d mA, odbior %d mA, GPS %d mA" % (TX, RX_OKNO, GPS + 5))
print("  energia jednego QSO (3 odbiory + 3 nadawania): %.1f J" % ((3 * RX_OKNO * 15 + 3 * MCU_FULL + 3 * TX * 12.64) * 3.3 / 1000))

# ---------- masa ----------
G_OGNIWA = 1.90 / (6 * 39 * 19)                # g/mm2 z pomiaru 18.11: 6 x 39 x 19 = 1,90 g
MASA = [("laminat 22 x 30 mm, 0,6 mm (FR4 1,85 g/cm3) + miedz i maska", 2.2 * 3.0 * 0.06 * 1.85 + 0.10),
        ("RP2350A QFN-60 + pamiec flash + kwarc", 0.25),
        ("Si5351A + TCXO", 0.05),
        ("GPS ATGM336H (modul)", 0.60),
        ("odbiornik: klucz analogowy + wzmacniacz", 0.09),
        ("stabilizator, ok. 45 elementow biernych, filtr wyjsciowy", 0.20),
        ("cyna", 0.10),
        ("6 ogniw 52 x 23 mm", 6 * 52 * 23 * G_OGNIWA),
        ("polaczenia ogniw, tasma, mocowanie", 0.60),
        ("dipol 20 m: 2 x 5,05 m drutu 0,10 mm", math.pi * 0.005 ** 2 * 1010 * 8.96),
        ("antena GPS (drut), linka do balonu", 0.25)]
print("\nMasa [g]:")
for n, m in MASA: print("  %-62s %5.2f" % (n, m))
pl = sum(m for _, m in MASA[:7]); cal = sum(m for _, m in MASA)
print("  %-62s %5.2f" % ("PLYTKA zmontowana", pl)); print("  %-62s %5.2f" % ("CALOSC do lotu", cal))
print("  %-62s %5.2f" % ("z superkondensatorem 0,47 F (opcja, ok. 1 g)", cal + 1.0))

# -*- coding: utf-8 -*-
"""Tracker-robot FT8 "R20" v0.1 - schemat jako kod (21.11.2026). ETAP 1: elementy i polaczenia, BEZ polozen.
ZMIANY 21.11 17:40 (po sprawdzeniu w bibliotece JLC/EasyEDA i magazynie):
 - procesor RP2354A (C41378174) = RP2350A z wbudowana pamiecia 2 MB -> bez osobnej kosci pamieci;
 - rdzen 1,2 V z osobnego stabilizatora ME6211C12 (ten sam co U7 w T433 lite) zamiast wbudowanej przetwornicy:
   bez cewki o krytycznej biegunowosci i bez zaklocen impulsowych przy odbiorniku. Karta RP2350: "DVDD can be supplied directly
   from an off-chip power source"; VREG_VIN i VREG_AVDD przez filtr do 3,3 V, VREG_LX i VREG_FB niepodlaczone.
   UWAGA: 1,2 V to wiecej niz nominalne 1,1 V (w zakresie ustawien regulatora 0,55-1,30 V) - do akceptacji przed zamowieniem.
 - nazwy i numery pinow U1, U3, U4, Y2, U6/U8, Q1/Q2, U7, D1, Y1 porownane z symbolami JLC/EasyEDA dla tych numerow LCSC - zgodne.
Uklad pliku jak firmware/tracker433/pcb_lite/projekt.py (ten sam tor: projekt.py -> buduj.py -> Freerouting -> pliki JLC).
Kazdy element: ref, footprint, wartosc, LCSC, {pad: siec}.  LCSC z "?" = numer do potwierdzenia w magazynie JLC przed zamowieniem.
Sprawdzenie: python3 projekt.py  (kontrola sieci + lista elementow)."""

# ---------------- RP2350A, QFN-60 7x7 mm (piny wg "Hardware design with RP2350", zgodne ze schematami Waveshare) ----------------
RP = {1: "+3V3", 6: "+1V1", 11: "+3V3", 20: "+3V3", 23: "+1V1", 30: "+3V3", 38: "+3V3", 39: "+1V1", 45: "+3V3",
      # pamiec 2 MB jest w obudowie RP2354A (piny QSPI 55-59 zostaja niepodlaczone na plytce)
      # przydzial GPIO pod rozmieszczenie (U1 obrocony o 180 st.: piny 31-45 w strone odbiornika, 16-30 w strone GPS)
      2: None, 3: None, 4: None, 5: None, 7: None, 8: None, 9: None, 10: None,          # GPIO0-7 wolne
      # 21.11 23:20: GPS przeniesiony na prawy bok ukladu, I2C i RF_EN_N na gorny - przy pinach 16-19 i 32-34 sciezki sie nie miescily
      12: "GPS_RXD",      # GPIO8  UART1 TX -> RXD GPS
      13: "GPS_TXD",      # GPIO9  UART1 RX <- TXD GPS
      14: "GPS_EN_N",     # GPIO10 stan niski = GPS wlaczony (Q2)
      15: None,           # GPIO11 wolny
      16: None, 17: None, 18: None, 19: None,                                             # GPIO12-15 wolne
      21: "XIN", 22: "XOUT_R",
      24: None, 25: None, 26: "RUN",        # SWCLK / SWD bez pol (wgrywanie przez USB)
      27: "SDA",          # GPIO16 I2C0 SDA
      28: "SCL",          # GPIO17 I2C0 SCL
      29: "RF_EN_N",      # GPIO18 stan niski = Si5351 + TCXO wlaczone (Q1)
      31: "RX_PWR",       # GPIO19 zasilanie odbiornika (klucz + wzmacniacz, ok. 3 mA) wprost z pinu
      32: None, 33: None, 34: None,                                                       # GPIO20-22 wolne
      35: "RX_OE_N",      # GPIO23 stan niski = klucz odbiornika wlaczony; przy nadawaniu 1 (klucz odlaczony od anteny)
      36: None, 37: None,                                                                 # GPIO24-25 wolne
      40: "RX_I",         # GPIO26 ADC0
      41: "RX_Q",         # GPIO27 ADC1
      42: "VSC_ADC",      # GPIO28 ADC2  napiecie paneli / 2
      43: None,           # GPIO29 ADC3 wolny
      44: "ADC_AVDD",
      46: "VREG_F", 47: "GND", 48: None, 49: "VREG_F", 50: "GND",    # wbudowana przetwornica nieuzywana: LX wolny, FB do masy (karta RP2350, zewn. zasilanie rdzenia)
      51: "USB_DM_R", 52: "USB_DP_R",
      53: "+3V3", 54: "+3V3",          # USB_OTP_VDD, QSPI_IOVDD
      55: None, 56: None, 57: None, 58: None, 59: None, 60: "QSPI_SS",
      61: "GND"}                        # pole srodkowe
# Si5351A-B-GT, MSOP-10 (jak w ICT v3.61: TCXO 26 MHz wprost na XA)
SI = {1: "RF_VCC", 2: "TCXO_OUT", 3: None, 4: "SCL", 5: "SDA", 6: "LO_Q", 7: "RF_VCC", 8: "GND", 9: "LO_I", 10: "TX_OUT"}
TCXO = {1: "GND", 2: "GND", 3: "TCXO_OUT", 4: "RF_VCC"}        # 1 = OE# (stan niski = wlaczony), jak w ICT v3.61
# SN74CBTLV3253 TSSOP-16: obie polowki rownolegle (mniejsza rezystancja klucza); S0 = LO_I, S1 = LO_Q (przesuniete o 90 st.)
MUX = {1: "RX_OE_N", 15: "RX_OE_N",              # OE# obu polowek z GPIO23 (przy nadawaniu = 1, inaczej klucz zwiera antene przez kondensatory odbiornika)
       14: "LO_I", 2: "LO_Q",
       7: "RX_IN", 9: "RX_IN",
       6: "QA", 10: "QA", 5: "QB", 11: "QB", 4: "QC", 12: "QC", 3: "QD", 13: "QD",   # B1..B4 = 4 fazy probkowania
       8: "GND", 16: "RX_PWR"}
# TLV9062 (podwojny wzmacniacz, MSOP-8): A = tor I (QA - QC), B = tor Q (QB - QD), wzmocnienie 1000, pasmo ok. 3,4 kHz
OPA = {1: "RX_I", 2: "I_N", 3: "I_P", 4: "GND", 5: "Q_P", 6: "Q_N", 7: "RX_Q", 8: "RX_PWR"}
LDO = {1: "VSC", 2: "GND", 3: "VSC", 4: None, 5: "+3V3"}            # ME6211C33: EN na stale
GPS = {1: "GND", 2: "GPS_TXD", 3: "GPS_RXD", 4: None, 5: "GPS_VCC", 6: "+3V3", 7: None, 8: "GPS_VCC",
       9: None, 10: "GND", 11: "GPS_ANT", 12: "GND", 13: None, 14: None, 15: None, 16: None, 17: None, 18: None}   # jak T433 lite

PARTS = [
    ("U1", "QFN-60-1EP_7x7mm_P0.4mm", "RP2354A (pamiec 2 MB w srodku)", "C41378174", RP),
    ("U8", "SOT-23-5", "TLV74311PDBVR (rdzen 1,1 V; do 22.11.2026 ME6211C12 1,2 V C236672 - za wysokie)", "C485147", {1: "+3V3", 2: "GND", 3: "+3V3", 4: None, 5: "+1V1"}),
    ("U3", "MSOP-10", "SI5351A-B-GTR", "C504891", SI),
    ("Y2", "SMD3225-4P", "TCXO 26 MHz KDS 1XTW26000MAA", "C213404", TCXO),
    ("U4", "TSSOP-16", "SN74CBTLV3253PWR", "C105246", MUX),
    ("U5", "VSSOP-8", "TLV9062IDGKR", "C398356", OPA),
    ("U6", "SOT-23-5", "ME6211C33M5G-N (3,3 V)", "C82942", LDO),
    ("U7", "ATGM336H", "ATGM336H-5N31", "C90770", GPS),
    ("Q1", "SOT-23", "SI2301CDS (zas. Si5351 + TCXO)", "C10487", {1: "RF_EN_N", 2: "+3V3", 3: "RF_VCC"}),
    ("Q2", "SOT-23", "SI2301CDS (zas. GPS)", "C10487", {1: "GPS_EN_N", 2: "+3V3", 3: "GPS_VCC"}),
    # D1 NIE MONTOWANY (decyzja 21.11 23:20): przy 6 ogniwach napiecie nie dochodzi do granicy stabilizatora (6 V); pola zostaja na wypadek 8 ogniw
    ("D1", "SOD-123", "NC BZT52C5V1 (ogr. 5,1 V, tylko pola)", "", {1: "VSC", 2: "GND"}),
    ("Y1", "SMD3225-4P", "kwarc 12 MHz X322512MSB4SI", "C9002", {1: "XIN", 2: "GND", 3: "XOUT", 4: "GND"}),   # kwarc symetryczny (21.11 23:40: XIN/XOUT zamienione pod rozmieszczenie)
]
# elementy dwukoncowkowe: ref, obudowa, wartosc, LCSC, siec1, siec2
PAS = [
    # --- zasilanie 3,3 V ---
    ("C1", "0603", "10uF", "C19702", "VSC", "GND"), ("C2", "0603", "10uF", "C19702", "+3V3", "GND"),
    # --- RP2354: rdzen ze stabilizatora U8; zasilanie nieuzywanego regulatora przez filtr ---
    ("C3", "0402", "1uF", "C52923", "+3V3", "GND"),       # wejscie U8
    ("C4", "0402", "1uF", "C52923", "+1V1", "GND"),       # wyjscie U8
    ("R1", "0402", "10R", "C25077", "+3V3", "VREG_F"), ("C5", "0402", "1uF", "C52923", "VREG_F", "GND"),
    # --- RP2350: odsprzeganie (100 nF na kazdy pin zasilania) ---
    ("C6", "0402", "100nF", "C1525", "+3V3", "GND"), ("C7", "0402", "100nF", "C1525", "+3V3", "GND"),
    ("C8", "0402", "100nF", "C1525", "+3V3", "GND"), ("C9", "0402", "100nF", "C1525", "+3V3", "GND"),
    ("C10", "0402", "100nF", "C1525", "+3V3", "GND"), ("C11", "0402", "100nF", "C1525", "+3V3", "GND"),
    ("C12", "0402", "100nF", "C1525", "+3V3", "GND"),      # piny 53 + 54 wspolnie
    ("C13", "0402", "100nF", "C1525", "+1V1", "GND"), ("C14", "0402", "100nF", "C1525", "+1V1", "GND"),
    ("C15", "0402", "100nF", "C1525", "+1V1", "GND"),
    ("R2", "0402", "10R", "C25077", "+3V3", "ADC_AVDD"), ("C16", "0402", "1uF", "C52923", "ADC_AVDD", "GND"),   # filtr zasilania ADC
    # --- kwarc, pamiec, uruchamianie ---
    ("R3", "0402", "1k", "C11702", "XOUT_R", "XOUT"), ("C17", "0402", "15pF", "C1548", "XIN", "GND"), ("C18", "0402", "15pF", "C1548", "XOUT", "GND"),
    ("R4", "0402", "1k", "C11702", "QSPI_SS", "BOOTSEL"),       # BOOTSEL na listku: zwarcie do masy przy wlaczeniu = tryb wgrywania przez USB
    ("R5", "0402", "10k", "C25744", "RUN", "+3V3"),
    ("R6", "0402", "27R", "C25100", "USB_DP_R", "USB_DP"), ("R7", "0402", "27R", "C25100", "USB_DM_R", "USB_DM"),
    # --- pomiar napiecia paneli ---
    ("R8", "0402", "1M", "C26083", "VSC", "VSC_ADC"), ("R9", "0402", "1M", "C26083", "VSC_ADC", "GND"),
    ("C20", "0402", "100nF", "C1525", "VSC_ADC", "GND"),
    # --- Si5351 + TCXO ---
    ("R10", "0402", "100k", "C25741", "RF_EN_N", "+3V3"),  # po resecie wylaczone
    ("C21", "0402", "100nF", "C1525", "RF_VCC", "GND"), ("C22", "0402", "1uF", "C52923", "RF_VCC", "GND"),
    ("R11", "0402", "4.7k", "C25900", "SDA", "RF_VCC"), ("R12", "0402", "4.7k", "C25900", "SCL", "RF_VCC"),
    # --- tor antenowy: CLK0 -> (miejsce na filtr) -> ANT; odbior z tego samego punktu ---
    ("C23", "0402", "100nF", "C1525", "TX_OUT", "ANT_F"),
    ("L2", "0603", "0R (miejsce na cewke filtra)", "C21189", "ANT_F", "ANT"),
    ("C24", "0402", "NC (filtr)", "", "ANT_F", "GND"), ("C25", "0402", "NC (filtr)", "", "ANT", "GND"),
    ("C26", "0402", "100nF", "C1525", "ANT", "RX_IN"),
    # --- odbiornik: polaryzacja RX_PWR/2, 4 kondensatory probkujace, 2 wzmacniacze roznicowe x1000 ---
    ("R13", "0402", "10k", "C25744", "RX_PWR", "RX_BIAS"), ("R14", "0402", "10k", "C25744", "RX_BIAS", "GND"),
    ("C27", "0402", "1uF", "C52923", "RX_BIAS", "GND"),
    ("R15", "0402", "100k", "C25741", "RX_BIAS", "RX_IN"),
    ("C28", "0402", "100nF", "C1525", "QA", "GND"), ("C29", "0402", "100nF", "C1525", "QB", "GND"),
    ("C30", "0402", "100nF", "C1525", "QC", "GND"), ("C31", "0402", "100nF", "C1525", "QD", "GND"),
    # kondensatory szeregowe 1 uF: dla napiecia stalego wzmocnienie = 1 (niezrownowazenie wzmacniacza do 1,6 mV x 1000 nasyciloby wyjscie);
    # dolna granica pasma ok. 160 Hz
    ("C40", "0402", "1uF", "C52923", "QA", "QA_C"), ("C41", "0402", "1uF", "C52923", "QC", "QC_C"),
    ("C42", "0402", "1uF", "C52923", "QB", "QB_C"), ("C43", "0402", "1uF", "C52923", "QD", "QD_C"),
    ("R16", "0402", "1k", "C11702", "QA_C", "I_P"), ("R17", "0402", "1k", "C11702", "QC_C", "I_N"),
    ("R18", "0402", "1M", "C26083", "I_N", "RX_I"), ("C32", "0402", "47pF", "C1567", "I_N", "RX_I"),
    ("R19", "0402", "1M", "C26083", "I_P", "RX_BIAS"), ("C33", "0402", "47pF", "C1567", "I_P", "RX_BIAS"),
    ("R20", "0402", "1k", "C11702", "QB_C", "Q_P"), ("R21", "0402", "1k", "C11702", "QD_C", "Q_N"),
    ("R22", "0402", "1M", "C26083", "Q_N", "RX_Q"), ("C34", "0402", "47pF", "C1567", "Q_N", "RX_Q"),
    ("R23", "0402", "1M", "C26083", "Q_P", "RX_BIAS"), ("C35", "0402", "47pF", "C1567", "Q_P", "RX_BIAS"),
    ("C36", "0402", "100nF", "C1525", "RX_PWR", "GND"), ("C37", "0402", "1uF", "C52923", "RX_PWR", "GND"),
    # --- GPS (jak T433 lite) ---
    ("R24", "0402", "100k", "C25741", "GPS_EN_N", "+3V3"),
    ("C38", "0402", "1uF", "C52923", "GPS_VCC", "GND"), ("C39", "0402", "100nF", "C1525", "GPS_VCC", "GND"),
]
# pola i otwory (bez montazu): nazwa, siec, opis
PADS = [("PV+", "VSC", "ogniwa +"), ("PV-", "GND", "ogniwa -"), ("SC+", "VSC", "superkondensator + (opcja, spod)"),
        ("SC-", "GND", "superkondensator - (spod)"), ("ANT", "ANT", "dipol - ramie gorace"), ("ANT_GND", "GND", "dipol - drugie ramie"),
        ("GPS_ANT", "GPS_ANT", "antena GPS (drut 47 mm)"),
        # listek do wgrywania, goldpin 2x3 - TEN SAM UKLAD co T433: B0, EN, V+, D+, D-, G (ten sam kabel USB)
        ("J1.1", "BOOTSEL", "B0"), ("J1.2", "RUN", "EN"), ("J1.3", "VSC", "V+"), ("J1.4", "USB_DP", "D+"), ("J1.5", "USB_DM", "D-"), ("J1.6", "GND", "G"),
]
NAPIS = "R20 v0.2"          # bez znaku wywolawczego na plytce (decyzja autora 22.11)

if __name__ == "__main__":
    from collections import defaultdict
    nets = defaultdict(list)
    for ref, fp, val, lcsc, pins in PARTS:
        for p, n in pins.items():
            if n: nets[n].append("%s.%s" % (ref, p))
    for ref, fp, val, lcsc, a, b in PAS:
        nets[a].append(ref + ".1"); nets[b].append(ref + ".2")
    for name, n, opis in PADS: nets[n].append(name)
    bledy = 0
    for n, w in sorted(nets.items()):
        if len(w) < 2: print("BLAD: siec %s ma tylko 1 wezel: %s" % (n, w)); bledy += 1
    if sorted(RP) != list(range(1, 62)): print("BLAD: RP2350 - brak pinow", sorted(set(range(1, 62)) - set(RP))); bledy += 1
    for n in ("+3V3", "+1V1", "GND", "VSC", "RF_VCC", "RX_PWR", "GPS_VCC"): print("%-8s %3d wezlow" % (n, len(nets[n])))
    print("sieci: %d, elementow montowanych: %d, bledow: %d" % (len(nets), len([x for x in PARTS + PAS if not x[2].startswith("NC")]), bledy))
    lista = defaultdict(list)
    for ref, fp, val, lcsc, *_ in PARTS: lista[(val, fp, lcsc)].append(ref)
    for ref, fp, val, lcsc, *_ in PAS: lista[(val, fp, lcsc)].append(ref)
    print("\nLista elementow (LCSC '?' = do potwierdzenia):")
    for (val, fp, lcsc), refs in sorted(lista.items(), key=lambda x: x[1][0]):
        print("  %2d x %-46s %-22s %-10s %s" % (len(refs), val, fp, lcsc or "-", ",".join(refs) if len(refs) < 7 else refs[0] + "…" + refs[-1]))
    print("do potwierdzenia w JLC:", sorted({v for (v, f, l) in lista if l == "?"}))

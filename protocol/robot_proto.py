"""
Protokół trackera-robota FT8 („R20”) – ramki danych w obie strony. WERSJA 1 (21.11.2026).

Wszystko idzie w ramkach FT8 typu „telemetria”: 71 dowolnych bitów. Ten plik jest wzorcem formatu –
firmware trackera ma kodować dokładnie tak samo (testy: test_robot.py). Czysty Python, bez numpy,
żeby ten sam plik działał na PC w biurze i na Dellu.

Rodzaj ramki rozpoznaje się po pierwszych bitach (od najstarszego):

  0     LOG      wpis logu: 1–2 łączności                            (balon -> ziemia)
  10    STAN     liczniki logu i stan trackera                       (balon -> ziemia)
  110   SLUCH    zarezerwowane („co słychać z 13 km”)                (balon -> ziemia)
  1110  –        zarezerwowane (znaki niestandardowe)
  1111  KOMENDA  polecenie z podpisem                                (dom -> balon)
        (od 22.11.2026 doszły komendy: 0 NADAWANIE, 14 ZNAK, 15 LOKATOR; PASMO ma też kanał WSPR)

LOG (71 b):   0 | znak1:28 | znak2:28 | czas:11 | nr:3
    Jeden WPIS logu = jedna albo dwie łączności. Tracker zamyka wpis, gdy ma dwie łączności albo gdy od pierwszej
    minęło 10 minut (wtedy znak2 = 0). Wpisy mają numery 1, 2, 3…; nr = numer wpisu modulo 8.
    znak = 28 bitów jak w zwykłej ramce FT8 (tylko znaki standardowe; 0 = brak).
    czas = (czas uniksowy pierwszej łączności // 600) modulo 2048, czyli jednostki 10 min, okres 14,2 doby.
    Druga łączność wpisu jest najwyżej 10 minut później – w logu dostaje ten sam czas.

STAN (71 b):  10 | wpisy:14 | zaleglosc:8 | qso:14 | napiecie:7 | temp:7 | tryb:3 | kom:6 | snr:5 | dekody:5
    wpisy     – ile wpisów logu tracker ma w pamięci (numer najnowszego)
    zaleglosc – ile najnowszych wpisów nie ma jeszcze potwierdzenia z ziemi (255 = 255 lub więcej)
    qso       – liczba łączności od startu
    napiecie  – napięcie paneli, krok 0,05 V (0…6,35 V)
    temp      – temperatura + 90 (−90…+37 °C)
    tryb      – 0 pełny, 1 średni, 2 oszczędny, 3 sam WSPR, 4 cisza
    kom       – licznik ostatniej przyjętej komendy (0…63)
    snr       – z jakim SNR balon ostatnio zdekodował dom: wartość − 24 dB (0…30 → −24…+6 dB), 31 = nie słyszał
    dekody    – ile komunikatów zdekodował w ostatnim oknie odbioru (31 = 31 lub więcej)

KOMENDA (71 b): 1111 | kod:4 | licznik:6 | argumenty:33 | podpis:24
    podpis = pierwsze 24 bity HMAC-SHA256(klucz, 6 bajtów [pierwsze 47 bitów ramki] + 4 bajty [numer okna]),
    numer okna = czas uniksowy początku okna nadawania // 15. Tracker liczy podpis dla okna, w którym odebrał
    ramkę – nagrana ramka nadana później już nie przejdzie. Klucz: 16 bajtów, tylko w trackerze i w pliku
    robot_klucz.txt na komputerze (nigdy w repo).
    licznik – numer kolejny komendy modulo 64; tracker odsyła go w ramce STAN (pole kom).
"""
import hashlib, hmac, time

BITY = 71
OKNO_S = 15
JEDN_CZASU = 600              # 10 minut
OKRES_CZASU = 2048            # 11 bitów
NTOKENS, MAX22 = 2063592, 4194304
A0 = " 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
A1 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
A2 = "0123456789"
A3 = " ABCDEFGHIJKLMNOPQRSTUVWXYZ"
TRYBY = ["pełny", "średni", "oszczędny", "sam WSPR", "cisza"]

# pola ramek: (nazwa, liczba bitów)
POLA_LOG = [("znak1", 28), ("znak2", 28), ("czas", 11), ("nr", 3)]
POLA_STAN = [("wpisy", 14), ("zaleglosc", 8), ("qso", 14), ("napiecie", 7), ("temp", 7), ("tryb", 3), ("kom", 6),
             ("snr", 5), ("dekody", 5)]
# komendy: kod -> (nazwa, opis, pola argumentów – razem najwyżej 33 bity)
KOMENDY = {
    1: ("POTWIERDZENIE", "mam wszystkie wpisy do nr „do”; mapa: które z następnych 19 (do+2 … do+20) też mam",
        [("do", 14), ("mapa", 19)]),
    2: ("DOSYLKA", "nadaj jeszcze raz wpisy od–do", [("od", 14), ("do", 14)]),
    3: ("TRYB", "tryb pracy 0 pełny / 1 średni / 2 oszczędny / 3 sam WSPR / 4 cisza na „godziny”",
        [("tryb", 3), ("godziny", 8)]),
    4: ("EMISJA", "0 = FT8, 1 = FT4", [("ft4", 1)]),
    5: ("MIEJSCE", "przesunięcie CQ i częstotliwość zrzutu logu [Hz dźwięku]", [("cq_hz", 12), ("log_hz", 12)]),
    6: ("MOC", "prąd wyjścia Si5351: 0 = 2 mA, 1 = 4, 2 = 6, 3 = 8 mA", [("moc", 2)]),
    7: ("PROGI", "napięcie [× 0,05 V] i wysokość Słońca [°]: od kiedy nasłuch ciągły, od kiedy tylko WSPR",
        [("u_pelny", 7), ("u_wspr", 7), ("slonce_pelny", 6), ("slonce_wspr", 6)]),
    8: ("STREFA", "strefa ciszy nr 0–3: dodaj = 1 / usuń = 0; rogi w krokach 2° (szer. = −90 + 2·v, dług. = −180 + 2·v)",
        [("dodaj", 1), ("nr", 2), ("szer1", 7), ("dlug1", 8), ("szer2", 7), ("dlug2", 8)]),
    9: ("ZASADY", "ta sama stacja: 0 bez ograniczeń, 1 raz na dobę, 2 raz na lot", [("regula", 2)]),
    10: ("TEKST", "zarezerwowane: tekst wolny do nadania przez balon (wymaga kilku ramek)", []),
    11: ("PYTANIE", "nadaj ramkę STAN od razu", []),
    12: ("PASMO", "pasmo (numer z listy PASMA) i kanał WSPR 0–599 (jak w Traquito)", [("pasmo", 4), ("kanal", 10)]),
    13: ("CZARNA_LISTA", "dodaj = 1 / usuń = 0 znak, z którym balon nie robi łączności", [("dodaj", 1), ("znak", 28)]),
    14: ("ZNAK", "zmiana znaku balonu: ktory = 0 znak FT8, 1 znak WSPR", [("ktory", 1), ("znak", 28)]),
    15: ("LOKATOR", "staly = 1: balon podaje zawsze ten lokator (6 znaków); staly = 0: lokator z GPS",
         [("staly", 1), ("lokator", 25)]),
    0: ("NADAWANIE", "wlacz = 0 wyłącza / 1 włącza nadawanie; zakres: 0 wszystko, 1 tylko FT8, 2 tylko WSPR; "
                     "dni: po ilu dniach wyłączone nadawanie włączy się samo (0 = nigdy)",
        [("wlacz", 1), ("zakres", 2), ("dni", 6)]),
}
KOD = {v[0]: k for k, v in KOMENDY.items()}
PASMA = ["160 m", "80 m", "60 m", "40 m", "30 m", "20 m", "17 m", "15 m", "12 m", "10 m", "6 m"]


# ---------------------------------------------------------------------- znaki 28 bitów
def pakuj_znak(znak):
    """Znak standardowy -> 28 bitów jak w FT8 (pusty = 0). ValueError dla znaku, którego nie da się tak zapisać."""
    z = (znak or "").strip().upper()
    if not z:
        return 0
    if z.startswith("3DA0") and 4 < len(z) <= 7:
        z = "3D0" + z[4:]
    elif z.startswith("3X") and len(z) > 2 and z[2].isalpha() and len(z) <= 7:
        z = "Q" + z[2:]
    if len(z) >= 3 and z[2].isdigit() and len(z) <= 6:
        c6 = z.ljust(6)
    elif len(z) >= 2 and z[1].isdigit() and len(z) <= 5:
        c6 = (" " + z).ljust(6)
    else:
        raise ValueError(f"znak niestandardowy: {znak}")
    try:
        i = [A0.index(c6[0]), A1.index(c6[1]), A2.index(c6[2]), A3.index(c6[3]), A3.index(c6[4]), A3.index(c6[5])]
    except ValueError:
        raise ValueError(f"znak niestandardowy: {znak}")
    n = ((((i[0] * 36 + i[1]) * 10 + i[2]) * 27 + i[3]) * 27 + i[4]) * 27 + i[5]
    return NTOKENS + MAX22 + n


def rozpakuj_znak(n28):
    """28 bitów -> znak ('' dla 0). None, gdy to nie jest znak standardowy (ramka spoza naszego formatu)."""
    if n28 == 0:
        return ""
    n = n28 - NTOKENS - MAX22
    if n < 0:
        return None
    c = [""] * 6
    c[5] = A3[n % 27]; n //= 27
    c[4] = A3[n % 27]; n //= 27
    c[3] = A3[n % 27]; n //= 27
    c[2] = A2[n % 10]; n //= 10
    c[1] = A1[n % 36]; n //= 36
    if n >= 37:
        return None
    c[0] = A0[n]
    z = "".join(c)
    if z.startswith("3D0") and z[3] != " ":
        z = "3DA0" + z[3:]
    elif z[0] == "Q" and z[1].isalpha():
        z = "3X" + z[1:]
    z = z.strip()
    if " " in z or len(z) < 3 or not any(ch.isalpha() for ch in z):
        return None
    return z


def pakuj_lokator(lok):
    """Lokator 4 lub 6 znaków (np. JO91 albo JO91AB) -> 25 bitów. 4 znaki = środek kwadratu (…LL)."""
    z = (lok or "").strip().upper()
    if len(z) == 4:
        z += "LL"
    if (len(z) != 6 or not ("A" <= z[0] <= "R" and "A" <= z[1] <= "R" and z[2:4].isdigit()
                            and "A" <= z[4] <= "X" and "A" <= z[5] <= "X")):
        raise ValueError(f"zły lokator: {lok}")
    a = [ord(z[0]) - 65, ord(z[1]) - 65, int(z[2]), int(z[3]), ord(z[4]) - 65, ord(z[5]) - 65]
    return ((((a[0] * 18 + a[1]) * 10 + a[2]) * 10 + a[3]) * 24 + a[4]) * 24 + a[5]


def rozpakuj_lokator(n):
    f = n % 24; n //= 24
    e = n % 24; n //= 24
    d = n % 10; n //= 10
    c = n % 10; n //= 10
    return chr(65 + n // 18) + chr(65 + n % 18) + str(c) + str(d) + chr(65 + e) + chr(65 + f)


# ---------------------------------------------------------------------- bity
def _skladaj(pola, wartosci):
    x = 0
    for nazwa, b in pola:
        v = int(wartosci.get(nazwa, 0))
        if not 0 <= v < (1 << b):
            raise ValueError(f"pole „{nazwa}” = {v} nie mieści się w {b} bitach")
        x = (x << b) | v
    return x


def _rozloz(pola, x):
    out = {}
    for nazwa, b in reversed(pola):
        out[nazwa] = x & ((1 << b) - 1)
        x >>= b
    return out


def _ile(pola):
    return sum(b for _, b in pola)


def czas_na_pole(t_unix):
    return (int(t_unix) // JEDN_CZASU) % OKRES_CZASU


def pole_na_czas(pole, t_odbioru):
    """Pole czasu z ramki -> czas uniksowy (początek 10-minutowej jednostki), najbliższy nie późniejszy niż odbiór."""
    teraz = int(t_odbioru) // JEDN_CZASU + 1            # + 1: zegar trackera może nieznacznie wyprzedzać nasz
    j = teraz - ((teraz - pole) % OKRES_CZASU)
    return j * JEDN_CZASU


# ---------------------------------------------------------------------- balon -> ziemia
def ramka_log(znak1, znak2, t_unix, nr_wpisu):
    """Wpis logu -> 71 bitów. (Dla testów i symulatora trackera.)"""
    return _skladaj(POLA_LOG, {"znak1": pakuj_znak(znak1), "znak2": pakuj_znak(znak2), "czas": czas_na_pole(t_unix),
                               "nr": nr_wpisu % 8})


def ramka_stan(wpisy, zaleglosc, qso, napiecie_v, temp_c, tryb=0, kom=0, snr_db=None, dekody=0):
    w = {"wpisy": wpisy, "zaleglosc": min(zaleglosc, 255), "qso": qso,
         "napiecie": max(0, min(127, round(napiecie_v / 0.05))), "temp": max(0, min(127, round(temp_c) + 90)),
         "tryb": tryb, "kom": kom % 64, "snr": 31 if snr_db is None else max(0, min(30, round(snr_db) + 24)),
         "dekody": min(dekody, 31)}
    return (0b10 << 69) | _skladaj(POLA_STAN, w)


def rozbierz(bity71, t_odbioru=None):
    """71 bitów -> słownik z kluczem „rodzaj” (LOG / STAN / SLUCH / KOMENDA / INNE) albo None, gdy ramka nie pasuje."""
    t_odbioru = time.time() if t_odbioru is None else t_odbioru
    if not 0 <= bity71 < (1 << BITY):
        return None
    if bity71 >> 70 == 0:
        p = _rozloz(POLA_LOG, bity71)
        z1, z2 = rozpakuj_znak(p["znak1"]), rozpakuj_znak(p["znak2"])
        if not z1 or z2 is None:
            return None
        return {"rodzaj": "LOG", "znak1": z1, "znak2": z2, "czas": pole_na_czas(p["czas"], t_odbioru), "nr8": p["nr"]}
    if bity71 >> 69 == 0b10:
        p = _rozloz(POLA_STAN, bity71 & ((1 << 69) - 1))
        if p["tryb"] >= len(TRYBY) or p["qso"] < p["wpisy"] or p["qso"] > 2 * p["wpisy"] or p["zaleglosc"] > max(p["wpisy"], 0) and p["zaleglosc"] != 255:
            return None
        return {"rodzaj": "STAN", "wpisy": p["wpisy"], "zaleglosc": p["zaleglosc"], "qso": p["qso"],
                "napiecie": round(p["napiecie"] * 0.05, 2), "temp": p["temp"] - 90, "tryb": p["tryb"],
                "tryb_opis": TRYBY[p["tryb"]], "kom": p["kom"], "snr": None if p["snr"] == 31 else p["snr"] - 24,
                "dekody": p["dekody"]}
    if bity71 >> 68 == 0b110:
        return {"rodzaj": "SLUCH", "bity": bity71 & ((1 << 68) - 1)}
    if bity71 >> 67 == 0b1111:
        kod = (bity71 >> 63) & 15
        if kod not in KOMENDY:
            return None
        arg = (bity71 >> 24) & ((1 << 33) - 1)
        pola = KOMENDY[kod][2]
        return {"rodzaj": "KOMENDA", "kod": kod, "nazwa": KOMENDY[kod][0], "licznik": (bity71 >> 57) & 63,
                "arg": _rozloz(pola, arg >> (33 - _ile(pola))), "podpis": bity71 & 0xFFFFFF}
    return {"rodzaj": "INNE"}


# ---------------------------------------------------------------------- dom -> balon
def _podpis(klucz, cialo47, okno):
    d = hmac.new(klucz, cialo47.to_bytes(6, "big") + int(okno).to_bytes(4, "big"), hashlib.sha256).digest()
    return int.from_bytes(d[:3], "big")


def ramka_komenda(kod, arg, licznik, klucz, t_okna):
    """Komenda -> 71 bitów z podpisem dla okna zaczynającego się w t_okna (czas uniksowy początku okna nadawania)."""
    if isinstance(kod, str):
        kod = KOD[kod]
    pola = KOMENDY[kod][2]
    a = _skladaj(pola, arg or {}) << (33 - _ile(pola))
    cialo = (0b1111 << 43) | (kod << 39) | ((licznik % 64) << 33) | a
    return (cialo << 24) | _podpis(klucz, cialo, int(t_okna) // OKNO_S)


def sprawdz_komende(bity71, klucz, t_okna):
    """Tak sprawdza podpis tracker: True, gdy ramka jest komendą podpisaną naszym kluczem dla tego okna."""
    if bity71 >> 67 != 0b1111:
        return False
    return _podpis(klucz, bity71 >> 24, int(t_okna) // OKNO_S) == (bity71 & 0xFFFFFF)


def opis_komendy(kod, arg):
    nazwa, _, pola = KOMENDY[kod]
    return nazwa + (" " + " ".join(f"{n}={arg.get(n, 0)}" for n, _ in pola) if pola else "")


def wczytaj_klucz(sciezka):
    """Klucz z pliku (32 znaki szesnastkowe). None, gdy pliku nie ma albo jest zły."""
    try:
        with open(sciezka, encoding="ascii") as f:
            k = bytes.fromhex(f.read().strip())
        return k if len(k) >= 16 else None
    except Exception:
        return None


def utworz_klucz(sciezka):
    import os
    k = os.urandom(16)
    with open(sciezka, "w", encoding="ascii") as f:
        f.write(k.hex() + "\n")
    return k

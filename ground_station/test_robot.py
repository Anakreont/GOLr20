"""
Testy modułów robota FT8: python test_robot.py
Sprawdza format ramek (robot_proto), składanie logu (robot_log) i – gdy jest biblioteka ft8shim –
pełną pętlę: ramka -> tony -> dźwięk z szumem -> dekoder -> ta sama ramka.
Uruchamiane też przy budowie instalatora (GitHub Actions), więc zła biblioteka DLL nie trafi do wydania.
"""
import os, random, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import robot_proto as P
from robot_log import RobotLog

KLUCZ = bytes(range(16))
T0 = 1795000000 - 1795000000 % 600          # okrągła jednostka czasu


def test_znaki():
    for z in ("SP9ABC", "SP1A", "SP5XYZ", "K1ABC", "DL1ABC", "3DA0XY", "3XA1AB", "OH3NIV", "R7IW", "JH7DFZ", "9A1A"):
        assert P.rozpakuj_znak(P.pakuj_znak(z)) == z, z
    assert P.pakuj_znak("") == 0 and P.rozpakuj_znak(0) == ""
    for zly in ("SP9/DL1ABC", "ABCDEFG", "Q"):
        try:
            P.pakuj_znak(zly)
            assert False, zly
        except ValueError:
            pass
    assert P.rozpakuj_znak(5) is None                      # żeton CQ/DE, nie znak
    for lok in ("KO00AA", "AA00AA", "RR99XX", "JO62QM"):
        assert P.rozpakuj_lokator(P.pakuj_lokator(lok)) == lok and P.pakuj_lokator(lok) < (1 << 25)
    assert P.rozpakuj_lokator(P.pakuj_lokator("KO00")) == "KO00LL"
    for zly in ("KO0", "SO00AA", "KO00YY", "KOAB"):
        try:
            P.pakuj_lokator(zly)
            assert False, zly
        except ValueError:
            pass


def test_ramki():
    b = P.ramka_log("DL1ABC", "K1ABC", T0 + 1234, 13)
    r = P.rozbierz(b, T0 + 5000)
    assert r == {"rodzaj": "LOG", "znak1": "DL1ABC", "znak2": "K1ABC", "czas": T0 + 1200, "nr8": 5}, r
    r = P.rozbierz(P.ramka_log("SP9ABC", "", T0, 2), T0 + 13 * 86400)       # odebrana 13 dni później
    assert r["czas"] == T0 and r["znak2"] == ""
    b = P.ramka_stan(37, 4, 70, 4.37, -52, tryb=1, kom=9, snr_db=-12, dekody=17)
    r = P.rozbierz(b)
    assert (r["wpisy"], r["zaleglosc"], r["qso"], r["napiecie"], r["temp"], r["tryb"], r["kom"], r["snr"], r["dekody"]) \
        == (37, 4, 70, 4.35, -52, 1, 9, -12, 17), r
    assert P.rozbierz(P.ramka_stan(3, 0, 5, 3.0, 20))["snr"] is None
    assert b < (1 << 71)


def test_komendy():
    t = 1795000005
    for kod, (nazwa, _, pola) in P.KOMENDY.items():
        assert sum(n for _, n in pola) <= 33, nazwa
        arg = {n: (1 << bity) - 1 - i for i, (n, bity) in enumerate(pola)}
        b = P.ramka_komenda(nazwa, arg, 70, KLUCZ, t)
        r = P.rozbierz(b)
        assert r["rodzaj"] == "KOMENDA" and r["kod"] == kod and r["arg"] == arg and r["licznik"] == 70 % 64, (nazwa, r)
        assert P.sprawdz_komende(b, KLUCZ, t) and P.sprawdz_komende(b, KLUCZ, t + 9)   # to samo okno 15 s
        assert not P.sprawdz_komende(b, KLUCZ, t + 15)            # następne okno – powtórka nagranej ramki odpada
        assert not P.sprawdz_komende(b ^ (1 << 30), KLUCZ, t)     # zmieniony argument
        assert not P.sprawdz_komende(b, b"x" * 16, t)             # obcy klucz
    # wektor wzorcowy dla firmware trackera
    b = P.ramka_komenda("POTWIERDZENIE", {"do": 35, "mapa": 0b101}, 7, KLUCZ, 1795000005)
    assert f"{b:018x}" == WZORZEC, f"{b:018x}"


def symulacja(n_wpisow, strata, ziarno):
    """Tracker robi wpisy co 3–40 min; ziemia odbiera część ramek LOG w losowej kolejności i STAN co jakiś czas."""
    rnd = random.Random(ziarno)
    znaki = [f"SP{rnd.randint(1, 9)}{''.join(rnd.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ') for _ in range(3))}" for _ in range(2 * n_wpisow)]
    log, t, wpisy = RobotLog(), T0, []
    for nr in range(1, n_wpisow + 1):
        t += rnd.randint(180, 2400)
        z1, z2 = znaki[2 * nr - 2], (znaki[2 * nr - 1] if rnd.random() < 0.7 else "")
        wpisy.append((nr, z1, z2, t))
        # tracker nadaje najnowszy wpis i kilka starszych; każda ramka dochodzi z prawdopodobieństwem 1 - strata
        do_nadania = [wpisy[-1]] + rnd.sample(wpisy, min(len(wpisy), 4))
        rnd.shuffle(do_nadania)
        for k, (n, a, b, tw) in enumerate(do_nadania):
            if rnd.random() > strata:
                log.dodaj(P.rozbierz(P.ramka_log(a, b, tw, n), t + 60 * k), t + 60 * k, "test")
        if rnd.random() < 0.6:
            qso = sum(1 + bool(w[2]) for w in wpisy)
            log.dodaj(P.rozbierz(P.ramka_stan(nr, 0, qso, 4.2, -50), t + 400), t + 400)
    t += 3000
    log.dodaj(P.rozbierz(P.ramka_stan(n_wpisow, 0, sum(1 + bool(w[2]) for w in wpisy), 4.2, -50), t), t)
    for nr, e in log.wpisy.items():                                   # żaden wpis nie może dostać złego numeru
        assert (wpisy[nr - 1][1], wpisy[nr - 1][2]) == (e["z1"], e["z2"]), (ziarno, nr, e, wpisy[nr - 1])
    return log, wpisy


def test_log():
    ponumerowane = wszystkie = 0
    for ziarno in range(60):
        log, wpisy = symulacja(40, 0.35, ziarno)
        ponumerowane += len(log.wpisy); wszystkie += len(log.wpisy) + len(log.luzne)
        assert log.liczba_wpisow() == 40
        p = log.potwierdzenie()
        assert all(n in log.wpisy for n in range(1, p["do"] + 1)) and p["do"] + 1 not in log.wpisy or p["do"] == 40
        for i in range(19):
            assert bool(p["mapa"] >> (18 - i) & 1) == (p["do"] + 2 + i in log.wpisy)
        assert set(log.brakujace()) == set(range(1, 41)) - set(log.wpisy)
    assert ponumerowane > 0.9 * wszystkie, (ponumerowane, wszystkie)
    # bez strat: komplet, potwierdzenie do końca, łączności do Log4OM i ich odhaczanie
    log, wpisy = symulacja(25, 0.0, 99)
    assert not log.brakujace() and not log.luzne and log.potwierdzenie()["do"] == 25
    q = log.nowe_do_logu()
    assert len(q) == sum(1 + bool(w[2]) for w in wpisy) == log.stan["qso"]
    log.oznacz([x["klucz"] for x in q[:5]]); log.oznacz([q[5]["klucz"]], pomin=True)
    assert len(log.nowe_do_logu()) == len(q) - 6
    assert "wpisy 25/25" in log.skrot()


def test_zapis():
    import tempfile
    sc = os.path.join(tempfile.mkdtemp(), "robot_log.json")
    log = RobotLog(sc)
    log.dodaj(P.rozbierz(P.ramka_log("DL1ABC", "K1ABC", T0, 1), T0 + 100), T0 + 100)
    log.dodaj(P.rozbierz(P.ramka_stan(1, 1, 2, 4.0, -40), T0 + 2000), T0 + 2000)
    log.zapisz()
    drugi = RobotLog(sc)
    assert drugi.wpisy == log.wpisy and 1 in drugi.wpisy and drugi.stan["qso"] == 2


def test_silnik():
    """Pętla przez dźwięk – tylko gdy jest biblioteka ft8shim i numpy."""
    try:
        import numpy as np
        import ft8silnik as F
        s = F.Silnik()
    except (ImportError, OSError) as e:
        print("  (pominięty: %s)" % e)
        return
    # znak 28 bitów liczony w Pythonie = ten sam, co w bibliotece FT8
    pl = s.pakuj_tekst("DL1ABC SP9ABC KO00")
    x = int.from_bytes(pl, "big") >> 3                       # 77 bitów
    assert x >> 49 == P.pakuj_znak("DL1ABC") and (x >> 20) & ((1 << 28) - 1) == P.pakuj_znak("SP9ABC")
    ramki = [P.ramka_log("DL1ABC", "K1ABC", T0 + 600, 3), P.ramka_stan(37, 4, 70, 4.35, -52, kom=9, snr_db=-12),
             P.ramka_komenda("POTWIERDZENIE", {"do": 35, "mapa": 5}, 7, KLUCZ, T0)]
    rng = np.random.default_rng(3)
    buf = rng.normal(0, 0.05, int(13.6 * F.FS_AUDIO)).astype(np.float32)
    i = int(0.5 * F.FS_AUDIO)
    for k, b in enumerate(ramki):                            # trzy ramki naraz, SNR ok. -13 dB
        a = F.synteza(s.tony(s.pakuj_telemetrie(b)), 2300.0 + 150 * k)
        buf[i:i + len(a)] += a * 0.01
    a = F.synteza(s.tony(pl), 1000.0)
    buf[i:i + len(a)] += a * 0.01
    d = s.dekoduj(F.na_12k(buf))
    odebrane = {x.bity71 for x in d if x.telemetria}
    assert odebrane == set(ramki), (odebrane, d)
    assert any(x.tekst == "DL1ABC SP9ABC KO00" and abs(x.hz - 1000) < 4 and abs(x.dt - 0.5) < 0.2 for x in d), d
    assert P.sprawdz_komende(ramki[2], KLUCZ, T0 + 3)


WZORZEC = "788e011800054ba73f"      # POTWIERDZENIE do=35 mapa=5, licznik 7, klucz 00 01 … 0f, okno 1795000005 // 15

if __name__ == "__main__":
    if "--wzorzec" in sys.argv:
        print(f"{P.ramka_komenda('POTWIERDZENIE', {'do': 35, 'mapa': 0b101}, 7, KLUCZ, 1795000005):018x}")
        sys.exit()
    for nazwa, f in sorted(globals().items()):
        if nazwa.startswith("test_"):
            print(nazwa)
            f()
    print("OK")

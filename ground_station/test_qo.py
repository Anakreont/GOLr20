"""
Testy zakładki „FT8 QO-100”: python test_qo.py
Sprawdza rozbiór komunikatów, automat łączności (ft8_qso.py), wpis ADIF z częstotliwościami QO-100
i – gdy jest biblioteka ft8shim – czy każdy nasz komunikat da się zakodować i zdekodować z dźwięku.
Uruchamiane też przy budowie instalatora (GitHub Actions).
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ft8_qso as Q
import logbook
import qo100

T = 1795000005 - 1795000005 % 30          # początek okna parzystego (:00 / :30)


def d(tekst, snr=-10, hz=1200):
    return (Q.rozbierz(tekst), snr, hz)


def test_rozbior():
    r = Q.rozbierz
    assert r("CQ DL1ABC JO62") == {"cq": True, "do": "", "od": "DL1ABC", "co": "CQ", "lok": "JO62", "rpt": ""}
    assert r("CQ DX DL1ABC JO62")["od"] == "DL1ABC" and r("CQ SP9/DL1ABC")["od"] == "SP9/DL1ABC"
    assert r("SP9ABC DL1ABC JO62")["co"] == "LOK" and r("SP9ABC DL1ABC JO62")["lok"] == "JO62"
    assert r("SP9ABC DL1ABC -07") == {"cq": False, "do": "SP9ABC", "od": "DL1ABC", "co": "RPT", "lok": "", "rpt": "-07"}
    assert r("SP9ABC DL1ABC R+03")["co"] == "RRPT" and r("SP9ABC DL1ABC R+03")["rpt"] == "+03"
    assert r("SP9ABC DL1ABC RR73")["co"] == "RR73" and r("SP9ABC DL1ABC RR73")["lok"] == ""
    assert r("SP9ABC DL1ABC RRR")["co"] == "RRR" and r("SP9ABC DL1ABC 73")["co"] == "73"
    assert r("<SP9ABC> DL1ABC/P -05")["od"] == "DL1ABC/P"
    for zly in ("TNX 73 GL", "<...> DL1ABC -05", "CQ", "0123456789ABCDEF12", "SP9ABC DL1ABC 599 0012"):
        assert r(zly) is None, zly
    assert Q.raport(-12.4) == "-12" and Q.raport(3) == "+03" and Q.raport(-44) == "-30" and Q.raport(0) == "+00"
    assert Q.okres(T) == 0 and Q.okres(T + 15) == 1 and Q.okres(T + 30) == 0


def test_odpowiadam_na_cq():
    """Dwuklik w cudze CQ: lokator -> R-raport -> 73, zapis po jego RR73."""
    s = Q.Sekwencer("SP9ABC", "KO00AA")
    assert s.wolaj(Q.rozbierz("CQ DL1ABC JO62"), T, snr=-12.3, hz=1234, teraz=T + 14)
    assert s.tx and s.parz == 1 and s.tekst() == "DL1ABC SP9ABC KO00" and s.dx_lok == "JO62"
    s.nadano(); s.nadano()                                   # dwa razy bez odpowiedzi – dalej wołamy
    assert s.tx and s.ile == 2
    s.odebrano(T + 30, [d("CQ SP1XYZ JO73"), d("SP9ABC DL1ABC -07", -11)])
    assert s.tekst() == "DL1ABC SP9ABC R-12" and s.rpt_o == "-07" and s.ile == 0
    s.nadano()
    s.odebrano(T + 60, [d("SP9ABC DL1ABC RR73")])
    assert s.tekst() == "DL1ABC SP9ABC 73"
    q = s.wez_log()
    assert q and (q["znak"], q["lok"], q["rpt_n"], q["rpt_o"]) == ("DL1ABC", "JO62", "-12", "-07") and s.wez_log() is None
    s.nadano()
    assert not s.tx                                          # po 73 koniec nadawania
    s.odebrano(T + 90, [d("SP9ABC DL1ABC RR73")])            # nie dosłyszał naszego 73 – nadajemy jeszcze raz
    assert s.tx and s.tekst() == "DL1ABC SP9ABC 73" and s.wez_log() is None      # ale łączność zapisana tylko raz


def test_moje_cq():
    """Moje CQ: ktoś woła -> raport -> RR73 (zapis po nadaniu RR73), powtórka RR73, gdy powtarza R-raport."""
    s = Q.Sekwencer("SP9ABC", "KO00")
    s.cq(teraz=T + 3)
    assert s.tx and s.parz == 1 and s.tekst() == "CQ SP9ABC KO00"
    s.nadano()
    s.odebrano(T + 30, [d("SP9ABC F4XYZ JN18", -15, 900), d("SP9ABC DL1ABC JO62", -3, 1500), d("CQ OH1AA KP10")], teraz=T + 44)
    assert s.dx == "DL1ABC" and s.tekst() == "DL1ABC SP9ABC -03" and s.parz == 1 and s.dx_hz == 1500
    s.nadano()
    s.odebrano(T + 60, [d("SP9ABC DL1ABC R-09"), d("SP9ABC F4XYZ JN18", -15)])
    assert s.tekst() == "DL1ABC SP9ABC RR73" and s.wez_log() is None           # zapis dopiero po nadaniu RR73
    s.nadano()
    q = s.wez_log()
    assert q and (q["rpt_n"], q["rpt_o"], q["lok"]) == ("-03", "-09", "JO62") and not s.tx
    s.odebrano(T + 90, [d("SP9ABC DL1ABC R-09")])            # nie dosłyszał RR73
    assert s.tx and s.tekst() == "DL1ABC SP9ABC RR73"
    s.nadano()
    s.odebrano(T + 120, [d("SP9ABC DL1ABC 73")])
    assert not s.tx and s.krok is None and s.wez_log() is None
    # stacja, która od razu daje raport zamiast lokatora
    s.cq(teraz=T + 3); s.nadano()
    s.odebrano(T + 30, [d("SP9ABC EA1ZZ -11", -8)])
    assert s.dx == "EA1ZZ" and s.tekst() == "EA1ZZ SP9ABC R-08"


def test_limity_i_reczne():
    s = Q.Sekwencer("SP9ABC", "KO00", limit=3, limit_cq=4)
    s.wolaj_znak("G4ABC", pocz=T + 15, snr=-20)
    assert s.parz == 0 and s.tekst() == "G4ABC SP9ABC KO00"
    for _ in range(3):
        assert s.tx
        s.nadano()
    assert not s.tx and "brak odpowiedzi" in s.powod         # trzy wołania bez odpowiedzi – stop
    s.odebrano(T + 15, [d("G4ABC DL1ABC -05"), d("CQ G4ABC IO91")])     # nie do nas – nic się nie zmienia
    assert not s.tx and s.krok == "LOK"
    s.odebrano(T + 45, [d("SP9ABC G4ABC -14")])              # jednak odpowiedział – jedziemy dalej
    assert s.tx and s.tekst() == "G4ABC SP9ABC R-20"
    s.ustaw_krok("RR73")
    assert s.tekst() == "G4ABC SP9ABC RR73"
    s.stop(); assert not s.tx
    s.wyczysc(); assert s.dx == "" and s.tekst() is None and s.biezaca() is None
    s.ustaw_krok("LOK"); assert s.krok is None               # bez korespondenta nie ma czego nadawać
    s.cq(teraz=T)
    for _ in range(4):
        s.nadano()
    assert not s.tx
    assert not s.wolaj(Q.rozbierz("CQ SP9ABC KO00"), T)      # własnego komunikatu nie wołamy


def test_adif():
    qo = qo100.QO100()
    q = {"znak": "DL1ABC", "lok": "JO62", "rpt_n": "-12", "rpt_o": "-07", "t_on": T, "t_off": T + 75, "dx_hz": 1234}
    f = Q.pola_adif(q, "SP9ABC", "KO00AA", 29_040_000 + 1500, 29_040_000 + 1234, qo, "3", logbook.band_of)
    assert f["freq"] == "2400.041500" and f["band"] == "13cm", f
    assert f["freq_rx"] == "10489.541234" and f["band_rx"] == "3cm", f
    assert (f["prop_mode"], f["sat_name"], f["mode"], f["rst_sent"], f["rst_rcvd"]) == ("SAT", "QO-100", "FT8", "-12", "-07")
    rec = logbook.adif_record(f)
    for kawalek in ("<CALL:6>DL1ABC", "<GRIDSQUARE:4>JO62", "<PROP_MODE:3>SAT", "<SAT_NAME:6>QO-100", "<BAND_RX:3>3cm",
                    "<FREQ:11>2400.041500", "<FREQ_RX:12>10489.541234", "<MY_GRIDSQUARE:6>KO00AA", "<EOR>"):
        assert kawalek in rec, (kawalek, rec)
    qo.calibrate(29_000_350)                                  # LNB 350 Hz za wysoko -> downlink w logu poprawiony
    assert Q.pola_adif(q, "SP9ABC", "KO00AA", 29_040_000, 29_040_350, qo)["freq_rx"] == "10489.540000"


def test_gridtracker():
    """Komunikaty WSJT-X dla GridTrackera: rozbieramy je z powrotem tak, jak zrobi to odbiorca."""
    import socket, struct
    import wsjtx_udp as W

    class Czyt:
        def __init__(self, b):
            self.b, self.i = b, 0

        def u(self, fmt):
            n = struct.calcsize(fmt)
            w = struct.unpack(fmt, self.b[self.i:self.i + n])[0]
            self.i += n
            return w

        def s(self):
            n = self.u(">I")
            w = self.b[self.i:self.i + n].decode("utf-8")
            self.i += n
            return w

    c = Czyt(W.dekod(T + 15 + 86400 * 3, -12.4, 0.3, 1234.4, "CQ DL1ABC JO62"))
    assert (c.u(">I"), c.u(">I"), c.u(">I"), c.s()) == (0xADBCCBDA, 2, 2, "GOLbase")
    assert c.u(">?") is True and c.u(">I") == ((T + 15) % 86400) * 1000 and c.u(">i") == -12
    assert abs(c.u(">d") - 0.3) < 1e-9 and c.u(">I") == 1234 and c.s() == "~" and c.s() == "CQ DL1ABC JO62"
    assert c.u(">?") is False and c.u(">?") is False and c.i == len(c.b)

    c = Czyt(W.stan(10_489_540_000, "SP9ABC", "KO00AA", dx="DL1ABC", dx_lok="JO62", raport="-12", tx_wlaczone=True,
                    nadaje=False, rx_df=1234, tx_df=1500, tx_tekst="DL1ABC SP9ABC KO00"))
    assert (c.u(">I"), c.u(">I"), c.u(">I"), c.s()) == (0xADBCCBDA, 2, 1, "GOLbase")
    assert c.u(">Q") == 10_489_540_000 and c.s() == "FT8" and c.s() == "DL1ABC" and c.s() == "-12" and c.s() == "FT8"
    assert (c.u(">?"), c.u(">?"), c.u(">?")) == (True, False, True) and (c.u(">I"), c.u(">I")) == (1234, 1500)
    assert (c.s(), c.s(), c.s()) == ("SP9ABC", "KO00AA", "JO62")
    assert c.u(">?") is False and c.s() == "" and c.u(">?") is False and c.u(">B") == 0
    assert c.u(">I") == 0xFFFFFFFF and c.u(">I") == 15 and c.s() == "QO-100" and c.s() == "DL1ABC SP9ABC KO00"
    assert c.i == len(c.b)

    c = Czyt(W.zyje("1.11"))
    assert (c.u(">I"), c.u(">I"), c.u(">I"), c.s(), c.u(">I"), c.s(), c.s()) == (0xADBCCBDA, 2, 0, "GOLbase", 3, "1.11", "")
    assert W.koniec()[8:12] == struct.pack(">I", 6)

    # wysyłka naprawdę wychodzi po UDP, a zły adres albo brak odbiorcy niczego nie wywraca
    odb = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    odb.bind(("127.0.0.1", 0)); odb.settimeout(2)
    n = W.Nadawca()
    assert n.wyslij("127.0.0.1:%d" % odb.getsockname()[1], W.zyje("1.11"), W.dekod(T, -5, 0.1, 900, "CQ SP1XYZ JO73"))
    assert odb.recv(2000) == W.zyje("1.11") and odb.recv(2000).endswith(b"CQ SP1XYZ JO73\x00\x00")
    assert not n.wyslij("zly adres", W.zyje()) and n.wyslij("127.0.0.1:9", W.zyje())
    n.zamknij(); odb.close()


def test_start_w_trakcie_okna():
    """Spóźniony start nadawania: bez początku, a reszta w swoim czasie; z biblioteką – czy da się to jeszcze zdekodować."""
    import numpy as np
    D = Q
    fs = 48000
    syg = np.arange(int(12.64 * fs), dtype=np.float32) + 1
    d, u = D.dzwiek_okna(syg, 0.1, fs)
    assert u == 0 and len(d) == len(syg) + int(0.4 * fs) and d[int(0.4 * fs)] == 1 and not d[:int(0.4 * fs)].any()
    d, u = D.dzwiek_okna(syg, 3.5, fs)
    assert abs(u - 3.0) < 1e-6 and len(d) == len(syg) - 3 * fs and d[-1] == syg[-1] and d[fs] == syg[4 * fs]
    assert D.dzwiek_okna(syg, 99, fs)[0].size == 0
    try:
        import ft8silnik as F
        sil = F.Silnik()
    except (ImportError, OSError) as e:
        print("  (dekodowanie pominiete: %r)" % (e,))
        return
    tekst = "DL1ABC SP9ABC R-12"
    syg = F.synteza(sil.tony(sil.pakuj_tekst(tekst)), 1500.0)
    rng = np.random.default_rng(7)
    for spoznienie in (1.0, 3.0, 4.0, 5.0):
        buf = rng.normal(0, 0.02, int(13.6 * F.FS_AUDIO)).astype(np.float32)
        d, _ = D.dzwiek_okna(syg, spoznienie, F.FS_AUDIO)
        i = int(max(spoznienie, 0.5) * F.FS_AUDIO)
        buf[i:i + len(d)] += d[:len(buf) - i] * 0.05
        dek = [x.tekst for x in sil.dekoduj(F.na_12k(buf))]
        print("  start %.0f s po poczatku okna: %s" % (spoznienie, "zdekodowany" if tekst in dek else "NIE zdekodowany"))
        if spoznienie <= 3.0:
            assert tekst in dek, (spoznienie, dek)


def test_zegar_probek():
    """Czas próbek (DT): opóźnienie karty i nierówne dostarczanie bloków nie mogą przesuwać okna o dziesiąte części sekundy."""
    import random
    try:
        import numpy as np
        import ft8silnik as F
    except (ImportError, OSError) as e:
        print("  (pominiety: %r)" % (e,))
        return
    rnd = random.Random(3)
    blok = np.zeros(1200, np.float32)
    for kwarc in (-60e-6, 0.0, 60e-6):                       # karta za wolna / dokładna / za szybka
        stare, F.OPOZNIENIE_WEJSCIA = F.OPOZNIENIE_WEJSCIA, 0.15
        try:
            o = F.Okna()
            t = 1795000000.0                                 # prawdziwy czas pierwszej próbki bloku
            bledy = []
            for i in range(40 * 60 * 20):                    # 20 minut po 40 bloków na sekundę
                dl = 1200 / 48000.0 / (1 + kwarc)            # tyle naprawdę trwa blok
                dotarl = t + dl + 0.15 + rnd.choice((0.0, 0.0, 0.01, 0.03, 0.12))
                o.podaj(blok, teraz=dotarl)
                bledy.append(o.bloki[-1][0] - t)
                t += dl
            assert max(abs(b) for b in bledy[2000:]) < 0.04, (kwarc, min(bledy[2000:]), max(bledy[2000:]))
        finally:
            F.OPOZNIENIE_WEJSCIA = stare


def test_silnik():
    """Każdy komunikat łączności: tekst -> tony -> dźwięk z szumem -> dekoder -> ten sam tekst."""
    try:
        import numpy as np
        import ft8silnik as F
        sil = F.Silnik()
    except (ImportError, OSError) as e:
        print("  (pominięty: %s)" % e)
        return
    s = Q.Sekwencer("SP9ABC", "KO00AA")
    s.wolaj(Q.rozbierz("CQ DL1ABC JO62"), T, snr=-12)
    teksty = ["CQ SP9ABC KO00"] + [s.tekst(k) for k in Q.KROKI[1:]]
    rng = np.random.default_rng(5)
    buf = rng.normal(0, 0.05, int(13.6 * F.FS_AUDIO)).astype(np.float32)
    i = int(0.5 * F.FS_AUDIO)
    for k, t in enumerate(teksty):
        a = F.synteza(sil.tony(sil.pakuj_tekst(t)), 500.0 + 300 * k)
        buf[i:i + len(a)] += a * 0.012
    dek = sil.dekoduj(F.na_12k(buf))
    assert sorted(x.tekst for x in dek) == sorted(teksty), (dek, teksty)
    for x in dek:
        p = Q.rozbierz(x.tekst)
        assert p and p["od"] == "SP9ABC", x
    assert [Q.rozbierz(t)["co"] for t in teksty] == ["CQ", "LOK", "RPT", "RRPT", "RR73", "73"]


if __name__ == "__main__":
    for nazwa, f in sorted(globals().items()):
        if nazwa.startswith("test_"):
            print(nazwa)
            f()
    print("OK")

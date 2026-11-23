"""
Komunikaty UDP w formacie WSJT-X / JTDX dla programów pokazujących dekody na mapie (GridTracker, JTAlert itp.).

Zakładka „FT8 QO-100” (od wersji 1.11) wysyła nimi to samo, co JTDX: „żyję” (typ 0), stan programu (typ 1)
i każdy dekod (typ 2). GridTracker rysuje z tego stacje i lokatory. Łączności do logu idą osobno (logbook.py, typ 12)
– tu ich NIE wysyłamy, żeby GridTracker nie zapisał łączności drugi raz.

Format: liczby w kolejności sieciowej (big-endian), napis = długość (4 bajty) + UTF-8 – jak QDataStream w WSJT-X.
"""
import socket, struct

MAGIC = 0xADBCCBDA
SCHEMA = 2
ID = "GOLbase"


def _s(t):
    b = (t or "").encode("utf-8")
    return struct.pack(">I", len(b)) + b


def _b(x):
    return b"\x01" if x else b"\x00"


def _glowa(typ, ident=ID):
    return struct.pack(">III", MAGIC, SCHEMA, typ) + _s(ident)


def zyje(wersja="", ident=ID):
    """Typ 0 – Heartbeat (co ok. 15 s)."""
    return _glowa(0, ident) + struct.pack(">I", 3) + _s(wersja) + _s("")


def stan(dial_hz, moj, moj_lok, dx="", dx_lok="", raport="", tx_wlaczone=False, nadaje=False, dekoduje=True,
         rx_df=1500, tx_df=1500, tx_tekst="", ident=ID):
    """Typ 1 – Status: częstotliwość, tryb FT8, mój znak i lokator, korespondent, czy nadaję."""
    return (_glowa(1, ident) + struct.pack(">Q", int(dial_hz)) + _s("FT8") + _s(dx) + _s(raport) + _s("FT8")
            + _b(tx_wlaczone) + _b(nadaje) + _b(dekoduje) + struct.pack(">II", int(rx_df), int(tx_df))
            + _s(moj) + _s(moj_lok) + _s(dx_lok) + _b(False) + _s("") + _b(False) + b"\x00"
            + struct.pack(">II", 0xFFFFFFFF, 15) + _s("QO-100") + _s(tx_tekst))


def dekod(pocz, snr, dt, hz, tekst, nowy=True, ident=ID):
    """Typ 2 – Decode: pocz = początek okna (czas uniksowy), dt [s], hz = częstotliwość dźwięku."""
    ms = (int(pocz) % 86400) * 1000
    return (_glowa(2, ident) + _b(nowy) + struct.pack(">Iid", ms, int(round(snr)), float(dt))
            + struct.pack(">I", max(0, int(round(hz)))) + _s("~") + _s(tekst) + _b(False) + _b(False))


def koniec(ident=ID):
    """Typ 6 – Close (program się zamyka)."""
    return _glowa(6, ident)


class Nadawca:
    """Wysyłka pod jeden adres „host:port”. Błędy sieci są połykane – mapa nie może zatrzymać łączności."""

    def __init__(self):
        self.gniazdo = None
        self.adres = None

    def wyslij(self, adres, *paczki):
        try:
            host, port = adres.rsplit(":", 1)
            cel = (host.strip(), int(port))
            if self.gniazdo is None:
                self.gniazdo = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            for p in paczki:
                self.gniazdo.sendto(p, cel)
            return True
        except (OSError, ValueError):
            return False

    def zamknij(self):
        try:
            if self.gniazdo is not None:
                self.gniazdo.close()
        except OSError:
            pass
        self.gniazdo = None

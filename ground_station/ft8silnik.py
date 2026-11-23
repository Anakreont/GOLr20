"""
Silnik FT8/FT4 dla GOLbase (zakładka „FT8 balon”).

Dekodowanie i kodowanie robi biblioteka kgoba/ft8_lib (ta sama, która pracuje w trackerze-robocie) przez cienką
warstwę C `ft8/ft8shim.c`, zbudowaną jako ft8shim.dll (Windows) / libft8shim.so (Linux, do testów).
Tutaj: wczytanie biblioteki (ctypes), synteza dźwięku GFSK, zmiana próbkowania 48 kHz -> 12 kHz
i składanie dźwięku z karty w okna 15-sekundowe (klasa Okna).
"""
import ctypes, math, os, sys, threading, time

import numpy as np

FS_AUDIO = 48000          # karta dźwiękowa radia
FS_DEC = 12000            # dekoder
OKNO_FT8, OKNO_FT4 = 15.0, 7.5
MAX_WYNIKOW = 80


class _Wynik(ctypes.Structure):
    _fields_ = [("freq_hz", ctypes.c_float), ("dt_s", ctypes.c_float), ("snr_db", ctypes.c_float),
                ("score", ctypes.c_int32), ("type", ctypes.c_int32), ("payload", ctypes.c_uint8 * 10),
                ("text", ctypes.c_char * 40)]


class Dekod:
    """Jeden zdekodowany komunikat."""
    __slots__ = ("hz", "dt", "snr", "tekst", "payload", "typ")

    def __init__(self, hz, dt, snr, tekst, payload, typ):
        self.hz, self.dt, self.snr, self.tekst, self.payload, self.typ = hz, dt, snr, tekst, payload, typ

    @property
    def telemetria(self):
        """Ramka typu telemetria: i3 = 0 (bity 74–76), n3 = 5 (bity 71–73)."""
        p = self.payload
        return (p[9] >> 3) & 7 == 0 and (((p[8] & 1) << 2) | (p[9] >> 6)) == 5

    @property
    def bity71(self):
        """71 bitów telemetrii jako liczba (tylko dla ramek typu telemetria)."""
        return int.from_bytes(self.payload[:9], "big") >> 1

    def __repr__(self):
        return f"Dekod({self.snr:+.0f} dB {self.dt:+.1f} s {self.hz:.0f} Hz '{self.tekst}')"


def _szukaj_biblioteki():
    nazwa = "ft8shim.dll" if os.name == "nt" else "libft8shim.so"
    tu = os.path.dirname(os.path.abspath(__file__))
    for kat in (getattr(sys, "_MEIPASS", None), tu, os.path.join(tu, "ft8")):
        if kat and os.path.exists(os.path.join(kat, nazwa)):
            return os.path.join(kat, nazwa)
    return None


class Silnik:
    """Dostęp do biblioteki ft8shim. Wyjątek OSError, gdy biblioteki nie ma (program pokazuje wtedy komunikat)."""

    def __init__(self, sciezka=None):
        sciezka = sciezka or _szukaj_biblioteki()
        if not sciezka:
            raise OSError("brak biblioteki ft8shim (dll/so) – zainstaluj program instalatorem albo zbuduj ft8/buduj.sh")
        self.lib = ctypes.CDLL(sciezka)
        L = self.lib
        L.ft8s_decode.argtypes = [ctypes.POINTER(ctypes.c_float), ctypes.c_int, ctypes.c_int, ctypes.c_float,
                                  ctypes.c_float, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  ctypes.POINTER(_Wynik), ctypes.c_int]
        L.ft8s_decode.restype = ctypes.c_int
        L.ft8s_pack_text.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint8)]
        L.ft8s_pack_telem.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.POINTER(ctypes.c_uint8)]
        L.ft8s_tones.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_int, ctypes.POINTER(ctypes.c_uint8)]
        L.ft8s_unpack.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_char_p, ctypes.POINTER(ctypes.c_int32)]
        L.ft8s_add_call.argtypes = [ctypes.c_char_p]
        L.ft8s_add_call.restype = None
        self.blokada = threading.Lock()          # biblioteka ma wspólną tablicę skrótów znaków

    def dekoduj(self, probki12k, f_min=200.0, f_max=3000.0, ft4=False, kandydaci=200, iteracje=30):
        """Próbki float32 12 kHz od początku okna -> lista Dekod."""
        x = np.ascontiguousarray(probki12k, dtype=np.float32)
        out = (_Wynik * MAX_WYNIKOW)()
        with self.blokada:
            n = self.lib.ft8s_decode(x.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), len(x), FS_DEC,
                                     float(f_min), float(f_max), int(ft4), kandydaci, iteracje, out, MAX_WYNIKOW)
        wyn = [Dekod(r.freq_hz, r.dt_s, r.snr_db, r.text.decode("ascii", "replace"), bytes(r.payload), r.type)
               for r in out[:n]]
        wyn.sort(key=lambda d: d.hz)
        return wyn

    def pakuj_tekst(self, tekst):
        """Tekst komunikatu (np. 'SP1A SP9ABC KO00') -> 10 bajtów. ValueError, gdy nie da się zakodować."""
        buf = (ctypes.c_uint8 * 10)()
        with self.blokada:
            rc = self.lib.ft8s_pack_text(tekst.upper().encode("ascii", "ignore"), buf)
        if rc != 0:
            raise ValueError(f"nie da się zakodować komunikatu FT8: '{tekst}' (kod {rc})")
        return bytes(buf)

    def pakuj_telemetrie(self, bity71):
        """71 bitów (liczba) -> 10 bajtów ramki typu telemetria."""
        if not 0 <= bity71 < (1 << 71):
            raise ValueError("telemetria musi mieć najwyżej 71 bitów")
        t = (ctypes.c_uint8 * 9)(*bity71.to_bytes(9, "big"))
        buf = (ctypes.c_uint8 * 10)()
        with self.blokada:
            if self.lib.ft8s_pack_telem(t, buf) != 0:
                raise ValueError("błąd pakowania telemetrii")
        return bytes(buf)

    def tony(self, payload, ft4=False):
        p = (ctypes.c_uint8 * 10)(*payload)
        t = (ctypes.c_uint8 * 128)()
        n = self.lib.ft8s_tones(p, int(ft4), t)
        return list(t[:n])

    def rozpakuj(self, payload):
        """10 bajtów -> (tekst, typ)."""
        p = (ctypes.c_uint8 * 10)(*payload)
        txt = ctypes.create_string_buffer(40)
        typ = ctypes.c_int32()
        with self.blokada:
            rc = self.lib.ft8s_unpack(p, txt, ctypes.byref(typ))
        return (txt.value.decode("ascii", "replace") if rc == 0 else "?"), typ.value

    def dodaj_znak(self, znak):
        with self.blokada:
            self.lib.ft8s_add_call(znak.upper().encode("ascii", "ignore"))


# ---------------------------------------------------------------------- dźwięk
def synteza(tony, f0, fs=FS_AUDIO, ft4=False, poziom=0.5):
    """Tony FT8 (79) / FT4 (105) -> próbki float32 (GFSK jak w WSJT-X). f0 = częstotliwość najniższego tonu."""
    baud, bt = (20.8333333, 1.0) if ft4 else (6.25, 2.0)
    n_sps = int(round(fs / baud))
    n_sym = len(tony)
    k = math.pi * math.sqrt(2.0 / math.log(2.0))
    t = (np.arange(3 * n_sps) / n_sps) - 1.5
    erf = np.vectorize(math.erf)
    impuls = (erf(k * bt * (t + 0.5)) - erf(k * bt * (t - 0.5))) / 2.0
    dphi_max = 2 * math.pi * 1.0 / n_sps                 # indeks modulacji h = 1
    dphi = np.full((n_sym + 2) * n_sps, 2 * math.pi * f0 / fs)
    for i, s in enumerate(tony):
        dphi[i * n_sps:(i + 3) * n_sps] += dphi_max * s * impuls
    dphi[:2 * n_sps] += dphi_max * tony[0] * impuls[n_sps:]          # symbole „przed” i „po” – przedłużenie skrajnych
    dphi[n_sym * n_sps:] += dphi_max * tony[-1] * impuls[:2 * n_sps]
    faza = np.cumsum(dphi[n_sps:(n_sym + 1) * n_sps])
    x = np.sin(faza)
    n_ramp = n_sps // 8
    rampa = 0.5 * (1 - np.cos(np.pi * np.arange(n_ramp) / n_ramp))
    x[:n_ramp] *= rampa
    x[-n_ramp:] *= rampa[::-1]
    return (poziom * x).astype(np.float32)


def _filtr(n=97, fc=4300.0, fs=FS_AUDIO):
    m = np.arange(n) - (n - 1) / 2
    h = np.sinc(2 * fc / fs * m) * np.hamming(n)
    return (h / h.sum()).astype(np.float32)


_FILTR = _filtr()


def na_12k(x48):
    """48 kHz -> 12 kHz (filtr dolnoprzepustowy 4,3 kHz + co czwarta próbka)."""
    return np.convolve(np.asarray(x48, np.float32), _FILTR, mode="same")[::4].astype(np.float32)


def poczatek_okna(t, okno=OKNO_FT8):
    return math.floor(t / okno) * okno


OPOZNIENIE_WEJSCIA = 0.0      # [s] opóźnienie karty dźwiękowej na wejściu (ustawia program po „Start odbioru”)
PELZANIE = 1e-4               # zegar próbek wolno „pełznie” do przodu, a cofa go każdy blok, który przyszedł wcześniej


class Okna:
    """Zbiera dźwięk 48 kHz z karty i wycina okna zgodne z zegarem UTC komputera.

    podaj(x)      – kolejny blok próbek (z wątku audio),
    gotowe(teraz) – zwraca (początek_okna, próbki 12 kHz), gdy minęło `koniec_s` sekund okna; inaczej None.
    """

    def __init__(self, okno=OKNO_FT8, koniec_s=13.6, fs=FS_AUDIO):
        self.okno, self.koniec_s, self.fs = okno, koniec_s, fs
        self.bloki = []                    # (czas pierwszej próbki, próbki)
        self.t_nast = None                 # oczekiwany czas następnej próbki (zegar próbek)
        self.ostatnie = 0.0                # początek ostatnio oddanego okna
        self.blokada = threading.Lock()

    def podaj(self, x, teraz=None):
        teraz = time.time() if teraz is None else teraz
        # Blok dociera do programu zawsze PÓŹNIEJ, niż został nagrany (bufor karty, kolejka) – nigdy wcześniej.
        # Dlatego najlepszym zegarem próbek jest ten wyznaczony przez bloki, które przyszły najszybciej: każdy
        # wcześniejszy blok cofa zegar, a między nimi zegar pełznie do przodu o 0,01 % (pokrywa błąd kwarcu karty).
        # Do 1.12 zegar poprawiał się dopiero przy różnicy 0,25 s i nie odejmował opóźnienia karty – DT wychodziło
        # o kilka dziesiątych sekundy za duże („ustaw zegar komputera” przy dobrym zegarze).
        t0 = teraz - len(x) / self.fs - OPOZNIENIE_WEJSCIA
        with self.blokada:
            if self.t_nast is None or t0 < self.t_nast or t0 - self.t_nast > 0.25:   # start, wcześniejszy blok, przerwa
                self.t_nast = t0
            self.bloki.append((self.t_nast, x))
            self.t_nast += len(x) / self.fs * (1 + PELZANIE)
            stare = teraz - 2 * self.okno - 5
            while self.bloki and self.bloki[0][0] < stare:
                self.bloki.pop(0)

    def gotowe(self, teraz=None):
        teraz = time.time() if teraz is None else teraz
        p = poczatek_okna(teraz, self.okno)
        if teraz - p < self.koniec_s or p <= self.ostatnie:
            return None
        self.ostatnie = p
        n = int(self.koniec_s * self.fs)
        buf = np.zeros(n, np.float32)
        ile = 0
        with self.blokada:
            for t, x in self.bloki:
                i = int(round((t - p) * self.fs))
                a, b = max(i, 0), min(i + len(x), n)
                if b > a:
                    buf[a:b] = x[a - i:b - i]
                    ile += b - a
        if ile < 0.6 * n:                  # za mało dźwięku z tego okna (np. dopiero włączono odbiór)
            return None
        return p, na_12k(buf)

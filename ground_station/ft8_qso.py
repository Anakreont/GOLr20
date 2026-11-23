"""
Zwykła łączność FT8 – rozbiór komunikatów i automat kolejnych kroków (zakładka „FT8 QO-100” programu GOLbase).

Bez okna i bez radia – sama logika, żeby dało się ją sprawdzić testem (test_qo.py):
  rozbierz(tekst)  – komunikat FT8 -> kto, do kogo, co (lokator / raport / R-raport / RR73 / 73),
  Sekwencer        – prowadzi łączność krok po kroku jak JTDX/WSJT-X (Auto Seq),
  pola_adif(...)   – wpis do logu z częstotliwościami QO-100 (uplink 13 cm, downlink 3 cm, PROP_MODE = SAT).

Kroki łączności (to, co MY nadajemy):
  CQ    CQ SP9ABC KO00
  LOK   DL1ABC SP9ABC KO00      wołam stację
  RPT   DL1ABC SP9ABC -12       raport
  RRPT  DL1ABC SP9ABC R-12      potwierdzenie + raport
  RR73  DL1ABC SP9ABC RR73      koniec (tu zapisujemy łączność)
  73    DL1ABC SP9ABC 73        koniec po jego RR73 (zapis po odebraniu RR73)
"""
import re, threading, time

KROKI = ("CQ", "LOK", "RPT", "RRPT", "RR73", "73")
OPISY = {"CQ": "wołam CQ", "LOK": "wołam stację", "RPT": "daję raport", "RRPT": "potwierdzam raport",
         "RR73": "kończę (RR73)", "73": "żegnam (73)"}
_LOK = re.compile(r"^[A-R]{2}[0-9]{2}$")
_RPT = re.compile(r"^(R?)([+-][0-9]{2})$")
_ZNAK = re.compile(r"^[A-Z0-9/]{3,11}$")


def znak_ok(z):
    return bool(_ZNAK.match(z)) and any(c.isdigit() for c in z) and any(c.isalpha() for c in z)


def raport(snr):
    """SNR z dekodera -> raport FT8 (-30…+30, zawsze ze znakiem i dwiema cyframi)."""
    return f"{max(-30, min(30, int(round(snr)))):+03d}"


def rozbierz(tekst):
    """Komunikat FT8 -> {"cq", "do", "od", "co", "lok", "rpt"} albo None (wolny tekst, telemetria, nieznany skrót znaku).

    co: "CQ", "LOK" (lokator albo sam znak), "RPT" (-12), "RRPT" (R-12), "RRR", "RR73", "73".
    """
    s = tekst.upper().replace("<", " ").replace(">", " ").split()
    if len(s) < 2:
        return None
    if s[0] == "CQ":
        lok = s[-1] if len(s) >= 3 and _LOK.match(s[-1]) and s[-1] != "RR73" else ""
        od = s[-2] if lok else s[-1]
        if not znak_ok(od):
            return None
        return {"cq": True, "do": "", "od": od, "co": "CQ", "lok": lok, "rpt": ""}
    do, od = s[0], s[1]
    if not znak_ok(od) or not znak_ok(do):
        return None
    x = s[2] if len(s) > 2 else ""
    w = {"cq": False, "do": do, "od": od, "co": "LOK", "lok": "", "rpt": ""}
    m = _RPT.match(x)
    if x in ("RRR", "RR73", "73"):
        w["co"] = x
    elif m:
        w["co"], w["rpt"] = ("RRPT" if m.group(1) else "RPT"), m.group(2)
    elif _LOK.match(x):
        w["lok"] = x
    elif x:
        return None                       # coś, czego nie rozumiemy (np. zawody) – nie zgadujemy
    return w


def okres(pocz):
    """Parzystość okna 15 s: 0 = okna zaczynające się w :00 i :30, 1 = w :15 i :45."""
    return int(round(pocz / 15.0)) % 2


def dzwiek_okna(sygnal, spoznienie, fs):
    """Dźwięk do zagrania, gdy od początku okna minęło `spoznienie` sekund. Zwraca (próbki, ile sekund sygnału ucięto).

    Sygnał FT8 zaczyna się 0,5 s po początku okna. Zdążyliśmy przed tym – dokładamy ciszę. Spóźnieni – jak JTDX
    pomijamy początek i gramy od miejsca, które wypada teraz, żeby reszta komunikatu trafiła u odbiorcy w swój czas.
    """
    import numpy as np
    spoznienie = max(0.0, spoznienie)
    if spoznienie <= 0.5:
        return np.concatenate([np.zeros(int((0.5 - spoznienie) * fs), np.float32), sygnal]), 0.0
    n = min(len(sygnal), int(round((spoznienie - 0.5) * fs)))
    reszta = np.array(sygnal[n:], np.float32)
    rampa = min(len(reszta), int(0.02 * fs))                   # łagodny początek – bez trzasku
    if rampa:
        reszta[:rampa] *= 0.5 * (1 - np.cos(np.pi * np.arange(rampa) / rampa))
    return reszta, n / fs


class Sekwencer:
    """Stan jednej łączności FT8 i reguły przechodzenia między krokami. Wszystkie metody są bezpieczne między wątkami."""

    def __init__(self, moj, lokator, limit=6, limit_cq=12):
        self.blokada = threading.RLock()
        self.moj = moj.upper()
        self.lokator = (lokator or "").upper()
        self.limit, self.limit_cq = int(limit), int(limit_cq)
        self.tx = False                  # czy nadawać w swoich oknach
        self.parz = 0                    # w których oknach nadajemy (okres())
        self.powod = ""                  # dlaczego nadawanie się wyłączyło (do pokazania w oknie)
        self.do_logu = None              # gotowa łączność czekająca na zapis (odbiera wez_log)
        self._nowa("")

    def _nowa(self, dx):
        self.dx, self.dx_lok = dx, ""
        self.rpt_n = None                # raport nadany (np. "-12")
        self.rpt_o = None                # raport odebrany
        self.krok = None
        self.ile = 0                     # ile razy nadano bieżący krok bez postępu
        self.t_on = None
        self.zapisana = False
        self.dx_hz = None

    @property
    def lok4(self):
        return self.lokator[:4]

    # ------------------------------------------------------------------ co nadać
    def tekst(self, krok=None):
        """Treść komunikatu dla kroku (domyślnie bieżącego); None, gdy nie ma czego nadać."""
        k = krok or self.krok
        if k == "CQ":
            return f"CQ {self.moj} {self.lok4}".strip()
        if not k or not self.dx:
            return None
        if k == "LOK":
            return f"{self.dx} {self.moj} {self.lok4}".strip()
        if k == "RPT":
            return f"{self.dx} {self.moj} {self.rpt_n or '-15'}"
        if k == "RRPT":
            return f"{self.dx} {self.moj} R{self.rpt_n or '-15'}"
        return f"{self.dx} {self.moj} {k}"            # RR73, 73

    # ------------------------------------------------------------------ polecenia operatora
    def cq(self, teraz=None):
        """Zacznij wołać CQ od najbliższego okna."""
        with self.blokada:
            teraz = time.time() if teraz is None else teraz
            self._nowa("")
            self.krok, self.tx, self.powod = "CQ", True, ""
            self.parz = (int(teraz // 15) + 1) % 2

    def wolaj(self, p, pocz, snr=None, hz=None, teraz=None):
        """Operator wybrał komunikat stacji (dwuklik): zaczynamy / podejmujemy łączność z nadawcą tego komunikatu."""
        with self.blokada:
            if not p or p["od"] == self.moj:
                return False
            if p["od"] != self.dx:
                self._nowa(p["od"])
            self.t_on = self.t_on or (time.time() if teraz is None else teraz)
            self.parz = (okres(pocz) + 1) % 2
            if snr is not None and self.rpt_n is None:
                self.rpt_n = raport(snr)
            if hz is not None:
                self.dx_hz = hz
            if p["lok"]:
                self.dx_lok = p["lok"]
            self.ile, self.powod = 0, ""
            if p["do"] == self.moj:
                self._postep(p)
            elif self.krok in (None, "CQ"):
                self.krok = "LOK"
            if self.krok:
                self.tx = True
            return True

    def wolaj_znak(self, znak, pocz=None, snr=None, hz=None, teraz=None):
        """Wołaj stację wpisaną ręcznie; pocz = okno, w którym ją ostatnio słyszano (żeby nadawać w przeciwnym)."""
        teraz = time.time() if teraz is None else teraz
        if pocz is None:
            pocz = int(teraz // 15) * 15           # nie wiemy, kiedy nadaje – zaczynamy od najbliższego okna
        return self.wolaj({"cq": True, "do": "", "od": znak.upper(), "co": "CQ", "lok": "", "rpt": ""}, pocz, snr, hz, teraz)

    def ustaw_krok(self, krok):
        with self.blokada:
            if krok == "CQ" or self.dx:
                self.krok, self.ile, self.powod = krok, 0, ""

    def stop(self, powod=""):
        with self.blokada:
            self.tx, self.powod = False, powod

    def wyczysc(self):
        with self.blokada:
            self.tx = False
            self._nowa("")
            self.powod = ""

    # ------------------------------------------------------------------ automat
    def _postep(self, p):
        """Komunikat od naszego korespondenta skierowany do nas -> następny krok."""
        stary = self.krok
        co = p["co"]
        if co == "LOK":
            if self.krok in (None, "CQ", "LOK", "RPT"):
                self.krok = "RPT"
        elif co == "RPT":
            self.rpt_o = p["rpt"]
            if self.krok not in ("RR73", "73"):
                self.krok = "RRPT"
        elif co == "RRPT":
            self.rpt_o = p["rpt"]
            self.krok = "RR73"
        elif co in ("RRR", "RR73"):
            self.krok = "73"
            self._koniec()
        elif co == "73":
            self._koniec()
            self.krok, self.tx = None, False
            return
        if self.krok != stary:
            self.ile = 0
        if self.ile < self.limit:
            self.tx, self.powod = True, ""

    def _koniec(self):
        if self.zapisana or not self.dx or not self.rpt_o or not self.rpt_n:
            return
        self.zapisana = True
        self.do_logu = {"znak": self.dx, "lok": self.dx_lok, "rpt_n": self.rpt_n, "rpt_o": self.rpt_o,
                        "t_on": self.t_on or time.time(), "t_off": time.time(), "dx_hz": self.dx_hz}

    def odebrano(self, pocz, dekody, teraz=None):
        """Dekody jednego okna: lista (rozbierz(tekst), snr, hz). Zwraca True, gdy coś było do nas."""
        with self.blokada:
            do_mnie = [(p, snr, hz) for p, snr, hz in dekody if p and p["do"] == self.moj and p["od"] != self.moj]
            moje = [x for x in do_mnie if self.dx and x[0]["od"] == self.dx]
            for p, snr, hz in moje:
                if self.rpt_n is None:
                    self.rpt_n = raport(snr)
                if p["lok"]:
                    self.dx_lok = p["lok"]
                self.dx_hz = hz
                self._postep(p)
            if not moje and do_mnie and self.krok == "CQ" and self.tx:
                # ktoś odpowiedział na nasze CQ – bierzemy najsilniejszego
                p, snr, hz = max(do_mnie, key=lambda x: x[1])
                if p["co"] in ("LOK", "RPT"):
                    self.wolaj(p, pocz, snr, hz, teraz)
            return bool(do_mnie)

    def nadano(self):
        """Wołać po każdym nadanym w całości komunikacie."""
        with self.blokada:
            self.ile += 1
            if self.krok == "RR73":
                self._koniec()
                self.tx = False                    # wznowi się samo, jeśli korespondent powtórzy R-raport
            elif self.krok == "73":
                self.tx = False
            elif self.ile >= (self.limit_cq if self.krok == "CQ" else self.limit):
                self.tx, self.powod = False, f"brak odpowiedzi po {self.ile} nadaniach – nadawanie wyłączone"

    def wez_log(self):
        with self.blokada:
            q, self.do_logu = self.do_logu, None
            return q

    def biezaca(self):
        """Łączność w toku jako słownik do ręcznego zapisu (None, gdy nie ma korespondenta)."""
        with self.blokada:
            if not self.dx:
                return None
            return {"znak": self.dx, "lok": self.dx_lok, "rpt_n": self.rpt_n or "", "rpt_o": self.rpt_o or "",
                    "t_on": self.t_on or time.time(), "t_off": time.time(), "dx_hz": self.dx_hz}

    def oznacz_zapisana(self):
        with self.blokada:
            self.zapisana, self.do_logu = True, None


# ---------------------------------------------------------------------- log
def pola_adif(q, moj, moj_lok, tx_if_hz, rx_if_hz, qo, tx_pwr="", pasmo_fn=None):
    """Łączność (słownik z Sekwencera) -> pola ADIF dla pracy przez QO-100.

    tx_if_hz / rx_if_hz – częstotliwości sygnałów na pośredniej (radio + ton dźwięku); qo – obiekt qo100.QO100.
    FREQ = uplink (13 cm), FREQ_RX = downlink (3 cm), PROP_MODE = SAT, SAT_NAME = QO-100.
    """
    up, dn = qo.uplink(tx_if_hz), qo.downlink(rx_if_hz)
    t1, t2 = time.gmtime(q["t_on"]), time.gmtime(q["t_off"])
    pasmo = pasmo_fn or (lambda mhz: "")
    return {"call": q["znak"], "gridsquare": q.get("lok", ""), "mode": "FT8",
            "qso_date": time.strftime("%Y%m%d", t1), "time_on": time.strftime("%H%M%S", t1),
            "qso_date_off": time.strftime("%Y%m%d", t2), "time_off": time.strftime("%H%M%S", t2),
            "rst_sent": q.get("rpt_n", ""), "rst_rcvd": q.get("rpt_o", ""),
            "freq": f"{up / 1e6:.6f}", "band": pasmo(up / 1e6), "freq_rx": f"{dn / 1e6:.6f}", "band_rx": pasmo(dn / 1e6),
            "prop_mode": "SAT", "sat_name": "QO-100", "station_callsign": moj, "operator": moj,
            "my_gridsquare": moj_lok, "tx_pwr": tx_pwr, "comment": "FT8 QO-100 (GOLbase)"}

"""
Log trackera-robota FT8 składany z odebranych ramek (robot_proto.py). Czysty Python – ten sam plik
ma pracować w programie GOLbase (tryb lokalny).

Ramka LOG niesie tylko numer wpisu modulo 8, więc pełny numer ustala się tutaj (funkcja _numeruj):
  * czasy wpisów rosną razem z numerami (wpis późniejszy ma numer większy),
  * ramka STAN mówi, ile wpisów tracker miał w chwili jej nadania.
Gdy numer da się ustalić jednoznacznie – wpis dostaje numer; gdy nie – czeka jako „luźny” i jest sprawdzany
ponownie po każdej nowej ramce. Łączności z wpisów luźnych też są ważne (znak + czas), brakuje im tylko numeru.
Działa także od zera (np. program włączony, gdy balon ma już kilkadziesiąt wpisów): gdy dojdą wszystkie, numery są pewne.
"""
import json, os, time

ZAPAS_S = 1500         # wpis o czasie starszym o tyle od ramki STAN jest już na pewno policzony w jej liczniku:
                       # czas wpisu jest zaokrąglony w dół do 10 min, a tracker zamyka wpis najpóźniej 10 min po pierwszej łączności


class RobotLog:
    def __init__(self, sciezka=None):
        self.sciezka = sciezka
        self.wpisy = {}        # nr -> {"z1", "z2", "czas", "odebrano", "zrodlo"}
        self.luzne = []        # ramki LOG bez ustalonego numeru: {"z1", "z2", "czas", "nr8", "odebrano", "zrodlo"}
        self.stany = []        # ostatnie ramki STAN: {"t": odbiór, ...pola}
        self.wyslane = []      # klucze łączności przekazanych do Log4OM ("ZNAK|czas")
        self.pominiete = []    # klucze łączności, których operator nie chce w Log4OM
        self.slyszany = 0      # kiedy ostatnio odebrano jakąkolwiek ramkę balonu
        if sciezka and os.path.exists(sciezka):
            try:
                with open(sciezka, encoding="utf-8") as f:
                    d = json.load(f)
                self.wpisy = {int(k): v for k, v in d.get("wpisy", {}).items()}
                self.luzne = d.get("luzne", [])
                self.stany = d.get("stany", [])
                self.wyslane = d.get("wyslane", [])
                self.pominiete = d.get("pominiete", [])
                self.slyszany = d.get("slyszany", 0)
            except Exception:
                pass

    def zapisz(self):
        if not self.sciezka:
            return
        tmp = self.sciezka + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"wpisy": self.wpisy, "luzne": self.luzne, "stany": self.stany[-50:], "wyslane": self.wyslane,
                       "pominiete": self.pominiete, "slyszany": self.slyszany}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.sciezka)

    # ------------------------------------------------------------------ przyjmowanie ramek
    def dodaj(self, ramka, t_odbioru=None, zrodlo=""):
        """Ramka z robot_proto.rozbierz(). Zwraca True, gdy wniosła coś nowego."""
        t = time.time() if t_odbioru is None else t_odbioru
        if not ramka or ramka.get("rodzaj") not in ("LOG", "STAN"):
            return False
        self.slyszany = max(self.slyszany, t)
        nowe = False
        if ramka["rodzaj"] == "STAN":
            s = {k: v for k, v in ramka.items() if k != "rodzaj"}
            s["t"] = t
            if not self.stany or any(self.stany[-1].get(k) != s.get(k) for k in s if k != "t"):
                nowe = True
            self.stany.append(s)
            self.stany = self.stany[-50:]
        else:
            w = {"z1": ramka["znak1"], "z2": ramka["znak2"], "czas": ramka["czas"], "nr8": ramka["nr8"],
                 "odebrano": t, "zrodlo": zrodlo}
            if not self._znany(w):
                self.luzne.append(w)
                nowe = True
        self._numeruj()
        return nowe

    def _znany(self, w):
        k = (w["z1"], w["z2"], w["czas"])
        return any((e["z1"], e["z2"], e["czas"]) == k for e in list(self.wpisy.values()) + self.luzne)

    def _granice(self, czas):
        """Najmniejszy i największy numer wpisu o danym czasie wynikający z ramek STAN (None = brak ograniczenia z góry)."""
        lo, hi = 1, None
        for s in self.stany:
            if czas < s["t"] - ZAPAS_S:                   # wpis na pewno zamknięty przed ramką STAN: numer nie większy niż jej licznik
                hi = s["wpisy"] if hi is None else min(hi, s["wpisy"])
            elif czas > s["t"] + 60:                      # wpis powstał po ramce STAN: numer większy
                lo = max(lo, s["wpisy"] + 1)
        return lo, hi

    def _numeruj(self):
        """Ustala numery wpisów luźnych.

        Wszystkie wpisy (ponumerowane i luźne) układamy po czasie. Numery rosną z czasem, a każdy luźny wpis zna swój numer
        modulo 8. Liczymy dla każdego najmniejszy możliwy numer (przejście od najstarszych) i największy możliwy (od najnowszych);
        gdzie oba są równe, numer jest pewny. Wpisy o tym samym czasie (ta sama jednostka 10 min) nie ograniczają się nawzajem.
        """
        INF = 1 << 30
        zmiana = True
        while zmiana and self.luzne:
            zmiana = False
            poz = [{"czas": e["czas"], "nr": nr} for nr, e in self.wpisy.items()] + \
                  [{"czas": w["czas"], "w": w} for w in self.luzne]
            poz.sort(key=lambda p: p["czas"])
            grupy = []
            for p in poz:
                if grupy and grupy[-1][0]["czas"] == p["czas"]:
                    grupy[-1].append(p)
                else:
                    grupy.append([p])
            dol = 1                                       # najmniejszy numer dozwolony dla bieżącej grupy
            for gr in grupy:
                for p in gr:
                    if "nr" in p:
                        p["min"] = p["nr"]
                    else:
                        lo, hi = self._granice(p["czas"])
                        p["hi"] = INF if hi is None else hi
                        n = max(dol, lo)
                        p["min"] = n + (p["w"]["nr8"] - n) % 8
                dol = max(p["min"] for p in gr) + 1
            gora = INF
            for gr in reversed(grupy):
                for p in gr:
                    if "nr" in p:
                        p["max"] = p["nr"]
                    else:
                        n = min(gora, p["hi"])
                        p["max"] = INF if n >= INF else n - (n - p["w"]["nr8"]) % 8
                gora = min(p["max"] for p in gr) - 1
            for gr in grupy:
                for p in gr:
                    if "w" in p and p["min"] == p["max"] and p["min"] not in self.wpisy:
                        self.wpisy[p["min"]] = {k: v for k, v in p["w"].items() if k != "nr8"}
                        self.luzne.remove(p["w"])
                        zmiana = True

    # ------------------------------------------------------------------ odczyt
    @property
    def stan(self):
        return self.stany[-1] if self.stany else None

    def liczba_wpisow(self):
        """Ile wpisów ma tracker według naszej wiedzy (z ramki STAN albo z najwyższego numeru)."""
        return max([s["wpisy"] for s in self.stany[-1:]] + list(self.wpisy) + [0])

    def brakujace(self):
        return [n for n in range(1, self.liczba_wpisow() + 1) if n not in self.wpisy]

    def potwierdzenie(self):
        """Argumenty komendy POTWIERDZENIE: do = ostatni numer, do którego mamy wszystko; mapa = które z do+2…do+20 mamy."""
        do = 0
        while do + 1 in self.wpisy:
            do += 1
        mapa = 0
        for i in range(19):
            mapa = (mapa << 1) | (1 if do + 2 + i in self.wpisy else 0)
        return {"do": do, "mapa": mapa}

    def lacznosci(self):
        """Wszystkie odebrane łączności: lista {"znak", "czas", "nr" (numer wpisu albo None), "klucz"} wg czasu."""
        out, widziane = [], set()
        for nr, e in list(sorted(self.wpisy.items())) + [(None, e) for e in self.luzne]:
            for z in (e["z1"], e["z2"]):
                k = f"{z}|{e['czas']}"
                if z and k not in widziane:
                    widziane.add(k)
                    out.append({"znak": z, "czas": e["czas"], "nr": nr, "klucz": k})
        out.sort(key=lambda q: (q["czas"], q["nr"] or 0))
        return out

    def nowe_do_logu(self):
        """Łączności jeszcze nieprzekazane do Log4OM i niepominięte."""
        bylo = set(self.wyslane) | set(self.pominiete)
        return [q for q in self.lacznosci() if q["klucz"] not in bylo]

    def oznacz(self, klucze, pomin=False):
        (self.pominiete if pomin else self.wyslane).extend(k for k in klucze)
        self.zapisz()

    def skrot(self):
        """Jedna linia do okna programu."""
        n, brak = self.liczba_wpisow(), self.brakujace()
        s = self.stan
        qso = len(self.lacznosci())
        txt = f"QSO odebrane {qso}" + (f" z {s['qso']}" if s else "") + f" · wpisy {n - len(brak)}/{n}"
        if brak:
            txt += " · brakuje nr " + ", ".join(map(str, brak[:12])) + ("…" if len(brak) > 12 else "")
        if self.luzne:
            txt += f" · bez numeru {len(self.luzne)}"
        return txt

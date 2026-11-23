"""
Zakładka „FT8 balon” programu GOLbase – łączność z trackerem-robotem FT8 (płytka R20).

Co robi:
  * dekoduje FT8 z dźwięku radia (ft8silnik.py), pokazuje wszystkie dekody, wyróżnia ramki balonu,
  * z ramek danych balonu składa jego log (robot_log.py) i pokazuje, czego brakuje,
  * nadaje do balonu komendy z podpisem (robot_proto.py) i po każdej zwykłą ramkę ze znakiem operatora,
  * przekazuje nowe łączności balonu do Log4OM po zatwierdzeniu przez operatora.

Radio: OmniRig (Rig 1 = IC-7300, Rig 2 = FTX-1) albo CI-V wprost (połączenie z góry okna, tylko IC-7300).
Nadawanie tylko przy operatorze: „Auto” samo się wyłącza po kilkunastu minutach, Esc / STOP przerywa natychmiast.
"""
import os, queue, threading, time, tkinter as tk
from tkinter import ttk, messagebox

import numpy as np

import logbook
import motyw as M
import robot_proto as P
from robot_log import RobotLog

try:
    import ft8silnik as F
except Exception as e:  # pragma: no cover
    F = None
    F_ERR = str(e)

DOMYSLNE = {
    "ft8_radio": "omnirig1",          # omnirig1 / omnirig2 / civ
    "ft8_audio_out": "",              # wyjście dźwięku do radia (nadawanie)
    "ft8_dial_khz": 14074.0,          # częstotliwość radia (USB-D)
    "ft8_tx_poziom": 0.5,             # poziom dźwięku nadawania 0…1
    "robot_call": "QQ0Q",             # znak FT8 balonu
    "robot_log_hz": 2600,             # gdzie balon nadaje ramki danych [Hz dźwięku]
    "robot_log_tol_hz": 40,
    "robot_tx_hz": 2200,              # gdzie nadajemy do balonu [Hz dźwięku]
    "robot_id_text": "{CALL} {MY} AA00",   # zwykła ramka ze znakiem operatora po każdej komendzie
    "robot_auto_min": 15,             # po ilu minutach „Auto” samo się wyłącza
    "robot_licznik": 0,               # numer kolejny komendy (modulo 64)
    "robot_qso_mhz": 14.074,          # częstotliwość łączności balonu – do wpisów w logu
    "robot_log4om_udp": "",           # pusty = ten sam adres co „log4om_udp”
    "robot_log4om_send": False,        # od 1.16: łączności balonu zawsze idą do pliku ADIF; do Log4OM tylko, gdy włączone
}
RADIA = [("omnirig1", "OmniRig – Rig 1 (IC-7300)"), ("omnirig2", "OmniRig – Rig 2 (FTX-1)"),
         ("civ", "CI-V wprost (IC-7300, „Połącz” u góry)")]
PASMA_KHZ = ["14074", "18100", "21074", "24915", "28074", "10136", "7074"]


WF_F0, WF_F1 = 200, 3000        # zakres wodospadu [Hz]
WF_H, WF_SKALA = 110, 13        # wysokość obrazu i paska skali [px]
WF_FFT, WF_KROK = 8192, 9600    # FFT z 0,17 s dźwięku 48 kHz, nowa linia co 0,2 s (110 linii = 22 s)
WF_OKNO = np.hanning(WF_FFT).astype(np.float32)
_KOL_X = np.array([0.0, 0.25, 0.5, 0.75, 1.0])
_KOL = np.array([[0, 0, 16], [10, 30, 140], [20, 170, 190], [240, 220, 40], [255, 60, 30]], float)


def _kolory(v):
    """Wartości 0…1 -> kolory wodospadu (granat – niebieski – turkus – żółty – czerwony)."""
    v = np.clip(v, 0, 1)
    return np.stack([np.interp(v, _KOL_X, _KOL[:, k]) for k in range(3)], axis=1).astype(np.uint8)


OPISY_KROTKIE = {1: "Potwierdzenie logu", 2: "Dosyłka braków", 11: "Pytanie o stan"}
_OSTROZNIE = "Ta komenda zmienia zachowanie balonu w locie. Jeśli po niej balon przestanie nas słyszeć, nie da się jej cofnąć."
# Okno „Komendy”: tytuł i opis po ludzku, pola w zwykłych jednostkach. Pole: (nazwa w ramce, etykieta, rodzaj, parametry…)
#   wybor: lista (numer pozycji = wartość)[, domyślna];  liczba: min, max, jednostka, domyślna;
#   skala: krok, min, max, jednostka, domyślna;  szer / dlug: stopnie;  znak;  lokator
FORMULARZE = [
    {"nazwa": "PYTANIE", "tytul": "Zapytaj o stan", "pola": [],
     "opis": "Balon od razu odsyła ramkę STAN: napięcie, temperaturę, tryb, liczbę łączności i to, z jaką siłą słyszy dom. "
             "Najprostszy sposób, żeby sprawdzić, czy balon nas słyszy."},
    {"nazwa": "POTWIERDZENIE", "tytul": "Potwierdź odebrany log", "pola": [], "auto": True,
     "opis": "Mówi balonowi, które wpisy logu już mamy, żeby przestał je powtarzać. Program sam wylicza, co potwierdzić."},
    {"nazwa": "DOSYLKA", "tytul": "Poproś o brakujące wpisy",
     "opis": "Balon nada jeszcze raz wpisy logu o podanych numerach (numery braków są w ramce „Balon”).",
     "pola": [("od", "Od wpisu nr", "liczba", 1, 16383, "", 1), ("do", "Do wpisu nr", "liczba", 1, 16383, "", 1)]},
    {"nazwa": "NADAWANIE", "tytul": "Nadawanie: wyłącz / włącz", "pytaj": _OSTROZNIE,
     "opis": "Wyłącza albo włącza nadajnik balonu. Wyłączony balon dalej słucha i czeka na komendę „włącz”.",
     "uwaga": "Zostaw samoczynne włączenie po kilku dniach – balon, który odleci poza zasięg domu z wyłączonym nadajnikiem "
              "i bez tego limitu, zamilknie na zawsze. 0 dni = bez limitu.",
     "pola": [("wlacz", "Co zrobić", "wybor", ["wyłącz nadawanie", "włącz nadawanie"]),
              ("zakres", "Czego dotyczy", "wybor", ["wszystko (FT8 i WSPR)", "tylko FT8", "tylko WSPR"]),
              ("dni", "Włącz samo po", "liczba", 0, 63, "dniach", 3)]},
    {"nazwa": "TRYB", "tytul": "Cisza na określony czas", "stale": {"tryb": 4}, "pytaj": _OSTROZNIE,
     "opis": "Balon milknie całkowicie na podaną liczbę godzin, potem sam wraca do pracy.",
     "pola": [("godziny", "Na ile", "liczba", 1, 255, "godzin", 12)]},
    {"nazwa": "TRYB", "tytul": "Tryb pracy (energia)", "stale": {"godziny": 0},
     "opis": "Ile balon pracuje. Pełny: nasłuch i łączności FT8 cały dzień. Średni i oszczędny: rzadziej. "
             "Sam WSPR: tylko pozycja, bez łączności.",
     "pola": [("tryb", "Tryb", "wybor", ["pełny", "średni", "oszczędny", "sam WSPR"])]},
    {"nazwa": "PASMO", "tytul": "Pasmo i kanał WSPR", "pytaj": _OSTROZNIE,
     "opis": "Pasmo, na którym balon pracuje, i jego kanał WSPR (numer 0–599 jak w Traquito – wyznacza częstotliwość i minutę).",
     "uwaga": "Antena i filtr trackera są zrobione na jedno pasmo. Zmiana pasma ma sens tylko wtedy, gdy płytka i dipol "
              "ją zniosą – inaczej balon będzie nadawał prawie bez mocy.",
     "pola": [("pasmo", "Pasmo", "wybor", P.PASMA, 5), ("kanal", "Kanał WSPR", "liczba", 0, 599, "", 0)]},
    {"nazwa": "ZNAK", "tytul": "Znak balonu", "pytaj": _OSTROZNIE + " Balon zacznie nadawać pod nowym znakiem.",
     "opis": "Zmienia znak, którym balon się przedstawia – osobno dla FT8 i dla WSPR. Tylko znaki, do których masz prawo.",
     "uwaga": "Po zmianie znaku FT8 wpisz ten sam znak w ⚙ Ustawienia → „Znak balonu”, inaczej program przestanie go wyróżniać.",
     "pola": [("ktory", "Który znak", "wybor", ["znak FT8", "znak WSPR"]), ("znak", "Nowy znak", "znak")]},
    {"nazwa": "LOKATOR", "tytul": "Lokator: z GPS albo stały",
     "opis": "Stały: balon podaje zawsze wpisany lokator zamiast prawdziwej pozycji (np. przy próbach na ziemi). "
             "Z GPS: wraca do prawdziwej pozycji.",
     "uwaga": "Ze stałym lokatorem nie widać na mapie, gdzie balon naprawdę jest.",
     "pola": [("staly", "Lokator", "wybor", ["z GPS (prawdziwa pozycja)", "stały – wpisany niżej"]),
              ("lokator", "Stały lokator", "lokator")]},
    {"nazwa": "EMISJA", "tytul": "FT8 albo FT4",
     "opis": "Rodzaj emisji do łączności. FT4 jest szybsze (okna 7,5 s), ale mniej czułe.",
     "uwaga": "Ten program na razie odbiera i nadaje tylko FT8 – po przełączeniu balonu na FT4 nie zobaczysz go tutaj.",
     "pola": [("ft4", "Emisja", "wybor", ["FT8", "FT4"])]},
    {"nazwa": "MOC", "tytul": "Moc nadajnika",
     "opis": "Prąd wyjścia układu nadajnika. Mniejszy = mniej mocy, ale balon pracuje przy słabszym słońcu.",
     "pola": [("moc", "Prąd wyjścia", "wybor", ["2 mA (najmniej)", "4 mA", "6 mA", "8 mA (najwięcej)"], 3)]},
    {"nazwa": "MIEJSCE", "tytul": "Miejsce w paśmie",
     "opis": "Na jakiej częstotliwości dźwięku (0–4095 Hz ponad częstotliwość pasma) balon woła CQ i gdzie nadaje ramki danych.",
     "uwaga": "Po zmianie częstotliwości danych wpisz tę samą w ⚙ Ustawienia → „Ramki danych balonu”.",
     "pola": [("cq_hz", "CQ i łączności", "liczba", 200, 3000, "Hz", 1500), ("log_hz", "Ramki danych", "liczba", 200, 3000, "Hz", 2600)]},
    {"nazwa": "PROGI", "tytul": "Progi zasilania",
     "opis": "Od jakiego napięcia paneli i od jakiej wysokości Słońca balon słucha i robi łączności, a od jakiego nadaje sam WSPR.",
     "pola": [("u_pelny", "Łączności FT8 od", "skala", 0.05, 0, 6.35, "V", 4.0), ("u_wspr", "Sam WSPR od", "skala", 0.05, 0, 6.35, "V", 3.3),
              ("slonce_pelny", "Łączności FT8 od Słońca", "liczba", 0, 63, "°", 17), ("slonce_wspr", "Sam WSPR od Słońca", "liczba", 0, 63, "°", 8)]},
    {"nazwa": "STREFA", "tytul": "Strefa ciszy (obszar)",
     "opis": "Prostokąt na mapie, nad którym balon nie nadaje. Mieszczą się cztery strefy; podaj dwa przeciwległe rogi.",
     "pola": [("dodaj", "Co zrobić", "wybor", ["usuń strefę", "ustaw strefę"], 1), ("nr", "Która strefa", "wybor", ["1", "2", "3", "4"]),
              ("szer1", "Róg 1 – szerokość", "szer"), ("dlug1", "Róg 1 – długość", "dlug"),
              ("szer2", "Róg 2 – szerokość", "szer"), ("dlug2", "Róg 2 – długość", "dlug")]},
    {"nazwa": "ZASADY", "tytul": "Powtórne łączności",
     "opis": "Jak często balon robi łączność z tą samą stacją.",
     "pola": [("regula", "Ta sama stacja", "wybor", ["bez ograniczeń", "najwyżej raz na dobę", "najwyżej raz na cały lot"], 1)]},
    {"nazwa": "CZARNA_LISTA", "tytul": "Czarna lista znaków",
     "opis": "Stacja, z którą balon nie robi łączności (np. ktoś, kto go zagłusza).",
     "pola": [("dodaj", "Co zrobić", "wybor", ["usuń z listy", "dodaj do listy"], 1), ("znak", "Znak stacji", "znak")]},
]


def hhmmss(t):
    return time.strftime("%H:%M:%S", time.gmtime(t))


class RadioCIV:
    """IC-7300 przez połączenie CI-V otwarte u góry okna (to samo, którego używa zakładka CW)."""

    def __init__(self, app):
        self.app = app

    @property
    def r(self):
        return self.app.radio

    @property
    def online(self):
        return bool(self.r and self.r.freq)

    @property
    def freq(self):
        return self.r.freq if self.r else 0

    @property
    def mode(self):
        return self.r.mode if self.r else None

    @property
    def stan(self):
        return "CI-V: połączony" if self.online else "CI-V: brak połączenia – wybierz port u góry i „Połącz”"

    def set_freq(self, hz):
        self.r.set_freq(hz)

    def set_usb_data(self):
        self.r.set_usb_data()

    def ptt(self, on):
        if self.r:
            self.r.ptt(on)
        return bool(self.r)

    def close(self):
        try:
            self.ptt(False)
        except Exception:
            pass


class ZakladkaFT8:
    def __init__(self, ramka, app, save_cfg, data_dir, sd):
        self.f, self.app, self.save_cfg, self.sd = ramka, app, save_cfg, sd
        self.cfg = app.cfg
        for k, v in DOMYSLNE.items():
            self.cfg.setdefault(k, v)
        self.data_dir = data_dir
        self.klucz_plik = os.path.join(data_dir, "robot_klucz.txt")
        self.log = RobotLog(os.path.join(data_dir, "robot_log.json"))
        self.silnik, self.okna = None, None
        if F is not None:
            try:
                self.silnik = F.Silnik()
                self.silnik.dodaj_znak(self.cfg["robot_call"])
                self.silnik.dodaj_znak(self.cfg["my_call"])
                self.okna = F.Okna()
            except OSError as e:
                self.blad_silnika = str(e)
        else:
            self.blad_silnika = F_ERR
        self.radio = None
        self.q_gui = queue.Queue()             # zdarzenia z wątków do okna
        self.kolejka = []                      # do nadania: {"rodzaj": "kom"/"tekst", ...}
        self.kol_blokada = threading.Lock()
        self.stop_evt = threading.Event()
        self.nadaje = False
        self.okna_tx = set()                   # okna, w których nadawaliśmy (nie dekodujemy własnego sygnału)
        self.balon_okno = None                 # początek okna, w którym ostatnio słyszano balon
        self.auto_do = 0.0
        self.auto_ostatnia = 0.0
        self.potw_wyslane = None
        self.dt_sr = None
        self.wf = np.zeros((WF_H, 4, 3), np.uint8)   # wodospad (wiersze od najnowszego)
        self.wf_buf = np.zeros(0, np.float32)
        self.wf_ile, self.wf_okno, self.wf_lo, self.wf_hi = 0, 0, -60.0, -20.0
        self.wf_start, self.wf_skok = True, 0
        self.okno_info = None                  # (początek, liczba dekodów) ostatniego zdekodowanego okna
        self.wyj_idx = None                    # numer urządzenia wyjściowego (dla wątku nadawania)
        self.alive = True
        self._buduj()
        threading.Thread(target=self._watek_dekodera, daemon=True).start()
        threading.Thread(target=self._watek_nadawania, daemon=True).start()
        self.f.after(200, self._tyk)

    # ------------------------------------------------------------------ okno
    def _buduj(self):
        f, c = self.f, self.cfg
        # ustawienia zmieniane rzadko siedzą w oknie „Ustawienia…” – tu tylko ich zmienne
        self.var_call = tk.StringVar(value=c["robot_call"])
        self.var_loghz = tk.StringVar(value=str(c["robot_log_hz"]))
        self.var_txhz = tk.StringVar(value=str(c["robot_tx_hz"]))
        self.var_poziom = tk.DoubleVar(value=c["ft8_tx_poziom"])
        self.var_out = tk.StringVar()
        self.wyjscia = []

        g = ttk.Frame(f, padding=(10, 10, 10, 4)); g.pack(fill="x")
        self.cb_radio = ttk.Combobox(g, width=34, state="readonly", values=[n for _, n in RADIA])
        self.cb_radio.set(dict(RADIA).get(c["ft8_radio"], RADIA[0][1])); self.cb_radio.pack(side="left")
        self.cb_radio.bind("<<ComboboxSelected>>", lambda e: (self._zapisz_ustawienia(), self.app.pokaz_civ()))
        self.btn_radio = ttk.Button(g, text="Połącz radio", width=13, command=self._przycisk_radia)
        self.btn_radio.pack(side="left", padx=(6, 14))
        self.var_khz = tk.StringVar(value=f"{c['ft8_dial_khz']:g}")
        ttk.Combobox(g, textvariable=self.var_khz, width=7, values=PASMA_KHZ).pack(side="left")
        ttk.Label(g, text="kHz", style="Szary.TLabel").pack(side="left", padx=(3, 6))
        ttk.Button(g, text="Ustaw radio (USB-D)", command=self.ustaw_radio).pack(side="left")
        ttk.Button(g, text="⚙ Ustawienia", command=self.okno_ustawien).pack(side="right")

        g = ttk.Frame(f, padding=(10, 2, 10, 6)); g.pack(fill="x")
        self.lbl_radio = ttk.Label(g, text="radio niepołączone", style="Szary.TLabel"); self.lbl_radio.pack(side="left")
        self.lbl_dt = ttk.Label(g, text="", style="Szary.TLabel"); self.lbl_dt.pack(side="left", padx=16)
        self.lbl_zegar = ttk.Label(g, text="", style="Zegar.TLabel"); self.lbl_zegar.pack(side="right")
        self.pasek = ttk.Progressbar(g, length=180, maximum=15.0); self.pasek.pack(side="right", padx=10)

        d = ttk.Frame(f, padding=10); d.pack(fill="x", side="bottom")     # przed środkiem – żeby zawsze był widoczny
        ttk.Label(d, text="Nadaj tekst FT8 (jedno okno):", style="Szary.TLabel").pack(side="left")
        self.ent_txt = ttk.Entry(d, font=(M.MONO, 11), width=26); self.ent_txt.pack(side="left", padx=6)
        self.ent_txt.insert(0, self._id_tekst())
        self.ent_txt.bind("<Return>", lambda e: self.dodaj_tekst(self.ent_txt.get()))
        ttk.Button(d, text="Nadaj raz", command=lambda: self.dodaj_tekst(self.ent_txt.get())).pack(side="left")
        ttk.Button(d, text="Wyczyść listę", command=lambda: self.lista.delete(*self.lista.get_children())).pack(side="right")
        srodek = ttk.Frame(f, padding=(10, 0, 10, 0)); srodek.pack(fill="both", expand=True)
        kol_kom = ttk.Frame(srodek); kol_kom.pack(side="right", fill="y", padx=(10, 0))
        prawa = ttk.Frame(srodek); prawa.pack(side="right", fill="y", padx=(10, 0))
        lewa_kol = ttk.Frame(srodek); lewa_kol.pack(side="left", fill="both", expand=True)
        # wodospad 200–3000 Hz: jedna linia = 0,2 s, najnowsze u góry; kreski: pomarańczowa = ramki danych balonu, czerwona = nasze nadawanie
        self.wf_c = tk.Canvas(lewa_kol, height=WF_SKALA + WF_H, bg="#000010", highlightthickness=1,
                              highlightbackground=M.LINIA)
        self.wf_c.pack(fill="x", pady=(0, 6))
        self.wf_img = tk.PhotoImage(width=4, height=WF_H)
        self.wf_c.create_image(0, WF_SKALA, image=self.wf_img, anchor="nw")
        self.wf_c.bind("<Configure>", self._wf_rozmiar)
        lewa = tk.Frame(lewa_kol, bg=M.LINIA); lewa.pack(fill="both", expand=True)
        kol = ("utc", "db", "dt", "hz", "tresc")
        self.lista = ttk.Treeview(lewa, columns=kol, show="headings", height=14, selectmode="browse")
        for k, n, w in zip(kol, ("UTC", "dB", "DT", "Hz", "Treść"), (84, 48, 56, 60, 340)):
            self.lista.heading(k, text=n, anchor="w" if k == "tresc" else "e")
            self.lista.column(k, width=w, minwidth=w if k != "tresc" else 200, anchor="w" if k == "tresc" else "e",
                              stretch=(k == "tresc"))
        self.lista.tag_configure("balon", background=M.BALON_TLO, foreground="#ffc46b", font=(M.MONO, 11, "bold"))
        self.lista.tag_configure("tx", foreground=M.CZERWONY, font=(M.MONO, 11, "bold"))
        self.lista.tag_configure("okno", foreground="#4d5870", font=(M.MONO, 9))
        self.lista.tag_configure("cq", foreground=M.ZIELONY)
        self.lista.tag_configure("moje", foreground=M.NIEBIESKI, font=(M.MONO, 11, "bold"))
        self.lista.tag_configure("zwykly", foreground=M.TEKST)
        sb = ttk.Scrollbar(lewa, command=self.lista.yview); self.lista.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", padx=(0, 1), pady=1); self.lista.pack(side="left", fill="both", expand=True, padx=(1, 0), pady=1)

        bal = M.karta(prawa, "Balon"); bal.zew.pack(fill="x")
        self.lbl_slychac = ttk.Label(bal, text="nie słyszany", style="Karta.TLabel", font=(M.CZC, 13, "bold"))
        self.lbl_slychac.pack(anchor="w")
        self.lbl_stan = ttk.Label(bal, text="stan: —", wraplength=300, justify="left", style="KartaSzary.TLabel")
        self.lbl_stan.pack(anchor="w", pady=(2, 0))
        self.lbl_log = ttk.Label(bal, text="log: —", wraplength=300, justify="left", style="Karta.TLabel")
        self.lbl_log.pack(anchor="w", pady=(4, 0))
        self.btn_l4o = ttk.Button(bal, text="Nowe łączności → log", style="Akcent.TButton", command=self.okno_log4om)
        self.btn_l4o.pack(fill="x", pady=(8, 0))

        self._buduj_komendy(kol_kom)
        kom = M.karta(prawa, "Do balonu – szybkie"); kom.zew.pack(fill="x", pady=(10, 0))
        r1 = ttk.Frame(kom, style="Karta.TFrame"); r1.pack(fill="x")
        for i, (t, fn) in enumerate((("Potwierdź log", self.kom_potwierdz), ("Dosyłka braków", self.kom_dosylka),
                                     ("Pytanie o stan", lambda: self.dodaj_komende(11, {})))):
            ttk.Button(r1, text=t, command=fn).pack(fill="x", pady=2)
        self.var_auto = tk.BooleanVar(value=False)
        ttk.Checkbutton(kom, text="Auto – sam potwierdzaj log, gdy słychać balon", variable=self.var_auto,
                        style="Karta.TCheckbutton", command=self._auto).pack(anchor="w", pady=(6, 0))
        self.lbl_auto = ttk.Label(kom, text="", style="KartaSzary.TLabel", wraplength=300); self.lbl_auto.pack(anchor="w")
        ttk.Label(kom, text="Kolejka nadawania", style="KartaSzary.TLabel").pack(anchor="w", pady=(6, 2))
        self.lb_kol = tk.Listbox(kom, height=5, width=38, font=(M.MONO, 9), bg=M.POLE, fg=M.TEKST, relief="flat",
                                 highlightthickness=1, highlightbackground=M.LINIA, activestyle="none")
        self.lb_kol.pack(fill="x")
        # przycisk-lampka jak w JTDX: ciemny w spoczynku, żółty gdy czeka na okno, jaskrawoczerwony gdy radio nadaje
        self.btn_stop = tk.Button(kom, text="STOP  (Esc)", bg="#1b2540", fg=M.SZARY, activebackground="#e53935",
                                  activeforeground="white", relief="flat", bd=0, font=(M.CZC, 13, "bold"), pady=6,
                                  cursor="hand2", command=self.stop)
        self.btn_stop.pack(fill="x", pady=(8, 0))

        if not self.silnik:
            ttk.Label(f, text="FT8 wyłączone: " + self.blad_silnika, foreground=M.CZERWONY).pack(anchor="w", padx=10)
        self.wypelnij_wyjscia()

    def wypelnij_wyjscia(self):
        if self.sd is None:
            return
        try:
            devs = [f"{i}: {d['name']}" for i, d in enumerate(self.sd.query_devices()) if d["max_output_channels"] > 0]
        except Exception:
            devs = []
        self.wyjscia = devs
        c = self.cfg["ft8_audio_out"]
        self.var_out.set(next((d for d in devs if c and c in d), None)
                         or next((d for d in devs if "USB Audio CODEC" in d), None) or (devs[0] if devs else ""))
        self.wyj_idx = int(self.var_out.get().split(":")[0]) if self.var_out.get() else None

    def okno_ustawien(self):
        """Rzadko zmieniane ustawienia zakładki: wyjście dźwięku, poziom, znak balonu, częstotliwości dźwięku."""
        w = tk.Toplevel(self.f); w.title("GOLbase – ustawienia FT8 balon"); w.transient(self.f.winfo_toplevel())
        w.configure(bg=M.TLO); w.resizable(False, False)
        fr = ttk.Frame(w, padding=14); fr.pack(fill="both", expand=True)
        wiersze = (("Wyjście audio do radia (nadawanie)", lambda p: ttk.Combobox(p, textvariable=self.var_out, values=self.wyjscia,
                                                                                  state="readonly", width=40)),
                   ("Poziom dźwięku nadawania", lambda p: ttk.Scale(p, from_=0.05, to=1.0, variable=self.var_poziom, length=200)),
                   ("Znak balonu", lambda p: ttk.Entry(p, textvariable=self.var_call, width=10)),
                   ("Ramki danych balonu [Hz dźwięku]", lambda p: ttk.Entry(p, textvariable=self.var_loghz, width=10)),
                   ("Nadaję do balonu na [Hz dźwięku]", lambda p: ttk.Entry(p, textvariable=self.var_txhz, width=10)))
        for i, (opis, rob) in enumerate(wiersze):
            ttk.Label(fr, text=opis, style="Szary.TLabel").grid(row=i, column=0, sticky="w", pady=5, padx=(0, 14))
            rob(fr).grid(row=i, column=1, sticky="w")
        ttk.Label(fr, text="Poziom ustaw tak, żeby wskaźnik ALC w radiu ledwo drgał.\nRamki danych balonu są przyjmowane "
                           f"tylko w pobliżu podanej częstotliwości (± {self.cfg['robot_log_tol_hz']} Hz).",
                  style="Szary.TLabel", justify="left").grid(row=len(wiersze), column=0, columnspan=2, sticky="w", pady=(8, 0))

        def zamknij():
            self._zapisz_ustawienia()
            w.destroy()

        ttk.Button(fr, text="Zapisz", style="Akcent.TButton", command=zamknij).grid(row=len(wiersze) + 1, column=1, sticky="e",
                                                                                    pady=(12, 0))
        w.protocol("WM_DELETE_WINDOW", zamknij)
        M.ciemna_belka(w)

    def _zapisz_ustawienia(self):
        c = self.cfg
        try:
            c["robot_log_hz"] = int(float(self.var_loghz.get()))
            c["robot_tx_hz"] = int(float(self.var_txhz.get()))
            c["ft8_dial_khz"] = float(self.var_khz.get().replace(",", "."))
        except ValueError:
            pass
        znak = self.var_call.get().strip().upper()
        if znak:
            c["robot_call"] = znak
            if self.silnik:
                self.silnik.dodaj_znak(znak)
        c["ft8_tx_poziom"] = round(float(self.var_poziom.get()), 2)
        if self.var_out.get():
            c["ft8_audio_out"] = self.var_out.get().split(":", 1)[1].strip()
            self.wyj_idx = int(self.var_out.get().split(":")[0])
        c["ft8_radio"] = next((k for k, n in RADIA if n == self.cb_radio.get()), "omnirig1")
        self.save_cfg(c)

    def _id_tekst(self):
        return self.cfg["robot_id_text"].replace("{CALL}", self.cfg["robot_call"]).replace("{MY}", self.cfg["my_call"])

    def _status(self, txt):
        self.app.status.config(text=txt)

    # ------------------------------------------------------------------ radio
    def _przycisk_radia(self):
        """„Połącz radio” albo – gdy połączone – „Rozłącz radio” (oddaje OmniRig / port COM innym programom)."""
        if self.radio:
            self.rozlacz_radio()
        else:
            self.polacz_radio()

    def rozlacz_radio(self):
        self.stop()
        if self.radio:
            self.radio.close()
        self.radio = None
        self.btn_radio.config(text="Połącz radio")
        self._status("FT8: radio rozłączone")

    def polacz_radio(self):
        self._zapisz_ustawienia()
        if self.radio:
            self.radio.close()
            self.radio = None
        rodzaj = self.cfg["ft8_radio"]
        if rodzaj == "civ":
            self.radio = RadioCIV(self.app)
        else:
            import omnirig
            if self.app.radio:                 # OmniRig potrzebuje tego samego portu COM – zwolnij połączenie CI-V
                self.app.disconnect_radio()
                self.f.update_idletasks()
                time.sleep(0.5)
            r = omnirig.OmniRig(1 if rodzaj == "omnirig1" else 2)
            if r.blad:
                messagebox.showerror("GOLbase", r.blad + "\n\nZainstaluj i uruchom OmniRig (dxatlas.com/omnirig), ustaw w nim "
                                     "Rig 1 = IC-7300, Rig 2 = FTX-1. Albo wybierz „CI-V wprost”.")
                return
            self.radio = r
        self.app.pokaz_civ()
        self.btn_radio.config(text="Rozłącz radio")
        self._status("FT8: łączę z radiem…")
        self.f.after(2000, lambda: self.radio and self._status("FT8: " + self.radio.stan))

    def ustaw_radio(self):
        self._zapisz_ustawienia()
        if not self._radio_ok():
            return
        try:
            self.radio.set_usb_data()
            time.sleep(0.15)
            self.radio.set_freq(int(round(self.cfg["ft8_dial_khz"] * 1000)))
        except Exception as e:
            messagebox.showerror("GOLbase", f"Radio: {e}")

    def _radio_ok(self, cicho=False):
        if self.radio is None:
            if not cicho:
                messagebox.showwarning("GOLbase", "Najpierw „Połącz radio” w zakładce FT8 balon.")
            return False
        if not self.radio.online:
            if not cicho:
                messagebox.showwarning("GOLbase", "Radio nie odpowiada: " + self.radio.stan)
            return False
        return True

    # ------------------------------------------------------------------ odbiór
    def podaj(self, x):
        """Blok dźwięku 48 kHz z wątku audio programu."""
        if self.okna is not None:
            self.okna.podaj(x)
        self.wf_buf = np.concatenate([self.wf_buf, x])[-WF_FFT:]
        self.wf_ile += len(x)
        if self.wf_ile >= WF_KROK and len(self.wf_buf) == WF_FFT:
            self.wf_ile = 0
            widmo = np.abs(np.fft.rfft(self.wf_buf * WF_OKNO))
            hz = np.fft.rfftfreq(WF_FFT, 1.0 / F.FS_AUDIO) if F else None
            w = self.wf.shape[1]
            db = 20 * np.log10(np.interp(np.linspace(WF_F0, WF_F1, w), hz, widmo) + 1e-9)
            if self.nadaje:
                # w czasie nadawania radio oddaje własny sygnał (albo ciszę) – nie rysujemy go i nie psujemy nim poziomów
                wiersz = np.tile(np.array([70, 12, 12], np.uint8), (w, 1))
            else:
                szum, szczyt = np.percentile(db, 50) + 3, np.percentile(db, 99.5)     # szum ma być ciemny
                if self.wf_start:                          # pierwsza linia – poziomy od razu z pomiaru
                    self.wf_start, self.wf_lo, self.wf_hi = False, szum, szczyt
                if abs(szum - self.wf_lo) < 15:            # nagły skok (przełączenie radia) nie przestawia skali
                    self.wf_lo = self.wf_lo * 0.95 + szum * 0.05
                    self.wf_hi = self.wf_hi * 0.95 + szczyt * 0.05
                else:
                    self.wf_skok += 1
                    if self.wf_skok > 15:                  # trwa ponad 3 s – to nowy poziom, nie zakłócenie
                        self.wf_skok, self.wf_start = 0, True
                self.wf_hi = min(max(self.wf_hi, self.wf_lo + 20), self.wf_lo + 40)
                wiersz = _kolory((db - self.wf_lo) / (self.wf_hi - self.wf_lo))
            okno = int(time.time() // 15)
            if okno != self.wf_okno:                      # początek okna 15 s – cienka linia w poprzek
                self.wf_okno = okno
                wiersz = np.maximum(wiersz, np.array([70, 80, 110], np.uint8))
            wf = np.roll(self.wf, 1, axis=0)
            wf[0] = wiersz
            self.wf = wf

    def _wf_rozmiar(self, ev=None):
        """Wodospad ma szerokość listy – po zmianie rozmiaru okna nowa tablica i nowa skala."""
        w = max(200, self.wf_c.winfo_width() - 2)
        if w == self.wf.shape[1]:
            return
        self.wf = np.zeros((WF_H, w, 3), np.uint8)
        self.wf_img.configure(width=w, height=WF_H)
        self.wf_c.delete("skala")
        for f in range(500, WF_F1, 500):
            x = (f - WF_F0) / (WF_F1 - WF_F0) * w
            self.wf_c.create_line(x, WF_SKALA - 5, x, WF_SKALA, fill="#7aa", tags="skala")
            self.wf_c.create_text(x, 6, text=str(f), fill="#7aa", font=(M.MONO, 7), tags="skala")

    def _wf_rysuj(self):
        wf = self.wf
        h, w = wf.shape[:2]
        self.wf_img.configure(data=b"P6 %d %d 255\n" % (w, h) + wf.tobytes(), format="PPM")
        self.wf_c.delete("znacznik")
        for hz, kolor, opis in ((self.cfg["robot_log_hz"], M.AKCENT, "balon"), (self.cfg["robot_tx_hz"], "#ff3b3b", "TX")):
            x = (float(hz) - WF_F0) / (WF_F1 - WF_F0) * w
            self.wf_c.create_line(x, WF_SKALA, x, WF_SKALA + 14, fill=kolor, width=2, tags="znacznik")
            self.wf_c.create_text(x + 4, WF_SKALA + 7, text=opis, fill=kolor, anchor="w", font=(M.CZC, 7, "bold"), tags="znacznik")

    def _watek_dekodera(self):
        while self.alive:
            time.sleep(0.1)
            if self.okna is None:
                continue
            g = self.okna.gotowe()
            if not g:
                continue
            pocz, probki = g
            if pocz in self.okna_tx:
                continue
            try:
                dek = self.silnik.dekoduj(probki)
            except Exception as e:
                self.q_gui.put(("status", f"FT8: błąd dekodera: {e}"))
                continue
            self.q_gui.put(("dekody", pocz, dek))

    def _przyjmij(self, pocz, dekody):
        """Nowe okno z dekodera (wątek okna)."""
        c = self.cfg
        znak = c["robot_call"]
        self.okno_info = (pocz, len(dekody))
        if dekody:                                   # pustych okien nie pokazujemy – tylko licznik u góry
            self.lista.insert("", "end", values=(hhmmss(pocz), "", "", "", f"──── {len(dekody)} ────"), tags=("okno",))
        moj = c["my_call"]
        dane = False
        dts = []
        for d in dekody:
            tresc, tag = d.tekst, "zwykly"
            dts.append(d.dt - 0.5)
            if d.telemetria:
                if abs(d.hz - c["robot_log_hz"]) <= c["robot_log_tol_hz"]:
                    r = P.rozbierz(d.bity71, pocz)
                    if r and r["rodzaj"] in ("LOG", "STAN"):
                        tag = "balon"
                        tresc = self._opis_ramki(r)
                        if self.log.dodaj(r, pocz, "pc"):
                            self.log.zapisz()
                        dane = True
                    elif r and r["rodzaj"] == "KOMENDA":
                        tresc = f"[komenda {r['nazwa']} nr {r['licznik']}]"
                else:
                    tresc = "telemetria " + d.tekst
            else:
                slowa = d.tekst.replace("<", " ").replace(">", " ").split()
                if znak in slowa:
                    tag = "balon"
                elif moj in slowa:
                    tag = "moje"
                elif slowa[:1] == ["CQ"]:
                    tag = "cq"
            if tag == "balon":
                self.balon_okno = pocz
                self.log.slyszany = max(self.log.slyszany, pocz)
            self.lista.insert("", "end", values=(hhmmss(pocz), f"{d.snr:+.0f}", f"{d.dt - 0.5:+.1f}", f"{d.hz:.0f}", tresc),
                              tags=(tag,))
        dzieci = self.lista.get_children()
        if len(dzieci) > 600:
            self.lista.delete(*dzieci[:len(dzieci) - 600])
        self.lista.yview_moveto(1.0)
        if dts:
            self.dt_sr = float(np.median(dts))
        if dane:
            self._auto_po_oknie()

    @staticmethod
    def _opis_ramki(r):
        if r["rodzaj"] == "LOG":
            kiedy = time.strftime("%d.%m %H:%M", time.gmtime(r["czas"]))
            return f"LOG wpis …{r['nr8']}: {r['znak1']}" + (f", {r['znak2']}" if r["znak2"] else "") + f"  ({kiedy} UTC)"
        snr = "nie słyszy domu" if r["snr"] is None else f"dom {r['snr']:+d} dB"
        return (f"STAN: wpisy {r['wpisy']} (bez potw. {r['zaleglosc']}), QSO {r['qso']}, {r['napiecie']:.2f} V, "
                f"{r['temp']:+d} °C, {r['tryb_opis']}, komenda nr {r['kom']}, {snr}")

    # ------------------------------------------------------------------ komendy i kolejka
    def _klucz(self):
        k = P.wczytaj_klucz(self.klucz_plik)
        if k:
            return k
        if messagebox.askyesno("GOLbase – klucz komend",
                               "Komendy do balonu muszą mieć podpis, a pliku z kluczem jeszcze nie ma:\n"
                               f"{self.klucz_plik}\n\nUtworzyć nowy klucz? Ten sam klucz trzeba potem wgrać do trackera. "
                               "Pliku nie wysyłaj nikomu i nie wrzucaj do repozytorium."):
            return P.utworz_klucz(self.klucz_plik)
        return None

    def dodaj_komende(self, kod, arg, auto=False, opis=None):
        if not auto and (not self._radio_ok() or not self._klucz()):
            return False
        with self.kol_blokada:
            if any(k["rodzaj"] == "kom" and k["kod"] == kod for k in self.kolejka):      # ta sama komenda już czeka
                self.kolejka = [k for k in self.kolejka if not (k["rodzaj"] == "kom" and k["kod"] == kod)]
            self.kolejka.append({"rodzaj": "kom", "kod": kod, "arg": dict(arg), "opis": opis or OPISY_KROTKIE.get(kod) or P.opis_komendy(kod, arg)})
        self.stop_evt.clear()
        return True

    def dodaj_tekst(self, tekst):
        tekst = " ".join(tekst.upper().split())
        if not tekst or not self.silnik or not self._radio_ok():
            return
        try:
            self.silnik.pakuj_tekst(tekst)
        except ValueError as e:
            messagebox.showerror("GOLbase", str(e)); return
        if self.cfg["robot_call"] in tekst.split()[1:2]:
            messagebox.showerror("GOLbase", f"Z domu nie nadajemy jako {self.cfg['robot_call']} – to znak balonu."); return
        with self.kol_blokada:
            self.kolejka.append({"rodzaj": "tekst", "tekst": tekst, "opis": tekst})
        self.stop_evt.clear()

    def kom_potwierdz(self):
        p = self.log.potwierdzenie()
        if p["do"] == 0 and p["mapa"] == 0:
            messagebox.showinfo("GOLbase", "Nie ma jeszcze żadnego ponumerowanego wpisu logu do potwierdzenia."); return
        if self.dodaj_komende(1, p):
            self.potw_wyslane = p

    def kom_dosylka(self):
        brak = self.log.brakujace()
        if not brak:
            messagebox.showinfo("GOLbase", "Według odebranych ramek w logu niczego nie brakuje."); return
        self.dodaj_komende(2, {"od": brak[0], "do": min(brak[-1], brak[0] + 15)})

    def _auto(self):
        if self.var_auto.get():
            if not self._radio_ok() or not self._klucz():
                self.var_auto.set(False); return
            self.auto_do = time.time() + 60 * float(self.cfg["robot_auto_min"])
        else:
            self.auto_do = 0

    def _auto_po_oknie(self):
        """Po oknie, w którym odebrano ramkę danych balonu: w trybie Auto dołóż potwierdzenie logu, gdy jest co potwierdzać."""
        if not self.var_auto.get() or time.time() > self.auto_do or time.time() - self.auto_ostatnia < 120:
            return
        if not self._radio_ok(cicho=True) or not P.wczytaj_klucz(self.klucz_plik):
            return
        p, s = self.log.potwierdzenie(), self.log.stan
        if p["do"] == 0 and p["mapa"] == 0:
            return
        # do którego wpisu balon ma już nasze potwierdzenie (z ramki STAN); None = nie wiemy
        u_balonu = (s["wpisy"] - s["zaleglosc"]) if s and s["zaleglosc"] < 255 else None
        if u_balonu is None:
            if p == self.potw_wyslane:
                return
        elif u_balonu >= p["do"] and (p["mapa"] == 0 or p == self.potw_wyslane):
            return                                    # balon już wie o wszystkim, co mamy
        if self.dodaj_komende(1, p, auto=True):
            self.potw_wyslane = p
            self.auto_ostatnia = time.time()

    def stop(self):
        """Natychmiast przerywa nadawanie, czyści kolejkę i wyłącza Auto."""
        self.stop_evt.set()
        with self.kol_blokada:
            self.kolejka = []
        self.var_auto.set(False); self.auto_do = 0
        try:
            if self.sd is not None:
                self.sd.stop()
        except Exception:
            pass
        try:
            if self.radio:
                self.radio.ptt(False)
        except Exception:
            pass

    # ------------------------------------------------------------------ nadawanie
    def _okno_nadawania(self):
        """Początek najbliższego okna, w którym wolno nadać: nie w oknach balonu (jeśli słychać go od niedawna)."""
        t = time.time()
        pocz = (int(t // 15) + 1) * 15
        if pocz - t < 0.6:
            pocz += 15
        if self.balon_okno and t - self.balon_okno < 900 and (pocz - self.balon_okno) % 30 == 0:
            pocz += 15                                # balon nadaje w oknach tej parzystości – my w przeciwnych
        return pocz

    def _watek_nadawania(self):
        while self.alive:
            time.sleep(0.05)
            with self.kol_blokada:
                poz = self.kolejka[0] if self.kolejka else None
            if poz is None or self.stop_evt.is_set():
                continue
            try:
                self._nadaj(poz)
            except Exception as e:
                self.q_gui.put(("status", f"FT8 nadawanie: {e}"))
                with self.kol_blokada:
                    if poz in self.kolejka:
                        self.kolejka.remove(poz)
            finally:
                self.nadaje = False
                try:
                    if self.radio:
                        self.radio.ptt(False)
                except Exception:
                    pass

    def _czekaj_do(self, t):
        while time.time() < t:
            if self.stop_evt.is_set() or not self.alive:
                return False
            time.sleep(min(0.02, max(0.0, t - time.time())))
        return True

    def _nadaj(self, poz):
        c = self.cfg
        if self.sd is None or not self.silnik:
            raise RuntimeError("brak biblioteki dźwięku albo silnika FT8")
        if not self._radio_ok(cicho=True):
            raise RuntimeError("radio nie jest połączone – pozycja usunięta z kolejki")
        if not logbook.band_of(self.radio.freq / 1e6):
            raise RuntimeError(f"częstotliwość {self.radio.freq / 1e6:.4f} MHz poza pasmem amatorskim – nie nadaję")
        if self.wyj_idx is None:
            raise RuntimeError("wybierz wyjście audio do radia")
        pocz = self._okno_nadawania()
        if not self._czekaj_do(pocz - 0.45):
            return
        if poz["rodzaj"] == "kom":
            klucz = P.wczytaj_klucz(self.klucz_plik)
            if not klucz:
                raise RuntimeError("brak pliku z kluczem komend")
            licznik = (int(c["robot_licznik"]) + 1) % 64
            payload = self.silnik.pakuj_telemetrie(P.ramka_komenda(poz["kod"], poz["arg"], licznik, klucz, pocz))
            opis = f"[komenda nr {licznik}] {poz['opis']}"
        else:
            payload = self.silnik.pakuj_tekst(poz["tekst"])
            opis = poz["tekst"]
        hz = float(c["robot_tx_hz"])
        dzwiek = np.concatenate([np.zeros(int(0.5 * F.FS_AUDIO), np.float32),
                                 F.synteza(self.silnik.tony(payload), hz, poziom=float(c["ft8_tx_poziom"]))])
        if not self._czekaj_do(pocz - 0.15):
            return
        self.nadaje = True
        self.okna_tx.add(pocz)
        if not self.radio.ptt(True):
            raise RuntimeError("radio nie przyjęło polecenia nadawania")
        self._czekaj_do(pocz)
        self.q_gui.put(("tx", pocz, hz, opis))
        self.sd.play(dzwiek, F.FS_AUDIO, device=self.wyj_idx)
        dokonczone = self._czekaj_do(pocz + len(dzwiek) / F.FS_AUDIO + 0.15)
        self.sd.stop()
        self.radio.ptt(False)
        self.nadaje = False
        with self.kol_blokada:
            if poz in self.kolejka:
                self.kolejka.remove(poz)
            if dokonczone and poz["rodzaj"] == "kom":             # po komendzie – zwykła ramka ze znakiem operatora
                self.kolejka.insert(0, {"rodzaj": "tekst", "tekst": self._id_tekst(), "opis": self._id_tekst()})
        if dokonczone and poz["rodzaj"] == "kom":
            c["robot_licznik"] = licznik
            self.q_gui.put(("zapisz",))
        if len(self.okna_tx) > 50:
            self.okna_tx = set(sorted(self.okna_tx)[-20:])

    # ------------------------------------------------------------------ Log4OM
    def okno_log4om(self):
        nowe = self.log.nowe_do_logu()
        if not nowe:
            messagebox.showinfo("GOLbase", "Nie ma nowych łączności balonu do przekazania."); return
        c = self.cfg
        adres = c["robot_log4om_udp"] or c["log4om_udp"]
        w = tk.Toplevel(self.f); w.title("GOLbase – nowe łączności balonu"); w.transient(self.f.winfo_toplevel())
        w.configure(bg=M.TLO); M.ciemna_belka(w)
        od, do = nowe[0]["czas"], nowe[-1]["czas"]
        zakres = time.strftime("%d.%m %H:%M", time.gmtime(od)) + "–" + time.strftime("%d.%m %H:%M", time.gmtime(do)) + " UTC"
        naglowek = ttk.Label(w, font=("Segoe UI", 11, "bold")); naglowek.pack(anchor="w", padx=8, pady=(8, 2))
        plik = os.path.join(self.data_dir, f"robot_{c['robot_call']}_log.adi")
        ttk.Label(w, text=f"Kliknięcie w wiersz zaznacza / odznacza. Wpisy są zapisywane do pliku ADIF ({plik}) jako "
                          f"STATION_CALLSIGN = {c['robot_call']}, OPERATOR = {c['my_call']}, FT8, {c['robot_qso_mhz']} MHz.\n"
                          f"Log4OM jest dodatkiem: przy wysyłce powinna być w nim otwarta osobna baza / konfiguracja "
                          f"dla znaku {c['robot_call']}.",
                  foreground=M.SZARY, justify="left").pack(anchor="w", padx=8)
        var_l4o = tk.BooleanVar(value=bool(c.get("robot_log4om_send", True)))
        tv = ttk.Treeview(w, columns=("z", "znak", "czas", "nr"), show="headings", height=min(18, max(6, len(nowe))),
                          selectmode="none")
        for k, n, sz in (("z", "", 30), ("znak", "Znak", 110), ("czas", "Data i czas UTC", 150), ("nr", "Wpis nr", 70)):
            tv.heading(k, text=n); tv.column(k, width=sz, anchor="center" if k != "znak" else "w")
        tv.pack(fill="both", expand=True, padx=8, pady=6)
        zazn = {}
        for q in nowe:
            iid = tv.insert("", "end", values=("✔", q["znak"], time.strftime("%d.%m.%Y %H:%M", time.gmtime(q["czas"])),
                                               q["nr"] if q["nr"] else "—"))
            zazn[iid] = [True, q]

        def tytul():
            n = sum(1 for z, _ in zazn.values() if z)
            naglowek.config(text=f"Nowe łączności {c['robot_call']}: {len(zazn)} ({zakres}) – zaznaczone {n}")

        def klik(ev):
            iid = tv.identify_row(ev.y)
            if iid in zazn:
                zazn[iid][0] = not zazn[iid][0]
                tv.set(iid, "z", "✔" if zazn[iid][0] else "")
                tytul()

        def wszystkie(stan):
            for iid in zazn:
                zazn[iid][0] = stan
                tv.set(iid, "z", "✔" if stan else "")
            tytul()

        def wyslij():
            wyb = [(iid, q) for iid, (z, q) in zazn.items() if z]
            do_l4o = bool(var_l4o.get())
            if c.get("robot_log4om_send", True) != do_l4o:
                c["robot_log4om_send"] = do_l4o
                self.save_cfg(c)
            gdzie = "pliku ADIF" + (f" i wysłać do Log4OM ({adres})" if do_l4o else "")
            if not wyb or not messagebox.askyesno("GOLbase", f"Zapisać {len(wyb)} łączności {c['robot_call']} do {gdzie}?",
                                                  parent=w):
                return
            ok, bledy, bledy_l4o = [], 0, 0
            for iid, q in wyb:
                tm = time.gmtime(q["czas"])
                rec = logbook.adif_record({
                    "call": q["znak"], "qso_date": time.strftime("%Y%m%d", tm), "time_on": time.strftime("%H%M%S", tm),
                    "mode": "FT8", "freq": f"{float(c['robot_qso_mhz']):.6f}", "band": logbook.band_of(float(c["robot_qso_mhz"])),
                    "station_callsign": c["robot_call"], "operator": c["my_call"],
                    "comment": "Balon pikowy, robot FT8 - log odebrany radiem (czas +-10 min)"})
                try:
                    logbook.append_adi(plik, rec)
                except Exception:
                    bledy += 1
                    continue
                ok.append((iid, q["klucz"]))              # zapis do pliku ADIF jest podstawą; Log4OM tylko dodatkiem
                if do_l4o:
                    try:
                        logbook.send_log4om(rec, adres)
                        time.sleep(0.03)
                    except Exception:
                        bledy_l4o += 1
            self.log.oznacz([k for _, k in ok])
            for iid, _ in ok:
                tv.delete(iid); zazn.pop(iid)
            self._status(f"Zapisano {len(ok)} łączności {c['robot_call']} w {plik}" + (f", błędów zapisu {bledy}" if bledy else "")
                         + ((f"; Log4OM: wysłano {len(ok) - bledy_l4o}" + (f", błędów {bledy_l4o}" if bledy_l4o else ""))
                            if do_l4o else "; Log4OM wyłączony"))
            if not zazn:
                w.destroy()
            else:
                tytul()

        def pomin():
            wyb = [(iid, q) for iid, (z, q) in zazn.items() if z]
            if not wyb or not messagebox.askyesno("GOLbase", f"Pominąć {len(wyb)} zaznaczonych łączności? "
                                                           "Nie będą więcej proponowane do logu.", parent=w):
                return
            self.log.oznacz([q["klucz"] for _, q in wyb], pomin=True)
            for iid, _ in wyb:
                tv.delete(iid); zazn.pop(iid)
            if not zazn:
                w.destroy()
            else:
                tytul()

        tv.bind("<Button-1>", klik)
        b = ttk.Frame(w, padding=8); b.pack(fill="x")
        ttk.Button(b, text="Zapisz zaznaczone", command=wyslij).pack(side="left")
        ttk.Checkbutton(b, text="wyślij też do Log4OM", variable=var_l4o).pack(side="left", padx=(10, 0))
        ttk.Button(b, text="Pomiń zaznaczone", command=pomin).pack(side="left", padx=6)
        ttk.Button(b, text="Odznacz wszystkie", command=lambda: wszystkie(False)).pack(side="left")
        ttk.Button(b, text="Zaznacz wszystkie", command=lambda: wszystkie(True)).pack(side="left", padx=6)
        ttk.Button(b, text="Zamknij", command=w.destroy).pack(side="right")
        tytul()

    # ------------------------------------------------------------------ okno „Komenda…”
    def _buduj_komendy(self, rodzic):
        """Panel „Komendy” w głównym oknie: lista wszystkich komend, pod nią opis po ludzku i pola w zwykłych jednostkach."""
        w = self.f
        k = M.karta(rodzic, "Komendy"); k.zew.pack(fill="both", expand=True)
        lb = tk.Listbox(k, height=len(FORMULARZE), width=30, font=(M.CZC, 10), bg=M.POLE, fg=M.TEKST, relief="flat",
                        highlightthickness=1, highlightbackground=M.LINIA, activestyle="none", exportselection=False,
                        selectbackground=M.AKCENT, selectforeground="#141414")
        for fm in FORMULARZE:
            lb.insert("end", "  " + fm["tytul"])
        lb.pack(fill="x")
        tytul = ttk.Label(k, text="", style="Karta.TLabel", foreground=M.AKCENT, font=(M.CZC, 12, "bold"))
        tytul.pack(anchor="w", pady=(10, 0))
        opis = ttk.Label(k, text="", wraplength=300, justify="left", style="Karta.TLabel"); opis.pack(anchor="w", pady=(2, 6))
        pola_fr = ttk.Frame(k, style="Karta.TFrame"); pola_fr.pack(anchor="w", fill="x")
        dol = ttk.Frame(k, style="Karta.TFrame"); dol.pack(side="bottom", fill="x", pady=(8, 0))
        uwaga = ttk.Label(k, text="", wraplength=300, justify="left", style="KartaSzary.TLabel"); uwaga.pack(anchor="w", pady=(6, 0))
        zm = {}

        def wybor(*a):
            fm = FORMULARZE[lb.curselection()[0]]
            tytul.config(text=fm["tytul"]); opis.config(text=fm["opis"]); uwaga.config(text=fm.get("uwaga", ""))
            for x in pola_fr.winfo_children():
                x.destroy()
            zm.clear()
            for i, (nazwa, etykieta, rodzaj, *par) in enumerate(fm["pola"]):
                ttk.Label(pola_fr, text=etykieta, style="KartaSzary.TLabel").grid(row=i, column=0, sticky="w", pady=3, padx=(0, 8))
                v = tk.StringVar()
                if rodzaj == "wybor":
                    wid = ttk.Combobox(pola_fr, textvariable=v, values=par[0], state="readonly", width=22)
                    v.set(par[0][par[1] if len(par) > 1 else 0])
                else:
                    wid = ttk.Entry(pola_fr, textvariable=v, width=9)
                    v.set(str(par[-1]) if rodzaj in ("liczba", "skala") else "")
                wid.grid(row=i, column=1, sticky="w", columnspan=2 if rodzaj == "wybor" else 1)
                jedn = {"liczba": lambda: par[2], "skala": lambda: par[3], "szer": lambda: "° (−90…90)",
                        "dlug": lambda: "° (−180…180)", "znak": lambda: "np. QQ0Q", "lokator": lambda: "np. JO91AB"}
                if rodzaj in jedn:
                    ttk.Label(pola_fr, text=jedn[rodzaj](), style="KartaSzary.TLabel").grid(row=i, column=2, sticky="w", padx=5)
                zm[nazwa] = (v, rodzaj, par, etykieta)
            if fm.get("auto"):
                p = self.log.potwierdzenie()
                uwaga.config(text=f"Z odebranego logu: mam komplet do wpisu nr {p['do']}"
                                  + (", dalsze pojedyncze też zaznaczone." if p["mapa"] else "."))

        def wartosc(v, rodzaj, par, etykieta):
            """Pole formularza -> (liczba do ramki, tekst do opisu w kolejce)."""
            t = v.get().strip()
            if rodzaj == "wybor":
                return par[0].index(t), t
            if rodzaj == "znak":
                return P.pakuj_znak(t), t.upper()
            if rodzaj == "lokator":
                return (P.pakuj_lokator(t) if t else 0), t.upper()
            try:
                x = float(t.replace(",", "."))
            except ValueError:
                raise ValueError(f"„{etykieta}” – wpisz liczbę")
            if rodzaj == "liczba":
                if not par[0] <= x <= par[1]:
                    raise ValueError(f"„{etykieta}” – dozwolone {par[0]}…{par[1]}")
                return int(round(x)), f"{x:g} {par[2]}".strip()
            if rodzaj == "skala":
                if not par[1] <= x <= par[2]:
                    raise ValueError(f"„{etykieta}” – dozwolone {par[1]}…{par[2]} {par[3]}")
                return int(round(x / par[0])), f"{x:g} {par[3]}"
            pol = 90 if rodzaj == "szer" else 180
            if not -pol <= x <= pol:
                raise ValueError(f"„{etykieta}” – dozwolone −{pol}…{pol}°")
            return min(int(round((x + pol) / 2)), pol - 1 if rodzaj == "szer" else 179), f"{x:g}°"

        def dodaj():
            fm = FORMULARZE[lb.curselection()[0]]
            arg, czesci = dict(fm.get("stale", {})), []
            try:
                if fm.get("auto"):
                    arg = self.log.potwierdzenie()
                    if arg["do"] == 0 and arg["mapa"] == 0:
                        raise ValueError("nie ma jeszcze żadnego ponumerowanego wpisu logu do potwierdzenia")
                for nazwa, (v, rodzaj, par, etykieta) in zm.items():
                    arg[nazwa], txt = wartosc(v, rodzaj, par, etykieta)
                    czesci.append(txt)
                if fm["nazwa"] == "NADAWANIE" and arg["wlacz"] == 1:
                    arg["dni"] = 0
                if fm["nazwa"] == "LOKATOR" and arg["staly"] == 1 and not arg["lokator"]:
                    raise ValueError("wpisz lokator")
                P.ramka_komenda(fm["nazwa"], arg, 0, b"0" * 16, 0)
            except ValueError as e:
                messagebox.showerror("GOLbase", str(e), parent=w); return
            if fm.get("pytaj") and not messagebox.askyesno("GOLbase – na pewno?", fm["pytaj"] + "\n\n" + fm["tytul"] + ": "
                                                           + ", ".join(czesci), parent=w):
                return
            self.dodaj_komende(P.KOD[fm["nazwa"]], arg, opis=fm["tytul"] + (": " + ", ".join(czesci) if czesci else ""))

        lb.bind("<<ListboxSelect>>", wybor)
        lb.selection_set(0); wybor()
        ttk.Button(dol, text="Do kolejki nadawania", style="Akcent.TButton", command=dodaj).pack(fill="x")

    # ------------------------------------------------------------------ pętla okna
    def _tyk(self):
        if not self.alive:
            return
        try:
            while True:
                z = self.q_gui.get_nowait()
                if z[0] == "dekody":
                    self._przyjmij(z[1], z[2])
                elif z[0] == "tx":
                    self.lista.insert("", "end", values=(hhmmss(z[1]), "TX", "", f"{z[2]:.0f}", z[3]), tags=("tx",))
                    self.lista.yview_moveto(1.0)
                elif z[0] == "status":
                    self._status(z[1])
                elif z[0] == "zapisz":
                    self.save_cfg(self.cfg)
        except queue.Empty:
            pass
        t = time.time()
        s = t % 15
        self.pasek["value"] = s
        self.lbl_zegar.config(text=f"{hhmmss(t)} UTC")
        if self.okno_info:
            zle = self.dt_sr is not None and abs(self.dt_sr) > 0.8
            dt = "" if self.dt_sr is None else f" · zegar PC: DT {self.dt_sr:+.1f} s" + (" – ustaw zegar komputera!" if zle else "")
            self.lbl_dt.config(text=f"okno {hhmmss(self.okno_info[0])}: {self.okno_info[1]} dekodów{dt}",
                               foreground=M.CZERWONY if zle else M.SZARY)
        r = self.radio
        if r is None:
            self.lbl_radio.config(text="radio niepołączone – wybierz i „Połącz radio”", foreground=M.SZARY)
        elif r.online:
            self.lbl_radio.config(text="radio połączone", foreground=M.ZIELONY)
        else:
            self.lbl_radio.config(text=r.stan, foreground=M.CZERWONY)
        if self.app.zakladka == 1:                    # duża częstotliwość u góry okna – z radia tej zakładki
            self.app.lbl_freq.config(text=(f"{r.freq / 1e6:,.5f} MHz  {r.mode or ''}".replace(",", " ") if r and r.online else "  —"))
        if self.log.slyszany:
            wiek = t - self.log.slyszany
            ile = f"{wiek:.0f} s" if wiek < 120 else (f"{wiek / 60:.0f} min" if wiek < 7200 else f"{wiek / 3600:.0f} h")
            self.lbl_slychac.config(text=f"słyszany {ile} temu", foreground=M.ZIELONY if wiek < 300 else M.SZARY)
        st = self.log.stan
        if st:
            snr = "nie słyszy domu" if st["snr"] is None else f"słyszy dom {st['snr']:+d} dB"
            self.lbl_stan.config(text=f"stan ({hhmmss(st['t'])[:5]}): {st['napiecie']:.2f} V, {st['temp']:+d} °C, "
                                      f"{st['tryb_opis']}, {snr}, ostatnia komenda nr {st['kom']}")
        self.lbl_log.config(text="log: " + self.log.skrot())
        n = len(self.log.nowe_do_logu())
        self.btn_l4o.config(text=f"Nowe łączności → log ({n})", state="normal" if n else "disabled")
        with self.kol_blokada:
            poz = [k["opis"] for k in self.kolejka]
        if list(self.lb_kol.get(0, "end")) != poz:
            self.lb_kol.delete(0, "end")
            for p in poz:
                self.lb_kol.insert("end", p)
        if self.nadaje:
            lampka = ("●  NADAJĘ  –  STOP (Esc)", "#ff1f1f", "white")
        elif poz:
            lampka = ("czeka na okno  –  STOP (Esc)", "#e0a800", "#141414")
        else:
            lampka = ("STOP  (Esc)", "#1b2540", M.SZARY)
        if self.btn_stop.cget("text") != lampka[0]:
            self.btn_stop.config(text=lampka[0], bg=lampka[1], fg=lampka[2])
        self._wf_rysuj()
        if self.var_auto.get():
            if t > self.auto_do:
                self.var_auto.set(False)
                self.lbl_auto.config(text="Auto wyłączyło się samo – zaznacz ponownie, jeśli jesteś przy radiu.")
            else:
                self.lbl_auto.config(text=f"Auto jeszcze {max(0, self.auto_do - t) / 60:.0f} min")
        elif not self.lbl_auto.cget("text").startswith("Auto wyłączyło"):
            self.lbl_auto.config(text="")
        self.f.after(100, self._tyk)

    def zamknij(self):
        self.alive = False
        self.stop_evt.set()
        try:
            if self.radio:
                self.radio.close()
        except Exception:
            pass
        try:
            self.log.zapisz()
        except Exception:
            pass

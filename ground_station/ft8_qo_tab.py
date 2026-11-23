"""
Zakładka „FT8 QO-100” programu GOLbase – zwykłe łączności FT8 przez satelitę QO-100 (transwerter, pośrednia 29 MHz).

Po co: JTDX widzi tylko pośrednią (29,040 MHz) i tak zapisuje łączność – w Log4OM trzeba potem ręcznie poprawiać
częstotliwości i dopisywać satelitę. Tutaj łączność idzie do Log4OM od razu poprawnie:
FREQ = uplink 2400 MHz (13 cm), FREQ_RX = downlink 10 489 MHz (3 cm), PROP_MODE = SAT, SAT_NAME = QO-100, raporty, lokator.

Co robi:
  * dekoduje FT8 z dźwięku radia (ten sam silnik co „FT8 balon”), pokazuje listę i wodospad,
  * dwuklik w komunikat = wołaj tę stację; dalej łączność idzie sama (ft8_qso.Sekwencer), można też wołać CQ,
  * nadaje przez to samo radio i wyjście dźwięku co zakładka „FT8 balon” (OmniRig albo CI-V wprost),
  * gotową łączność zapisuje do golbase_log.adi i wysyła do Log4OM (UDP, jak JTDX).

Nadawanie tylko przy operatorze: po kilku nadaniach bez odpowiedzi wyłącza się samo, Esc / STOP przerywa natychmiast.
"""
import os, queue, threading, time, tkinter as tk
from tkinter import ttk, messagebox

import numpy as np

import ft8_qso as Q
import logbook
import motyw as M
import qo100
import wsjtx_udp
from ft8_tab import RADIA, WF_F0, WF_F1, WF_H, WF_SKALA, WF_FFT, WF_KROK, WF_OKNO, _kolory, hhmmss

try:
    import ft8silnik as F
except Exception:  # pragma: no cover
    F = None

DOMYSLNE = {
    "qo_ft8_dial_khz": 29040.0,       # radio (USB-D) dla FT8 na QO-100: 29,040 MHz = downlink 10 489,540 / uplink 2 400,040 MHz
    "qo_ft8_tx_hz": 1500,             # gdzie nadajemy [Hz dźwięku]
    "qo_lokator": "AA00AA",           # mój lokator: w komunikatach idą 4 znaki, do logu cały
    "qo_ft8_limit": 6,                # po ilu nadaniach bez odpowiedzi wyłączyć nadawanie (wołanie stacji)
    "qo_ft8_limit_cq": 12,            # to samo dla CQ
    "qo_ft8_autolog": True,           # zapisuj łączność sam (bez pytania)
    "qo_ft8_snr_poprawka_db": -13.0,  # poprawka raportu w tej zakładce: porównanie z JTDX na QO-100 22.11.2026 (6 ramek: +10…+17 dB)
    "gt_pasmo": "uplink",             # częstotliwość dla GridTrackera: "uplink" (2400 MHz, 13 cm) albo "downlink"
    "gt_send": True,                  # wysyłaj dekody i stan do GridTrackera (format WSJT-X / JTDX)
    "gt_udp": "127.0.0.1:2240",       # adres GridTrackera – port, na którym nie słucha Log4OM
    "qo_ft8_spoznienie_s": 4.0,       # do ilu sekund po początku okna wolno jeszcze zacząć nadawać (jak w JTDX – bez początku)
}
DROGA_SAT = 0.26                             # [s] Ziemia – QO-100 – Ziemia: tyle DT ma każda stacja przy dobrym zegarze
IF_MIN, IF_MAX = 29_000_000, 29_500_000      # pośrednia transwertera – poza nią nie nadajemy
SPOZNIENIE_MAX = 5.0                         # górna granica qo_ft8_spoznienie_s: próba z dekoderem – do 4 s pewnie, 5 s co drugi raz, 6 s nigdy
NAZWY_KROKOW = (("CQ", "CQ"), ("LOK", "1  wołam"), ("RPT", "2  raport"), ("RRPT", "3  R + raport"),
                ("RR73", "4  RR73"), ("73", "5  73"))


class ZakladkaQO:
    def __init__(self, ramka, app, save_cfg, data_dir, sd, balon):
        self.f, self.app, self.save_cfg, self.sd, self.balon = ramka, app, save_cfg, sd, balon
        self.cfg = app.cfg
        for k, v in DOMYSLNE.items():
            self.cfg.setdefault(k, v)
        self.data_dir = data_dir
        self.plik_logu = os.path.join(data_dir, "golbase_log.adi")
        self.silnik = balon.silnik                 # wspólna biblioteka FT8 (ma własną blokadę)
        self.okna = F.Okna() if (F is not None and self.silnik) else None
        c = self.cfg
        self.sekw = Q.Sekwencer(c["my_call"], c["qo_lokator"], c["qo_ft8_limit"], c["qo_ft8_limit_cq"])
        self.q_gui = queue.Queue()
        self.stop_evt = threading.Event()
        self.aktywna = False                       # zakładka otwarta – tylko wtedy dekodujemy i nadajemy
        self.nadaje = False
        self.okna_tx = set()                       # okna, w których nadawaliśmy (nie dekodujemy własnego sygnału)
        self.okno_przetw = 0.0                     # początek ostatniego okna, które przeszło przez automat
        self.okno_info, self.dt_sr = None, None
        self.wiersze = {}                          # wiersz listy -> (początek okna, tekst, snr, hz)
        self.slyszane = {}                         # znak -> (początek okna, snr, hz, lokator)
        self.czeka_log = None                      # łączność do zapisu, gdy „zapisuj sam” wyłączone
        self.zrobione = self._wczytaj_zrobione()
        self.wf = np.zeros((WF_H, 4, 3), np.uint8)
        self.wf_buf = np.zeros(0, np.float32)
        self.wf_ile, self.wf_okno, self.wf_lo, self.wf_hi = 0, 0, -60.0, -20.0
        self.wf_start, self.wf_skok = True, 0
        self.alive = True
        self.gt = wsjtx_udp.Nadawca()              # dekody i stan dla GridTrackera
        self.gt_stan, self.gt_t_stan, self.gt_t_zyje = None, 0.0, 0.0
        self._buduj()
        threading.Thread(target=self._watek_dekodera, daemon=True).start()
        threading.Thread(target=self._watek_nadawania, daemon=True).start()
        self.f.after(200, self._tyk)

    @property
    def radio(self):
        return self.balon.radio

    # ------------------------------------------------------------------ okno
    def _buduj(self):
        f, c = self.f, self.cfg
        st = ttk.Style(f)
        st.configure("Karta.TRadiobutton", background=M.PANEL, foreground=M.TEKST, indicatorbackground=M.POLE,
                     indicatorforeground=M.AKCENT, font=(M.MONO, 10))
        st.map("Karta.TRadiobutton", background=[("active", M.PANEL)], indicatorbackground=[("selected", M.AKCENT)])

        g = ttk.Frame(f, padding=(10, 10, 10, 4)); g.pack(fill="x")
        self.cb_radio = ttk.Combobox(g, width=34, state="readonly", values=[n for _, n in RADIA])
        self.cb_radio.set(dict(RADIA).get(c["ft8_radio"], RADIA[0][1])); self.cb_radio.pack(side="left")
        self.cb_radio.bind("<<ComboboxSelected>>", self._wybor_radia)
        self.btn_radio = ttk.Button(g, text="Połącz radio", width=13, command=self.balon._przycisk_radia)
        self.btn_radio.pack(side="left", padx=(6, 14))
        self.var_khz = tk.StringVar(value=f"{c['qo_ft8_dial_khz']:g}")
        ttk.Entry(g, textvariable=self.var_khz, width=8).pack(side="left")
        ttk.Label(g, text="kHz", style="Szary.TLabel").pack(side="left", padx=(3, 6))
        ttk.Button(g, text="Ustaw radio (USB-D)", command=self.ustaw_radio).pack(side="left")
        ttk.Label(g, text="  moc radia najwyżej 5 W!", foreground=M.AKCENT).pack(side="left")
        ttk.Button(g, text="⚙ Ustawienia", command=self.okno_ustawien).pack(side="right")

        g = ttk.Frame(f, padding=(10, 2, 10, 6)); g.pack(fill="x")
        self.lbl_radio = ttk.Label(g, text="radio niepołączone", style="Szary.TLabel"); self.lbl_radio.pack(side="left")
        self.lbl_qo = ttk.Label(g, text="", font=(M.MONO, 10), foreground=M.NIEBIESKI); self.lbl_qo.pack(side="left", padx=16)
        self.lbl_dt = ttk.Label(g, text="", style="Szary.TLabel"); self.lbl_dt.pack(side="left")
        self.lbl_zegar = ttk.Label(g, text="", style="Zegar.TLabel"); self.lbl_zegar.pack(side="right")
        self.pasek = ttk.Progressbar(g, length=180, maximum=15.0); self.pasek.pack(side="right", padx=10)

        srodek = ttk.Frame(f, padding=(10, 0, 10, 10)); srodek.pack(fill="both", expand=True)
        prawa = ttk.Frame(srodek); prawa.pack(side="right", fill="y", padx=(10, 0))
        lewa_kol = ttk.Frame(srodek); lewa_kol.pack(side="left", fill="both", expand=True)
        # wodospad 200–3000 Hz: kliknięcie = częstotliwość nadawania (czerwona kreska); niebieska = korespondent
        self.wf_c = tk.Canvas(lewa_kol, height=WF_SKALA + WF_H, bg="#000010", highlightthickness=1,
                              highlightbackground=M.LINIA, cursor="crosshair")
        self.wf_c.pack(fill="x", pady=(0, 6))
        self.wf_img = tk.PhotoImage(width=4, height=WF_H)
        self.wf_c.create_image(0, WF_SKALA, image=self.wf_img, anchor="nw")
        self.wf_c.bind("<Configure>", self._wf_rozmiar)
        self.wf_c.bind("<Button-1>", self._wf_klik)
        lewa = tk.Frame(lewa_kol, bg=M.LINIA); lewa.pack(fill="both", expand=True)
        kol = ("utc", "db", "dt", "hz", "tresc", "kraj")
        self.lista = ttk.Treeview(lewa, columns=kol, show="headings", height=14, selectmode="browse")
        for k, n, w in zip(kol, ("UTC", "dB", "DT", "Hz", "Treść", "Kraj"), (84, 48, 56, 60, 260, 200)):
            lewo = k in ("tresc", "kraj")
            self.lista.heading(k, text=n, anchor="w" if lewo else "e")
            self.lista.column(k, width=w, minwidth=w if not lewo else 140, anchor="w" if lewo else "e", stretch=lewo)
        self.lista.tag_configure("okno", foreground="#4d5870", font=(M.MONO, 9))
        self.lista.tag_configure("tx", foreground=M.CZERWONY, font=(M.MONO, 11, "bold"))
        self.lista.tag_configure("moje", background=M.BALON_TLO, foreground="#ffc46b", font=(M.MONO, 11, "bold"))
        self.lista.tag_configure("dx", foreground=M.NIEBIESKI, font=(M.MONO, 11, "bold"))
        self.lista.tag_configure("cq", foreground=M.ZIELONY)
        self.lista.tag_configure("cq_stare", foreground="#5f8f6f")
        self.lista.tag_configure("log", foreground=M.AKCENT, font=(M.MONO, 11, "bold"))
        self.lista.tag_configure("zwykly", foreground=M.TEKST)
        self.lista.bind("<Double-1>", self._dwuklik)
        sb = ttk.Scrollbar(lewa, command=self.lista.yview); self.lista.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", padx=(0, 1), pady=1); self.lista.pack(side="left", fill="both", expand=True, padx=(1, 0), pady=1)
        ttk.Label(lewa_kol, text="Dwuklik = wołaj stację · klik w wodospad = moja częstotliwość · zielone = CQ (ciemne: już w logu) · "
                                 "pomarańczowe = do mnie",
                  style="Szary.TLabel").pack(anchor="w", pady=(4, 0))

        qs = M.karta(prawa, "Łączność"); qs.zew.pack(fill="x")
        r = ttk.Frame(qs, style="Karta.TFrame"); r.pack(fill="x")
        ttk.Label(r, text="Stacja", style="KartaSzary.TLabel").pack(side="left")
        self.var_dx = tk.StringVar()
        e = ttk.Entry(r, textvariable=self.var_dx, width=11, font=(M.MONO, 12, "bold")); e.pack(side="left", padx=6)
        e.bind("<Return>", lambda ev: self.wolaj_wpisana())
        self.ent_dx = e
        ttk.Button(r, text="Wołaj", width=7, command=self.wolaj_wpisana).pack(side="left")
        ttk.Button(r, text="Wyczyść", width=8, command=self.wyczysc).pack(side="right")
        self.lbl_dx = ttk.Label(qs, text="—", style="Karta.TLabel", wraplength=330, justify="left")
        self.lbl_dx.pack(anchor="w", pady=(4, 0))
        self.lbl_rpt = ttk.Label(qs, text="raport nadany —   odebrany —", style="Karta.TLabel", font=(M.MONO, 10))
        self.lbl_rpt.pack(anchor="w", pady=(2, 6))
        self.var_krok = tk.StringVar(value="")
        self.rb = {}
        for k, n in NAZWY_KROKOW:
            b = ttk.Radiobutton(qs, text=n, value=k, variable=self.var_krok, style="Karta.TRadiobutton",
                                command=lambda k=k: self.sekw.ustaw_krok(k))
            b.pack(anchor="w")
            self.rb[k] = (b, n)
        r = ttk.Frame(qs, style="Karta.TFrame"); r.pack(fill="x", pady=(8, 0))
        ttk.Label(r, text="Nadaję na", style="KartaSzary.TLabel").pack(side="left")
        self.var_txhz = tk.StringVar(value=str(c["qo_ft8_tx_hz"]))
        e = ttk.Entry(r, textvariable=self.var_txhz, width=6); e.pack(side="left", padx=6)
        e.bind("<Return>", lambda ev: self._tx_hz_z_pola()); e.bind("<FocusOut>", lambda ev: self._tx_hz_z_pola())
        ttk.Label(r, text="Hz", style="KartaSzary.TLabel").pack(side="left")
        self.lbl_okres = ttk.Label(r, text="", style="KartaSzary.TLabel"); self.lbl_okres.pack(side="right")
        r = ttk.Frame(qs, style="Karta.TFrame"); r.pack(fill="x", pady=(8, 0))
        ttk.Button(r, text="CQ", width=6, style="Akcent.TButton", command=self.cq).pack(side="left")
        self.btn_tx = ttk.Button(r, text="Włącz nadawanie", command=self.przelacz_tx); self.btn_tx.pack(side="left", padx=6,
                                                                                                         fill="x", expand=True)
        # przycisk-lampka jak w zakładce balonu: ciemny w spoczynku, żółty gdy czeka na okno, czerwony gdy radio nadaje
        self.btn_stop = tk.Button(qs, text="STOP  (Esc)", bg="#1b2540", fg=M.SZARY, activebackground="#e53935",
                                  activeforeground="white", relief="flat", bd=0, font=(M.CZC, 13, "bold"), pady=6,
                                  cursor="hand2", command=self.stop)
        self.btn_stop.pack(fill="x", pady=(8, 0))
        self.lbl_powod = ttk.Label(qs, text="", style="KartaSzary.TLabel", wraplength=330, justify="left")
        self.lbl_powod.pack(anchor="w", pady=(4, 0))

        lg = M.karta(prawa, "Log → Log4OM"); lg.zew.pack(fill="x", pady=(10, 0))
        self.var_auto = tk.BooleanVar(value=bool(c["qo_ft8_autolog"]))
        ttk.Checkbutton(lg, text="Zapisuj łączność sam (po RR73 / 73)", variable=self.var_auto, style="Karta.TCheckbutton",
                        command=self._auto_zmiana).pack(anchor="w")
        ttk.Checkbutton(lg, text="Wysyłaj do Log4OM", variable=self.app.var_l4o, style="Karta.TCheckbutton").pack(anchor="w")
        self.btn_log = ttk.Button(lg, text="Zapisz łączność teraz", command=self.zapisz_recznie)
        self.btn_log.pack(fill="x", pady=(6, 4))
        self.lb_log = tk.Listbox(lg, height=6, width=44, font=(M.MONO, 9), bg=M.POLE, fg=M.TEKST, relief="flat",
                                 highlightthickness=1, highlightbackground=M.LINIA, activestyle="none")
        self.lb_log.pack(fill="x")
        ttk.Label(lg, text="Wpis: 13 cm ↑ / 3 cm ↓, SAT, QO-100. Kopia w golbase_log.adi.", style="KartaSzary.TLabel",
                  wraplength=330, justify="left").pack(anchor="w", pady=(4, 0))
        if not self.silnik:
            ttk.Label(f, text="FT8 wyłączone: brak biblioteki ft8shim", foreground=M.CZERWONY).pack(anchor="w", padx=10)

    def _wybor_radia(self, ev=None):
        self.balon.cb_radio.set(self.cb_radio.get())
        self.balon._zapisz_ustawienia()
        self.app.pokaz_civ()

    def okno_ustawien(self):
        c = self.cfg
        w = tk.Toplevel(self.f); w.title("GOLbase – ustawienia FT8 QO-100"); w.transient(self.f.winfo_toplevel())
        w.configure(bg=M.TLO); w.resizable(False, False)
        fr = ttk.Frame(w, padding=14); fr.pack(fill="both", expand=True)
        zm = {k: tk.StringVar(value=str(c[k])) for k in ("qo_lokator", "qo_tx_pwr", "qo_ft8_limit", "qo_ft8_limit_cq",
                                                         "qo_lo_rx_mhz", "qo_lo_tx_mhz", "log4om_udp", "gt_udp")}
        zm_gt = tk.BooleanVar(value=bool(c["gt_send"]))
        wiersze = (("Mój lokator (w eter idą 4 znaki, do logu cały)", "qo_lokator"), ("Moc do logu [W]", "qo_tx_pwr"),
                   ("Wołanie stacji: stop po tylu nadaniach bez odpowiedzi", "qo_ft8_limit"),
                   ("CQ: stop po tylu nadaniach bez odpowiedzi", "qo_ft8_limit_cq"),
                   ("Heterodyna odbioru (LNB) [MHz]", "qo_lo_rx_mhz"), ("Heterodyna nadawania [MHz]", "qo_lo_tx_mhz"),
                   ("Log4OM – adres UDP", "log4om_udp"),
                   ("GridTracker – adres UDP (inny port niż Log4OM)", "gt_udp"))
        for i, (opis, k) in enumerate(wiersze):
            ttk.Label(fr, text=opis, style="Szary.TLabel").grid(row=i, column=0, sticky="w", pady=5, padx=(0, 14))
            ttk.Entry(fr, textvariable=zm[k], width=18).grid(row=i, column=1, sticky="w")
        ttk.Checkbutton(fr, text="Wysyłaj dekody i stan do GridTrackera", variable=zm_gt).grid(
            row=len(wiersze), column=0, columnspan=2, sticky="w", pady=5)
        n = len(wiersze) + 1
        ttk.Label(fr, text=f"Poprawka LNB z kalibracji na beaconie (zakładka CW): {self.app.qo.corr_rx:+.0f} Hz – "
                           "uwzględniana w częstotliwościach wpisu.\nWyjście dźwięku i poziom nadawania są wspólne "
                           "z zakładką „FT8 balon”.", style="Szary.TLabel", justify="left").grid(row=n, column=0, columnspan=2,
                                                                                                  sticky="w", pady=(8, 0))

        def zapisz():
            try:
                lok = zm["qo_lokator"].get().strip().upper()
                if not (len(lok) in (4, 6) and Q._LOK.match(lok[:4])):
                    raise ValueError("lokator ma mieć 4 albo 6 znaków, np. JO91AB")
                lim, lim_cq = int(zm["qo_ft8_limit"].get()), int(zm["qo_ft8_limit_cq"].get())
                if not (1 <= lim <= 20 and 1 <= lim_cq <= 40):
                    raise ValueError("limity nadań: 1–20 (stacja) i 1–40 (CQ)")
                lo_rx, lo_tx = (float(zm[k].get().replace(",", ".")) for k in ("qo_lo_rx_mhz", "qo_lo_tx_mhz"))
                adres = zm["log4om_udp"].get().strip()
                int(adres.rsplit(":", 1)[1])
                adres_gt = zm["gt_udp"].get().strip()
                int(adres_gt.rsplit(":", 1)[1])
                if zm_gt.get() and adres_gt == adres:
                    raise ValueError("GridTracker i Log4OM muszą mieć różne porty (np. 2238 i 2237)")
            except (ValueError, IndexError) as e:
                messagebox.showerror("GOLbase", f"Ustawienia: {e}", parent=w); return
            c.update(qo_lokator=lok, qo_tx_pwr=zm["qo_tx_pwr"].get().strip(), qo_ft8_limit=lim, qo_ft8_limit_cq=lim_cq,
                     qo_lo_rx_mhz=lo_rx, qo_lo_tx_mhz=lo_tx, log4om_udp=adres, gt_udp=adres_gt, gt_send=bool(zm_gt.get()))
            self.app.qo.lo_rx, self.app.qo.lo_tx = round(lo_rx * 1e6), round(lo_tx * 1e6)
            s = self.sekw
            s.lokator, s.limit, s.limit_cq = lok, lim, lim_cq
            self.save_cfg(c)
            w.destroy()

        b = ttk.Frame(fr); b.grid(row=n + 1, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(b, text="Dźwięk nadawania…", command=self.balon.okno_ustawien).pack(side="left", padx=6)
        ttk.Button(b, text="Anuluj", command=w.destroy).pack(side="left", padx=6)
        ttk.Button(b, text="Zapisz", style="Akcent.TButton", command=zapisz).pack(side="left")
        M.ciemna_belka(w)

    def _status(self, txt):
        self.app.status.config(text=txt)

    # ------------------------------------------------------------------ radio i częstotliwości
    def _dial(self):
        """Częstotliwość radia [Hz]: z radia, a gdy niepołączone – z pola kHz."""
        r = self.radio
        if r is not None and r.online and r.freq:
            return int(r.freq)
        return int(round(float(self.cfg["qo_ft8_dial_khz"]) * 1000))

    def _tx_hz(self):
        return float(self.cfg["qo_ft8_tx_hz"])

    def _radio_ok(self, cicho=False):
        r = self.radio
        blad = None
        if r is None:
            blad = "Najpierw „Połącz radio”."
        elif not r.online:
            blad = "Radio nie odpowiada: " + r.stan
        elif not IF_MIN <= r.freq <= IF_MAX:
            blad = (f"Radio jest na {r.freq / 1e6:.4f} MHz – to nie pośrednia QO-100 (29,0–29,5 MHz). "
                    "Kliknij „Ustaw radio (USB-D)”.")
        elif self.balon.wyj_idx is None:
            blad = "Wybierz wyjście dźwięku do radia (⚙ Ustawienia → Dźwięk nadawania…)."
        if blad and not cicho:
            messagebox.showwarning("GOLbase", blad)
        return blad is None

    def ustaw_radio(self):
        try:
            khz = float(self.var_khz.get().replace(",", "."))
        except ValueError:
            messagebox.showerror("GOLbase", "Wpisz częstotliwość radia w kHz, np. 29040."); return
        if not IF_MIN <= khz * 1000 <= IF_MAX:
            messagebox.showerror("GOLbase", "Pośrednia QO-100 to 29 000–29 500 kHz."); return
        self.cfg["qo_ft8_dial_khz"] = khz; self.save_cfg(self.cfg)
        r = self.radio
        if r is None or not r.online:
            messagebox.showwarning("GOLbase", "Najpierw „Połącz radio”." if r is None else "Radio nie odpowiada: " + r.stan)
            return
        try:
            r.set_usb_data()
            time.sleep(0.15)
            r.set_freq(int(round(khz * 1000)))
        except Exception as e:
            messagebox.showerror("GOLbase", f"Radio: {e}")

    def _tx_hz_z_pola(self):
        try:
            hz = int(float(self.var_txhz.get().replace(",", ".")))
        except ValueError:
            hz = int(self.cfg["qo_ft8_tx_hz"])
        hz = max(WF_F0 + 50, min(WF_F1 - 100, hz))
        self.var_txhz.set(str(hz))
        if hz != self.cfg["qo_ft8_tx_hz"]:
            self.cfg["qo_ft8_tx_hz"] = hz; self.save_cfg(self.cfg)

    # ------------------------------------------------------------------ odbiór
    def podaj(self, x):
        """Blok dźwięku 48 kHz z wątku audio programu (tylko gdy zakładka jest otwarta)."""
        if self.okna is not None:
            self.okna.podaj(x)
        self.wf_buf = np.concatenate([self.wf_buf, x])[-WF_FFT:]
        self.wf_ile += len(x)
        if self.wf_ile < WF_KROK or len(self.wf_buf) != WF_FFT:
            return
        self.wf_ile = 0
        w = self.wf.shape[1]
        if self.nadaje:                                # własnego nadawania nie rysujemy i nie psujemy nim poziomów
            wiersz = np.tile(np.array([70, 12, 12], np.uint8), (w, 1))
        else:
            widmo = np.abs(np.fft.rfft(self.wf_buf * WF_OKNO))
            hz = np.fft.rfftfreq(WF_FFT, 1.0 / 48000)
            db = 20 * np.log10(np.interp(np.linspace(WF_F0, WF_F1, w), hz, widmo) + 1e-9)
            szum, szczyt = np.percentile(db, 50) + 3, np.percentile(db, 99.5)
            if self.wf_start:
                self.wf_start, self.wf_lo, self.wf_hi = False, szum, szczyt
            if abs(szum - self.wf_lo) < 15:
                self.wf_lo = self.wf_lo * 0.95 + szum * 0.05
                self.wf_hi = self.wf_hi * 0.95 + szczyt * 0.05
            else:
                self.wf_skok += 1
                if self.wf_skok > 15:
                    self.wf_skok, self.wf_start = 0, True
            self.wf_hi = min(max(self.wf_hi, self.wf_lo + 20), self.wf_lo + 40)
            wiersz = _kolory((db - self.wf_lo) / (self.wf_hi - self.wf_lo))
        okno = int(time.time() // 15)
        if okno != self.wf_okno:
            self.wf_okno = okno
            wiersz = np.maximum(wiersz, np.array([70, 80, 110], np.uint8))
        wf = np.roll(self.wf, 1, axis=0)
        wf[0] = wiersz
        self.wf = wf

    def _wf_rozmiar(self, ev=None):
        w = max(200, self.wf_c.winfo_width() - 2)
        if w == self.wf.shape[1]:
            return
        self.wf = np.zeros((WF_H, w, 3), np.uint8)
        self.wf_img.configure(width=w, height=WF_H)
        self.wf_c.delete("skala")
        for hz in range(500, WF_F1, 500):
            x = (hz - WF_F0) / (WF_F1 - WF_F0) * w
            self.wf_c.create_line(x, WF_SKALA - 5, x, WF_SKALA, fill="#7aa", tags="skala")
            self.wf_c.create_text(x, 6, text=str(hz), fill="#7aa", font=(M.MONO, 7), tags="skala")

    def _wf_klik(self, ev):
        w = self.wf.shape[1]
        self.var_txhz.set(str(int(round((WF_F0 + ev.x / w * (WF_F1 - WF_F0)) / 10.0) * 10)))
        self._tx_hz_z_pola()

    def _wf_rysuj(self):
        wf = self.wf
        h, w = wf.shape[:2]
        self.wf_img.configure(data=b"P6 %d %d 255\n" % (w, h) + wf.tobytes(), format="PPM")
        self.wf_c.delete("znacznik")
        zn = [(self._tx_hz(), "#ff3b3b", "TX")]
        if self.sekw.dx and self.sekw.dx_hz:
            zn.append((self.sekw.dx_hz, M.NIEBIESKI, self.sekw.dx))
        for hz, kolor, opis in zn:
            x = (float(hz) - WF_F0) / (WF_F1 - WF_F0) * w
            self.wf_c.create_line(x, WF_SKALA, x, WF_SKALA + 14, fill=kolor, width=2, tags="znacznik")
            self.wf_c.create_line(x + 50 / (WF_F1 - WF_F0) * w, WF_SKALA, x + 50 / (WF_F1 - WF_F0) * w, WF_SKALA + 6,
                                  fill=kolor, tags="znacznik")           # szerokość sygnału FT8 (50 Hz)
            self.wf_c.create_text(x + 4, WF_SKALA + 9, text=opis, fill=kolor, anchor="w", font=(M.CZC, 7, "bold"),
                                  tags="znacznik")

    def _watek_dekodera(self):
        while self.alive:
            time.sleep(0.05)
            if self.okna is None or not self.aktywna:
                continue
            g = self.okna.gotowe()
            if not g:
                continue
            pocz, probki = g
            if pocz in self.okna_tx:
                self.okno_przetw = pocz
                continue
            try:
                dek = self.silnik.dekoduj(probki)
            except Exception as e:
                self.okno_przetw = pocz
                self.q_gui.put(("status", f"FT8: błąd dekodera: {e}"))
                continue
            try:                                   # raporty jak w JTDX (patrz CZYTAJ.md, „Od wersji 1.14”)
                poprawka = float(self.cfg["qo_ft8_snr_poprawka_db"])
            except (TypeError, ValueError):
                poprawka = 0.0
            for d in dek:
                d.snr += poprawka
            # automat od razu w tym wątku – żeby zdążyć z odpowiedzią przed początkiem następnego okna
            self.sekw.moj = self.cfg["my_call"].upper()
            self.sekw.odebrano(pocz, [(None if d.telemetria else Q.rozbierz(d.tekst), d.snr, d.hz) for d in dek])
            self.okno_przetw = pocz
            self.q_gui.put(("dekody", pocz, dek))
            self._sprawdz_log()

    def _przyjmij(self, pocz, dekody):
        moj, s = self.cfg["my_call"].upper(), self.sekw
        self.okno_info = (pocz, len(dekody))
        if dekody:
            self.lista.insert("", "end", values=(hhmmss(pocz), "", "", "", f"──── {len(dekody)} ────", ""), tags=("okno",))
        dts = []
        if dekody and self.cfg["gt_send"]:
            self.gt.wyslij(self.cfg["gt_udp"], *[wsjtx_udp.dekod(pocz, d.snr, d.dt - 0.5, d.hz, d.tekst) for d in dekody])
        for d in dekody:
            dts.append(d.dt - 0.5)
            p = None if d.telemetria else Q.rozbierz(d.tekst)
            tag, kraj = "zwykly", ""
            if p:
                self.slyszane[p["od"]] = (pocz, d.snr, d.hz, p["lok"] or self.slyszane.get(p["od"], (0, 0, 0, ""))[3])
                if p["do"] == moj:
                    tag = "moje"
                elif s.dx and s.dx in (p["od"], p["do"]):
                    tag = "dx"
                elif p["cq"]:
                    tag = "cq_stare" if p["od"] in self.zrobione else "cq"
                if p["cq"] or p["do"] == moj:
                    kraj = self._kraj(p["od"])
            iid = self.lista.insert("", "end", values=(hhmmss(pocz), f"{d.snr:+.0f}", f"{d.dt - 0.5:+.1f}", f"{d.hz:.0f}",
                                                       d.tekst, kraj), tags=(tag,))
            if p:
                self.wiersze[iid] = (pocz, d.tekst, d.snr, d.hz)
        dzieci = self.lista.get_children()
        if len(dzieci) > 600:
            for iid in dzieci[:len(dzieci) - 600]:
                self.wiersze.pop(iid, None)
            self.lista.delete(*dzieci[:len(dzieci) - 600])
        if len(self.slyszane) > 400:
            for z, _ in sorted(self.slyszane.items(), key=lambda kv: kv[1][0])[:200]:
                self.slyszane.pop(z, None)
        self.lista.yview_moveto(1.0)
        if dts:
            self.dt_sr = float(np.median(dts))

    def _kraj(self, znak):
        try:
            return self.app.kraje.describe(znak, self.cfg["my_call"])
        except Exception:
            return ""

    # ------------------------------------------------------------------ polecenia operatora
    def _dwuklik(self, ev):
        iid = self.lista.identify_row(ev.y)
        w = self.wiersze.get(iid)
        if not w:
            return
        pocz, tekst, snr, hz = w
        self.sekw.moj = self.cfg["my_call"].upper()
        if not self._radio_ok():
            return
        if self.sekw.wolaj(Q.rozbierz(tekst), pocz, snr, hz):
            self.stop_evt.clear()
            self._sprawdz_log()

    def wolaj_wpisana(self):
        znak = self.var_dx.get().strip().upper()
        if not Q.znak_ok(znak):
            messagebox.showwarning("GOLbase", "Wpisz znak stacji."); return
        if znak == self.sekw.dx:                       # ta sama stacja – tylko włącz nadawanie
            self.przelacz_tx(wlacz=True); return
        if not self._radio_ok():
            return
        o = self.slyszane.get(znak)
        self.sekw.moj = self.cfg["my_call"].upper()
        if o:
            self.sekw.wolaj_znak(znak, o[0], o[1], o[2])
            self.sekw.dx_lok = o[3]
        else:
            self.sekw.wolaj_znak(znak)
        self.stop_evt.clear()

    def cq(self):
        if not self._radio_ok():
            return
        self.sekw.moj = self.cfg["my_call"].upper()
        self.sekw.cq()
        self.stop_evt.clear()

    def przelacz_tx(self, wlacz=None):
        s = self.sekw
        wlacz = (not s.tx) if wlacz is None else wlacz
        if not wlacz:
            self.stop(); return
        if not s.tekst():
            messagebox.showinfo("GOLbase", "Nie ma czego nadawać – kliknij dwa razy w stację na liście albo „CQ”."); return
        if not self._radio_ok():
            return
        with s.blokada:
            s.tx, s.ile, s.powod = True, 0, ""
        self.stop_evt.clear()

    def wyczysc(self):
        self.stop()
        self.sekw.wyczysc()
        self.var_dx.set("")

    def stop(self):
        """Natychmiast przerywa nadawanie (Esc)."""
        self.stop_evt.set()
        self.sekw.stop()
        if self.nadaje:
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

    def ustaw_aktywna(self, tak):
        """Woła główne okno przy zmianie zakładki; po wyjściu z zakładki nadawanie się wyłącza."""
        if self.aktywna and not tak:
            self.stop()
        if tak and not self.aktywna and self.okna is not None:
            self.okna = F.Okna()                       # stary dźwięk sprzed przerwy nie jest nic wart
        self.aktywna = tak

    # ------------------------------------------------------------------ nadawanie
    def _watek_nadawania(self):
        while self.alive:
            time.sleep(0.02)
            s = self.sekw
            if not s.tx or not self.aktywna or self.stop_evt.is_set():
                continue
            t = time.time()
            nr = int(t // 15)
            if nr % 2 == s.parz and t - nr * 15 <= self._spoznienie_max() and nr * 15 not in self.okna_tx:
                pocz = nr * 15                         # nasze okno już trwa – zaczynamy od razu, od bieżącego miejsca komunikatu
            elif (nr + 1) % 2 == s.parz and (nr + 1) * 15 - t <= 0.5:
                pocz = (nr + 1) * 15
            else:
                continue
            try:
                self._nadaj(pocz)
            except Exception as e:
                s.stop(str(e))
                self.q_gui.put(("status", f"FT8 QO-100 nadawanie: {e}"))
            finally:
                if self.nadaje:
                    self.nadaje = False
                    try:
                        self.sd.stop()
                    except Exception:
                        pass
                    try:
                        if self.radio:
                            self.radio.ptt(False)
                    except Exception:
                        pass

    def _spoznienie_max(self):
        try:
            return max(0.5, min(SPOZNIENIE_MAX, float(self.cfg["qo_ft8_spoznienie_s"])))
        except (TypeError, ValueError):
            return 4.0

    def _czekaj_do(self, t):
        while time.time() < t:
            if self.stop_evt.is_set() or not self.alive or not self.aktywna:
                return False
            time.sleep(min(0.01, max(0.0, t - time.time())))
        return True

    def _nadaj(self, pocz):
        s = self.sekw
        if self.sd is None or not self.silnik:
            raise RuntimeError("brak biblioteki dźwięku albo silnika FT8")
        if not self._radio_ok(cicho=True):
            raise RuntimeError("radio niepołączone, poza pośrednią 29,0–29,5 MHz albo brak wyjścia dźwięku – nie nadaję")
        # poczekaj, aż automat zobaczy dekody poprzedniego okna (zwykle ok. 1 s przed końcem okna), najdłużej do −0,25 s
        while time.time() < pocz - 0.25 and self.okno_przetw < pocz - 15:
            if self.stop_evt.is_set() or not self.alive:
                return
            time.sleep(0.01)
        with s.blokada:
            if not s.tx or okres(pocz) != s.parz:
                return
            tekst = s.tekst()
        if not tekst:
            s.stop()
            return
        hz = self._tx_hz()
        sygnal = F.synteza(self.silnik.tony(self.silnik.pakuj_tekst(tekst)), hz, poziom=float(self.cfg["ft8_tx_poziom"]))
        if not self._czekaj_do(pocz - 0.15):
            return
        self.nadaje = True
        self.okna_tx.add(pocz)
        if not self.radio.ptt(True):
            raise RuntimeError("radio nie przyjęło polecenia nadawania")
        if not self._czekaj_do(max(pocz, time.time() + 0.15)):     # radio ma 0,15 s na przejście na nadawanie
            return
        dzwiek, ucieto = Q.dzwiek_okna(sygnal, time.time() - pocz, F.FS_AUDIO)
        if ucieto > 0.05:
            tekst_listy = f"{tekst}   (start {ucieto + 0.5:.1f} s po początku okna)"
        else:
            tekst_listy = tekst
        self.q_gui.put(("tx", pocz, hz, tekst_listy))
        self.sd.play(dzwiek, F.FS_AUDIO, device=self.balon.wyj_idx)
        cale = self._czekaj_do(time.time() + len(dzwiek) / F.FS_AUDIO + 0.15)
        self.sd.stop()
        self.radio.ptt(False)
        self.nadaje = False
        if cale:
            s.nadano()
            self._sprawdz_log()
        if len(self.okna_tx) > 50:
            self.okna_tx = set(sorted(self.okna_tx)[-20:])

    # ------------------------------------------------------------------ log
    def _wczytaj_zrobione(self):
        """Znaki stacji, z którymi jest już łączność FT8 przez QO-100 w golbase_log.adi (do przyciemniania CQ)."""
        zn = set()
        try:
            with open(self.plik_logu, encoding="utf-8") as f:
                for linia in f:
                    g = linia.upper()
                    if "<MODE:3>FT8" in g and "QO-100" in g and "<CALL:" in g:
                        i = g.index("<CALL:")
                        n = int(g[i + 6:g.index(">", i)])
                        k = g.index(">", i) + 1
                        zn.add(g[k:k + n])
        except (OSError, ValueError):
            pass
        return zn

    def _sprawdz_log(self):
        q = self.sekw.wez_log()
        if q:
            q["tx_hz"], q["dial"] = self._tx_hz(), self._dial()
            self.q_gui.put(("log", q))

    def _auto_zmiana(self):
        self.cfg["qo_ft8_autolog"] = self.var_auto.get(); self.save_cfg(self.cfg)

    def zapisz_recznie(self):
        q = self.czeka_log or self.sekw.biezaca()
        if not q:
            messagebox.showinfo("GOLbase", "Nie ma łączności do zapisania."); return
        if not q["rpt_n"] or not q["rpt_o"]:
            if not messagebox.askyesno("GOLbase", f"Łączność z {q['znak']} nie ma kompletu raportów (nadany "
                                                 f"{q['rpt_n'] or '—'}, odebrany {q['rpt_o'] or '—'}). Zapisać mimo to?"):
                return
        q.setdefault("tx_hz", self._tx_hz()); q.setdefault("dial", self._dial())
        if self.czeka_log is None:
            self.sekw.oznacz_zapisana()
        self._zapisz(q)

    def _zapisz(self, q):
        """Zapis łączności: plik ADIF + Log4OM (wątek okna)."""
        c = self.cfg
        self.czeka_log = None
        rx_if = q["dial"] + (q.get("dx_hz") or q["tx_hz"])
        f = Q.pola_adif(q, c["my_call"].upper(), c["qo_lokator"], q["dial"] + q["tx_hz"], rx_if, self.app.qo, c["qo_tx_pwr"],
                        logbook.band_of)
        rec = logbook.adif_record(f)
        gdzie = "plik"
        try:
            logbook.append_adi(self.plik_logu, rec)
        except Exception as e:
            messagebox.showerror("GOLbase", f"Nie mogę zapisać {self.plik_logu}:\n{e}"); return
        if self.app.var_l4o.get():
            try:
                logbook.send_log4om(rec, c["log4om_udp"])
                gdzie = "Log4OM"
            except Exception as e:
                gdzie = f"plik (Log4OM: błąd {e})"
        c["log4om_send"] = self.app.var_l4o.get(); self.save_cfg(c)
        self.zrobione.add(q["znak"])
        godz = time.strftime("%H:%M", time.gmtime(q["t_off"]))
        self.lb_log.insert(0, f"{godz} {q['znak']:<10} {f['rst_sent'] or '—'}/{f['rst_rcvd'] or '—'} {q.get('lok', ''):<4} → {gdzie}")
        self.lista.insert("", "end", values=(hhmmss(q["t_off"]), "", "", "", f"ZAPISANE → {gdzie}: {q['znak']} "
                                             f"{f['rst_sent'] or '—'}/{f['rst_rcvd'] or '—'}", "13 cm ↑ / 3 cm ↓ SAT"), tags=("log",))
        self.lista.yview_moveto(1.0)
        self._status(f"Log: {q['znak']} FT8 QO-100, ↑ {f['freq']} MHz ({f['band']}), ↓ {f['freq_rx']} MHz ({f['band_rx']}) → {gdzie}")

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
                    self.lista.insert("", "end", values=(hhmmss(z[1]), "TX", "", f"{z[2]:.0f}", z[3], ""), tags=("tx",))
                    self.lista.yview_moveto(1.0)
                elif z[0] == "status":
                    self._status(z[1])
                elif z[0] == "log":
                    if self.var_auto.get():
                        self._zapisz(z[1])
                    else:
                        if self.czeka_log:             # poprzednia niezapisana – nie może przepaść
                            self._zapisz(self.czeka_log)
                        self.czeka_log = z[1]
        except queue.Empty:
            pass
        if not self.aktywna:                           # zakładka schowana – nic nie odświeżamy
            self.f.after(300, self._tyk)
            return
        t = time.time()
        s, c = self.sekw, self.cfg
        self.pasek["value"] = t % 15
        self.lbl_zegar.config(text=f"{hhmmss(t)} UTC")
        if self.okno_info:
            zle = self.dt_sr is not None and abs(self.dt_sr - DROGA_SAT) > 0.8
            dt = "" if self.dt_sr is None else (f" · DT {self.dt_sr:+.1f} s (satelita +0,3)"
                                                + (" – sprawdź zegar komputera!" if zle else ""))
            self.lbl_dt.config(text=f"okno {hhmmss(self.okno_info[0])}: {self.okno_info[1]} dekodów{dt}",
                               foreground=M.CZERWONY if zle else M.SZARY)
        # radio wspólne z zakładką balonu – pokazujemy jej wybór i stan
        if self.cb_radio.get() != self.balon.cb_radio.get():
            self.cb_radio.set(self.balon.cb_radio.get())
        if self.btn_radio.cget("text") != self.balon.btn_radio.cget("text"):
            self.btn_radio.config(text=self.balon.btn_radio.cget("text"))
        r = self.radio
        dial = self._dial()
        if r is None:
            self.lbl_radio.config(text="radio niepołączone – wybierz i „Połącz radio”", foreground=M.SZARY)
            self.app.lbl_freq.config(text="  —")
        elif r.online:
            dobrze = IF_MIN <= r.freq <= IF_MAX
            self.lbl_radio.config(text="radio połączone" if dobrze else f"radio na {r.freq / 1e3:,.1f} kHz – to nie pośrednia QO-100!"
                                  .replace(",", " "), foreground=M.ZIELONY if dobrze else M.CZERWONY)
            self.app.lbl_freq.config(text=(f"↓{self.app.qo.downlink(r.freq) / 1e6:,.5f} MHz  {r.mode or ''}" if dobrze
                                           else f"{r.freq / 1e6:,.5f} MHz  {r.mode or ''}").replace(",", " "))
        else:
            self.lbl_radio.config(text=r.stan, foreground=M.CZERWONY)
            self.app.lbl_freq.config(text="  —")
        if IF_MIN <= dial <= IF_MAX:
            jf = dial + self._tx_hz()
            self.lbl_qo.config(text=f"nadaję ↑ {qo100.khz(self.app.qo.uplink(jf))}   słychać mnie ↓ {qo100.khz(self.app.qo.downlink(jf))}")
        else:
            self.lbl_qo.config(text="")
        # łączność
        if self.app.focus_get_safe() is not self.ent_dx and self.var_dx.get() != s.dx:
            self.var_dx.set(s.dx)                      # pola nie ruszamy, gdy operator właśnie w nim pisze
        if s.dx:
            self.lbl_dx.config(text=" · ".join(x for x in (s.dx_lok, self._kraj(s.dx),
                                                           "już w logu" if s.dx in self.zrobione and not s.zapisana else "") if x) or "—")
        else:
            self.lbl_dx.config(text="—")
        self.lbl_rpt.config(text=f"raport nadany {s.rpt_n or '—'}   odebrany {s.rpt_o or '—'}"
                                 + ("   ✔ zapisana" if s.zapisana else ""))
        if self.var_krok.get() != (s.krok or ""):
            self.var_krok.set(s.krok or "")
        for k, (b, n) in self.rb.items():
            txt = s.tekst(k)
            b.config(text=f"{n:<14} {txt or ''}", state="normal" if txt else "disabled")
        self.lbl_okres.config(text=f"okna :{'15 i :45' if s.parz else '00 i :30'}" if (s.tx or s.dx) else "")
        self.btn_tx.config(text="Wyłącz nadawanie" if s.tx else "Włącz nadawanie")
        if self.nadaje:
            lampka = ("●  NADAJĘ  –  STOP (Esc)", "#ff1f1f", "white")
        elif s.tx:
            lampka = ("czeka na okno  –  STOP (Esc)", "#e0a800", "#141414")
        else:
            lampka = ("STOP  (Esc)", "#1b2540", M.SZARY)
        if self.btn_stop.cget("text") != lampka[0]:
            self.btn_stop.config(text=lampka[0], bg=lampka[1], fg=lampka[2])
        self.lbl_powod.config(text=s.powod)
        q = self.czeka_log
        self.btn_log.config(text=f"Zapisz łączność z {q['znak']}" if q else "Zapisz łączność teraz",
                            style="Akcent.TButton" if q else "TButton")
        self._gt_stan(t, dial)
        self._wf_rysuj()
        self.f.after(100, self._tyk)

    def _gt_stan(self, t, dial):
        """GridTracker: „żyję” co 15 s, stan przy każdej zmianie i co 5 s. Częstotliwość wg ustawienia gt_pasmo."""
        c, s = self.cfg, self.sekw
        if not c["gt_send"]:
            return
        paczki = []
        if t - self.gt_t_zyje >= 15:
            self.gt_t_zyje = t
            paczki.append(wsjtx_udp.zyje(getattr(self.app, "wersja", "")))
        if not IF_MIN <= dial <= IF_MAX:
            hz = dial
        elif str(c["gt_pasmo"]).lower() == "downlink":
            hz = self.app.qo.downlink(dial)
        else:                                      # 13 cm – GridTracker porównuje z logiem po paśmie, a w logu jest 13cm
            hz = self.app.qo.uplink(dial)
        stan = (int(hz), s.dx, s.dx_lok, s.rpt_n or "", bool(s.tx), bool(self.nadaje), int(s.dx_hz or self._tx_hz()),
                int(self._tx_hz()), (s.tekst() or "") if s.tx else "", c["my_call"].upper(), c["qo_lokator"])
        if stan != self.gt_stan or t - self.gt_t_stan >= 5:
            self.gt_stan, self.gt_t_stan = stan, t
            paczki.append(wsjtx_udp.stan(stan[0], stan[9], stan[10], dx=stan[1], dx_lok=stan[2], raport=stan[3],
                                         tx_wlaczone=stan[4], nadaje=stan[5], rx_df=stan[6], tx_df=stan[7], tx_tekst=stan[8]))
        if paczki:
            self.gt.wyslij(c["gt_udp"], *paczki)

    def zamknij(self):
        self.alive = False
        self.stop_evt.set()
        if self.cfg.get("gt_send"):
            self.gt.wyslij(self.cfg["gt_udp"], wsjtx_udp.koniec())
        self.gt.zamknij()


def okres(pocz):
    return Q.okres(pocz)


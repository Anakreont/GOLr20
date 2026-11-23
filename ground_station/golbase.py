"""
GOLbase – dekodowanie i nadawanie CW z IC-7300 + zakładki „FT8 balon” (od wersji 1.5, ft8_tab.py)
         i „FT8 QO-100” (od wersji 1.10, ft8_qo_tab.py)

Odbiór: dźwięk z karty "USB Audio CODEC" radia -> wodospad + dekoder (tryb normalny lub "odwrócony"
        dla CW startowego trackerów ICT).
Nadawanie: tekst wysyłany przez CI-V (komenda 0x17) – kluczuje wbudowany klucz radia, więc nie trzeba
        żadnego dodatkowego kabla. Radio musi być w emisji CW z włączonym BK-IN (semi lub full).

QO-100: przy transwerterze 29 MHz program pokazuje prawdziwe częstotliwości downlinku (10 489 MHz) i uplinku
        (2400 MHz), kalibruje błąd LNB na beaconie CW i ustawia ΔTX, żeby nadawać tam, gdzie słychać stację.

Uruchomienie: run.bat (Windows) albo:  python golbase.py
"""
import json, os, queue, sys, threading, time, tkinter as tk
from tkinter import ttk, messagebox

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cw_decoder import CWDecoder  # noqa: E402
import qo100  # noqa: E402
import logbook  # noqa: E402
import kraje  # noqa: E402
import ft8_tab  # noqa: E402
import ft8_qo_tab  # noqa: E402
import motyw  # noqa: E402
from cw_decoder import TEXT2MORSE  # noqa: E402

try:
    import sounddevice as sd
except Exception as e:  # pragma: no cover
    sd = None
    SD_ERR = str(e)
try:
    import serial.tools.list_ports as list_ports
    from civ import IC7300
except Exception as e:  # pragma: no cover
    list_ports = None
    SER_ERR = str(e)
    CW_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/?.,-=+@: '()!^")
else:
    from civ import CW_CHARS

VERSION = "1.16"
# zainstalowany program (exe): ustawienia, logi i nagrania w Dokumenty\GOLbase; uruchomiony ze skryptu: obok skryptu
if getattr(sys, "frozen", False):
    try:                                  # prawdziwy folder Dokumenty (także przeniesiony na OneDrive)
        import ctypes
        _b = ctypes.create_unicode_buffer(260)
        ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, _b)
        DATA_DIR = os.path.join(_b.value, "GOLbase")
    except Exception:
        DATA_DIR = os.path.join(os.path.expanduser("~"), "Documents", "GOLbase")
else:
    DATA_DIR = os.path.dirname(os.path.abspath(__file__))
os.makedirs(DATA_DIR, exist_ok=True)
LOG_ADI = "golbase_log.adi"
CFG_PATH = os.path.join(DATA_DIR, "golbase.json")
DEFAULT_CFG = {
    "audio": "", "port": "", "baud": 115200, "civ_addr": "94", "wpm": 20, "inverted": False, "afc": True,
    "squelch_db": 6,
    "qo100": False, "qo_lo_rx_mhz": 10460.5, "qo_lo_tx_mhz": 2371.0, "qo_beacon_mhz": 10489.5,
    "qo_corr_rx_hz": 0.0, "qo_corr_tx_hz": 0.0, "qo_cal_time": "", "pitch_hz": 600,
    "log4om_udp": "127.0.0.1:2237", "log4om_send": False, "qo_tx_pwr": "3",
    "macros": {
        "F1 CQ": "CQ CQ CQ DE {MY} {MY} {MY} K",
        "F2 Raport": "{CALL} DE {MY} TNX FER CALL UR RST 599 599 NAME MYNAME QTH MYQTH HW? {CALL} DE {MY} K",
        "F3 73": "{CALL} DE {MY} TNX QSO 73 GL <SK>",
        "F4 Znak": "{MY}",
        "F5 QRZ?": "QRZ? DE {MY} K",
    },
    "my_call": "N0CALL",
    "my_lat": 52.0, "my_lon": 19.0,       # do azymutu i odległości (z cty.dat)
    "cty_auto": True,                       # raz w miesiącu pobierz świeży cty.dat (country-files.com)
}
MAX_MACROS = 8
APP_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
HELP_MACROS = ("{MY} – mój znak   {CALL} – jego znak   {RST} – RST nadany   {NAME} – jego imię\n"
               "<SK> <AR> <BT> <KN> – znaki łączone.  Pusta nazwa albo treść = przycisk ukryty.")
FS = 48000
WF_W, WF_H = 560, 140
FMIN, FMAX = 200, 1500


def load_cfg():
    cfg = json.loads(json.dumps(DEFAULT_CFG))
    try:
        with open(CFG_PATH, encoding="utf-8") as f:
            user = json.load(f)
        macros = user.pop("macros", None)
        cfg.update(user)
        if macros:
            cfg["macros"] = macros
    except Exception:
        pass
    return cfg


def save_cfg(cfg):
    try:
        with open(CFG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def colormap(v):
    """0..1 -> RGB (ciemny granat -> turkus -> żółty -> biały)."""
    stops = np.array([[0, 0, 20], [0, 60, 120], [0, 200, 220], [255, 230, 0], [255, 255, 255]], float)
    x = np.clip(v, 0, 1) * (len(stops) - 1)
    i = np.minimum(x.astype(int), len(stops) - 2)
    t = (x - i)[..., None]
    return (stops[i] * (1 - t) + stops[i + 1] * t).astype(np.uint8)


class App:
    def __init__(self, root):
        self.root = root
        motyw.zastosuj(root)
        self.cfg = load_cfg()
        self.q_text = queue.Queue()
        self.q_audio = queue.Queue(maxsize=200)
        self.dec = CWDecoder(FS, on_text=self.q_text.put)
        self.dec.inverted = self.cfg["inverted"]
        self.dec.afc = self.cfg["afc"]
        self.dec.squelch_db = float(self.cfg["squelch_db"])
        c = self.cfg
        self.qo = qo100.QO100(round(c["qo_lo_rx_mhz"] * 1e6), round(c["qo_lo_tx_mhz"] * 1e6),
                              round(c["qo_beacon_mhz"] * 1e6), c["qo_corr_rx_hz"], c["qo_corr_tx_hz"])
        self.ring = np.zeros(0, np.float32)     # ostatnie 2 s dźwięku – dokładny pomiar tonu
        self.stream = None
        self.radio = None
        self.wf = np.zeros((WF_H, WF_W, 3), np.uint8)
        self.wf_lo, self.wf_hi = -80.0, -20.0
        self.last_audio = np.zeros(4096, np.float32)
        self.running = True
        self.rec = None                 # nagrywanie WAV: lista bloków albo None
        self.rec_until = 0
        self.clip = 0.0
        self.kraje = kraje.Kraje(DATA_DIR, APP_DIR, float(self.cfg["my_lat"]), float(self.cfg["my_lon"]))
        if self.cfg["cty_auto"]:
            self.kraje.update_async(on_done=lambda src: self.root.after(0, self._cty_updated, src))
        self.tx_msgs = {}               # id komunikatu -> (znacznik w polu Odebrane, długość tekstu)
        self.tx_next = 1
        self.tx_last = None
        self.ft8 = None
        self.qo_tab = None
        self.wersja = VERSION
        self.zakladka = 0               # 0 = CW, 1 = FT8 balon, 2 = FT8 QO-100
        self.cw_aktywne = True          # dekoder CW pracuje tylko przy otwartej zakładce CW
        self._build()
        self._fill_devices()
        threading.Thread(target=self._dsp_loop, daemon=True).start()
        self.root.after(50, self._tick)
        self.root.protocol("WM_DELETE_WINDOW", self._quit)
        if self.cfg["audio"]:
            self.root.after(300, self.start_audio)
        if self.cfg["port"] and self.cfg.get("civ_auto", True):      # po „Rozłącz” program nie łączy CI-V sam
            self.root.after(600, self.connect_radio)

    # ------------------------------------------------------------------ interfejs
    def _build(self):
        r = self.root
        r.title(f"GOLbase {VERSION} – {self.cfg['my_call']}")
        try:
            r.iconbitmap(os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "ikona.ico"))
        except Exception:
            pass
        r.geometry("1400x900")
        top = ttk.Frame(r, padding=4); top.pack(fill="x")
        ttk.Label(top, text="Wejście audio:").pack(side="left")
        self.cb_audio = ttk.Combobox(top, width=38, state="readonly"); self.cb_audio.pack(side="left", padx=3)
        ttk.Button(top, text="Start odbioru", command=self.start_audio).pack(side="left")
        # CI-V jest potrzebne zakładce CW (i FT8 tylko przy „CI-V wprost”) – przy OmniRig chowamy je, żeby nie myliło
        self.civ_fr = ttk.Frame(top); self.civ_fr.pack(side="left")
        ttk.Label(self.civ_fr, text="   CI-V (IC-7300):").pack(side="left")
        self.cb_port = ttk.Combobox(self.civ_fr, width=22, state="readonly"); self.cb_port.pack(side="left", padx=3)
        self.btn_civ = ttk.Button(self.civ_fr, text="Połącz", width=8, command=self._civ_button); self.btn_civ.pack(side="left")
        ttk.Button(self.civ_fr, text="↻", width=3, command=self._fill_devices).pack(side="left", padx=2)
        self.lbl_freq = ttk.Label(top, text="  —", style="Duzy.TLabel"); self.lbl_freq.pack(side="right", padx=8)
        self.status = ttk.Label(r, text="", style="Status.TLabel", anchor="w"); self.status.pack(fill="x", side="bottom")
        # zakładki: CW (jak w 1.4), FT8 balon i FT8 QO-100; wspólne: audio, CI-V i pasek stanu
        self.nb = ttk.Notebook(r); self.nb.pack(fill="both", expand=True)
        cw = ttk.Frame(self.nb); self.nb.add(cw, text="  CW  ")
        f8 = ttk.Frame(self.nb); self.nb.add(f8, text="  FT8 balon  ")
        fq = ttk.Frame(self.nb); self.nb.add(fq, text="  FT8 QO-100  ")

        # wodospad
        mid = ttk.Frame(cw, padding=(4, 0)); mid.pack(fill="x")
        self.canvas = tk.Canvas(mid, width=WF_W, height=WF_H + 16, bg="#000014", highlightthickness=0)
        self.canvas.pack(side="left")
        self.canvas.bind("<Button-1>", self._wf_click)
        self.img = tk.PhotoImage(width=WF_W, height=WF_H)
        self.canvas.create_image(0, 16, image=self.img, anchor="nw")
        for f in range(300, FMAX + 1, 200):
            x = (f - FMIN) / (FMAX - FMIN) * WF_W
            self.canvas.create_line(x, 10, x, 16, fill="#7aa")
            self.canvas.create_text(x, 5, text=str(f), fill="#7aa", font=("Consolas", 7))
        self.marker = self.canvas.create_line(0, 0, 0, WF_H + 16, fill="#f33", width=2)

        side = ttk.Frame(mid, padding=(8, 0)); side.pack(side="left", fill="both", expand=True)
        self.var_inv = tk.BooleanVar(value=self.cfg["inverted"])
        ttk.Checkbutton(side, text="Tryb odwrócony (CW trackera ICT)", variable=self.var_inv,
                        command=self._opts).pack(anchor="w")
        self.var_afc = tk.BooleanVar(value=self.cfg["afc"])
        ttk.Checkbutton(side, text="AFC – sam szuka tonu", variable=self.var_afc, command=self._opts).pack(anchor="w")
        ttk.Label(side, text="Blokada szumu (dB):").pack(anchor="w", pady=(6, 0))
        self.var_sq = tk.DoubleVar(value=self.cfg["squelch_db"])
        ttk.Scale(side, from_=2, to=20, variable=self.var_sq, command=lambda e: self._opts()).pack(fill="x")
        self.lbl_stat = ttk.Label(side, text="ton — Hz | — WPM | SNR —", font=("Consolas", 10))
        self.lbl_stat.pack(anchor="w", pady=(6, 0))
        self.led = tk.Canvas(side, width=18, height=18, highlightthickness=0); self.led.pack(anchor="w", pady=4)
        self.led_id = self.led.create_oval(2, 2, 16, 16, fill="#333")
        ttk.Label(side, text="Kliknij w wodospad, żeby wybrać sygnał.", foreground=motyw.SZARY).pack(anchor="w")

        # QO-100
        qf = ttk.LabelFrame(side, text="QO-100", padding=3); qf.pack(fill="x", pady=(4, 0))
        self.var_qo = tk.BooleanVar(value=self.cfg["qo100"])
        ttk.Checkbutton(qf, text="Transwerter QO-100 (pośrednia 29 MHz)", variable=self.var_qo,
                        command=self._qo_toggle).pack(anchor="w")
        self.lbl_qo = ttk.Label(qf, text="", font=("Consolas", 10), cursor="hand2")
        self.lbl_qo.pack(anchor="w")
        self.lbl_qo.bind("<Button-1>", self._qo_copy)
        self.lbl_qocal = ttk.Label(qf, text="", foreground=motyw.SZARY, wraplength=320); self.lbl_qocal.pack(anchor="w")
        qb = ttk.Frame(qf); qb.pack(fill="x")
        ttk.Button(qb, text="Kalibruj (beacon)", command=self._qo_cal).pack(side="left")
        ttk.Button(qb, text="Dostrój", command=self._qo_tune).pack(side="left", padx=3)
        ttk.Button(qb, text="ΔTX", width=5, command=self._qo_xit).pack(side="left")

        # tekst odebrany
        rx = ttk.LabelFrame(cw, text="Odebrane", padding=4); rx.pack(fill="both", expand=True, padx=4, pady=4)
        self.txt = tk.Text(rx, height=6, font=("Consolas", 13), wrap="word", bg=motyw.POLE, fg=motyw.TEKST, insertbackground=motyw.TEKST, relief="flat", padx=6, pady=4)
        self.txt.pack(fill="both", expand=True, side="left")
        sb = ttk.Scrollbar(rx, command=self.txt.yview); sb.pack(side="right", fill="y")
        self.txt.config(yscrollcommand=sb.set)
        self.txt.tag_config("tx", foreground=motyw.CZERWONY)
        self.txt.tag_config("txdone", foreground="#5d6880")
        self.txt.tag_config("txcur", background="#ffd84d", foreground="#000", font=("Consolas", 13, "bold"))
        bt = ttk.Frame(cw, padding=(4, 0)); bt.pack(fill="x")
        ttk.Button(bt, text="Wyczyść", command=self._clear).pack(side="left")
        ttk.Button(bt, text="Zapisz log", command=self._save_log).pack(side="left", padx=4)
        ttk.Button(bt, text="Nagraj 60 s (WAV)", command=self._rec_start).pack(side="left", padx=4)
        self.lbl_clip = ttk.Label(bt, text="", foreground=motyw.CZERWONY, font=("Segoe UI", 10, "bold"))
        self.lbl_clip.pack(side="left", padx=10)

        # nadawanie
        tx = ttk.LabelFrame(cw, text="Nadawanie (Enter = nadaj, Esc = stop)", padding=4)
        tx.pack(fill="x", padx=4, pady=4)
        row = ttk.Frame(tx); row.pack(fill="x")
        ttk.Label(row, text="Jego znak:").pack(side="left")
        self.var_call = tk.StringVar()
        ttk.Entry(row, textvariable=self.var_call, width=12).pack(side="left", padx=3)
        self.lbl_cty = ttk.Label(row, text="", foreground=motyw.NIEBIESKI, font=("Segoe UI", 10, "bold"))
        self.lbl_cty.pack(side="left", padx=(2, 8))
        ttk.Label(row, text="  WPM:").pack(side="left")
        self.var_wpm = tk.IntVar(value=self.cfg["wpm"])
        sp = ttk.Spinbox(row, from_=6, to=48, textvariable=self.var_wpm, width=4, command=self._wpm)
        sp.pack(side="left"); sp.bind("<Return>", lambda e: self._wpm()); self.sp_wpm = sp
        self.lbl_tx = ttk.Label(row, text="", foreground=motyw.CZERWONY); self.lbl_tx.pack(side="left", padx=10)
        self.lbl_cur = tk.Label(row, text="", fg=motyw.CZERWONY, font=("Consolas", 16, "bold"), width=12, anchor="w")
        self.lbl_cur.pack(side="left")
        # logger
        lrow = ttk.Frame(tx); lrow.pack(fill="x", pady=(3, 0))
        self.var_rsts, self.var_rstr = tk.StringVar(value="599"), tk.StringVar(value="599")
        self.var_name, self.var_cmt = tk.StringVar(), tk.StringVar()
        for lab, var, w in (("RST nad.:", self.var_rsts, 5), ("odb.:", self.var_rstr, 5),
                            ("Imię:", self.var_name, 10), ("Uwagi:", self.var_cmt, 18)):
            ttk.Label(lrow, text=lab).pack(side="left", padx=(6, 0))
            ttk.Entry(lrow, textvariable=var, width=w).pack(side="left", padx=2)
        ttk.Button(lrow, text="Zapisz QSO (Ctrl+L)", command=self.log_qso).pack(side="left", padx=8)
        self.var_l4o = tk.BooleanVar(value=self.cfg["log4om_send"])
        ttk.Checkbutton(lrow, text="→ Log4OM", variable=self.var_l4o).pack(side="left")
        r.bind("<Control-l>", lambda e: self.log_qso())
        self.t_on = None
        self.var_call.trace_add("write", self._call_changed)
        self.ent = ttk.Entry(tx, font=("Consolas", 13)); self.ent.pack(fill="x", pady=4)
        self.ent.bind("<Return>", lambda e: self.send(self.ent.get(), clear=True))
        r.bind("<Escape>", lambda e: self.stop())
        mrow = ttk.Frame(tx); mrow.pack(fill="x")
        self.mframe = ttk.Frame(mrow); self.mframe.pack(side="left")
        ttk.Button(mrow, text="STOP", command=self.stop).pack(side="right")
        ttk.Button(mrow, text="✎ Makra", command=self.edit_macros).pack(side="right", padx=6)
        self._build_macros()
        self.ft8 = ft8_tab.ZakladkaFT8(f8, self, save_cfg, DATA_DIR, sd)
        self.qo_tab = ft8_qo_tab.ZakladkaQO(fq, self, save_cfg, DATA_DIR, sd, self.ft8)
        self.nb.bind("<<NotebookTabChanged>>", self._tab_changed)
        if self.cfg.get("zakladka") in (1, 2):
            self.nb.select(self.cfg["zakladka"])

    def _tab_changed(self, ev=None):
        i = self.nb.index(self.nb.select())
        self.zakladka = i
        self.cw_aktywne = i == 0
        self.qo_tab.ustaw_aktywna(i == 2)       # FT8 QO-100 dekoduje i nadaje tylko, gdy jest otwarta
        self.cfg["zakladka"] = i; save_cfg(self.cfg)
        self.pokaz_civ()
        if self.cw_aktywne:                 # duża częstotliwość u góry: w CW z CI-V, w FT8 z radia tamtej zakładki
            if self.radio and self.radio.freq:
                self._show_freq(self.radio.freq)
            else:
                self.lbl_freq.config(text="  —")

    def pokaz_civ(self):
        """Pola CI-V u góry widać w zakładce CW, a w FT8 tylko gdy radiem jest „CI-V wprost”."""
        if self.cw_aktywne or self.cfg.get("ft8_radio") == "civ":
            self.civ_fr.pack(side="left")
        else:
            self.civ_fr.pack_forget()

    def _fill_devices(self):
        if sd is None:
            self.status.config(text="Brak sounddevice: " + SD_ERR)
        else:
            devs = [f"{i}: {d['name']}" for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]
            self.cb_audio["values"] = devs
            pick = next((d for d in devs if self.cfg["audio"] and self.cfg["audio"] in d), None) \
                or next((d for d in devs if "USB Audio CODEC" in d), None) or (devs[0] if devs else "")
            self.cb_audio.set(pick)
        if list_ports is None:
            self.status.config(text="Brak pyserial: " + SER_ERR)
        else:
            ports = [f"{p.device} – {p.description}" for p in list_ports.comports()]
            self.cb_port["values"] = ports
            pick = next((p for p in ports if self.cfg["port"] and p.startswith(self.cfg["port"] + " ")), None) \
                or next((p for p in ports if "Silicon Labs" in p or "CP210" in p), None) or (ports[0] if ports else "")
            self.cb_port.set(pick)
        if self.ft8 is not None:
            self.ft8.wypelnij_wyjscia()

    def _opts(self):
        self.dec.inverted = self.var_inv.get()
        self.dec.afc = self.var_afc.get()
        self.dec.squelch_db = float(self.var_sq.get())
        self.dec.marks = []
        self.cfg.update(inverted=self.dec.inverted, afc=self.dec.afc, squelch_db=round(self.dec.squelch_db, 1))
        save_cfg(self.cfg)

    def _wpm(self):
        try:
            w = int(self.var_wpm.get())
        except Exception:
            return
        self.cfg["wpm"] = w; save_cfg(self.cfg)
        if self.radio:
            try:
                self.radio.set_wpm(w)
            except Exception as e:
                self.status.config(text=f"CI-V: {e}")

    def _wf_click(self, ev):
        f = FMIN + ev.x / WF_W * (FMAX - FMIN)
        self.var_afc.set(False); self._opts()
        self.dec.set_tone(f)

    # ------------------------------------------------------------------ audio
    def start_audio(self):
        if sd is None:
            messagebox.showerror("GOLbase", "Brak biblioteki sounddevice – uruchom run.bat"); return
        sel = self.cb_audio.get()
        if not sel:
            return
        idx = int(sel.split(":")[0])
        if self.stream:
            self.stream.stop(); self.stream.close()

        def cb(indata, frames, t, status):
            try:
                self.q_audio.put_nowait(indata[:, 0].copy())
            except queue.Full:
                pass
        try:
            self.stream = sd.InputStream(device=idx, channels=1, samplerate=FS, blocksize=1200, dtype="float32",
                                         callback=cb)
            self.stream.start()
            try:                                # opóźnienie karty – odejmowane od czasu próbek w zakładkach FT8 (DT)
                ft8_tab.F.OPOZNIENIE_WEJSCIA = max(0.0, min(0.5, float(self.stream.latency)))
            except Exception:
                pass
        except Exception as e:
            messagebox.showerror("GOLbase", f"Nie mogę otworzyć wejścia audio:\n{e}"); return
        self.cfg["audio"] = sel.split(":", 1)[1].strip(); save_cfg(self.cfg)
        self.status.config(text=f"Odbiór: {self.cfg['audio']}")

    def _dsp_loop(self):
        acc = []
        while self.running:
            try:
                x = self.q_audio.get(timeout=0.2)
            except queue.Empty:
                continue
            if self.cw_aktywne:
                self.dec.process(x)
            if self.zakladka == 2:              # radio stoi na pośredniej QO-100 – dźwięk tylko dla tej zakładki
                if self.qo_tab is not None:
                    self.qo_tab.podaj(x)
            elif self.ft8 is not None:
                self.ft8.podaj(x)
            self.ring = np.concatenate([self.ring, x])[-2 * FS:]
            pk = float(np.max(np.abs(x))) if len(x) else 0.0
            self.clip = max(pk, self.clip * 0.97)
            if self.rec is not None:
                self.rec.append(x)
                if time.time() > self.rec_until:
                    data, self.rec = self.rec, None
                    self.root.after(0, self._rec_save, data)
            acc.append(x)
            if sum(len(a) for a in acc) >= 2400:          # wodospad co 50 ms
                blk = np.concatenate(acc); acc = []
                self.last_audio = np.concatenate([self.last_audio, blk])[-4096:]
                f, db = self.dec.spectrum(self.last_audio)
                row = np.interp(np.linspace(FMIN, FMAX, WF_W), f, db)
                self.wf_lo = self.wf_lo * 0.98 + np.percentile(row, 20) * 0.02
                self.wf_hi = max(self.wf_hi * 0.97 + np.percentile(row, 99.5) * 0.03, self.wf_lo + 25)
                v = (row - self.wf_lo) / (self.wf_hi - self.wf_lo)
                self.wf = np.roll(self.wf, 1, axis=0)
                self.wf[0] = colormap(v)

    # ------------------------------------------------------------------ radio
    def _civ_button(self):
        """Przycisk przy CI-V: „Połącz” albo – gdy połączony – „Rozłącz” (zwalnia port COM, np. dla OmniRig)."""
        if self.radio:
            self.disconnect_radio()
        else:
            self.connect_radio()

    def disconnect_radio(self, zapamietaj=True):
        if self.radio:
            try:
                self.radio.close()
            except Exception:
                pass
        self.radio = None
        self.btn_civ.config(text="Połącz")
        self.lbl_freq.config(text="  —")
        self.status.config(text="CI-V rozłączony – port COM wolny")
        if zapamietaj:                      # przy następnym starcie programu nie łącz sam
            self.cfg["civ_auto"] = False; save_cfg(self.cfg)

    def connect_radio(self):
        if list_ports is None:
            messagebox.showerror("GOLbase", "Brak pyserial – uruchom run.bat"); return
        sel = self.cb_port.get()
        if not sel:
            return
        port = sel.split(" ")[0]
        if self.radio:
            self.radio.close()
        try:
            self.radio = IC7300(port, int(self.cfg["baud"]), radio_addr=int(self.cfg["civ_addr"], 16),
                                on_freq=lambda hz: self.root.after(0, self._show_freq, hz),
                                on_mode=lambda m: self.root.after(0, self._show_mode, m))
            self.radio.on_tx = lambda st, info="": self.root.after(0, self._on_tx, st, info)
            self.radio.poll()
            self.radio.set_wpm(int(self.var_wpm.get()))
        except Exception as e:
            self.radio = None
            messagebox.showerror("GOLbase", f"Nie mogę otworzyć {port}:\n{e}"); return
        self.cfg["port"] = port; self.cfg["civ_auto"] = True; save_cfg(self.cfg)
        self.btn_civ.config(text="Rozłącz")
        self.status.config(text=f"CI-V: {port} @ {self.cfg['baud']}, adres {self.cfg['civ_addr']}h")
        self.root.after(1500, self._check_radio)

    def _check_radio(self):
        if self.radio and not self.radio.freq:
            self.status.config(text="Radio nie odpowiada na CI-V – sprawdź port, prędkość (115200) i adres 94h "
                                    "(Menu > Set > Connectors > CI-V)")

    def _show_freq(self, hz):
        if not self.radio:                  # spóźniona odpowiedź po „Rozłącz”
            return
        if self.zakladka == 2 or (not self.cw_aktywne and self.cfg.get("ft8_radio") != "civ"):
            return                          # w zakładkach FT8 częstotliwość pokazuje radio tamtej zakładki
        if self.var_qo.get():
            d = self.qo.downlink(hz)
            self.lbl_freq.config(text=f"↓{d / 1e6:,.5f} MHz  {self.radio.mode or ''}".replace(",", " "))
        else:
            self.lbl_freq.config(text=f"{hz / 1e6:,.5f} MHz  {self.radio.mode or ''}".replace(",", " "))

    def _show_mode(self, m):
        if self.radio:
            self._show_freq(self.radio.freq)

    # ------------------------------------------------------------------ makra
    def _macro_list(self):
        return [(n, t) for n, t in self.cfg["macros"].items() if n.strip() and t.strip()][:MAX_MACROS]

    def _build_macros(self):
        for w in self.mframe.winfo_children():
            w.destroy()
        for i in range(1, 13):
            self.root.unbind(f"<F{i}>")
        for i, (name, text) in enumerate(self._macro_list()):
            b = ttk.Button(self.mframe, text=name, command=lambda i=i: self.send_macro(i))
            b.pack(side="left", padx=2)
            b.bind("<Button-3>", lambda e: self.edit_macros())          # prawy klik = edycja
            self.root.bind(f"<F{i + 1}>", lambda e, i=i: self.send_macro(i))

    def send_macro(self, i):
        m = self._macro_list()
        if i < len(m):
            self.send(m[i][1])

    def edit_macros(self):
        if getattr(self, "_medit", None) and self._medit.winfo_exists():
            self._medit.lift(); return
        w = tk.Toplevel(self.root); self._medit = w
        w.title("GOLbase – makra F1–F8"); w.transient(self.root)
        f = ttk.Frame(w, padding=8); f.pack(fill="both", expand=True)
        ttk.Label(f, text="Klawisz").grid(row=0, column=0, sticky="w")
        ttk.Label(f, text="Nazwa przycisku").grid(row=0, column=1, sticky="w")
        ttk.Label(f, text="Treść").grid(row=0, column=2, sticky="w")
        items = list(self.cfg["macros"].items())[:MAX_MACROS]
        items += [("", "")] * (MAX_MACROS - len(items))
        rows = []
        for i, (n, t) in enumerate(items):
            ttk.Label(f, text=f"F{i + 1}").grid(row=i + 1, column=0, padx=(0, 6))
            vn, vt = tk.StringVar(value=n), tk.StringVar(value=t)
            ttk.Entry(f, textvariable=vn, width=12).grid(row=i + 1, column=1, pady=2)
            ttk.Entry(f, textvariable=vt, width=80, font=("Consolas", 10)).grid(row=i + 1, column=2, pady=2, padx=4)
            rows.append((vn, vt))
        ttk.Label(f, text="Mój znak:").grid(row=MAX_MACROS + 1, column=1, sticky="e", pady=(8, 0))
        v_my = tk.StringVar(value=self.cfg["my_call"])
        ttk.Entry(f, textvariable=v_my, width=12).grid(row=MAX_MACROS + 1, column=2, sticky="w", padx=4, pady=(8, 0))
        ttk.Label(f, text=HELP_MACROS, foreground=motyw.SZARY, justify="left").grid(
            row=MAX_MACROS + 2, column=0, columnspan=3, sticky="w", pady=6)
        bf = ttk.Frame(f); bf.grid(row=MAX_MACROS + 3, column=0, columnspan=3, sticky="e")

        def save():
            mac, seen = {}, set()
            for vn, vt in rows:
                n, t = vn.get().strip(), " ".join(vt.get().split())
                if not n and not t:
                    continue
                if not n:
                    n = t[:8]
                while n in seen:
                    n += "'"
                seen.add(n); mac[n] = t
            self.cfg["macros"] = mac
            self.cfg["my_call"] = v_my.get().strip().upper() or self.cfg["my_call"]
            save_cfg(self.cfg); self._build_macros()
            self.root.title(f"GOLbase {VERSION} – {self.cfg['my_call']}")
            w.destroy()

        def defaults():
            d = list(DEFAULT_CFG["macros"].items()) + [("", "")] * MAX_MACROS
            for (vn, vt), (n, t) in zip(rows, d):
                vn.set(n); vt.set(t)

        ttk.Button(bf, text="Domyślne", command=defaults).pack(side="left", padx=4)
        ttk.Button(bf, text="Anuluj", command=w.destroy).pack(side="left", padx=4)
        ttk.Button(bf, text="Zapisz", command=save).pack(side="left", padx=4)
        w.bind("<Escape>", lambda e: w.destroy())

    def _fill(self, text):
        call = self.var_call.get().strip().upper()
        return (text.replace("{MY}", self.cfg["my_call"]).replace("{CALL}", call)
                .replace("{RST}", self.var_rsts.get().strip() or "599")
                .replace("{NAME}", self.var_name.get().strip().upper()))

    def send(self, text, clear=False):
        text = self._fill(text).upper()
        # prosigny w nawiasach <SK> zamieniamy na litery nadawane razem (radio nie zna nawiasów)
        text = text.replace("<SK>", "SK").replace("<AR>", "+").replace("<BT>", "=").replace("<KN>", "(")
        text = " ".join("".join(c for c in text if c in CW_CHARS).split())
        if not text:
            return
        if not self.radio:
            messagebox.showwarning("GOLbase", "Najpierw połącz z radiem (CI-V)."); return
        if self.radio.mode and self.radio.mode not in ("CW", "CW-R"):
            if not messagebox.askyesno("GOLbase", f"Radio jest w emisji {self.radio.mode}, nie CW.\nNadać mimo to?"):
                return
        wpm = int(self.var_wpm.get())
        mid = self.tx_next; self.tx_next += 1
        self.txt.insert("end", "\n>> ", "tx")
        mark = f"txm{mid}"
        self.txt.mark_set(mark, "end-1c"); self.txt.mark_gravity(mark, "left")
        self.txt.insert("end", text + "\n", "tx"); self.txt.see("end")
        self.tx_msgs[mid] = (mark, len(text))
        self.lbl_tx.config(text="NADAJĘ…")
        self.radio.send_cw(text, wpm, msg_id=mid)
        if clear:
            self.ent.delete(0, "end")

    def _clear(self):
        self.txt.delete("1.0", "end")
        for m, _ in self.tx_msgs.values():
            self.txt.mark_unset(m)
        self.tx_msgs = {}; self.tx_last = None

    def _tx_show(self):
        """Podświetla w polu Odebrane literę, którą radio teraz nadaje (żółte tło), nadane – szare."""
        pos = self.radio.tx_pos() if self.radio else None
        if pos == self.tx_last:
            return
        self.tx_last = pos
        self.txt.tag_remove("txcur", "1.0", "end")
        if not pos or pos[0] not in self.tx_msgs:
            self.lbl_cur.config(text="")
            return
        mid, idx = pos
        for old in [k for k in self.tx_msgs if k < mid]:     # wcześniejsze komunikaty – całe nadane
            m, n = self.tx_msgs.pop(old)
            self.txt.tag_add("txdone", m, f"{m}+{n}c"); self.txt.mark_unset(m)
        mark, n = self.tx_msgs[mid]
        idx = min(idx, n)
        self.txt.tag_add("txdone", mark, f"{mark}+{idx}c")
        if idx < n:
            self.txt.tag_add("txcur", f"{mark}+{idx}c", f"{mark}+{idx + 1}c")
            c = self.txt.get(f"{mark}+{idx}c")
            mo = TEXT2MORSE.get(c, "")
            self.lbl_cur.config(text=(f"{c}  {mo.replace('.', '·').replace('-', '–')}" if c.strip() else ""))
        else:
            self.lbl_cur.config(text="")

    def _on_tx(self, state, info):
        self.lbl_tx.config(text=("NADAJĘ…" if state else "") + (f"  {info}" if info else ""))
        if info:
            self.status.config(text=f"CI-V: {info}")

    # ------------------------------------------------------------------ logger
    def _cty_updated(self, src):
        self.status.config(text=f"Kraje: pobrano świeży {src}")
        self._call_changed()

    def _call_changed(self, *a):
        c = self.var_call.get().strip()
        try:
            self.lbl_cty.config(text=self.kraje.describe(c, self.cfg["my_call"]) if len(c) >= 2 else "")
        except Exception:
            self.lbl_cty.config(text="")
        if c and self.t_on is None:
            self.t_on = time.gmtime()          # początek QSO = chwila wpisania znaku
        elif not c:
            self.t_on = None

    def log_qso(self):
        call = self.var_call.get().strip().upper()
        if not call:
            messagebox.showwarning("GOLbase", "Wpisz znak korespondenta (Jego znak)."); return
        if not self.radio or not self.radio.freq:
            if not messagebox.askyesno("GOLbase", "Brak częstotliwości z radia (CI-V). Zapisać bez częstotliwości?"):
                return
        hz = self.radio.freq if self.radio and self.radio.freq else 0
        qo = None
        if self.var_qo.get() and hz:
            dn = self.qo.downlink(hz)
            qo = (self.qo.uplink_for(dn), dn)
        t_off = time.gmtime()
        f = logbook.make_qso(call, self.t_on or t_off, t_off, hz, self.var_rsts.get(), self.var_rstr.get(),
                             self.var_name.get(), self.var_cmt.get(), qo, self.cfg["my_call"],
                             self.cfg["qo_tx_pwr"] if qo else "")
        rec = logbook.adif_record(f)
        path = os.path.join(DATA_DIR, LOG_ADI)
        try:
            logbook.append_adi(path, rec)
        except Exception as e:
            messagebox.showerror("GOLbase", f"Nie mogę zapisać {path}:\n{e}"); return
        where = "plik " + LOG_ADI
        self.cfg["log4om_send"] = self.var_l4o.get(); save_cfg(self.cfg)
        if self.var_l4o.get():
            try:
                logbook.send_log4om(rec, self.cfg["log4om_udp"])
                where += f" + Log4OM ({self.cfg['log4om_udp']})"
            except Exception as e:
                where += f" (Log4OM: błąd {e})"
        fr = f"{f['freq']} MHz {f['band']}" + (f" / RX {f['freq_rx']} {f['band_rx']} QO-100" if qo else "")
        self.txt.insert("end", f"\n[LOG] {time.strftime('%H:%M', t_off)} UTC {call} {f['rst_sent']}/{f['rst_rcvd']} "
                               f"{fr} → {where}\n", "tx"); self.txt.see("end")
        self.var_call.set(""); self.var_name.set(""); self.var_cmt.set("")
        self.var_rsts.set("599"); self.var_rstr.set("599")

    def focus_get_safe(self):
        try:
            return self.root.focus_get()
        except Exception:
            return None

    def stop(self):
        if self.radio:
            self.radio.abort()
        if self.ft8 is not None:
            self.ft8.stop()
        if self.qo_tab is not None:
            self.qo_tab.stop()
        self.lbl_tx.config(text=""); self.lbl_cur.config(text="")
        self.txt.tag_remove("txcur", "1.0", "end"); self.tx_last = None

    # ------------------------------------------------------------------ QO-100
    def _pitch(self):
        p = self.radio.pitch if self.radio and self.radio.pitch else None
        if p and p != self.cfg["pitch_hz"]:
            self.cfg["pitch_hz"] = p; save_cfg(self.cfg)
        return p or self.cfg["pitch_hz"]

    def _sig_if(self, precise=False):
        """Pośrednia (IF) nośnej wybranego sygnału; precise=True – dokładny pomiar z ostatnich 2 s dźwięku."""
        if not self.radio or not self.radio.freq:
            return None, None
        tone, snr = self.dec.tone, None
        if precise:
            t, snr = qo100.precise_peak(self.ring.copy(), FS, self.dec.tone)
            if t is None:
                return None, None
            tone = t
        return qo100.signal_if(self.radio.freq, self.radio.mode or "CW", tone, self._pitch()), snr

    def _qo_toggle(self):
        self.cfg["qo100"] = self.var_qo.get(); save_cfg(self.cfg)
        if self.radio and self.radio.freq:
            self._show_freq(self.radio.freq)

    def _qo_save(self):
        self.cfg.update(qo_corr_rx_hz=round(self.qo.corr_rx, 1), qo_corr_tx_hz=self.qo.corr_tx)
        save_cfg(self.cfg)

    def _qo_note(self, text):
        self.txt.insert("end", f"\n[QO-100] {text}\n", "tx"); self.txt.see("end")

    def _qo_cal(self):
        if not self.radio or not self.radio.freq:
            messagebox.showwarning("GOLbase", "Najpierw połącz z radiem (CI-V)."); return
        exp_if = self.qo.beacon - self.qo.lo_rx
        if not messagebox.askokcancel("GOLbase – kalibracja QO-100",
                                      f"Nastaw radio w okolice {exp_if / 1e6:.4f} MHz (CW), tak żeby beacon CW "
                                      f"był na wodospadzie i czerwona kreska stała na nim (AFC albo kliknięcie).\n\n"
                                      f"Mierzę ostatnie 2 sekundy – OK?"):
            return
        sig, snr = self._sig_if(precise=True)
        if sig is None or snr < 15:
            messagebox.showerror("GOLbase", "Nie widzę wyraźnego beacona przy czerwonej kresce "
                                 f"(SNR {snr or 0:.0f} dB). Ustaw kreskę na beaconie i spróbuj jeszcze raz."); return
        corr = sig + self.qo.lo_rx - self.qo.beacon
        if abs(corr) > 30000 and not messagebox.askyesno(
                "GOLbase", f"Wychodzi błąd LNB {corr / 1000:+.2f} kHz – dużo. Na pewno to beacon? Zapisać?"):
            return
        self.qo.calibrate(sig)
        self.cfg["qo_cal_time"] = time.strftime("%d.%m %H:%M"); self._qo_save()
        self._qo_note(f"beacon słychać na {sig / 1e6:.6f} MHz (SNR {snr:.0f} dB) → błąd LNB "
                      f"{self.qo.corr_rx:+.0f} Hz. Od teraz częstotliwości są poprawione.")
        if not self.var_qo.get():
            self.var_qo.set(True); self._qo_toggle()

    def _qo_tune(self):
        """Ustawia radio tak, żeby wybrany sygnał był na tonie CW (zero-beat)."""
        sig, _ = self._sig_if(precise=True)
        if sig is None:
            messagebox.showwarning("GOLbase", "Najpierw połącz z radiem i wybierz sygnał na wodospadzie."); return
        if self.radio.mode not in ("CW", "CW-R"):
            messagebox.showwarning("GOLbase", "Dostrajanie działa w emisji CW."); return
        self.radio.set_freq(round(sig / 10) * 10)
        self.dec.set_tone(self._pitch())
        self._qo_note(f"radio na {sig / 1e6:.5f} MHz – stacja na tonie {self._pitch()} Hz, "
                      f"↓ {qo100.khz(self.qo.downlink(sig))}")
        self.root.after(300, self.radio.poll)

    def _qo_xit(self):
        if not self.radio:
            messagebox.showwarning("GOLbase", "Najpierw połącz z radiem (CI-V)."); return
        x = self.qo.xit()
        if not self.cfg["qo_cal_time"]:
            messagebox.showwarning("GOLbase", "Najpierw kalibracja na beaconie."); return
        try:
            if x == 0:
                self.radio.xit_off()
            else:
                self.radio.set_xit(x)
        except Exception as e:
            messagebox.showerror("GOLbase", str(e)); return
        self._qo_note(f"ΔTX = {x:+d} Hz – nadajesz tam, gdzie słychać stację (zero-beat przez satelitę). "
                      "Wyłącz ΔTX w radiu przed pracą na KF.")

    def _qo_copy(self, ev=None):
        sig, _ = self._sig_if()
        if sig is None:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(f"{self.qo.downlink(sig) / 1e6:.6f}")
        self.status.config(text=f"Skopiowano downlink {self.qo.downlink(sig) / 1e6:.6f} MHz (do logu)")

    def _qo_update(self):
        if not self.var_qo.get():
            self.lbl_qo.config(text=""); self.lbl_qocal.config(text=""); return
        sig, _ = self._sig_if()
        if sig is None:
            self.lbl_qo.config(text="sygnał: brak CI-V")
        else:
            d = self.qo.downlink(sig)
            self.lbl_qo.config(text=f"sygnał ↓ {qo100.khz(d)}\n   nadaj ↑ {qo100.khz(self.qo.uplink_for(d))}")
        cal = self.cfg["qo_cal_time"]
        self.lbl_qocal.config(text=(f"LNB {self.qo.corr_rx:+.0f} Hz ({cal}), ΔTX {self.qo.xit():+d} Hz"
                                    if cal else "bez kalibracji – kliknij „Kalibruj na beacon”"))

    # ------------------------------------------------------------------ pętla GUI
    def _tick(self):
        out = []
        while not self.q_text.empty():
            out.append(self.q_text.get())
        if out:
            self.txt.insert("end", "".join(out)); self.txt.see("end")
        h, w = self.wf.shape[:2]
        ppm = b"P6 %d %d 255\n" % (w, h) + self.wf.tobytes()
        self.img.configure(data=ppm, format="PPM")
        x = (self.dec.tone - FMIN) / (FMAX - FMIN) * WF_W
        self.canvas.coords(self.marker, x, 16, x, WF_H + 16)
        self.lbl_stat.config(text=f"ton {self.dec.tone:4.0f} Hz | {self.dec.wpm:4.1f} WPM | SNR {self.dec.snr_db:4.1f} dB")
        self.lbl_clip.config(text="PRZESTEROWANIE – zmniejsz AF Output Level / włącz ATT" if self.clip > 0.95
                             else ("" if self.rec is None else "● nagrywam…"))
        if int(time.time() * 20) % 5 == 0:
            self._qo_update()
        self.led.itemconfig(self.led_id, fill="#2f2" if self.dec.key else "#333")
        self._tx_show()
        if self.radio and self.radio.wpm and self.radio.wpm != self.cfg["wpm"] and self.focus_get_safe() is not self.sp_wpm:
            self.var_wpm.set(self.radio.wpm); self.cfg["wpm"] = self.radio.wpm; save_cfg(self.cfg)
        if self.radio and int(time.time() * 20) % 40 == 0:
            try:
                self.radio.poll()
            except Exception:
                pass
        self.root.after(50, self._tick)

    def _rec_start(self):
        if self.stream is None:
            messagebox.showwarning("GOLbase", "Najpierw Start odbioru."); return
        self.rec_until = time.time() + 60
        self.rec = []

    def _rec_save(self, blocks):
        import wave
        x = np.clip(np.concatenate(blocks), -1, 1)
        fn = os.path.join(DATA_DIR, time.strftime("cw_nagranie_%Y%m%d_%H%M%S.wav"))
        with wave.open(fn, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(FS)
            w.writeframes((x * 32767).astype("<i2").tobytes())
        self.status.config(text=f"Nagranie: {fn}")

    def _save_log(self):
        fn = os.path.join(DATA_DIR, time.strftime("cw_log_%Y%m%d_%H%M%S.txt"))
        with open(fn, "w", encoding="utf-8") as f:
            f.write(self.txt.get("1.0", "end"))
        self.status.config(text=f"Zapisano {fn}")

    def _quit(self):
        self.running = False
        try:
            if self.qo_tab is not None:
                self.qo_tab.zamknij()
            if self.ft8 is not None:
                self.ft8.zamknij()
        except Exception:
            pass
        try:
            if self.stream:
                self.stream.stop(); self.stream.close()
            if self.radio:
                self.radio.close()
        finally:
            self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()

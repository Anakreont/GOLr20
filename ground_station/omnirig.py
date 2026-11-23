"""
Sterowanie radiem przez OmniRig (Windows, COM) – zakładka „FT8 balon” w GOLbase.

OmniRig trzyma port COM radia i dzieli go między programy (Log4OM, GOLbase…), więc ten sam kabel
obsługuje log i nasz program. Rig 1 = IC-7300, Rig 2 = Yaesu FTX-1 (ustawia się w oknie OmniRig).
Używamy tylko: częstotliwość, emisja cyfrowa USB (DIG-U = USB-D / DATA-U) i nadawanie (PTT).

Cała rozmowa z OmniRig idzie z jednego wątku (wymóg COM); pozostałe wątki wrzucają polecenia do kolejki.
"""
import queue, threading, time

PM_FREQ, PM_FREQA = 0x2, 0x4
PM_RX, PM_TX = 0x00200000, 0x00400000
PM_CW_U, PM_CW_L, PM_SSB_U, PM_SSB_L = 0x00800000, 0x01000000, 0x02000000, 0x04000000
PM_DIG_U, PM_DIG_L, PM_AM, PM_FM = 0x08000000, 0x10000000, 0x20000000, 0x40000000
EMISJE = {PM_CW_U: "CW", PM_CW_L: "CW-R", PM_SSB_U: "USB", PM_SSB_L: "LSB", PM_DIG_U: "DIG-U", PM_DIG_L: "DIG-L",
          PM_AM: "AM", PM_FM: "FM"}
ST_ONLINE = 4
STANY = {0: "nie skonfigurowany w OmniRig", 1: "wyłączony w OmniRig", 2: "port COM zajęty",
         3: "radio nie odpowiada", 4: "połączony"}


class OmniRig:
    def __init__(self, nr=1):
        self.nr = nr
        self.freq = 0
        self.mode = None
        self.tx = False
        self.stan = "łączenie…"
        self.typ = ""
        self.online = False
        self.blad = None
        self.alive = True
        self.q = queue.Queue()
        self.gotowy = threading.Event()
        threading.Thread(target=self._watek, daemon=True).start()
        self.gotowy.wait(5)

    # ------------------------------------------------------------------ wątek COM
    def _watek(self):
        try:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            omni = win32com.client.Dispatch("OmniRig.OmniRigX")
            rig = omni.Rig1 if self.nr == 1 else omni.Rig2
        except Exception as e:
            self.blad = f"OmniRig niedostępny: {e}"
            self.stan = self.blad
            self.gotowy.set()
            return
        self.gotowy.set()
        nast = 0.0
        while self.alive:
            try:
                f, zrobione = self.q.get(timeout=0.1)
                try:
                    f(rig)
                except Exception as e:
                    self.stan = f"OmniRig: {e}"
                zrobione.set()
                continue
            except queue.Empty:
                pass
            if time.time() >= nast:
                nast = time.time() + 0.7
                try:
                    st = int(rig.Status)
                    self.online = st == ST_ONLINE
                    self.typ = str(rig.RigType)
                    self.stan = f"Rig {self.nr} {self.typ}: {STANY.get(st, st)}"
                    if self.online:
                        self.freq = int(rig.Freq) or int(rig.FreqA)
                        self.mode = EMISJE.get(int(rig.Mode), "?")
                        self.tx = int(rig.Tx) == PM_TX
                except Exception as e:
                    self.online = False
                    self.stan = f"OmniRig: {e}"
        try:
            rig.Tx = PM_RX
        except Exception:
            pass
        # zwolnij OmniRig: gdy nie korzysta z niego żaden inny program, OmniRig sam się zamyka i oddaje port COM
        rig = omni = None
        try:
            import gc
            gc.collect()
            pythoncom.CoUninitialize()
        except Exception:
            pass

    def _zrob(self, f, czekaj=1.5):
        if self.blad:
            raise RuntimeError(self.blad)
        ev = threading.Event()
        self.q.put((f, ev))
        return ev.wait(czekaj)

    # ------------------------------------------------------------------ polecenia
    def set_freq(self, hz):
        def f(rig):
            rig.Freq = int(hz)
            if int(rig.Freq) != int(hz):          # część radii w OmniRig zna tylko VFO A
                rig.FreqA = int(hz)
        self._zrob(f)

    def set_usb_data(self):
        self._zrob(lambda rig: setattr(rig, "Mode", PM_DIG_U))

    def ptt(self, on):
        """Nadawanie wł./wył.; wraca po wykonaniu przez OmniRig (najwyżej 1,5 s)."""
        return self._zrob(lambda rig: setattr(rig, "Tx", PM_TX if on else PM_RX))

    def close(self):
        try:
            self.ptt(False)
        except Exception:
            pass
        self.alive = False

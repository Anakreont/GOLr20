"""
Dekoder CW z sygnału audio (np. wyjście USB IC-7300).

Dwa tryby:
  normalny   - klasyczny Morse: kropka/kreska rozróżniane po długości TONU.
  odwrocony  - jak CW startowe trackera ICT (Beep.h SA6BSS/YO3ICT): każdy ton trwa tyle samo,
               a kropkę od kreski rozróżnia długość PRZERWY po tonie
               (~1 jedn. = kropka, ~3 = kreska, ~4 = kropka + koniec litery, ~6 = kreska + koniec litery).

Użycie:
  d = CWDecoder(fs=48000, on_text=print)
  d.process(numpy_array_float32)   # kolejne kawałki audio (mono)
"""
import numpy as np

MORSE = {
    ".-": "A", "-...": "B", "-.-.": "C", "-..": "D", ".": "E", "..-.": "F", "--.": "G", "....": "H",
    "..": "I", ".---": "J", "-.-": "K", ".-..": "L", "--": "M", "-.": "N", "---": "O", ".--.": "P",
    "--.-": "Q", ".-.": "R", "...": "S", "-": "T", "..-": "U", "...-": "V", ".--": "W", "-..-": "X",
    "-.--": "Y", "--..": "Z",
    "-----": "0", ".----": "1", "..---": "2", "...--": "3", "....-": "4", ".....": "5", "-....": "6",
    "--...": "7", "---..": "8", "----.": "9",
    ".-.-.-": ".", "--..--": ",", "..--..": "?", "-..-.": "/", "-...-": "=", ".-.-.": "+", "-....-": "-",
    ".--.-.": "@", "---...": ":", "-.--.": "(", "-.--.-": ")", ".----.": "'", "-.-.--": "!",
    "...-.-": "<SK>", ".-...": "<AS>", "-.-.-": "<KA>", "........": "<HH>",
}
TEXT2MORSE = {v: k for k, v in MORSE.items() if len(v) == 1}


def text_to_morse(text):
    return " ".join(TEXT2MORSE.get(c, "") for c in text.upper())


class CWDecoder:
    def __init__(self, fs=48000, on_text=None, tone=700.0, hop_ms=4.0, win_ms=10.0):
        self.fs = fs
        self.on_text = on_text or (lambda s: None)
        self.tone = float(tone)
        self.hop = int(fs * hop_ms / 1000)
        self.win = int(fs * win_ms / 1000)
        self.dt = self.hop / fs                       # sekundy na blok
        self.buf = np.zeros(0, dtype=np.float32)
        self.inverted = False
        self.afc = True
        self.squelch_db = 6.0                         # min. odstęp sygnału od szumu
        # stan obwiedni
        self.noise = 1e-6
        self.peak = 1e-5
        self.key = False
        self.run = 0                                  # długość bieżącego stanu (bloki)
        # stan dekodowania
        self.marks = []                               # ostatnie długości tonów (s)
        self.unit = 0.06                              # długość kropki (s) ~ 20 WPM
        self.symbol = ""
        self.space_sent = True
        self.pending = None                           # tryb odwrócony: ton czekający na przerwę
        # widmo do AFC / wodospadu
        self.spec_acc = None
        self.spec_n = 0
        self.snr_db = 0.0
        self.warm = 0                                 # pierwsze ~0,3 s tylko uczy się poziomu szumu
        self._make_window()

    # ---------------------------------------------------------------- ustawienia
    def _make_window(self):
        self.w = np.hanning(self.win).astype(np.float32)

    def set_tone(self, f):
        self.tone = float(f)
        self.warm = 0; self.peak = 1e-5; self.key = False; self.run = 0

    @property
    def wpm(self):
        return 1.2 / self.unit if self.unit > 0 else 0

    # ---------------------------------------------------------------- przetwarzanie
    def process(self, x):
        x = np.asarray(x, dtype=np.float32).ravel()
        self.buf = np.concatenate([self.buf, x])
        while len(self.buf) >= self.win:
            frame = self.buf[:self.win]
            self.buf = self.buf[self.hop:]
            self._block(frame)

    def _goertzel(self, frame, f):
        n = np.arange(len(frame))
        ph = np.exp(-2j * np.pi * f / self.fs * n)
        return abs(np.dot(frame * self.w, ph)) / len(frame)

    def _block(self, frame):
        m = self._goertzel(frame, self.tone)
        # obwiednia: szum wolno w dół/szybko w górę tylko gdy brak tonu, szczyt szybko w górę/wolno w dół
        if self.warm < 80:
            self.warm += 1
            self.noise = m if self.warm == 1 else self.noise * 0.9 + m * 0.1
            self.peak = max(self.peak, self.noise * 1.5)
            return
        if m > self.peak:
            self.peak = m
        else:
            self.peak = self.peak * 0.998 + m * 0.002
        if not self.key:
            self.noise = self.noise * 0.99 + m * 0.01 if m < self.noise * 3 else self.noise * 0.999 + m * 0.001
        self.noise = min(self.noise, self.peak)
        self.snr_db = 20 * np.log10(max(self.peak, 1e-12) / max(self.noise, 1e-12))
        thr_hi = self.noise + 0.55 * (self.peak - self.noise)
        thr_lo = self.noise + 0.40 * (self.peak - self.noise)
        valid = self.snr_db >= self.squelch_db
        new_key = (m > thr_hi) if not self.key else (m > thr_lo)
        new_key = new_key and valid
        if new_key == self.key:
            self.run += 1
            if not self.key:
                self._silence(self.run * self.dt)
            return
        dur = self.run * self.dt
        if self.key:                                   # koniec tonu
            if dur >= 0.012:
                self._mark(dur)
            else:                                      # trzask: ignoruj, wracamy do przerwy
                pass
        else:                                          # początek tonu po przerwie
            self._gap_end(dur)
        self.key = new_key
        self.run = 1

    # ---------------------------------------------------------------- logika Morse'a
    def _update_unit(self, dur):
        self.marks = (self.marks + [dur])[-24:]
        ms = sorted(self.marks)
        if self.inverted:
            self.unit = float(np.median(ms))
            return
        if len(ms) < 2:
            self.unit = min(self.unit, dur) if dur < self.unit * 2 else self.unit
            return
        # 2 grupy: kropki i kreski (k-means 1D)
        lo, hi = ms[0], ms[-1]
        if hi < lo * 2:                                # wszystkie podobne – nie wiadomo czy kropki czy kreski
            if abs(dur - self.unit) > abs(dur - 3 * self.unit):
                self.unit = float(np.median(ms)) / 3
            else:
                self.unit = float(np.median(ms))
            return
        for _ in range(8):
            mid = (lo + hi) / 2
            a = [v for v in ms if v < mid] or [lo]
            b = [v for v in ms if v >= mid] or [hi]
            lo, hi = float(np.mean(a)), float(np.mean(b))
        self.unit = (lo + hi / 3) / 2

    def _mark(self, dur):
        self._update_unit(dur)
        if self.inverted:
            self.pending = dur
        else:
            self.symbol += "." if dur < 2 * self.unit else "-"
        self.space_sent = False

    def _gap_end(self, gap):
        """Ton zaczyna się po przerwie gap."""
        u = self.unit
        if self.inverted:
            if self.pending is not None:
                r = gap / u
                if r < 2.0:
                    self.symbol += "."
                elif r < 3.6:
                    self.symbol += "-"
                elif r < 5.0:
                    self.symbol += "."; self._flush()
                elif r < 9.0:
                    self.symbol += "-"; self._flush()
                else:
                    self.symbol += "."; self._flush(); self._emit(" ")
                self.pending = None
            return
        if gap > 5.0 * u and not self.space_sent:
            self._flush(); self._emit(" ")
        elif gap > 2.0 * u:
            self._flush()

    def _silence(self, gap):
        """Wywoływane w trakcie trwającej przerwy (żeby tekst pojawiał się bez czekania na kolejny ton)."""
        u = self.unit
        if self.inverted:
            if self.pending is not None and gap > 10 * u:
                self.symbol += "."                     # ostatni element nadawania: nie da się rozróżnić
                self.pending = None
                self._flush(); self._emit(" "); self.space_sent = True
            return
        if self.symbol and gap > 2.5 * u:
            self._flush()
        if gap > 6 * u and not self.space_sent:
            self._emit(" "); self.space_sent = True

    def _flush(self):
        if self.symbol:
            self._emit(MORSE.get(self.symbol, "*"))
            self.symbol = ""

    def _emit(self, s):
        self.on_text(s)

    # ---------------------------------------------------------------- widmo (AFC i wodospad)
    def spectrum(self, x, nfft=4096, fmin=200, fmax=1500):
        """Zwraca (częstotliwości, widmo dB) dla wodospadu; przy AFC dostraja ton do najsilniejszego prążka."""
        x = np.asarray(x, dtype=np.float32)
        if len(x) < nfft:
            x = np.pad(x, (0, nfft - len(x)))
        s = np.abs(np.fft.rfft(x[-nfft:] * np.hanning(nfft))) + 1e-9
        f = np.fft.rfftfreq(nfft, 1 / self.fs)
        sel = (f >= fmin) & (f <= fmax)
        f, s = f[sel], s[sel]
        self.spec_acc = s if self.spec_acc is None else self.spec_acc * 0.85 + s * 0.15
        self.spec_n += 1
        if self.afc and self.spec_n % 8 == 0:
            i = int(np.argmax(self.spec_acc))
            if self.spec_acc[i] > 6 * np.median(self.spec_acc) and abs(f[i] - self.tone) > 15:
                self.set_tone(f[i])
        return f, 20 * np.log10(s)

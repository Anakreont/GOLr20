"""
QO-100 – przeliczanie częstotliwości dla transwertera SP3OSJ (pośrednia 29,0–29,5 MHz na odbiór i nadawanie).

  downlink (3 cm) = IF + LO_RX − błąd LNB        LO_RX = 10 460,5 MHz  (29,000 MHz -> 10 489,500 MHz)
  uplink  (13 cm) = IF + LO_TX + błąd TX           LO_TX =  2 371,0 MHz  (29,000 MHz ->  2 400,000 MHz)
  satelita przenosi 2400 -> 10489,5 MHz, czyli o LO_RX − LO_TX = 8 089,5 MHz.

Błąd LNB wyznacza się z dolnego beacona CW (10 489,500 MHz): mierzymy, gdzie go naprawdę słychać.
Żeby własny sygnał wylądował dokładnie na stacji, której słuchamy, nadajnik trzeba przesunąć o
−(błąd LNB + błąd TX) – w IC-7300 robi to ΔTX (XIT).
"""
import numpy as np

LO_RX = 10_460_500_000
LO_TX = 2_371_000_000
BEACON = 10_489_500_000


def signal_if(dial_hz, mode, tone_hz, pitch_hz):
    """Częstotliwość nośnej sygnału słyszanego tonem tone_hz przy wyświetlaczu dial_hz (pośrednia)."""
    if mode == "CW":
        return dial_hz + (tone_hz - pitch_hz)
    if mode == "CW-R":
        return dial_hz - (tone_hz - pitch_hz)
    if mode in ("LSB", "RTTY-R"):
        return dial_hz - tone_hz
    return dial_hz + tone_hz          # USB, RTTY i reszta


def precise_peak(x, fs, f0, span=60.0):
    """Dokładna częstotliwość najsilniejszego prążka w f0 ± span Hz (FFT z dopełnieniem + interpolacja paraboliczna)."""
    x = np.asarray(x, float)
    if len(x) < fs // 4:
        return None, 0.0
    x = x - x.mean()
    n = 1 << int(np.ceil(np.log2(len(x) * 4)))
    sp = np.abs(np.fft.rfft(x * np.hanning(len(x)), n))
    f = np.fft.rfftfreq(n, 1 / fs)
    sel = np.where((f > f0 - span) & (f < f0 + span))[0]
    if len(sel) < 3:
        return None, 0.0
    i = sel[np.argmax(sp[sel])]
    a, b, c = np.log(sp[i - 1:i + 2] + 1e-12)
    d = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) != 0 else 0.0
    snr = 20 * np.log10(sp[i] / (np.median(sp[sel]) + 1e-12))
    return f[i] + d * (f[1] - f[0]), float(snr)


class QO100:
    def __init__(self, lo_rx=LO_RX, lo_tx=LO_TX, beacon=BEACON, corr_rx=0.0, corr_tx=0.0):
        self.lo_rx, self.lo_tx, self.beacon = lo_rx, lo_tx, beacon
        self.corr_rx = float(corr_rx)     # błąd LNB [Hz]: o tyle za wysoko słychać sygnały
        self.corr_tx = float(corr_tx)     # błąd toru nadawczego [Hz] (wpisywany ręcznie, domyślnie 0)

    def downlink(self, if_hz):
        return if_hz + self.lo_rx - self.corr_rx

    def uplink(self, if_hz):
        """Gdzie trafi nasz nadajnik przy tej pośredniej (bez ΔTX)."""
        return if_hz + self.lo_tx + self.corr_tx

    def uplink_for(self, downlink_hz):
        """Częstotliwość nadawania, przy której nasz sygnał pojawi się na downlink_hz."""
        return downlink_hz - (self.lo_rx - self.lo_tx)

    def calibrate(self, beacon_if_hz):
        self.corr_rx = beacon_if_hz + self.lo_rx - self.beacon
        return self.corr_rx

    def xit(self):
        """ΔTX [Hz], żeby nadawać tam, gdzie słyszymy (zero-beat przez satelitę)."""
        return -round(self.corr_rx + self.corr_tx)


def khz(hz):
    """10489523400 -> '10 489 523,40 kHz'"""
    s = f"{hz / 1000:,.2f}".replace(",", " ").replace(".", ",")
    return s + " kHz"

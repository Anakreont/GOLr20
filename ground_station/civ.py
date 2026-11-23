"""
Sterowanie IC-7300 przez CI-V (wirtualny port COM po kablu USB).

Komendy (Icom CI-V, IC-7300):
  0x03            odczyt częstotliwości
  0x04            odczyt emisji (0x03 = CW, 0x07 = CW-R)
  0x00            radio samo wysyła zmianę częstotliwości (CI-V Transceive = ON)
  0x17 + ASCII    nadaj tekst CW wbudowanym kluczem radia (max 30 znaków na ramkę)
  0x17 0xFF       przerwij nadawanie CW
  0x14 0x0C       prędkość klucza (0000..0255 BCD = 6..48 WPM)
  0x14 0x09       ton CW / CW pitch (0000..0255 BCD = 300..900 Hz) – do przeliczeń QO-100
  0x05 + 5 B BCD  ustaw częstotliwość
  0x21 0x00       przesunięcie RIT/ΔTX (2 B BCD, najmłodszy pierwszy, + bajt znaku 00/01)
  0x21 0x02       ΔTX (XIT) wł./wył.
  0x1C 0x00       nadawanie wł./wył. (PTT) – zakładka „FT8 balon”
  0x26 0x00       emisja wybranego VFO z trybem DATA (01 01 01 = USB-D, filtr 1)
"""
import queue, threading, time
import serial

PREAMBLE = b"\xFE\xFE"
EOM = 0xFD
CW_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/?.,-=+@: '()!^")


def bcd2(b1, b2):
    """2 bajty BCD 0000..0255 (starszy pierwszy) -> liczba."""
    return (b1 & 0x0F) * 100 + (b2 >> 4) * 10 + (b2 & 0x0F)


def freq_bcd(hz):
    """Hz -> 5 bajtów BCD (najmłodszy pierwszy)."""
    hz = int(round(hz))
    out = []
    for _ in range(5):
        d = hz % 100
        out.append((d // 10) << 4 | d % 10)
        hz //= 100
    return bytes(out)


def bcd_freq(data):
    """5 bajtów BCD (najmłodszy pierwszy) -> Hz."""
    hz, mul = 0, 1
    for b in data[:5]:
        hz += ((b & 0x0F) + 10 * (b >> 4)) * mul
        mul *= 100
    return hz


class IC7300:
    def __init__(self, port, baud=115200, radio_addr=0x94, ctrl_addr=0xE0, on_freq=None, on_mode=None):
        self.radio = radio_addr
        self.ctrl = ctrl_addr
        self.on_freq = on_freq or (lambda hz: None)
        self.on_mode = on_mode or (lambda m: None)
        self.ser = serial.serial_for_url(port, baud, timeout=0.1)
        # DTR/RTS w stanie nieaktywnym: przy ustawieniu "USB Keying (CW) = DTR" nie kluczujemy przypadkiem nadajnika
        self.ser.dtr = False
        self.ser.rts = False
        self.lock = threading.Lock()
        self.stop_tx = threading.Event()
        self.tx_thread = None
        self.alive = True
        self.freq = 0
        self.mode = None
        self.pitch = None          # ton CW ustawiony w radiu [Hz]
        self.wpm = None            # tempo klucza ustawione w radiu (gałka KEY SPEED)
        self.ack = queue.Queue()   # odpowiedzi radia FB (OK) / FA (NG)
        self.txq = queue.Queue()   # kolejka kawałków tekstu do nadania
        self.tx_lock = threading.Lock()
        self.on_tx = lambda state, info="": None   # (True/False, opis) – nadaje / skończył / błąd
        self.busy = False
        self.sched = []            # plan nadawania: (czas startu znaku, id komunikatu, nr znaku) – podświetlanie liter
        self.sched_lock = threading.Lock()
        threading.Thread(target=self._tx_worker, daemon=True).start()
        threading.Thread(target=self._reader, daemon=True).start()

    def close(self):
        self.alive = False
        self.abort()
        try:
            self.ser.close()
        except Exception:
            pass

    # ------------------------------------------------------------------ niskopoziomowe
    def _send(self, cmd, data=b""):
        frame = PREAMBLE + bytes([self.radio, self.ctrl]) + bytes(cmd) + bytes(data) + bytes([EOM])
        with self.lock:
            self.ser.write(frame)

    def _reader(self):
        buf = b""
        while self.alive:
            try:
                buf += self.ser.read(64)
            except Exception:
                time.sleep(0.5)
                continue
            while True:
                s = buf.find(PREAMBLE)
                if s < 0:
                    buf = buf[-1:]
                    break
                e = buf.find(bytes([EOM]), s)
                if e < 0:
                    buf = buf[s:]
                    break
                frame, buf = buf[s:e + 1], buf[e + 1:]
                self._frame(frame)

    def _frame(self, f):
        if len(f) < 6:
            return
        to, frm, cmd, data = f[2], f[3], f[4], f[5:-1]
        if frm != self.radio:                       # echo naszych ramek (CI-V USB Echo Back = ON)
            return
        if cmd in (0x00, 0x03) and len(data) >= 5:
            self.freq = bcd_freq(data)
            self.on_freq(self.freq)
        elif cmd in (0x01, 0x04) and len(data) >= 1:
            self.mode = {0x00: "LSB", 0x01: "USB", 0x02: "AM", 0x03: "CW", 0x04: "RTTY", 0x05: "FM",
                         0x07: "CW-R", 0x08: "RTTY-R"}.get(data[0], hex(data[0]))
            self.on_mode(self.mode)
        elif cmd in (0xFB, 0xFA):
            self.ack.put(cmd == 0xFB)
        elif cmd == 0x14 and len(data) >= 3 and data[0] == 0x0C:
            v = bcd2(data[1], data[2])
            self.wpm = round(6 + v * 42 / 255)
        elif cmd == 0x14 and len(data) >= 3 and data[0] == 0x09:
            v = bcd2(data[1], data[2])
            self.pitch = 300 + round(v * 600 / 255 / 5) * 5

    # ------------------------------------------------------------------ polecenia
    def poll(self):
        self._send([0x03])
        time.sleep(0.05)
        self._send([0x04])
        time.sleep(0.05)
        self._send([0x14, 0x09])
        time.sleep(0.05)
        self._send([0x14, 0x0C])

    def set_freq(self, hz):
        self._send([0x05], freq_bcd(hz))

    def ptt(self, on):
        """Nadawanie wł./wył. (do FT8: dźwięk idzie kartą USB radia, DATA MOD = USB)."""
        self._send([0x1C, 0x00], bytes([1 if on else 0]))

    def set_usb_data(self):
        """Emisja USB-D (USB z trybem DATA), filtr 1."""
        self._send([0x26, 0x00], bytes([0x01, 0x01, 0x01]))
        self.mode = "USB"

    def set_xit(self, hz):
        """Ustawia przesunięcie ΔTX (±9999 Hz) i włącza ΔTX. Uwaga: w IC-7300 RIT i ΔTX mają wspólne przesunięcie."""
        hz = int(round(hz))
        if abs(hz) > 9999:
            raise ValueError("ΔTX w IC-7300 to maks. ±9,999 kHz")
        a = abs(hz)
        lo, hi = a % 100, a // 100
        self._send([0x21, 0x00], bytes([(lo // 10) << 4 | lo % 10, (hi // 10) << 4 | hi % 10, 1 if hz < 0 else 0]))
        time.sleep(0.05)
        self._send([0x21, 0x01], b"\x00")      # RIT wył. – inaczej to samo przesunięcie zmieni też odbiór
        time.sleep(0.05)
        self._send([0x21, 0x02], b"\x01")

    def xit_off(self):
        self._send([0x21, 0x02], b"\x00")

    def set_wpm(self, wpm):
        wpm = max(6, min(48, int(wpm)))
        self.wpm = wpm
        v = round((wpm - 6) * 255 / 42)
        self._send([0x14, 0x0C], bytes([v // 100, ((v // 10) % 10) << 4 | (v % 10)]))

    def abort(self):
        """STOP: czyści kolejkę i przerywa nadawanie w radiu."""
        self.stop_tx.set()
        with self.sched_lock:
            self.sched = []
        try:
            while True:
                self.txq.get_nowait()
        except queue.Empty:
            pass
        try:
            self._send([0x17], b"\xFF")
        except Exception:
            pass

    def _cmd_ack(self, cmd, data, timeout=0.5):
        """Wysyła komendę i czeka na OK/NG radia. True = OK, False = NG, None = brak odpowiedzi."""
        with self.tx_lock:
            while not self.ack.empty():
                self.ack.get_nowait()
            self._send(cmd, data)
            try:
                return self.ack.get(timeout=timeout)
            except queue.Empty:
                return None

    @staticmethod
    def chunk_text(text):
        """Tekst -> kawałki po maks. 29 znaków (+ spacja na końcu = 30), bez cięcia słów."""
        chunks, cur = [], ""
        for w in text.split(" "):
            while len(w) > 29:
                chunks.append(w[:29]); w = w[29:]
            if len(cur) + len(w) + (1 if cur else 0) > 29:
                chunks.append(cur); cur = w
            else:
                cur = (cur + " " + w) if cur else w
        if cur:
            chunks.append(cur)
        return chunks

    @staticmethod
    def duration(ch, wpm):
        from cw_decoder import TEXT2MORSE
        units = 0
        for c in ch:
            if c == " ":
                units += 4
                continue
            m = TEXT2MORSE.get(c, "")
            units += sum(1 if e == "." else 3 for e in m) + len(m) - 1 + 3
        return units * 1.2 / wpm

    def send_cw(self, text, wpm, msg_id=None):
        """Dokłada tekst do kolejki (nie przerywa tego, co już idzie). Kawałki po 30 znaków.
        msg_id – numer komunikatu; tx_pos() mówi potem, który jego znak radio właśnie nadaje."""
        text = "".join(c for c in text.upper() if c in CW_CHARS)
        if not text:
            return
        self.stop_tx.clear()
        pos = 0
        for ch in self.chunk_text(text):          # spacja na końcu każdego kawałka: kolejne teksty się nie sklejają
            off = text.find(ch, pos)
            off = pos if off < 0 else off
            pos = off + len(ch)
            self.txq.put((ch + " ", wpm, msg_id, off))

    def tx_pos(self):
        """(id komunikatu, nr znaku) nadawanego teraz – wg planu czasowego (tempo z radia) – albo None."""
        now = time.time()
        with self.sched_lock:
            while len(self.sched) > 1 and self.sched[1][0] <= now:
                self.sched.pop(0)
            if not self.sched or self.sched[0][0] > now:
                return None
            t, mid, idx, end = self.sched[0]
            if end:                                 # znacznik końca kawałka
                if len(self.sched) == 1:
                    self.sched.pop(0)
                return (mid, idx)
            return (mid, idx)

    def _plan(self, ch, wpm, start, msg_id, off):
        t = start
        plan = []
        for i, c in enumerate(ch):
            plan.append((t, msg_id, off + i, False))
            t += self.duration(c, wpm)
        plan.append((t, msg_id, off + len(ch.rstrip()), True))
        with self.sched_lock:
            self.sched = [p for p in self.sched if p[0] < start] + plan

    def _tx_worker(self):
        busy_until = 0.0
        while self.alive:
            try:
                ch, wpm_gui, msg_id, off = self.txq.get(timeout=0.2)
            except queue.Empty:
                if self.busy and time.time() > busy_until:
                    self.busy = False
                    self.on_tx(False, "")
                continue
            wpm = self.wpm or wpm_gui                       # tempo z radia, gdy znane
            # radio odrzuca (NG) nowy tekst, gdy jeszcze nadaje poprzedni – ponawiamy do skutku (maks. ~20 s)
            give_up = time.time() + max(20.0, busy_until - time.time() + 10)
            res, tries = None, 0
            while not self.stop_tx.is_set() and time.time() < give_up:
                res = self._cmd_ack([0x17], ch.encode("ascii"))
                tries += 1
                if res is not False:                        # OK albo radio nie potwierdza (Echo/ACK wył.)
                    break
                time.sleep(0.3)
            if self.stop_tx.is_set():
                continue
            if res is False:
                self.on_tx(False, "radio odrzuca tekst (NG) – sprawdź emisję CW i BK-IN")
                continue
            if not self.busy:
                self.busy = True
                self.on_tx(True, "")
            if tries > 10:
                self.on_tx(True, f"radio długo zajęte – wysłane za {tries}. razem")
            if res is None:
                self.on_tx(True, "radio nie potwierdza CI-V – nadaję na wyczucie czasu")
            start = max(time.time(), busy_until)
            busy_until = start + self.duration(ch, wpm) + 0.1
            self._plan(ch, wpm, start, msg_id, off)
            # następny kawałek wysyłamy chwilę przed końcem bieżącego – radio i tak go odrzuci, jeśli za wcześnie
            while time.time() < busy_until - 0.4 and not self.stop_tx.is_set():
                time.sleep(0.05)

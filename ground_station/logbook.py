"""
Prosty logger GOLbase: zapis QSO do pliku ADIF i wysłanie do Log4OM przez UDP.

Do Log4OM idzie ten sam komunikat, który wysyła JTDX/WSJT-X przy logowaniu („Logged ADIF”, typ 12),
na ten sam port (domyślnie 127.0.0.1:2237). Log4OM przyjmuje go połączeniem „JTDX/WSJT-X UDP inbound”,
więc nie trzeba niczego nowego ustawiać. Gdy działa qo100_proxy.py, QSO przechodzi przez niego bez zmian
(GOLbase sam podaje już częstotliwości QO-100).
"""
import os, socket, struct, time

MAGIC = 0xADBCCBDA
BANDS = [(1.8, 2.0, "160m"), (3.5, 4.0, "80m"), (5.06, 5.45, "60m"), (7.0, 7.3, "40m"), (10.1, 10.15, "30m"),
         (14.0, 14.35, "20m"), (18.068, 18.168, "17m"), (21.0, 21.45, "15m"), (24.89, 24.99, "12m"),
         (28.0, 29.7, "10m"), (50, 54, "6m"), (70, 71, "4m"), (144, 148, "2m"), (430, 440, "70cm"),
         (1240, 1300, "23cm"), (2300, 2450, "13cm"), (10000, 10500, "3cm")]


def band_of(mhz):
    for lo, hi, b in BANDS:
        if lo <= mhz <= hi:
            return b
    return ""


def adif_record(f):
    """dict -> rekord ADIF zakończony <EOR> (puste pola pomijane)."""
    out = []
    for k, v in f.items():
        v = str(v).strip() if v is not None else ""
        if v:
            out.append(f"<{k.upper()}:{len(v.encode('utf-8'))}>{v}")
    return " ".join(out) + " <EOR>"


def _qstr(s):
    b = s.encode("utf-8")
    return struct.pack(">I", len(b)) + b


def wsjtx_logged_adif(record, client_id="GOLbase"):
    """Datagram WSJT-X typu 12 (Logged ADIF)."""
    text = "\n<adif_ver:5>3.1.0\n<programid:7>GOLbase\n<EOH>\n" + record
    return struct.pack(">III", MAGIC, 2, 12) + _qstr(client_id) + _qstr(text)


def send_log4om(record, addr="127.0.0.1:2237"):
    host, port = addr.rsplit(":", 1)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(wsjtx_logged_adif(record), (host, int(port)))


def append_adi(path, record):
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as f:
        if new:
            f.write("Log GOLbase\n<adif_ver:5>3.1.0\n<programid:7>GOLbase\n<EOH>\n")
        f.write(record + "\n")


def make_qso(call, t_on, t_off, freq_hz, rst_s, rst_r, name="", comment="", qo=None, my_call="", tx_pwr=""):
    """Pola QSO. qo = (uplink_hz, downlink_hz) przy pracy przez QO-100."""
    f = {"call": call.upper(), "qso_date": time.strftime("%Y%m%d", t_on), "time_on": time.strftime("%H%M%S", t_on),
         "qso_date_off": time.strftime("%Y%m%d", t_off), "time_off": time.strftime("%H%M%S", t_off),
         "mode": "CW", "rst_sent": rst_s, "rst_rcvd": rst_r, "name": name, "comment": comment,
         "station_callsign": my_call, "tx_pwr": tx_pwr}
    if qo:
        up, dn = qo
        f.update(freq=f"{up / 1e6:.6f}", band=band_of(up / 1e6), freq_rx=f"{dn / 1e6:.6f}",
                 band_rx=band_of(dn / 1e6), prop_mode="SAT", sat_name="QO-100")
    else:
        f.update(freq=f"{freq_hz / 1e6:.6f}", band=band_of(freq_hz / 1e6))
    return f

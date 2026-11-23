"""
Kraj (DXCC) ze znaku wywoławczego.

1. Jeśli jest plik cty.dat (country-files.com, AD1C) – dokładne dane: kraj, kontynent, strefa CQ/ITU, położenie
   (azymut i odległość od nas). Program szuka go w Dokumenty\\GOLbase, potem obok programu (dołączany do instalatora),
   i raz w miesiącu sam pobiera świeży do Dokumenty\\GOLbase.
2. Bez cty.dat – wbudowana tabela prefiksów (główne kraje, bez wysp i wyjątków).
"""
import math, os, re, threading, time, urllib.request

CTY_URLS = ["https://www.country-files.com/cty/cty.dat", "https://www.country-files.com/bigcty/cty.dat"]

# Kraj | kontynent | prefiksy (AA-AK = zakres ostatniej litery). Dłuższy prefiks wygrywa.
_TAB = """
Polska|EU|SN-SR 3Z HF
Niemcy|EU|DA-DR
Czechy|EU|OK OL
Słowacja|EU|OM
Ukraina|EU|UR-UZ EM-EO
Białoruś|EU|EU-EW
Litwa|EU|LY
Łotwa|EU|YL
Estonia|EU|ES
Węgry|EU|HA HG
Rumunia|EU|YO-YR
Bułgaria|EU|LZ
Serbia|EU|YT YU
Chorwacja|EU|9A
Słowenia|EU|S5
Bośnia i Hercegowina|EU|E7 T9
Czarnogóra|EU|4O
Macedonia Płn.|EU|Z3
Albania|EU|ZA
Kosowo|EU|Z6
Grecja|EU|SV-SZ J4
Kreta|EU|SV9 J49
Dodekanez|EU|SV5 J45
Turcja|AS|TA-TC YM
Cypr|AS|5B C4 H2 P3
Malta|EU|9H
Włochy|EU|I
Sardynia|EU|IS0 IM0
San Marino|EU|T7
Watykan|EU|HV
Hiszpania|EU|EA-EH AM-AO
Baleary|EU|EA6 EB6 EC6 ED6 EE6 EF6 EG6 EH6
Wyspy Kanaryjskie|AF|EA8 EB8 EC8 ED8 EE8 EF8 EG8 EH8
Ceuta i Melilla|AF|EA9 EB9 EC9 ED9 EE9 EF9 EG9 EH9
Portugalia|EU|CQ-CT
Madera|AF|CT3 CQ3 CR3 CS3
Azory|EU|CU
Francja|EU|F TM TH HW-HY
Korsyka|EU|TK
Monako|EU|3A
Andora|EU|C3
Belgia|EU|ON-OT
Holandia|EU|PA-PI
Luksemburg|EU|LX
Szwajcaria|EU|HB HE
Liechtenstein|EU|HB0
Austria|EU|OE
Dania|EU|OU OV OW OZ 5P 5Q
Wyspy Owcze|EU|OY
Grenlandia|NA|OX XP
Szwecja|EU|SA-SM 7S 8S
Norwegia|EU|LA-LN
Svalbard|EU|JW
Jan Mayen|EU|JX
Finlandia|EU|OF-OJ
Wyspy Alandzkie|EU|OH0 OG0 OF0 OJ0
Islandia|EU|TF
Irlandia|EU|EI EJ
Anglia|EU|G M 2E
Walia|EU|GW MW 2W GC
Szkocja|EU|GM MM 2M GS
Irlandia Płn.|EU|GI MI 2I GN
Wyspa Man|EU|GD MD 2D GT
Jersey|EU|GJ MJ 2J GH
Guernsey|EU|GU MU 2U GP
Gibraltar|EU|ZB ZG
Mołdawia|EU|ER
Gruzja|AS|4L
Armenia|AS|EK
Azerbejdżan|AS|4J 4K
Kazachstan|AS|UN-UQ
Uzbekistan|AS|UJ-UM
Kirgistan|AS|EX
Tadżykistan|AS|EY
Turkmenistan|AS|EZ
Japonia|AS|JA-JS 7J-7N 8J-8N
Chiny|AS|B
Tajwan|AS|BM-BQ BU-BX
Korea Płd.|AS|HL DS DT D7 D8 D9 6K-6N
Korea Płn.|AS|P5
Mongolia|AS|JT-JV
Indie|AS|VU AT-AW 8T-8Y
Pakistan|AS|AP-AS 6P-6S
Bangladesz|AS|S2 S3
Sri Lanka|AS|4S
Nepal|AS|9N
Tajlandia|AS|HS E2
Wietnam|AS|3W XV
Filipiny|OC|DU-DZ 4D-4I
Indonezja|OC|YB-YH PK-PO 7A-7I 8A-8I
Malezja|AS|9M 9W
Malezja Wsch.|OC|9M6 9M8 9W6 9W8
Singapur|AS|9V S6
Hongkong|AS|VR
Makau|AS|XX9
Izrael|AS|4X 4Z
Palestyna|AS|E4
Jordania|AS|JY
Liban|AS|OD
Syria|AS|YK
Irak|AS|YI
Iran|AS|EP EQ 9B-9D
Arabia Saudyjska|AS|HZ 7Z 8Z
Zjedn. Emiraty Arabskie|AS|A6
Katar|AS|A7
Bahrajn|AS|A9
Kuwejt|AS|9K
Oman|AS|A4
Jemen|AS|7O
Afganistan|AS|YA T6
Egipt|AF|SU
Libia|AF|5A
Tunezja|AF|3V TS
Algieria|AF|7R 7T-7Y
Maroko|AF|CN 5C-5G
RPA|AF|ZR-ZU
Namibia|AF|V5
Kenia|AF|5Y 5Z
Nigeria|AF|5N 5O
Ghana|AF|9G
Senegal|AF|6V 6W
Etiopia|AF|ET 9E 9F
Uganda|AF|5X
Tanzania|AF|5H 5I
Zambia|AF|9I 9J
Zimbabwe|AF|Z2
Angola|AF|D2 D3
Mozambik|AF|C8 C9
Madagaskar|AF|5R 5S
Mauritius|AF|3B8
Reunion|AF|FR
Kamerun|AF|TJ
Wybrzeże Kości Słoniowej|AF|TU
Mali|AF|TZ
Botswana|AF|A2 8O
Sudan|AF|ST
Gambia|AF|C5
Liberia|AF|EL 5L
Sierra Leone|AF|9L
Republika Zielonego Przylądka|AF|D4
Rwanda|AF|9X
Burundi|AF|9U
DR Konga|AF|9Q-9T
Gabon|AF|TR
Benin|AF|TY
Togo|AF|5V
Burkina Faso|AF|XT
Niger|AF|5U
Czad|AF|TT
Mauretania|AF|5T
Gwinea|AF|3X
Somalia|AF|T5 6O
Dżibuti|AF|J2
Erytrea|AF|E3
Eswatini|AF|3DA
Lesotho|AF|7P
Malawi|AF|7Q
Seszele|AF|S7
Komory|AF|D6
USA|NA|K N W AA-AK
Alaska|NA|KL AL NL WL
Hawaje|OC|KH6 KH7 AH6 NH6 WH6
Portoryko|NA|KP4 NP4 WP4 KP3
Guam|OC|KH2 AH2 NH2 WH2
Samoa Amerykańskie|OC|KH8
Kanada|NA|VA-VG VO VY CF-CK CY CZ XJ-XO
Meksyk|NA|XA-XI 4A-4C 6D-6J
Kuba|NA|CM CO T4
Haiti|NA|HH 4V
Dominikana|NA|HI
Jamajka|NA|6Y
Bahamy|NA|C6
Barbados|NA|8P
Trynidad i Tobago|SA|9Y 9Z
Gwatemala|NA|TG TD
Salwador|NA|YS HU
Honduras|NA|HR HQ
Nikaragua|NA|YN H6 H7 HT
Kostaryka|NA|TI TE
Panama|NA|HO HP 3E 3F H3 H8 H9
Kolumbia|SA|HJ HK 5J 5K
Wenezuela|SA|YV-YY 4M
Ekwador|SA|HC HD
Galapagos|SA|HC8 HD8
Peru|SA|OA-OC 4T
Boliwia|SA|CP
Chile|SA|CA-CE XQ XR 3G
Argentyna|SA|LO-LW AY AZ
Urugwaj|SA|CV-CX
Paragwaj|SA|ZP
Brazylia|SA|PP-PY ZV-ZZ
Gujana|SA|8R
Surinam|SA|PZ
Gujana Francuska|SA|FY
Martynika|NA|FM
Gwadelupa|NA|FG
Aruba|SA|P4
Curaçao|SA|PJ2
Bonaire|SA|PJ4
Sint Maarten|NA|PJ7
Bermudy|NA|VP9
Kajmany|NA|ZF
Falklandy|SA|VP8
Australia|OC|VH-VN AX
Nowa Zelandia|OC|ZL ZM
Fidżi|OC|3D2
Tonga|OC|A3
Samoa|OC|5W
Polinezja Francuska|OC|FO
Nowa Kaledonia|OC|FK
Papua-Nowa Gwinea|OC|P2
Wyspy Salomona|OC|H4
Vanuatu|OC|YJ
Kiribati|OC|T3
Wyspy Marshalla|OC|V7
Mikronezja|OC|V6
Palau|OC|T8
Nauru|OC|C2
Tuvalu|OC|T2
Wyspy Cooka|OC|E5
"""

_ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_SKIP_SUFFIX = {"P", "M", "MM", "AM", "QRP", "A", "B", "LH", "R", "T", "J", "E", "LGT"}


def _expand(p):
    if "-" in p:
        a, b = p.split("-")
        out = []
        for ch in _ALPHA[_ALPHA.index(a[-1]):_ALPHA.index(b[-1]) + 1]:
            out.append(a[:-1] + ch)
        return out
    return [p]


def _builtin():
    tab = {}
    for line in _TAB.strip().splitlines():
        name, cont, prefs = line.split("|")
        for p in prefs.split():
            for q in _expand(p):
                tab[q] = {"name": name, "cont": cont}
    return tab


def base_call(call):
    """Znak -> (część do szukania kraju, morski/lotniczy?). SP9/DL1ABC -> SP9; DL1ABC/P -> DL1ABC."""
    c = re.sub(r"[^A-Z0-9/]", "", call.upper())
    parts = [p for p in c.split("/") if p]
    if not parts:
        return "", False
    mm = any(p in ("MM", "AM") for p in parts[1:])
    parts = [parts[0]] + [p for p in parts[1:] if p not in _SKIP_SUFFIX and not p.isdigit()]
    if len(parts) == 1:
        return parts[0], mm
    # prefiks przed albo po znaku: krótsza część to prefiks kraju (np. SP9/DL1ABC, DL1ABC/OH0)
    a, b = parts[0], parts[1]
    return (a if len(a) <= len(b) else b), mm


def _russia(call, prefix_hit):
    """Rosja w tabeli wbudowanej: cyfra 2 = Kaliningrad, 8/9/0 = Azja."""
    if not (call[:1] == "R" or (call[:1] == "U" and call[1:2] in "ABCDEFGHI")):
        return None
    d = next((ch for ch in call if ch.isdigit()), "")
    if d == "2":
        return {"name": "Obwód Kaliningradzki", "cont": "EU"}
    if d in "890":
        return {"name": "Rosja azjatycka", "cont": "AS"}
    return {"name": "Rosja europejska", "cont": "EU"}


class Kraje:
    def __init__(self, data_dir, app_dir, my_lat=52.0, my_lon=19.0):
        self.data_dir, self.app_dir = data_dir, app_dir
        self.my_lat, self.my_lon = my_lat, my_lon
        self.builtin = _builtin()
        self.pref, self.exact = {}, {}
        self.source = "tabela wbudowana"
        self.load()

    # ---------------------------------------------------------------- cty.dat
    def _cty_path(self):
        for d in (self.data_dir, self.app_dir):
            p = os.path.join(d, "cty.dat")
            if os.path.exists(p) and os.path.getsize(p) > 10000:
                return p
        return None

    def load(self):
        p = self._cty_path()
        if not p:
            return
        try:
            pref, exact = self.parse_cty(open(p, encoding="latin-1").read())
            if len(pref) > 1000:
                self.pref, self.exact = pref, exact
                self.source = f"cty.dat ({time.strftime('%d.%m.%Y', time.localtime(os.path.getmtime(p)))})"
        except Exception:
            pass

    @staticmethod
    def parse_cty(txt):
        pref, exact = {}, {}
        for rec in txt.split(";"):
            rec = rec.strip()
            if not rec:
                continue
            f = rec.split(":")
            if len(f) < 9:
                continue
            ent = {"name": f[0].strip(), "cq": f[1].strip(), "itu": f[2].strip(), "cont": f[3].strip(),
                   "lat": float(f[4]), "lon": -float(f[5]), "main": f[7].strip().lstrip("*")}
            for a in f[8].replace("\n", "").split(","):
                a = a.strip()
                if not a:
                    continue
                e = dict(ent)
                m = re.search(r"\((\d+)\)", a)
                if m:
                    e["cq"] = m.group(1)
                m = re.search(r"\[(\d+)\]", a)
                if m:
                    e["itu"] = m.group(1)
                m = re.search(r"<([-\d.]+)/([-\d.]+)>", a)
                if m:
                    e["lat"], e["lon"] = float(m.group(1)), -float(m.group(2))
                m = re.search(r"\{(\w+)\}", a)
                if m:
                    e["cont"] = m.group(1)
                key = re.sub(r"[\(\[<{~].*", "", a)
                if key.startswith("="):
                    exact[key[1:]] = e
                else:
                    pref[key] = e
        return pref, exact

    def update_async(self, max_age_days=30, on_done=None):
        """Pobiera świeży cty.dat do Dokumenty\\GOLbase, jeśli nie ma albo starszy niż max_age_days."""
        p = os.path.join(self.data_dir, "cty.dat")
        if os.path.exists(p) and time.time() - os.path.getmtime(p) < max_age_days * 86400:
            return

        def run():
            for url in CTY_URLS:
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "GOLbase"})
                    data = urllib.request.urlopen(req, timeout=20).read()
                    if len(data) > 10000 and b"Poland" in data:
                        with open(p + ".tmp", "wb") as f:
                            f.write(data)
                        os.replace(p + ".tmp", p)
                        self.load()
                        if on_done:
                            on_done(self.source)
                        return
                except Exception:
                    continue
        threading.Thread(target=run, daemon=True).start()

    # ---------------------------------------------------------------- szukanie
    def lookup(self, call):
        """Znak -> dict(name, cont, [cq, itu, lat, lon], [az, km]) albo None."""
        full = re.sub(r"[^A-Z0-9/]", "", call.upper())
        b, mm = base_call(full)
        if mm:
            return {"name": "praca morska/lotnicza (/MM, /AM)", "cont": ""}
        if len(b) < 2:
            return None
        e = None
        if self.pref:
            e = self.exact.get(full) or self.exact.get(b)
            if not e:
                for n in range(len(b), 0, -1):
                    e = self.pref.get(b[:n])
                    if e:
                        break
        if not e:
            e = _russia(b, None)
        if not e:
            for n in range(len(b), 0, -1):
                e = self.builtin.get(b[:n])
                if e:
                    break
        if not e:
            return None
        e = dict(e)
        if "lat" in e:
            e["az"], e["km"] = self.bearing(e["lat"], e["lon"])
        return e

    def bearing(self, lat, lon):
        f1, f2 = math.radians(self.my_lat), math.radians(lat)
        dl = math.radians(lon - self.my_lon)
        az = math.degrees(math.atan2(math.sin(dl) * math.cos(f2),
                                     math.cos(f1) * math.sin(f2) - math.sin(f1) * math.cos(f2) * math.cos(dl)))
        c = math.acos(max(-1, min(1, math.sin(f1) * math.sin(f2) + math.cos(f1) * math.cos(f2) * math.cos(dl))))
        return round(az % 360), round(c * 6371)

    def describe(self, call, my_call=""):
        e = self.lookup(call)
        if not e:
            return ""
        mine = self.lookup(my_call) if my_call else None
        if mine and mine.get("name") == e["name"]:
            e.pop("az", None)                       # własny kraj – azymut do środka kraju nic nie mówi
        s = e["name"]
        if e.get("cont"):
            s += f"  {e['cont']}"
        if e.get("cq"):
            s += f"  CQ {e['cq']}  ITU {e['itu']}"
        if "az" in e and e["km"] > 30:
            s += f"  az {e['az']}°  {e['km']:,} km".replace(",", " ")
        return s

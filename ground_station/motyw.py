"""
Ciemny wygląd GOLbase (od 1.6) – kolory jak na stronie „Kontrola lotów”: granat, pomarańczowe nagłówki.
Jedno miejsce na kolory i style ttk; reszta programu bierze stąd nazwy kolorów.
"""
import sys
import tkinter as tk
from tkinter import ttk

TLO = "#0b0f1a"          # tło okna
PANEL = "#121829"        # karty, ramki
POLE = "#0e1422"         # pola tekstowe, listy
LINIA = "#243049"        # obramowania
TEKST = "#d8e1f0"
SZARY = "#7f8aa3"
AKCENT = "#ff9f1c"       # pomarańcz
ZIELONY = "#3ccf6e"
NIEBIESKI = "#39c5e8"
CZERWONY = "#ff5c5c"
STOP = "#c62828"
ZAZN = "#1d3557"         # zaznaczenie
BALON_TLO = "#3a2a08"    # wiersz z ramką balonu
CZC = "Segoe UI" if sys.platform == "win32" else "DejaVu Sans"
MONO = "Consolas" if sys.platform == "win32" else "DejaVu Sans Mono"


def ciemna_belka(okno):
    """Ciemna belka tytułowa (Windows 10/11); gdzie indziej nic nie robi."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        okno.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(okno.winfo_id())
        wart = ctypes.c_int(1)
        for atrybut in (20, 19):          # DWMWA_USE_IMMERSIVE_DARK_MODE (nowy i stary numer)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, atrybut, ctypes.byref(wart), ctypes.sizeof(wart))
    except Exception:
        pass


def zastosuj(root):
    s = ttk.Style(root)
    s.theme_use("clam")
    root.configure(bg=TLO)
    for wzor, wart in (("*background", TLO), ("*foreground", TEKST), ("*Text.background", POLE),
                       ("*Listbox.background", POLE), ("*Entry.background", POLE), ("*insertBackground", TEKST),
                       ("*selectBackground", ZAZN), ("*selectForeground", "#ffffff"),
                       ("*TCombobox*Listbox.background", POLE), ("*TCombobox*Listbox.foreground", TEKST),
                       ("*TCombobox*Listbox.selectBackground", ZAZN), ("*TCombobox*Listbox.selectForeground", "#ffffff"),
                       ("*highlightBackground", LINIA), ("*highlightColor", AKCENT)):
        root.option_add(wzor, wart)
    s.configure(".", background=TLO, foreground=TEKST, fieldbackground=POLE, bordercolor=LINIA, darkcolor=TLO,
                lightcolor=TLO, troughcolor=POLE, focuscolor=AKCENT, insertcolor=TEKST, font=(CZC, 10),
                selectbackground=ZAZN, selectforeground="#ffffff")
    s.map(".", foreground=[("disabled", "#4d5870")])
    s.configure("TFrame", background=TLO)
    s.configure("Karta.TFrame", background=PANEL)
    s.configure("TLabel", background=TLO, foreground=TEKST)
    s.configure("Karta.TLabel", background=PANEL, foreground=TEKST)
    s.configure("Szary.TLabel", background=TLO, foreground=SZARY)
    s.configure("KartaSzary.TLabel", background=PANEL, foreground=SZARY)
    s.configure("Naglowek.TLabel", background=PANEL, foreground=AKCENT, font=(CZC, 9, "bold"))
    s.configure("Duzy.TLabel", background=TLO, foreground=TEKST, font=(MONO, 16, "bold"))
    s.configure("Zegar.TLabel", background=TLO, foreground=AKCENT, font=(MONO, 13, "bold"))
    s.configure("Status.TLabel", background=PANEL, foreground=SZARY, padding=(8, 3))
    s.configure("TButton", background="#1b2540", foreground=TEKST, bordercolor=LINIA, padding=(10, 4), relief="flat")
    s.map("TButton", background=[("pressed", "#2c3a63"), ("active", "#243152"), ("disabled", "#141b2e")],
          bordercolor=[("active", AKCENT)])
    s.configure("Akcent.TButton", background=AKCENT, foreground="#141414", font=(CZC, 10, "bold"))
    s.map("Akcent.TButton", background=[("pressed", "#d98310"), ("active", "#ffb347"), ("disabled", "#5a4420")])
    s.configure("TCheckbutton", background=TLO, foreground=TEKST, indicatorbackground=POLE, indicatorforeground=AKCENT)
    s.map("TCheckbutton", background=[("active", TLO)], indicatorbackground=[("selected", POLE)])
    s.configure("Karta.TCheckbutton", background=PANEL)
    s.map("Karta.TCheckbutton", background=[("active", PANEL)])
    s.configure("TEntry", fieldbackground=POLE, foreground=TEKST, bordercolor=LINIA, insertcolor=TEKST, padding=3)
    s.map("TEntry", bordercolor=[("focus", AKCENT)])
    s.configure("TSpinbox", fieldbackground=POLE, foreground=TEKST, bordercolor=LINIA, arrowcolor=TEKST, background=PANEL)
    s.configure("TCombobox", fieldbackground=POLE, foreground=TEKST, background=PANEL, bordercolor=LINIA,
                arrowcolor=TEKST, padding=3)
    s.map("TCombobox", fieldbackground=[("readonly", POLE)], foreground=[("readonly", TEKST)],
          selectbackground=[("readonly", POLE)], selectforeground=[("readonly", TEKST)], bordercolor=[("focus", AKCENT)])
    s.configure("TNotebook", background=TLO, bordercolor=LINIA, tabmargins=(6, 6, 6, 0))
    s.configure("TNotebook.Tab", background=TLO, foreground=SZARY, padding=(18, 7), bordercolor=LINIA, font=(CZC, 10, "bold"))
    s.map("TNotebook.Tab", background=[("selected", PANEL)], foreground=[("selected", AKCENT)])
    s.configure("TLabelframe", background=TLO, bordercolor=LINIA, relief="solid")
    s.configure("TLabelframe.Label", background=TLO, foreground=AKCENT, font=(CZC, 9, "bold"))
    s.configure("Treeview", background=POLE, fieldbackground=POLE, foreground=TEKST, bordercolor=LINIA, rowheight=24,
                font=(MONO, 11))
    s.map("Treeview", background=[("selected", ZAZN)], foreground=[("selected", "#ffffff")])
    s.configure("Treeview.Heading", background=PANEL, foreground=SZARY, bordercolor=LINIA, relief="flat", font=(CZC, 9, "bold"))
    s.map("Treeview.Heading", background=[("active", PANEL)])
    s.configure("Horizontal.TProgressbar", background=AKCENT, troughcolor=POLE, bordercolor=LINIA, lightcolor=AKCENT,
                darkcolor=AKCENT, thickness=10)
    s.configure("Horizontal.TScale", background=TLO, troughcolor=POLE, bordercolor=LINIA)
    s.configure("Vertical.TScrollbar", background="#1b2540", troughcolor=TLO, bordercolor=TLO, arrowcolor=SZARY)
    s.map("Vertical.TScrollbar", background=[("active", "#2c3a63")])
    ciemna_belka(root)


def karta(rodzic, tytul):
    """Panel z pomarańczowym nagłówkiem; zwraca ramkę na zawartość (style Karta.*)."""
    zew = tk.Frame(rodzic, bg=LINIA)
    wew = ttk.Frame(zew, style="Karta.TFrame", padding=(10, 8))
    wew.pack(fill="both", expand=True, padx=1, pady=1)
    ttk.Label(wew, text=tytul.upper(), style="Naglowek.TLabel").pack(anchor="w", pady=(0, 4))
    wew.zew = zew
    return wew

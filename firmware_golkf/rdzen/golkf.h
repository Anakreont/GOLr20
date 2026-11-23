/*
 * GOLkf – firmware trackera-robota FT8 (płytka R20, RP2350). RDZEŃ: logika bez sprzętu.
 *
 * Rdzeń nie dotyka sprzętu. Warstwa sprzętowa (albo symulator na PC) woła:
 *   gk_start()     – raz po włączeniu (z konfiguracją i logiem odczytanymi z pamięci),
 *   gk_okno()      – tuż przed każdym oknem 15 s: dostaje czas, pozycję, napięcie; zwraca, co zrobić w tym oknie,
 *   gk_odebrano()  – po oknie odbioru: lista zdekodowanych ramek FT8.
 * Format ramek danych i komend = narzedzia/cw7300/robot_proto.py (wersja 1). Testy: ../test/.
 */
#ifndef GOLKF_H
#define GOLKF_H
#include <stdbool.h>
#include <stdint.h>

#define GK_WERSJA "0.1"
#define GK_MAX_WPISOW 2048   /* wpisów logu w pamięci (do 4096 łączności) */
#define GK_STREF 4
#define GK_CZARNA 8
#define GK_MAGIA 0x474B6601u /* znacznik ważnej konfiguracji w pamięci ("GKf" + wersja układu danych) */

enum { GK_TRYB_PELNY, GK_TRYB_SREDNI, GK_TRYB_OSZCZ, GK_TRYB_WSPR, GK_TRYB_CISZA };
enum { GK_W_POTW = 1, GK_W_ZADANY = 2 };

typedef struct
{
    uint32_t z1, z2; /* znaki jako 28 bitów FT8; z2 = 0: wpis z jedną łącznością */
    uint32_t czas;   /* czas uniksowy pierwszej łączności */
    uint8_t flagi;   /* GK_W_POTW – dom potwierdził; GK_W_ZADANY – dom prosi o powtórkę */
    uint8_t nadano;  /* ile razy wpis poszedł w eter */
} gk_wpis;

typedef struct
{
    uint8_t czynna;
    int8_t szer1, szer2;  /* stopnie, szer1 <= szer2 */
    int16_t dlug1, dlug2; /* stopnie, dlug1 <= dlug2 */
} gk_strefa;

/* Konfiguracja trwała – zapisywana w pamięci flash po każdej zmianie (komendą albo przy programowaniu). */
typedef struct
{
    uint32_t magia;
    char znak_ft8[12];  /* znak FT8 */
    char znak_wspr[12]; /* znak WSPR */
    uint8_t pasmo;      /* numer z listy gk_pasma[] (5 = 20 m) */
    uint16_t kanal;     /* kanał WSPR 0–599 (Traquito) */
    uint8_t tryb;       /* GK_TRYB_PELNY … GK_TRYB_WSPR */
    uint32_t cisza_do;  /* czas uniksowy końca ciszy (0 = brak) */
    uint8_t ft4;
    uint16_t cq_hz, log_hz;              /* częstotliwości dźwięku: łączności i ramki danych */
    uint8_t moc;                         /* 0…3 = 2/4/6/8 mA */
    uint8_t u_pelny, u_wspr;             /* progi napięcia paneli, krok 0,05 V */
    uint8_t slonce_pelny, slonce_wspr;   /* progi wysokości Słońca, stopnie */
    gk_strefa strefa[GK_STREF];          /* strefy ciszy ustawiane komendą (stałe – w golkf.c) */
    uint8_t regula;                      /* ta sama stacja: 0 bez ograniczeń, 1 raz na dobę, 2 raz na lot */
    uint32_t czarna[GK_CZARNA];          /* znaki (28 b), z którymi nie robimy łączności */
    uint8_t staly_lok;
    char lokator[8];                     /* stały lokator (gdy staly_lok) */
    uint8_t tx_wyl;                      /* bit 0: FT8 wyłączone, bit 1: WSPR wyłączone */
    uint32_t tx_wlacz_o;                 /* kiedy wyłączone nadawanie włączy się samo (0 = nigdy) */
    uint8_t ost_kom;                     /* licznik ostatniej przyjętej komendy */
    uint8_t jest_klucz;
    uint8_t klucz[16];                   /* klucz podpisu komend – wgrywany przez USB, nigdy w repo */
    uint32_t potw_do;                    /* dom potwierdził wszystkie wpisy do tego numeru */
} gk_cfg;

/* Co warstwa sprzętowa wie na początku okna. */
typedef struct
{
    uint32_t t;      /* czas uniksowy początku okna (wielokrotność 15 s), z GPS */
    uint8_t gps_ok;  /* jest aktualna pozycja */
    float szer, dlug;
    int32_t wys_m;
    float u_v;       /* napięcie paneli */
    int8_t temp_c;
} gk_env;

typedef struct
{
    uint8_t payload[10]; /* 77 bitów ramki FT8 */
    int8_t snr;
    uint16_t hz;
} gk_dekod;

enum { GK_SPI, GK_ODBIOR, GK_NADAJ_FT8, GK_NADAJ_WSPR };
typedef struct
{
    uint8_t co;
    uint8_t payload[10]; /* GK_NADAJ_FT8: ramka do nadania */
    uint16_t hz;         /* częstotliwość dźwięku najniższego tonu */
    uint8_t ft4;
    uint8_t moc;
    uint32_t czest_hz;   /* FT8: częstotliwość „dial”; WSPR: środek kanału */
    char wspr_znak[12], wspr_lok[5];
    uint8_t wspr_dbm;
    char opis[48];       /* do konsoli USB i testów: co nadajemy */
} gk_akcja;

enum { Q_BRAK, Q_RAPORT, Q_RRAPORT, Q_RR73, Q_PO_RR73, Q_73 };
typedef struct
{
    uint8_t stan;
    char znak[12];
    uint32_t n28;
    int8_t snr;         /* z jakim SNR ich słyszymy (nasz raport dla nich) */
    uint8_t powt;       /* ile razy nadaliśmy bieżący krok bez odpowiedzi */
    uint8_t zalogowane;
} gk_qso;

/* Zapis trwały – podaje warstwa sprzętowa (albo test). */
typedef struct
{
    void (*zapisz_cfg)(const gk_cfg* c);
    void (*zapisz_wpis)(uint32_t nr, const gk_wpis* w); /* nr od 1 */
} gk_plat;

typedef struct
{
    gk_cfg cfg;
    gk_plat plat;
    gk_wpis wpis[GK_MAX_WPISOW];
    uint32_t n_wpisow;      /* zamknięte wpisy: wpis[0] ma numer 1 */
    uint32_t n_qso;         /* łączności w zamkniętych wpisach */
    gk_wpis otwarty;        /* wpis z jedną łącznością, czeka na drugą (najwyżej 10 min) */
    uint8_t jest_otwarty;
    gk_qso qso;
    uint32_t t_stan;        /* kiedy ostatnio nadano ramkę STAN */
    uint32_t t_log;         /* kiedy ostatnio nadano ramkę LOG */
    uint32_t wspr_do;       /* do kiedy trwa nadawanie WSPR */
    uint32_t t_dom;         /* kiedy ostatnio przyjęto komendę z domu (0 = nigdy) */
    uint8_t stan_teraz;     /* nadaj STAN w najbliższym oknie nadawczym (po komendzie) */
    int8_t snr_dom;         /* SNR ostatniej przyjętej komendy; 127 = jeszcze nie słyszał domu */
    uint8_t dekody;         /* liczba dekodów w ostatnim oknie odbioru */
    uint8_t poziom;         /* 0 = za mało energii, 1 = tylko WSPR, 2 = pełna praca (do wglądu) */
    uint8_t w_strefie;
    float slonce;           /* wysokość Słońca w stopniach (do wglądu) */
    gk_env env;
} gk_t;

extern const char* const gk_pasma[];

void gk_cfg_domyslna(gk_cfg* c);
void gk_start(gk_t* g, const gk_cfg* cfg, const gk_plat* plat);
void gk_wczytaj_wpis(gk_t* g, const gk_wpis* w); /* przy starcie: kolejne wpisy logu z pamięci */
gk_akcja gk_okno(gk_t* g, const gk_env* e);
void gk_odebrano(gk_t* g, uint32_t t_okna, const gk_dekod* d, int n);

/* pomocnicze (też dla testów i konsoli USB) */
uint32_t gk_pakuj_znak(const char* znak);             /* 0 = pusty, 0xFFFFFFFF = niestandardowy */
bool gk_rozpakuj_znak(uint32_t n28, char* znak);      /* false = to nie jest znak standardowy */
void gk_ramka_log(const gk_wpis* w, uint32_t nr, uint8_t* t9);
void gk_ramka_stan(const gk_t* g, uint8_t* t9);
bool gk_komenda(gk_t* g, const uint8_t* t9, uint32_t t_okna, int8_t snr); /* true = przyjęta */
void gk_telem_na_payload(const uint8_t* t9, uint8_t* payload10);
bool gk_payload_na_telem(const uint8_t* payload10, uint8_t* t9);
void gk_lokator(float szer, float dlug, char* lok7);
float gk_slonce(uint32_t t, float szer, float dlug);
bool gk_strefa_ciszy(const gk_t* g, float szer, float dlug);
void gk_wspr_kanal(uint8_t pasmo, uint16_t kanal, uint32_t* czest_hz, uint8_t* minuta);
void gk_hmac_sha256(const uint8_t* klucz, int nk, const uint8_t* dane, int nd, uint8_t* wynik32);

#endif

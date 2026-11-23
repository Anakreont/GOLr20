/* GOLkf – warstwa sprzętowa dla płytki R20 v0.2 (RP2354A). Wspólne deklaracje. */
#ifndef SPRZET_H
#define SPRZET_H
#include <stdbool.h>
#include <stdint.h>
#include "../rdzen/golkf.h"

#define GK_SPRZET_WERSJA "0.2"

/* ---- piny (firmware/robot_ft8/pcb/projekt.py) ---- */
#define PIN_GPS_TX 8     /* UART1 TX -> RXD GPS */
#define PIN_GPS_RX 9     /* UART1 RX <- TXD GPS */
#define PIN_GPS_EN_N 10  /* 0 = GPS włączony */
#define PIN_SDA 16       /* I2C0 */
#define PIN_SCL 17
#define PIN_RF_EN_N 18   /* 0 = Si5351 + TCXO włączone */
#define PIN_RX_PWR 19    /* 1 = zasilanie odbiornika (z pinu) */
#define PIN_RX_OE_N 23   /* 0 = klucz odbiornika włączony */
#define PIN_ADC_I 26     /* ADC0 */
#define PIN_ADC_Q 27     /* ADC1 */
#define PIN_ADC_VSC 28   /* ADC2: napięcie paneli / 2 */

/* ---- ustawienia sprzętowe (osobno od konfiguracji rdzenia; zapisywane w pamięci) ---- */
#define HW_MAGIA 0x52323002u
typedef struct
{
    uint32_t magia;
    uint32_t tcxo_hz;     /* rzeczywista częstotliwość TCXO (kalibracja), domyślnie 26 000 000 */
    int16_t gps_dt_ms;    /* ile ms po pełnej sekundzie GPS zaczyna wysyłać dane */
    int8_t bok;           /* +1 / -1: wybór wstęgi odbiornika */
    uint8_t praca;        /* 0 = stół (nic nie nadaje samo), 1 = praca samodzielna */
    uint8_t gps_stale;    /* 1 = GPS zawsze włączony, 0 = włączany co gps_co_s */
    uint16_t gps_co_s;
    uint8_t lo_moc;       /* prąd wyjść heterodyny 0–3 */
    uint8_t kandydaci;    /* ilu kandydatów sprawdza dekoder */
} hw_cfg;
extern hw_cfg hw;
extern gk_t g;

/* ---- czas ---- */
bool czas_jest(void);
uint64_t czas_us(void);                 /* czas uniksowy w mikrosekundach (0 = nieznany) */
void czas_ustaw(uint64_t unix_us, uint64_t zegar_us);
void czekaj_do(uint64_t unix_us);       /* czeka (karmi układ nadzoru) */
void nadzor(void);

/* ---- si5351.c ---- */
bool si_wlacz(void);                    /* zasilanie + ustawienia początkowe; false = układ nie odpowiada */
void si_wylacz(void);
bool si_jest(void);
int si_status(void);                    /* rejestr 0 albo -1 */
bool si_tx_przygotuj(double f_hz, double krok_hz, uint8_t moc);
bool si_tx_wlacz(void);
void si_tx_ton(int k);
void si_tx_stop(void);
bool si_rx_start(double f_hz);
void si_rx_stop(void);
extern uint32_t si_bledy;               /* nieudane zapisy I2C */

/* ---- gps.c ---- */
typedef struct
{
    bool fix;             /* ostatnie zdanie mówiło: pozycja ważna */
    float szer, dlug;
    int32_t wys_m;
    uint8_t sat;
    uint64_t t_poz_us;    /* zegar (time_us_64) ostatniej ważnej pozycji; 0 = nigdy */
    uint64_t t_czas_us;   /* zegar ostatniego ustawienia czasu */
    uint32_t zdan, bledow;
} gps_t;
extern gps_t gps;
void gps_init(void);
void gps_wlacz(bool wl);
bool gps_wlaczony(void);
void gps_krok(void);                    /* wołać często: czyta dane, ustawia czas i pozycję */
void gps_echo(bool wl);                 /* przepisuj zdania NMEA na konsolę */

/* ---- pamiec.c ---- */
void pam_init(void);
bool pam_czytaj_cfg(gk_cfg* c);
void pam_zapisz_cfg(const gk_cfg* c);
bool pam_czytaj_hw(hw_cfg* h);
void pam_zapisz_hw(const hw_cfg* h);
uint32_t pam_czytaj_log(gk_t* gg);      /* woła gk_wczytaj_wpis dla każdego wpisu; zwraca ile */
void pam_zapisz_wpis(uint32_t nr, const gk_wpis* w);
void pam_kasuj_log(void);
void pam_kasuj_wszystko(void);

/* ---- odbior.c ---- */
typedef struct
{
    float rms_i, rms_q, kor;            /* poziomy (kody przetwornika) i korelacja I z Q */
    uint16_t min_i, max_i, min_q, max_q;
    float sr_dt;                        /* średnie przesunięcie czasu dekodów [s] */
    int kandydatow, blokow;
    uint32_t ms_dekod;
} odb_stat;
bool odb_init(void);
/* Słucha od chwili t0 (czas uniksowy okna, us) do t0 + 13,4 s, potem dekoduje najdalej do t0 + 14,6 s. Zwraca liczbę dekodów. */
int odb_okno(uint64_t t0_us, double dial_hz, gk_dekod* d, int max, odb_stat* st);
float adc_vsc(void);                    /* napięcie paneli [V] */
float adc_temp(void);                   /* temperatura procesora [C] */

/* ---- nadaj.c ---- */
bool nadaj_ft8(uint64_t t0_us, const gk_akcja* a);
bool nadaj_wspr(uint64_t t0_us, const gk_akcja* a);
bool nadaj_nosna(double f_hz, uint8_t moc, uint32_t ms);

/* ---- konsola.c ---- */
void kon_krok(void);
void kon_klawisz(void);
void kon_druk_stan(void);
extern volatile bool kon_przerwij;      /* naciśnięto klawisz podczas testu */
#endif

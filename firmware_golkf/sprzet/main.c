/* GOLkf – firmware trackera-robota FT8, warstwa sprzętowa dla płytki R20 v0.2 (RP2354A). Pętla główna.
 *
 * Rytm: okna 15 s wg czasu GPS. Ok. 0,25 s przed każdym oknem rdzeń (rdzen/golkf.c) decyduje, co robić:
 * odbiór (odbior.c), nadawanie FT8 / WSPR (nadaj.c) albo nic. Konsola USB (konsola.c) służy do uruchamiania i ustawień.
 * Po wgraniu tracker jest w trybie STÓŁ (hw.praca = 0): sam niczego nie nadaje, dopóki nie dostanie komendy „praca 1”.
 */
#include "sprzet.h"
#include <stdio.h>
#include <string.h>
#include "hardware/gpio.h"
#include "hardware/structs/powman.h"
#include "hardware/watchdog.h"
#include "pico/stdlib.h"

hw_cfg hw;
gk_t g;
static int64_t przes_us; /* czas uniksowy = zegar + przes */
static bool jest_czas;

bool czas_jest(void) { return jest_czas; }
uint64_t czas_us(void) { return jest_czas ? (uint64_t)((int64_t)time_us_64() + przes_us) : 0; }
void nadzor(void) { watchdog_update(); }

void czas_ustaw(uint64_t unix_us, uint64_t zegar_us)
{
    int64_t nowe = (int64_t)unix_us - (int64_t)zegar_us;
    int64_t r = nowe - przes_us;
    if (!jest_czas || r > 50000 || r < -50000)
        przes_us = nowe; /* pierwszy raz albo duża różnica: ustaw od razu */
    else
        przes_us += r / 8; /* małe różnice wygładzaj (rozrzut chwili nadejścia danych z GPS) */
    jest_czas = true;
}

void czekaj_do(uint64_t unix_us)
{
    while (czas_us() < unix_us)
    {
        nadzor();
        gps_krok();
        if ((int64_t)(unix_us - czas_us()) > 2000)
            sleep_us(1000);
    }
}

static void hw_domyslne(void)
{
    memset(&hw, 0, sizeof(hw));
    hw.magia = HW_MAGIA;
    hw.tcxo_hz = 26000000;
    hw.gps_dt_ms = 50;
    hw.bok = 1;
    hw.praca = 0;
    hw.gps_stale = 0;
    hw.gps_co_s = 600;
    hw.lo_moc = 1;
    hw.kandydaci = 70;
}

/* Rdzeń procesora zasila osobny stabilizator 1,2 V – wbudowaną przetwornicę przełączamy w stan wysokiej impedancji. */
static void przetwornica_wyl(void)
{
#ifndef R20_BEZ_HIZ
    hw_set_bits(&powman_hw->vreg_ctrl, POWMAN_PASSWORD_BITS | POWMAN_VREG_CTRL_UNLOCK_BITS);
    while (powman_hw->vreg & POWMAN_VREG_UPDATE_IN_PROGRESS_BITS)
        tight_loop_contents();
    hw_write_masked(&powman_hw->vreg, POWMAN_PASSWORD_BITS | POWMAN_VREG_HIZ_BITS, POWMAN_PASSWORD_BITS | POWMAN_VREG_HIZ_BITS);
#endif
}

static void gps_zarzadzaj(void)
{
    static uint64_t t_wl;
    uint64_t z = time_us_64();
    uint64_t co = (uint64_t)hw.gps_co_s * 1000000ull;
    bool trzeba = hw.gps_stale || !hw.praca || !jest_czas || !gps.t_poz_us || z - gps.t_czas_us > co || z - gps.t_poz_us > co;
    if (trzeba && !gps_wlaczony())
    {
        gps_wlacz(true);
        t_wl = time_us_64();
    }
    else if (!trzeba && gps_wlaczony() && z - t_wl > 5000000ull)
        gps_wlacz(false);
}

static const char* const NAZWA[] = { "spi", "ODBIOR", "NADAJE FT8", "NADAJE WSPR" };

/* Dekoder FT8 potrzebuje ok. 6 kB stosu, a domyślny stos Pico SDK ma 2 kB (obszar 4 kB) – praca idzie na własnym stosie 24 kB. */
uint32_t stos[6144] __attribute__((aligned(8), used));
void praca(void);
int __attribute__((naked)) main(void)
{
    __asm volatile("ldr r0, =stos\n"
                   "msr msplim, r0\n"
                   "ldr r1, =(6144 * 4)\n"
                   "add r0, r0, r1\n"
                   "msr msp, r0\n"
                   "b praca\n");
}

uint32_t stos_wolny(void) /* ile bajtów stosu nigdy nie było użyte (do konsoli) */
{
    uint32_t i = 0;
    while (i < 6144 && stos[i] == 0)
        i++;
    return i * 4;
}

void __attribute__((noreturn, used)) praca(void)
{
    przetwornica_wyl();
    gpio_init(PIN_RF_EN_N);
    gpio_put(PIN_RF_EN_N, 1);
    gpio_set_dir(PIN_RF_EN_N, GPIO_OUT);
    stdio_init_all();
    gps_init();
    bool odb_ok = odb_init();
    pam_init();
    if (!pam_czytaj_hw(&hw))
        hw_domyslne();
    gk_cfg cfg;
    bool cfg_ok = pam_czytaj_cfg(&cfg);
    gk_plat plat = { .zapisz_cfg = pam_zapisz_cfg, .zapisz_wpis = pam_zapisz_wpis };
    gk_start(&g, cfg_ok ? &cfg : NULL, &plat);
    pam_czytaj_log(&g);
    watchdog_enable(8000, true);

    static gk_dekod dek[40];
    uint64_t ost_okno = 0;
    bool rx_zas = false;
    (void)odb_ok;
    for (;;)
    {
        nadzor();
        gps_krok();
        kon_krok();
        gps_zarzadzaj();
        if (!hw.praca || !jest_czas)
        {
            if (rx_zas)
            {
                gpio_put(PIN_RX_PWR, 0);
                rx_zas = false;
            }
            sleep_ms(2);
            continue;
        }
        uint64_t teraz = czas_us();
        uint64_t tn = (teraz / 15000000ull + 1) * 15000000ull;
        uint64_t do_okna = tn - teraz;
        if (tn <= ost_okno)
        {
            sleep_ms(1);
            continue;
        }
        /* odbiornik zasilany 3,5 s przed oknem, gdy jest dość energii na odbiór (albo jeszcze nie wiadomo) */
        if (do_okna < 3500000 && !rx_zas && (g.poziom >= 2 || !ost_okno))
        {
            gpio_put(PIN_RX_PWR, 1);
            rx_zas = true;
        }
        if (do_okna > 250000)
        {
            sleep_ms(1);
            continue;
        }
        ost_okno = tn;
        gk_env e = { 0 };
        e.t = (uint32_t)(tn / 1000000ull);
        e.gps_ok = gps.t_poz_us && time_us_64() - gps.t_poz_us < 1800000000ull; /* pozycja nie starsza niż 30 min */
        e.szer = gps.szer;
        e.dlug = gps.dlug;
        e.wys_m = gps.wys_m;
        e.u_v = adc_vsc();
        e.temp_c = (int8_t)adc_temp();
        gk_akcja a = gk_okno(&g, &e);
        if (stdio_usb_connected())
            printf("[%02u:%02u:%02u] %s %s  U=%.2f V poziom %u\n", (unsigned)(e.t / 3600 % 24), (unsigned)(e.t / 60 % 60), (unsigned)(e.t % 60),
                NAZWA[a.co & 3], a.opis, (double)e.u_v, g.poziom);
        switch (a.co)
        {
        case GK_ODBIOR:
        {
            odb_stat st;
            int n = odb_okno(tn, a.czest_hz, dek, 40, &st);
            gk_odebrano(&g, e.t, dek, n);
            if (stdio_usb_connected())
                printf("   dekodow %d (kandydatow %d, %u ms), I %.0f Q %.0f, sr. dt %+.2f s\n", n, st.kandydatow, (unsigned)st.ms_dekod,
                    (double)st.rms_i, (double)st.rms_q, (double)st.sr_dt);
            break;
        }
        case GK_NADAJ_FT8:
            if (!nadaj_ft8(tn, &a) && stdio_usb_connected())
                printf("   BLAD: Si5351 nie odpowiada\n");
            break;
        case GK_NADAJ_WSPR:
            gpio_put(PIN_RX_PWR, 0);
            rx_zas = false;
            if (!nadaj_wspr(tn, &a) && stdio_usb_connected())
                printf("   BLAD: WSPR nie poszedl (Si5351 albo znak / lokator)\n");
            si_wylacz();
            break;
        default:
            gpio_put(PIN_RX_PWR, 0);
            rx_zas = false;
            si_wylacz(); /* nic do roboty: Si5351 i TCXO bez zasilania */
            break;
        }
    }
}

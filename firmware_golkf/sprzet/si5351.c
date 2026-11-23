/* GOLkf / R20 – Si5351A-B-GT na I2C0. CLK0 = nadajnik (pętla A); CLK1 + CLK2 = heterodyna odbiornika (pętla B).
 *
 * Odbiornik: klucz SN74CBTLV3253 wybiera jeden z 4 kondensatorów wg wejść S1 S0, a wzmacniacze biorą pary
 * (1. – 3.) i (2. – 4.). Żeby te pary były w przeciwfazie, wejścia muszą LICZYĆ DWÓJKOWO (00, 01, 10, 11):
 * S0 (CLK1) dostaje 2 x f, S1 (CLK2) dostaje f. Dwa przebiegi f przesunięte o 90 st. dałyby kolejność 1, 2, 4, 3
 * i oba wzmacniacze widziałyby to samo (brak tłumienia drugiej wstęgi).
 */
#include "sprzet.h"
#include "si_licz.h"
#include "hardware/gpio.h"
#include "hardware/i2c.h"
#include "pico/stdlib.h"

#define ADR 0x60
#define I2C i2c0
uint32_t si_bledy;
static bool zasilony;
static si_plan plan_tx;

static bool zapis(uint8_t rej, const uint8_t* d, int n)
{
    uint8_t b[10];
    b[0] = rej;
    for (int i = 0; i < n; i++)
        b[1 + i] = d[i];
    int r = i2c_write_timeout_us(I2C, ADR, b, (size_t)n + 1, false, 20000);
    if (r != n + 1)
    {
        si_bledy++;
        return false;
    }
    return true;
}
static bool zapis1(uint8_t rej, uint8_t w) { return zapis(rej, &w, 1); }

int si_status(void)
{
    uint8_t r = 0, w;
    if (i2c_write_timeout_us(I2C, ADR, &r, 1, true, 20000) != 1)
        return -1;
    if (i2c_read_timeout_us(I2C, ADR, &w, 1, false, 20000) != 1)
        return -1;
    return w;
}

bool si_jest(void) { return zasilony; }

bool si_wlacz(void)
{
    if (zasilony)
        return true;
    gpio_put(PIN_RF_EN_N, 0);
    sleep_ms(20); /* rozruch TCXO i Si5351 */
    i2c_init(I2C, 400000);
    gpio_set_function(PIN_SDA, GPIO_FUNC_I2C);
    gpio_set_function(PIN_SCL, GPIO_FUNC_I2C);
    int st = -1;
    for (int i = 0; i < 50; i++) /* czekaj na koniec inicjalizacji układu (bit 7 rejestru 0) */
    {
        st = si_status();
        if (st >= 0 && !(st & 0x80))
            break;
        sleep_ms(2);
    }
    if (st < 0 || (st & 0x80))
    {
        si_wylacz();
        return false;
    }
    bool ok = zapis1(3, 0xFF);   /* wszystkie wyjścia wyłączone */
    ok &= zapis1(9, 0xFF);       /* pin OEB nie steruje wyjściami */
    ok &= zapis1(15, 0x00);      /* obie pętle z wejścia XA (TCXO) */
    for (uint8_t r = 16; r <= 23; r++)
        ok &= zapis1(r, 0x80);   /* wyjścia uśpione */
    ok &= zapis1(149, 0x00);     /* bez rozpraszania widma */
    zasilony = ok;
    if (!ok)
        si_wylacz();
    return ok;
}

void si_wylacz(void)
{
    /* linie I2C w stan wysokiej impedancji, żeby nie zasilać układu przez rezystory podciągające */
    gpio_set_function(PIN_SDA, GPIO_FUNC_NULL);
    gpio_set_function(PIN_SCL, GPIO_FUNC_NULL);
    gpio_put(PIN_RF_EN_N, 1);
    zasilony = false;
}

/* ustawia wszystko, ale wyjście zostaje wyłączone – włącza je si_tx_wlacz() dokładnie w chwili startu */
bool si_tx_przygotuj(double f_hz, double krok_hz, uint8_t moc)
{
    uint8_t r[8];
    if (!si_wlacz() || !si_plan_licz(hw.tcxo_hz, f_hz, krok_hz, 2, &plan_tx))
        return false;
    bool ok = zapis1(3, 0xFF);
    si_plan_rej_pll(&plan_tx, 0, r);
    ok &= zapis(26, r, 8);                    /* pętla A */
    si_rej_wyj(plan_tx.D, r);
    ok &= zapis(42, r, 8);                    /* dzielnik CLK0 */
    ok &= zapis1(165, 0);
    ok &= zapis1(16, (uint8_t)(0x0C | (moc & 3))); /* CLK0: pętla A, dzielnik ułamkowy, prąd wg mocy */
    ok &= zapis1(177, 0x20);                  /* reset pętli A */
    return ok;
}

bool si_tx_wlacz(void) { return zapis1(3, 0xFE); }

void si_tx_ton(int k)
{
    uint8_t r[8];
    si_plan_rej_pll(&plan_tx, k, r);
    zapis(26, r, 8);
}

void si_tx_stop(void)
{
    if (!zasilony)
        return;
    zapis1(3, 0xFF);
    zapis1(16, 0x80);
}

bool si_rx_start(double f_hz)
{
    uint8_t r[8];
    si_plan p;
    /* S1 = CLK2 = f (dzielnik D, wielokrotność 4), S0 = CLK1 = 2 f (dzielnik D/2) */
    if (!si_wlacz() || !si_plan_licz(hw.tcxo_hz, f_hz, 0, 4, &p))
        return false;
    bool ok = zapis1(3, 0xFF);
    si_plan_rej_pll(&p, 0, r);
    ok &= zapis(34, r, 8);                    /* pętla B */
    si_rej_wyj(p.D / 2, r);
    ok &= zapis(50, r, 8);                    /* CLK1 = 2 f */
    si_rej_wyj(p.D, r);
    ok &= zapis(58, r, 8);                    /* CLK2 = f */
    ok &= zapis1(166, 0);
    ok &= zapis1(167, 0);
    ok &= zapis1(17, (uint8_t)(0x2C | (hw.lo_moc & 3)));
    ok &= zapis1(18, (uint8_t)(0x2C | (hw.lo_moc & 3)));
    ok &= zapis1(177, 0x80);                  /* reset pętli B: oba wyjścia ruszają razem */
    ok &= zapis1(3, 0xF9);                    /* włącz CLK1 i CLK2 */
    return ok;
}

void si_rx_stop(void)
{
    if (!zasilony)
        return;
    zapis1(3, 0xFF);
    zapis1(17, 0x80);
    zapis1(18, 0x80);
}

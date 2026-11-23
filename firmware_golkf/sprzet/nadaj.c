/* GOLkf / R20 – nadawanie: FT8 (79 tonów co 0,16 s, odstęp 6,25 Hz) i WSPR (162 tony co 8192/12000 s, odstęp 1,4648 Hz).
   Zmienia się tylko ułamek pętli PLL – bez przerw fazy. Kluczowanie proste (bez wygładzania częstotliwości). */
#include "sprzet.h"
#include "wspr.h"
#include <ft8/constants.h>
#include <ft8/encode.h>
#include "hardware/gpio.h"
#include "pico/stdlib.h"

static void rx_odlacz(void)
{
    si_rx_stop();
    gpio_put(PIN_RX_OE_N, 1); /* klucz odbiornika odłączony od anteny */
}

static bool tony(uint64_t start_us, const uint8_t* t, int n, uint32_t symbol_us, double f0, double krok, uint8_t moc)
{
    rx_odlacz();
    /* przygotuj układ wcześniej, wyjście włącz dopiero w chwili startu */
    if (!si_tx_przygotuj(f0, krok, moc))
    {
        si_tx_stop();
        return false;
    }
    si_tx_ton(t[0]);
    if (start_us)
        czekaj_do(start_us);
    uint64_t z0 = time_us_64();
    bool ok = si_tx_wlacz();
    for (int i = 0; ok && i < n && !kon_przerwij; i++)
    {
        if (i)
            si_tx_ton(t[i]);
        uint64_t do_us = z0 + (uint64_t)(i + 1) * symbol_us;
        while (time_us_64() < do_us)
        {
            nadzor();
            gps_krok();
            kon_klawisz();
            int64_t zost = (int64_t)(do_us - time_us_64());
            if (zost > 2000)
                sleep_us(1000);
        }
    }
    si_tx_stop();
    return ok;
}

bool nadaj_ft8(uint64_t t0_us, const gk_akcja* a)
{
    uint8_t t[FT8_NN];
    ft8_encode(a->payload, t);
    return tony(t0_us ? t0_us + 500000 : 0, t, FT8_NN, 160000, (double)a->czest_hz + a->hz, 6.25, a->moc);
}

bool nadaj_wspr(uint64_t t0_us, const gk_akcja* a)
{
    uint8_t t[WSPR_SYMBOLI];
    if (!wspr_koduj(a->wspr_znak, a->wspr_lok, a->wspr_dbm, t))
        return false;
    const double krok = 12000.0 / 8192.0;
    return tony(t0_us ? t0_us + 1000000 : 0, t, WSPR_SYMBOLI, 682667, (double)a->czest_hz - 1.5 * krok, krok, a->moc);
}

bool nadaj_nosna(double f_hz, uint8_t moc, uint32_t ms)
{
    rx_odlacz();
    if (!si_tx_przygotuj(f_hz, 0, moc) || !si_tx_wlacz())
    {
        si_tx_stop();
        return false;
    }
    uint64_t do_us = time_us_64() + (uint64_t)ms * 1000;
    while (time_us_64() < do_us && !kon_przerwij)
    {
        nadzor();
        kon_klawisz();
        sleep_ms(1);
    }
    si_tx_stop();
    return true;
}

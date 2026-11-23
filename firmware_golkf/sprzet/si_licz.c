/* GOLkf / R20 – obliczenia dzielników Si5351A (wzory z noty AN619). */
#include "si_licz.h"
#include <math.h>

#define C_MAX 1048575u
#define VCO_MIN 600e6
#define VCO_MAX 900e6

bool si_plan_licz(uint32_t fx, double f_hz, double krok_hz, uint32_t wiel, si_plan* p)
{
    if (wiel < 2)
        wiel = 2;
    /* dzielnik: pętla możliwie blisko 750 MHz, w zakresie 600–900 MHz, D <= 126 (przesunięcia fazy, zapas) */
    uint32_t najl = 0;
    double najl_odl = 1e18;
    for (uint32_t D = wiel; D <= 126; D += wiel)
    {
        double vco = f_hz * D;
        if (vco < VCO_MIN || vco > VCO_MAX)
            continue;
        double odl = fabs(vco - 750e6);
        if (odl < najl_odl)
        {
            najl_odl = odl;
            najl = D;
        }
    }
    if (!najl)
        return false;
    p->fx = fx;
    p->D = najl;
    double mnoz = f_hz * najl / fx; /* a + b/c */
    p->a = (uint32_t)mnoz;
    if (p->a < 15 || p->a > 90)
        return false;
    if (krok_hz > 0)
    {
        /* krok tonu = fx*m/(c*D)  ->  c = fx*m/(krok*D); największe m, przy którym c mieści się w rejestrze */
        double c1 = fx / (krok_hz * najl);
        uint32_t m = (uint32_t)(C_MAX / c1);
        if (m < 1)
            return false;
        p->m = m;
        p->c = (uint32_t)(c1 * m + 0.5);
    }
    else
    {
        p->m = 0;
        p->c = C_MAX;
    }
    p->b = (uint32_t)((mnoz - p->a) * p->c + 0.5);
    if (p->b >= p->c)
    {
        p->b -= p->c;
        p->a++;
    }
    return true;
}

double si_plan_hz(const si_plan* p, int k)
{
    return (double)p->fx * ((double)p->a + ((double)p->b + (double)p->m * k) / p->c) / p->D;
}

static void rej(uint32_t p1, uint32_t p2, uint32_t p3, uint8_t* r)
{
    r[0] = (uint8_t)(p3 >> 8);
    r[1] = (uint8_t)p3;
    r[2] = (uint8_t)((p1 >> 16) & 3);
    r[3] = (uint8_t)(p1 >> 8);
    r[4] = (uint8_t)p1;
    r[5] = (uint8_t)(((p3 >> 12) & 0xF0) | ((p2 >> 16) & 0x0F));
    r[6] = (uint8_t)(p2 >> 8);
    r[7] = (uint8_t)p2;
}

void si_plan_rej_pll(const si_plan* p, int k, uint8_t* r8)
{
    uint64_t licz = (uint64_t)p->b + (uint64_t)p->m * (uint32_t)k;
    uint32_t a = p->a + (uint32_t)(licz / p->c);
    uint32_t b = (uint32_t)(licz % p->c);
    uint32_t t = (uint32_t)(((uint64_t)128 * b) / p->c);
    rej(128 * a + t - 512, 128 * b - p->c * t, p->c, r8);
}

void si_rej_wyj(uint32_t D, uint8_t* r8)
{
    rej(128 * D - 512, 0, 1, r8);
}

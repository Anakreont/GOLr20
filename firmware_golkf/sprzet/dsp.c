/* GOLkf / R20 – tor odbiorczy cyfrowy (patrz dsp.h). */
#include "dsp.h"
#include <math.h>
#include <string.h>

#define PI 3.14159265358979f
#define FC 5500.0f /* granica filtru przed decymacją: płasko do ok. 3,9 kHz, tłumi od ok. 7 kHz */

void dsp_start(dsp_t* d, int bok)
{
    memset(d, 0, sizeof(*d));
    d->bok = bok >= 0 ? 1 : -1;
    d->sr_i = d->sr_q = 2048.0f;
    d->min_i = d->min_q = 4095;
    float s = 0;
    for (int k = 0; k < DSP_LP_I; k++)
    {
        float x = (float)k - (DSP_LP_I - 1) / 2.0f;
        float h = (x == 0) ? 2 * FC / DSP_FS_ADC : sinf(2 * PI * FC * x / DSP_FS_ADC) / (PI * x);
        d->lp_i[k] = h * (0.54f - 0.46f * cosf(2 * PI * k / (DSP_LP_I - 1)));
        s += d->lp_i[k];
    }
    for (int k = 0; k < DSP_LP_I; k++)
        d->lp_i[k] /= s;
    s = 0;
    for (int k = 0; k < DSP_LP_Q; k++)
    {
        float x = (float)k - (DSP_LP_Q - 1) / 2.0f; /* połówkowe */
        float h = sinf(2 * PI * FC * x / DSP_FS_ADC) / (PI * x);
        d->lp_q[k] = h * (0.54f - 0.46f * cosf(2 * PI * k / (DSP_LP_Q - 1)));
        s += d->lp_q[k];
    }
    for (int k = 0; k < DSP_LP_Q; k++)
        d->lp_q[k] /= s;
    for (int k = 0; k < DSP_HIL; k++)
    {
        int x = k - (DSP_HIL - 1) / 2;
        float h = (x & 1) ? 2.0f / (PI * (float)x) : 0.0f;
        d->hil[k] = h * (0.54f - 0.46f * cosf(2 * PI * k / (DSP_HIL - 1)));
    }
}

int dsp_dodaj(dsp_t* d, const uint16_t* pary, int n_par, float* wyj)
{
    int nw = 0;
    for (int i = 0; i < n_par; i++)
    {
        uint16_t ri = pary[2 * i] & 0x0FFF, rq = pary[2 * i + 1] & 0x0FFF;
        if (ri < d->min_i) d->min_i = ri;
        if (ri > d->max_i) d->max_i = ri;
        if (rq < d->min_q) d->min_q = rq;
        if (rq > d->max_q) d->max_q = rq;
        d->sr_i += ((float)ri - d->sr_i) * (1.0f / 4096);
        d->sr_q += ((float)rq - d->sr_q) * (1.0f / 4096);
        d->hi[d->n & 63] = (float)ri - d->sr_i;
        d->hq[d->n & 63] = (float)rq - d->sr_q;
        d->n++;
        if (d->n & 3)
            continue;
        /* co czwarta para: wynik filtrów; najnowsza próbka I ma indeks n-1, środek filtru I = n-1-24,
           filtr Q bierze Q[n-49 .. n-2] – jego środek wypada w tej samej chwili (Q jest czytane pół okresu po I) */
        float yi = 0, yq = 0;
        uint32_t b = d->n - DSP_LP_I;
        for (int k = 0; k < DSP_LP_I; k++)
            yi += d->lp_i[k] * d->hi[(b + (uint32_t)k) & 63];
        b = d->n - 1 - DSP_LP_Q;
        for (int k = 0; k < DSP_LP_Q; k++)
            yq += d->lp_q[k] * d->hq[(b + (uint32_t)k) & 63];
        d->sum_i2 += (double)yi * yi;
        d->sum_q2 += (double)yq * yq;
        d->sum_iq += (double)yi * yq;
        d->pom_n++;
        uint32_t p = d->nd % DSP_HIL;
        d->di[p] = yi;
        d->dq[p] = yq;
        d->nd++;
        /* dźwięk = I opóźnione o połowę przesuwnika + (lub -) Q przesunięte o 90 st. */
        float h = 0;
        uint32_t st = d->nd % DSP_HIL; /* najstarsza próbka */
        for (int k = 0; k < DSP_HIL; k += 2) /* współczynniki o parzystej odległości od środka są zerowe -> k parzyste przy 127 */
            h += d->hil[k] * d->dq[(st + (uint32_t)(DSP_HIL - 1 - k)) % DSP_HIL];
        float isr = d->di[(st + (DSP_HIL - 1) / 2) % DSP_HIL];
        wyj[nw++] = (isr + (float)d->bok * h) * (1.0f / 2048.0f);
    }
    return nw;
}

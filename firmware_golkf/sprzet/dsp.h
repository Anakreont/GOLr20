/* GOLkf / R20 – tor odbiorczy cyfrowy: próbki I/Q z przetwornika (48 kHz na kanał) -> dźwięk jednej wstęgi 12 kHz.
   Bez sprzętu, testowany na PC. */
#ifndef DSP_H
#define DSP_H
#include <stdint.h>
#define DSP_FS_ADC 48000
#define DSP_FS 12000
#define DSP_LP_I 49   /* filtr przed decymacją, tor I (nieparzysty) */
#define DSP_LP_Q 48   /* tor Q (parzysty: wyrównuje pół próbki opóźnienia, bo przetwornik czyta I i Q na przemian) */
#define DSP_HIL 127   /* przesuwnik fazy 90 st. */

typedef struct
{
    float lp_i[DSP_LP_I], lp_q[DSP_LP_Q], hil[DSP_HIL];
    float hi[64], hq[64];           /* historia surowych próbek (pierścień) */
    float di[DSP_HIL], dq[DSP_HIL]; /* historia po decymacji (pierścień) */
    uint32_t n, nd;
    float sr_i, sr_q;               /* składowa stała */
    int bok;                        /* +1 / -1: która wstęga */
    /* pomiary do diagnostyki */
    double sum_i2, sum_q2, sum_iq;
    uint32_t pom_n;
    uint16_t min_i, max_i, min_q, max_q;
} dsp_t;

void dsp_start(dsp_t* d, int bok);
/* pary[2*i] = I, pary[2*i+1] = Q (kody przetwornika 0–4095); zwraca liczbę próbek dźwięku dopisanych do wyj */
int dsp_dodaj(dsp_t* d, const uint16_t* pary, int n_par, float* wyj);
#endif

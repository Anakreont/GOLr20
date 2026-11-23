/* GOLkf / R20 – dekoder FT8 (patrz dekoder.h). Ocena SNR jak w narzedzia/cw7300/ft8/ft8shim.c. */
#include "dekoder.h"
#include <string.h>
#include <common/monitor.h>
#include <ft8/constants.h>
#include <ft8/decode.h>
#include <ft8/encode.h>

#define MAX_KAND 140
#define SNR_PAS 48
#define SNR_STALA 28.0f
static monitor_t mon;
static bool gotowy;
static ftx_candidate_t kand[MAX_KAND];

bool dek_init(void)
{
    monitor_config_t cfg = { .f_min = 200, .f_max = 3000, .sample_rate = 12000, .time_osr = 2, .freq_osr = 2, .protocol = FTX_PROTOCOL_FT8 };
    monitor_init(&mon, &cfg);
    gotowy = mon.wf.mag != NULL && mon.window != NULL && mon.last_frame != NULL && mon.fft_work != NULL;
    return gotowy;
}

void dek_reset(void)
{
    if (gotowy)
        monitor_reset(&mon);
}

void dek_blok(const float* blok)
{
    if (gotowy && mon.wf.num_blocks < mon.wf.max_blocks)
        monitor_process(&mon, blok);
}

int dek_blokow(void) { return gotowy ? mon.wf.num_blocks : 0; }

/* szum w okolicy sygnału: mediana punktów wodospadu w pasie +-300 Hz (histogram wartości 0-255) */
static float szum_obok(const ftx_waterfall_t* wf, const ftx_candidate_t* c)
{
    static uint32_t hist[256];
    int b0 = c->freq_offset - SNR_PAS, b1 = c->freq_offset + 8 + SNR_PAS;
    if (b0 < 0)
        b0 = 0;
    if (b1 > wf->num_bins)
        b1 = wf->num_bins;
    memset(hist, 0, sizeof(hist));
    uint32_t n = 0;
    for (int blok = 0; blok < wf->num_blocks; blok++)
    {
        const WF_ELEM_T* p = wf->mag + (size_t)blok * wf->block_stride;
        for (int b = b0; b < b1; b++, n++)
            hist[(uint8_t)p[b]]++;
    }
    uint32_t s = 0;
    for (int v = 0; v < 256; v++)
    {
        s += hist[v];
        if (s * 2 >= n)
            return WF_ELEM_MAG((WF_ELEM_T)v);
    }
    return -120.0f;
}

static float snr(const ftx_waterfall_t* wf, const ftx_candidate_t* c, const uint8_t* tony)
{
    float sum = 0;
    int ile = 0;
    for (int k = 0; k < FT8_NN; k++)
    {
        int blok = c->time_offset + k, bin = c->freq_offset + tony[k];
        if (blok < 0 || blok >= wf->num_blocks || bin < 0 || bin >= wf->num_bins)
            continue;
        const WF_ELEM_T* p = wf->mag + (size_t)blok * wf->block_stride + (size_t)(c->time_sub * wf->freq_osr + c->freq_sub) * wf->num_bins + bin;
        sum += WF_ELEM_MAG(*p);
        ile++;
    }
    if (!ile)
        return -30.0f;
    return sum / (float)ile - szum_obok(wf, c) - SNR_STALA;
}

int dek_dekoduj(gk_dekod* d, int max, int max_kand, bool (*czy_dalej)(void), float* sr_dt, int* kandydatow)
{
    if (sr_dt)
        *sr_dt = 0;
    if (kandydatow)
        *kandydatow = 0;
    if (!gotowy)
        return 0;
    if (max_kand < 1 || max_kand > MAX_KAND)
        max_kand = MAX_KAND;
    const ftx_waterfall_t* wf = &mon.wf;
    int nk = ftx_find_candidates(wf, max_kand, kand, 10);
    if (kandydatow)
        *kandydatow = nk;
    int n = 0;
    float sdt = 0;
    for (int i = 0; i < nk && n < max; i++)
    {
        if (czy_dalej && !czy_dalej())
            break;
        ftx_message_t msg;
        ftx_decode_status_t st;
        if (!ftx_decode_candidate(wf, &kand[i], 25, &msg, &st))
            continue;
        bool jest = false;
        for (int k = 0; k < n && !jest; k++)
            jest = !memcmp(d[k].payload, msg.payload, 10);
        if (jest)
            continue;
        uint8_t tony[FT8_NN];
        ft8_encode(msg.payload, tony);
        float s = snr(wf, &kand[i], tony);
        float hz = ((float)mon.min_bin + (float)kand[i].freq_offset + (float)kand[i].freq_sub / (float)wf->freq_osr) / mon.symbol_period;
        float dt = ((float)kand[i].time_offset + (float)kand[i].time_sub / (float)wf->time_osr) * mon.symbol_period - 0.5f;
        memcpy(d[n].payload, msg.payload, 10);
        d[n].snr = (int8_t)(s < -30 ? -30 : (s > 40 ? 40 : (s < 0 ? s - 0.5f : s + 0.5f)));
        d[n].hz = (uint16_t)(hz + 0.5f);
        sdt += dt;
        n++;
    }
    if (sr_dt && n)
        *sr_dt = sdt / (float)n;
    return n;
}

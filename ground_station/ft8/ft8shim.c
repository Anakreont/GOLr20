/*
 * ft8shim – cienka warstwa nad biblioteką kgoba/ft8_lib (MIT) dla programu GOLbase (zakładka „FT8 balon”).
 * Budowana jako biblioteka dzielona (ft8shim.dll / libft8shim.so) i wołana z Pythona przez ctypes (ft8silnik.py).
 *
 * Funkcje:
 *   ft8s_decode       – dekoduje jedno okno (próbki float, zwykle 12 kHz, 15 s dla FT8 / 7,5 s dla FT4)
 *   ft8s_pack_text    – tekst komunikatu -> 10 bajtów (77 bitów)
 *   ft8s_pack_telem   – 9 bajtów telemetrii (71 bitów, wyrównane do prawej) -> 10 bajtów
 *   ft8s_tones        – 10 bajtów -> tony (79 dla FT8, 105 dla FT4)
 *   ft8s_add_call     – dopisuje znak do tablicy skrótów (żeby <...> rozwijało się do znaku)
 *
 * Tablica skrótów znaków jest globalna – bibliotekę woła jeden wątek naraz (pilnuje tego ft8silnik.py).
 */
#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include <common/monitor.h>
#include <ft8/constants.h>
#include <ft8/decode.h>
#include <ft8/encode.h>
#include <ft8/message.h>

#ifdef _WIN32
#define API __declspec(dllexport)
#else
#define API __attribute__((visibility("default")))
#endif

#ifdef stpcpy
/* zamiennik stpcpy dla systemów bez niej (Windows) – patrz zgodnosc.h */
#undef stpcpy
char* ft8s_stpcpy(char* dst, const char* src)
{
    while ((*dst = *src++) != 0)
        ++dst;
    return dst;
}
#endif

#define HASH_SIZE 512
static struct
{
    char call[12];
    uint32_t n22;
    uint32_t age;
} htab[HASH_SIZE];
static uint32_t hclock = 0;

static void h_save(const char* call, uint32_t n22)
{
    int free_i = -1, old_i = 0;
    for (int i = 0; i < HASH_SIZE; ++i)
    {
        if (htab[i].call[0] == 0)
        {
            if (free_i < 0)
                free_i = i;
            continue;
        }
        if (htab[i].n22 == n22 && 0 == strcmp(htab[i].call, call))
        {
            htab[i].age = ++hclock;
            return;
        }
        if (htab[i].age < htab[old_i].age || htab[old_i].call[0] == 0)
            old_i = i;
    }
    int i = (free_i >= 0) ? free_i : old_i; /* pełna tablica: nadpisz najdawniej używany wpis */
    strncpy(htab[i].call, call, 11);
    htab[i].call[11] = 0;
    htab[i].n22 = n22;
    htab[i].age = ++hclock;
}

static bool h_lookup(ftx_callsign_hash_type_t type, uint32_t hash, char* call)
{
    int shift = (type == FTX_CALLSIGN_HASH_10_BITS) ? 12 : (type == FTX_CALLSIGN_HASH_12_BITS ? 10 : 0);
    int best = -1;
    for (int i = 0; i < HASH_SIZE; ++i)
    {
        if (htab[i].call[0] && (htab[i].n22 >> shift) == hash && (best < 0 || htab[i].age > htab[best].age))
            best = i;
    }
    if (best < 0)
        return false;
    strcpy(call, htab[best].call);
    return true;
}

static ftx_callsign_hash_interface_t hash_if = { .lookup_hash = h_lookup, .save_hash = h_save };

typedef struct
{
    float freq_hz;       /* częstotliwość najniższego tonu */
    float dt_s;          /* początek sygnału względem początku bufora */
    float snr_db;        /* zgrubnie, w paśmie 2500 Hz jak w WSJT-X */
    int32_t score;       /* ocena synchronizacji */
    int32_t type;        /* ftx_message_type_t (5 = telemetria) */
    uint8_t payload[10]; /* 77 bitów komunikatu */
    char text[40];
} ft8s_result_t;

static int cmp_float(const void* a, const void* b)
{
    float x = *(const float*)a, y = *(const float*)b;
    return (x > y) - (x < y);
}

/* Poziom szumu w okolicy sygnału: mediana punktów wodospadu w pasie +-300 Hz wokół niego (cały czas okna).
   Sygnały FT8 zajmują w każdej chwili tylko jeden z ośmiu tonów, więc mediany prawie nie podnoszą.
   Do 1.12 szum liczony był z całego okna 200-3000 Hz: gdy filtr radia przepuszcza węższy pas (QO-100),
   mediana wypadała w wyciszonej części i raporty wychodziły o kilkanaście dB za wysokie (+36 zamiast ok. +20). */
#define SNR_PAS_BINS 48
static float local_noise(const ftx_waterfall_t* wf, const ftx_candidate_t* cand, float fallback)
{
    int b0 = cand->freq_offset - SNR_PAS_BINS, b1 = cand->freq_offset + 8 + SNR_PAS_BINS;
    if (b0 < 0)
        b0 = 0;
    if (b1 > wf->num_bins)
        b1 = wf->num_bins;
    if (b1 - b0 < 16 || wf->num_blocks < 1)
        return fallback;
    size_t n = (size_t)(b1 - b0) * wf->num_blocks, i = 0;
    float* tmp = (float*)malloc(n * sizeof(float));
    if (!tmp)
        return fallback;
    for (int block = 0; block < wf->num_blocks; ++block)
    {
        const WF_ELEM_T* p = wf->mag + (size_t)block * wf->block_stride;
        for (int bin = b0; bin < b1; ++bin)
            tmp[i++] = WF_ELEM_MAG(p[bin]);
    }
    qsort(tmp, n, sizeof(float), cmp_float);
    float m = tmp[n / 2];
    free(tmp);
    return m;
}

/* SNR (zgrubny): średni poziom tonów sygnału minus szum z okolicy sygnału, przeliczone z 6,25 Hz na 2500 Hz.
   Stała dobrana tak, żeby na nagraniach testowych ft8_lib średnio zgadzać się z raportami WSJT-X (rozrzut ok. 4 dB). */
#define SNR_STALA 28.0f
static float estimate_snr(const ftx_waterfall_t* wf, const ftx_candidate_t* cand, const uint8_t* tones, int num_tones, float noise_db)
{
    float sum = 0;
    int cnt = 0;
    for (int k = 0; k < num_tones; ++k)
    {
        int block = cand->time_offset + k;
        if (block < 0 || block >= wf->num_blocks)
            continue;
        int bin = cand->freq_offset + tones[k];
        if (bin < 0 || bin >= wf->num_bins)
            continue;
        const WF_ELEM_T* p = wf->mag + (size_t)block * wf->block_stride + (size_t)(cand->time_sub * wf->freq_osr + cand->freq_sub) * wf->num_bins + bin;
        sum += WF_ELEM_MAG(*p);
        ++cnt;
    }
    if (cnt == 0)
        return -30.0f;
    return sum / cnt - local_noise(wf, cand, noise_db) - SNR_STALA;
}

API int ft8s_decode(const float* samples, int num_samples, int sample_rate, float f_min, float f_max, int is_ft4,
    int max_candidates, int ldpc_iterations, ft8s_result_t* out, int max_out)
{
    if (max_candidates < 1)
        max_candidates = 140;
    if (max_candidates > 400)
        max_candidates = 400;
    if (ldpc_iterations < 1)
        ldpc_iterations = 25;

    monitor_t mon;
    monitor_config_t cfg = {
        .f_min = f_min,
        .f_max = f_max,
        .sample_rate = sample_rate,
        .time_osr = 2,
        .freq_osr = 2,
        .protocol = is_ft4 ? FTX_PROTOCOL_FT4 : FTX_PROTOCOL_FT8
    };
    monitor_init(&mon, &cfg);
    for (int pos = 0; pos + mon.block_size <= num_samples; pos += mon.block_size)
    {
        if (mon.wf.num_blocks >= mon.wf.max_blocks)
            break;
        monitor_process(&mon, samples + pos);
    }
    const ftx_waterfall_t* wf = &mon.wf;

    /* poziom szumu = mediana wszystkich punktów wodospadu (co 7. punkt, żeby było szybko) */
    float noise_db = -120.0f;
    {
        size_t total = (size_t)wf->num_blocks * wf->block_stride;
        size_t n = total / 7;
        if (n > 0)
        {
            float* tmp = (float*)malloc(n * sizeof(float));
            if (tmp)
            {
                for (size_t i = 0; i < n; ++i)
                    tmp[i] = WF_ELEM_MAG(wf->mag[i * 7]);
                qsort(tmp, n, sizeof(float), cmp_float);
                noise_db = tmp[n / 2];
                free(tmp);
            }
        }
    }

    ftx_candidate_t* cands = (ftx_candidate_t*)malloc(sizeof(ftx_candidate_t) * max_candidates);
    int num_cand = cands ? ftx_find_candidates(wf, max_candidates, cands, 10) : 0;
    int num_out = 0;
    int num_tones = is_ft4 ? FT4_NN : FT8_NN;
    for (int i = 0; i < num_cand && num_out < max_out; ++i)
    {
        const ftx_candidate_t* cand = &cands[i];
        ftx_message_t msg;
        ftx_decode_status_t status;
        if (!ftx_decode_candidate(wf, cand, ldpc_iterations, &msg, &status))
            continue;
        bool dup = false;
        for (int k = 0; k < num_out; ++k)
        {
            if (0 == memcmp(out[k].payload, msg.payload, 10))
            {
                dup = true;
                break;
            }
        }
        if (dup)
            continue;
        ft8s_result_t* r = &out[num_out];
        memset(r, 0, sizeof(*r));
        char text[FTX_MAX_MESSAGE_LENGTH + 8];
        ftx_message_offsets_t offsets;
        ftx_message_rc_t rc = ftx_message_decode(&msg, &hash_if, text, &offsets);
        if (rc != FTX_MESSAGE_RC_OK)
            strcpy(text, "?");
        strncpy(r->text, text, sizeof(r->text) - 1);
        memcpy(r->payload, msg.payload, 10);
        r->type = (int32_t)ftx_message_get_type(&msg);
        r->score = cand->score;
        r->freq_hz = (mon.min_bin + cand->freq_offset + (float)cand->freq_sub / wf->freq_osr) / mon.symbol_period;
        r->dt_s = (cand->time_offset + (float)cand->time_sub / wf->time_osr) * mon.symbol_period;
        uint8_t tones[FT4_NN > FT8_NN ? FT4_NN : FT8_NN];
        if (is_ft4)
            ft4_encode(msg.payload, tones);
        else
            ft8_encode(msg.payload, tones);
        r->snr_db = estimate_snr(wf, cand, tones, num_tones, noise_db);
        ++num_out;
    }
    free(cands);
    monitor_free(&mon);
    return num_out;
}

API int ft8s_pack_text(const char* text, uint8_t* payload10)
{
    ftx_message_t msg;
    ftx_message_init(&msg);
    ftx_message_rc_t rc = ftx_message_encode(&msg, &hash_if, text);
    if (rc != FTX_MESSAGE_RC_OK)
        return (int)rc;
    memcpy(payload10, msg.payload, 10);
    return 0;
}

/* telem9: 71 bitów wyrównanych do prawej w 9 bajtach (najstarszy bit bajtu 0 = 0) */
API int ft8s_pack_telem(const uint8_t* telem9, uint8_t* payload10)
{
    if (telem9[0] & 0x80)
        return -1;
    ftx_message_t msg;
    ftx_message_init(&msg);
    ftx_message_encode_telemetry(&msg, telem9);
    msg.payload[8] &= 0xFE;
    msg.payload[8] |= 0x01;             /* n3 = 5 (101): bit 71 = 1 */
    msg.payload[9] = 0x40;              /* bity 72, 73 = 01; i3 = 000 */
    memcpy(payload10, msg.payload, 10);
    return 0;
}

API int ft8s_tones(const uint8_t* payload10, int is_ft4, uint8_t* tones)
{
    if (is_ft4)
    {
        ft4_encode(payload10, tones);
        return FT4_NN;
    }
    ft8_encode(payload10, tones);
    return FT8_NN;
}

API int ft8s_unpack(const uint8_t* payload10, char* text40, int32_t* type)
{
    ftx_message_t msg;
    ftx_message_init(&msg);
    memcpy(msg.payload, payload10, 10);
    char text[FTX_MAX_MESSAGE_LENGTH + 8];
    ftx_message_offsets_t offsets;
    ftx_message_rc_t rc = ftx_message_decode(&msg, &hash_if, text, &offsets);
    *type = (int32_t)ftx_message_get_type(&msg);
    if (rc != FTX_MESSAGE_RC_OK)
        return (int)rc;
    strncpy(text40, text, 39);
    text40[39] = 0;
    return 0;
}

API void ft8s_add_call(const char* call)
{
    /* zakodowanie komunikatu ze znakiem zapisuje jego skróty w tablicy */
    char buf[48];
    ftx_message_t msg;
    ftx_message_init(&msg);
    strcpy(buf, "CQ ");
    strncat(buf, call, 12);
    if (ftx_message_encode(&msg, &hash_if, buf) != FTX_MESSAGE_RC_OK)
    {
        strcpy(buf, "CQ <");
        strncat(buf, call, 12);
        strcat(buf, ">");
        ftx_message_encode(&msg, &hash_if, buf);
    }
}

API int ft8s_version(void) { return 1; }

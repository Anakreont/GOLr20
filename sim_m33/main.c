// Symulacja dekodera FT8 (ft8_lib) na Cortex-M33 w QEMU - pomiar liczby instrukcji. 21.11.2026
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdbool.h>
#include "ft8/decode.h"
#include "ft8/message.h"
#include "common/monitor.h"

extern const int16_t wav_start[]; extern const int16_t wav_end[];
#ifndef MAX_CAND
#define MAX_CAND 140
#endif
#ifndef LDPC_IT
#define LDPC_IT 25
#endif
#ifndef F_MIN
#define F_MIN 200
#endif
#ifndef F_MAX
#define F_MAX 3000
#endif

#define SYST_CSR (*(volatile uint32_t*)0xE000E010)
#define SYST_RVR (*(volatile uint32_t*)0xE000E014)
#define SYST_CVR (*(volatile uint32_t*)0xE000E018)
volatile uint32_t wraps;
void SysTick_Handler(void) { wraps++; }
static uint64_t ticks(void) { uint32_t w, c; do { w = wraps; c = SYST_CVR; } while (w != wraps); return (uint64_t)w * 0x1000000u + (0xFFFFFFu - c); }

static int sh(int op, void* arg) { register int r0 __asm__("r0") = op; register void* r1 __asm__("r1") = arg; __asm__ volatile("bkpt 0xAB" : "+r"(r0) : "r"(r1) : "memory"); return r0; }
static void out(const char* s) { sh(0x04, (void*)s); }
static bool hl(ftx_callsign_hash_type_t t, uint32_t h, char* c) { (void)t; (void)h; c[0] = 0; return false; }
static void ha(const char* c, uint32_t h) { (void)c; (void)h; }
static ftx_callsign_hash_interface_t hif = { .lookup_hash = hl, .save_hash = ha };
static float frame[1920];
static char buf[160];

int main(void)
{
    SYST_RVR = 0xFFFFFF; SYST_CVR = 0; SYST_CSR = 7;
    monitor_t mon;
    monitor_config_t cfg = { .f_min = F_MIN, .f_max = F_MAX, .sample_rate = 12000, .time_osr = 2, .freq_osr = 2, .protocol = FTX_PROTOCOL_FT8 };
    uint64_t t0 = ticks();
    monitor_init(&mon, &cfg);
    uint64_t t1 = ticks();
    int n = wav_end - wav_start, bl = 0;
    for (int pos = 0; pos + mon.block_size <= n; pos += mon.block_size) {
        for (int i = 0; i < mon.block_size; i++) frame[i] = wav_start[pos + i] / 32768.0f;
        monitor_process(&mon, frame); bl++;
    }
    uint64_t t2 = ticks();
    static ftx_candidate_t cl[140];
    int nc = ftx_find_candidates(&mon.wf, MAX_CAND, cl, 10);
    uint64_t t3 = ticks();
    static ftx_message_t dec[50]; static ftx_message_t* ht[50]; int nd = 0;
    for (int i = 0; i < nc; i++) {
        ftx_message_t m; ftx_decode_status_t st;
        if (!ftx_decode_candidate(&mon.wf, &cl[i], LDPC_IT, &m, &st)) continue;
        int ih = m.hash % 50; bool e = false, d = false;
        do { if (!ht[ih]) e = true; else if (ht[ih]->hash == m.hash && !memcmp(ht[ih]->payload, m.payload, sizeof(m.payload))) d = true; else ih = (ih + 1) % 50; } while (!e && !d);
        if (e) { memcpy(&dec[ih], &m, sizeof(m)); ht[ih] = &dec[ih]; nd++;
            char text[FTX_MAX_MESSAGE_LENGTH]; ftx_message_offsets_t off;
            if (ftx_message_decode(&m, &hif, text, &off) == FTX_MESSAGE_RC_OK && nd <= 3) { out("  "); out(text); out("\n"); } }
    }
    uint64_t t4 = ticks();
    // 1 tik SysTick (20 MHz) = 50 ns czasu wirtualnego = 50 instrukcji przy -icount shift=0
    snprintf(buf, sizeof buf, "blokow %d, kandydatow %d, dekodow %d\ninstr_mln: init %lu, widmo %lu (na blok %lu tys.), kandydaci %lu, dekodowanie %lu, PO_OKNIE %lu\n",
        bl, nc, nd, (unsigned long)((t1 - t0) * 50 / 1000000), (unsigned long)((t2 - t1) * 50 / 1000000), (unsigned long)((t2 - t1) * 50 / 1000 / (bl ? bl : 1)),
        (unsigned long)((t3 - t2) * 50 / 1000000), (unsigned long)((t4 - t3) * 50 / 1000000), (unsigned long)((t4 - t2) * 50 / 1000000));
    out(buf);
    static uint32_t ex[2] = { 0x20026, 0 }; sh(0x20, ex); sh(0x18, (void*)0x20026);
    for (;;) {}
}

/*
 * GOLkf – rdzeń (logika trackera-robota FT8). Opis interfejsu: golkf.h.
 * Jedyna zależność: kgoba/ft8_lib (pakowanie i rozpakowanie zwykłych komunikatów FT8).
 */
#include "golkf.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <ft8/message.h>

const char* const gk_pasma[] = { "160m", "80m", "60m", "40m", "30m", "20m", "17m", "15m", "12m", "10m", "6m" };
#define N_PASM 11
/* częstotliwości „dial” FT8 i WSPR [Hz]; minuta startu kanału 0 wg mapy kanałów Traquito (znane dla 20–10 m, reszta przyjęta 0) */
static const uint32_t FT8_DIAL[N_PASM] = { 1840000, 3573000, 5357000, 7074000, 10136000, 14074000, 18100000, 21074000, 24915000, 28074000, 50313000 };
static const uint32_t WSPR_DIAL[N_PASM] = { 1836600, 3568600, 5287200, 7038600, 10138700, 14095600, 18104600, 21094600, 24924600, 28124600, 50293000 };
static const uint8_t WSPR_MIN[N_PASM] = { 0, 0, 0, 0, 0, 8, 2, 6, 0, 4, 0 };

/* ====================================================================== SHA-256 i HMAC (podpis komend) */
static const uint32_t K256[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be,
    0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa,
    0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85,
    0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3,
    0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f,
    0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
};
#define ROR(x, n) (((x) >> (n)) | ((x) << (32 - (n))))

typedef struct
{
    uint32_t h[8];
    uint8_t buf[64];
    uint32_t n;
    uint64_t razem;
} sha_t;

static void sha_blok(sha_t* s, const uint8_t* p)
{
    uint32_t w[64], a[8];
    for (int i = 0; i < 16; ++i)
        w[i] = ((uint32_t)p[4 * i] << 24) | ((uint32_t)p[4 * i + 1] << 16) | ((uint32_t)p[4 * i + 2] << 8) | p[4 * i + 3];
    for (int i = 16; i < 64; ++i)
    {
        uint32_t s0 = ROR(w[i - 15], 7) ^ ROR(w[i - 15], 18) ^ (w[i - 15] >> 3);
        uint32_t s1 = ROR(w[i - 2], 17) ^ ROR(w[i - 2], 19) ^ (w[i - 2] >> 10);
        w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    memcpy(a, s->h, sizeof(a));
    for (int i = 0; i < 64; ++i)
    {
        uint32_t S1 = ROR(a[4], 6) ^ ROR(a[4], 11) ^ ROR(a[4], 25);
        uint32_t t1 = a[7] + S1 + ((a[4] & a[5]) ^ (~a[4] & a[6])) + K256[i] + w[i];
        uint32_t S0 = ROR(a[0], 2) ^ ROR(a[0], 13) ^ ROR(a[0], 22);
        uint32_t t2 = S0 + ((a[0] & a[1]) ^ (a[0] & a[2]) ^ (a[1] & a[2]));
        memmove(a + 1, a, 7 * sizeof(uint32_t));
        a[4] += t1;
        a[0] = t1 + t2;
    }
    for (int i = 0; i < 8; ++i)
        s->h[i] += a[i];
}

static void sha_start(sha_t* s)
{
    static const uint32_t h0[8] = { 0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19 };
    memcpy(s->h, h0, sizeof(h0));
    s->n = 0;
    s->razem = 0;
}

static void sha_dodaj(sha_t* s, const uint8_t* d, int n)
{
    s->razem += (uint64_t)n;
    while (n-- > 0)
    {
        s->buf[s->n++] = *d++;
        if (s->n == 64)
        {
            sha_blok(s, s->buf);
            s->n = 0;
        }
    }
}

static void sha_koniec(sha_t* s, uint8_t* out)
{
    uint64_t bity = s->razem * 8;
    uint8_t b = 0x80;
    sha_dodaj(s, &b, 1);
    b = 0;
    while (s->n != 56)
        sha_dodaj(s, &b, 1);
    uint8_t len[8];
    for (int i = 0; i < 8; ++i)
        len[i] = (uint8_t)(bity >> (56 - 8 * i));
    sha_dodaj(s, len, 8);
    for (int i = 0; i < 8; ++i)
        for (int k = 0; k < 4; ++k)
            out[4 * i + k] = (uint8_t)(s->h[i] >> (24 - 8 * k));
}

void gk_hmac_sha256(const uint8_t* klucz, int nk, const uint8_t* dane, int nd, uint8_t* wynik32)
{
    uint8_t k[64] = { 0 }, pad[64], w[32];
    sha_t s;
    if (nk > 64)
    {
        sha_start(&s);
        sha_dodaj(&s, klucz, nk);
        sha_koniec(&s, k);
    }
    else
        memcpy(k, klucz, (size_t)nk);
    for (int i = 0; i < 64; ++i)
        pad[i] = k[i] ^ 0x36;
    sha_start(&s);
    sha_dodaj(&s, pad, 64);
    sha_dodaj(&s, dane, nd);
    sha_koniec(&s, w);
    for (int i = 0; i < 64; ++i)
        pad[i] = k[i] ^ 0x5c;
    sha_start(&s);
    sha_dodaj(&s, pad, 64);
    sha_dodaj(&s, w, 32);
    sha_koniec(&s, wynik32);
}

/* ====================================================================== bity ramki 71-bitowej
 * t9 = 9 bajtów, 71 bitów wyrównanych do prawej (najstarszy bit bajtu 0 zawsze 0). Pozycja 0 = pierwszy bit ramki. */
static uint32_t bity_wez(const uint8_t* t9, int poz, int n)
{
    uint32_t v = 0;
    for (int i = 0; i < n; ++i)
    {
        int b = poz + i + 1;
        v = (v << 1) | ((t9[b >> 3] >> (7 - (b & 7))) & 1u);
    }
    return v;
}

static void bity_daj(uint8_t* t9, int poz, int n, uint32_t v)
{
    for (int i = 0; i < n; ++i)
    {
        int b = poz + i + 1;
        uint8_t m = (uint8_t)(1u << (7 - (b & 7)));
        if ((v >> (n - 1 - i)) & 1u)
            t9[b >> 3] |= m;
        else
            t9[b >> 3] &= (uint8_t)~m;
    }
}

void gk_telem_na_payload(const uint8_t* t9, uint8_t* p)
{
    /* 71 bitów na pozycjach 0–70 ramki 77-bitowej, potem n3 = 5 (101), i3 = 0 */
    for (int i = 0; i < 9; ++i)
        p[i] = (uint8_t)((t9[i] << 1) | (i < 8 ? (t9[i + 1] >> 7) : 0));
    p[8] |= 0x01;
    p[9] = 0x40;
}

bool gk_payload_na_telem(const uint8_t* p, uint8_t* t9)
{
    if (((p[9] >> 3) & 7) != 0 || ((((p[8] & 1) << 2) | (p[9] >> 6)) != 5))
        return false;
    for (int i = 0; i < 9; ++i)
        t9[i] = (uint8_t)((p[i] >> 1) | (i > 0 ? (p[i - 1] << 7) : 0));
    return true;
}

/* ====================================================================== znaki i lokatory */
#define NTOKENS 2063592u
#define MAX22 4194304u
static const char A0[] = " 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";
static const char A3[] = " ABCDEFGHIJKLMNOPQRSTUVWXYZ";

static int idx(const char* tab, char c)
{
    const char* p = strchr(tab, c);
    return (p && c) ? (int)(p - tab) : -1;
}

uint32_t gk_pakuj_znak(const char* znak)
{
    char z[12], c6[7];
    int n = 0;
    while (znak[n] && n < 11)
    {
        z[n] = (char)((znak[n] >= 'a' && znak[n] <= 'z') ? znak[n] - 32 : znak[n]);
        ++n;
    }
    z[n] = 0;
    if (n == 0)
        return 0;
    if (strncmp(z, "3DA0", 4) == 0 && n > 4 && n <= 7)
    {
        memmove(z + 3, z + 4, (size_t)(n - 3));
        z[2] = '0';
        --n;
    }
    else if (strncmp(z, "3X", 2) == 0 && n > 2 && z[2] >= 'A' && z[2] <= 'Z' && n <= 7)
    {
        memmove(z + 1, z + 2, (size_t)(n - 1));
        z[0] = 'Q';
        --n;
    }
    memset(c6, ' ', 6);
    c6[6] = 0;
    if (n >= 3 && z[2] >= '0' && z[2] <= '9' && n <= 6)
        memcpy(c6, z, (size_t)n);
    else if (n >= 2 && z[1] >= '0' && z[1] <= '9' && n <= 5)
        memcpy(c6 + 1, z, (size_t)n);
    else
        return 0xFFFFFFFFu;
    int i0 = idx(A0, c6[0]), i1 = idx(A0 + 1, c6[1]), i2 = idx(A0 + 1, c6[2]);
    int i3 = idx(A3, c6[3]), i4 = idx(A3, c6[4]), i5 = idx(A3, c6[5]);
    if (i0 < 0 || i1 < 0 || i2 < 0 || i2 > 9 || i3 < 0 || i4 < 0 || i5 < 0)
        return 0xFFFFFFFFu;
    uint32_t v = (uint32_t)i0;
    v = v * 36 + (uint32_t)i1;
    v = v * 10 + (uint32_t)i2;
    v = v * 27 + (uint32_t)i3;
    v = v * 27 + (uint32_t)i4;
    v = v * 27 + (uint32_t)i5;
    return NTOKENS + MAX22 + v;
}

bool gk_rozpakuj_znak(uint32_t n28, char* znak)
{
    znak[0] = 0;
    if (n28 == 0)
        return true;
    if (n28 < NTOKENS + MAX22 || n28 >= (1u << 28))
        return false;
    uint32_t n = n28 - NTOKENS - MAX22;
    char c[7];
    c[5] = A3[n % 27]; n /= 27;
    c[4] = A3[n % 27]; n /= 27;
    c[3] = A3[n % 27]; n /= 27;
    c[2] = (char)('0' + n % 10); n /= 10;
    c[1] = A0[1 + n % 36]; n /= 36;
    if (n >= 37)
        return false;
    c[0] = A0[n];
    c[6] = 0;
    char z[12];
    if (strncmp(c, "3D0", 3) == 0 && c[3] != ' ')
        snprintf(z, sizeof(z), "3DA0%s", c + 3);
    else if (c[0] == 'Q' && c[1] >= 'A' && c[1] <= 'Z')
        snprintf(z, sizeof(z), "3X%s", c + 1);
    else
        snprintf(z, sizeof(z), "%s", c);
    /* obetnij spacje z obu stron; spacja w środku = nie znak */
    char* p = z;
    while (*p == ' ')
        ++p;
    int len = (int)strlen(p);
    while (len > 0 && p[len - 1] == ' ')
        --len;
    p[len] = 0;
    if (len < 3 || strchr(p, ' '))
        return false;
    strcpy(znak, p);
    return true;
}

static bool rozpakuj_lokator(uint32_t n, char* lok)
{
    lok[5] = (char)('A' + n % 24); n /= 24;
    lok[4] = (char)('A' + n % 24); n /= 24;
    lok[3] = (char)('0' + n % 10); n /= 10;
    lok[2] = (char)('0' + n % 10); n /= 10;
    if (n >= 18 * 18)
        return false;
    lok[1] = (char)('A' + n % 18);
    lok[0] = (char)('A' + n / 18);
    lok[6] = 0;
    return true;
}

void gk_lokator(float szer, float dlug, char* lok)
{
    float lo = dlug + 180.0f, la = szer + 90.0f;
    if (lo < 0) lo = 0;
    if (lo >= 360) lo = 359.999f;
    if (la < 0) la = 0;
    if (la >= 180) la = 179.999f;
    lok[0] = (char)('A' + (int)(lo / 20));
    lok[1] = (char)('A' + (int)(la / 10));
    lo = fmodf(lo, 20.0f);
    la = fmodf(la, 10.0f);
    lok[2] = (char)('0' + (int)(lo / 2));
    lok[3] = (char)('0' + (int)la);
    lo = fmodf(lo, 2.0f);
    la = fmodf(la, 1.0f);
    lok[4] = (char)('A' + (int)(lo * 12));
    lok[5] = (char)('A' + (int)(la * 24));
    lok[6] = 0;
}

/* ====================================================================== ramki danych (balon -> ziemia) */
void gk_ramka_log(const gk_wpis* w, uint32_t nr, uint8_t* t9)
{
    memset(t9, 0, 9);
    bity_daj(t9, 0, 1, 0);
    bity_daj(t9, 1, 28, w->z1);
    bity_daj(t9, 29, 28, w->z2);
    bity_daj(t9, 57, 11, (w->czas / 600) % 2048);
    bity_daj(t9, 68, 3, nr % 8);
}

void gk_ramka_stan(const gk_t* g, uint8_t* t9)
{
    uint32_t zal = g->n_wpisow - g->cfg.potw_do;
    int u = (int)lroundf(g->env.u_v / 0.05f), temp = g->env.temp_c + 90;
    uint32_t tryb = (g->cfg.cisza_do > g->env.t) ? GK_TRYB_CISZA : g->cfg.tryb;
    memset(t9, 0, 9);
    bity_daj(t9, 0, 2, 2);
    bity_daj(t9, 2, 14, g->n_wpisow);
    bity_daj(t9, 16, 8, zal > 255 ? 255 : zal);
    bity_daj(t9, 24, 14, g->n_qso);
    bity_daj(t9, 38, 7, (uint32_t)(u < 0 ? 0 : (u > 127 ? 127 : u)));
    bity_daj(t9, 45, 7, (uint32_t)(temp < 0 ? 0 : (temp > 127 ? 127 : temp)));
    bity_daj(t9, 52, 3, tryb);
    bity_daj(t9, 55, 6, g->cfg.ost_kom & 63u);
    int s = g->snr_dom + 24; /* 31 = jeszcze nie słyszał domu */
    bity_daj(t9, 61, 5, (g->snr_dom == 127) ? 31u : (uint32_t)(s < 0 ? 0 : (s > 30 ? 30 : s)));
    bity_daj(t9, 66, 5, g->dekody > 31 ? 31 : g->dekody);
}

/* ====================================================================== log */
static void zapisz_cfg(gk_t* g)
{
    if (g->plat.zapisz_cfg)
        g->plat.zapisz_cfg(&g->cfg);
}

static void log_zamknij(gk_t* g)
{
    if (!g->jest_otwarty)
        return;
    g->jest_otwarty = 0;
    if (g->n_wpisow >= GK_MAX_WPISOW)
        return; /* pamięć logu pełna – v0.1: nowe łączności już się nie mieszczą */
    g->wpis[g->n_wpisow] = g->otwarty;
    g->n_wpisow++;
    g->n_qso += g->otwarty.z2 ? 2 : 1;
    if (g->plat.zapisz_wpis)
        g->plat.zapisz_wpis(g->n_wpisow, &g->otwarty);
}

static void log_qso(gk_t* g, uint32_t n28, uint32_t t)
{
    if (g->jest_otwarty && t < g->otwarty.czas + 600)
    {
        g->otwarty.z2 = n28;
        log_zamknij(g);
        return;
    }
    log_zamknij(g);
    memset(&g->otwarty, 0, sizeof(g->otwarty));
    g->otwarty.z1 = n28;
    g->otwarty.czas = t;
    g->jest_otwarty = 1;
}

void gk_wczytaj_wpis(gk_t* g, const gk_wpis* w)
{
    if (g->n_wpisow >= GK_MAX_WPISOW)
        return;
    g->wpis[g->n_wpisow] = *w;
    g->wpis[g->n_wpisow].flagi = (g->n_wpisow + 1 <= g->cfg.potw_do) ? GK_W_POTW : 0;
    g->wpis[g->n_wpisow].nadano = 0;
    g->n_wpisow++;
    g->n_qso += w->z2 ? 2 : 1;
}

/* przesuń „potwierdzone do” przez kolejne potwierdzone wpisy */
static void log_przesun_potw(gk_t* g)
{
    while (g->cfg.potw_do < g->n_wpisow && (g->wpis[g->cfg.potw_do].flagi & GK_W_POTW))
        g->cfg.potw_do++;
}

/* numer wpisu do nadania teraz (0 = nie ma niepotwierdzonych): najpierw żądane przez dom, potem najrzadziej nadawane, z nich najnowszy */
static uint32_t log_nastepny(gk_t* g)
{
    uint32_t best = 0;
    for (uint32_t i = g->cfg.potw_do; i < g->n_wpisow; ++i)
    {
        const gk_wpis* w = &g->wpis[i];
        if (w->flagi & GK_W_POTW)
            continue;
        if (best == 0)
        {
            best = i + 1;
            continue;
        }
        const gk_wpis* b = &g->wpis[best - 1];
        bool wz = (w->flagi & GK_W_ZADANY) != 0, bz = (b->flagi & GK_W_ZADANY) != 0;
        if ((wz && !bz) || (wz == bz && w->nadano <= b->nadano))
            best = i + 1;
    }
    return best;
}

static bool log_byla_lacznosc(const gk_t* g, uint32_t n28, uint32_t od_czasu)
{
    for (uint32_t i = 0; i < g->n_wpisow; ++i)
        if ((g->wpis[i].z1 == n28 || g->wpis[i].z2 == n28) && g->wpis[i].czas >= od_czasu)
            return true;
    return g->jest_otwarty && g->otwarty.z1 == n28 && g->otwarty.czas >= od_czasu;
}

/* ====================================================================== komendy (dom -> balon) */
bool gk_komenda(gk_t* g, const uint8_t* t9, uint32_t t_okna, int8_t snr)
{
    gk_cfg* c = &g->cfg;
    if (bity_wez(t9, 0, 4) != 15 || !c->jest_klucz)
        return false;
    /* podpis: HMAC-SHA256(klucz, 47 bitów treści w 6 bajtach + numer okna w 4 bajtach), pierwsze 24 bity */
    uint8_t dane[10], mac[32];
    uint32_t hi = bity_wez(t9, 0, 15), lo = bity_wez(t9, 15, 32), okno = t_okna / 15;
    dane[0] = (uint8_t)(hi >> 8); dane[1] = (uint8_t)hi;
    dane[2] = (uint8_t)(lo >> 24); dane[3] = (uint8_t)(lo >> 16); dane[4] = (uint8_t)(lo >> 8); dane[5] = (uint8_t)lo;
    dane[6] = (uint8_t)(okno >> 24); dane[7] = (uint8_t)(okno >> 16); dane[8] = (uint8_t)(okno >> 8); dane[9] = (uint8_t)okno;
    gk_hmac_sha256(c->klucz, 16, dane, 10, mac);
    if (bity_wez(t9, 47, 24) != (((uint32_t)mac[0] << 16) | ((uint32_t)mac[1] << 8) | mac[2]))
        return false;

    uint32_t kod = bity_wez(t9, 4, 4), licznik = bity_wez(t9, 8, 6);
    const int A = 14; /* początek argumentów (33 bity) */
    char txt[12];
    switch (kod)
    {
    case 0: /* NADAWANIE: wlacz 1, zakres 2, dni 6 */
    {
        uint32_t wlacz = bity_wez(t9, A, 1), zakres = bity_wez(t9, A + 1, 2), dni = bity_wez(t9, A + 3, 6);
        uint8_t maska = (zakres == 0) ? 3 : (zakres == 1 ? 1 : 2);
        if (wlacz)
        {
            c->tx_wyl &= (uint8_t)~maska;
            if (!c->tx_wyl)
                c->tx_wlacz_o = 0;
        }
        else
        {
            c->tx_wyl |= maska;
            c->tx_wlacz_o = dni ? t_okna + dni * 86400u : 0;
        }
        break;
    }
    case 1: /* POTWIERDZENIE: do 14, mapa 19 (bit najstarszy = wpis do + 2) */
    {
        uint32_t d = bity_wez(t9, A, 14), mapa = bity_wez(t9, A + 14, 19);
        if (d > g->n_wpisow)
            d = g->n_wpisow;
        for (uint32_t i = 0; i < d; ++i)
            g->wpis[i].flagi = (g->wpis[i].flagi | GK_W_POTW) & (uint8_t)~GK_W_ZADANY;
        for (uint32_t i = 0; i < 19; ++i)
        {
            uint32_t nr = d + 2 + i;
            if (((mapa >> (18 - i)) & 1u) && nr <= g->n_wpisow)
                g->wpis[nr - 1].flagi |= GK_W_POTW;
        }
        if (d > c->potw_do)
            c->potw_do = d;
        log_przesun_potw(g);
        break;
    }
    case 2: /* DOSYLKA: od 14, do 14 */
    {
        uint32_t od = bity_wez(t9, A, 14), d = bity_wez(t9, A + 14, 14);
        if (od < 1)
            od = 1;
        for (uint32_t nr = od; nr <= d && nr <= g->n_wpisow; ++nr)
            g->wpis[nr - 1].flagi = (g->wpis[nr - 1].flagi | GK_W_ZADANY) & (uint8_t)~GK_W_POTW;
        if (od <= g->n_wpisow && c->potw_do > od - 1)
            c->potw_do = od - 1;
        break;
    }
    case 3: /* TRYB: tryb 3, godziny 8 */
    {
        uint32_t tryb = bity_wez(t9, A, 3), godz = bity_wez(t9, A + 3, 8);
        if (tryb > GK_TRYB_CISZA)
            return false;
        if (tryb == GK_TRYB_CISZA)
            c->cisza_do = t_okna + godz * 3600u;
        else
        {
            c->tryb = (uint8_t)tryb;
            c->cisza_do = 0;
        }
        break;
    }
    case 4: c->ft4 = (uint8_t)bity_wez(t9, A, 1); break;
    case 5: c->cq_hz = (uint16_t)bity_wez(t9, A, 12); c->log_hz = (uint16_t)bity_wez(t9, A + 12, 12); break;
    case 6: c->moc = (uint8_t)bity_wez(t9, A, 2); break;
    case 7:
        c->u_pelny = (uint8_t)bity_wez(t9, A, 7); c->u_wspr = (uint8_t)bity_wez(t9, A + 7, 7);
        c->slonce_pelny = (uint8_t)bity_wez(t9, A + 14, 6); c->slonce_wspr = (uint8_t)bity_wez(t9, A + 20, 6);
        break;
    case 8: /* STREFA: dodaj 1, nr 2, szer1 7, dlug1 8, szer2 7, dlug2 8 (kroki 2 stopni) */
    {
        gk_strefa* s = &c->strefa[bity_wez(t9, A + 1, 2)];
        int s1 = -90 + 2 * (int)bity_wez(t9, A + 3, 7), d1 = -180 + 2 * (int)bity_wez(t9, A + 10, 8);
        int s2 = -90 + 2 * (int)bity_wez(t9, A + 18, 7), d2 = -180 + 2 * (int)bity_wez(t9, A + 25, 8);
        s->czynna = (uint8_t)bity_wez(t9, A, 1);
        s->szer1 = (int8_t)(s1 < s2 ? s1 : s2); s->szer2 = (int8_t)(s1 < s2 ? s2 : s1);
        s->dlug1 = (int16_t)(d1 < d2 ? d1 : d2); s->dlug2 = (int16_t)(d1 < d2 ? d2 : d1);
        break;
    }
    case 9: c->regula = (uint8_t)bity_wez(t9, A, 2); break;
    case 11: break; /* PYTANIE – sama ramka STAN */
    case 12: /* PASMO: pasmo 4, kanał 10 */
    {
        uint32_t p = bity_wez(t9, A, 4), k = bity_wez(t9, A + 4, 10);
        if (p >= N_PASM || k > 599)
            return false;
        c->pasmo = (uint8_t)p;
        c->kanal = (uint16_t)k;
        break;
    }
    case 13: /* CZARNA_LISTA: dodaj 1, znak 28 */
    {
        uint32_t dodaj = bity_wez(t9, A, 1), z = bity_wez(t9, A + 1, 28);
        int wolne = -1;
        for (int i = 0; i < GK_CZARNA; ++i)
        {
            if (c->czarna[i] == z)
            {
                if (!dodaj)
                    c->czarna[i] = 0;
                wolne = -2;
            }
            else if (c->czarna[i] == 0 && wolne == -1)
                wolne = i;
        }
        if (dodaj && wolne >= 0)
            c->czarna[wolne] = z;
        break;
    }
    case 14: /* ZNAK: ktory 1 (0 FT8, 1 WSPR), znak 28 */
        if (!gk_rozpakuj_znak(bity_wez(t9, A + 1, 28), txt) || !txt[0])
            return false;
        strcpy(bity_wez(t9, A, 1) ? c->znak_wspr : c->znak_ft8, txt);
        break;
    case 15: /* LOKATOR: staly 1, lokator 25 */
        c->staly_lok = (uint8_t)bity_wez(t9, A, 1);
        if (c->staly_lok && !rozpakuj_lokator(bity_wez(t9, A + 1, 25), c->lokator))
            return false;
        break;
    default:
        return false; /* 10 TEKST i nieznane */
    }
    c->ost_kom = (uint8_t)licznik;
    g->snr_dom = snr;
    g->t_dom = t_okna;
    g->stan_teraz = 1;
    zapisz_cfg(g);
    return true;
}

/* ====================================================================== strefy ciszy, Słońce, kanał WSPR */
/* stałe strefy: Chiny (prostokąty z firmware ICT v2.2, w 0,1 stopnia: szer. min, max, dług. min, max) */
static const int16_t CHINY[][4] = {
    { 260, 410, 1040, 1230 }, { 215, 260, 1067, 1195 }, { 202, 215, 1093, 1115 }, { 180, 205, 1080, 1115 },
    { 230, 280, 975, 1060 }, { 210, 230, 995, 1018 }, { 300, 370, 780, 1040 }, { 280, 300, 850, 1040 },
    { 365, 420, 735, 970 }, { 420, 450, 795, 970 }, { 450, 490, 855, 910 }, { 370, 420, 970, 1190 },
    { 420, 450, 1110, 1190 }, { 410, 460, 1190, 1310 }, { 460, 485, 1190, 1345 }, { 485, 535, 1190, 1270 }
};
/* Korea Płn. i Jemen: kwadraty lokatora (lista Matta Downsa 2E1GYP z firmware ICT) */
static const char KWADRATY[] = "PN31 PN41 PN20 PN30 PN40 PM29 PM39 PM28 PM38 LK16 LK15 LK14 LK13 LK23 LK24 LK25 LK26 LK36 LK35 LK34 "
                               "LK33 LK44 LK45 LK46 LK47 LK48 LK58 LK57 LK56 LK55";

bool gk_strefa_ciszy(const gk_t* g, float szer, float dlug)
{
    int L = (int)(szer * 10.0f), O = (int)(dlug * 10.0f);
    for (unsigned i = 0; i < sizeof(CHINY) / sizeof(CHINY[0]); ++i)
        if (L >= CHINY[i][0] && L <= CHINY[i][1] && O >= CHINY[i][2] && O <= CHINY[i][3])
            return true;
    char lok[7];
    gk_lokator(szer, dlug, lok);
    lok[4] = 0;
    if (strstr(KWADRATY, lok))
        return true;
    for (int i = 0; i < GK_STREF; ++i)
    {
        const gk_strefa* s = &g->cfg.strefa[i];
        if (s->czynna && szer >= s->szer1 && szer <= s->szer2 && dlug >= s->dlug1 && dlug <= s->dlug2)
            return true;
    }
    return false;
}

/* wysokość Słońca nad horyzontem [stopnie], dokładność ok. 1 stopnia – wystarcza do progów zasilania */
float gk_slonce(uint32_t t, float szer, float dlug)
{
    const float R = 0.01745329252f;
    float dni = (float)((double)t / 86400.0 - 10957.5);          /* dni od 1.01.2000 12:00 UTC */
    float L = fmodf(280.460f + 0.9856474f * dni, 360.0f);        /* średnia długość Słońca */
    float gm = fmodf(357.528f + 0.9856003f * dni, 360.0f) * R;   /* anomalia średnia */
    float lam = (L + 1.915f * sinf(gm) + 0.020f * sinf(2 * gm)) * R;
    float eps = 23.439f * R;
    float dek = asinf(sinf(eps) * sinf(lam));
    float ra = atan2f(cosf(eps) * sinf(lam), cosf(lam));
    float gmst = fmodf(280.46061837f + 360.98564736629f * dni, 360.0f) * R;
    float h = gmst + dlug * R - ra;                              /* kąt godzinny */
    float s = sinf(szer * R) * sinf(dek) + cosf(szer * R) * cosf(dek) * cosf(h);
    return asinf(s) / R;
}

void gk_wspr_kanal(uint8_t pasmo, uint16_t kanal, uint32_t* czest_hz, uint8_t* minuta)
{
    static const uint8_t pas[4] = { 1, 2, 4, 5 };
    if (pasmo >= N_PASM)
        pasmo = 5;
    *czest_hz = WSPR_DIAL[pasmo] + 1400 + (uint32_t)(pas[(kanal % 20) / 5] - 1) * 40 + 20;
    *minuta = (uint8_t)((2 * (kanal % 5) + WSPR_MIN[pasmo]) % 10);
}

/* ====================================================================== komunikaty FT8 (przez ft8_lib) */
#define N_HASH 32
static struct
{
    char znak[12];
    uint32_t n22;
} tab_hash[N_HASH];
static int hash_poz;

static void h_zapisz(const char* znak, uint32_t n22)
{
    for (int i = 0; i < N_HASH; ++i)
        if (tab_hash[i].n22 == n22 && strcmp(tab_hash[i].znak, znak) == 0)
            return;
    strncpy(tab_hash[hash_poz].znak, znak, 11);
    tab_hash[hash_poz].znak[11] = 0;
    tab_hash[hash_poz].n22 = n22;
    hash_poz = (hash_poz + 1) % N_HASH;
}

static bool h_szukaj(ftx_callsign_hash_type_t typ, uint32_t hash, char* znak)
{
    int przes = (typ == FTX_CALLSIGN_HASH_10_BITS) ? 12 : (typ == FTX_CALLSIGN_HASH_12_BITS ? 10 : 0);
    for (int i = 0; i < N_HASH; ++i)
        if (tab_hash[i].znak[0] && (tab_hash[i].n22 >> przes) == hash)
        {
            strcpy(znak, tab_hash[i].znak);
            return true;
        }
    return false;
}

static ftx_callsign_hash_interface_t hash_if = { .lookup_hash = h_szukaj, .save_hash = h_zapisz };

static bool tekst_na_payload(const char* tekst, uint8_t* payload)
{
    ftx_message_t m;
    ftx_message_init(&m);
    if (ftx_message_encode(&m, &hash_if, tekst) != FTX_MESSAGE_RC_OK)
        return false;
    memcpy(payload, m.payload, 10);
    return true;
}

/* zwykły komunikat „DO OD RESZTA” -> trzy pola (bez nawiasów <>); false, gdy to inny rodzaj ramki */
static bool payload_na_pola(const uint8_t* payload, char* doo, char* od, char* reszta)
{
    ftx_message_t m;
    ftx_message_offsets_t off;
    char tekst[FTX_MAX_MESSAGE_LENGTH + 4];
    ftx_message_init(&m);
    memcpy(m.payload, payload, 10);
    if (ftx_message_decode(&m, &hash_if, tekst, &off) != FTX_MESSAGE_RC_OK)
        return false;
    char* pola[3] = { doo, od, reszta };
    doo[0] = od[0] = reszta[0] = 0;
    int k = 0, n = 0;
    for (const char* p = tekst; *p && k < 3; ++p)
    {
        if (*p == ' ')
        {
            if (n)
            {
                pola[k][n] = 0;
                ++k;
                n = 0;
            }
            continue;
        }
        if (*p != '<' && *p != '>' && n < 11)
            pola[k][n++] = *p;
    }
    if (k < 3 && n)
        pola[k][n] = 0;
    return doo[0] && od[0];
}

/* ====================================================================== automat łączności */
enum { K_ZGL, K_RAP, K_RRAP, K_RR, K_73, K_INNE };

static int rodzaj_reszty(const char* r)
{
    if (!r[0])
        return K_ZGL;
    if (strcmp(r, "RR73") == 0 || strcmp(r, "RRR") == 0)
        return K_RR;
    if (strcmp(r, "73") == 0)
        return K_73;
    if ((r[0] == '+' || r[0] == '-') && r[1] >= '0' && r[1] <= '9')
        return K_RAP;
    if (r[0] == 'R' && (r[1] == '+' || r[1] == '-'))
        return K_RRAP;
    if (strlen(r) == 4 && r[0] >= 'A' && r[0] <= 'R' && r[1] >= 'A' && r[1] <= 'R' && r[2] >= '0' && r[2] <= '9')
        return K_ZGL; /* lokator */
    return K_INNE;
}

static bool wolno_z(const gk_t* g, uint32_t n28, uint32_t t)
{
    for (int i = 0; i < GK_CZARNA; ++i)
        if (g->cfg.czarna[i] && g->cfg.czarna[i] == n28)
            return false;
    if (g->cfg.regula == 1)
        return !log_byla_lacznosc(g, n28, t > 86400 ? t - 86400 : 0);
    if (g->cfg.regula == 2)
        return !log_byla_lacznosc(g, n28, 0);
    return true;
}

static void qso_zaloguj(gk_t* g, uint32_t t)
{
    if (!g->qso.zalogowane)
    {
        g->qso.zalogowane = 1;
        log_qso(g, g->qso.n28, t);
    }
}

void gk_odebrano(gk_t* g, uint32_t t_okna, const gk_dekod* d, int n)
{
    gk_qso* q = &g->qso;
    g->dekody = (uint8_t)(n > 255 ? 255 : n);
    int nowy = -1, nowy_rodz = 0;
    uint32_t nowy_n28 = 0;
    char nowy_znak[12] = "";
    bool od_rozmowcy = false;
    for (int i = 0; i < n; ++i)
    {
        uint8_t t9[9];
        if (gk_payload_na_telem(d[i].payload, t9))
        {
            gk_komenda(g, t9, t_okna, d[i].snr);
            continue;
        }
        char doo[12], od[12], reszta[12];
        if (!payload_na_pola(d[i].payload, doo, od, reszta) || strcmp(doo, g->cfg.znak_ft8) != 0)
            continue;
        int rodz = rodzaj_reszty(reszta);
        uint32_t n28 = gk_pakuj_znak(od);
        if (rodz == K_INNE || n28 == 0 || n28 == 0xFFFFFFFFu)
            continue; /* znaków niestandardowych nie da się zapisać w logu 28-bitowym – nie robimy z nimi łączności */
        if (q->stan != Q_BRAK && n28 == q->n28)
        {
            od_rozmowcy = true;
            q->snr = d[i].snr;
            switch (rodz)
            {
            case K_ZGL:
                if (q->stan == Q_PO_RR73)
                    q->stan = Q_BRAK; /* łączność skończona, woła od nowa – potraktuj jak nowego */
                break;
            case K_RAP:
                if (q->stan == Q_RAPORT || q->stan == Q_RRAPORT)
                {
                    if (q->stan != Q_RRAPORT)
                        q->powt = 0;
                    q->stan = Q_RRAPORT;
                }
                break;
            case K_RRAP:
                if (q->stan == Q_RAPORT || q->stan == Q_RR73 || q->stan == Q_PO_RR73)
                {
                    qso_zaloguj(g, t_okna);
                    if (q->stan == Q_RAPORT)
                        q->powt = 0;
                    q->stan = (q->powt < 3) ? Q_RR73 : Q_BRAK;
                }
                break;
            case K_RR:
                if (q->stan == Q_RRAPORT)
                {
                    qso_zaloguj(g, t_okna);
                    q->stan = Q_73;
                }
                else
                    q->stan = Q_BRAK;
                break;
            case K_73:
                if (q->stan == Q_RRAPORT)
                    qso_zaloguj(g, t_okna);
                q->stan = Q_BRAK;
                break;
            }
            if (q->stan != Q_BRAK)
                continue;
        }
        /* kandydat na nową łączność: zgłoszenie z lokatorem albo od razu raport; wybieramy najsilniejszego */
        if ((rodz == K_ZGL || rodz == K_RAP) && wolno_z(g, n28, t_okna) && (nowy < 0 || d[i].snr > d[nowy].snr))
        {
            nowy = i;
            nowy_rodz = rodz;
            nowy_n28 = n28;
            strcpy(nowy_znak, od);
        }
    }
    if (q->stan == Q_PO_RR73 && !od_rozmowcy)
        q->stan = Q_BRAK; /* po naszym RR73 cisza – łączność zamknięta */
    if (q->stan == Q_BRAK && nowy >= 0)
    {
        memset(q, 0, sizeof(*q));
        strcpy(q->znak, nowy_znak);
        q->n28 = nowy_n28;
        q->snr = d[nowy].snr;
        q->stan = (nowy_rodz == K_ZGL) ? Q_RAPORT : Q_RRAPORT;
    }
}

/* ====================================================================== plan okien */
static void lokator_teraz(const gk_t* g, char* lok7)
{
    if (g->cfg.staly_lok)
        strcpy(lok7, g->cfg.lokator);
    else
        gk_lokator(g->env.szer, g->env.dlug, lok7);
}

/* Jak często nadawać ramki LOG: 0 = nie ma czego; 60 s, gdy jest wpis świeży (nadany mniej niż 3 razy) albo żądany przez dom;
 * 300 s, gdy zostały same stare, a dom od kwadransa się nie odzywa – pewnie jest poza zasięgiem, szkoda energii. */
static uint32_t log_odstep(const gk_t* g)
{
    uint32_t odstep = 0;
    for (uint32_t i = g->cfg.potw_do; i < g->n_wpisow; ++i)
    {
        const gk_wpis* w = &g->wpis[i];
        if (w->flagi & GK_W_POTW)
            continue;
        if (w->nadano < 3 || (w->flagi & GK_W_ZADANY) || (g->t_dom && g->env.t - g->t_dom < 900))
            return 60; /* świeży, żądany albo dom właśnie nas słyszy (komenda w ostatnich 15 min) */
        odstep = 300;
    }
    return odstep;
}

static void nadaj_tekst(gk_t* g, gk_akcja* a, const char* tekst)
{
    a->co = tekst_na_payload(tekst, a->payload) ? GK_NADAJ_FT8 : GK_SPI;
    a->hz = g->cfg.cq_hz;
    snprintf(a->opis, sizeof(a->opis), "%s", tekst);
}

static void nadaj_dane(gk_t* g, gk_akcja* a, const uint8_t* t9, const char* opis)
{
    gk_telem_na_payload(t9, a->payload);
    a->co = GK_NADAJ_FT8;
    a->hz = g->cfg.log_hz;
    snprintf(a->opis, sizeof(a->opis), "%s", opis);
}

/* co nadać w oknie nadawczym: łączność > STAN > LOG > CQ */
static void wybierz_nadawanie(gk_t* g, gk_akcja* a)
{
    gk_qso* q = &g->qso;
    const gk_cfg* c = &g->cfg;
    uint32_t t = g->env.t;
    char txt[40], lok[7];
    int snr = q->snr < -30 ? -30 : (q->snr > 30 ? 30 : q->snr);
    if (q->stan == Q_PO_RR73)
        q->stan = Q_BRAK;
    if ((q->stan == Q_RAPORT || q->stan == Q_RRAPORT) && q->powt >= 4)
        q->stan = Q_BRAK; /* cztery próby bez odpowiedzi – porzucamy, bez wpisu w logu */
    switch (q->stan)
    {
    case Q_RAPORT:
        snprintf(txt, sizeof(txt), "%s %s %+03d", q->znak, c->znak_ft8, snr);
        break;
    case Q_RRAPORT:
        snprintf(txt, sizeof(txt), "%s %s R%+03d", q->znak, c->znak_ft8, snr);
        break;
    case Q_RR73:
        snprintf(txt, sizeof(txt), "%s %s RR73", q->znak, c->znak_ft8);
        break;
    case Q_73:
        snprintf(txt, sizeof(txt), "%s %s 73", q->znak, c->znak_ft8);
        break;
    default:
        txt[0] = 0;
    }
    if (txt[0])
    {
        q->powt++;
        if (q->stan == Q_RR73)
            q->stan = Q_PO_RR73;
        else if (q->stan == Q_73)
            q->stan = Q_BRAK;
        nadaj_tekst(g, a, txt);
        if (a->co == GK_NADAJ_FT8)
            return;
        q->stan = Q_BRAK; /* nie dało się zakodować – porzuć */
    }
    uint8_t t9[9];
    if (g->stan_teraz || t - g->t_stan >= 600)
    {
        g->stan_teraz = 0;
        g->t_stan = t;
        gk_ramka_stan(g, t9);
        nadaj_dane(g, a, t9, "STAN");
        return;
    }
    uint32_t odstep = log_odstep(g);
    if (odstep && t - g->t_log >= odstep)
    {
        uint32_t nr = log_nastepny(g);
        if (nr)
        {
            gk_wpis* w = &g->wpis[nr - 1];
            if (w->nadano < 255)
                w->nadano++;
            w->flagi &= (uint8_t)~GK_W_ZADANY;
            g->t_log = t;
            gk_ramka_log(w, nr, t9);
            snprintf(txt, sizeof(txt), "LOG %u", (unsigned)nr);
            nadaj_dane(g, a, t9, txt);
            return;
        }
    }
    lokator_teraz(g, lok);
    lok[4] = 0;
    snprintf(txt, sizeof(txt), "CQ %s %s", c->znak_ft8, lok);
    nadaj_tekst(g, a, txt);
}

gk_akcja gk_okno(gk_t* g, const gk_env* e)
{
    gk_akcja a;
    gk_cfg* c = &g->cfg;
    uint32_t t = e->t;
    memset(&a, 0, sizeof(a));
    a.co = GK_SPI;
    a.moc = c->moc;
    a.ft4 = c->ft4;
    a.czest_hz = FT8_DIAL[c->pasmo < N_PASM ? c->pasmo : 5];
    g->env = *e;

    /* sprawy zależne od czasu */
    if (c->tx_wyl && c->tx_wlacz_o && t >= c->tx_wlacz_o)
    {
        c->tx_wyl = 0;
        c->tx_wlacz_o = 0;
        zapisz_cfg(g);
    }
    if (c->cisza_do && t >= c->cisza_do)
    {
        c->cisza_do = 0;
        zapisz_cfg(g);
    }
    if (g->jest_otwarty && t >= g->otwarty.czas + 600)
        log_zamknij(g);
    if (t < g->wspr_do || !e->gps_ok)
        return a; /* trwa WSPR albo nie ma pozycji – bez pozycji nie znamy Słońca ani strefy */

    /* energia: 0 = nic, 1 = tylko WSPR, 2 = pełna praca */
    float u = e->u_v / 0.05f;
    g->slonce = gk_slonce(t, e->szer, e->dlug);
    if (u < c->u_wspr || g->slonce < c->slonce_wspr)
        g->poziom = 0;
    else if (u < c->u_pelny || g->slonce < c->slonce_pelny)
        g->poziom = 1;
    else
        g->poziom = 2;
    g->w_strefie = gk_strefa_ciszy(g, e->szer, e->dlug);
    bool wolno_nadawac = g->poziom >= 1 && !g->w_strefie && c->cisza_do == 0;

    /* WSPR co 10 minut w minucie kanału */
    uint32_t wspr_hz;
    uint8_t minuta;
    gk_wspr_kanal(c->pasmo, c->kanal, &wspr_hz, &minuta);
    if (wolno_nadawac && !(c->tx_wyl & 2) && t % 600 == (uint32_t)minuta * 60)
    {
        char lok[7];
        a.co = GK_NADAJ_WSPR;
        a.czest_hz = wspr_hz;
        strcpy(a.wspr_znak, c->znak_wspr);
        lokator_teraz(g, lok);
        memcpy(a.wspr_lok, lok, 4);
        a.wspr_lok[4] = 0;
        a.wspr_dbm = 10;
        snprintf(a.opis, sizeof(a.opis), "WSPR %s %s", a.wspr_znak, a.wspr_lok);
        g->wspr_do = t + 120;
        g->qso.stan = Q_BRAK;
        return a;
    }
    if (g->poziom < 2)
        return a;

    uint32_t okno = t / 15, poz = okno % 4, parz = okno % 2;
    bool ft8 = wolno_nadawac && !(c->tx_wyl & 1) && c->tryb != GK_TRYB_WSPR;
    if (!ft8)
    {
        /* nie nadajemy FT8 (wyłączone, cisza, strefa, tryb „sam WSPR”) – raz na minutę słuchamy komend z domu */
        a.co = (poz == 1) ? GK_ODBIOR : GK_SPI;
        return a;
    }
    bool pelny = c->tryb == GK_TRYB_PELNY || g->qso.stan != Q_BRAK; /* zaczęta łączność idzie pełnym rytmem */
    if (pelny)
    {
        if (parz == 1)
            a.co = GK_ODBIOR;
        else
            wybierz_nadawanie(g, &a);
        return a;
    }
    bool czynna_minuta = c->tryb == GK_TRYB_SREDNI || (t / 60) % 2 == 0;
    if (czynna_minuta && poz == 0)
        wybierz_nadawanie(g, &a);
    else if (czynna_minuta && poz == 1)
        a.co = GK_ODBIOR;
    return a;
}

/* ====================================================================== start */
void gk_cfg_domyslna(gk_cfg* c)
{
    memset(c, 0, sizeof(*c));
    c->magia = GK_MAGIA;
    strcpy(c->znak_ft8, "QQ0Q");
    strcpy(c->znak_wspr, "QQ0QQQ");
    c->pasmo = 5; /* 20 m */
    c->kanal = 0;
    c->tryb = GK_TRYB_PELNY;
    c->cq_hz = 1500;
    c->log_hz = 2600;
    c->moc = 3;
    c->u_pelny = 60;  /* 3,00 V */
    c->u_wspr = 54;   /* 2,70 V */
    c->slonce_pelny = 17;
    c->slonce_wspr = 8;
    c->regula = 1;
}

void gk_start(gk_t* g, const gk_cfg* cfg, const gk_plat* plat)
{
    memset(g, 0, sizeof(*g));
    if (cfg && cfg->magia == GK_MAGIA)
        g->cfg = *cfg;
    else
        gk_cfg_domyslna(&g->cfg);
    if (plat)
        g->plat = *plat;
    g->snr_dom = 127;
    /* nasze znaki do tablicy skrótów (ramki ze znakiem w nawiasach <>) */
    ftx_message_t m;
    char txt[32];
    ftx_message_init(&m);
    snprintf(txt, sizeof(txt), "CQ %s", g->cfg.znak_ft8);
    ftx_message_encode(&m, &hash_if, txt);
}

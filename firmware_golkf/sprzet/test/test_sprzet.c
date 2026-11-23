/* GOLkf / R20 – testy na PC części warstwy sprzętowej, które nie dotykają sprzętu:
   dzielniki Si5351, koder WSPR, tor odbiorczy I/Q -> dźwięk -> dekoder FT8.  Uruchamianie: ./test.sh */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ft8/constants.h>
#include <ft8/encode.h>
#include "../dekoder.h"
#include "../dsp.h"
#include "../si_licz.h"
#include "../wspr.h"

static int bledy;
#define SPR(w, ...) do { if (!(w)) { bledy++; printf("  BLAD: " __VA_ARGS__); printf("\n"); } } while (0)

/* ---------- 1. Si5351 ---------- */
static double z_rej(uint32_t fx, const uint8_t* r, uint32_t D)
{
    uint32_t p3 = ((uint32_t)(r[5] & 0xF0) << 12) | ((uint32_t)r[0] << 8) | r[1];
    uint32_t p1 = ((uint32_t)(r[2] & 3) << 16) | ((uint32_t)r[3] << 8) | r[4];
    uint32_t p2 = ((uint32_t)(r[5] & 0x0F) << 16) | ((uint32_t)r[6] << 8) | r[7];
    /* odwrotność wzorów AN619: a + b/c = (P1 + 512 + P2/P3) / 128 */
    double mnoz = ((double)p1 + 512.0 + (double)p2 / p3) / 128.0;
    return fx * mnoz / D;
}

static void test_si(void)
{
    printf("1. dzielniki Si5351\n");
    static const struct { double f, krok; int ton; uint32_t wiel; const char* co; } T[] = {
        { 14074000 + 1500, 6.25, 8, 2, "FT8 20 m" }, { 14074000 + 2600, 6.25, 8, 2, "FT8 20 m, ramki danych" },
        { 14097100 - 2.2, 12000.0 / 8192, 4, 2, "WSPR 20 m" }, { 28074000 + 1500, 6.25, 8, 2, "FT8 10 m" },
        { 7074000 + 1500, 6.25, 8, 2, "FT8 40 m" }, { 10138700 + 1500, 12000.0 / 8192, 4, 2, "WSPR 30 m" },
        { 50313000 + 1500, 6.25, 8, 2, "FT8 6 m" }, { 5357000 + 1500, 6.25, 8, 2, "FT8 60 m" },
        { 14074000, 0, 1, 4, "heterodyna 20 m" }, { 28074000, 0, 1, 4, "heterodyna 10 m" }, { 7074000, 0, 1, 4, "heterodyna 40 m" },
    };
    for (unsigned i = 0; i < sizeof(T) / sizeof(T[0]); i++)
        for (uint32_t fx = 25999900; fx <= 26000100; fx += 100) /* także TCXO odstrojony o +-4 ppm */
        {
            si_plan p;
            bool ok = si_plan_licz(fx, T[i].f, T[i].krok, T[i].wiel, &p);
            SPR(ok, "%s: brak planu", T[i].co);
            if (!ok)
                continue;
            double vco = fx * (p.a + (double)p.b / p.c);
            SPR(vco >= 600e6 && vco <= 900e6, "%s: petla %.1f MHz poza 600-900", T[i].co, vco / 1e6);
            SPR(p.D % T[i].wiel == 0 && p.D >= 6 && p.D <= 126, "%s: dzielnik %u", T[i].co, p.D);
            SPR(p.c >= 1 && p.c <= 1048575 && p.b < p.c, "%s: ulamek %u/%u", T[i].co, p.b, p.c);
            double blad0 = 0, bladk = 0;
            for (int k = 0; k < T[i].ton; k++)
            {
                uint8_t r[8];
                si_plan_rej_pll(&p, k, r);
                double f = z_rej(fx, r, p.D), cel = T[i].f + k * T[i].krok;
                if (k == 0)
                    blad0 = f - cel;
                if (fabs((f - cel) - blad0) > bladk)
                    bladk = fabs((f - cel) - blad0);
                SPR(fabs(f - si_plan_hz(&p, k)) < 0.01, "%s: rejestry daja %.3f, wzor %.3f", T[i].co, f, si_plan_hz(&p, k));
            }
            /* częstotliwość tonu 0 trafia w siatkę o kroku (odstęp tonów / przyrost): błąd najwyżej pół kroku */
            double dop = T[i].krok > 0 ? T[i].krok / p.m / 2 + 0.02 : 0.5;
            SPR(fabs(blad0) <= dop, "%s: blad czestotliwosci %.3f Hz (dopuszczalne %.2f)", T[i].co, blad0, dop);
            SPR(bladk < 0.01, "%s: blad odstepu tonow %.4f Hz", T[i].co, bladk);
            if (fx == 26000000)
                printf("  %-24s D=%3u petla %.1f MHz, c=%7u, przyrost %2u, blad %+.2f Hz, odstep +-%.4f Hz\n", T[i].co, p.D, vco / 1e6, p.c, p.m, blad0, bladk);
        }
    si_plan p;
    SPR(!si_plan_licz(26000000, 3573000, 6.25, 2, &p), "80 m powinno byc odrzucone (dzielnik > 126)");
    uint8_t r[8];
    si_rej_wyj(52, r);
    SPR(r[0] == 0 && r[1] == 1 && ((r[2] & 3) << 16 | r[3] << 8 | r[4]) == 128 * 52 - 512 && !r[5] && !r[6] && !r[7], "rejestry dzielnika wyjsciowego");
}

/* ---------- pomocnicze: szum, zapis WAV ---------- */
static double gauss(void)
{
    double u1 = (rand() + 1.0) / (RAND_MAX + 2.0), u2 = (rand() + 1.0) / (RAND_MAX + 2.0);
    return sqrt(-2 * log(u1)) * cos(2 * M_PI * u2);
}

static void wav(const char* nazwa, const float* x, int n, float skala)
{
    FILE* f = fopen(nazwa, "wb");
    if (!f)
        return;
    uint32_t dl = (uint32_t)n * 2, u;
    uint16_t h;
    fwrite("RIFF", 1, 4, f); u = 36 + dl; fwrite(&u, 4, 1, f); fwrite("WAVEfmt ", 1, 8, f);
    u = 16; fwrite(&u, 4, 1, f); h = 1; fwrite(&h, 2, 1, f); fwrite(&h, 2, 1, f);
    u = 12000; fwrite(&u, 4, 1, f); u = 24000; fwrite(&u, 4, 1, f); h = 2; fwrite(&h, 2, 1, f); h = 16; fwrite(&h, 2, 1, f);
    fwrite("data", 1, 4, f); fwrite(&dl, 4, 1, f);
    for (int i = 0; i < n; i++)
    {
        float v = x[i] * skala;
        int16_t s = (int16_t)(v > 32000 ? 32000 : (v < -32000 ? -32000 : v));
        fwrite(&s, 2, 1, f);
    }
    fclose(f);
}

/* ---------- 2. tor odbiorczy ---------- */
#define N_PAR (48000 * 15)
static uint16_t pary[2 * N_PAR];
static float dzw[12000 * 15 + 64];
static double faza_i[N_PAR], faza_q[N_PAR]; /* robocze */

/* dodaje do bufora sygnał FT8: odstrojenie df (ujemne = druga wstęga), amplituda w kodach przetwornika.
   Umowa: I = A cos(fi), Q = -A sin(fi)  (heterodyna Q opóźniona o 90 st.) */
static double syg_i[N_PAR], syg_q[N_PAR];
static void dodaj_ft8(const char* tekst, double df, double amp, double start_s)
{
    extern bool gk_tekst_na_payload(const char* tekst, uint8_t* payload10);
    uint8_t pl[10], tony[FT8_NN];
    if (!gk_tekst_na_payload(tekst, pl))
    {
        SPR(0, "nie da sie zlozyc '%s'", tekst);
        return;
    }
    ft8_encode(pl, tony);
    double fi = 0, znak = df < 0 ? -1 : 1, f0 = fabs(df);
    for (int i = 0; i < 2 * N_PAR; i++) /* krok 1/96000 s: parzyste = chwila próbki I, nieparzyste = Q */
    {
        double t = i / 96000.0 - start_s;
        int s = (int)floor(t / 0.16);
        if (s < 0 || s >= FT8_NN)
            continue;
        fi += 2 * M_PI * znak * (f0 + 6.25 * tony[s]) / 96000.0;
        if (i & 1)
            syg_q[i / 2] += -amp * sin(fi);
        else
            syg_i[i / 2] += amp * cos(fi);
    }
}

static int odbierz(int bok, gk_dekod* d, float* sr_dt, const char* plik)
{
    static dsp_t dsp;
    dsp_start(&dsp, bok);
    dek_reset();
    int n = 0;
    for (int i = 0; i < N_PAR; i += 64)
        n += dsp_dodaj(&dsp, pary + 2 * i, 64, dzw + n);
    for (int p = 0; p + DEK_BLOK <= n; p += DEK_BLOK)
        dek_blok(dzw + p);
    if (plik)
        wav(plik, dzw, n, 20000.0f);
    int kand;
    return dek_dekoduj(d, 20, 70, NULL, sr_dt, &kand);
}

static bool jest(const gk_dekod* d, int n, const char* tekst, int* snr, int* hz)
{
    extern bool gk_tekst_na_payload(const char* tekst, uint8_t* payload10);
    uint8_t pl[10];
    gk_tekst_na_payload(tekst, pl);
    for (int i = 0; i < n; i++)
        if (!memcmp(d[i].payload, pl, 10))
        {
            if (snr) *snr = d[i].snr;
            if (hz) *hz = d[i].hz;
            return true;
        }
    return false;
}

static void test_odbior(void)
{
    printf("2. tor odbiorczy: I/Q z przetwornika -> wybor wstegi -> dekoder FT8\n");
    SPR(dek_init(), "dekoder: brak pamieci");
    /* a) tłumienie drugiej wstęgi tonem */
    static dsp_t dsp;
    printf("  tlumienie drugiej wstegi [dB]:");
    for (int f = 300; f <= 3000; f += 450)
    {
        double moc[2];
        for (int strona = 0; strona < 2; strona++)
        {
            dsp_start(&dsp, 1);
            double zn = strona ? -1 : 1, s2 = 0;
            int n = 0, m = 0;
            for (int i = 0; i < 48000; i++)
            {
                uint16_t pr[2];
                pr[0] = (uint16_t)lrint(2048 + 800 * cos(2 * M_PI * zn * f * (2 * i) / 96000.0));
                pr[1] = (uint16_t)lrint(2048 - 800 * sin(2 * M_PI * zn * f * (2 * i + 1) / 96000.0));
                float w[4];
                int k = dsp_dodaj(&dsp, pr, 1, w);
                for (int j = 0; j < k; j++, n++)
                    if (n > 6000) { s2 += (double)w[j] * w[j]; m++; }
            }
            moc[strona] = s2 / m;
        }
        double tl = 10 * log10(moc[0] / moc[1]);
        printf(" %d Hz: %.0f", f, tl);
        SPR(tl > 30, "tlumienie drugiej wstegi przy %d Hz tylko %.1f dB", f, tl);
    }
    printf("\n");
    /* b) dwie stacje: jedna we właściwej wstędze (1500 Hz), druga w lustrzanej (-1000 Hz, 10 dB silniejsza), szum */
    srand(7);
    memset(syg_i, 0, sizeof(syg_i));
    memset(syg_q, 0, sizeof(syg_q));
    dodaj_ft8("CQ SP9ABC KO00", 1500, 12, 0.5);
    dodaj_ft8("CQ DL1XYZ JO31", -1000, 38, 0.7);
    dodaj_ft8("SP1A OK1AAA -07", 2200, 5, 0.3);
    for (int i = 0; i < N_PAR; i++)
    {
        double vi = 2048 + 15 + syg_i[i] + 40 * gauss(), vq = 2048 - 22 + syg_q[i] + 40 * gauss();
        pary[2 * i] = (uint16_t)(vi < 0 ? 0 : (vi > 4095 ? 4095 : lrint(vi)));
        pary[2 * i + 1] = (uint16_t)(vq < 0 ? 0 : (vq > 4095 ? 4095 : lrint(vq)));
    }
    gk_dekod d[20];
    float dt;
    int snr = 0, hz = 0;
    int n = odbierz(1, d, &dt, "/tmp/golkf_odbior.wav");
    printf("  wstega +1: dekodow %d, srednie dt %+.2f s\n", n, dt);
    SPR(jest(d, n, "CQ SP9ABC KO00", &snr, &hz), "brak 'CQ SP9ABC KO00' we wlasciwej wstedze");
    printf("    CQ SP9ABC KO00: %+d dB, %d Hz\n", snr, hz);
    SPR(abs(hz - 1500) <= 4, "czestotliwosc %d zamiast 1500", hz);
    SPR(jest(d, n, "SP1A OK1AAA -07", &snr, &hz), "brak slabszej stacji 'SP1A OK1AAA -07'");
    printf("    SP1A OK1AAA -07: %+d dB, %d Hz\n", snr, hz);
    SPR(!jest(d, n, "CQ DL1XYZ JO31", NULL, NULL), "stacja z drugiej wstegi przeszla przez wybor wstegi");
    n = odbierz(-1, d, &dt, NULL);
    printf("  wstega -1: dekodow %d\n", n);
    SPR(jest(d, n, "CQ DL1XYZ JO31", &snr, &hz), "po zamianie wstegi powinna byc slyszana stacja lustrzana");
    SPR(abs(hz - 1000) <= 4, "czestotliwosc %d zamiast 1000", hz);
    SPR(!jest(d, n, "CQ SP9ABC KO00", NULL, NULL), "po zamianie wstegi wlasciwa stacja powinna zniknac");
    (void)faza_i;
    (void)faza_q;
}

/* ---------- 3. WSPR ---------- */
static void test_wspr(void)
{
    printf("3. koder WSPR\n");
    uint8_t s[WSPR_SYMBOLI];
    SPR(wspr_koduj("SP9ABC", "KO00", 10, s), "SP9ABC KO00 10");
    SPR(!wspr_koduj("SP9ABCX", "KO00", 10, s), "za dlugi znak powinien byc odrzucony");
    SPR(!wspr_koduj("SP9ABC", "ZZ00", 10, s), "zly lokator powinien byc odrzucony");
    static const struct { const char* z; const char* l; int p; } T[] = { { "SP9ABC", "KO00", 10 }, { "K1ABC", "FN42", 37 }, { "G4JNT", "IO90", 20 }, { "SP5XYZ", "JO90", 13 } };
    static float x[12000 * 120];
    for (unsigned k = 0; k < sizeof(T) / sizeof(T[0]); k++)
    {
        SPR(wspr_koduj(T[k].z, T[k].l, T[k].p, s), "%s %s %d", T[k].z, T[k].l, T[k].p);
        double fi = 0;
        srand(3 + k);
        for (int i = 0; i < 12000 * 120; i++)
        {
            double t = i / 12000.0 - 1.0;
            int n = (int)floor(t * 12000.0 / 8192.0);
            double v = 0.3 * gauss();
            if (n >= 0 && n < WSPR_SYMBOLI)
            {
                fi += 2 * M_PI * (1500.0 + (s[n] - 1.5) * 12000.0 / 8192.0) / 12000.0;
                v += 0.1 * sin(fi);
            }
            x[i] = (float)v;
        }
        char nazwa[64];
        snprintf(nazwa, sizeof(nazwa), "/tmp/golkf_wspr_%u.wav", k);
        wav(nazwa, x, 12000 * 120, 8000.0f);
        printf("  %s %s %d dBm -> %s (do sprawdzenia programem wsprd)\n", T[k].z, T[k].l, T[k].p, nazwa);
    }
}

int main(void)
{
    test_si();
    test_odbior();
    test_wspr();
    printf(bledy ? "\nBLEDOW: %d\n" : "\nwszystko dobrze (czesc bez sprzetu)\n", bledy);
    return bledy ? 1 : 0;
}

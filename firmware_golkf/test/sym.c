/* Symulator GOLkf na PC: cienka warstwa do wołania rdzenia z Pythona (ctypes) – patrz test_golkf.py. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../rdzen/golkf.h"

static int zapisow_cfg, zapisow_wpisow;
static gk_cfg ost_cfg;
static void z_cfg(const gk_cfg* c) { ost_cfg = *c; ++zapisow_cfg; }
static void z_wpis(uint32_t nr, const gk_wpis* w) { (void)nr; (void)w; ++zapisow_wpisow; }

gk_t* s_nowy(const uint8_t* klucz16)
{
    gk_t* g = (gk_t*)malloc(sizeof(gk_t));
    gk_cfg c;
    gk_plat p = { z_cfg, z_wpis };
    gk_cfg_domyslna(&c);
    if (klucz16)
    {
        memcpy(c.klucz, klucz16, 16);
        c.jest_klucz = 1;
    }
    gk_start(g, &c, &p);
    return g;
}

/* ponowny start z zapisaną konfiguracją i wpisami (jak po zaniku zasilania) */
gk_t* s_restart(gk_t* stary)
{
    gk_t* g = (gk_t*)malloc(sizeof(gk_t));
    gk_plat p = { z_cfg, z_wpis };
    gk_start(g, &stary->cfg, &p);
    for (uint32_t i = 0; i < stary->n_wpisow; ++i)
        gk_wczytaj_wpis(g, &stary->wpis[i]);
    return g;
}

void s_zwolnij(gk_t* g) { free(g); }

int s_okno(gk_t* g, uint32_t t, int gps, float szer, float dlug, float u, int temp, uint8_t* payload, int* hz, uint32_t* czest, char* opis)
{
    gk_env e = { t, (uint8_t)gps, szer, dlug, 13000, u, (int8_t)temp };
    gk_akcja a = gk_okno(g, &e);
    memcpy(payload, a.payload, 10);
    *hz = a.hz;
    *czest = a.czest_hz;
    strcpy(opis, a.opis);
    return a.co;
}

void s_odebrano(gk_t* g, uint32_t t, const uint8_t* payloady, const int8_t* snr, int n)
{
    gk_dekod d[64];
    if (n > 64)
        n = 64;
    for (int i = 0; i < n; ++i)
    {
        memcpy(d[i].payload, payloady + 10 * i, 10);
        d[i].snr = snr[i];
        d[i].hz = 1500;
    }
    gk_odebrano(g, t, d, n);
}

long s_liczba(gk_t* g, const char* co)
{
    const gk_cfg* c = &g->cfg;
#define P(n, v) if (strcmp(co, n) == 0) return (long)(v)
    P("wpisy", g->n_wpisow); P("qso", g->n_qso); P("potw_do", c->potw_do); P("otwarty", g->jest_otwarty);
    P("tryb", c->tryb); P("cisza_do", c->cisza_do); P("ft4", c->ft4); P("cq_hz", c->cq_hz); P("log_hz", c->log_hz);
    P("moc", c->moc); P("u_pelny", c->u_pelny); P("u_wspr", c->u_wspr); P("slonce_pelny", c->slonce_pelny);
    P("slonce_wspr", c->slonce_wspr); P("regula", c->regula); P("pasmo", c->pasmo); P("kanal", c->kanal);
    P("staly_lok", c->staly_lok); P("tx_wyl", c->tx_wyl); P("tx_wlacz_o", c->tx_wlacz_o); P("ost_kom", c->ost_kom);
    P("poziom", g->poziom); P("w_strefie", g->w_strefie); P("qso_stan", g->qso.stan); P("zapisow_cfg", zapisow_cfg);
    P("zapisow_wpisow", zapisow_wpisow); P("czarna0", c->czarna[0]);
    P("strefa0", c->strefa[0].czynna * 1000000L + (c->strefa[0].szer1 + 90) * 10000L + (c->strefa[0].szer2 + 90) * 100L);
    P("strefa0_dlug", (c->strefa[0].dlug1 + 180) * 1000L + (c->strefa[0].dlug2 + 180));
    P("rozmiar_stanu", sizeof(gk_t)); P("rozmiar_cfg", sizeof(gk_cfg));
#undef P
    return -999999;
}

const char* s_tekst(gk_t* g, const char* co)
{
    if (strcmp(co, "znak_ft8") == 0) return g->cfg.znak_ft8;
    if (strcmp(co, "znak_wspr") == 0) return g->cfg.znak_wspr;
    if (strcmp(co, "lokator") == 0) return g->cfg.lokator;
    if (strcmp(co, "qso_znak") == 0) return g->qso.znak;
    return "?";
}

float s_slonce(uint32_t t, float szer, float dlug) { return gk_slonce(t, szer, dlug); }
int s_strefa(gk_t* g, float szer, float dlug) { return gk_strefa_ciszy(g, szer, dlug); }
void s_lokator(float szer, float dlug, char* lok) { gk_lokator(szer, dlug, lok); }
uint32_t s_pakuj_znak(const char* z) { return gk_pakuj_znak(z); }
void s_wspr(int pasmo, int kanal, uint32_t* hz, uint8_t* minuta) { gk_wspr_kanal((uint8_t)pasmo, (uint16_t)kanal, hz, minuta); }

/* podgląd wpisu logu: co = 0 flagi, 1 ile razy nadano, 2 czas, 3 znak1 (28 b), 4 znak2 */
long s_wpis(gk_t* g, uint32_t nr, int co)
{
    if (nr < 1 || nr > g->n_wpisow)
        return -1;
    const gk_wpis* w = &g->wpis[nr - 1];
    return co == 0 ? w->flagi : co == 1 ? w->nadano : co == 2 ? (long)w->czas : co == 3 ? (long)w->z1 : (long)w->z2;
}

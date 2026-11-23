/* GOLkf / R20 – zapis trwały w pamięci flash (ostatnie 40 kB z 2 MB).
 *   LOG : 8 sektorów (32 kB) – wpis nr N w komórce N-1 (16 bajtów), zapisywany raz przy zamknięciu wpisu.
 *   CFG : 2 sektory (8 kB)   – dziennik rekordów po 256 bajtów (konfiguracja rdzenia i ustawienia sprzętowe);
 *         ważny jest rekord danego typu z najwyższym numerem; gdy brakuje miejsca, kasowany jest sektor bez najnowszych rekordów.
 */
#include "sprzet.h"
#include <string.h>
#include "hardware/flash.h"
#include "hardware/sync.h"
#include "pico/stdlib.h"

#define SEKTOR FLASH_SECTOR_SIZE /* 4096 */
#define STRONA FLASH_PAGE_SIZE   /* 256 */
#define CFG_SEKT 2
#define LOG_SEKT 8
#define CFG_OFF (PICO_FLASH_SIZE_BYTES - CFG_SEKT * SEKTOR)
#define LOG_OFF (CFG_OFF - LOG_SEKT * SEKTOR)
#define CFG_STRON (CFG_SEKT * SEKTOR / STRONA)
#define REK_MAGIA 0x474B5245u

_Static_assert(sizeof(gk_wpis) == 16, "komorka logu ma 16 bajtow");
_Static_assert(GK_MAX_WPISOW * 16 <= LOG_SEKT * SEKTOR, "log sie miesci");
_Static_assert(sizeof(gk_cfg) <= STRONA - 20, "konfiguracja miesci sie w rekordzie");

typedef struct
{
    uint32_t magia, nr, suma;
    uint16_t typ, dl;
    uint8_t dane[STRONA - 16];
} rekord;
_Static_assert(sizeof(rekord) == STRONA, "rekord = strona");

static const uint8_t* adr(uint32_t off) { return (const uint8_t*)(XIP_BASE + off); }

static uint32_t suma(const uint8_t* d, int n)
{
    uint32_t s = 0x811C9DC5u; /* FNV-1a */
    for (int i = 0; i < n; i++)
        s = (s ^ d[i]) * 16777619u;
    return s;
}

static void kasuj(uint32_t off, uint32_t ile)
{
    nadzor();
    uint32_t st = save_and_disable_interrupts();
    flash_range_erase(off, ile);
    restore_interrupts(st);
    nadzor();
}

static void programuj(uint32_t off, const uint8_t* d, uint32_t ile)
{
    uint32_t st = save_and_disable_interrupts();
    flash_range_program(off, d, ile);
    restore_interrupts(st);
}

static bool rek_wazny(const rekord* r)
{
    return r->magia == REK_MAGIA && r->dl <= sizeof(r->dane) && r->suma == suma(r->dane, r->dl);
}

static bool strona_pusta(int i)
{
    const uint8_t* p = adr(CFG_OFF + (uint32_t)i * STRONA);
    for (int k = 0; k < STRONA; k++)
        if (p[k] != 0xFF)
            return false;
    return true;
}

static const rekord* najnowszy(uint16_t typ, uint32_t* nr_max)
{
    const rekord* naj = NULL;
    uint32_t mx = 0;
    for (int i = 0; i < (int)CFG_STRON; i++)
    {
        const rekord* r = (const rekord*)adr(CFG_OFF + (uint32_t)i * STRONA);
        if (!rek_wazny(r))
            continue;
        if (r->nr > mx)
            mx = r->nr;
        if (r->typ == typ && (!naj || r->nr > naj->nr))
            naj = r;
    }
    if (nr_max)
        *nr_max = mx;
    return naj;
}

static void rek_zapisz(uint16_t typ, const void* dane, uint16_t dl)
{
    static rekord r; /* poza stosem; wyrównany */
    uint32_t mx;
    const rekord* stary = najnowszy(typ, &mx);
    if (stary && stary->dl == dl && !memcmp(stary->dane, dane, dl))
        return; /* bez zmian – nie zużywaj pamięci */
    int wolna = -1;
    for (int i = 0; i < (int)CFG_STRON && wolna < 0; i++)
        if (strona_pusta(i))
            wolna = i;
    if (wolna < 0)
    {
        /* brak miejsca: przepisz najnowsze rekordy obu typów do RAM, skasuj oba sektory po kolei tak,
           żeby w każdej chwili jeden komplet był w pamięci */
        static rekord kopia[2];
        int nk = 0;
        for (uint16_t t = 1; t <= 2; t++)
        {
            const rekord* x = najnowszy(t, NULL);
            if (x && t != typ)
                kopia[nk++] = *x;
        }
        /* sektor 0: skasuj i zapisz tam kopie + nowy rekord; potem skasuj sektor 1 */
        kasuj(CFG_OFF, SEKTOR);
        for (int i = 0; i < nk; i++)
        {
            kopia[i].nr = ++mx;
            programuj(CFG_OFF + (uint32_t)i * STRONA, (const uint8_t*)&kopia[i], STRONA);
        }
        wolna = nk;
        memset(&r, 0xFF, sizeof(r));
        r.magia = REK_MAGIA;
        r.nr = ++mx;
        r.typ = typ;
        r.dl = dl;
        memcpy(r.dane, dane, dl);
        r.suma = suma(r.dane, dl);
        programuj(CFG_OFF + (uint32_t)wolna * STRONA, (const uint8_t*)&r, STRONA);
        kasuj(CFG_OFF + SEKTOR, SEKTOR);
        return;
    }
    memset(&r, 0xFF, sizeof(r));
    r.magia = REK_MAGIA;
    r.nr = mx + 1;
    r.typ = typ;
    r.dl = dl;
    memcpy(r.dane, dane, dl);
    r.suma = suma(r.dane, dl);
    programuj(CFG_OFF + (uint32_t)wolna * STRONA, (const uint8_t*)&r, STRONA);
}

void pam_init(void) {}

bool pam_czytaj_cfg(gk_cfg* c)
{
    const rekord* r = najnowszy(1, NULL);
    if (!r || r->dl != sizeof(*c))
        return false;
    memcpy(c, r->dane, sizeof(*c));
    return c->magia == GK_MAGIA;
}
void pam_zapisz_cfg(const gk_cfg* c) { rek_zapisz(1, c, sizeof(*c)); }

bool pam_czytaj_hw(hw_cfg* h)
{
    const rekord* r = najnowszy(2, NULL);
    if (!r || r->dl != sizeof(*h))
        return false;
    memcpy(h, r->dane, sizeof(*h));
    return h->magia == HW_MAGIA;
}
void pam_zapisz_hw(const hw_cfg* h) { rek_zapisz(2, h, sizeof(*h)); }

static bool komorka_pusta(const uint8_t* p)
{
    for (int k = 0; k < 16; k++)
        if (p[k] != 0xFF)
            return false;
    return true;
}

uint32_t pam_czytaj_log(gk_t* gg)
{
    uint32_t n = 0;
    for (; n < GK_MAX_WPISOW; n++)
    {
        const uint8_t* p = adr(LOG_OFF + n * 16);
        if (komorka_pusta(p))
            break;
        gk_wpis w;
        memcpy(&w, p, sizeof(w));
        w.flagi = 0;
        w.nadano = 0;
        gk_wczytaj_wpis(gg, &w);
    }
    return n;
}

void pam_zapisz_wpis(uint32_t nr, const gk_wpis* w)
{
    if (nr < 1 || nr > GK_MAX_WPISOW)
        return;
    uint32_t off = LOG_OFF + (nr - 1) * 16;
    if (!komorka_pusta(adr(off)))
        return; /* komórka już zapisana (nie powinno się zdarzyć) */
    static uint8_t str[STRONA];
    memset(str, 0xFF, sizeof(str)); /* 0xFF nie zmienia sąsiednich komórek tej samej strony */
    memcpy(str + (off % STRONA), w, 16);
    programuj(off - (off % STRONA), str, STRONA);
}

void pam_kasuj_log(void) { kasuj(LOG_OFF, LOG_SEKT * SEKTOR); }
void pam_kasuj_wszystko(void)
{
    kasuj(LOG_OFF, LOG_SEKT * SEKTOR);
    kasuj(CFG_OFF, CFG_SEKT * SEKTOR);
}

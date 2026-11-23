/* GOLkf / R20 – konsola USB (port szeregowy): ustawienia i testy do uruchamiania płytki. Komenda „pomoc”. */
#include "sprzet.h"
#include <ctype.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "hardware/gpio.h"
#include "hardware/watchdog.h"
#include "pico/bootrom.h"
#include "pico/stdlib.h"

volatile bool kon_przerwij;
static char lin[96];
static int nlin;
static bool zajeta; /* trwa test wywołany z konsoli (albo okno pracy) – znaki tylko przerywają test */

static const char* const TRYBY[] = { "pelny", "sredni", "oszczedny", "sam WSPR", "cisza" };

static void czas_txt(char* b, size_t n)
{
    if (!czas_jest())
    {
        snprintf(b, n, "brak (czekam na GPS)");
        return;
    }
    uint32_t t = (uint32_t)(czas_us() / 1000000ull);
    snprintf(b, n, "%02u:%02u:%02u UTC", (unsigned)(t / 3600 % 24), (unsigned)(t / 60 % 60), (unsigned)(t % 60));
}

void kon_druk_stan(void)
{
    char b[40], lok[8];
    czas_txt(b, sizeof(b));
    printf("\nGOLkf rdzen %s, sprzet %s (plytka R20)\n", GK_WERSJA, GK_SPRZET_WERSJA);
    printf("  praca      : %s\n", hw.praca ? "SAMODZIELNA (nadaje sam)" : "STOL (sam nic nie nadaje; 'praca 1' wlacza)");
    printf("  czas       : %s\n", b);
    if (gps.t_poz_us)
    {
        gk_lokator(gps.szer, gps.dlug, lok);
        printf("  pozycja    : %.4f %.4f  %ld m  %s  (sat %u, %s, %lu s temu)\n", (double)gps.szer, (double)gps.dlug, (long)gps.wys_m, lok, gps.sat,
            gps.fix ? "wazna" : "stara", (unsigned long)((time_us_64() - gps.t_poz_us) / 1000000ull));
    }
    else
        printf("  pozycja    : brak (GPS %s, zdan %lu, bledow %lu)\n", gps_wlaczony() ? "wlaczony" : "wylaczony", (unsigned long)gps.zdan, (unsigned long)gps.bledow);
    printf("  panele     : %.2f V, procesor %.0f C\n", (double)adc_vsc(), (double)adc_temp());
    printf("  znaki      : FT8 %s, WSPR %s\n", g.cfg.znak_ft8, g.cfg.znak_wspr);
    printf("  pasmo      : %s, kanal WSPR %u, tryb %s, moc %u (0-3), FT8 %s, WSPR %s\n", gk_pasma[g.cfg.pasmo < 11 ? g.cfg.pasmo : 5], g.cfg.kanal,
        TRYBY[g.cfg.tryb < 5 ? g.cfg.tryb : 0], g.cfg.moc, (g.cfg.tx_wyl & 1) ? "wyl." : "wl.", (g.cfg.tx_wyl & 2) ? "wyl." : "wl.");
    printf("  progi      : FT8 od %.2f V i Slonca %u st., WSPR od %.2f V i %u st.\n", g.cfg.u_pelny * 0.05, g.cfg.slonce_pelny, g.cfg.u_wspr * 0.05, g.cfg.slonce_wspr);
    printf("  klucz      : %s\n", g.cfg.jest_klucz ? "wgrany" : "BRAK (tracker nie przyjmie zadnej komendy z domu)");
    printf("  log        : %lu wpisow, %lu lacznosci, potwierdzone do %lu\n", (unsigned long)g.n_wpisow, (unsigned long)g.n_qso, (unsigned long)g.cfg.potw_do);
    printf("  sprzet     : TCXO %lu Hz, GPS dt %d ms, wstega %+d, GPS %s (co %u s), kandydatow %u, bledy I2C %lu\n", (unsigned long)hw.tcxo_hz, hw.gps_dt_ms, hw.bok,
        hw.gps_stale ? "stale" : "okresowo", hw.gps_co_s, hw.kandydaci, (unsigned long)si_bledy);
    extern uint32_t stos_wolny(void);
    printf("  stos       : wolne %lu bajtow z 24576\n", (unsigned long)stos_wolny());
}

static void pomoc(void)
{
    printf("\nKomendy (Enter na koncu):\n"
           "  stan                    co wie tracker\n"
           "  test napiecia           napiecie paneli i temperatura\n"
           "  test gps [s]            pokazuj dane z GPS przez s sekund (domyslnie 20)\n"
           "  test si                 czy Si5351 odpowiada\n"
           "  test nosna <Hz> [s]     nosna na wyjsciu nadajnika (domyslnie 5 s) - NADAJE\n"
           "  test odbior [Hz]        15 s odbioru i dekodowania (domyslnie pasmo FT8 z ustawien)\n"
           "  test ft8                jedna ramka 'CQ <znak> <lokator>' od razu - NADAJE\n"
           "  test wspr               jedna ramka WSPR od razu (ok. 111 s) - NADAJE\n"
           "  praca 0|1               0 = stol, 1 = praca samodzielna (zapamietane)\n"
           "  klucz <32 znaki hex>    klucz komend z domu;  klucz usun\n"
           "  znak ft8|wspr <ZNAK>    znaki wywolawcze\n"
           "  pasmo <0-10>  kanal <0-599>  tryb <0-4>  moc <0-3>\n"
           "  tcxo <Hz>               rzeczywista czestotliwosc TCXO (kalibracja)\n"
           "  gpsdt <ms>              opoznienie danych GPS wzgledem sekundy\n"
           "  wstega 1|-1             wybor wstegi odbiornika\n"
           "  gps stale|okresowo      GPS zawsze wlaczony albo co 10 minut\n"
           "  log                     wpisy logu\n"
           "  kasuj log               usun caly log lacznosci (po probach na stole)\n"
           "  fabryczne               usun log i wszystkie ustawienia\n"
           "  restart                 uruchom ponownie\n"
           "  wgraj                   przejdz w tryb wgrywania (dysk USB)\n"
           "Dowolny klawisz przerywa trwajacy test.\n");
}

static void test_odbior(double hz)
{
    static gk_dekod d[40];
    odb_stat st;
    printf("odbior %.0f Hz: 3 s rozgrzewki, 13,4 s sluchania...\n", hz);
    gpio_put(PIN_RX_PWR, 1);
    for (int i = 0; i < 300 && !kon_przerwij; i++)
    {
        nadzor();
        kon_klawisz();
        sleep_ms(10);
    }
    uint64_t t0 = 0;
    if (czas_jest())
        t0 = (czas_us() / 15000000ull + 1) * 15000000ull; /* od początku najbliższego okna */
    if (t0)
        printf("czekam na poczatek okna...\n");
    int n = odb_okno(t0, hz, d, 40, &st);
    gpio_put(PIN_RX_PWR, 0);
    si_wylacz();
    printf("przetwornik: I %u..%u, Q %u..%u (zakres 0..4095, spoczynek ok. 2048)\n", st.min_i, st.max_i, st.min_q, st.max_q);
    printf("poziom: I %.1f, Q %.1f, zaleznosc I-Q %+.2f (blisko 0 = dobrze; blisko 1 lub -1 = tory I i Q niosa to samo)\n", (double)st.rms_i, (double)st.rms_q, (double)st.kor);
    printf("blokow %d, kandydatow %d, dekodowanie %u ms, dekodow %d", st.blokow, st.kandydatow, (unsigned)st.ms_dekod, n);
    if (n && t0)
        printf(", srednie dt %+.2f s", (double)st.sr_dt);
    printf("\n");
    for (int i = 0; i < n; i++)
    {
        printf("  %+3d dB %4u Hz  ", d[i].snr, d[i].hz);
        for (int k = 0; k < 10; k++)
            printf("%02X", d[i].payload[k]);
        printf("\n");
    }
    if (!t0)
        printf("(bez czasu GPS okno nie bylo zgrane z sekunda - dekodow moze nie byc)\n");
}

static void wykonaj(char* s)
{
    char* a[5] = { "", "", "", "", "" };
    int n = 0;
    for (char* p = strtok(s, " \t"); p && n < 5; p = strtok(NULL, " \t"))
        a[n++] = p;
    if (!n)
        return;
    for (char* p = a[0]; *p; p++)
        *p = (char)tolower((unsigned char)*p);
    if (!strcmp(a[0], "pomoc") || !strcmp(a[0], "?"))
        pomoc();
    else if (!strcmp(a[0], "stan"))
        kon_druk_stan();
    else if (!strcmp(a[0], "test") && !strcmp(a[1], "napiecia"))
        printf("panele %.3f V, procesor %.1f C\n", (double)adc_vsc(), (double)adc_temp());
    else if (!strcmp(a[0], "test") && !strcmp(a[1], "gps"))
    {
        int sek = n > 2 ? atoi(a[2]) : 20;
        gps_wlacz(true);
        gps_echo(true);
        for (int i = 0; i < sek * 100 && !kon_przerwij; i++)
        {
            nadzor();
            gps_krok();
            kon_klawisz();
            sleep_ms(10);
        }
        gps_echo(false);
        kon_druk_stan();
    }
    else if (!strcmp(a[0], "test") && !strcmp(a[1], "si"))
    {
        bool ok = si_wlacz();
        int st = si_status();
        printf("Si5351: %s, rejestr stanu 0x%02X%s\n", ok ? "odpowiada" : "NIE ODPOWIADA", st & 0xFF, st < 0 ? " (brak odczytu)" : "");
        if (ok && (st & 0x08))
            printf("  uwaga: brak sygnalu zegara na wejsciu (TCXO)\n");
        si_wylacz();
    }
    else if (!strcmp(a[0], "test") && !strcmp(a[1], "nosna") && n > 2)
    {
        double f = atof(a[2]);
        int sek = n > 3 ? atoi(a[3]) : 5;
        if (f < 1e6 || f > 60e6 || sek < 1 || sek > 60)
            printf("zakres: 1-60 MHz, 1-60 s\n");
        else
        {
            printf("nosna %.0f Hz przez %d s, moc %u...\n", f, sek, g.cfg.moc);
            printf(nadaj_nosna(f, g.cfg.moc, (uint32_t)sek * 1000) ? "koniec\n" : "BLAD: Si5351 nie odpowiada albo czestotliwosc poza zakresem\n");
            si_wylacz();
        }
    }
    else if (!strcmp(a[0], "test") && !strcmp(a[1], "odbior"))
    {
        double f = n > 2 ? atof(a[2]) : 0;
        test_odbior(f < 1e6 ? (double)gk_ft8_hz(g.cfg.pasmo) : f);
    }
    else if (!strcmp(a[0], "test") && (!strcmp(a[1], "ft8") || !strcmp(a[1], "wspr")))
    {
        if (!gps.t_poz_us && !g.cfg.staly_lok)
        {
            printf("brak pozycji GPS - nie znam lokatora\n");
            return;
        }
        gk_akcja x;
        memset(&x, 0, sizeof(x));
        char lok[8];
        if (g.cfg.staly_lok)
            strncpy(lok, g.cfg.lokator, 7);
        else
            gk_lokator(gps.szer, gps.dlug, lok);
        lok[4] = 0;
        x.moc = g.cfg.moc;
        uint64_t t0 = 0;
        if (!strcmp(a[1], "wspr"))
        {
            uint8_t minuta;
            gk_wspr_kanal(g.cfg.pasmo, g.cfg.kanal, &x.czest_hz, &minuta);
            strcpy(x.wspr_znak, g.cfg.znak_wspr);
            strcpy(x.wspr_lok, lok);
            x.wspr_dbm = 10;
            if (czas_jest())
                t0 = (czas_us() / 120000000ull + 1) * 120000000ull; /* najbliższa parzysta minuta */
            printf("WSPR %s %s 10 dBm na %lu Hz%s...\n", x.wspr_znak, x.wspr_lok, (unsigned long)x.czest_hz, t0 ? ", czekam na parzysta minute" : " (bez czasu GPS - nikt tego nie zdekoduje)");
            printf(nadaj_wspr(t0, &x) ? "koniec\n" : "BLAD\n");
        }
        else
        {
            char txt[40];
            snprintf(txt, sizeof(txt), "CQ %s %s", g.cfg.znak_ft8, lok);
            if (!gk_tekst_na_payload(txt, x.payload))
            {
                printf("nie umiem zlozyc ramki '%s'\n", txt);
                return;
            }
            x.czest_hz = gk_ft8_hz(g.cfg.pasmo);
            x.hz = g.cfg.cq_hz;
            if (czas_jest())
                t0 = (czas_us() / 15000000ull + 1) * 15000000ull;
            printf("FT8 'CQ %s %s' na %lu + %u Hz%s...\n", g.cfg.znak_ft8, lok, (unsigned long)x.czest_hz, x.hz, t0 ? "" : " (bez czasu GPS - nikt tego nie zdekoduje)");
            printf(nadaj_ft8(t0, &x) ? "koniec\n" : "BLAD: Si5351 nie odpowiada\n");
        }
        si_wylacz();
    }
    else if (!strcmp(a[0], "praca") && n > 1)
    {
        hw.praca = (uint8_t)(atoi(a[1]) ? 1 : 0);
        pam_zapisz_hw(&hw);
        printf("praca: %s\n", hw.praca ? "SAMODZIELNA - tracker nadaje sam, gdy ma czas GPS, pozycje i dosc napiecia" : "STOL");
    }
    else if (!strcmp(a[0], "klucz") && n > 1)
    {
        if (!strcmp(a[1], "usun"))
        {
            memset(g.cfg.klucz, 0, 16);
            g.cfg.jest_klucz = 0;
        }
        else
        {
            if (strlen(a[1]) != 32)
            {
                printf("klucz = dokladnie 32 znaki 0-9 a-f\n");
                return;
            }
            uint8_t k[16];
            for (int i = 0; i < 16; i++)
            {
                char h[3] = { a[1][2 * i], a[1][2 * i + 1], 0 };
                char* kon;
                k[i] = (uint8_t)strtoul(h, &kon, 16);
                if (*kon)
                {
                    printf("klucz = dokladnie 32 znaki 0-9 a-f\n");
                    return;
                }
            }
            memcpy(g.cfg.klucz, k, 16);
            g.cfg.jest_klucz = 1;
        }
        pam_zapisz_cfg(&g.cfg);
        printf("klucz %s\n", g.cfg.jest_klucz ? "wgrany" : "usuniety");
    }
    else if (!strcmp(a[0], "znak") && n > 2)
    {
        for (char* p = a[2]; *p; p++)
            *p = (char)toupper((unsigned char)*p);
        uint32_t n28 = gk_pakuj_znak(a[2]);
        if (strlen(a[2]) > 10 || n28 == 0 || n28 == 0xFFFFFFFFu)
        {
            printf("to nie jest zwykly znak wywolawczy\n");
            return;
        }
        if (!strcmp(a[1], "ft8"))
            strcpy(g.cfg.znak_ft8, a[2]);
        else if (!strcmp(a[1], "wspr"))
            strcpy(g.cfg.znak_wspr, a[2]);
        else
            return;
        pam_zapisz_cfg(&g.cfg);
        printf("znaki: FT8 %s, WSPR %s (pelne dzialanie po 'restart')\n", g.cfg.znak_ft8, g.cfg.znak_wspr);
    }
    else if ((!strcmp(a[0], "pasmo") || !strcmp(a[0], "kanal") || !strcmp(a[0], "tryb") || !strcmp(a[0], "moc")) && n > 1)
    {
        int v = atoi(a[1]);
        if (!strcmp(a[0], "pasmo") && v >= 0 && v <= 10)
            g.cfg.pasmo = (uint8_t)v;
        else if (!strcmp(a[0], "kanal") && v >= 0 && v <= 599)
            g.cfg.kanal = (uint16_t)v;
        else if (!strcmp(a[0], "tryb") && v >= 0 && v <= 4)
            g.cfg.tryb = (uint8_t)v;
        else if (!strcmp(a[0], "moc") && v >= 0 && v <= 3)
            g.cfg.moc = (uint8_t)v;
        else
        {
            printf("wartosc poza zakresem\n");
            return;
        }
        pam_zapisz_cfg(&g.cfg);
        kon_druk_stan();
    }
    else if (!strcmp(a[0], "tcxo") && n > 1)
    {
        uint32_t v = (uint32_t)strtoul(a[1], NULL, 10);
        if (v < 25990000 || v > 26010000)
            printf("zakres 25 990 000 - 26 010 000 Hz\n");
        else
        {
            hw.tcxo_hz = v;
            pam_zapisz_hw(&hw);
            printf("TCXO %lu Hz\n", (unsigned long)v);
        }
    }
    else if (!strcmp(a[0], "gpsdt") && n > 1)
    {
        hw.gps_dt_ms = (int16_t)atoi(a[1]);
        pam_zapisz_hw(&hw);
        printf("GPS dt %d ms\n", hw.gps_dt_ms);
    }
    else if (!strcmp(a[0], "wstega") && n > 1)
    {
        hw.bok = (int8_t)(atoi(a[1]) < 0 ? -1 : 1);
        pam_zapisz_hw(&hw);
        printf("wstega %+d\n", hw.bok);
    }
    else if (!strcmp(a[0], "gps") && n > 1)
    {
        hw.gps_stale = (uint8_t)(!strcmp(a[1], "stale"));
        pam_zapisz_hw(&hw);
        printf("GPS %s\n", hw.gps_stale ? "stale wlaczony" : "okresowo");
    }
    else if (!strcmp(a[0], "log"))
    {
        for (uint32_t i = 0; i < g.n_wpisow; i++)
        {
            char z1[12] = "?", z2[12] = "";
            gk_rozpakuj_znak(g.wpis[i].z1, z1);
            if (g.wpis[i].z2)
                gk_rozpakuj_znak(g.wpis[i].z2, z2);
            uint32_t t = g.wpis[i].czas;
            printf("%4lu  %02u:%02u  %-10s %-10s %s nadano %u\n", (unsigned long)i + 1, (unsigned)(t / 3600 % 24), (unsigned)(t / 60 % 60), z1, z2,
                (g.wpis[i].flagi & GK_W_POTW) ? "potw." : "     ", g.wpis[i].nadano);
            nadzor();
        }
        printf("razem %lu wpisow\n", (unsigned long)g.n_wpisow);
    }
    else if (!strcmp(a[0], "kasuj") && !strcmp(a[1], "log"))
    {
        pam_kasuj_log();
        g.cfg.potw_do = 0;
        pam_zapisz_cfg(&g.cfg);
        printf("log skasowany - restart...\n");
        sleep_ms(200);
        watchdog_reboot(0, 0, 10);
    }
    else if (!strcmp(a[0], "fabryczne"))
    {
        pam_kasuj_wszystko();
        printf("wszystko skasowane - restart...\n");
        sleep_ms(200);
        watchdog_reboot(0, 0, 10);
    }
    else if (!strcmp(a[0], "restart"))
        watchdog_reboot(0, 0, 10);
    else if (!strcmp(a[0], "wgraj"))
    {
        printf("tryb wgrywania: pojawi sie dysk RP2350, skopiuj na niego plik .uf2\n");
        sleep_ms(200);
        reset_usb_boot(0, 0);
    }
    else
        printf("nie znam komendy '%s' - napisz: pomoc\n", a[0]);
}

/* wołane w trakcie długich operacji: w czasie testu z konsoli dowolny klawisz go przerywa;
   w pracy samodzielnej znaki czekają w buforze do końca okna */
void kon_klawisz(void)
{
    if (zajeta && getchar_timeout_us(0) >= 0)
        kon_przerwij = true;
}

void kon_krok(void)
{
    for (;;)
    {
        int c = getchar_timeout_us(0);
        if (c < 0)
            return;
        if (c == '\r' || c == '\n')
        {
            if (!nlin)
                continue;
            lin[nlin] = 0;
            nlin = 0;
            printf("\n");
            zajeta = true;
            kon_przerwij = false;
            wykonaj(lin);
            zajeta = false;
            kon_przerwij = false;
            printf("> ");
        }
        else if ((c == 8 || c == 127) && nlin)
        {
            nlin--;
            printf("\b \b");
        }
        else if (c >= 32 && c < 127 && nlin < (int)sizeof(lin) - 1)
        {
            lin[nlin++] = (char)c;
            putchar(c);
        }
    }
}

/* GOLkf / R20 – GPS ATGM336H na UART1 (9600). Czas i pozycja ze zdań RMC / GGA.
 * Płytka nie ma linii PPS: początek sekundy bierzemy z chwili, w której GPS zaczyna wysyłać paczkę zdań
 * (pierwszy znak po przerwie), minus hw.gps_dt_ms. Dokładność rzędu kilkudziesięciu ms – dla FT8 i WSPR wystarcza.
 */
#include "sprzet.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "hardware/gpio.h"
#include "hardware/irq.h"
#include "hardware/sync.h"
#include "hardware/uart.h"
#include "pico/stdlib.h"

#define U uart1
gps_t gps;
static volatile uint8_t buf[512];
static volatile uint16_t wr, rd;
static volatile uint64_t t_ost_znak, t_paczka;
/* dla każdego '$' w buforze: gdzie leży i kiedy zaczęła się jego paczka (pętla główna bywa zajęta ponad sekundę) */
#define N_ZN 16
static volatile struct { uint16_t poz; uint64_t t; } zn[N_ZN];
static volatile uint8_t zn_wr;
static bool ustawiony; /* po włączeniu wysłano już wybór zdań */
static char lin[100];
static int nlin;
static bool echo, wlaczony;
static uint64_t t_paczki_linii; /* początek paczki, do której należy składana linia */

static void irq_uart(void)
{
    while (uart_is_readable(U))
    {
        uint8_t c = (uint8_t)uart_getc(U);
        uint64_t t = time_us_64();
        if (t - t_ost_znak > 150000) /* przerwa > 150 ms = nowa paczka (nowa sekunda) */
            t_paczka = t;
        t_ost_znak = t;
        uint16_t n = (uint16_t)((wr + 1) % sizeof(buf));
        if (n != rd)
        {
            if (c == '$')
            {
                zn[zn_wr].poz = wr;
                zn[zn_wr].t = t_paczka;
                zn_wr = (uint8_t)((zn_wr + 1) % N_ZN);
            }
            buf[wr] = c;
            wr = n;
        }
    }
}

static void wyslij(const char* tresc) /* tresc bez '$' i sumy */
{
    uint8_t s = 0;
    char t[80];
    for (const char* p = tresc; *p; p++)
        s ^= (uint8_t)*p;
    snprintf(t, sizeof(t), "$%s*%02X\r\n", tresc, s);
    uart_puts(U, t);
}

void gps_init(void)
{
    gpio_init(PIN_GPS_EN_N);
    gpio_put(PIN_GPS_EN_N, 1);
    gpio_set_dir(PIN_GPS_EN_N, GPIO_OUT);
    uart_init(U, 9600);
    gpio_set_function(PIN_GPS_RX, GPIO_FUNC_UART);
    gpio_set_function(PIN_GPS_TX, GPIO_FUNC_NULL); /* TX dopiero po włączeniu GPS (nie zasilać modułu przez pin) */
    uart_set_fifo_enabled(U, false);
    irq_set_exclusive_handler(UART1_IRQ, irq_uart);
    irq_set_enabled(UART1_IRQ, true);
    uart_set_irq_enables(U, true, false);
}

bool gps_wlaczony(void) { return wlaczony; }

void gps_wlacz(bool wl)
{
    if (wl == wlaczony)
        return;
    wlaczony = wl;
    if (wl)
    {
        gpio_put(PIN_GPS_EN_N, 0);
        gpio_set_function(PIN_GPS_TX, GPIO_FUNC_UART);
        ustawiony = false; /* wybór zdań wyślemy po pierwszym odebranym zdaniu (moduł już wtedy słucha) */
    }
    else
    {
        gpio_set_function(PIN_GPS_TX, GPIO_FUNC_NULL);
        gpio_put(PIN_GPS_EN_N, 1);
        gps.fix = false;
    }
}

void gps_echo(bool wl) { echo = wl; }

static int pola(char* s, char** p, int max)
{
    int n = 0;
    p[n++] = s;
    for (; *s && n < max; s++)
        if (*s == ',')
        {
            *s = 0;
            p[n++] = s + 1;
        }
    return n;
}

static bool wsp(const char* v, const char* pol, int stopni_cyfr, float* wynik)
{
    if (strlen(v) < (size_t)stopni_cyfr + 2 || !*pol)
        return false;
    int st = 0;
    for (int i = 0; i < stopni_cyfr; i++)
        st = st * 10 + (v[i] - '0');
    float x = (float)st + (float)atof(v + stopni_cyfr) / 60.0f;
    if (*pol == 'S' || *pol == 'W')
        x = -x;
    *wynik = x;
    return true;
}

static uint32_t unix_z_daty(int r, int m, int d, int h, int mi, int s)
{
    /* dni od 1970-01-01 (algorytm dni cywilnych) */
    r -= m <= 2;
    int era = r / 400, yoe = r - era * 400;
    int doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1;
    int doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    int32_t dni = era * 146097 + doe - 719468;
    return (uint32_t)dni * 86400u + (uint32_t)(h * 3600 + mi * 60 + s);
}

static void zdanie(char* s, uint64_t t_paczki)
{
    /* suma kontrolna */
    char* gw = strchr(s, '*');
    if (s[0] != '$' || !gw)
    {
        gps.bledow++;
        return;
    }
    uint8_t suma = 0;
    for (char* p = s + 1; p < gw; p++)
        suma ^= (uint8_t)*p;
    if ((uint8_t)strtoul(gw + 1, NULL, 16) != suma)
    {
        gps.bledow++;
        return;
    }
    *gw = 0;
    gps.zdan++;
    char* p[20];
    int n = pola(s, p, 20);
    if (n >= 10 && !strcmp(p[0] + 3, "RMC"))
    {
        bool wazne = p[2][0] == 'A';
        float sz, dl;
        if (wazne && wsp(p[3], p[4], 2, &sz) && wsp(p[5], p[6], 3, &dl))
        {
            gps.szer = sz;
            gps.dlug = dl;
            gps.fix = true;
            gps.t_poz_us = time_us_64();
        }
        else
            gps.fix = false;
        /* czas: ustawiamy tylko przy ważnej pozycji (wtedy czas GPS jest pewny) */
        if (wazne && strlen(p[1]) >= 6 && strlen(p[9]) == 6)
        {
            int h = (p[1][0] - '0') * 10 + p[1][1] - '0', mi = (p[1][2] - '0') * 10 + p[1][3] - '0', se = (p[1][4] - '0') * 10 + p[1][5] - '0';
            int d = (p[9][0] - '0') * 10 + p[9][1] - '0', m = (p[9][2] - '0') * 10 + p[9][3] - '0', r = 2000 + (p[9][4] - '0') * 10 + p[9][5] - '0';
            if (t_paczki && r >= 2026 && m >= 1 && m <= 12 && d >= 1 && d <= 31 && h < 24 && mi < 60 && se < 60)
            {
                uint64_t u = (uint64_t)unix_z_daty(r, m, d, h, mi, se) * 1000000ull;
                czas_ustaw(u, t_paczki - (int64_t)hw.gps_dt_ms * 1000);
                gps.t_czas_us = time_us_64();
            }
        }
    }
    else if (n >= 10 && !strcmp(p[0] + 3, "GGA"))
    {
        gps.sat = (uint8_t)atoi(p[7]);
        if (p[6][0] > '0' && *p[9])
            gps.wys_m = (int32_t)atof(p[9]);
    }
}

void gps_krok(void)
{
    while (rd != wr)
    {
        char c = (char)buf[rd];
        rd = (uint16_t)((rd + 1) % sizeof(buf));
        if (c == '$')
        {
            uint16_t tu = (uint16_t)((rd + sizeof(buf) - 1) % sizeof(buf));
            nlin = 0;
            t_paczki_linii = 0;
            uint32_t st = save_and_disable_interrupts();
            for (int i = 0; i < N_ZN; i++)
                if (zn[i].poz == tu && zn[i].t > t_paczki_linii)
                    t_paczki_linii = zn[i].t;
            restore_interrupts(st);
        }
        if (c == '\r' || c == '\n')
        {
            if (nlin > 6)
            {
                lin[nlin] = 0;
                if (echo)
                    printf("%s\n", lin);
                zdanie(lin, t_paczki_linii);
                if (!ustawiony && gps.zdan)
                {
                    wyslij("PCAS03,1,0,0,0,1,0,0,0,0,0,,,0,0"); /* tylko GGA i RMC: krótka paczka */
                    ustawiony = true;
                }
            }
            nlin = 0;
        }
        else if (nlin < (int)sizeof(lin) - 1)
            lin[nlin++] = c;
    }
}

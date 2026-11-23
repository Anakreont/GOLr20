/* GOLkf / R20 – odbiór: przetwornik A/C (I i Q na przemian, 48 kHz na kanał) przez DMA do bufora kołowego,
   filtr + wybór wstęgi (dsp.c), widmo i dekoder (dekoder.c). Także pomiar napięcia paneli i temperatury. */
#include "sprzet.h"
#include "dekoder.h"
#include "dsp.h"
#include <math.h>
#include "hardware/adc.h"
#include "hardware/dma.h"
#include "hardware/gpio.h"
#include "pico/stdlib.h"

#define BUF_BITY 14                       /* 16384 bajty = 8192 próbki = 4096 par = 85 ms */
#define BUF_PROBEK (1u << (BUF_BITY - 1))
static uint16_t bufor[BUF_PROBEK] __attribute__((aligned(1u << BUF_BITY)));
static int kanal_dma = -1;
static dsp_t dsp;
static float dzwiek[DEK_BLOK + 64];
static int n_dzw;
static uint64_t termin_us;

float adc_vsc(void)
{
    adc_set_round_robin(0);
    adc_select_input(2);
    uint32_t s = 0;
    for (int i = 0; i < 32; i++)
        s += adc_read();
    return (float)s / 32.0f * (3.3f / 4096.0f) * 2.0f; /* dzielnik 1 M / 1 M */
}

float adc_temp(void)
{
    adc_set_temp_sensor_enabled(true);
    adc_set_round_robin(0);
    adc_select_input(ADC_TEMPERATURE_CHANNEL_NUM);
    sleep_us(200);
    uint32_t s = 0;
    for (int i = 0; i < 16; i++)
        s += adc_read();
    adc_set_temp_sensor_enabled(false);
    float v = (float)s / 16.0f * (3.3f / 4096.0f);
    return 27.0f - (v - 0.706f) / 0.001721f;
}

bool odb_init(void)
{
    adc_init();
    adc_gpio_init(PIN_ADC_I);
    adc_gpio_init(PIN_ADC_Q);
    adc_gpio_init(PIN_ADC_VSC);
    gpio_init(PIN_RX_PWR);
    gpio_put(PIN_RX_PWR, 0);
    gpio_set_dir(PIN_RX_PWR, GPIO_OUT);
    gpio_set_drive_strength(PIN_RX_PWR, GPIO_DRIVE_STRENGTH_12MA);
    gpio_init(PIN_RX_OE_N);
    gpio_put(PIN_RX_OE_N, 1);
    gpio_set_dir(PIN_RX_OE_N, GPIO_OUT);
    kanal_dma = dma_claim_unused_channel(false);
    return kanal_dma >= 0 && dek_init();
}

static void start_adc(void)
{
    adc_run(false);
    adc_fifo_drain();
    adc_set_round_robin(0x03);
    adc_select_input(0);
    adc_fifo_setup(true, true, 1, false, false);
    adc_set_clkdiv(48000000.0f / (2.0f * DSP_FS_ADC) - 1.0f); /* 96 000 próbek/s łącznie */
    dma_channel_config c = dma_channel_get_default_config((uint)kanal_dma);
    channel_config_set_transfer_data_size(&c, DMA_SIZE_16);
    channel_config_set_read_increment(&c, false);
    channel_config_set_write_increment(&c, true);
    channel_config_set_ring(&c, true, BUF_BITY);
    channel_config_set_dreq(&c, DREQ_ADC);
    dma_channel_configure((uint)kanal_dma, &c, bufor, &adc_hw->fifo, 0x0FFFFFFFu, true);
    adc_run(true);
}

static void stop_adc(void)
{
    adc_run(false);
    dma_channel_abort((uint)kanal_dma);
    adc_fifo_drain();
    adc_fifo_setup(false, false, 1, false, false);
    adc_set_round_robin(0);
}

static bool czy_dalej(void)
{
    nadzor();
    return time_us_64() < termin_us;
}

int odb_okno(uint64_t t0_us, double dial_hz, gk_dekod* d, int max, odb_stat* st)
{
    odb_stat s0;
    if (!st)
        st = &s0;
    *st = (odb_stat){ 0 };
    if (kanal_dma < 0)
        return 0;
    /* zasilanie odbiornika (PIN_RX_PWR) włącza wcześniej pętla główna: kondensatory sprzęgające 1 uF z rezystorami 1 M
       ustalają się kilka sekund */
    gpio_put(PIN_RX_PWR, 1);
    gpio_put(PIN_RX_OE_N, 0);
    if (!si_rx_start(dial_hz))
    {
        gpio_put(PIN_RX_OE_N, 1);
        return 0;
    }
    dek_reset();
    dsp_start(&dsp, hw.bok);
    n_dzw = 0;
    if (t0_us)
        czekaj_do(t0_us);
    else
        t0_us = czas_us() ? czas_us() : 1;
    uint64_t z0 = time_us_64();
    start_adc();
    uint32_t czyt = 0; /* indeks próbki w buforze kołowym (parzysty = I) */
    while (time_us_64() - z0 < 13400000ull && !kon_przerwij)
    {
        uint32_t pis = (uint32_t)(((uintptr_t)dma_hw->ch[kanal_dma].write_addr - (uintptr_t)bufor) / 2) & (BUF_PROBEK - 1);
        uint32_t jest = (pis - czyt) & (BUF_PROBEK - 1);
        jest &= ~1u;
        if (jest < 64)
        {
            nadzor();
            gps_krok();
            kon_klawisz();
            sleep_us(500);
            continue;
        }
        while (jest)
        {
            uint32_t ile = jest;
            if (czyt + ile > BUF_PROBEK)
                ile = BUF_PROBEK - czyt;
            if (ile > 128)
                ile = 128; /* po 64 pary: najwyżej 16 próbek dźwięku naraz */
            n_dzw += dsp_dodaj(&dsp, bufor + czyt, (int)(ile / 2), dzwiek + n_dzw);
            czyt = (czyt + ile) & (BUF_PROBEK - 1);
            jest -= ile;
            if (n_dzw >= DEK_BLOK)
            {
                dek_blok(dzwiek);
                n_dzw -= DEK_BLOK;
                for (int i = 0; i < n_dzw; i++)
                    dzwiek[i] = dzwiek[DEK_BLOK + i];
            }
        }
    }
    stop_adc();
    si_rx_stop();
    gpio_put(PIN_RX_OE_N, 1);
    if (dsp.pom_n)
    {
        st->rms_i = sqrtf((float)(dsp.sum_i2 / dsp.pom_n));
        st->rms_q = sqrtf((float)(dsp.sum_q2 / dsp.pom_n));
        float m = st->rms_i * st->rms_q;
        st->kor = m > 0 ? (float)(dsp.sum_iq / dsp.pom_n) / m : 0;
    }
    st->min_i = dsp.min_i;
    st->max_i = dsp.max_i;
    st->min_q = dsp.min_q;
    st->max_q = dsp.max_q;
    st->blokow = dek_blokow();
    termin_us = z0 + 14600000ull;
    uint32_t tp = to_ms_since_boot(get_absolute_time());
    int n = dek_dekoduj(d, max, hw.kandydaci, czy_dalej, &st->sr_dt, &st->kandydatow);
    st->ms_dekod = to_ms_since_boot(get_absolute_time()) - tp;
    return n;
}

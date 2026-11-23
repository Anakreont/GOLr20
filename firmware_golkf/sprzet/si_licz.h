/* GOLkf / R20 – obliczenia dzielników Si5351 (bez sprzętu, testowane na PC). */
#ifndef SI_LICZ_H
#define SI_LICZ_H
#include <stdbool.h>
#include <stdint.h>

/* f(k) = fx * (A + (B + m*k) / c) / D   – k = numer tonu; zmienia się tylko ułamek pętli PLL (bez trzasków). */
typedef struct
{
    uint32_t fx;   /* częstotliwość TCXO w Hz (po kalibracji) */
    uint32_t D;    /* dzielnik wyjściowy, parzysty */
    uint32_t a, b, c;
    uint32_t m;    /* przyrost licznika na jeden ton */
} si_plan;

/* f_hz – częstotliwość tonu 0; krok_hz – odstęp tonów (0 = sama nośna); wielokrotnosc – D ma być jej wielokrotnością (2 albo 4). */
bool si_plan_licz(uint32_t fx, double f_hz, double krok_hz, uint32_t wielokrotnosc, si_plan* p);
double si_plan_hz(const si_plan* p, int k);
/* 8 bajtów rejestrów pętli PLL (MSNA / MSNB) dla tonu k */
void si_plan_rej_pll(const si_plan* p, int k, uint8_t* r8);
/* 8 bajtów rejestrów dzielnika wyjściowego (liczba całkowita D) */
void si_rej_wyj(uint32_t D, uint8_t* r8);
#endif

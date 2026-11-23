/* GOLkf / R20 – dekoder FT8 nad biblioteką kgoba/ft8_lib: dźwięk 12 kHz -> lista ramek dla rdzenia. Testowany na PC. */
#ifndef DEKODER_H
#define DEKODER_H
#include <stdbool.h>
#include "../rdzen/golkf.h"
#define DEK_BLOK 1920 /* próbek na symbol FT8 przy 12 kHz */
bool dek_init(void);
void dek_reset(void);
void dek_blok(const float* blok);   /* dokładnie DEK_BLOK próbek */
int dek_blokow(void);
/* czy_dalej (może być NULL): wołane przed każdym kandydatem; false = koniec czasu.
   sr_dt: średnie przesunięcie początku ramek względem 0,5 s od początku nagrania [s]. */
int dek_dekoduj(gk_dekod* d, int max, int max_kand, bool (*czy_dalej)(void), float* sr_dt, int* kandydatow);
#endif

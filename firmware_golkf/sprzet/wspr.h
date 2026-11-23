/* GOLkf / R20 – koder WSPR (ramka typu 1: znak, lokator 4 znaki, moc). Bez sprzętu, testowany na PC. */
#ifndef WSPR_H
#define WSPR_H
#include <stdbool.h>
#include <stdint.h>
#define WSPR_SYMBOLI 162
/* false = znaku albo lokatora nie da się zakodować w ramce typu 1 */
bool wspr_koduj(const char* znak, const char* lok4, int dbm, uint8_t* symbole);
#endif

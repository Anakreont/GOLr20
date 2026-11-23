/* Windows (MinGW) nie ma funkcji stpcpy, której używa ft8_lib – podstawiamy własną (definicja w ft8shim.c).
   Plik dołączany przy budowie opcją -include, razem z -Dstpcpy=ft8s_stpcpy (patrz buduj.sh). */
#ifndef FT8S_ZGODNOSC_H
#define FT8S_ZGODNOSC_H
char* ft8s_stpcpy(char* dst, const char* src);
#endif

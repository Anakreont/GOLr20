/* GOLkf / R20 – koder WSPR wg opisu protokołu (K1JT; G4JNT „WSPR coding process”). */
#include "wspr.h"
#include <ctype.h>
#include <string.h>

static const uint8_t SYNC[WSPR_SYMBOLI] = {
    1,1,0,0,0,0,0,0,1,0,0,0,1,1,1,0,0,0,1,0,0,1,0,1,1,1,1,0,0,0,0,0,0,0,1,0,0,1,0,1,0,0,0,0,0,0,1,0,
    1,1,0,0,1,1,0,1,0,0,0,1,1,0,1,0,0,0,0,1,1,0,1,0,1,0,1,0,1,0,0,1,0,0,1,0,
    1,1,0,0,0,1,1,0,1,0,1,0,0,0,1,0,0,0,0,0,1,0,0,1,0,0,1,1,1,0,1,1,0,0,1,1,
    0,1,0,0,0,1,1,1,0,0,0,0,0,1,0,1,0,0,1,1,0,0,0,0,0,0,0,1,1,0,1,0,1,1,0,0,0,1,1,0,0,0
};

static int kod(char c) /* 0-9, A-Z = 10-35, spacja = 36 */
{
    if (c >= '0' && c <= '9')
        return c - '0';
    if (c >= 'A' && c <= 'Z')
        return c - 'A' + 10;
    return 36;
}

bool wspr_koduj(const char* znak, const char* lok, int dbm, uint8_t* sym)
{
    char z[7] = "      ";
    char w[12];
    size_t n = strlen(znak);
    if (n < 3 || n > 6 || strlen(lok) < 4)
        return false;
    for (size_t i = 0; i < n; i++)
        w[i] = (char)toupper((unsigned char)znak[i]);
    w[n] = 0;
    /* trzeci znak musi być cyfrą: znak z jednoliterowym prefiksem dostaje spację z przodu */
    if (isdigit((unsigned char)w[2]))
        memcpy(z, w, n);
    else if (isdigit((unsigned char)w[1]) && n <= 5)
        memcpy(z + 1, w, n);
    else
        return false;
    for (int i = 3; i < 6; i++)
        if (!(z[i] == ' ' || (z[i] >= 'A' && z[i] <= 'Z')))
            return false;
    char l0 = (char)toupper((unsigned char)lok[0]), l1 = (char)toupper((unsigned char)lok[1]);
    if (l0 < 'A' || l0 > 'R' || l1 < 'A' || l1 > 'R' || !isdigit((unsigned char)lok[2]) || !isdigit((unsigned char)lok[3]))
        return false;

    uint32_t N = (uint32_t)kod(z[0]);
    N = N * 36 + (uint32_t)kod(z[1]);
    N = N * 10 + (uint32_t)kod(z[2]);
    N = N * 27 + (uint32_t)(kod(z[3]) - 10);
    N = N * 27 + (uint32_t)(kod(z[4]) - 10);
    N = N * 27 + (uint32_t)(kod(z[5]) - 10);
    uint32_t M = (uint32_t)((179 - 10 * (l0 - 'A') - (lok[2] - '0')) * 180 + 10 * (l1 - 'A') + (lok[3] - '0'));
    M = M * 128 + (uint32_t)dbm + 64;

    /* 50 bitów danych + 31 zer -> kod splotowy K=32, r=1/2 */
    uint8_t bity[81];
    memset(bity, 0, sizeof(bity));
    for (int i = 0; i < 28; i++)
        bity[i] = (uint8_t)((N >> (27 - i)) & 1);
    for (int i = 0; i < 22; i++)
        bity[28 + i] = (uint8_t)((M >> (21 - i)) & 1);
    uint8_t s[WSPR_SYMBOLI];
    uint32_t rej = 0;
    for (int i = 0; i < 81; i++)
    {
        rej = (rej << 1) | bity[i];
        s[2 * i] = (uint8_t)(__builtin_parity(rej & 0xF2D05351u));
        s[2 * i + 1] = (uint8_t)(__builtin_parity(rej & 0xE4613C47u));
    }
    /* przeplot: kolejność wg odwróconych bitów indeksu */
    uint8_t d[WSPR_SYMBOLI];
    int p = 0;
    for (int i = 0; i < 256 && p < WSPR_SYMBOLI; i++)
    {
        int j = 0;
        for (int k = 0; k < 8; k++)
            if (i & (1 << k))
                j |= 0x80 >> k;
        if (j < WSPR_SYMBOLI)
            d[j] = s[p++];
    }
    for (int i = 0; i < WSPR_SYMBOLI; i++)
        sym[i] = (uint8_t)(SYNC[i] + 2 * d[i]);
    return true;
}

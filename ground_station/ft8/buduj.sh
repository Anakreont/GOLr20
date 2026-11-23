#!/bin/bash
# Buduje bibliotekę FT8 dla GOLbase (Linux: libft8shim.so – do testów; Windows/MSYS: ft8shim.dll).
# Źródła kgoba/ft8_lib (MIT) nie są w repo – pobierane w ustalonej wersji do katalogu ft8_lib obok.
set -e
cd "$(dirname "$0")"
WERSJA=9fec6ca39886edbf96f4f5e71edc76da5074e871
if [ ! -d ft8_lib/ft8 ]; then
  git clone https://github.com/kgoba/ft8_lib ft8_lib
  git -C ft8_lib checkout -q $WERSJA
fi
S=ft8_lib
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) OUT=../ft8shim.dll; EXTRA="-static -static-libgcc -Dstpcpy=ft8s_stpcpy -include zgodnosc.h" ;;
  *) OUT=../libft8shim.so; EXTRA="-fPIC -fvisibility=hidden -DHAVE_STPCPY" ;;
esac
gcc -O2 -w -shared $EXTRA "-DLOG_PRINTF(...)=((void)0)" -I$S -o $OUT ft8shim.c $S/ft8/constants.c $S/ft8/crc.c $S/ft8/decode.c $S/ft8/encode.c \
    $S/ft8/ldpc.c $S/ft8/message.c $S/ft8/text.c $S/common/monitor.c $S/fft/kiss_fft.c $S/fft/kiss_fftr.c -lm
echo "zbudowano $OUT"

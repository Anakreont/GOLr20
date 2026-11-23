#!/bin/bash
# Builds the GOLkf core as a PC library (libgolkf_sym.so) for host-side testing.
# Needs kgoba/ft8_lib (MIT) next to this script:  git clone --depth 1 https://github.com/kgoba/ft8_lib
set -e
cd "$(dirname "$0")"
S=ft8_lib
[ -d $S/ft8 ] || git clone --depth 1 https://github.com/kgoba/ft8_lib $S
gcc -O2 -Wall -Wextra -Wno-unused-parameter -Wno-unused-variable -shared -fPIC -DHAVE_STPCPY "-DLOG_PRINTF(...)=((void)0)" -I$S -o libgolkf_sym.so \
    sym.c ../rdzen/golkf.c $S/ft8/message.c $S/ft8/text.c $S/ft8/constants.c $S/ft8/crc.c -lm
echo "built libgolkf_sym.so"

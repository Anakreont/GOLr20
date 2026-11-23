#!/bin/bash
# Testy na PC warstwy sprzętowej GOLkf (bez sprzętu):  ./test.sh
# Gdy w systemie są programy WSJT-X (wsprd, jt9), sygnały z testu sprawdzane są także nimi – niezależnym dekoderem.
set -e
cd "$(dirname "$0")"
S=${FT8_LIB:-../ft8_lib}
[ -d $S/ft8 ] || { git clone -q https://github.com/kgoba/ft8_lib ../ft8_lib && git -C ../ft8_lib checkout -q 9fec6ca39886edbf96f4f5e71edc76da5074e871; }
gcc -O2 -Wall -Wextra -Wno-unused-parameter -DHAVE_STPCPY "-DLOG_PRINTF(...)=((void)0)" -I$S -I.. -o /tmp/test_sprzet \
    test_sprzet.c ../si_licz.c ../wspr.c ../dsp.c ../dekoder.c ../../rdzen/golkf.c \
    $S/ft8/constants.c $S/ft8/crc.c $S/ft8/decode.c $S/ft8/encode.c $S/ft8/ldpc.c $S/ft8/message.c $S/ft8/text.c \
    $S/common/monitor.c $S/fft/kiss_fft.c $S/fft/kiss_fftr.c -lm 2>&1 | grep -v "ft8_lib" | grep "warning\|error" || true
/tmp/test_sprzet
if command -v wsprd >/dev/null; then
  echo "4. niezalezne sprawdzenie programem wsprd (WSJT-X)"
  W=$(mktemp -d); zle=0
  i=0
  for oczek in "SP9ABC KO00 10" "K1ABC FN42 37" "G4JNT IO90 20" "SP5XYZ JO90 13"; do
    wynik=$(cd $W && wsprd -f 14.0956 /tmp/golkf_wspr_$i.wav 2>/dev/null | grep -v "^<" || true)
    if echo "$wynik" | grep -q "$oczek"; then echo "  dobrze: $oczek   [$(echo "$wynik" | head -1 | tr -s ' ')]"; else echo "  BLAD: wsprd nie zdekodowal '$oczek': $wynik"; zle=1; fi
    i=$((i+1))
  done
  rm -rf $W
  [ $zle = 0 ] || exit 1
fi
if command -v jt9 >/dev/null; then
  echo "5. niezalezne sprawdzenie dzwieku z toru odbiorczego programem jt9 (WSJT-X)"
  W=$(mktemp -d)
  wynik=$(cd $W && jt9 -8 -d 3 /tmp/golkf_odbior.wav 2>/dev/null || true)
  rm -rf $W
  echo "$wynik" | sed 's/^/    /' | head -8
  echo "$wynik" | grep -q "CQ SP9ABC KO00" || { echo "  BLAD: jt9 nie zdekodowal 'CQ SP9ABC KO00'"; exit 1; }
  echo "$wynik" | grep -q "DL1XYZ" && { echo "  BLAD: jt9 slyszy stacje z drugiej wstegi"; exit 1; }
  echo "  dobrze"
fi

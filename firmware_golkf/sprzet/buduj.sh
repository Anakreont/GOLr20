#!/bin/bash
# Buduje firmware GOLkf dla płytki R20:  ./buduj.sh   ->  build/golkf_r20.uf2
# Potrzebne: cmake, gcc-arm-none-eabi, libnewlib-arm-none-eabi. Pico SDK i ft8_lib pobierane w ustalonych wersjach.
set -e
cd "$(dirname "$0")"
# kgoba/ft8_lib (MIT), pinned version
if [ ! -d ft8_lib/ft8 ]; then
  git clone -q https://github.com/kgoba/ft8_lib ft8_lib
  git -C ft8_lib checkout -q 9fec6ca39886edbf96f4f5e71edc76da5074e871
fi
if [ -z "$PICO_SDK_PATH" ]; then
  export PICO_SDK_PATH="$PWD/pico-sdk"
  if [ ! -d pico-sdk/src ]; then
    git clone -q --depth 1 --branch 2.3.1 https://github.com/raspberrypi/pico-sdk pico-sdk
    git -C pico-sdk submodule update -q --init --depth 1 lib/tinyusb
  fi
fi
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release ${FT8_LIB:+-DFT8_LIB=$FT8_LIB} > build.log 2>&1 || { tail -30 build.log; exit 1; }
cmake --build build -j4 >> build.log 2>&1 || { grep -n "error\|Error" build.log | head -30; exit 1; }
grep -n "warning" build.log | grep -v "pico-sdk\|ft8_lib" | head -20 || true
arm-none-eabi-size build/golkf_r20.elf
# wariant zapasowy na pierwsze uruchomienie: bez przełączania wbudowanej przetwornicy w stan wysokiej impedancji
cmake -S . -B build_bezhiz -DCMAKE_BUILD_TYPE=Release -DR20_BEZ_HIZ=1 ${FT8_LIB:+-DFT8_LIB=$FT8_LIB} >> build.log 2>&1 && cmake --build build_bezhiz -j4 >> build.log 2>&1
mkdir -p wynik
cp build/golkf_r20.uf2 wynik/golkf_r20_v02.uf2
cp build_bezhiz/golkf_r20.uf2 wynik/golkf_r20_v02_zapasowy.uf2
ls -la wynik/

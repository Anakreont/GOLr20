# GOLkf – firmware trackera-robota FT8 dla płytki R20 v0.2 (RP2354A). Budowanie: ./buduj.sh
cmake_minimum_required(VERSION 3.13)
set(PICO_BOARD r20 CACHE STRING "")
set(PICO_BOARD_HEADER_DIRS ${CMAKE_CURRENT_LIST_DIR}/boards)
set(PICO_PLATFORM rp2350-arm-s CACHE STRING "")
include(pico_sdk_import.cmake)
project(golkf_r20 C CXX ASM)
set(CMAKE_C_STANDARD 11)
pico_sdk_init()

if(NOT DEFINED FT8_LIB)
  set(FT8_LIB ${CMAKE_CURRENT_LIST_DIR}/ft8_lib)
endif()

add_executable(golkf_r20
  main.c konsola.c gps.c pamiec.c si5351.c si_licz.c odbior.c dsp.c dekoder.c nadaj.c wspr.c
  ../rdzen/golkf.c
  ${FT8_LIB}/ft8/constants.c ${FT8_LIB}/ft8/crc.c ${FT8_LIB}/ft8/decode.c ${FT8_LIB}/ft8/encode.c ${FT8_LIB}/ft8/ldpc.c
  ${FT8_LIB}/ft8/message.c ${FT8_LIB}/ft8/text.c ${FT8_LIB}/common/monitor.c ${FT8_LIB}/fft/kiss_fft.c ${FT8_LIB}/fft/kiss_fftr.c)
target_include_directories(golkf_r20 PRIVATE ${CMAKE_CURRENT_LIST_DIR} ${FT8_LIB})
target_compile_definitions(golkf_r20 PRIVATE HAVE_STPCPY "LOG_PRINTF(...)=((void)0)"
  PICO_STDIO_USB_ENABLE_RESET_VIA_VENDOR_INTERFACE=1 PICO_STDIO_USB_CONNECT_WAIT_TIMEOUT_MS=0
  PICO_HEAP_SIZE=0x48000)
target_compile_options(golkf_r20 PRIVATE -O2 -Wall -Wextra -Wno-unused-parameter)
if(R20_BEZ_HIZ)
  target_compile_definitions(golkf_r20 PRIVATE R20_BEZ_HIZ=1)   # wariant zapasowy: nie ruszaj wbudowanej przetwornicy
endif()
set_source_files_properties(${FT8_LIB}/ft8/message.c ${FT8_LIB}/ft8/text.c ${FT8_LIB}/ft8/decode.c ${FT8_LIB}/common/monitor.c
  ${FT8_LIB}/fft/kiss_fft.c ${FT8_LIB}/fft/kiss_fftr.c PROPERTIES COMPILE_OPTIONS "-w")
target_link_libraries(golkf_r20 pico_stdlib hardware_adc hardware_dma hardware_i2c hardware_flash hardware_sync hardware_watchdog hardware_powman)
pico_enable_stdio_usb(golkf_r20 1)
pico_enable_stdio_uart(golkf_r20 0)
pico_set_program_name(golkf_r20 "GOLkf R20")
pico_add_extra_outputs(golkf_r20)

/* Płytka R20 v0.2 (tracker-robot FT8 GOLkf): RP2354A (RP2350A + 2 MB pamięci w obudowie), kwarc 12 MHz. */
#ifndef _BOARDS_R20_H
#define _BOARDS_R20_H
pico_board_cmake_set(PICO_PLATFORM, rp2350)
#define GOLKF_R20
#define PICO_RP2350A 1
#define PICO_BOOT_STAGE2_CHOOSE_W25Q080 1
#ifndef PICO_FLASH_SPI_CLKDIV
#define PICO_FLASH_SPI_CLKDIV 2
#endif
pico_board_cmake_set_default(PICO_FLASH_SIZE_BYTES, (2 * 1024 * 1024))
#ifndef PICO_FLASH_SIZE_BYTES
#define PICO_FLASH_SIZE_BYTES (2 * 1024 * 1024)
#endif
pico_board_cmake_set_default(PICO_RP2350_A2_SUPPORTED, 1)
#ifndef PICO_RP2350_A2_SUPPORTED
#define PICO_RP2350_A2_SUPPORTED 1
#endif
/* kwarc X322512MSB4SI: dłuższy czas na rozruch generatora (jak w płytkach Pico) */
#ifndef PICO_XOSC_STARTUP_DELAY_MULTIPLIER
#define PICO_XOSC_STARTUP_DELAY_MULTIPLIER 64
#endif
#endif

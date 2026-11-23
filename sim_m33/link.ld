MEMORY { ROM (rx) : ORIGIN = 0x10000000, LENGTH = 4M  RAM (rwx) : ORIGIN = 0x38000000, LENGTH = 4M }
ENTRY(Reset_Handler)
SECTIONS {
 .text : { KEEP(*(.vectors)) *(.text*) *(.rodata*) *(.ARM.ex*) . = ALIGN(4); } > ROM
 _sidata = LOADADDR(.data);
 .data : { _sdata = .; *(.data*) . = ALIGN(4); _edata = .; } > RAM AT > ROM
 .bss : { _sbss = .; *(.bss*) *(COMMON) . = ALIGN(4); _ebss = .; _end = .; } > RAM
 _estack = ORIGIN(RAM) + LENGTH(RAM);
}

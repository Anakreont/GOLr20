#include <stdint.h>
extern uint32_t _sidata, _sdata, _edata, _sbss, _ebss, _estack, _end;
int main(void); void SysTick_Handler(void);
void Reset_Handler(void) {
    uint32_t *s = &_sidata, *d = &_sdata; while (d < &_edata) *d++ = *s++;
    for (d = &_sbss; d < &_ebss;) *d++ = 0;
    *(volatile uint32_t*)0xE000ED88 |= (0xFu << 20);   /* FPU on */
    __asm__ volatile("dsb\nisb");
    main(); for (;;) {}
}
void Default_Handler(void) { static const char m[] = "FAULT\n"; register int r0 __asm__("r0") = 4; register const char* r1 __asm__("r1") = m; __asm__ volatile("bkpt 0xAB" : "+r"(r0) : "r"(r1)); register int a __asm__("r0") = 0x18; register int b __asm__("r1") = 0x20026; __asm__ volatile("bkpt 0xAB" : "+r"(a) : "r"(b)); for (;;) {} }
__attribute__((section(".vectors"), used)) void (*const vt[16])(void) = { (void (*)(void))&_estack, Reset_Handler, Default_Handler, Default_Handler, Default_Handler, Default_Handler, Default_Handler, Default_Handler, 0, 0, 0, Default_Handler, Default_Handler, 0, Default_Handler, SysTick_Handler };
static char* brk;
void* _sbrk(int incr) { if (!brk) brk = (char*)&_end; char* p = brk; if (brk + incr > (char*)&_estack - 0x10000) return (void*)-1; brk += incr; return p; }

/* Minimal startup for STM32H743 (Cortex-M7): vector table, .data copy, .bss clear, FPU on.
 * No clock setup: the core runs on the 64 MHz HSI after reset. Caches stay off. */
#include <stdint.h>

extern uint32_t _sidata, _sdata, _edata, _sbss, _ebss, _estack;
int main(void);

void Reset_Handler(void)
{
    /* enable CP10/CP11 (FPU) before any floating-point instruction */
    *(volatile uint32_t *)0xE000ED88u |= 0xFu << 20;
    __asm volatile("dsb\n isb");

    uint32_t *src = &_sidata, *dst = &_sdata;
    while (dst < &_edata) *dst++ = *src++;
    for (dst = &_sbss; dst < &_ebss;) *dst++ = 0;

    main();
    for (;;) {
    }
}

void Default_Handler(void)
{
    for (;;) {
    }
}

/* Only the 16 core exceptions; peripheral IRQs are unused. */
__attribute__((section(".isr_vector"), used))
const void *const g_vectors[16] = {
    &_estack,
    (void *)Reset_Handler,
    (void *)Default_Handler, /* NMI */
    (void *)Default_Handler, /* HardFault */
    (void *)Default_Handler, /* MemManage */
    (void *)Default_Handler, /* BusFault */
    (void *)Default_Handler, /* UsageFault */
    0, 0, 0, 0,
    (void *)Default_Handler, /* SVC */
    (void *)Default_Handler, /* DebugMon */
    0,
    (void *)Default_Handler, /* PendSV */
    (void *)Default_Handler, /* SysTick */
};

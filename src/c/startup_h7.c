/* Startup for STM32H753 / H743 with the full vector table (16 core exceptions + 150 interrupts, numbers from
 * stm32h753xx.h, CMSIS device v1.10.7). Copies .data, clears .bss, enables the FPU, calls main().
 * Every handler not defined elsewhere is Default_Handler (weak aliases). Used by the board build (board_h7.c);
 * the size-only builds keep startup_h743.c. */
#include <stdint.h>

extern uint32_t _sidata, _sdata, _edata, _sbss, _ebss, _estack;
int main(void);

void Reset_Handler(void)
{
    *(volatile uint32_t *)0xE000ED88u |= 0xFu << 20;      /* CPACR: CP10 / CP11 full access (FPU) */
    __asm volatile("dsb\n isb");
    uint32_t *src = &_sidata, *dst = &_sdata;
    while (dst < &_edata)
        *dst++ = *src++;
    for (dst = &_sbss; dst < &_ebss;)
        *dst++ = 0;
    main();
    for (;;) {
    }
}

void Default_Handler(void)
{
    for (;;) {
    }
}

#define WEAK __attribute__((weak, alias("Default_Handler")))
void NMI_Handler(void) WEAK;
void HardFault_Handler(void) WEAK;
void MemManage_Handler(void) WEAK;
void BusFault_Handler(void) WEAK;
void UsageFault_Handler(void) WEAK;
void SVC_Handler(void) WEAK;
void DebugMon_Handler(void) WEAK;
void PendSV_Handler(void) WEAK;
void SysTick_Handler(void) WEAK;
void USART3_IRQHandler(void) WEAK;

#define N_IRQ 150
#define USART3_IRQ 39

__attribute__((section(".isr_vector"), used))
const void *const g_vectors[16 + N_IRQ] = {
    [0] = &_estack,
    [1] = (void *)Reset_Handler,
    [2] = (void *)NMI_Handler,
    [3] = (void *)HardFault_Handler,
    [4] = (void *)MemManage_Handler,
    [5] = (void *)BusFault_Handler,
    [6] = (void *)UsageFault_Handler,
    [11] = (void *)SVC_Handler,
    [12] = (void *)DebugMon_Handler,
    [14] = (void *)PendSV_Handler,
    [15] = (void *)SysTick_Handler,
    [16 ... 16 + N_IRQ - 1] = (void *)Default_Handler,
    [16 + USART3_IRQ] = (void *)USART3_IRQHandler,
};

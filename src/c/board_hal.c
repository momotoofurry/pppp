/* Board layer on ST's HAL for a STM32CubeMX project (NUCLEO-H753ZI): the clocks, caches and USART3 are set up by
 * the CubeMX-generated code (main.c: HAL_Init, SystemClock_Config, MX_USART3_UART_Init), so nothing here touches
 * the clock tree or the power supply. This replaces board_h7.c (register level, not yet checked against RM0433)
 * for the first runs on the board.
 *   Flash    bank 2 sector 7 (BENCH_IMAGE_BASE, the last 128 KB): HAL_FLASHEx_Erase, then HAL_FLASH_Program with
 *            256-bit Flash words; the bytes are buffered as in board_h7.c (each Flash word is programmed once) and
 *            the D-cache lines are invalidated after erasing / programming
 *   time     board_time_us: HAL tick (ms) + the SysTick down-counter (wraps after ~71 min); bench_cycles: DWT
 *   UART     USART3 (the ST-LINK virtual COM port) set up by CubeMX. TX: polled writes to TDR (no HAL lock, so it can
 *            be called from both contexts); in thread mode the receive-processing interrupt is masked while a packet
 *            goes out, so packets from the two contexts never interleave.
 *            RX (board_rx_start, route B): own USART3_IRQHandler at the highest priority -> 4 KB ring; TIM6 at 1 kHz
 *            (lower priority) drains the ring into the handler (rt_rx: features, votes, decision); the main loop
 *            (thread mode, lowest) runs rt_idle(). The same three contexts as board_h7.c. CubeMX must not enable the
 *            USART3 or TIM6 interrupts itself (their handlers are here).
 * Also the platform part of bench.h.
 */
#include <stdio.h>
#include <string.h>

#include "bench.h"
#include "board.h"
#include "stm32h7xx_hal.h"

extern UART_HandleTypeDef huart3;
extern uint8_t _sidata[], _sdata[], _edata[];       /* linker script: load address and size of .data */

#define FLASH_WORD 32u
#define RX_RING 4096u                                 /* power of two */
static uint32_t s_word_w[FLASH_WORD / 4];
static uint8_t *const s_word = (uint8_t *)s_word_w;
static uint32_t s_word_addr = 0xFFFFFFFFu;
static void (*s_rx_handler)(const uint8_t *p, uint32_t n);
static volatile uint8_t s_rx[RX_RING];
static volatile uint32_t s_rx_head, s_rx_tail, s_rx_overflow, s_rx_errors, s_rx_hw;
static int s_rx_on;
/* stack painting: the stack grows down from _estack (top of DTCM, nothing else up there); board_init() fills
 * STACK_PAINT bytes below the current stack pointer with a pattern, board_stack_peak() finds the deepest word
 * that was overwritten (main loop + all interrupts share the MSP) */
#define STACK_PAINT 0x8000u
#define STACK_PATTERN 0xC0FFEE11u
extern uint32_t _estack[];
static uint32_t *s_paint_lo;

int board_flash_erase_sector(uint32_t addr)
{
    if (addr < FLASH_BANK2_BASE)
        return -1;                                    /* only bank 2 is ever written (the program is in bank 1) */
    FLASH_EraseInitTypeDef e = {0};
    e.TypeErase = FLASH_TYPEERASE_SECTORS;
    e.Banks = FLASH_BANK_2;
    e.Sector = (addr - FLASH_BANK2_BASE) / FLASH_SECTOR_SIZE;
    e.NbSectors = 1;
    e.VoltageRange = FLASH_VOLTAGE_RANGE_3;
    uint32_t bad = 0;
    HAL_FLASH_Unlock();
    HAL_StatusTypeDef r = HAL_FLASHEx_Erase(&e, &bad);
    HAL_FLASH_Lock();
    SCB_InvalidateDCache_by_Addr((void *)(addr & ~(FLASH_SECTOR_SIZE - 1u)), (int32_t)FLASH_SECTOR_SIZE);
    s_word_addr = 0xFFFFFFFFu;
    return r == HAL_OK ? 0 : -1;
}

int board_flash_flush(void)
{
    if (s_word_addr == 0xFFFFFFFFu)
        return 0;
    HAL_FLASH_Unlock();
    HAL_StatusTypeDef r = HAL_FLASH_Program(FLASH_TYPEPROGRAM_FLASHWORD, s_word_addr, (uint32_t)s_word_w);
    HAL_FLASH_Lock();
    SCB_InvalidateDCache_by_Addr((void *)s_word_addr, (int32_t)FLASH_WORD);
    s_word_addr = 0xFFFFFFFFu;
    return r == HAL_OK ? 0 : -1;
}

int board_flash_write(uint32_t addr, const void *src, uint32_t n)
{
    const uint8_t *p = src;
    while (n) {
        uint32_t base = addr & ~(FLASH_WORD - 1u);
        if (base != s_word_addr) {                    /* another Flash word: program the buffered one */
            if (board_flash_flush() != 0)
                return -1;
            memset(s_word_w, 0xFF, sizeof s_word_w);       /* the whole 32-byte word (s_word is a pointer) */
            s_word_addr = base;
        }
        uint32_t off = addr - base, take = FLASH_WORD - off;
        if (take > n)
            take = n;
        memcpy(s_word + off, p, take);
        addr += take;
        p += take;
        n -= take;
    }
    return 0;
}

void board_init(void)
{
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->LAR = 0xC5ACCE55u;                           /* unlock the DWT (Cortex-M7) */
    DWT->CYCCNT = 0;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
    uint32_t *top = (uint32_t *)(__get_MSP() & ~3u) - 16;  /* leave this frame alone */
    s_paint_lo = (uint32_t *)((uintptr_t)_estack - STACK_PAINT);
    for (uint32_t *p = s_paint_lo; p < top; p++)
        *p = STACK_PATTERN;
}

uint32_t board_stack_peak(void)
{
    const uint32_t *p = s_paint_lo;
    while (p < _estack && *p == STACK_PATTERN)
        p++;
    return (uint32_t)((const uint8_t *)_estack - (const uint8_t *)p);
}

uint32_t board_rx_highwater(void)
{
    return s_rx_hw;
}

uint32_t board_time_us(void)
{
    uint32_t ms, val;
    do {                                              /* tick and counter read consistently */
        ms = HAL_GetTick();
        val = SysTick->VAL;
    } while (ms != HAL_GetTick());
    uint32_t per_us = (SysTick->LOAD + 1u) / 1000u;   /* SysTick reloads every 1 ms */
    return ms * 1000u + (SysTick->LOAD - val) / per_us;
}

void board_uart_tx(const uint8_t *p, uint32_t n)
{
    int thread = __get_IPSR() == 0;
    if (thread && s_rx_on)
        NVIC_DisableIRQ(TIM6_DAC_IRQn);               /* the receive processing sends packets too */
    while (n--) {
        while (!(USART3->ISR & USART_ISR_TXE_TXFNF)) {
        }
        USART3->TDR = *p++;
    }
    if (thread && s_rx_on)
        NVIC_EnableIRQ(TIM6_DAC_IRQn);
}

void board_set_rx_handler(void (*h)(const uint8_t *p, uint32_t n))
{
    s_rx_handler = h;
}

/* route B: switch USART3 to `baud` and start the receive path (USART3 interrupt -> ring -> TIM6 1 kHz -> handler) */
void board_rx_start(uint32_t baud)
{
    huart3.Init.BaudRate = baud;
    HAL_UART_Init(&huart3);
    s_rx_head = s_rx_tail = 0;
    __HAL_RCC_TIM6_CLK_ENABLE();
    uint32_t tim_hz = HAL_RCC_GetPCLK1Freq();
    if ((RCC->D2CFGR & RCC_D2CFGR_D2PPRE1) != RCC_D2CFGR_D2PPRE1_DIV1)
        tim_hz *= 2u;                                 /* APB1 timers run at 2 x PCLK1 when APB1 is divided */
    TIM6->PSC = tim_hz / 1000000u - 1u;               /* 1 MHz */
    TIM6->ARR = 1000u - 1u;                           /* 1 kHz */
    TIM6->EGR = TIM_EGR_UG;
    TIM6->SR = 0;
    TIM6->DIER = TIM_DIER_UIE;
    NVIC_SetPriority(USART3_IRQn, 0);                 /* highest: never lose a byte */
    NVIC_SetPriority(TIM6_DAC_IRQn, 8);               /* below the UART, above thread mode */
    s_rx_on = 1;
    NVIC_EnableIRQ(TIM6_DAC_IRQn);
    NVIC_EnableIRQ(USART3_IRQn);
    TIM6->CR1 = TIM_CR1_CEN;
    USART3->CR1 |= USART_CR1_RXNEIE_RXFNEIE;
}

uint32_t board_rx_overflow(void)
{
    return s_rx_overflow;
}

uint32_t board_rx_errors(void)
{
    return s_rx_errors;
}

void USART3_IRQHandler(void)
{
    uint32_t isr = USART3->ISR;
    if (isr & (USART_ISR_ORE | USART_ISR_FE | USART_ISR_NE)) {
        USART3->ICR = USART_ICR_ORECF | USART_ICR_FECF | USART_ICR_NECF;
        s_rx_errors++;
    }
    while (USART3->ISR & USART_ISR_RXNE_RXFNE) {
        uint8_t b = (uint8_t)USART3->RDR;
        uint32_t next = (s_rx_head + 1u) & (RX_RING - 1u);
        if (next == s_rx_tail) {
            s_rx_overflow++;                          /* ring full: byte dropped (the parser resyncs) */
        } else {
            s_rx[s_rx_head] = b;
            s_rx_head = next;
            uint32_t depth = (next - s_rx_tail) & (RX_RING - 1u);
            if (depth > s_rx_hw)
                s_rx_hw = depth;
        }
    }
}

void TIM6_DAC_IRQHandler(void)
{
    TIM6->SR = 0;
    uint8_t chunk[256];
    while (s_rx_handler && s_rx_tail != s_rx_head) {
        uint32_t n = 0;
        while (n < sizeof chunk && s_rx_tail != s_rx_head) {
            chunk[n++] = s_rx[s_rx_tail];
            s_rx_tail = (s_rx_tail + 1u) & (RX_RING - 1u);
        }
        s_rx_handler(chunk, n);
    }
}

void board_wait(void)
{
    __WFI();
}

/* ---------------------------------------------------------------- bench.h */
const uint8_t *bench_image(void)
{
    uint32_t end = (uint32_t)_sidata + (uint32_t)(_edata - _sdata);   /* end of what the program puts in Flash */
    return end <= BENCH_IMAGE_BASE ? (const uint8_t *)BENCH_IMAGE_BASE : 0;
}

uint32_t bench_cycles(void)
{
    return DWT->CYCCNT;
}

void bench_print(const char *s)
{
    board_uart_tx((const uint8_t *)s, (uint32_t)strlen(s));
}

const char *bench_platform(void)
{
    static char line[96];
    snprintf(line, sizeof line, "STM32H7 HAL, SYSCLK %lu MHz, I-cache %s, D-cache %s",
             (unsigned long)(SystemCoreClock / 1000000u), (SCB->CCR & SCB_CCR_IC_Msk) ? "on" : "off",
             (SCB->CCR & SCB_CCR_DC_Msk) ? "on" : "off");
    return line;
}

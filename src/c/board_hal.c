/* Board layer on ST's HAL for a STM32CubeMX project (NUCLEO-H753ZI): the clocks, caches and USART3 are set up by
 * the CubeMX-generated code (main.c: HAL_Init, SystemClock_Config, MX_USART3_UART_Init), so nothing here touches
 * the clock tree or the power supply. This replaces board_h7.c (register level, not yet checked against RM0433)
 * for the first runs on the board.
 *   Flash    bank 2 sector 7 (BENCH_IMAGE_BASE, the last 128 KB): HAL_FLASHEx_Erase, then HAL_FLASH_Program with
 *            256-bit Flash words; the bytes are buffered as in board_h7.c (each Flash word is programmed once) and
 *            the D-cache lines are invalidated after erasing / programming
 *   time     DWT cycle counter (board_time_us from it, wraps with the counter)
 *   UART     HAL_UART_Transmit on huart3 (the ST-LINK virtual COM port), blocking; no receive path (bench only)
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
static uint32_t s_word_w[FLASH_WORD / 4];
static uint8_t *const s_word = (uint8_t *)s_word_w;
static uint32_t s_word_addr = 0xFFFFFFFFu;
static void (*s_rx_handler)(const uint8_t *p, uint32_t n);

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
            memset(s_word, 0xFF, sizeof s_word);
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
}

uint32_t board_time_us(void)
{
    return DWT->CYCCNT / (SystemCoreClock / 1000000u);
}

void board_uart_tx(const uint8_t *p, uint32_t n)
{
    HAL_UART_Transmit(&huart3, (uint8_t *)p, (uint16_t)n, HAL_MAX_DELAY);
}

void board_set_rx_handler(void (*h)(const uint8_t *p, uint32_t n))
{
    s_rx_handler = h;                                 /* no receive path in this layer yet */
    (void)s_rx_handler;
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

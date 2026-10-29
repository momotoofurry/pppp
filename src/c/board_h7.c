/* Board layer for NUCLEO-H753ZI (STM32H753ZI; also H743ZI2, same MB1364 board), register level on the CMSIS
 * device header (STMicroelectronics cmsis-device-h7 v1.10.7) and CMSIS core (ARM CMSIS_5 5.9.0).
 *
 * *** COMPILED ONLY, NOT RUN, AND NOT CHECKED AGAINST RM0433 / UM2407 ***
 * The register and bit names come from the official header (so they exist); the VALUES below (clock tree, VOS,
 * Flash wait states, pins, Flash programming sequence) are the usual settings for this part and board, written
 * without the reference manual at hand. Each one is marked "check:" with what has to be confirmed before the
 * first run on the board.
 *
 *   clock     HSE bypass 8 MHz (ST-LINK MCO) -> PLL1 M=1 N=120 P=2: VCO 960 MHz, SYSCLK 480 MHz; HCLK 240 MHz,
 *             APB1..4 120 MHz. Needs VOS0 (VOS1 + SYSCFG overdrive) and 4 Flash wait states, WRHIGHFREQ 2.
 *   caches    I-cache and D-cache on; MPU: AXI SRAM normal, write-back, read/write allocate (as the default map).
 *   time      TIM2 (32 bit) at 1 MHz.
 *   UART      USART3 on PD8 (TX) / PD9 (RX), AF7 = the ST-LINK virtual COM port; 921600 baud from PCLK1 120 MHz.
 *             RX interrupt (highest priority) -> 4 KB ring; SysTick at 1 kHz (lower priority) drains the ring into the
 *             rt_rx() handler; the main loop (thread mode, lowest) runs rt_idle(). TX is polled.
 *   Flash     bank 2 sector 7 (0x081E0000, 128 KB): erase, then 256-bit Flash words with PG; partial words are
 *             buffered and padded with 0xFF; the D-cache lines of the sector are invalidated after writing.
 */
#include "board.h"

#include <string.h>

#include "stm32h7xx.h"

#define HSE_HZ 8000000u
#define SYSCLK_HZ 480000000u
#define PCLK1_HZ 120000000u
#define BAUD 921600u
#define RX_RING 4096u                             /* power of two */

uint32_t SystemCoreClock = 64000000u;            /* HSI after reset; system_stm32h7xx.c is not linked */
static volatile uint8_t s_rx[RX_RING];
static volatile uint32_t s_rx_head, s_rx_tail, s_rx_overflow;
static void (*s_rx_handler)(const uint8_t *p, uint32_t n);

/* ---------------------------------------------------------------- clocks */
static void clock_480mhz(void)
{
    /* supply: LDO (check: the Nucleo's SMPS / LDO solder bridges, UM2407; the CR3 write is allowed once) */
    PWR->CR3 = (PWR->CR3 & ~(PWR_CR3_BYPASS | PWR_CR3_SCUEN)) | PWR_CR3_LDOEN;
    while (!(PWR->CSR1 & PWR_CSR1_ACTVOSRDY)) {
    }
    /* VOS1, then overdrive -> VOS0 (check: RM0433 "voltage scaling", needed for 480 MHz on revision V) */
    PWR->D3CR = (PWR->D3CR & ~PWR_D3CR_VOS) | (3u << PWR_D3CR_VOS_Pos);
    while (!(PWR->D3CR & PWR_D3CR_VOSRDY)) {
    }
    RCC->APB4ENR |= RCC_APB4ENR_SYSCFGEN;
    (void)RCC->APB4ENR;
    SYSCFG->PWRCR |= SYSCFG_PWRCR_ODEN;
    while (!(PWR->D3CR & PWR_D3CR_VOSRDY)) {
    }
    /* HSE in bypass mode: 8 MHz from the ST-LINK MCO (check: UM2407, default solder bridges) */
    RCC->CR |= RCC_CR_HSEBYP | RCC_CR_HSEON;
    while (!(RCC->CR & RCC_CR_HSERDY)) {
    }
    /* PLL1: 8 MHz / M1 = 8 MHz in the 8-16 MHz range, x N 120 = 960 MHz (wide VCO), / P 2 = 480 MHz
     * (check: RM0433 PLL limits for the chosen VOS / revision) */
    RCC->PLLCKSELR = (RCC->PLLCKSELR & ~(RCC_PLLCKSELR_PLLSRC | RCC_PLLCKSELR_DIVM1)) | RCC_PLLCKSELR_PLLSRC_HSE |
                     (1u << RCC_PLLCKSELR_DIVM1_Pos);
    RCC->PLLCFGR = (RCC->PLLCFGR & ~(RCC_PLLCFGR_PLL1RGE | RCC_PLLCFGR_PLL1VCOSEL | RCC_PLLCFGR_PLL1FRACEN)) |
                   (3u << RCC_PLLCFGR_PLL1RGE_Pos) | RCC_PLLCFGR_DIVP1EN | RCC_PLLCFGR_DIVQ1EN;
    RCC->PLL1DIVR = ((120u - 1u) << RCC_PLL1DIVR_N1_Pos) | ((2u - 1u) << RCC_PLL1DIVR_P1_Pos) |
                    ((4u - 1u) << RCC_PLL1DIVR_Q1_Pos) | ((2u - 1u) << RCC_PLL1DIVR_R1_Pos);
    RCC->CR |= RCC_CR_PLL1ON;
    while (!(RCC->CR & RCC_CR_PLL1RDY)) {
    }
    /* Flash: 4 wait states, WRHIGHFREQ 2 for a 240 MHz AXI clock at VOS0 (check: RM0433 Flash latency table) */
    FLASH->ACR = (4u << FLASH_ACR_LATENCY_Pos) | (2u << FLASH_ACR_WRHIGHFREQ_Pos);
    while ((FLASH->ACR & FLASH_ACR_LATENCY) != (4u << FLASH_ACR_LATENCY_Pos)) {
    }
    /* HCLK = SYSCLK / 2 = 240 MHz, every APB = HCLK / 2 = 120 MHz */
    RCC->D1CFGR = RCC_D1CFGR_D1CPRE_DIV1 | RCC_D1CFGR_HPRE_DIV2 | RCC_D1CFGR_D1PPRE_DIV2;
    RCC->D2CFGR = RCC_D2CFGR_D2PPRE1_DIV2 | RCC_D2CFGR_D2PPRE2_DIV2;
    RCC->D3CFGR = RCC_D3CFGR_D3PPRE_DIV2;
    RCC->CFGR = (RCC->CFGR & ~RCC_CFGR_SW) | RCC_CFGR_SW_PLL1;
    while ((RCC->CFGR & RCC_CFGR_SWS) != RCC_CFGR_SWS_PLL1) {
    }
    SystemCoreClock = SYSCLK_HZ;
}

/* ---------------------------------------------------------------- caches / MPU */
static void caches_mpu(void)
{
    ARM_MPU_Disable();
    /* region 0: AXI SRAM 0x24000000, 512 KB: normal memory, write-back, read / write allocate, not shareable */
    ARM_MPU_SetRegion(ARM_MPU_RBAR(0u, 0x24000000u),
                      ARM_MPU_RASR(0u, ARM_MPU_AP_FULL, 1u, 0u, 1u, 1u, 0u, ARM_MPU_REGION_SIZE_512KB));
    ARM_MPU_Enable(MPU_CTRL_PRIVDEFENA_Msk);     /* everything else: default memory map */
    SCB_EnableICache();
    SCB_EnableDCache();
}

/* ---------------------------------------------------------------- time base */
static void timer_1mhz(void)
{
    RCC->APB1LENR |= RCC_APB1LENR_TIM2EN;
    (void)RCC->APB1LENR;
    TIM2->PSC = (2u * PCLK1_HZ) / 1000000u - 1u;  /* timer clock = 2 x PCLK1 when APB1 is divided (check: RM0433) */
    TIM2->ARR = 0xFFFFFFFFu;
    TIM2->EGR = TIM_EGR_UG;
    TIM2->CR1 = TIM_CR1_CEN;
}

uint32_t board_time_us(void)
{
    return TIM2->CNT;
}

/* ---------------------------------------------------------------- UART */
static void uart3(void)
{
    RCC->AHB4ENR |= RCC_AHB4ENR_GPIODEN;
    RCC->APB1LENR |= RCC_APB1LENR_USART3EN;
    (void)RCC->APB1LENR;
    /* PD8 = USART3_TX, PD9 = USART3_RX, alternate function 7 (check: UM2407 virtual COM port, datasheet AF table) */
    GPIOD->MODER = (GPIOD->MODER & ~((3u << 16) | (3u << 18))) | (2u << 16) | (2u << 18);
    GPIOD->OSPEEDR |= (3u << 16) | (3u << 18);
    GPIOD->AFR[1] = (GPIOD->AFR[1] & ~(0xFFu)) | (7u << 0) | (7u << 4);
    /* kernel clock: PCLK1 (USART28SEL = 0, the reset value) */
    RCC->D2CCIP2R &= ~RCC_D2CCIP2R_USART28SEL;
    USART3->CR1 = 0;
    USART3->BRR = (PCLK1_HZ + BAUD / 2u) / BAUD;  /* oversampling 16: 130 -> 923077 baud (+0.16 %) */
    USART3->CR1 = USART_CR1_TE | USART_CR1_RE | USART_CR1_RXNEIE_RXFNEIE | USART_CR1_UE;
    NVIC_SetPriority(USART3_IRQn, 0);              /* highest: never lose a byte */
    NVIC_EnableIRQ(USART3_IRQn);
}

void USART3_IRQHandler(void)
{
    uint32_t isr = USART3->ISR;
    if (isr & (USART_ISR_ORE | USART_ISR_FE | USART_ISR_NE))
        USART3->ICR = USART_ICR_ORECF | USART_ICR_FECF | USART_ICR_NECF;
    while (USART3->ISR & USART_ISR_RXNE_RXFNE) {
        uint8_t b = (uint8_t)USART3->RDR;
        uint32_t next = (s_rx_head + 1u) & (RX_RING - 1u);
        if (next == s_rx_tail)
            s_rx_overflow++;
        else {
            s_rx[s_rx_head] = b;
            s_rx_head = next;
        }
    }
}

/* 1 kHz, below the UART: hand the received bytes to the real-time handler (rt_rx) */
void SysTick_Handler(void)
{
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

void board_set_rx_handler(void (*h)(const uint8_t *p, uint32_t n))
{
    s_rx_handler = h;
}

void board_uart_tx(const uint8_t *p, uint32_t n)
{
    while (n--) {
        while (!(USART3->ISR & USART_ISR_TXE_TXFNF)) {
        }
        USART3->TDR = *p++;
    }
}

void board_wait(void)
{
    __WFI();
}

/* ---------------------------------------------------------------- Flash (bank 2) */
#define FLASH_WORD 32u
static uint32_t s_word_w[FLASH_WORD / 4];        /* word aligned: copied to Flash with 32-bit writes */
static uint8_t *const s_word = (uint8_t *)s_word_w;
static uint32_t s_word_addr = 0xFFFFFFFFu;        /* address of the buffered Flash word */

static int bank2_wait(void)
{
    while (FLASH->SR2 & (FLASH_SR_QW | FLASH_SR_BSY)) {
    }
    uint32_t err = FLASH->SR2 & (FLASH_SR_WRPERR | FLASH_SR_PGSERR | FLASH_SR_STRBERR | FLASH_SR_INCERR |
                                 FLASH_SR_OPERR);
    FLASH->CCR2 = FLASH_CCR_CLR_EOP | FLASH_CCR_CLR_WRPERR | FLASH_CCR_CLR_PGSERR | FLASH_CCR_CLR_STRBERR |
                  FLASH_CCR_CLR_INCERR | FLASH_CCR_CLR_OPERR;
    return err ? -1 : 0;
}

static void bank2_unlock(void)
{
    if (FLASH->CR2 & FLASH_CR_LOCK) {
        FLASH->KEYR2 = 0x45670123u;                /* check: RM0433 Flash key sequence */
        FLASH->KEYR2 = 0xCDEF89ABu;
    }
}

int board_flash_erase_sector(uint32_t addr)
{
    if (addr < FLASH_BANK2_BASE)
        return -1;                                 /* only bank 2 is ever written (code runs from bank 1) */
    uint32_t sector = (addr - FLASH_BANK2_BASE) / FLASH_SECTOR_SIZE;
    bank2_unlock();
    if (bank2_wait() != 0)
        return -1;
    /* check: RM0433 sector erase sequence and PSIZE for the supply voltage (x64 here) */
    FLASH->CR2 = (3u << FLASH_CR_PSIZE_Pos) | FLASH_CR_SER | (sector << FLASH_CR_SNB_Pos);
    FLASH->CR2 |= FLASH_CR_START;
    int r = bank2_wait();
    FLASH->CR2 &= ~FLASH_CR_SER;
    FLASH->CR2 |= FLASH_CR_LOCK;
    SCB_InvalidateDCache_by_Addr((void *)(addr & ~(FLASH_SECTOR_SIZE - 1u)), (int32_t)FLASH_SECTOR_SIZE);
    s_word_addr = 0xFFFFFFFFu;
    return r;
}

static int program_word(uint32_t addr, const uint8_t *w)
{
    bank2_unlock();
    FLASH->CR2 = (3u << FLASH_CR_PSIZE_Pos) | FLASH_CR_PG;
    __ISB();
    __DSB();
    volatile uint32_t *dst = (volatile uint32_t *)addr;
    const uint32_t *src = (const uint32_t *)(const void *)w;   /* w is s_word: 4-byte aligned */
    for (int i = 0; i < 8; i++)                    /* one 256-bit Flash word, 32-bit writes */
        dst[i] = src[i];
    __ISB();
    __DSB();
    int r = bank2_wait();
    FLASH->CR2 &= ~FLASH_CR_PG;
    FLASH->CR2 |= FLASH_CR_LOCK;
    SCB_InvalidateDCache_by_Addr((void *)addr, (int32_t)FLASH_WORD);
    return r;
}

int board_flash_flush(void)
{
    if (s_word_addr == 0xFFFFFFFFu)
        return 0;
    int r = program_word(s_word_addr, s_word);
    s_word_addr = 0xFFFFFFFFu;
    return r;
}

int board_flash_write(uint32_t addr, const void *src, uint32_t n)
{
    const uint8_t *p = src;
    while (n) {
        uint32_t base = addr & ~(FLASH_WORD - 1u);
        if (base != s_word_addr) {                 /* another Flash word: write out the buffered one */
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

/* ---------------------------------------------------------------- init */
void board_init(void)
{
    clock_480mhz();
    caches_mpu();
    timer_1mhz();
    uart3();
    NVIC_SetPriority(SysTick_IRQn, 8);             /* below the UART, above thread mode */
    SysTick_Config(SYSCLK_HZ / 1000u);
}

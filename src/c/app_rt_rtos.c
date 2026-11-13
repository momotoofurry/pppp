/* LDA main line on FreeRTOS (report 35.36; exploratory, NOT the frozen firmware): rt_lda.c on the HAL board layer,
 * the same core as app_rt_lda.c, with the bare-metal contexts mapped one to one onto RTOS tasks:
 *
 *   bare metal (app_rt_lda.c)                    FreeRTOS (this file)
 *   USART3 IRQ (prio 0) -> 4 KB ring             unchanged (board_hal.c), never masked by the kernel
 *   TIM6 IRQ 1 kHz (prio 8): ring -> rtl_rx      TIM6 IRQ 1 kHz: ring -> stream buffer (FromISR)
 *                                                task "rx" (priority 3): stream buffer -> rtl_rx (features, LDA
 *                                                scores, votes, commands, PRED packets)
 *   main loop: rtl_idle (fits, task-label        task "learn" (priority 1): rtl_idle; preempted by "rx" at any
 *   updates), diagnostics every 10 s, WFI        point, exactly as the main loop was by the TIM6 IRQ; diagnostics
 *                                                every 10 s
 *                                                idle task: __WFI()
 *
 * rt_lda.c assumes that rtl_rx may preempt rtl_idle but never the other way round: a higher-priority task gives
 * the same guarantee. Packets from the two tasks must not interleave: every send suspends the scheduler (the USART3
 * and TIM6 interrupts keep running; board_uart_tx itself masks TIM6 in thread mode, as before).
 * The kernel's SVC / PendSV / SysTick handlers are installed by copying the vector table to RAM (VTOR) and patching
 * those three entries, so the CubeMX files (Core/Src/stm32h7xx_it.c) stay untouched; the SysTick handler also
 * keeps HAL_IncTick() (board_time_us uses the HAL tick).
 * Static allocation only. Extra diagnostics (STATUS packets, every 10 s): 30 / 31 = stack used by "rx" / "learn"
 * (bytes, from the high-water mark), 32 = deepest MSP use (interrupts; stack painting), 33 / 34 / 35 = CPU share of
 * "rx" / "learn" / idle over the last 10 s (x 100, i.e. 1234 = 12.34 %).
 * Defines app_rt_run(); built like app_rt_lda.c (-DEMG_APP_RT=ON) in a COPY of the project with the FreeRTOS kernel.
 */
#include "app_rt.h"

#include <string.h>

#include "FreeRTOS.h"
#include "board.h"
#include "rt_lda.h"
#include "stm32h7xx_hal.h"
#include "stream_buffer.h"
#include "task.h"

#define RX_STACK_WORDS 2048u
#define LEARN_STACK_WORDS 2048u
#define IDLE_STACK_WORDS configMINIMAL_STACK_SIZE
#define RX_PRIO 3
#define LEARN_PRIO 1
#define STREAM_BYTES 4096u
#define CHUNK 256u
enum { EV_RX_STACK = 30, EV_LEARN_STACK = 31, EV_MSP = 32, EV_CPU_RX = 33, EV_CPU_LEARN = 34, EV_CPU_IDLE = 35 };

static StaticTask_t s_rx_tcb, s_learn_tcb, s_idle_tcb;
static StackType_t s_rx_stack[RX_STACK_WORDS], s_learn_stack[LEARN_STACK_WORDS], s_idle_stack[IDLE_STACK_WORDS];
static TaskHandle_t s_rx_task, s_learn_task;
static StaticStreamBuffer_t s_sb_ctl;
static uint8_t s_sb_mem[STREAM_BYTES + 1];
static StreamBufferHandle_t s_sb;
static volatile uint32_t s_sb_drop;

/* ------------------------------------------------------------------ vector table in RAM */
extern uint32_t g_pfnVectors[];
extern void vPortSVCHandler(void);
extern void xPortPendSVHandler(void);
extern void xPortSysTickHandler(void);
#define N_VECTORS 256u
static uint32_t s_vectors[N_VECTORS] __attribute__((aligned(1024)));

static void tick_handler(void)
{
    HAL_IncTick();
    if (xTaskGetSchedulerState() != taskSCHEDULER_NOT_STARTED)
        xPortSysTickHandler();
}

static void install_vectors(void)
{
    __disable_irq();
    memcpy(s_vectors, g_pfnVectors, sizeof s_vectors);
    s_vectors[11] = (uint32_t)vPortSVCHandler;          /* SVCall */
    s_vectors[14] = (uint32_t)xPortPendSVHandler;       /* PendSV */
    s_vectors[15] = (uint32_t)tick_handler;             /* SysTick */
    SCB_CleanDCache_by_Addr(s_vectors, (int32_t)sizeof s_vectors);
    __DSB();
    SCB->VTOR = (uint32_t)s_vectors;
    __DSB();
    __ISB();
    __enable_irq();
}

/* ------------------------------------------------------------------ hooks required by the configuration */
void vApplicationGetIdleTaskMemory(StaticTask_t **tcb, StackType_t **stack, uint32_t *words)
{
    *tcb = &s_idle_tcb;
    *stack = s_idle_stack;
    *words = IDLE_STACK_WORDS;
}

void vApplicationIdleHook(void)
{
    __WFI();
}

static void halt(void)
{
    __disable_irq();
    for (;;) {
    }
}

void vApplicationStackOverflowHook(TaskHandle_t task, char *name)
{
    (void)task;
    (void)name;
    halt();
}

void rtos_assert_failed(const char *file, int line)
{
    (void)file;
    (void)line;
    halt();
}

/* ------------------------------------------------------------------ glue */
static void tx_locked(const uint8_t *p, uint32_t n)
{
    if (xTaskGetSchedulerState() == taskSCHEDULER_RUNNING && __get_IPSR() == 0) {
        vTaskSuspendAll();
        board_uart_tx(p, n);
        (void)xTaskResumeAll();
    } else {
        board_uart_tx(p, n);
    }
}

/* TIM6 interrupt (board_hal.c drains the USART ring into this handler every 1 ms) */
static void rx_isr(const uint8_t *p, uint32_t n)
{
    BaseType_t woken = pdFALSE;
    size_t put = xStreamBufferSendFromISR(s_sb, p, n, &woken);
    if (put < n)
        s_sb_drop += (uint32_t)(n - put);
    portYIELD_FROM_ISR(woken);
}

static void rx_task(void *arg)
{
    (void)arg;
    static uint8_t chunk[CHUNK];
    board_set_rx_handler(rx_isr);
    board_rx_start(APP_RT_BAUD);
    for (;;) {
        size_t n = xStreamBufferReceive(s_sb, chunk, sizeof chunk, portMAX_DELAY);
        if (n) {
            rtl_rx(chunk, (uint32_t)n);
            xTaskNotifyGive(s_learn_task);
        }
    }
}

static uint32_t cpu_x100(uint32_t dt, uint32_t total)
{
    return total ? (uint32_t)((uint64_t)dt * 10000u / total) : 0u;
}

static void diagnostics(void)
{
    static uint32_t last_total, last_rx, last_learn, last_idle;
    TaskStatus_t st[4];
    uint32_t total = 0, rx = 0, learn = 0, idle = 0;
    UBaseType_t k = uxTaskGetSystemState(st, 4, &total);
    for (UBaseType_t i = 0; i < k; i++) {
        if (st[i].xHandle == s_rx_task)
            rx = st[i].ulRunTimeCounter;
        else if (st[i].xHandle == s_learn_task)
            learn = st[i].ulRunTimeCounter;
        else if (st[i].xHandle == xTaskGetIdleTaskHandle())
            idle = st[i].ulRunTimeCounter;
    }
    uint32_t dt = total - last_total;
    rtl_status(RTL_EV_DIAG_RX_HW, (int32_t)board_rx_highwater());
    rtl_status(RTL_EV_DIAG_RX_OVF, (int32_t)(board_rx_overflow() + s_sb_drop));
    rtl_status(RTL_EV_DIAG_RX_ERR, (int32_t)board_rx_errors());
    rtl_status(EV_RX_STACK, (int32_t)((RX_STACK_WORDS - uxTaskGetStackHighWaterMark(s_rx_task)) * sizeof(StackType_t)));
    rtl_status(EV_LEARN_STACK, (int32_t)((LEARN_STACK_WORDS - uxTaskGetStackHighWaterMark(NULL)) * sizeof(StackType_t)));
    rtl_status(EV_MSP, (int32_t)board_stack_peak());
    if (last_total) {
        rtl_status(EV_CPU_RX, (int32_t)cpu_x100(rx - last_rx, dt));
        rtl_status(EV_CPU_LEARN, (int32_t)cpu_x100(learn - last_learn, dt));
        rtl_status(EV_CPU_IDLE, (int32_t)cpu_x100(idle - last_idle, dt));
    }
    last_total = total;
    last_rx = rx;
    last_learn = learn;
    last_idle = idle;
}

static void learn_task(void *arg)
{
    (void)arg;
    uint32_t last = board_time_us();
    for (;;) {
        (void)ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(10));
        rtl_idle();
        if (board_time_us() - last >= APP_RT_DIAG_US) {
            last = board_time_us();
            diagnostics();
        }
    }
}

void app_rt_run(void)
{
    const rtl_config_t cfg = {
        .tx = tx_locked, .now_us = board_time_us, .warmup = 9, .margin_x100 = 0, .dist2 = 0, .k = 3,
    };
    rtl_init(&cfg);
    s_sb = xStreamBufferCreateStatic(STREAM_BYTES, 1, s_sb_mem, &s_sb_ctl);
    s_rx_task = xTaskCreateStatic(rx_task, "rx", RX_STACK_WORDS, NULL, RX_PRIO, s_rx_stack, &s_rx_tcb);
    s_learn_task = xTaskCreateStatic(learn_task, "learn", LEARN_STACK_WORDS, NULL, LEARN_PRIO, s_learn_stack, &s_learn_tcb);
    install_vectors();
    vTaskStartScheduler();
    halt();                                             /* not reached */
}

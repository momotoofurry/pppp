/* Serial protocol between the PC (route B: Trigno samples forwarded from the lab PC) and the MCU. Portable C.
 *
 * Every packet:  0xA5 0x5A | type u8 | seq u16 | len u16 | payload (len bytes) | crc u16
 * little-endian; crc = CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF, no reflection) over type .. payload
 * (Python: binascii.crc_hqx(bytes, 0xFFFF)). seq counts packets per type and direction (wraps at 65536).
 *
 * PC -> MCU
 *   PK_SAMPLES  frames of PK_CH int16 samples, frame-major (ch0..ch7, ch0..ch7, ...), 1 LSB = PK_LSB_VOLT V
 *               (0.25 uV: +-8.19 mV; the lab's largest MVC is 1.85 mV). 20 frames (10 ms at 2 kHz) per packet:
 *               9 + 320 bytes per 10 ms = 32.9 KB/s, 36% of 921600 baud (8N1)
 *   PK_CONTROL  sub-command u8 + arguments, see rt.h
 * MCU -> PC
 *   PK_COMMAND  window u32 | t_us u32 | command u8 | class u8 | ratio_permille u16    (a robot command)
 *   PK_PRED     window u32 | t_us u32 | class u8 | accepted u8 | ratio_permille u16 | pushed u8 | pad u8
 *               (every classified window, if enabled: logging / latency)
 *   PK_STATUS   event u8 | pad u8[3] | value i32
 * t_us: MCU time of the decision (board timer; the PC logs its own receive time next to it).
 */
#pragma once
#include <stdint.h>

#define PK_SYNC0 0xA5u
#define PK_SYNC1 0x5Au
#define PK_HEADER 7                     /* sync, type, seq, len */
#define PK_OVERHEAD 9                   /* header + crc */
#define PK_MAX_PAYLOAD 512
#define PK_CH 8
#define PK_LSB_VOLT 2.5e-7f

enum { PK_SAMPLES = 0x01, PK_CONTROL = 0x02, PK_COMMAND = 0x81, PK_PRED = 0x83, PK_STATUS = 0x82 };

typedef void (*pk_handler_t)(void *ctx, uint8_t type, uint16_t seq, const uint8_t *payload, uint16_t len);

typedef struct {
    uint8_t raw[PK_OVERHEAD + PK_MAX_PAYLOAD];   /* bytes of the packet being received */
    uint16_t n;                                  /* bytes in raw */
    uint16_t need;                               /* total bytes of the packet once the header is known */
    uint32_t ok, crc_errors, len_errors, skipped_bytes;
} pk_parser_t;

uint16_t pk_crc16(const uint8_t *p, uint32_t n, uint16_t crc);
void pk_init(pk_parser_t *p);
/* feed received bytes; calls h for every packet with a valid CRC. After a bad packet the parser rescans the
 * bytes after its sync word, so a good packet that starts inside the bad one is not lost. */
void pk_feed(pk_parser_t *p, const uint8_t *data, uint32_t n, pk_handler_t h, void *ctx);
/* build a packet into out (PK_OVERHEAD + len bytes); returns its size, or 0 if len is too large */
uint32_t pk_build(uint8_t *out, uint8_t type, uint16_t seq, const void *payload, uint16_t len);

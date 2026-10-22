/* STM32H743ZI (NUCLEO-H743ZI2): 2 MB Flash, 128 KB DTCM, 512 KB AXI SRAM.
 * Self-calibration build: model tables are const -> .rodata in FLASH; .bss (buffer, t-SNE, training,
 * RAM trees) goes to the 512 KB AXI SRAM; .data and the stack stay in DTCM. The last Flash sector is kept
 * free for the one-shot image (on-device calibration, oneshot.c).
 * _Min_Stack_Size only reserves space so the linker fails if RAM overflows; the real worst-case
 * stack depth comes from -fstack-usage (see build_arm.sh). */
ENTRY(Reset_Handler)

MEMORY
{
  FLASH   (rx)  : ORIGIN = 0x08000000, LENGTH = 2048K - 128K
  ONESHOT (r)   : ORIGIN = 0x081E0000, LENGTH = 128K   /* last 128 KB sector (bank 2, sector 7): one-shot image */
  DTCM    (rwx) : ORIGIN = 0x20000000, LENGTH = 128K
  AXI     (rwx) : ORIGIN = 0x24000000, LENGTH = 512K
}

_oneshot_image = ORIGIN(ONESHOT);   /* written by os_calibrate() through board_flash_write(), see oneshot.h */
_oneshot_bytes = LENGTH(ONESHOT);
_estack = ORIGIN(DTCM) + LENGTH(DTCM);
_Min_Stack_Size = 0x1000;

SECTIONS
{
  .isr_vector : { KEEP(*(.isr_vector)) } > FLASH

  .text : {
    *(.text*)
    *(.rodata*)
    . = ALIGN(4);
  } > FLASH

  .ARM.exidx : { *(.ARM.exidx*) } > FLASH

  _sidata = LOADADDR(.data);
  .data : {
    . = ALIGN(4);
    _sdata = .;
    *(.data*)
    . = ALIGN(4);
    _edata = .;
  } > DTCM AT > FLASH

  .bss (NOLOAD) : {
    . = ALIGN(4);
    _sbss = .;
    *(.bss*)
    *(COMMON)
    . = ALIGN(4);
    _ebss = .;
  } > AXI

  ._stack (NOLOAD) : {
    . = ALIGN(8);
    . = . + _Min_Stack_Size;
  } > DTCM
}

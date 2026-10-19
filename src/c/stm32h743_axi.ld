/* STM32H743ZI (NUCLEO-H743ZI2): 2 MB Flash, 128 KB DTCM, 512 KB AXI SRAM.
 * Self-calibration build: model tables are const -> .rodata in FLASH; .bss (buffer, t-SNE, training,
 * RAM trees) goes to the 512 KB AXI SRAM; .data and the stack stay in DTCM.
 * _Min_Stack_Size only reserves space so the linker fails if RAM overflows; the real worst-case
 * stack depth comes from -fstack-usage (see build_arm.sh). */
ENTRY(Reset_Handler)

MEMORY
{
  FLASH (rx)  : ORIGIN = 0x08000000, LENGTH = 2048K
  DTCM  (rwx) : ORIGIN = 0x20000000, LENGTH = 128K
  AXI   (rwx) : ORIGIN = 0x24000000, LENGTH = 512K
}

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

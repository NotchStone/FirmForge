/*
******************************************************************************
**  GC-H743 板级链接脚本 —— STM32H743ZIT6 / LQFP144 / 2 MB Flash
**
**  基线：STM32CubeH7 / Projects/NUCLEO-H743ZI/Templates/STM32CubeIDE/
**        STM32H743ZITx_FLASH_DTCMRAM.ld（对外部包的引用，不入库）
**
**  与基线的差异（只有一处，但是关键的一处）
**  ----------------------------------------
**  基线只声明了 ITCMRAM 64K + RAM(DTCM) 128K + ROM 2048K，
**  512 KB 的 AXI SRAM、288 KB 的 SRAM1~3、64 KB 的 SRAM4 **完全没有出现在
**  MEMORY 里** —— 不是芯片没有，是模板没写。后果是应用无法用链接器符号
**  往这些区放东西，只能硬编地址。
**
**  本脚本把全部可用内存区声明出来，并各给一个可用的段名。
**  默认布局仍与基线一致（data/bss/heap/stack 全在 DTCM）—— 因为 DTCM 是
**  零等待、直连内核的 TCM，是默认路径最快的选择；而需要大缓冲区的外设
**  （以太网描述符、JPEG/LTDC 帧缓冲）本来就必须显式指定位置。
**
**  ⚠️ DTCM / ITCM 走 TCM 总线，**DMA 不可访问**。任何 DMA 缓冲区必须放在
**     AXI / SRAM1~3 / SRAM4（即 `.axisram` / `.sram1`~`.sram3` / `.sram4`）。
**     D-Cache 与 DMA 的一致性另需处理（RM0433 Cache 章节）。
**
**  ⚠️ 除 `.bss` 外，下列命名区**不会被启动代码清零**（startup 只清 `_sbss`~
**     `_ebss`）。放进这些区的数据使用前请自行初始化。
**
**  内存数值来源：ST 官方产品页 stm32h743zi + 数据手册 DS12110 Table 2
**                （与 board.yaml::memories 一致，有测试比对）
******************************************************************************
*/

/* Entry Point */
ENTRY(Reset_Handler)

/* Highest address of the user mode stack */
_estack = ORIGIN(DTCM) + LENGTH(DTCM); /* end of "DTCM" Ram type memory */

_Min_Heap_Size = 0x800;  /* required amount of heap  */
_Min_Stack_Size = 0x400; /* required amount of stack */

/* Memories definition */
MEMORY
{
  ITCM  (xrw) : ORIGIN = 0x00000000,   LENGTH = 64K    /* 指令 TCM，零等待 */
  DTCM  (xrw) : ORIGIN = 0x20000000,   LENGTH = 128K   /* 数据 TCM，零等待 */
  AXI   (xrw) : ORIGIN = 0x24000000,   LENGTH = 512K   /* D1，主 SRAM */
  SRAM1 (xrw) : ORIGIN = 0x30000000,   LENGTH = 128K   /* D2 */
  SRAM2 (xrw) : ORIGIN = 0x30020000,   LENGTH = 128K   /* D2 */
  SRAM3 (xrw) : ORIGIN = 0x30040000,   LENGTH = 32K    /* D2 */
  SRAM4 (xrw) : ORIGIN = 0x38000000,   LENGTH = 64K    /* D3 */
  ROM   (rx)  : ORIGIN = 0x08000000,   LENGTH = 2048K
}

/* Sections */
SECTIONS
{
  /* The startup code into "ROM" Rom type memory */
  .isr_vector :
  {
    . = ALIGN(4);
    KEEP(*(.isr_vector)) /* Startup code */
    . = ALIGN(4);
  } >ROM

  /* The program code and other data into "ROM" Rom type memory */
  .text :
  {
    . = ALIGN(4);
    *(.text)           /* .text sections (code) */
    *(.text*)          /* .text* sections (code) */
    *(.glue_7)         /* glue arm to thumb code */
    *(.glue_7t)        /* glue thumb to arm code */
    *(.eh_frame)

    KEEP (*(.init))
    KEEP (*(.fini))

    . = ALIGN(4);
    _etext = .;        /* define a global symbols at end of code */
  } >ROM

  /* Constant data into "ROM" Rom type memory */
  .rodata :
  {
    . = ALIGN(4);
    *(.rodata)         /* .rodata sections (constants, strings, etc.) */
    *(.rodata*)        /* .rodata* sections (constants, strings, etc.) */
    . = ALIGN(4);
  } >ROM

  .ARM.extab (READONLY) : /* The READONLY keyword is only supported in GCC11 and later, remove it if using GCC10 or earlier. */
  {
    . = ALIGN(4);
    *(.ARM.extab* .gnu.linkonce.armextab.*)
    . = ALIGN(4);
  } >ROM

  .ARM (READONLY) : /* The READONLY keyword is only supported in GCC11 and later, remove it if using GCC10 or earlier. */
  {
    . = ALIGN(4);
    __exidx_start = .;
    *(.ARM.exidx*)
    __exidx_end = .;
    . = ALIGN(4);
  } >ROM

  .preinit_array (READONLY) : /* The READONLY keyword is only supported in GCC11 and later, remove it if using GCC10 or earlier. */
  {
    . = ALIGN(4);
    PROVIDE_HIDDEN (__preinit_array_start = .);
    KEEP (*(.preinit_array*))
    PROVIDE_HIDDEN (__preinit_array_end = .);
    . = ALIGN(4);
  } >ROM

  .init_array (READONLY) : /* The READONLY keyword is only supported in GCC11 and later, remove it if using GCC10 or earlier. */
  {
    . = ALIGN(4);
    PROVIDE_HIDDEN (__init_array_start = .);
    KEEP (*(SORT(.init_array.*)))
    KEEP (*(.init_array*))
    PROVIDE_HIDDEN (__init_array_end = .);
    . = ALIGN(4);
  } >ROM

  .fini_array (READONLY) : /* The READONLY keyword is only supported in GCC11 and later, remove it if using GCC10 or earlier. */
  {
    . = ALIGN(4);
    PROVIDE_HIDDEN (__fini_array_start = .);
    KEEP (*(SORT(.fini_array.*)))
    KEEP (*(.fini_array*))
    PROVIDE_HIDDEN (__fini_array_end = .);
    . = ALIGN(4);
  } >ROM

  /* Used by the startup to initialize data */
  _sidata = LOADADDR(.data);

  /* Initialized data sections into "DTCM" Ram type memory */
  .data :
  {
    . = ALIGN(4);
    _sdata = .;        /* create a global symbol at data start */
    *(.data)           /* .data sections */
    *(.data*)          /* .data* sections */
    *(.RamFunc)        /* .RamFunc sections */
    *(.RamFunc*)       /* .RamFunc* sections */

    . = ALIGN(4);
    _edata = .;        /* define a global symbol at data end */

  } >DTCM AT> ROM

  /* Uninitialized data section into "DTCM" Ram type memory */
  . = ALIGN(4);
  .bss :
  {
    /* This is used by the startup in order to initialize the .bss section */
    _sbss = .;         /* define a global symbol at bss start */
    __bss_start__ = _sbss;
    *(.bss)
    *(.bss*)
    *(COMMON)

    . = ALIGN(4);
    _ebss = .;         /* define a global symbol at bss end */
    __bss_end__ = _ebss;
  } >DTCM

  /* User_heap_stack section, used to check that there is enough "DTCM" Ram  type memory left */
  ._user_heap_stack :
  {
    . = ALIGN(8);
    PROVIDE ( end = . );
    PROVIDE ( _end = . );
    . = . + _Min_Heap_Size;
    . = . + _Min_Stack_Size;
    . = ALIGN(8);
  } >DTCM

  /* ------------------------------------------------------------------
   * 命名内存区 —— 供显式放置使用，用法：
   *   __attribute__((section(".axisram"))) uint8_t dma_buf[4096];
   *
   * (NOLOAD) = 不占用 Flash 空间、不由启动代码搬运。适合 DMA 描述符、
   * 帧缓冲、通信缓冲区这类"运行时才填"的东西。
   * ------------------------------------------------------------------ */
  .itcmram (NOLOAD) :
  {
    . = ALIGN(4);
    *(.itcmram) *(.itcmram*)
    . = ALIGN(4);
  } >ITCM

  .axisram (NOLOAD) :
  {
    . = ALIGN(4);
    *(.axisram) *(.axisram*)
    . = ALIGN(4);
  } >AXI

  .sram1 (NOLOAD) :
  {
    . = ALIGN(4);
    *(.sram1) *(.sram1*)
    . = ALIGN(4);
  } >SRAM1

  .sram2 (NOLOAD) :
  {
    . = ALIGN(4);
    *(.sram2) *(.sram2*)
    . = ALIGN(4);
  } >SRAM2

  .sram3 (NOLOAD) :
  {
    . = ALIGN(4);
    *(.sram3) *(.sram3*)
    . = ALIGN(4);
  } >SRAM3

  .sram4 (NOLOAD) :
  {
    . = ALIGN(4);
    *(.sram4) *(.sram4*)
    . = ALIGN(4);
  } >SRAM4

  /* Remove information from the compiler libraries */
  /DISCARD/ :
  {
    libc.a ( * )
    libm.a ( * )
    libgcc.a ( * )
  }

  .ARM.attributes 0 : { *(.ARM.attributes) }
}

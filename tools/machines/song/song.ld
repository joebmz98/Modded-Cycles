/* Song mode, stage 1 (notes/74 §8-9), in freed sprite masks (tools/sprites.py, free in REGISTRY.md on 14/11/2026):
 *   - one 41x41 mask (328 bytes), four 35x35 (280 bytes) and three 34x34 (272 bytes): the code and the router entry;
 *   - the variables in the free hole above the OS's BSS (0x423380b0..0x4233efff, notes/56 §3.5.2), at 0x4233d000,
 *     below step-rec's 0x4233e800: not cleared at start-up, set on first use (magic word). */
SECTIONS
{
  .cave_a 0x4018d918 : { *(.text.store) }
  .cave_b 0x40167c50 : { *(.text.song_tick_c) *(.text.next_row) }
  .cave_c 0x401696a0 : { *(.text.act) *(.text.init) }
  .cave_d 0x401699a8 : { *(.text.reply) *(.text.queue) }
  .cave_e 0x4016aa28 : { *(.text.load) *(.text.unpack) }
  .cave_f 0x40185f48 : { *(.text.song_sysex) *(.text.requests) }
  .cave_g 0x40186238 : { *(.text.answer) *(.text.queue_next) *(.text.song_tick) }
  .cave_h 0x40189618 : { *(.text.enter_row) *(.rodata*) *(.text*) }
  .ram 0x4233d000 (NOLOAD) : { *(.bss*) *(COMMON) *(.data*) }
  /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
}

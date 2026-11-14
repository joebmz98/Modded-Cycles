/* Song mode (notes/74 §9-10), in freed sprite masks (tools/sprites.py, free in REGISTRY.md on 14/11/2026):
 *   - one 41x41 mask (328 bytes), four 35x35 (280 bytes), five 34x34 (272 bytes) and one 48x22 (192 bytes): the code
 *     and the router entry;
 *   - the variables in the free hole above the OS's BSS (0x423380b0..0x4233efff, notes/56 §3.5.2), at 0x4233c000,
 *     below step-rec's 0x4233e800: not cleared at start-up, set on first use (magic word). */
SECTIONS
{
  .cave_a 0x4018d918 : { *(.text.store) }
  .cave_b 0x40167c50 : { *(.text.song_tick_c) }
  .cave_c 0x401696a0 : { *(.text.act) *(.text.next_row) }
  .cave_d 0x401699a8 : { *(.text.reply) *(.text.queue) }
  .cave_e 0x4016aa28 : { *(.text.load) *(.text.unpack) }
  .cave_f 0x40185f48 : { *(.text.song_sysex) *(.text.requests) }
  .cave_g 0x40186238 : { *(.text.answer) *(.text.queue_next) *(.text.song_tick) }
  .cave_h 0x40189618 : { *(.text.enter_row) *(.rodata*) }
  .cave_i 0x4018af88 : { *(.text.apply_lanes) }
  .cave_j 0x4018b1a8 : { *(.text.store_lane) }
  .cave_k 0x40152d38 : { *(.text.init) *(.text*) }
  .ram 0x4233c000 (NOLOAD) : { *(.bss*) *(COMMON) *(.data*) }
  /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
}

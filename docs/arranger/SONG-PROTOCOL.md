# Song mode SysEx protocol, v1

Spoken by the Cycles Arranger (`docs/arranger/index.html`) and by the `song-mode` tweak of this fork's OS
(`tools/machines/song/song.c`, notes/74). The arranger's "Mock device" target (`class MockDevice`) answers the same way
as the firmware, for testing without hardware.

## Framing

```
request:  F0 00 20 3C 0E 00 cmd        <body, 7-bit packed> F7
reply:    F0 00 20 3C 0E 00 (cmd|0x40) <status, body, 7-bit packed> F7
```

`0E` is a product byte the Model:Cycles OS leaves free in its SysEx router (`0x40081300`, table `0x40148d08`); the
tweak puts song mode's entry there (notes/74 §8.1). The router hands the message, its length and the port to the
handler. Replies go back over **USB only** (port 2, `0x40003396`); a message received on MIDI IN is acted on, without
an answer.

7-bit packing, Elektron's: for each group of up to 7 bytes, one byte holds their top bits (first byte in bit 6), then
the 7 bytes with the top bit cleared.

## Commands

| Cmd | Name   | Request body | Reply body (status first) |
|-----|--------|--------------|---------------------------|
| 0   | INFO   | none         | `0, protoVer = 1, maxRows = 128` |
| 1   | WRITE  | song         | `status`; song mode on |
| 2   | READ   | none         | `status, song` |
| 3   | PLAY   | `row`        | `status`; the song is armed at that row: stopped, the row's pattern loads at once and PLAY on the machine starts the song; playing, it switches at the end of the current loop |
| 4   | STOP   | none         | `status`; song mode off |
| 5   | STATUS | none         | `0, playing, row, repeat, songMode` |
| 6   | MODE   | `0` or `1`   | `status` |

Status: `0` ok, `2` bad length, `3` too many rows, `4` pattern above 95 or 0 repeats, `5` no song, `0x7F` unknown command.

## Song body

```
ver (= 1)
nameLen (0..16), name[nameLen]   ASCII
rowCount                         0..128
loopOn, loopStart, loopEnd       row indices; a loop outside the rows is ignored
rows[rowCount] x 6 bytes:
  pattern     0..95  (A01..F16, Program Change numbering)
  repeats     1..255 (times the pattern plays through)
  muteMask    bit n = track n+1 muted
  flags       bit0 = tempo present
  tempoHi, tempoLo   u16 big-endian, 1/120 BPM; 0 when flags bit0 is clear
```

A row's tempo stays until another row sets one. Without a loop, the last row's pattern keeps looping.

## How the firmware plays it (notes/74 §4, §9)

The engine runs in the UI task's 30 Hz tick (hook at `0x400081ea`). While the sequencer plays, it counts the loops of
the pattern (the step counter `0x40a78840` going down). When a row's last loop begins, it writes the next row's
pattern to the pattern chain with `0x40055cd6`, the function an incoming Program Change calls, a whole loop before
the sequencer reads it on the last step. When a row begins, it sets the six mutes (`0x4001381c`, as CC 94 does) and
the tempo if the row has one (`0x4000c846`, as the TEMPO menu does).

| What | Where (OS 1.13) |
|---|---|
| SysEx router, table of products | `0x40081300`, `0x40148d08` |
| USB send of raw bytes | `0x40003396(n, bytes)` |
| Set pattern chain (what Program Change calls) | `0x40055cd6(pairs, count)`, pairs = `{0x406fa040 + p*30710, 0x409c9c80 + p*7094}` |
| Chain / index / length | `0x40a7863c` (64 pairs) / `0x40a78634` / `0x40a78638` |
| Arming on the last step, swap at the wrap | `0x4005559a..0x40055ad8`, `0x4005563e..0x40055698` |
| Sequencer playing, step counter | `0x40a7883c`, `0x40a78840` |
| Mute a track; set the tempo | `0x4001381c(project, track, muted, 0)`; `0x4000c846(project, tempo × 120)` |
| The project | `0x4000eb90(0x400cf866())` |

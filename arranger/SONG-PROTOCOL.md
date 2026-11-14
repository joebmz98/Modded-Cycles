# Song mode SysEx protocol, v1 (proposal for the Modded Cycles fork)

Cycles Arranger (`arranger/index.html`) already speaks this protocol. Its "Mock device" target implements the device side in
JavaScript (`class MockDevice` in `arranger/index.html`), so the firmware can be checked against it byte for byte.

## Framing

Same framing as Elektron Transfer, which the OS already decodes (see Modded Cycles `notes/37-flash-rapide-usb.md`):

```
F0 00 20 3C 10 00  <payload, 7-bit packed>  F7
```

7-bit packing: for each group of up to 7 bytes, one byte holds their top bits (first byte -> bit 6), followed by the
7 bytes with the top bit cleared.

- Request payload: `seqHi seqLo 00 00 cmd body...`
- Reply payload:   `seqHi seqLo reqSeqHi reqSeqLo (cmd|0x80) status body...`

Commands are offsets from a base `B` (default `0x70`). Change it once you have mapped which command IDs the
Cycles OS dispatcher leaves unused. The arranger lets you set B in its settings.

| Cmd   | Name   | Request body | Reply body after `status` |
|-------|--------|--------------|---------------------------|
| B+0   | INFO   | none         | `protoVer (1), maxRows`   |
| B+1   | WRITE  | song         | none                      |
| B+2   | READ   | none         | song                      |
| B+3   | PLAY   | `row`        | none                      |
| B+4   | STOP   | none         | none                      |
| B+5   | STATUS | none         | `playing, row, repeat, songMode` |
| B+6   | MODE   | `0` or `1`   | none                      |

Status codes: `0` ok, `1` busy, `2` bad length, `3` too many rows, `4` pattern > 95, `5` song mode off or no song,
`0x7F` unknown command.

## Song body

```
ver (=1)
nameLen, name[nameLen]          ASCII, up to 16
rowCount                        up to maxRows (arranger assumes 128)
loopOn, loopStart, loopEnd      row indices
rows[rowCount] x 6 bytes:
  pattern     0..95  (A01..F16, same numbering as Program Change)
  repeats     1..255 (times the pattern plays through)
  muteMask    bit n = track n+1 muted
  flags       bit0 = tempo present
  tempoHi, tempoLo   u16 big-endian, 1/120 BPM (the unit at 0x40149310, notes/38). 0 when flags bit0 is clear
```

Tempo carries forward: a row without a tempo keeps the tempo already playing.

## Behaviour the firmware needs

1. Keep the song table in SDRAM (about 800 bytes for 128 rows). Re-sending it each session is fine for v1.
2. At the end of each loop of the playing pattern, count `repeats`. At the start of the last loop's last step, queue
   the next row's pattern using the same function that Program Change receive calls, so the change lands on the
   boundary as it does from PC.
3. On entering a row: apply `muteMask` to the six tracks, and set the tempo if flags bit0 is set.
4. After `loopEnd`, go to `loopStart` when `loopOn` is set. Otherwise stop after the last row.
5. Reply to STATUS fast enough for polling every 250 ms.

## Firmware addresses already known (OS 1.13, Modded Cycles notes)

| What | Where |
|------|-------|
| SysEx router (Cycles) | `0x40081348`, table `0x40148d08` (notes/15) |
| Current pattern | `*(0x40a7887c) + 30706` (notes/32) |
| Pattern bank | `0x406fa040 + pattern * 30710` (notes/32) |
| UI pattern-select state | `UIStates` (`0x400cf9a8`) +389 (notes/34, 73) |
| Tempo, 1/120 BPM | `0x40149310` (notes/38) |
| 30 Hz UI tick | `0x400081e4` (notes/73) |
| Free space | sprite-mask registry, `tools/registry.py` (notes/52) |

| Set pattern chain (what Program Change calls) | `0x40055cd6(pairs, count)`, pairs = `{0x406fa040 + p*30710, 0x409c9c80 + p*7094}` (notes/74) |
| Chain / index / length | `0x40a7863c` (64 pairs) / `0x40a78634` / `0x40a78638` (notes/74) |
| Arming on the last step, swap at the wrap | `0x4005559a..0x40055ad8`, `0x4005563e..0x40055698` (notes/74) |
| Step counter, current pattern pointer | `0x40a78840`, `0x40a7887c` (notes/74) |

The next row's pattern must be written to the chain before the last step of the playing pattern (notes/74 §4).

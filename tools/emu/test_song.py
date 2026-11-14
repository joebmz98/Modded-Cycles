"""Song mode, stage 1 (tweak song-mode, notes/74 §9): proof in Unicorn on the OS's own code.

What runs for real: the OS's SysEx router (0x400812f6) dispatching our messages to song_sysex through the entry the
tweak writes in its table; our whole engine; the OS's set-chain function 0x40055cd6. What is stubbed, with every call
recorded: the USB send (0x40003396), the mute and tempo setters (0x4001381c, 0x4000c846), the two calls that find the
project (0x400cf866, 0x4000eb90) and the function the tick hook replaced (0x400d0b12, whose d0 must come back). The
sequencer is simulated: a step counter (0x40a78840) that wraps every LEN steps, and at each wrap the pattern becomes
entry 0 of the chain, which must have been written before the last step (notes/74 §4).

    python3 tools/emu/test_song.py --cycles firmware/model-cycles_OS1.13.syx [--with id,id,...]
"""
import argparse
import json
import pathlib
import struct
import sys

from unicorn import Uc, UC_ARCH_M68K, UC_MODE_BIG_ENDIAN, UC_HOOK_CODE
from unicorn import m68k_const as mk

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import build                          # noqa: E402
import test_sdvintage as T            # noqa: E402

BASE = build.BASE
DEV = HERE.parent.parent / "tweaks" / "model-cycles_OS1.13"
STACK, RET, MSG = 0x90008000, 0x90000000, 0x42e00300
ROUTER, TICK_HOOK = 0x400812f6, 0x400081ea
USB_SEND, SET_MUTE, SET_TEMPO, UI_APP, PROJECT, TICK_NEXT, SET_CC = (
    0x40003396, 0x4001381c, 0x4000c846, 0x400cf866, 0x4000eb90, 0x400d0b12, 0x40082cda)
PLAYING, STEP, CHAIN, CHAIN_LEN, PENDING = 0x40a7883c, 0x40a78840, 0x40a7863c, 0x40a78638, 0x40a78920
PAT_BANK, PAT_SIZE = 0x406fa040, 30710
FAKE_PROJECT, TICK_D0 = 0x42f00000, 0x1234
P = 0x0e
LEN = 16


def pack7(b):
    out = []
    for i in range(0, len(b), 7):
        g = b[i:i + 7]
        out.append(sum(((x >> 7) & 1) << (6 - j) for j, x in enumerate(g)))
        out += [x & 0x7f for x in g]
    return out


def unpack7(b):
    out = []
    for i in range(0, len(b), 8):
        top = b[i]
        out += [x | (((top >> (6 - j)) & 1) << 7) for j, x in enumerate(b[i + 1:i + 8])]
    return out


def song_body(name, rows, loop=(0, 0, 0)):
    body = [1, len(name), *name.encode(), len(rows), *loop]
    for pat, reps, mutes, tempo in rows:
        t = round(tempo * 120) if tempo else 0
        body += [pat, reps, mutes, 1 if tempo else 0, t >> 8, t & 0xff]
    return body


class Rig:
    def __init__(self, image, syms):
        self.syms = syms
        self.uc = uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
        uc.ctl_set_cpu_model(mk.UC_CPU_M68K_CFV4E)
        uc.mem_map(0x40000000, 0x03000000)
        uc.mem_write(BASE, bytes(image))
        uc.mem_map(0x90000000, 0x10000)
        uc.mem_write(RET, b"\x4e\x71" * 2)
        self.sent, self.mutes, self.tempos, self.ccs, self.chain_writes = [], [], [], [], 0
        stubs = {USB_SEND: self._usb, SET_MUTE: self._mute, SET_TEMPO: self._tempo,
                 UI_APP: lambda a: 0x42f00100, PROJECT: lambda a: FAKE_PROJECT, TICK_NEXT: lambda a: TICK_D0,
                 SET_CC: self._cc}
        for addr, fn in stubs.items():
            uc.hook_add(UC_HOOK_CODE, self._stub(fn), begin=addr, end=addr)
        uc.hook_add(UC_HOOK_CODE, self._count_chain, begin=0x40055cd6, end=0x40055cd6)

    def rd(self, a, n=4):
        return int.from_bytes(self.uc.mem_read(a, n), "big")

    def wr(self, a, v, n=4):
        self.uc.mem_write(a, (v & ((1 << 8 * n) - 1)).to_bytes(n, "big"))

    def _stub(self, fn):
        def hook(uc, addr, size, _):
            sp = uc.reg_read(mk.UC_M68K_REG_A7)
            args = [self.rd(sp + 4 * i) for i in range(1, 5)]
            r = fn(args)
            if r is not None:
                uc.reg_write(mk.UC_M68K_REG_D0, r)
            uc.reg_write(mk.UC_M68K_REG_PC, self.rd(sp))
            uc.reg_write(mk.UC_M68K_REG_A7, sp + 4)
        return hook

    def _usb(self, a):
        self.sent.append(bytes(self.uc.mem_read(a[1], a[0])))

    def _mute(self, a):
        assert a[0] == FAKE_PROJECT and a[3] == 0
        self.mutes.append((a[1], a[2]))

    def _tempo(self, a):
        assert a[0] == FAKE_PROJECT
        self.tempos.append(a[1])

    def _cc(self, a):
        self.ccs.append((a[0], a[1], a[2], self.rd(CHAIN)))

    def _count_chain(self, *_):
        self.chain_writes += 1

    def call(self, fn, *args):
        sp = STACK
        for a in reversed(args):
            sp -= 4
            self.wr(sp, a)
        sp -= 4
        self.wr(sp, RET)
        self.uc.reg_write(mk.UC_M68K_REG_A7, sp)
        self.uc.emu_start(fn, RET, count=2_000_000)
        return self.uc.reg_read(mk.UC_M68K_REG_D0)

    def sysex(self, cmd, body=(), port=2):
        """One message through the OS's router; the reply decoded, or None."""
        msg = bytes([0xf0, 0x00, 0x20, 0x3c, P, 0x00, cmd, *pack7(list(body)), 0xf7])
        self.uc.mem_write(MSG, msg)
        n = len(self.sent)
        self.call(ROUTER, MSG, len(msg), port, 0)
        if len(self.sent) == n:
            return None
        r = self.sent[-1]
        assert r[:7] == bytes([0xf0, 0, 0x20, 0x3c, P, 0, cmd | 0x40]) and r[-1] == 0xf7, r.hex()
        return unpack7(list(r[7:-1]))

    def tick(self):
        return self.call(self.syms["song_tick"])


def play(rig, loops, ticks_per_step=1):
    """The simulated sequencer: returns the program of each pattern loop played, and the late chain writes."""
    cur = (rig.rd(CHAIN) - PAT_BANK) // PAT_SIZE
    played, late, step, n = [cur], 0, 0, 0
    rig.wr(PLAYING, 1)
    while len(played) < loops:
        rig.wr(STEP, step)
        if n % ticks_per_step == 0:
            before = rig.chain_writes
            rig.tick()
            if step == LEN - 1 and rig.chain_writes != before:
                late += 1                            # written during the last step: too late for this wrap
        n += 1
        step += 1
        if step == LEN:
            step = 0
            cur = (rig.rd(CHAIN) - PAT_BANK) // PAT_SIZE
            played.append(cur)
    return played, late


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cycles", required=True, help="model-cycles_OS1.13.syx (official)")
    ap.add_argument("--with", dest="with_", default="", help="other tweaks of the OS to apply first, comma-separated")
    args = ap.parse_args()
    stock = T.main_os_from_syx(args.cycles)
    _, tweaks = build.load_catalog()["model-cycles_OS1.13"]
    chosen = [tweaks[i] for i in args.with_.split(",") if i] + [tweaks["song-mode"]]
    image, _ = build.apply_writes(stock, chosen)
    song = tweaks["song-mode"]
    syms = {k: int(v, 16) for k, v in song["symbols"].items()}
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + msg)
        ok &= bool(cond)

    hook = image[TICK_HOOK - BASE:TICK_HOOK - BASE + 6]
    check(hook == struct.pack(">HI", 0x4eb9, syms["song_tick"]), "the 30 Hz tick calls song_tick")
    rig = Rig(image, syms)
    rig.wr(PLAYING, 0)
    rig.wr(PENDING, 0)

    r = rig.sysex(0)
    check(r == [0, 2, 128, 8], f"INFO through the OS's router (protocol 2, 128 rows, 8 lanes): {r}")
    check(rig.sysex(0, port=4) is None, "no reply on another port than USB (2)")
    bad = song_body("X", [(96, 1, 0, None)])
    check(rig.sysex(1, bad) == [4], "WRITE with pattern 96 refused (status 4)")
    rows = [(0, 2, 0b000011, None), (1, 1, 0, None), (3, 3, 0b100000, 130.0), (1, 2, 0b000001, None)]
    body = song_body("Night Drive", rows)
    check(rig.sysex(1, body) == [0], f"WRITE of {len(rows)} rows ({len(body)} bytes) accepted")
    r = rig.sysex(2)
    check(r and r[0] == 0 and r[1:] == body, "READ gives back the song byte for byte")
    check(rig.tick() == TICK_D0, "song_tick returns the d0 of the call it replaced")

    # lanes: track 1 Sweep (CC 18) ramps 0 -> 127 over row 2 (one loop) and holds 100 over row 3; FX Delay Feedback
    # (CC 86, target 6) falls 64 -> 0 over row 4 (two loops); nothing in row 1
    no = 0xff
    lane0 = [0, 6 - 6, 18, 4, no, no, 0, 127, 100, 100, no, no]
    lane1 = [1, 6, 86, 4, no, no, no, no, no, no, 64, 0]
    check(rig.sysex(7, lane0) == [0] and rig.sysex(7, lane1) == [0], "two LANE messages accepted")
    check(rig.sysex(7, [8, 0, 18, 0]) == [2], "a ninth lane is refused")
    rig.wr(PLAYING, 1)                                   # playing, so 0x40055cd6 only copies the chain
    check(rig.sysex(3, [0]) == [0], "PLAY from row 1")
    rig.tick()
    check(rig.rd(CHAIN_LEN) == 1 and rig.rd(CHAIN) == PAT_BANK, "the request writes A01 to the chain")
    rig.wr(PLAYING, 0)
    rig.tick()
    rig.mutes.clear()
    played, late = play(rig, 12)
    names = ["ABCDEF"[p // 16] + f"{p % 16 + 1:02}" for p in played]
    expect = [0, 0, 1, 3, 3, 3, 1, 1, 1, 1, 1, 1]
    check(played == expect, f"patterns played, one per loop: {' '.join(names)}")
    check(late == 0, "every next pattern is written before the last step of the loop")
    entries = [rig.mutes[i:i + 6] for i in range(0, len(rig.mutes), 6)]
    want = [[(t, (m >> t) & 1) for t in range(6)] for _, _, m, _ in rows]
    check(entries == want, f"each row sets the six mutes as it begins ({len(entries)} rows)")
    check(rig.tempos == [15600], f"tempo set once, at the row that has one: {rig.tempos}")
    pat = lambda c: (c - PAT_BANK) // PAT_SIZE
    sweep = [v for t, cc, v, ch in rig.ccs if (t, cc) == (0, 18)]
    ramp = sweep[:16]
    check(len(ramp) == 16 and ramp[0] == 0 and ramp[-1] == 127 and ramp == sorted(ramp),
          f"row 2: Sweep on track 1 ramps 0 -> 127 across its loop, one value per step: {ramp}")
    check(sweep[16:] == [100], f"row 3: Sweep holds 100, sent once over its three loops: {sweep[16:]}")
    fx = [v for t, cc, v, ch in rig.ccs if (t, cc) == (6, 86)]
    check(fx[0] == 64 and fx[-1] == 0 and fx == sorted(fx, reverse=True) and len(fx) > 16,
          f"row 4: FX Delay Feedback falls 64 -> 0 over its two loops ({len(fx)} values)")
    check(all(pat(ch) != 0 or (t, cc) != (0, 18) for t, cc, v, ch in rig.ccs), "no lane value in row 1, which has none")
    plen = rig.uc.mem_read(syms["plen"], 4)
    check(list(plen[:2]) == [LEN, LEN], f"pattern lengths learnt at their wraps: A01 {plen[0]}, A02 {plen[1]} steps")
    r = rig.sysex(5)
    check(r == [0, 1, 3, r[3], 1], f"STATUS: playing, row 4, song mode on: {r}")

    loop = song_body("Loop", rows, (1, 1, 2))
    check(rig.sysex(1, loop) == [0], "WRITE with a loop on rows 2-3")
    rig.wr(PLAYING, 1)
    rig.sysex(3, [0])
    rig.tick()
    rig.wr(PLAYING, 0)
    rig.tick()
    played, late = play(rig, 12, ticks_per_step=3)
    check(played == [0, 0, 1, 3, 3, 3, 1, 3, 3, 3, 1, 3], f"loop of rows 2-3, ticks every 3 steps: {played}")
    check(late == 0, "still written before the last step with a tick every 3 steps")
    check(rig.sysex(4) == [0], "STOP")
    rig.tick()
    check(rig.sysex(5)[1:2] == [0], "STATUS after STOP: not playing")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

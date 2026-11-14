"""Pattern chains in the stock OS: what Program Change calls, and how the sequencer walks the chain (notes/74).

Runs the OS's own code in Unicorn (ColdFire V4e), stock MAIN OS 1.13, no tweak:
  - 0x40055cd6(pairs, n), the "set chain" function an incoming Program Change ends in (with n = 1 there), called
    here with a chain of four (A01, A01, A02, A04) while the sequencer is playing;
  - the chain length getter 0x4005428a;
  - the swap code of the sequencer interrupt (0x4005563e..0x400556a0), six times with a change armed: the chain
    index must step 0, 1, 2, 3, then loop to 0, and the next pattern pointer must follow the entries.

This is the ground the Arranger song mode builds on: writing the chain before the last step is enough to choose
the next pattern (notes/74 §4, §5). The arming on the last step is read in code, not run here.

    python3 tools/emu/test_chain.py --cycles firmware/model-cycles_OS1.13.syx
"""
import argparse
import pathlib
import struct
import sys

from unicorn import Uc, UC_ARCH_M68K, UC_MODE_BIG_ENDIAN
from unicorn import m68k_const as mk

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import build                          # noqa: E402
import test_sdvintage as T            # noqa: E402

BASE = build.BASE
STACK, RET = 0x90008000, 0x90000000
BUF = 0x42e00000                      # scratch for the pairs passed to 0x40055cd6 (DDR, zero in the image)

SET_CHAIN, CHAIN_LEN = 0x40055cd6, 0x4005428a
SWAP, SWAP_END = 0x4005563e, 0x400556a0
IDX, LEN, CHAIN = 0x40a78634, 0x40a78638, 0x40a7863c
PLAYING, PENDING, NEXT_PAT = 0x40a7883c, 0x40a78920, 0x40a78880
PAT_BANK, PAT_SIZE = 0x406fa040, 30710
KIT_BANK, KIT_SIZE = 0x409c9c80, 7094


def pattern(p):
    return PAT_BANK + p * PAT_SIZE


def kit(p):
    return KIT_BANK + p * KIT_SIZE


class Rig:
    def __init__(self, main_os):
        self.uc = uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
        uc.ctl_set_cpu_model(mk.UC_CPU_M68K_CFV4E)
        uc.mem_map(0x40000000, 0x03000000)          # image, then the OS's BSS and heap in DDR
        uc.mem_write(BASE, bytes(main_os))
        uc.mem_map(0x90000000, 0x10000)
        uc.mem_write(RET, b"\x4e\x71" * 2)          # landing pad for calls

    def rd(self, a):
        return struct.unpack(">l", self.uc.mem_read(a, 4))[0]

    def wr(self, a, v):
        self.uc.mem_write(a, struct.pack(">L", v & 0xffffffff))

    def call(self, fn, *args):
        sp = STACK
        for a in reversed(args):
            sp -= 4
            self.wr(sp, a)
        sp -= 4
        self.wr(sp, RET)
        self.uc.reg_write(mk.UC_M68K_REG_A7, sp)
        self.uc.emu_start(fn, RET, count=100000)
        return self.uc.reg_read(mk.UC_M68K_REG_D0)

    def swap(self):
        self.wr(PENDING, 1)
        self.uc.emu_start(SWAP, SWAP_END, count=1000)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cycles", required=True, help="model-cycles_OS1.13.syx (official)")
    args = ap.parse_args()
    rig = Rig(T.main_os_from_syx(args.cycles))
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + msg)
        ok &= bool(cond)

    progs = [0, 0, 1, 3]                            # A01, A01, A02, A04
    for i, p in enumerate(progs):
        rig.wr(BUF + 8 * i, pattern(p))
        rig.wr(BUF + 8 * i + 4, kit(p))
    rig.wr(PLAYING, 1)
    rig.wr(PENDING, 0)
    rig.call(SET_CHAIN, BUF, len(progs))
    check(rig.rd(LEN) == 4 and rig.rd(IDX) == -1, f"chain set while playing: length {rig.rd(LEN)}, index {rig.rd(IDX)}")
    check(all(rig.rd(CHAIN + 8 * i) == pattern(p) for i, p in enumerate(progs)), "chain holds the four pattern pointers")
    check(rig.call(CHAIN_LEN) == 4, "0x4005428a returns the chain length")

    seen = []
    for _ in range(6):
        rig.swap()
        seen.append((rig.rd(IDX), (rig.rd(NEXT_PAT) - PAT_BANK) // PAT_SIZE, rig.rd(PENDING)))
    print("swaps (index, next program, armed):", seen)
    check([s[0] for s in seen] == [0, 1, 2, 3, 0, 1], "index steps 0, 1, 2, 3, then loops to 0")
    check([s[1] for s in seen] == [0, 0, 1, 3, 0, 0], "next pattern follows the chain entries")
    check(all(s[2] == 0 for s in seen), "the armed flag is consumed by each swap")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

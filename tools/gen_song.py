#!/usr/bin/env python3
"""Writes tweaks/model-cycles_OS1.13/93-song-mode.json: song mode, stage 1 (notes/74 §8-9).

A song (rows of pattern, repeats, mutes, tempo) is sent over SysEx by the Cycles Arranger (docs/arranger/) and played
by the Model:Cycles itself: the engine writes the pattern chain (0x40055cd6, what an incoming Program Change calls) one
loop ahead and applies each row's mutes and tempo as it begins. The song lives in RAM (stage 1): it is lost at power
off.

tools/machines/song/: song.c, linked by song.ld into freed sprite masks (tools/sprites.py); its variables live in the
free hole above the OS's BSS. The writes on the OS are HOOKS below (the 30 Hz tick) and ROUTE (our entry in the SysEx
router's table); every write carries its stock bytes, checked on the official MAIN OS.

    python3 tools/gen_song.py --cycles firmware/model-cycles_OS1.13.syx [--check]
"""
import argparse
import json
import pathlib
import struct
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "emu"))

import build                       # noqa: E402
import gen_sdvintage_exact as gx   # noqa: E402
import sprites                     # noqa: E402
import test_sdvintage as T         # noqa: E402

SRC = HERE / "machines" / "song"
DEV = HERE.parent / "tweaks" / "model-cycles_OS1.13"
OUT = DEV / "93-song-mode.json"
BASE = gx.BASE
SONG_P = 0x0e                                   # product byte of our SysEx messages: F0 00 20 3C 0E 00 cmd ...
ROUTER_TABLE = 0x40148d08                       # 18 pointers, one per product byte (notes/74 §8.1)
# sections of song.ld: freed mask -> size (free in REGISTRY.md on 14/11/2026)
CAVES = {
    ".cave_a": (0x4018d918, 328),
    ".cave_b": (0x40167c50, 280),
    ".cave_c": (0x401696a0, 280),
    ".cave_d": (0x401699a8, 280),
    ".cave_e": (0x4016aa28, 280),
    ".cave_f": (0x40185f48, 272),
    ".cave_g": (0x40186238, 272),
    ".cave_h": (0x40189618, 272),
    ".cave_i": (0x4018af88, 272),
    ".cave_j": (0x4018b1a8, 272),
    ".cave_k": (0x40152d38, 192),
}
RAM = (0x4233c000, 0x4233e000)                  # variables (.ram of song.ld), below step-rec's 0x4233e800
# (address, stock bytes, symbol, opcode, role)
HOOKS = (
    (0x400081ea, "4eb9400d0b12", "song_tick", 0x4eb9,
     "interface tick, 30 Hz (message 5): jsr 0x400d0b12 -> jsr song_tick, which calls it and returns its d0"),
)
SYMBOLS = ("song_sysex", "song_tick", "song_tick_c", "song_route", "song", "magic", "mode", "running", "row", "rep",
           "busy", "req_play", "req_stop", "pair", "buf", "lanes", "nlanes", "plen")   # for tools/emu/test_song.py


def compile_song():
    """Linked code (ELF): {section: (address, bytes)}, symbols, [(name, address, size)] of every allocated section."""
    with tempfile.TemporaryDirectory() as d:
        d = pathlib.Path(d)
        obj, elf = d / "song.o", d / "song.elf"
        gx.run([gx.CROSS + "gcc", *gx.CFLAGS, "-c", str(SRC / "song.c"), "-o", str(obj)])
        gx.run([gx.CROSS + "ld", "-T", str(SRC / "song.ld"), "--no-warn-rwx-segments", "-o", str(elf), str(obj)])
        syms = {}
        for line in gx.run([gx.CROSS + "nm", str(elf)]).splitlines():
            p = line.split()
            if len(p) == 3:
                syms[p[2]] = int(p[0], 16)
        heads = gx.run([gx.CROSS + "objdump", "-h", str(elf)])
        allocated = []
        for line in heads.splitlines():
            p = line.split()
            if len(p) > 3 and p[1].startswith(".") and int(p[2], 16):
                allocated.append((p[1], int(p[3], 16), int(p[2], 16)))
        secs = {}
        for name in CAVES:
            out = d / (name.strip(".") + ".bin")
            gx.run([gx.CROSS + "objcopy", "-O", "binary", "-j", name, str(elf), str(out)])
            secs[name] = (int(heads.split(name)[1].split()[2], 16), out.read_bytes())
    for name, vma, size in allocated:
        if name in CAVES:
            continue
        if name != ".ram" or not (RAM[0] <= vma and vma + size <= RAM[1]):
            raise SystemExit(f"!! section {name} ({size} bytes at {vma:#x}) outside the caves and the RAM window")
    return secs, syms, allocated


def build_tweak(stock):
    secs, syms, allocated = compile_song()
    writes, used = [], {}
    for name, (mask, room) in CAVES.items():
        addr, code = secs[name]
        if addr != mask or len(code) > room:
            raise SystemExit(f"!! {name}: {len(code)} bytes at {addr:#x}, room {room} at {mask:#x}")
        kept = sprites.kept_of(mask)
        if stock[mask - BASE:mask - BASE + room] != stock[kept - BASE:kept - BASE + room]:
            raise SystemExit(f"!! {name}: mask {mask:#x} differs from the kept mask {kept:#x}")
        writes.append({"off": addr - BASE, "old": stock[addr - BASE:addr - BASE + len(code)].hex(), "new": code.hex()})
        writes.append(sprites.redirect_write(mask))
        used[name] = len(code)
    for va, old_hex, sym, op, _ in HOOKS:
        old = bytes.fromhex(old_hex)
        if stock[va - BASE:va - BASE + len(old)] != old:
            raise SystemExit(f"!! unexpected stock bytes at {va:#x}")
        writes.append({"off": va - BASE, "old": old_hex, "new": struct.pack(">HI", op, syms[sym]).hex()})
    route = ROUTER_TABLE + 4 * SONG_P
    if stock[route - BASE:route - BASE + 4] != bytes(4):
        raise SystemExit(f"!! the router's entry for product {SONG_P:#x} is not free")
    writes.append({"off": route - BASE, "old": "00000000", "new": struct.pack(">I", syms["song_route"]).hex()})
    writes.sort(key=lambda w: w["off"])
    ram = next(size for name, _, size in allocated if name == ".ram")
    total = sum(used.values())
    tweak = {
        "id": "song-mode",
        "order": 93,
        "name": "Mode morceau (étape 1) : un morceau envoyé par SysEx, joué par la machine, avec ses lignes de CC",
        "description": [
            "Le Cycles Arranger (docs/arranger/) envoie un morceau (lignes : pattern, répétitions, mutes, tempo) par",
            f"SysEx (F0 00 20 3C {SONG_P:02X} 00 commande …, docs/arranger/SONG-PROTOCOL.md). Séquenceur en lecture,",
            "le moteur compte les boucles du pattern et écrit la chaîne de patterns (0x40055cd6, ce qu'appelle un",
            "Program Change reçu) une boucle à l'avance ; au début de chaque ligne, il pose ses mutes et son tempo. Le",
            "morceau est en mémoire vive (étape 1) : perdu à l'extinction. Lignes de CC (protocole v2, commande 7) :",
            "par ligne une valeur de début et de fin, en rampe sur toutes ses boucles, appliquée par 0x40082cda (ce",
            "qu'appelle un CC reçu) ; la longueur de chaque pattern est apprise à son premier retour au début.",
            f"Code dans onze masques de sprites libérés (tools/sprites.py) : {total} o ; {ram} o de variables en",
            f"{RAM[0]:#x}, au-dessus du BSS. Entrée {SONG_P:#x} de la table du routeur SysEx ({ROUTER_TABLE:#x}).",
            "Généré par tools/gen_song.py, notes/74.",
        ],
        "device": "Model:Cycles",
        "os": "1.13",
        "section": 3,
        "symbols": {n: f"{syms[n]:#x}" for n in SYMBOLS},
        "writes": writes,
    }
    return tweak, used, ram


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cycles", required=True, help="official model-cycles_OS1.13.syx")
    ap.add_argument("--check", action="store_true", help="checks that the committed JSON is up to date")
    args = ap.parse_args()
    stock = T.main_os_from_syx(args.cycles)
    if build.sha(stock) != json.loads((DEV / "device.json").read_text(encoding="utf-8"))["section_sha256"]:
        raise SystemExit("!! not the official MAIN OS 1.13")
    tweak, used, ram = build_tweak(stock)
    build.apply_writes(stock, [tweak])                # the stock bytes match
    text = json.dumps(tweak, indent=1) + "\n"
    print("  " + ", ".join(f"{n} {used[n]}/{CAVES[n][1]}" for n in CAVES) + f" bytes; RAM {ram} bytes")
    if args.check:
        ok = OUT.exists() and OUT.read_text(encoding="utf-8") == text
        print(f"  {OUT.name} {'is up to date' if ok else 'DOES NOT MATCH (another GCC?)'}")
        raise SystemExit(0 if ok else 1)
    OUT.write_text(text, encoding="utf-8")
    print(f"  written: {OUT.relative_to(HERE.parent)} ({len(tweak['writes'])} writes)")


if __name__ == "__main__":
    main()

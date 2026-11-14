# Cycles Arranger

A song arranger for the Model:Cycles in one web page (`index.html`). Open it in Chrome, Edge or Opera on a desktop
computer: it needs Web MIDI. Nothing is uploaded anywhere; the song is kept in the browser and can be saved as a
`.cycles.json` file.

- **Live playback, any firmware (stock or Modded Cycles):** the page is the MIDI clock. It sends each next
  pattern as a Program Change a few steps before the pattern ends, plus track mutes (CC 94) and CC lanes from the
  Model:Cycles MIDI map. On the Cycles: CONFIG › MIDI › SYNC, turn on CLK IN and PCH IN, and match the PC channel.
- **Song mode on the device (experimental, this fork's OS):** "Send song" uploads the arrangement as one SysEx
  message and the Cycles plays it with no computer attached: patterns, repeats, mutes, tempo, loop. Kept until
  power-off. The built-in mock device answers like the firmware, for testing without hardware. Protocol:
  [`SONG-PROTOCOL.md`](SONG-PROTOCOL.md). Firmware: [`notes/74`](../../notes/74-arranger-mode-morceau.md).

The page is English only for now: the site's rule of English
and French side by side (docs/AGENTS.md) still has to be met before it can go upstream.

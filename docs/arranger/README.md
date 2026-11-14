# Cycles Arranger

A song arranger for the Model:Cycles in one web page (`index.html`). Open it in Chrome, Edge or Opera on a desktop
computer: it needs Web MIDI. Nothing is uploaded anywhere; the song is kept in the browser and can be saved as a
`.cycles.json` file.

- **Live playback, any firmware (stock or Modded Cycles):** the page is the MIDI clock. It sends each next
  pattern as a Program Change a few steps before the pattern ends, plus track mutes (CC 94) and CC lanes from the
  Model:Cycles MIDI map. On the Cycles: CONFIG › MIDI › SYNC, turn on CLK IN and PCH IN, and match the PC channel.
- **Song mode on the device (planned):** "Send song" uploads the arrangement as one SysEx message, so the Cycles
  plays it without a computer. This needs the song-mode firmware that this fork is working towards; until then
  the real device does not answer, and the built-in mock device stands in for testing. Protocol:
  [`SONG-PROTOCOL.md`](SONG-PROTOCOL.md). Firmware research: [`notes/74`](../../notes/74-arranger-mode-morceau.md).

Served with the fork's GitHub Pages at `/arranger/`. The page is English only for now: the site's rule of English
and French side by side (docs/AGENTS.md) still has to be met before it can go upstream.

# Custom voice packs — WORKING

Fully working on this XU7100. Your robot fetches a voice pack you build, from
this machine, over the LAN — no cloud, no root.

## The correct format (captured from the robot's real download)
- **ZIP** (NOT tar.gz — that was the upstream reference tool's mistake for this model)
- MP3s named **`01.mp3`, `02.mp3`, `04.mp3` …** at the archive ROOT (plain numbers,
  with gaps; NOT `C001.mp3`). The exact 75-file set is in `reference_official/`.
- Audio: **MP3, 44.1 kHz, mono, ~192 kbps**
- Served at a URL ending `.zip`: `http://<pc>:8781/smart/product/voice/custom.zip`
- Install command: DP 35, cmd 0x34, with a **leading flag byte** (see
  ../docs/COMMAND_PROTOCOL.md). languageId must be fresh (range ~8..30).

## Make your own
```bash
cp -r voice/reference_official voice/custom
# replace the numbered mp3s with your own (same names, same 44.1k/mono/192k format).
# to match format:  ffmpeg -i in.wav -ac 1 -ar 44100 -b:a 192k 01.mp3
./homerun voice voice/custom
```
Every prompt whose number you replace will speak your audio. To go back to a
normal voice, just re-select a language in the Smart Life app.

## Which number is which prompt?
`reference_official/NN.mp3` — play them to hear each prompt (they're in Spanish
in the reference). Replace only the ones you care about; leave the rest and the
robot keeps the official audio for those.

## How the format was found
The robot downloads official packs over HTTPS from a CloudFront CDN
(`euimagesd2h2yqnfpu4gl5.cdn5th.com/smart/product/voice/<id>.zip`). It does NOT
validate the CDN's TLS cert, so a transparent proxy on the LAN could read one
real download and reveal the exact ZIP structure. See docs/COMMAND_PROTOCOL.md.

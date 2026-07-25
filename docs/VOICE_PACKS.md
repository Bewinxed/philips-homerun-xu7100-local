# Custom voice packs

The robot speaks 75 prompts (powering on, start cleaning, returning to dock, bin full, and so on). This project can replace any of them with your own audio, served from your own machine over the LAN. No cloud account and no root access on the robot are needed.

## How the format was found

The install path was known from the community project [SinfreeX/Tuya-robots-custom-voice](https://github.com/SinfreeX/Tuya-robots-custom-voice), but the exact pack format for this model was not. The robot downloaded a pack but never activated it, which meant the archive layout or audio encoding was wrong.

The robot is on Wi-Fi, so a passive sniff sees nothing (the access point only delivers each client its own frames). To read the real download, the robot's traffic was routed through this machine with ARP spoofing and IP forwarding, then a transparent proxy read the download. The official pack comes over HTTPS from a CloudFront CDN, and the robot does not validate that CDN's certificate, so the proxy could read one real download in the clear. Triggering a language change in the vendor app produced a fresh 5 MB download to inspect.

That capture revealed the format the earlier attempts got wrong.

## The pack format

- A **ZIP** archive, not a tar.gz.
- MP3 files named `01.mp3`, `02.mp3`, `04.mp3`, and so on, at the archive root. There are 75 files with gaps in the numbering.
- Audio encoded as **MP3, 44.1 kHz, mono, about 192 kbps**.
- Served at a URL ending in `.zip`.

A pack built with those exact filenames and that audio format activates correctly. Any prompt number you leave out keeps the official audio, so you can replace only the prompts you care about.

## The install command

Install is a single Tuya datapoint write: DP 35, command `0x34`, carrying a full URL and an MD5. The robot fetches the ZIP from that URL itself.

The one detail specific to this robot is a **leading flag byte** before the language id. The upstream reference tool emits the language id first with no flag, which makes this robot misparse the frame, fall back to its own English pack, and never fetch the URL. With the flag byte in front, it downloads immediately. The full frame layout is in [COMMAND_PROTOCOL.md](COMMAND_PROTOCOL.md).

The language id has to change on each install or the robot treats it as a duplicate and skips the download. The valid range on this model is roughly 8 to 30.

To go back to a normal voice, re-select a language in the Philips or Smart Life app.

## The Voice Studio

The web UI has a Voice Studio tab that turns all of this into a workflow:

- Every one of the 75 prompts is listed with a plain-English label for what it means (the labels were mapped from the captured Spanish prompts, see `voice/prompts_es.json`).
- Each prompt has an editable script. Lines can carry ElevenLabs v3 audio tags, and there is a click-to-insert palette for them.
- ElevenLabs generates the audio per line, and ffmpeg normalizes it to the 44.1 kHz mono format the robot needs.
- One button builds the ZIP and installs it to the robot over the LAN, with progress reported back to the UI.

The generation settings (voice id, stability, similarity, speed) are adjustable. The ElevenLabs API key is read from `voice/eleven_key.txt` or the `ELEVENLABS_API_KEY` environment variable, and it is gitignored.

The scripts in this repo (`voice/lines_ar.json`) are written for a specific character voice. Replace them with whatever you like.

## Files

- `voice/lines_ar.json` is the editable script, keyed by prompt number.
- `voice/prompts_es.json` maps each prompt number to its original meaning.
- `backend/voice_studio.py` handles editing, generation, and the background install job.
- `backend/custom_voice.py` builds the ZIP, serves it over HTTP, and sends the install command.

Generated and captured audio is not committed. The official reference pack in particular is copyrighted. The scripts are enough to regenerate everything.

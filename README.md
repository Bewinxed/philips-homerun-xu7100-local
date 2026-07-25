![HomeRun Local](docs/banner.svg)

# HomeRun Local

Local control for the Philips HomeRun XU7100 robot vacuum. It talks to the robot directly over your LAN using the Tuya protocol, so cleaning, mapping, diagnostics, and custom voice packs all work without the cloud. There is a web UI, a JSON API, and a Home Assistant integration.

## Why this exists

The robot stopped returning to its dock about a year ago and got stuck on an old map. A factory reset did not help, and there was no local repair option. Instead of replacing it, I reverse-engineered how it talks on the network and built a controller that runs entirely on the LAN.

Along the way the original problem turned out to be mechanical, not a sensor fault. The full write-up is in [docs/ROOT_CAUSE.md](docs/ROOT_CAUSE.md). Short version: the dock ramp lip sat slightly proud of the floor, the bumper read it as a wall, and every failed dock made the robot think it had been kidnapped, which threw away the session map. A thin shim under the ramp fixed it.

## What it does

- **Direct LAN control.** Start, pause, stop, dock, and locate over Tuya 3.3 on port 6668. No cloud round-trip for control.
- **Live status.** State, battery, suction, water, current job, and faults, streamed to the UI over Server-Sent Events.
- **Interactive map.** The robot stores rooms as per-pixel ids with no polygons, so the map is decoded from the raster and the room outlines are traced from it. You can select rooms, set per-room suction and passes, rename, and merge.
- **Custom voice packs.** Replace any of the robot's 75 spoken prompts with your own audio, served from your machine over the LAN. Includes a Voice Studio that writes lines, generates them with ElevenLabs, and installs the pack to the robot. Details in [docs/VOICE_PACKS.md](docs/VOICE_PACKS.md).
- **Diagnostics.** Consumable wear, lifetime totals, mode toggles, and the decoded fault bitmap.
- **Home Assistant.** A custom component under `homeassistant/` exposes the vacuum entity.
- **Simulator.** With no `local_key` configured, the whole stack runs against an in-memory robot so you can develop against it.

## How it works

The robot runs on a Tuya Linux SDK board. Control datapoints travel over the LAN as small AES-encrypted frames, which is why direct control works without the cloud. The map is the exception: laser vacuums stream maps over Tuya P2P or the cloud rather than the LAN datapoint channel, so the stored map is fetched through the Tuya cloud API and rendered locally.

```
  web/app  (Svelte 5 + Tailwind)         Home Assistant
      |  REST + SSE                            |  REST
      v                                        v
  backend/server.py  (Flask)  ------  controller  ------  robot (LAN, tinytuya)
      |                                    |
      |  cloud map fetch                   |  stored-map decode + room tracing
      v                                    v
  Tuya cloud OpenAPI                   backend/map_vector.py
```

Key modules:

- `backend/controller.py` maps semantic actions to Tuya datapoints, with a real backend and a simulator behind one interface.
- `backend/voice_studio.py` and `backend/custom_voice.py` build and install voice packs.
- `backend/room_overrides.py` stores your renames and merges locally, since the robot will not apply those over the LAN.
- `backend/map_vector.py` traces room outlines from the raster.
- `backend/tuya_cloud.py` signs and calls the Tuya cloud OpenAPI for the stored map.

The command protocol, datapoint map, and voice frame format are documented in [docs/COMMAND_PROTOCOL.md](docs/COMMAND_PROTOCOL.md).

## Setup

You need Python 3.12, Node 22, and a Tuya IoT cloud project linked to the app account your robot is paired with.

```bash
# 1. Python deps
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 2. Configure
cp config.example.json config.json
#    fill in your device id, ip, and Tuya cloud client id/secret

# 3. Pull the robot's local key from your Tuya project
./getrobotkey            # runs the tinytuya wizard, writes robot_secrets.json

# 4. Build the web UI
cd web/app && npm install && npm run build && cd ../..

# 5. Run
./homerun start          # http://localhost:8787
```

With no `local_key` the server starts against the simulator, so you can try the UI before wiring up a real robot.

The `homerun` script is the entry point for everything else too: `homerun build`, `homerun cloud`, `homerun voice <folder>`, `homerun sniff`, and more. Run it with no known command to see the list.

## Home Assistant

Copy `homeassistant/custom_components/homerun_local` into your Home Assistant `custom_components` directory and point it at the backend URL. It surfaces the vacuum state, battery, and the start, stop, dock, and locate commands.

## Documentation

- [docs/COMMAND_PROTOCOL.md](docs/COMMAND_PROTOCOL.md) covers the datapoint map, navigation frames, and the voice frame family, verified on this robot.
- [docs/VOICE_PACKS.md](docs/VOICE_PACKS.md) covers how custom voices were reverse-engineered, the exact pack format, and the ElevenLabs Voice Studio.
- [docs/ROOT_CAUSE.md](docs/ROOT_CAUSE.md) covers the docking failure investigation.
- [docs/API_CONTRACT.md](docs/API_CONTRACT.md) covers the backend HTTP API.

## Safety and scope

This project is not affiliated with Philips or Tuya. It was built by observing traffic to and from one robot, so the datapoint numbers and command frames are specific to this model and firmware and may differ on yours. Some frames were confirmed by watching the robot move rather than from an official spec. Treat the undocumented datapoints as unsafe to write blindly, since one of them is plausibly a map reset.

Your secrets stay out of the repo. `config.json`, `robot_secrets.json`, the ElevenLabs key, and your home map are all gitignored. Copy the `.example` files and fill in your own.

## License

MIT. See [LICENSE](LICENSE).

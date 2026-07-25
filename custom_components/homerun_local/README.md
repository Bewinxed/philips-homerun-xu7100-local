# Philips HomeRun (Local) — Home Assistant integration

Local control of a Philips HomeRun XU7100 robot vacuum through the HomeRun Local
HTTP backend (`backend/server.py`). It talks only to that backend over your LAN,
so no cloud account is needed once the backend is up.

Provides a full expose of the robot as one device:

- **Vacuum**: start, pause, stop, return home, locate, fan speed, battery, and state.
- **Select**: water flow (Off / Low / Medium / High), which the vacuum entity does not cover.
- **Switches**: every mode toggle the robot reports (carpet boost, do-not-disturb, child lock, Y-pattern mop, vibration mop, custom mode, auto-empty dock). These are created from live diagnostics, so nothing is hardcoded to one firmware.
- **Number**: voice-prompt volume (0-100).
- **Buttons**: empty the bin, start a mapping run, and locate.
- **Sensors**: battery %, cleaned area (m²), cleaning time (min), status, and fault. Diagnostic sensors for the four consumables (side brush, main brush, filter, mop cloth, as percent remaining with hours-left as an attribute) and the lifetime totals (area, cleans, runtime).
- **Camera**: the robot's map PNG.

Everything runs through the backend, which owns the robot's single LAN connection, so Home Assistant never contends with the web UI for the socket.

## Requirements

The HomeRun Local backend must be running and reachable, e.g.:

```bash
python backend/server.py   # serves http://<host>:8787
```

## Install

1. Copy this folder into your Home Assistant configuration:

   ```
   <config>/custom_components/homerun_local/
   ```

   (`<config>` is where your `configuration.yaml` lives.)

2. Restart Home Assistant.

3. Go to **Settings → Devices & Services → Add Integration**, search for
   **"Philips HomeRun (Local)"**, and enter the backend **host** and **port**
   (default `8787`). The flow validates the connection by calling `/api/state`.

### HACS

This folder is a HACS-compatible custom integration. You can also add the
repository to HACS as a custom repository (category: Integration) and install it
from there.

## Options

After adding, use **Configure** on the integration to edit the list of fan
speeds offered by the vacuum (comma-separated). Default:
`quiet, normal, strong, max`.

## Notes

- Polls `GET /api/state` and `GET /api/diagnostics` every 5 seconds.
- The map camera returns nothing until the backend can produce a map
  (`GET /api/map` returns 404 until then) — this is expected before the cloud
  link and a laser scan exist.

# Philips HomeRun (Local) — Home Assistant integration

Local control of a Philips HomeRun XU7100 robot vacuum through the HomeRun Local
HTTP backend (`backend/server.py`). It talks only to that backend over your LAN,
so no cloud account is needed once the backend is up.

Provides:
- A **vacuum** entity (start / pause / stop / return home / locate / fan speed / battery / state)
- **Sensors**: battery %, cleaned area (m²), cleaning time (min), and a diagnostic status sensor
- A **camera** entity that shows the robot's live map PNG

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

- Polls `GET /api/state` every 5 seconds.
- The map camera returns nothing until the backend can produce a map
  (`GET /api/map` returns 404 until then) — this is expected before the cloud
  link and a laser scan exist.

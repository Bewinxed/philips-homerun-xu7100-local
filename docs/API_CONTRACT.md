# HomeRun Local — backend API contract

Base URL: `http://<host>:8787`

## State object (returned by /api/state and pushed by /api/events)
```json
{
  "source": "robot" | "sim",
  "connected": true,
  "state": "idle|cleaning|paused|returning|docked|charging|error",
  "battery": 82,               // int %, or null
  "fan": "normal",             // string level or null
  "water": "middle",           // string level or null
  "mode": "smart",
  "clean_area": 12,            // m2
  "clean_time": 18,           // minutes
  "fault": 0,
  "raw": { "<dp>": <value> },  // raw Tuya datapoints
  "last_update": 1712345678.0
}
```

## Endpoints
- `GET  /api/state` → State object
- `GET  /api/events` → text/event-stream, each event `data: <State object>`
- `POST /api/command` body `{"action":"start|pause|stop|home|locate"}` → `{ok:true}`
- `POST /api/fan`   body `{"level":"quiet|normal|strong|max"}` → `{ok:true}`
- `POST /api/water` body `{"level":"low|middle|high|closed"}` → `{ok:true}`
- `POST /api/dp`    body `{"dp":"3","value":"smart"}` → `{ok:true}` (raw escape hatch)
- `GET  /api/map` → image/png (latest map) or 404 `{ok:false,error}` if not available
- `GET  /api/map/meta[?force=1]` → `{ok, width, height, resolution_mm, origin:[x,y],
      charger:[x,y], robot:[x,y], rooms:[{id,name}], path_points, ts}`

Fan/water level enums come from the live state; treat them as strings, don't hardcode.
```
```

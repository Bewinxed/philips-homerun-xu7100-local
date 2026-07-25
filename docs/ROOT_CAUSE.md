# Root cause of the "won't return to base / map keeps resetting" problem

**Found 2026-07-25. Fixed with a folded receipt.**

## The defect
The leading lip of the charging dock's ramp sat slightly proud of the floor —
a step, not a slope. On approach the robot's front bumper contacted the vertical
face of the ramp tip instead of riding up it.

## Why it produced every symptom
```
ramp lip too abrupt
  -> bumper contact reads as an obstacle
    -> obstacle avoidance: hard reverse, re-approach
      -> infinite retry loop, never docks
        -> owner lifts the robot back to the dock
          -> "kidnapped" -> localisation lost -> session map DISCARDED
            -> robot reverts to last saved map
              -> "stuck on the old map" for ~a year
```

Critically the robot reported **`fault=0` throughout**. Nothing was broken; the
bumper was working correctly and honestly reporting "wall ahead". No error code
was ever going to surface this.

## Proof
Placing a folded receipt under the ramp tip (changing nothing else) let it dock
on the first attempt:
```
status=charging   batt=76%   fault=0   charge_flag=False
```

## Corrected assumption
Earlier working theory was LDS/lidar degradation, based on the robot announcing
"scanning the room to know where I am" on every resume and spin-scanning every
~2 m. That is now believed to be a **consequence, not a cause**: because every
session map was discarded at dock time, the robot never had a persisted map to
relocalise against, so it re-scanned from scratch every time. Expect this to
improve substantially once one map successfully commits. The lidar may be fine.

## Permanent fix
Replace the receipt with a stable feathered shim (stiff plastic / aluminium tape
/ thin card, taped down) at the ramp tip. Check why the lip sits proud: dock
rubber feet, uneven floor, or a warped ramp. Push the dock flush to a wall so it
cannot creep backwards. Keep the approach clear of carpet — the robot crawls on
carpet and cannot build the traction/momentum needed to mount the ramp.

## Still open
- Mapping command DP is unidentified (one of the undocumented vendor DPs:
  25, 27, 37, 39, 45, 47, 48, 101, 107, 108). Find it with `./homerun sniff`
  while pressing "start mapping" in the vendor app. Do NOT blind-write these —
  one is plausibly `map_reset`.
- Once a map persists: it renders in the web UI + HA, and `pile_x/pile_y` from
  the map header unlocks the `0x16` goto-coordinate command as a dock-return
  fallback. Command framing is already verified on this robot (see
  docs/COMMAND_PROTOCOL.md).

## 2026-07-25 later: manual drive + telemetry findings

- **Manual drive (DP 12 `direction_control`) WORKS.** All four directions plus stop
  drive the robot. Earlier conclusion that it was "ignored" was WRONG — the write
  returns `null` and the robot never echoes the value, so a missing ack must not
  be read as rejection. Verify by watching the robot, not the datapoint.
- **The robot publishes NO telemetry during manual drive:** `status` stays
  `standby`, `dir` is never reported, `fault` stays 0. Battery drains, so it is
  genuinely moving.
- **It refuses to advance onto the dock ramp — and raises no fault while doing so.**
  Sampled at 2 Hz while forward was held: `fault=0` throughout. That rules out
  cliff_ir, co_sensor and lidar_shelter, and also rules out traction/ramp height
  (it never reaches the ramp). Silent refusal is the signature of obstacle
  avoidance, which is not a fault condition.
- **Therefore the docking fault cannot be diagnosed over the Tuya protocol.**
  Avoidance decisions never reach the wifi module. Leading hypothesis is the front
  3D ToF obstacle sensor reporting a phantom obstacle at the dock (dirty/hazed
  window). Decisive test is observational: drive at a plain wall — stopping short
  of that too implicates the sensor; approaching a wall normally but refusing only
  the dock implicates docking firmware.
- Manual drive probably cannot dock the robot by design; docking is the IR homing
  routine (`switch_charge`), not a substitutable manual approach.

---
name: dds-idl-generator
description: Generate DDS IDL schema drafts from natural-language requirements. Use when defining or refining DDS/XTypes message types, topics, structs, enums, keys, optional fields, bounded strings, sequences, or appendable evolution hints for embedded, robotics, or distributed pub-sub systems.
---

# DDS IDL Generator

Convert natural-language message requirements into stable DDS/XTypes-style IDL drafts.
Use this skill in two phases: compact rule planning, then generation with targeted few-shots.

## Core Workflow

1. Extract schema facts from the request.
2. Apply conservative DDS/XTypes defaults.
3. Load 2-4 few-shots from `assets/few_shots/` that best match the request shape.
4. Generate the output in the requested format.
5. Surface assumptions and warnings explicitly.

## Few-Shot Routing

When needed, read examples via `load_skill(name="dds-idl-generator", path="assets/few_shots/<file>.md")`.

Pick by pattern:

- IDs, timestamp, optional numeric fields:
  - `01_vehicle_location_appendable.md`
- enum + bounded sequence:
  - `02_alarm_event_enum_sequence.md`
- nested struct + key + optional:
  - `03_device_telemetry_nested.md`
- bounded strings and explicit key:
  - `04_robot_heartbeat_bounded.md`
- missing sequence bound warning:
  - `05_track_list_unbounded_warning.md`
- optional fields + appendable evolution:
  - `06_power_state_optional.md`
- geometry/pose style nested payload:
  - `07_pose_with_covariance.md`
- closed status set with enum and key:
  - `08_job_status_event.md`
- arrays represented as bounded sequence:
  - `09_battery_pack_cells.md`
- mixed lists with nested element struct:
  - `10_sensor_snapshot_bundle.md`

## Default Modeling Rules

- ID-like fields: prefer `string<32>` or `string<64>`.
- Time fields: prefer `uint64` and assume milliseconds since epoch.
- Coordinates (`latitude`, `longitude`): use `double`.
- Typical measured values: use `float`.
- Boolean switches: use `boolean`.
- Closed categories: use `enum`.
- Repeated fields with bound: use `sequence<T, N>`.
- Repeated fields without bound: use `sequence<T>` and add warning.

## DDS/XTypes Constraints

- Members are not `@key` by default.
- Members are not `@optional` by default.
- A member cannot be both `@key` and `@optional`.
- Use `@appendable` when evolution is likely.
- Do not introduce `union`, `map`, inheritance, typedefs, custom annotations unless user requests.

## Naming Rules

- `module`: `lower_snake_case`
- type names: `PascalCase`
- member names: `snake_case`
- enum literals: `UPPER_SNAKE_CASE`

## Output Contract

If user asks for draft schema output, prefer:

```json
{
  "assumptions": [],
  "warnings": [],
  "idl": "module demo { ... }"
}
```

If user asks for only IDL, return only IDL.

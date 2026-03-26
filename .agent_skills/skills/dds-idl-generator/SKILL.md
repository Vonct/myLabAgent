---
name: dds-idl-generator
description: Generate DDS IDL schema drafts from natural-language requirements. Use when defining or refining DDS/XTypes message types, topics, structs, enums, keys, optional fields, bounded strings, sequences, or appendable evolution hints for embedded, robotics, or distributed pub-sub systems.
---

# DDS IDL Generator

Convert natural-language message requirements into stable DDS/XTypes-style IDL drafts.
Prefer a direct-generation workflow for first-pass productivity: produce clean IDL plus explicit assumptions and warnings, then apply light rule checking mentally before answering.

## Workflow

Follow this sequence:

1. Identify the requested artifact.
   Supported first-class outputs are `module`, `struct`, `enum`, `sequence<T, N>`, `string<N>`, `@key`, `@optional`, and `@appendable`.

2. Extract the schema facts from the request.
   Look for:
   - main type names
   - module or namespace names
   - field names
   - enum candidates
   - list or array constraints
   - key fields
   - optional fields
   - future evolution hints such as "later may add fields"

3. Apply conservative DDS/XTypes defaults.
   Prefer stable, unsurprising mappings over ambitious modeling.

4. Generate the IDL directly.
   Do not force an IR-first architecture unless the user explicitly asks for IR, validation output, or machine-readable intermediate schema.

5. Surface ambiguity explicitly.
   If a field meaning is unclear, keep the schema conservative and record the assumption or warning instead of pretending certainty.

## Default Modeling Rules

Use these defaults unless the user gives a stronger constraint:

- IDs such as `vehicle_id`, `device_id`, `sensor_id`:
  prefer `string<32>` or `string<64>` rather than unbounded `string`.
- `timestamp`, `time`, `timestamp_ms`:
  prefer `uint64`, and assume milliseconds since epoch when not specified.
- `latitude` and `longitude`:
  use `double`.
- common measured values such as speed, heading, angle, confidence, voltage:
  use `float`.
- booleans or switches:
  use `boolean`.
- categories, modes, or status sets with a closed list:
  model as `enum`.
- repeated items with a stated upper bound:
  use `sequence<T, N>`.
- repeated items without a bound:
  use `sequence<T>` and add a warning that no bound was provided.

## DDS/XTypes Constraints

Respect these rules in every answer:

- Members are not `@key` by default.
- Members are not `@optional` by default.
- A member cannot be both `@key` and `@optional`.
- Use `@appendable` when the request says the type may gain fields later.
- Do not introduce `@mutable` or `@final` unless the user clearly asks for strict layout or stronger evolution semantics.
- Do not introduce `union`, `map`, inheritance, typedefs, or custom annotations unless the user explicitly requests them.

## Naming Rules

Normalize names when the user does not specify an exact spelling:

- `module`: `lower_snake_case`
- type names: `PascalCase`
- members: `snake_case`
- enum literals: `UPPER_SNAKE_CASE`

Keep user-provided domain terminology when it is already clear and valid.

## Output Contract

Prefer this response structure when the caller wants a schema draft rather than only raw code:

```json
{
  "assumptions": [
    "vehicle_id is modeled as string<64>",
    "timestamp is interpreted as milliseconds since epoch"
  ],
  "warnings": [],
  "idl": "module vehicle { ... }"
}
```

If the user asks for only the IDL, still apply the same reasoning internally, but keep the final answer compact.

## Example

User request:

```text
定义一个车辆定位消息，包含车辆ID、经纬度、速度、航向和时间戳。车辆ID是键，速度和航向可能没有。后续可能会增加电池信息。
```

Preferred result:

```json
{
  "assumptions": [
    "vehicle_id is modeled as string<64>",
    "timestamp is interpreted as milliseconds since epoch",
    "future extensibility maps to @appendable"
  ],
  "warnings": [],
  "idl": "module vehicle {\n\n  @appendable\n  struct VehicleLocation {\n    @key string<64> vehicle_id;\n    double latitude;\n    double longitude;\n    @optional float speed;\n    @optional float heading;\n    uint64 timestamp_ms;\n  };\n\n};"
}
```

## Style Guidance

- Be decisive when the request is clear.
- Be conservative when the request is ambiguous.
- Prefer a useful first draft over exhaustive theory.
- Mention DDS/XTypes rules only when they materially affect the output.
- Optimize for schemas that are easy for a human to review and easy for a later validator to check.

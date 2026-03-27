# Shot 06: Power State with Optional Fields

## Request

需要电源状态消息，字段有设备ID（键）、电池电量、充电状态、剩余续航里程（可选）、外接电源电压（可选），后续可能加更多字段。

## Expected Output

```json
{
  "assumptions": [
    "device_id uses string<64>",
    "range_km and ext_power_voltage are optional",
    "future extension implies @appendable"
  ],
  "warnings": [],
  "idl": "module power {\n\n  @appendable\n  struct PowerState {\n    @key string<64> device_id;\n    float battery_percent;\n    boolean charging;\n    @optional float range_km;\n    @optional float ext_power_voltage;\n    uint64 timestamp_ms;\n  };\n\n};"
}
```


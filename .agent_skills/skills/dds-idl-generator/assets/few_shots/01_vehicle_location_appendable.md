# Shot 01: Vehicle Location with Appendable

## Request

定义一个车辆定位消息，包含车辆ID、经纬度、速度、航向和时间戳。车辆ID是键，速度和航向可能没有。后续可能会增加电池信息。

## Expected Output

```json
{
  "assumptions": [
    "vehicle_id uses string<64>",
    "timestamp_ms is milliseconds since epoch",
    "future extension implies @appendable"
  ],
  "warnings": [],
  "idl": "module vehicle {\n\n  @appendable\n  struct VehicleLocation {\n    @key string<64> vehicle_id;\n    double latitude;\n    double longitude;\n    @optional float speed;\n    @optional float heading;\n    uint64 timestamp_ms;\n  };\n\n};"
}
```


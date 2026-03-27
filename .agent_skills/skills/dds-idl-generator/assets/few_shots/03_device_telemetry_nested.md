# Shot 03: Nested Telemetry

## Request

需要一个设备遥测消息，包含设备ID（键）、位置（经纬度）、姿态（yaw/pitch/roll）、电压和温度。姿态和温度可能缺失。

## Expected Output

```json
{
  "assumptions": [
    "device_id uses string<64>",
    "orientation is optional as a whole",
    "temperature_c is optional"
  ],
  "warnings": [],
  "idl": "module telemetry {\n\n  struct GeoPoint {\n    double latitude;\n    double longitude;\n  };\n\n  struct Orientation {\n    float yaw;\n    float pitch;\n    float roll;\n  };\n\n  struct DeviceTelemetry {\n    @key string<64> device_id;\n    GeoPoint location;\n    @optional Orientation orientation;\n    float voltage;\n    @optional float temperature_c;\n    uint64 timestamp_ms;\n  };\n\n};"
}
```


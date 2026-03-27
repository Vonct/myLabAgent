# Shot 10: Sensor Snapshot Bundle

## Request

生成传感器快照消息，包含设备ID（键）、多个传感器读数（每个读数有名称和值，最多20个）、整体质量评分（可选）和时间戳。

## Expected Output

```json
{
  "assumptions": [
    "device_id uses string<64>",
    "sensor list has upper bound 20",
    "quality_score is optional"
  ],
  "warnings": [],
  "idl": "module sensing {\n\n  struct SensorReading {\n    string<32> name;\n    float value;\n  };\n\n  struct SensorSnapshot {\n    @key string<64> device_id;\n    sequence<SensorReading, 20> readings;\n    @optional float quality_score;\n    uint64 timestamp_ms;\n  };\n\n};"
}
```


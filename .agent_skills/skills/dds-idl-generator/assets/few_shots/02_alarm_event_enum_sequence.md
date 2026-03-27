# Shot 02: Alarm Event with Enum and Bounded Sequence

## Request

设计一个告警事件，包含设备ID（主键）、告警级别、告警码列表（最多16个）和发生时间。

## Expected Output

```json
{
  "assumptions": [
    "device_id uses string<64>",
    "alarm_code list max size is 16",
    "occurred_at_ms is milliseconds since epoch"
  ],
  "warnings": [],
  "idl": "module alarm {\n\n  enum AlarmLevel {\n    INFO,\n    WARN,\n    ERROR,\n    FATAL\n  };\n\n  struct AlarmEvent {\n    @key string<64> device_id;\n    AlarmLevel level;\n    sequence<uint32, 16> alarm_codes;\n    uint64 occurred_at_ms;\n  };\n\n};"
}
```


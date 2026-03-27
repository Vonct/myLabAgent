# Shot 04: Robot Heartbeat with Bounded Strings

## Request

定义机器人心跳，字段有机器人ID（键）、状态文本、固件版本、在线标记和时间戳。状态文本最长32，版本号最长24。

## Expected Output

```json
{
  "assumptions": [
    "robot_id uses string<64>",
    "status_text and firmware_version are bounded by request"
  ],
  "warnings": [],
  "idl": "module robot {\n\n  struct Heartbeat {\n    @key string<64> robot_id;\n    string<32> status_text;\n    string<24> firmware_version;\n    boolean online;\n    uint64 timestamp_ms;\n  };\n\n};"
}
```


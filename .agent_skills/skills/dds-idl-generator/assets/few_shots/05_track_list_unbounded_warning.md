# Shot 05: Unbounded Sequence Warning

## Request

生成目标轨迹列表，包含目标ID、轨迹点集合、更新时间。轨迹点数量没有给上限。

## Expected Output

```json
{
  "assumptions": [
    "target_id uses string<64>",
    "point contains latitude, longitude, and timestamp"
  ],
  "warnings": [
    "track_points has no upper bound; sequence is unbounded"
  ],
  "idl": "module tracking {\n\n  struct TrackPoint {\n    double latitude;\n    double longitude;\n    uint64 timestamp_ms;\n  };\n\n  struct TargetTrack {\n    @key string<64> target_id;\n    sequence<TrackPoint> track_points;\n    uint64 updated_at_ms;\n  };\n\n};"
}
```


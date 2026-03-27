# Shot 07: Pose with Covariance

## Request

定义位姿消息，包含机器人ID（键）、x/y/z、四元数qx/qy/qz/qw、协方差矩阵（最多36项）和时间戳。

## Expected Output

```json
{
  "assumptions": [
    "robot_id uses string<64>",
    "covariance represented as flattened list with bound 36"
  ],
  "warnings": [],
  "idl": "module localization {\n\n  struct Pose {\n    float x;\n    float y;\n    float z;\n    float qx;\n    float qy;\n    float qz;\n    float qw;\n  };\n\n  struct PoseWithCovariance {\n    @key string<64> robot_id;\n    Pose pose;\n    sequence<float, 36> covariance;\n    uint64 timestamp_ms;\n  };\n\n};"
}
```


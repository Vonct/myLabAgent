# Shot 09: Battery Pack Cells

## Request

定义电池包数据，包含电池包ID（键）、单体电压列表（最多24个）、总电流、总电压、采样时间。

## Expected Output

```json
{
  "assumptions": [
    "pack_id uses string<64>",
    "cell_voltage_count has max 24"
  ],
  "warnings": [],
  "idl": "module battery {\n\n  struct BatteryPackSample {\n    @key string<64> pack_id;\n    sequence<float, 24> cell_voltages;\n    float total_current;\n    float total_voltage;\n    uint64 timestamp_ms;\n  };\n\n};"
}
```


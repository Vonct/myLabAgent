# Shot 08: Job Status Event

## Request

设计任务状态事件，字段有任务ID（键）、任务状态（pending/running/success/failed）、错误码（仅失败时可能有）和上报时间。

## Expected Output

```json
{
  "assumptions": [
    "job_id uses string<64>",
    "error_code is optional because only present on failure"
  ],
  "warnings": [],
  "idl": "module job {\n\n  enum JobStatus {\n    PENDING,\n    RUNNING,\n    SUCCESS,\n    FAILED\n  };\n\n  struct JobStatusEvent {\n    @key string<64> job_id;\n    JobStatus status;\n    @optional uint32 error_code;\n    uint64 reported_at_ms;\n  };\n\n};"
}
```


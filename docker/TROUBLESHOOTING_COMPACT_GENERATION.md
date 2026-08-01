# UMDL compact generation mode

## Why v0.3 changes the generation path

The full UMDL schema contains nested tasks, open-ended parameter objects, constraints,
contingencies, and strings that are intentionally extensible. Passing that full schema to
vLLM guided decoding can make a small model generate long, semantically weak objects.
When the token budget is exhausted, the response is truncated and is no longer valid JSON.

v0.3 separates the two concerns:

1. The LLM generates `umdl-generation-0.1.schema.json`, a compact and bounded planner IR.
2. The server compiles that IR into the full `umdl-0.1.schema.json` structure.
3. The compiled UMDL is validated with JSON Schema and deterministic rules.
4. The planner still does not publish ROS commands.

## Expected health response

```json
{
  "schema_ready": true,
  "generation_schema_ready": true,
  "generation_mode": "compact_ir_then_compile",
  "planner_max_tokens": 512,
  "guided_json": true,
  "guided_decoding_backend": "outlines"
}
```

## Important output diagnostics

Each attempt now reports:

- `finish_reason`
- token `usage`
- compact generation-schema error count
- semantic generation-rule error count
- final UMDL validation error count

A `finish_reason` of `length` means the model reached `UMDL_MAX_TOKENS`.

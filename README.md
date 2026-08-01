# Context Doctor

Repairs malformed JSON in model responses with [json_repair](https://github.com/mangiucugna/json_repair), then beautifies output before it reaches history, log, and tool execution.

## How it works

DirtyJson runs first (native A0). Context Doctor runs second: `json_repair` fixes what DirtyJson couldn't, validates against A0 schema (`tool_name` + `tool_args` required), outputs clean JSON.

Three hooks modify in-place, nothing appended:

- `response_stream_end` - log item content, kvps, heading
- `hist_add_ai_response/end` - history message, `llm_result.response`, log item
- `tool_execute_before` - `tool_args` from full repaired response

### Fallbacks

| Input | Output |
|---|---|
| Malformed A0 tool call | Repaired + beautified JSON |
| Plain text with XML tags | `{}` (history only, log untouched) |
| Plain text without XML | `{"thoughts": [raw]}` |

`json_repair` runs first. Fallbacks only apply if it returns nothing usable.

## Settings

| Setting | Default | What it does |
|---|---|---|
| `indent` | `4` | JSON indent spaces |
| `minify` | `false` | Compact output, no whitespace |
| `update_log` | `false` | Put repaired JSON in View Details. Kvps and heading always update. |
| `use_standard_mode` | `false` | Standard mode, no schema. Off = salvage mode with A0 schema. |

## Structure

```
context_doctor/
├── plugin.yaml
├── default_config.yaml
├── helpers/context_doctor.py          # repair_and_beautify, transform_response, build_heading, update_log_item, schema
├── vendor/json_repair/                # bundled, no pip
├── extensions/python/
│   ├── response_stream_end/_20_context_doctor.py
│   ├── _functions/agent/Agent/hist_add_ai_response/end/_20_context_doctor.py
│   └── tool_execute_before/_30_context_doctor.py
├── webui/config.html
└── tests/                             # unit + integration + e2e (58 tests)
```

## Install

Copy to `/a0/usr/plugins/`. Toggle on in WebUI.

## Test

```bash
cd /a0/usr/plugins/context_doctor
/opt/venv-a0/bin/python -m pytest tests/ -q
```

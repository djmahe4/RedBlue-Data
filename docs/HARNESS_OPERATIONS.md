# Harness Operations

## Run the harness in the workspace

Install base requirements and launch from the project/user workspace:

```bash
pip install -r requirements.txt
uvicorn api.main:app --reload
```

`docker/harness.Dockerfile` is optional image packaging, not a runtime
requirement. `config/tools.yaml` is currently reference-only; runtime registry
is defined in `harness/graph.py`.

## Planner

Set `HARNESS_PLANNER=ollama` to use local Ollama for selecting one tool from
an allowlist. It uses `PLANNER_MODEL` or falls back to `OLLAMA_MODEL`,
`OLLAMA_BASE_URL`, and `PLANNER_TIMEOUT`. Default `HARNESS_PLANNER=rules`
keeps deterministic keyword routing when model planning is disabled. The model
selects a tool only; arguments come from the request, not model-generated
values. Each run executes at most one tool. Browser, search, and dataset actions
remain HITL-gated; approval replays the exact stored plan without asking the
model again. Planner prompts go to the configured Ollama endpoint, so use a
local endpoint for private task text. The referenced [harness-creator skill](https://github.com/walkinglabs/learn-harness-engineering/blob/main/skills/harness-creator/SKILL.md)
covers coding-agent instructions, state, and verification artifacts rather than
runtime planner design; implementation here follows its scope and verification
principles.

## Dataset generation

Start a run with a dataset task and optional settings:

```json
{
  "task": "generate dataset",
  "dataset_options": {
    "max_reports": 30,
    "skip_ocr": false
  }
}
```

Dataset generation pauses for approval, then runs the existing
`scripts/process_reports.py` in the configured workspace. It does not dispatch
the dataset pipeline to the sandbox container. Set `REDBLUE_WORKSPACE` to the
user workspace path when the API process does not run from that directory. The
workspace must contain `reports-source/`; output paths remain inside it.

`max_reports`, `max_file_size_mb`, `output_dir`, `skip_ocr`, and `full_run` are
supported. Reset/wipe operations are not exposed through the harness.

## OCR and PDF vision

`tools/ocr.py` supports local Tesseract, Ollama, and a configurable HTTP API.
OpenAPI is the API description format, not a provider. For an API endpoint, set
`OCR_PROVIDER=api`, `OCR_API_URL`, and optionally `OCR_MODEL`, `OCR_API_KEY`,
`OCR_API_AUTH_SCHEME`, `OCR_API_HEADERS` (JSON object), and
`OCR_API_EXTRA_PAYLOAD` (JSON object). The default request includes `task`,
`model`, `prompt`, `mime_type`, and base64 `image_base64`; see
[`ocr-api.openapi.yaml`](ocr-api.openapi.yaml). `VLM_API_URL` and `VLM_MODEL`
can configure a separate reasoning endpoint/model. Ollama uses
`OCR_PROVIDER=ollama`, `OLLAMA_BASE_URL`, and `OCR_MODEL` or
`OLLAMA_OCR_MODEL`; optional `VLM_MODEL` uses a second Ollama pass. Tesseract
runs when no model endpoint is configured or a model request fails.

PDF OCR renders a page screenshot, clusters nearby image/vector regions, OCRs
up to two selected crops, and removes exact duplicate lines. Optional VLM notes
are retained only with a verbatim quote from OCR text and remain unverified.

## Dashboard

`POST /api/run/start` returns `run_id` and `dashboard_url`. Open the dashboard
URL to watch execution, approve pending actions, and inspect syscall events.
Run events are held in process memory and disappear when the API restarts.

Agent stages use an OpenTelemetry-style span record: `trace_id`, `span_id`,
`parent_span_id`, `name`, `kind`, `status`, nanosecond start/end times,
`duration_ns`, and semantic `attributes`. Planner, approval, tool execution,
reflection, errors, and syscalls share the run's `trace_id`; trace edges show
parent-child relationships rather than just event order. Expand a dashboard
trace row to inspect its IDs and attributes. This local schema has no OpenTelemetry
SDK or OTLP exporter; exception stack traces and tool arguments are not added to
span attributes. Exception messages may still include local paths or provider
details, so bind the API to a trusted interface.

## Rust syscall-hook ingestion contract

The API accepts one event per request at `POST /api/run/{run_id}/syscalls`.
The hook must send `X-Trace-Token`, matching `REDBLUE_TRACE_TOKEN` configured on
the API. Ingestion is disabled when that variable is unset.

```json
{
  "timestamp": "2026-11-15T12:00:00Z",
  "syscall": "openat",
  "pid": 1234,
  "result": 0,
  "duration_ns": 1200,
  "parent_span_id": "0123456789abcdef"
}
```

`parent_span_id` is optional and must be a 16-character hex span ID when
provided. The URL supplies `trace_id`; the API assigns a syscall span ID and
records process PID, syscall name, result, and duration as attributes. Do not
send syscall arguments, file contents, credentials, or other sensitive data.
Events are bounded to the newest 10,000 per run. The repository currently
provides the receiver and dashboard, not a Rust syscall collector. A collector
still needs a platform-specific implementation selected for the deployment
environment.

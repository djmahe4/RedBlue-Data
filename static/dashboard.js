const runId = window.RUN_ID;
const statusNode = document.getElementById("status");
const taskNode = document.getElementById("task");
const detailsNode = document.getElementById("details");
const traceNode = document.getElementById("trace");
const syscallNode = document.getElementById("syscalls");
const approveButton = document.getElementById("approve");
let eventStream = null;

function cell(row, value) {
  const node = document.createElement("td");
  node.textContent = value == null ? "" : String(value);
  row.appendChild(node);
}

function formatDuration(durationNs) {
  const milliseconds = Number(durationNs || 0) / 1_000_000;
  return `${milliseconds < 1 ? milliseconds.toFixed(3) : milliseconds.toFixed(1)} ms`;
}

function connectStream() {
  if (eventStream) return;
  const source = new EventSource(`/api/run/${runId}/stream`);
  eventStream = source;
  for (const eventName of ["planner", "executor", "reflector", "hitl_request", "error"]) {
    source.addEventListener(eventName, () => {
      refresh().catch(() => {});
      if (["hitl_request", "reflector", "error"].includes(eventName)) {
        source.close();
        if (eventStream === source) eventStream = null;
      }
    });
  }
  source.onerror = () => {
    source.close();
    if (eventStream === source) eventStream = null;
    refresh().catch(() => {});
  };
}

async function refresh() {
  const [statusResponse, traceResponse, syscallResponse] = await Promise.all([
    fetch(`/api/run/${runId}`),
    fetch(`/r3f/trace/${runId}`),
    fetch(`/api/run/${runId}/syscalls`),
  ]);
  if (![statusResponse, traceResponse, syscallResponse].every((response) => response.ok)) {
    statusNode.textContent = "UNAVAILABLE";
    statusNode.dataset.status = "failed";
    return;
  }

  const status = await statusResponse.json();
  const trace = await traceResponse.json();
  const syscalls = await syscallResponse.json();
  statusNode.textContent = status.status.replaceAll("_", " ").toUpperCase();
  statusNode.dataset.status = status.status;
  document.getElementById("run-id").textContent = runId.slice(0, 12);
  taskNode.textContent = status.task;
  document.getElementById("event-count").textContent = status.event_count;
  document.getElementById("syscall-count").textContent = status.syscall_count;
  document.getElementById("syscall-count-inline").textContent = status.syscall_count;
  document.getElementById("approval-count").textContent = status.status === "awaiting_approval" ? "REVIEW" : "—";
  detailsNode.textContent = status.pending_action
    ? JSON.stringify(status.pending_action, null, 2)
    : status.last_error || "No action pending.";
  approveButton.hidden = status.status !== "awaiting_approval";

  const traceItems = trace.nodes.map((node) => {
    const item = document.createElement("li");
    item.className = `trace-${node.type}`;

    const heading = document.createElement("div");
    heading.className = "trace-row-heading";
    const kind = document.createElement("span");
    kind.className = "trace-event-type";
    kind.textContent = node.name || node.type.replaceAll("_", " ");
    const label = document.createElement("strong");
    label.textContent = node.label || "event";
    const status = document.createElement("span");
    status.className = "trace-status";
    status.dataset.status = (node.status || "UNSET").toLowerCase();
    status.textContent = node.status || "UNSET";
    heading.append(kind, label, status);

    const metadata = document.createElement("div");
    metadata.className = "trace-row-meta";
    const timestamp = document.createElement("time");
    timestamp.dateTime = node.timestamp || "";
    timestamp.textContent = node.timestamp ? new Date(node.timestamp).toLocaleString() : "time unavailable";
    const duration = document.createElement("span");
    duration.textContent = formatDuration(node.duration_ns);
    metadata.append(timestamp, duration);

    const disclosure = document.createElement("details");
    disclosure.className = "trace-details";
    const summary = document.createElement("summary");
    summary.textContent = `Span details · ${node.span_id || "ID unavailable"}`;
    const attributes = document.createElement("pre");
    attributes.textContent = JSON.stringify({
      trace_id: node.trace_id,
      span_id: node.span_id,
      parent_span_id: node.parent_span_id,
      kind: node.kind,
      status: node.status,
      attributes: node.attributes || {},
      ...(node.message ? { message: node.message } : {}),
    }, null, 2);
    disclosure.append(summary, attributes);
    item.append(heading, metadata, disclosure);
    return item;
  });
  if (!traceItems.length) {
    const empty = document.createElement("li");
    empty.className = "trace-empty";
    empty.textContent = "Waiting for first event…";
    traceItems.push(empty);
  }
  traceNode.replaceChildren(...traceItems);

  const rows = syscalls.syscalls.map((event) => {
    const row = document.createElement("tr");
    cell(row, event.timestamp);
    cell(row, event.pid);
    cell(row, event.syscall);
    cell(row, event.result);
    cell(row, event.duration_ns);
    return row;
  });
  if (!rows.length) {
    const row = document.createElement("tr");
    const empty = document.createElement("td");
    empty.className = "table-empty";
    empty.colSpan = 5;
    empty.textContent = "No syscall events received for this run.";
    row.appendChild(empty);
    rows.push(row);
  }
  syscallNode.replaceChildren(...rows);
}

approveButton.addEventListener("click", async () => {
  approveButton.disabled = true;
  try {
    const response = await fetch(`/api/run/${runId}/approve`, { method: "POST" });
    if (!response.ok) {
      const result = await response.json();
      throw new Error(result.detail || result.error || "Approval failed");
    }
    connectStream();
  } catch (error) {
    detailsNode.textContent = error instanceof Error ? error.message : "Approval failed";
  } finally {
    approveButton.disabled = false;
    await refresh();
  }
});

refresh().then(() => {
  if (statusNode.dataset.status === "queued") connectStream();
}).catch(() => {
  statusNode.textContent = "UNAVAILABLE";
  statusNode.dataset.status = "failed";
});
window.setInterval(() => refresh().catch(() => {}), 2500);

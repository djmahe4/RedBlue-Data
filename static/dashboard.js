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
    statusNode.textContent = "unavailable";
    return;
  }

  const status = await statusResponse.json();
  const trace = await traceResponse.json();
  const syscalls = await syscallResponse.json();
  statusNode.textContent = status.status;
  taskNode.textContent = status.task;
  detailsNode.textContent = status.pending_action
    ? JSON.stringify(status.pending_action, null, 2)
    : "None";
  approveButton.hidden = status.status !== "awaiting_approval";

  traceNode.replaceChildren(...trace.nodes.map((node) => {
    const item = document.createElement("li");
    item.textContent = `${node.type}: ${node.label}`;
    return item;
  }));
  syscallNode.replaceChildren(...syscalls.syscalls.map((event) => {
    const row = document.createElement("tr");
    cell(row, event.timestamp);
    cell(row, event.pid);
    cell(row, event.syscall);
    cell(row, event.result);
    cell(row, event.duration_ns);
    return row;
  }));
}

approveButton.addEventListener("click", async () => {
  approveButton.disabled = true;
  try {
    const response = await fetch(`/api/run/${runId}/approve`, { method: "POST" });
    if (!response.ok) statusNode.textContent = "approval failed";
    else connectStream();
  } finally {
    approveButton.disabled = false;
    await refresh();
  }
});

refresh().then(() => {
  if (statusNode.textContent === "queued") connectStream();
}).catch(() => { statusNode.textContent = "unavailable"; });
window.setInterval(() => refresh().catch(() => {}), 2000);

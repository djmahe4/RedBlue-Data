const form = document.getElementById("run-form");
const workflow = document.getElementById("workflow");
const taskField = document.getElementById("task");
const targetField = document.getElementById("target-field");
const targetLabel = document.getElementById("target-label");
const targetInput = document.getElementById("target");
const targetHint = document.getElementById("target-hint");
const datasetField = document.getElementById("dataset-field");
const message = document.getElementById("form-message");
const startButton = document.getElementById("start-button");
const mode = (window.PLANNER_MODE || "rules").toLowerCase();

const workflowFields = {
  dataset: { prefix: "generate dataset", label: "Report source", placeholder: "reports-source/ (configured workspace)", hint: "Dataset runs read reports-source/ from the server workspace and require approval." },
  ocr: { prefix: "ocr document", label: "Server-side file path", placeholder: "C:\\workspace\\report.pdf", hint: "Path must be readable by the API process. PDF pages include visual-region OCR." },
  search: { prefix: "search", label: "Search query", placeholder: "e.g. recent public pentest reports", hint: "Uses configured SearXNG. Search pauses for approval." },
  browser: { prefix: "browser fetch", label: "Page URL", placeholder: "https://example.org", hint: "External navigation pauses for approval." },
};

function updateWorkflow() {
  const selected = workflow.value;
  const config = workflowFields[selected];
  const needsTarget = selected !== "dataset";
  targetField.hidden = !needsTarget;
  targetInput.required = needsTarget;
  datasetField.hidden = selected !== "dataset";
  targetLabel.textContent = config.label;
  targetInput.placeholder = config.placeholder;
  targetHint.textContent = config.hint;
  taskField.placeholder = selected === "dataset"
    ? "e.g. Process recent public pentest reports"
    : "Optional details for this run";
  message.dataset.error = "false";
  message.textContent = selected === "dataset" || selected === "browser" || selected === "search"
    ? "This workflow pauses for approval before execution."
    : "Local document processing runs in the API workspace.";
}

workflow.addEventListener("change", updateWorkflow);
updateWorkflow();

document.getElementById("planner-mode").textContent = `${mode} planner`;
document.getElementById("planner-detail").textContent = mode;

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!form.reportValidity()) return;
  startButton.disabled = true;
  message.dataset.error = "false";
  message.textContent = "Creating run…";

  const selected = workflow.value;
  const config = workflowFields[selected];
  const description = taskField.value.trim();
  const payload = { task: description ? `${config.prefix}: ${description}` : config.prefix };
  const value = targetInput.value.trim();

  if (selected === "dataset") {
    payload.dataset_options = { max_reports: Number(document.getElementById("max-reports").value) || 30 };
  } else if (selected === "ocr") {
    payload.input = value.toLowerCase().split("?")[0].endsWith(".pdf")
      ? { pdf_path: value }
      : { image_path: value };
  } else if (selected === "search") {
    payload.input = value;
  } else {
    payload.input = value;
  }

  try {
    const response = await fetch("/api/run/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || result.error || `Request failed (${response.status})`);
    message.textContent = "Run created. Opening trace…";
    window.location.assign(result.dashboard_url);
  } catch (error) {
    message.dataset.error = "true";
    message.textContent = error instanceof Error ? error.message : "Could not start run.";
    startButton.disabled = false;
  }
});

async function mountScene() {
  const canvas = document.getElementById("hero-scene");
  if (!canvas || !window.WebGLRenderingContext || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    canvas?.parentElement?.classList.add("scene-static");
    return;
  }

  try {
    const THREE = await import("three");
    const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, powerPreference: "low-power" });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    renderer.setClearColor(0x000000, 0);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 40);
    camera.position.set(0, 0, 5.5);

    const field = new THREE.Group();
    scene.add(field);
    const globe = new THREE.Mesh(
      new THREE.IcosahedronGeometry(1.12, 2),
      new THREE.MeshBasicMaterial({ color: 0x7295c2, wireframe: true, transparent: true, opacity: 0.24 }),
    );
    field.add(globe);

    const redOrbit = new THREE.Mesh(
      new THREE.TorusGeometry(1.56, 0.006, 3, 160),
      new THREE.MeshBasicMaterial({ color: 0xff6874, transparent: true, opacity: 0.7 }),
    );
    redOrbit.rotation.set(1.05, 0.2, 0.22);
    field.add(redOrbit);
    const blueOrbit = new THREE.Mesh(
      new THREE.TorusGeometry(1.72, 0.005, 3, 160),
      new THREE.MeshBasicMaterial({ color: 0x6ba8ff, transparent: true, opacity: 0.6 }),
    );
    blueOrbit.rotation.set(0.35, 1.05, -0.25);
    field.add(blueOrbit);

    const nodeGeometry = new THREE.SphereGeometry(0.028, 8, 6);
    const nodeMaterial = new THREE.MeshBasicMaterial({ color: 0xffffff });
    const nodeCount = 38;
    const nodes = new THREE.InstancedMesh(nodeGeometry, nodeMaterial, nodeCount);
    const helper = new THREE.Object3D();
    const red = new THREE.Color(0xff6874);
    const blue = new THREE.Color(0x6ba8ff);
    for (let index = 0; index < nodeCount; index += 1) {
      const y = 1 - (index / (nodeCount - 1)) * 2;
      const radius = Math.sqrt(1 - y * y);
      const angle = index * Math.PI * (3 - Math.sqrt(5));
      helper.position.set(Math.cos(angle) * radius, y, Math.sin(angle) * radius);
      helper.position.multiplyScalar(1.14);
      helper.scale.setScalar(index % 5 === 0 ? 1.55 : 1);
      helper.updateMatrix();
      nodes.setMatrixAt(index, helper.matrix);
      nodes.setColorAt(index, index % 2 === 0 ? red : blue);
    }
    field.add(nodes);

    const timer = new THREE.Timer();
    timer.connect(document);
    let width = 0;
    let height = 0;
    const resize = () => {
      const box = canvas.getBoundingClientRect();
      if (!box.width || !box.height) return;
      width = box.width;
      height = box.height;
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height, false);
      renderer.render(scene, camera);
    };
    const observer = new ResizeObserver(resize);
    observer.observe(canvas.parentElement);
    resize();

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const animate = () => {
      timer.update();
      const elapsed = timer.getElapsed();
      field.rotation.y = elapsed * 0.075;
      field.rotation.x = Math.sin(elapsed * 0.16) * 0.045;
      redOrbit.rotation.z = 0.22 + Math.sin(elapsed * 0.2) * 0.035;
      renderer.render(scene, camera);
    };
    if (!reducedMotion.matches) renderer.setAnimationLoop(animate);
    else renderer.render(scene, camera);

    window.addEventListener("resize", resize, { passive: true });
    window.addEventListener("pagehide", () => {
      observer.disconnect();
      timer.dispose();
      renderer.setAnimationLoop(null);
      renderer.dispose();
    }, { once: true });
  } catch {
    canvas.parentElement.classList.add("scene-static");
  }
}

mountScene();

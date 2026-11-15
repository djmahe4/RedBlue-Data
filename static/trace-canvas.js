// Minimal CDN-only R3F trace canvas hook. Host page supplies window.RUN_ID.
import React, { useEffect, useState } from "https://esm.sh/react";
import { createRoot } from "https://esm.sh/react-dom/client";
import { Canvas } from "https://esm.sh/@react-three/fiber";
import { OrbitControls } from "https://esm.sh/@react-three/drei";
import * as THREE from "https://esm.sh/three";

function Trace() {
  const [trace, setTrace] = useState({nodes: [], edges: []});
  useEffect(() => { fetch(`/r3f/trace/${window.RUN_ID}`).then(r => r.json()).then(setTrace); }, []);
  return React.createElement(Canvas, null,
    React.createElement(OrbitControls),
    trace.nodes.map((node, i) => React.createElement("mesh", {key: node.id, position: [i * 2, 0, 0]},
      React.createElement("sphereGeometry", {args: [0.35, 16, 16]}),
      React.createElement("meshStandardMaterial", {color: new THREE.Color(0x2f80ed)})
    )));
}

const root = document.getElementById("trace-canvas");
if (root) createRoot(root).render(React.createElement(Trace));

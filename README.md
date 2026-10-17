<p align="center">
  <h1 align="center">🏭 STF Digital Twin</h1>
  <p align="center">
    <strong>Full-Stack Cyber-Physical Digital Twin with In-Browser WebAssembly PLC & Grounded AI Copilot</strong>
  </p>
  <p align="center">
    <em>A mathematically proven digital twin of the fischertechnik Fabrik Simulation 24V (536634): 3D kinematics, real-time physics, IEC 61131-3 PLC control, predictive maintenance, and Industry 4.0 connectivity.</em>
  </p>
</p>

<p align="center">
  <a href="https://github.com/soham10i/stf-hw/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/soham10i/stf-hw/ci.yml?branch=main&label=CI%20Pipeline&logo=github" alt="CI"></a>
  <a href="https://soham10i.github.io/stf-hw/"><img src="https://img.shields.io/badge/Demo-Live%20In--Browser-brightgreen?logo=googlechrome" alt="Live Demo"></a>
  <img src="https://img.shields.io/badge/Python-3.11%2B-blue?logo=python" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/TypeScript-5.6-blue?logo=typescript" alt="TypeScript">
  <img src="https://img.shields.io/badge/Three.js-r166%20%7C%20R3F-black?logo=three.js" alt="Three.js">
  <img src="https://img.shields.io/badge/PLC-IEC%2061131--3%20Wasm-orange" alt="IEC 61131-3">
  <img src="https://img.shields.io/badge/Industry%204.0-OPC%20UA%20%7C%20AAS%20%7C%20Sparkplug%20B-darkblue" alt="Industry 4.0">
  <img src="https://img.shields.io/badge/License-MIT-green" alt="License">
</p>

<p align="center">
  <a href="https://stf-twin.onrender.com/"><b>🌐 Live In-Browser Demo</b></a> •
  <a href="https://stf-live.onrender.com/stf/"><b>⚡ Live Twin + AI Copilot</b></a> •
  <a href="docs/DASHBOARD_GUIDE.md"><b>📖 Operations Guide</b></a> •
  <a href="docs/DEPLOY.md"><b>🚀 Deployment</b></a> •
  <a href="#quick-start"><b>💻 Quick Start</b></a>
</p>

---

<p align="center">
  <img src="docs/images/twin-order.jpg" alt="STF Digital Twin 3D view executing an automated baking order" width="100%" style="border-radius: 8px; box-shadow: 0 4px 20px rgba(0,0,0,0.15);">
</p>

> [!NOTE]
> **One Parametric Model as the Single Source of Truth**: The CAD geometry, joint kinematics, electrical I/O, safety zones, analytics models, and the generated PLC code are derived from a unified FreeCAD parameter table. Nothing is exported unless mathematical and geometric proofs pass, guaranteeing zero drift between CAD, simulation, and physical execution.

---

## 📑 Table of Contents

- [Key Highlights](#-key-highlights)
- [Visual Showcase](#-visual-showcase)
- [System Architecture](#-system-architecture)
- [Core Capabilities](#-core-capabilities)
  - [1. Real-Time 3D Kinematics & Physics](#1-real-time-3d-kinematics--physics)
  - [2. In-Browser IEC 61131-3 PLC (WebAssembly)](#2-in-browser-iec-61131-3-plc-webassembly)
  - [3. Grounded Industrial AI Copilot](#3-grounded-industrial-ai-copilot)
  - [4. Predictive Maintenance & Analytics Dashboard](#4-predictive-maintenance--analytics-dashboard)
  - [5. Industry 4.0 & Cyber-Physical Security](#5-industry-40--cyber-physical-security)
- [Quick Start](#-quick-start)
- [AI Copilot Setup (Cloud, Local & Offline)](#-ai-copilot-setup)
- [Repository Structure](#-repository-structure)
- [Testing & Validation](#-testing--validation)
- [Documentation Directory](#-documentation-directory)

---

## 🌟 Key Highlights

* **No Disconnected Mocks:** Real S-curve acceleration profiles, motor back-EMF, lead-screw pitches, and belt tooth meshing calculated per frame.
* **PLC in the Browser:** Production IEC 61131-3 Structured Text compiled by MatIEC to WebAssembly, running against a deterministic plant I/O loop.
* **Fact-Checked AI Copilot:** Multi-turn operations assistant powered by Gemini 2.5 / local Ollama (`qwen2.5:7b-instruct`) with Python-driven tool grounding and automated numerical verification.
* **20+ Dashboard Perspectives:** OEE waterfalls, cycle bottlenecks, carbon per batch, microgrid battery scheduling, vision QC, and ISO 13849 / IEC 62443 security boundaries.
* **Dual Execution Modes:** Runs 100% serverless in the browser via static WebAssembly, or connects live via WebSockets (`/ws`) to a high-rate FastAPI simulation kernel.

---

## 📸 Visual Showcase

<table>
  <tr>
    <td width="50%">
      <img src="docs/images/twin-plc.jpg" alt="In-Browser IEC 61131-3 PLC execution" style="border-radius: 6px;">
      <br>
      <b>⚡ Real PLC Running in WebAssembly</b>
      <p>IEC 61131-3 control logic running directly in your browser. Shows real-time unit states, I/O registers, hazard zone interlocks, and the execution trace.</p>
    </td>
    <td width="50%">
      <img src="docs/images/twin-inside.jpg" alt="Mechanical layout inside the enclosure" style="border-radius: 6px;">
      <br>
      <b>🔧 Physical Kinematics & Wire Routing</b>
      <p>Enclosure stripped away exposing real drag chains, lead screws, motor pulleys, photoelectric sensors, and field wiring to the PLC cabinet.</p>
    </td>
  </tr>
  <tr>
    <td width="50%">
      <img src="docs/images/dashboard-overview.jpg" alt="Operations Overview Dashboard" style="border-radius: 6px;">
      <br>
      <b>📊 Factory Operations & OEE</b>
      <p>Live order tracking, OEE breakdown (availability, performance, quality), dynamic cycle bottleneck analysis, and unit state progressions.</p>
    </td>
    <td width="50%">
      <img src="docs/images/dashboard-health.jpg" alt="Predictive Maintenance & Health Index" style="border-radius: 6px;">
      <br>
      <b>🩺 Predictive Maintenance & Degradation</b>
      <p>Health Index (HI) and Remaining Useful Life (RUL) tracking for high-bay warehouse belts, vacuum cups, oven heaters, and pneumatic seals.</p>
    </td>
  </tr>
  <tr>
    <td width="50%">
      <img src="docs/images/copilot.jpg" alt="Industrial AI Copilot with context store" style="border-radius: 6px;">
      <br>
      <b>🤖 Grounded Industrial Copilot</b>
      <p>Conversational assistant grounded in live telemetry and 438 technical documents. Verified against twin data before answers are presented.</p>
    </td>
    <td width="50%">
      <img src="docs/images/dashboard-month.jpg" alt="Simulated production month" style="border-radius: 6px;">
      <br>
      <b>📅 Full Simulated Production Month</b>
      <p>30 days of accelerated production: compare throughput, unexpected breakdowns, and downtime costs with preventive maintenance (PM) ON vs. OFF.</p>
    </td>
  </tr>
</table>

---

## 🏗️ System Architecture

```mermaid
flowchart TD
  subgraph CAD_SOURCE["Single Source of Truth (Parametric CAD)"]
    FreeCAD["FreeCAD Model (stf-cad/hbw)"]
    Proofs["Automated Proof Engine\n(Interference, Travel, Kinematics)"]
    FreeCAD --> Proofs
  end

  subgraph EXPORT_PIPELINE["Generation Pipeline"]
    Proofs -->|Export JSON| WebAssets["web/public/*.json\n(Parts, Layout, Slots)"]
    Proofs -->|Compile MatIEC| WasmPLC["WebAssembly PLC\n(IEC 61131-3 ST / IL)"]
    Proofs -->|Train Synthetic CNN| VisionONNX["Vision QC Model\n(ONNX In-Browser)"]
    Proofs -->|Industry 4.0 Export| I40["AAS (IDTA) · OPC UA · Sparkplug B"]
  end

  subgraph BACKEND["FastAPI Live Twin Kernel (Python 3.11)"]
    PhysKernel["Kinematics & Motor Kernel\n(packages/stf_kernel)"]
    LiveAPI["FastAPI Backend\n(services/api)"]
    CopilotEngine["Python Grounding & Tool Engine\n(services/api/grounding.py)"]
    PhysKernel --> LiveAPI
    LiveAPI <--> CopilotEngine
    CopilotEngine --> LLM["Cloud (Gemini) / Local (Ollama)"]
  end

  subgraph FRONTEND["Interactive 3D Twin & Dashboard (React 18 + Three.js)"]
    WebAssets --> ThreeTwin["3D Three.js Digital Twin\n(React Three Fiber)"]
    WasmPLC --> ThreeTwin
    VisionONNX --> Dashboard["20+ Operations Pages\n(OEE, Health, Carbon, Alarms)"]
    LiveAPI -->|WebSocket /ws (30 Hz)| ThreeTwin
    LiveAPI -->|REST /chat, /orders| Dashboard
  end
```

---

## ⚡ Core Capabilities

### 1. Real-Time 3D Kinematics & Physics
* **High-Bay Warehouse (HBW):** 3-axis Cartesian crane with automated slot management (4×3 rack), realistic rack indexing, and toothed belt kinematics.
* **Vacuum Gripper Robot (VGR):** Multi-axis articulated transfer arm with pneumatic suction cup simulation, pressure decay, and spring compliance.
* **Baking Oven & Turntable:** Synchronized sliding door, heating cycles, and turntable rotation.
* **Sorting Station:** Dual-belt sorting line with optical colour detection (white, red, blue) and pneumatic pusher gates.
* **Zero-Allocation Render Loop:** Three.js instanced rendering with in-place matrix updates to maintain rock-solid 60 FPS in standard browsers.

### 2. In-Browser IEC 61131-3 PLC (WebAssembly)
* **True Industrial Code:** The control logic is not simulated in JavaScript; it is written in IEC 61131-3 Structured Text.
* **Compiled to Wasm:** Using the MatIEC compiler toolchain, the logic compiles to WebAssembly and runs client-side against a full hardware I/O image.
* **Observable States:** Inspect digital/analog inputs, memory registers, fault flags, and safety interlocks in real time.

### 3. Grounded Industrial AI Copilot
* **Zero Hallucination Tolerance:** The copilot is grounded through a dedicated Python domain tool engine ([`services/api/grounding.py`](services/api/grounding.py)) accessing 11 live factory telemetry tools.
* **Automated Fact Verification:** The server cross-references numerical values in LLM outputs against underlying physical metrics before presenting them to the user.
* **Flexible LLM Runtime:**
  * **Cloud:** Gemini 2.5 Flash / Pro with automatic model pool fallback.
  * **Local Offline:** Ollama running `qwen2.5:7b-instruct` on `localhost:11434`.
  * **Deterministic Rules:** 100% offline heuristic & BM25 document search over 438 technical documentation chunks.
* **Context Preservation:** Chat sessions store established technical facts, allowing seamless hand-offs between models without losing context.

### 4. Predictive Maintenance & Analytics Dashboard
* **Condition Monitoring:** Real-time Health Index (HI) calculated via Exponentially Weighted Moving Averages (EWMA).
* **Remaining Useful Life (RUL):** Predicts wear runways on conveyor belts, vacuum seals, and mechanical drives.
* **Environmental & Financial Metrics:** Tracks carbon grams per cookie, dynamic electricity tariff scheduling, and microgrid renewable utilization.
* **Full Month Simulation:** Accelerated playback of 720 hours of production with controllable fault injection (motor jams, photo-sensor occlusion, air pressure loss).

### 5. Industry 4.0 & Cyber-Physical Security
* **Asset Administration Shells (AAS):** IDTA-compliant submodels for Digital Nameplate, Handover Documentation, and Carbon Footprint.
* **OPC UA & MQTT:** OPC UA companion spec for Machinery and MQTT Sparkplug B mapped into an ISA-95 Unified Namespace (UNS).
* **OT Cybersecurity (IEC 62443):** Zone and conduit segmentation, operator role tokens, rate limiters, and defensive API origin validation.

---

## 💻 Quick Start

### Prerequisites
* **Python 3.11+**
* **Node.js 20+**
* *(Optional)* **Ollama** (for 100% private, offline LLM execution)

### 1. Clone & Setup

```bash
git clone https://github.com/soham10i/stf-hw.git
cd stf-hw

# Create virtualenv and install Python + Node dependencies
make install
```

### 2. Launch the Application

In two terminal windows:

```bash
# Terminal 1: Start the Python FastAPI backend (Port 8000)
make api
```

```bash
# Terminal 2: Start the Vite frontend dev server (Port 5173)
cd web && npm run dev
```

Open your browser:
* **Interactive 3D Twin:** [`http://localhost:5173/stf/`](http://localhost:5173/stf/)
* **Operations Dashboard:** [`http://localhost:5173/stf/dashboard.html`](http://localhost:5173/stf/dashboard.html)

---

## 🤖 AI Copilot Setup

The copilot works out-of-the-box in **Rules / Grounded Tool mode** without any external API keys. To enable generative LLMs:

### Option A: Gemini Cloud AI (Recommended)
1. Copy the environment template:
   ```bash
   cp .env.example .env
   ```
2. Add your Gemini API key in `.env`:
   ```env
   GEMINI_API_KEY="your-api-key-here"
   GEMINI_MODEL="gemini-3.5-flash"
   ```
3. Restart the backend (`make api`). The copilot tab will display `Gemini · cloud AI`.

### Option B: 100% Local Offline LLM (Ollama)
1. Install and start [Ollama](https://ollama.com/):
   ```bash
   ollama run qwen2.5:7b-instruct
   ```
2. The backend automatically detects the local Ollama instance on `http://127.0.0.1:11434` and makes the **Local (offline)** mode available in the dashboard.

---

## 📂 Repository Structure

```
stf-hw/
├── packages/
│   ├── stf_kernel/          # Physics engine: trajectories, S-curves, motor dynamics
│   └── stf_layout/          # Kinematic frame transforms and slot coordinate maps
├── services/
│   ├── api/                 # FastAPI REST & WebSocket server (ports, telemetry, copilot)
│   │   ├── chat.py          # LLM orchestration, verification, and session management
│   │   ├── grounding.py     # Deterministic domain tools & BM25 document search
│   │   └── runtime.py       # Async live factory simulation loop
│   └── sim/                 # Standalone simulation daemons & testing harnesses
├── stf-cad/
│   ├── hbw/                 # FreeCAD parametric model, collision proofs, and exporters
│   ├── hbw_model.py         # Parametric source of truth for all mechanical parts
│   └── sil/                 # MatIEC WebAssembly compiler for IEC 61131-3 logic
├── web/
│   ├── src/
│   │   ├── scene/           # Three.js / React Three Fiber 3D factory modules
│   │   ├── dashboard/       # 20+ operations dashboard views, charts, and guides
│   │   └── copilot/         # Chat client, audio/voice interface, and citation renderer
│   └── public/              # Exported CAD meshes, telemetry datasets, and knowledge bases
└── docs/                    # Architecture reports, hardware datasheets, and validation proofs
```

---

## 🧪 Testing & Validation

This project enforces strict validation gates across mechanical, kinematic, and software boundaries:

```bash
# Run backend Python tests (kernel, API, copilot, security)
make test

# Run frontend TypeScript type-checks and Vitest unit suite
cd web && npm test

# Run code linter
make lint

# Re-run full mathematical CAD collision and kinematic proofs (~25 min)
python3 stf-cad/hbw/validate.py
```

---

## 📚 Documentation Directory

* 📘 [Operations Dashboard Guide](docs/DASHBOARD_GUIDE.md) — Comprehensive walkthrough of all 20+ dashboard pages.
* 🚀 [Deployment Guide](docs/DEPLOY.md) — Production deployment with Docker, Render, and GitHub Pages.
* 🛡️ [Security & OT Architecture](docs/SECURITY.md) — IEC 62443 zone modeling, rate limits, and access tokens.
* 📐 [Hardware Ground Truth](docs/FACTORY_GROUND_TRUTH.md) — Physical specifications and factory dimensions.
* 🎙️ [Voice & TTS Pipeline](docs/TTS_PIPELINE.md) — Speech-to-text and text-to-speech audio architecture.
* 📜 [Upgrade Roadmap](docs/UPGRADE_PLAN.md) — Evolution of the digital twin across 18 development stages.

---

<p align="center">
  <sub>Built with ❤️ for industrial robotics, cyber-physical automation, and open-source engineering.</sub>
</p>

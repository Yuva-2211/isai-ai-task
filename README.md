# ⚡ Natural Language Workflow Generator

An enterprise GenAI system that transforms high-level natural language operational requirements into strongly-typed, validated, and executable Directed Acyclic Graph (DAG) workflows.

[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?logo=fastapi)](https://fastapi.tiangolo.com)
[![Streamlit](https://img.shields.io/badge/Frontend-Streamlit-FF4B4B?logo=streamlit)](https://streamlit.io)
[![Groq](https://img.shields.io/badge/LLM-Groq%20Llama%203.3-F55036)](https://groq.com)
[![SQLite](https://img.shields.io/badge/Database-SQLite3-003B57?logo=sqlite)](https://sqlite.org)

---

## 🎯 Problem Statement & Overview

Business stakeholders frequently understand business intent (e.g. *"If a refund request exceeds $500, check the fraud score, request manager authorization, then trigger Stripe"*), but cannot manually wire together REST APIs, data transformations, conditional checks, error fallbacks, and human approval steps.

This platform bridges that gap by compiling unstructured text into a machine-executable DAG with real-time visualization and a pause/resume runtime engine.

---

## 🏗 System Architecture

```
                       ┌───────────────────────────────┐
                       │     Streamlit User Portal     │
                       │  (Prompt, Graphviz, Approvals)│
                       └───────────────┬───────────────┘
                                       │ HTTP / In-Process
                                       ▼
                       ┌───────────────────────────────┐
                       │        FastAPI Backend        │
                       └──────┬─────────────────┬──────┘
                              │                 │
           1. NL Compilation  ▼                 ▼  2. Runtime & Execution
         ┌────────────────────────┐         ┌────────────────────────┐
         │     Groq LLM Client    │         │  Workflow DAG Engine   │
         │ (Llama-3.3 JSON Mode)  │         │ (Topological Traversal)│
         └───────────┬────────────┘         └───────────┬────────────┘
                     │                                  │
                     ▼ Validated JSON Spec              ▼ Persist State
         ┌────────────────────────┐         ┌────────────────────────┐
         │   Pydantic Validator   │         │    SQLite3 Database    │
         │  & Graph Cycle Checker │         │ (Runs, Steps, Pending) │
         └────────────────────────┘         └────────────────────────┘
                                                        │
                              ┌─────────────────────────┴────────────────────────┐
                              ▼                         ▼                        ▼
                       [Mock/Real APIs]        [Transformation/Tools]     [Human Approval]
                       (Stripe, Email, etc.)   (Math, JSON, Validation)  (Pause & Resume)
```

---

## 🧩 Supported Workflow Primitives (The 7 Node Types)

| Node Type | Functionality | Example |
| :--- | :--- | :--- |
| **`validation`** | Enforces schemas, required keys, thresholds, or regex rules | `amount > 0` and `email` contains `@` |
| **`tool`** | Deterministic computational modules & scoring algorithms | `fraud_detector`, `sentiment_analyzer`, `calculate_tax` |
| **`api`** | External REST integrations (supports mock sandbox & live HTTP) | `POST https://api.stripe.com/v1/refunds` |
| **`transform`** | Dynamic schema reshaping & mustache context interpolation | Maps `{ "total": "{{amount}} + {{tax}}" }` |
| **`condition`** | Boolean expression evaluation for dynamic graph branching | `amount > 500 or nodes.step_fraud.output.risk_score > 0.6` |
| **`human_approval`** | Pauses workflow execution state until an authorized role approves/rejects | Prompts manager to review high-value refund |
| **`notification`** | Dispatches operational alerts or customer emails | Sends Slack ping `#finance-ops` or customer receipt |

---

## 🚀 Quickstart Guide

### 1. Prerequisites
- Python 3.9+ installed
- Git

### 2. Installation
```bash
git clone https://github.com/Yuva-2211/isai-ai-task.git
cd isai-ai-task

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Environment Configuration (Optional)
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Add your Groq API Key:
```env
GROQ_API_KEY=gsk_your_groq_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile
```
*(Note: If no API key is provided, the platform automatically switches to high-fidelity template synthesis, enabling full testing without an API key!)*

### 4. Running the Application

#### Option A: Launch Interactive Streamlit UI
```bash
streamlit run app.py
```
Open your browser at `http://localhost:8501`.

#### Option B: Launch FastAPI Backend
```bash
uvicorn src.api.main:app --reload --port 8000
```
API Documentation (Swagger UI) is available at `http://localhost:8000/docs`.

---

## 🧪 Demonstration & Test Scenarios

### Scenario 1: E-Commerce Refund & Fraud Guard
- **Natural Language Prompt**:
  > *"When a refund request arrives, validate that amount is positive and email is valid. Run the fraud detector tool. If amount > $500 or risk score > 0.65, request manager approval. Once approved, call the Stripe refund API. If Stripe fails, alert support on Slack. Finally send a confirmation email to customer."*
- **Execution Path**:
  1. `Validation`: Checks `amount > 0` and email validity.
  2. `Tool (Fraud Detector)`: Evaluates transaction risk score.
  3. `Condition`: Evaluates threshold logic.
  4. `Human Approval`: Workflow engine **pauses** in `WAITING_APPROVAL` status.
  5. `Human Action`: Reviewer clicks **"Approve & Continue"**.
  6. `API Call`: Invokes Stripe Gateway.
  7. `Notification`: Dispatches confirmation email.

---

## 📁 Repository Structure

```
isai-ai-task/
├── docs/
│   ├── DESIGN_DOCUMENT.md      # Comprehensive Architecture & State Machine Design
│   └── WORKFLOW_SCHEMA.md      # Standard JSON DAG Specification Contract
├── src/
│   ├── models/
│   │   └── schema.py           # Pydantic Schemas (Nodes, Edges, Executions, Approvals)
│   ├── database/
│   │   └── db.py               # SQLite3 Persistence Layer
│   ├── engine/
│   │   ├── runner.py           # DAG State Machine with Pause/Resume
│   │   ├── evaluator.py        # Safe Expression Evaluator & Template Interpolator
│   │   └── tool_registry.py    # Integrations, Tools, APIs, and Transformers
│   ├── generator/
│   │   ├── groq_client.py      # Groq Llama 3 Compiler with JSON mode
│   │   └── templates.py        # Pre-built Business Workflow Blueprints
│   └── api/
│       └── main.py             # FastAPI REST Endpoints
├── app.py                      # Streamlit Visualizer & Interactive Console
├── requirements.txt            # Project Dependencies
├── .env.example                # Environment Variable Template
├── .gitignore                  # Git Ignore configuration
└── README.md                   # Documentation
```

---

## 🛡 Robustness & Error Handling
- **AST Expression Sandbox**: Conditions are parsed through a syntax tree to prevent arbitrary code injection.
- **Durable Persistence**: State is snapshotted into SQLite at every node transition, ensuring executions survive server restarts.
- **Retry Policies**: Configurable retries with backoff and automatic fallback rerouting.

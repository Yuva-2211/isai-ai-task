import streamlit as st
import json
import os
import time
import httpx
from typing import Dict, Any

from dotenv import load_dotenv
load_dotenv()

from src.models.schema import (
    WorkflowDefinition,
    ExecutionStatus,
    NodeType
)

# Backend API Base URL
API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")

# Page Configuration
st.set_page_config(
    page_title="GenAI Natural Language Workflow Generator",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling
st.markdown("""
<style>
    .reportview-container {
        background: #0e1117;
    }
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        background: linear-gradient(90deg, #4F46E5, #06B6D4);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 1.05rem;
        color: #94A3B8;
        margin-bottom: 1.5rem;
    }
    .approval-card {
        background-color: rgba(245, 158, 11, 0.1);
        border: 2px solid #F59E0B;
        border-radius: 8px;
        padding: 1.2rem;
        margin-top: 1rem;
        margin-bottom: 1rem;
    }
    .success-card {
        background-color: rgba(16, 185, 129, 0.1);
        border: 1px solid #10B981;
        border-radius: 8px;
        padding: 1rem;
        margin-bottom: 1rem;
    }
    .rejected-card {
        background-color: rgba(220, 38, 38, 0.1);
        border: 1px solid #DC2626;
        border-radius: 8px;
        padding: 1rem;
        margin-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)


# ─── API Client Helpers ──────────────────────────────────

def api_generate_workflow(prompt: str) -> Dict[str, Any]:
    """POST /api/workflows/generate — calls FastAPI backend."""
    resp = httpx.post(f"{API_BASE}/api/workflows/generate", json={"prompt": prompt}, timeout=30)
    resp.raise_for_status()
    return resp.json()

def api_execute_workflow(workflow_id: str, input_payload: Dict[str, Any]) -> Dict[str, Any]:
    """POST /api/workflows/{id}/execute — calls FastAPI backend."""
    resp = httpx.post(f"{API_BASE}/api/workflows/{workflow_id}/execute", json=input_payload, timeout=30)
    resp.raise_for_status()
    return resp.json()

def api_get_execution(execution_id: str) -> Dict[str, Any]:
    """GET /api/executions/{id} — calls FastAPI backend."""
    resp = httpx.get(f"{API_BASE}/api/executions/{execution_id}", timeout=10)
    resp.raise_for_status()
    return resp.json()

def api_decide(execution_id: str, decision: str, comment: str) -> Dict[str, Any]:
    """POST /api/executions/{id}/decision — calls FastAPI backend."""
    resp = httpx.post(
        f"{API_BASE}/api/executions/{execution_id}/decision",
        json={"decision": decision, "comment": comment},
        timeout=30
    )
    resp.raise_for_status()
    return resp.json()

def api_list_workflows():
    """GET /api/workflows"""
    resp = httpx.get(f"{API_BASE}/api/workflows", timeout=10)
    resp.raise_for_status()
    return resp.json()

def check_backend_health() -> bool:
    try:
        resp = httpx.get(f"{API_BASE}/api/health", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


# ─── Graphviz Renderer ───────────────────────────────────

def render_workflow_graph(workflow_data: Dict, current_node_id: str = None, execution_logs: list = None):
    node_status_map = {}
    if execution_logs:
        for log in execution_logs:
            node_status_map[log["node_id"]] = log["status"]

    dot_lines = [
        'digraph G {',
        '  rankdir="TB";',
        '  graph [bgcolor="transparent", fontname="Inter, Arial"];',
        '  node [fontname="Inter, Arial", style="filled,rounded", shape="box", margin="0.2,0.1"];',
        '  edge [fontname="Inter, Arial", fontsize=10, color="#64748B"];'
    ]

    type_styles = {
        "validation": 'fillcolor="#E0F2FE", fontcolor="#0369A1", color="#0284C7"',
        "tool": 'fillcolor="#DCFCE7", fontcolor="#15803D", color="#16A34A"',
        "api": 'fillcolor="#F3E8FF", fontcolor="#7E22CE", color="#9333EA"',
        "condition": 'fillcolor="#FEF3C7", fontcolor="#B45309", color="#D97706", shape="diamond"',
        "human_approval": 'fillcolor="#FFEDD5", fontcolor="#C2410C", color="#EA580C", shape="hexagon"',
        "transform": 'fillcolor="#F1F5F9", fontcolor="#334155", color="#64748B"',
        "notification": 'fillcolor="#CCFBF1", fontcolor="#0F766E", color="#0D9488"'
    }

    for node in workflow_data.get("nodes", []):
        nid = node["id"]
        ntype = node["type"]
        style = type_styles.get(ntype, 'fillcolor="#F8FAFC", fontcolor="#1E293B", color="#94A3B8"')

        status_suffix = ""
        if nid == current_node_id:
            style += ', penwidth=3, color="#EC4899"'
            status_suffix = "\\n(⏳ CURRENT)"
        elif nid in node_status_map:
            st_val = node_status_map[nid]
            if st_val == "SUCCESS":
                status_suffix = "\\n(✓ DONE)"
            elif st_val == "WAITING_APPROVAL":
                status_suffix = "\\n(⏸ AWAITING)"
            elif st_val == "FAILED":
                status_suffix = "\\n(✕ FAILED)"
            elif st_val == "REJECTED":
                status_suffix = "\\n(✕ REJECTED)"

        label_escaped = node["label"].replace('"', '\\"') + status_suffix
        dot_lines.append(f'  "{nid}" [label="{label_escaped}", {style}];')

    for edge in workflow_data.get("edges", []):
        edge_label = ""
        if edge.get("condition_branch") == "true":
            edge_label = ' [label=" TRUE", fontcolor="#16A34A", color="#16A34A", penwidth=1.5]'
        elif edge.get("condition_branch") == "false":
            edge_label = ' [label=" FALSE", fontcolor="#DC2626", color="#DC2626", penwidth=1.5]'
        dot_lines.append(f'  "{edge["from_node"]}" -> "{edge["to_node"]}"{edge_label};')

    dot_lines.append('}')
    return "\n".join(dot_lines)


# ─── Sidebar ─────────────────────────────────────────────

with st.sidebar:
    st.image("https://img.icons8.com/isometric/100/workflow.png", width=64)
    st.title("Workflow Studio")
    st.markdown("Convert plain English into enterprise-grade executable DAGs.")

    st.subheader("LLM Configuration")
    user_api_key = st.text_input("Groq API Key (Optional)", type="password",
                                 help="Leave blank to use environment key or smart demo templates.")
    if user_api_key:
        os.environ["GROQ_API_KEY"] = user_api_key

    groq_model = st.selectbox(
        "LLM Model",
        ["openai/gpt-oss-120b", "llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
        index=0
    )
    os.environ["GROQ_MODEL"] = groq_model

    st.divider()

    # Backend health
    backend_alive = check_backend_health()
    if backend_alive:
        st.success("🟢 FastAPI Backend Connected")
    else:
        st.warning("🔴 FastAPI Backend Offline — using in-process engine")

    st.divider()
    st.subheader("Quick-Load Templates")
    template_choices = ["-- Select --", "High-Value Refund & Fraud Guard", "Employee IT & Access Provisioning"]
    selected_template_name = st.selectbox("Blueprint:", template_choices)


# ─── Header ──────────────────────────────────────────────

st.markdown('<div class="main-header">⚡ Natural Language Workflow Generator</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Compile business objectives into deterministic, executable DAGs with APIs, validation, conditional branching, and human approval gates.</div>', unsafe_allow_html=True)

# State init
if "current_workflow" not in st.session_state:
    st.session_state.current_workflow = None
if "current_execution" not in st.session_state:
    st.session_state.current_execution = None

# Template loading
if selected_template_name != "-- Select --":
    if st.button(f"📋 Load '{selected_template_name}'"):
        # Use in-process templates since they're lightweight
        from src.generator.templates import get_template_as_workflow
        from src.database.db import save_workflow
        tid = "wf_refund_guard" if "Refund" in selected_template_name else "wf_employee_onboarding"
        wf = get_template_as_workflow(tid)
        save_workflow(wf)
        st.session_state.current_workflow = wf.model_dump()
        st.session_state.current_execution = None
        st.rerun()


# ─── Tabs ────────────────────────────────────────────────

tab_gen, tab_run = st.tabs(["🛠 1. Generator & Flow Graph", "🚀 2. Live Execution & Approval Gate"])


# TAB 1: GENERATOR & FLOW GRAPH
with tab_gen:
    col_input, col_graph = st.columns([1, 1])

    with col_input:
        st.subheader("Natural Language Objective")

        default_prompt = (
            "When a refund request arrives, validate that amount is positive and email is valid. "
            "Run the fraud detector tool. If amount > $500 or risk score > 0.65, request manager approval. "
            "Once approved, call the Stripe refund API. If Stripe fails, alert support on Slack. "
            "Finally send a confirmation email to customer."
        )

        prompt_input = st.text_area(
            "Describe the business process to automate:",
            value=default_prompt,
            height=140
        )

        if st.button("✨ Compile into Workflow", type="primary", use_container_width=True):
            with st.spinner("AI analyzing intent and constructing DAG..."):
                try:
                    if backend_alive:
                        wf_data = api_generate_workflow(prompt_input)
                    else:
                        from src.generator.groq_client import generate_workflow_from_prompt
                        from src.database.db import save_workflow
                        wf = generate_workflow_from_prompt(prompt_input, user_api_key)
                        save_workflow(wf)
                        wf_data = wf.model_dump()

                    st.session_state.current_workflow = wf_data
                    st.session_state.current_execution = None
                    st.success(f"Generated workflow: {wf_data['name']} ({len(wf_data['nodes'])} steps)")
                    st.rerun()
                except Exception as e:
                    st.error(f"Compilation error: {e}")

        st.markdown("---")
        wf = st.session_state.current_workflow
        if wf:
            st.markdown(f"**Loaded Workflow**: `{wf['name']}`")
            st.markdown(f"**Description**: {wf['description']}")
            st.markdown(f"**Entrypoint**: `{wf['entrypoint']}`")
            st.markdown(f"**Node Count**: `{len(wf['nodes'])}` | **Edge Count**: `{len(wf['edges'])}`")
        else:
            st.info("No workflow loaded. Type a prompt above or select a template from the sidebar.")

    with col_graph:
        st.subheader("Interactive Visual Graph (DAG)")
        if st.session_state.current_workflow:
            exec_data = st.session_state.current_execution
            dot_code = render_workflow_graph(
                st.session_state.current_workflow,
                current_node_id=exec_data.get("current_node_id") if exec_data else None,
                execution_logs=exec_data.get("logs") if exec_data else None
            )
            st.graphviz_chart(dot_code, use_container_width=True)
        else:
            st.info("Generate or load a workflow to see the visual DAG here.")


# TAB 2: LIVE EXECUTION & APPROVAL GATE
with tab_run:
    col_run_config, col_run_console = st.columns([1, 2])

    with col_run_config:
        st.subheader("Trigger Parameters")
        st.caption("Provide mock initial payload to feed into workflow entrypoint:")

        wf = st.session_state.current_workflow
        sample = wf.get("sample_input", {}) if wf else {}
        sample_input_str = json.dumps(sample, indent=2)
        user_input_json = st.text_area("Initial Input Payload (JSON)", value=sample_input_str, height=180)

        if st.button("▶ Start Workflow Execution", type="primary", use_container_width=True):
            if not wf:
                st.error("No workflow loaded. Generate or load one first.")
            else:
                try:
                    parsed_input = json.loads(user_input_json)
                    wf_id = wf["id"]

                    if backend_alive:
                        exec_data = api_execute_workflow(wf_id, parsed_input)
                    else:
                        from src.engine.runner import WorkflowRunner
                        from src.database.db import save_workflow as sw
                        wf_obj = WorkflowDefinition.model_validate(wf)
                        sw(wf_obj)
                        exec_obj = WorkflowRunner.initialize_execution(wf_obj, parsed_input)
                        updated = WorkflowRunner.run_step_by_step(exec_obj.id)
                        exec_data = updated.model_dump()

                    st.session_state.current_execution = exec_data
                    st.rerun()
                except Exception as e:
                    st.error(f"Execution failed to start: {e}")

    with col_run_console:
        st.subheader("Runtime Execution Console")
        exec_data = st.session_state.current_execution

        if not exec_data:
            st.info("No active execution. Click 'Start Workflow Execution' to run.")
        else:
            status = exec_data["status"]
            status_colors = {
                "RUNNING": "orange", "WAITING_APPROVAL": "orange",
                "COMPLETED": "green", "FAILED": "red", "REJECTED": "red"
            }
            color = status_colors.get(status, "grey")
            st.markdown(f"**Execution ID**: `{exec_data['id']}` | **Status**: :{color}[**{status}**]")

            # HUMAN APPROVAL GATE
            if status == "WAITING_APPROVAL" and exec_data.get("pending_approval"):
                approval = exec_data["pending_approval"]
                st.markdown(f"""
                <div class="approval-card">
                    <h4 style="color: #D97706; margin-top: 0;">⏸ Human Approval Required</h4>
                    <p><b>Prompt:</b> {approval['prompt']}</p>
                    <p><b>Required Role:</b> <span style="background: #FDE68A; color: #78350F; padding: 2px 6px; border-radius: 4px;">{approval.get('required_role', 'Manager')}</span></p>
                </div>
                """, unsafe_allow_html=True)

                appr_comment = st.text_input("Reviewer Comment / Reason:", value="Verified risk criteria and authorized.")

                btn_col1, btn_col2 = st.columns(2)
                with btn_col1:
                    if st.button("✅ Approve & Continue", type="primary", use_container_width=True):
                        with st.spinner("Processing approval and resuming downstream steps..."):
                            try:
                                if backend_alive:
                                    result = api_decide(exec_data["id"], "APPROVE", appr_comment)
                                else:
                                    from src.engine.runner import WorkflowRunner
                                    resumed = WorkflowRunner.resume_approval(exec_data["id"], "APPROVE", appr_comment)
                                    result = resumed.model_dump()
                                st.session_state.current_execution = result
                                st.rerun()
                            except Exception as e:
                                st.error(f"Approval error: {e}")
                with btn_col2:
                    if st.button("❌ Reject Workflow", use_container_width=True):
                        with st.spinner("Rejecting workflow..."):
                            try:
                                if backend_alive:
                                    result = api_decide(exec_data["id"], "REJECT", appr_comment)
                                else:
                                    from src.engine.runner import WorkflowRunner
                                    resumed = WorkflowRunner.resume_approval(exec_data["id"], "REJECT", appr_comment)
                                    result = resumed.model_dump()
                                st.session_state.current_execution = result
                                st.rerun()
                            except Exception as e:
                                st.error(f"Rejection error: {e}")

            elif status == "COMPLETED":
                st.markdown("""
                <div class="success-card">
                    <h4 style="color: #059669; margin: 0;">🎉 Workflow Successfully Completed!</h4>
                    <p style="margin: 0.5rem 0 0 0; color: #065F46;">All operations, data transformations, and external API calls finished.</p>
                </div>
                """, unsafe_allow_html=True)

            elif status == "REJECTED":
                st.markdown("""
                <div class="rejected-card">
                    <h4 style="color: #DC2626; margin: 0;">🚫 Workflow Rejected</h4>
                    <p style="margin: 0.5rem 0 0 0; color: #991B1B;">The workflow was rejected by the human approver.</p>
                </div>
                """, unsafe_allow_html=True)

            # Step-by-Step Audit Trail
            logs = exec_data.get("logs", [])
            if logs:
                st.markdown("#### Step Execution Audit Trail")
                for i, log in enumerate(logs):
                    badge = "✅" if log["status"] == "SUCCESS" else ("⏸" if log["status"] == "WAITING_APPROVAL" else "❌")
                    with st.expander(f"{badge} Step {i+1}: {log['label']} ({log['node_type']}) — {log['execution_time_ms']} ms"):
                        col_l, col_r = st.columns(2)
                        with col_l:
                            st.markdown("**Inputs / Config:**")
                            st.json(log.get("input_data", {}))
                        with col_r:
                            st.markdown("**Outputs / Result:**")
                            st.json(log.get("output_data", {}))
                            if log.get("error_message"):
                                st.error(f"Error: {log['error_message']}")

import streamlit as st
import json
import os
import time
import httpx
from typing import Dict, Any, Optional

from src.models.schema import (
    WorkflowDefinition,
    WorkflowExecution,
    ExecutionStatus,
    NodeType
)
from src.database.db import (
    save_workflow,
    get_workflow,
    list_workflows,
    get_execution
)
from src.generator.groq_client import generate_workflow_from_prompt
from src.generator.templates import get_predefined_templates, get_template_as_workflow
from src.engine.runner import WorkflowRunner

# Backend Configuration
BACKEND_BASE_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

# Page Configuration - No Sidebar
st.set_page_config(
    page_title="GenAI Natural Language Workflow Generator",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom Styling
st.markdown("""
<style>
    [data-testid="stSidebar"] {
        display: none;
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
        margin-bottom: 1.2rem;
    }
    .status-bar {
        background-color: #1E293B;
        border: 1px solid #334155;
        border-radius: 6px;
        padding: 0.5rem 1rem;
        margin-bottom: 1.2rem;
        font-size: 0.88rem;
        display: flex;
        align-items: center;
        gap: 0.75rem;
    }
    .status-online {
        color: #10B981;
        font-weight: 600;
    }
    .status-offline {
        color: #F59E0B;
        font-weight: 600;
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
        background-color: rgba(239, 68, 68, 0.1);
        border: 1px solid #EF4444;
        border-radius: 8px;
        padding: 1rem;
        margin-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)

# --- Backend HTTP Client Helpers ---

def check_backend_health() -> bool:
    try:
        resp = httpx.get(f"{BACKEND_BASE_URL}/api/health", timeout=1.5)
        return resp.status_code == 200
    except Exception:
        return False

def api_generate_workflow(prompt: str) -> WorkflowDefinition:
    """Calls FastAPI POST /api/workflows/generate with fallback to in-process compiler."""
    try:
        resp = httpx.post(
            f"{BACKEND_BASE_URL}/api/workflows/generate",
            json={"prompt": prompt},
            timeout=30.0
        )
        if resp.status_code == 200:
            return WorkflowDefinition.model_validate(resp.json())
    except Exception as e:
        print(f"[HTTP] Backend API generate failed: {e}. Using in-process compiler.")
    
    # In-process execution fallback
    wf = generate_workflow_from_prompt(prompt)
    save_workflow(wf)
    return wf

def api_execute_workflow(workflow_id: str, input_payload: Dict[str, Any]) -> WorkflowExecution:
    """Calls FastAPI POST /api/workflows/{id}/execute with fallback to in-process runner."""
    try:
        resp = httpx.post(
            f"{BACKEND_BASE_URL}/api/workflows/{workflow_id}/execute",
            json=input_payload,
            timeout=15.0
        )
        if resp.status_code == 200:
            return WorkflowExecution.model_validate(resp.json())
    except Exception as e:
        print(f"[HTTP] Backend API execute failed: {e}. Using in-process runner.")

    # In-process execution fallback
    wf = get_workflow(workflow_id)
    exec_obj = WorkflowRunner.initialize_execution(wf, input_payload)
    return WorkflowRunner.run_step_by_step(exec_obj.id)

def api_submit_decision(execution_id: str, decision: str, comment: str) -> WorkflowExecution:
    """Calls FastAPI POST /api/executions/{id}/decision with fallback to in-process runner."""
    try:
        resp = httpx.post(
            f"{BACKEND_BASE_URL}/api/executions/{execution_id}/decision",
            json={"decision": decision, "comment": comment},
            timeout=15.0
        )
        if resp.status_code == 200:
            return WorkflowExecution.model_validate(resp.json())
    except Exception as e:
        print(f"[HTTP] Backend API decision failed: {e}. Using in-process runner.")

    # In-process execution fallback
    return WorkflowRunner.resume_approval(execution_id, decision, comment)

# Helper: Render Graphviz Chart
def render_workflow_graph(workflow: WorkflowDefinition, current_node_id: str = None, execution_logs: list = None):
    node_status_map = {}
    if execution_logs:
        for log in execution_logs:
            node_status_map[log.node_id] = log.status

    dot_lines = [
        'digraph G {',
        '  rankdir="TB";',
        '  graph [bgcolor="transparent", fontname="Inter, Arial"];',
        '  node [fontname="Inter, Arial", style="filled,rounded", shape="box", margin="0.2,0.1"];',
        '  edge [fontname="Inter, Arial", fontsize=10, color="#64748B"];'
    ]

    type_styles = {
        NodeType.VALIDATION: 'fillcolor="#E0F2FE", fontcolor="#0369A1", color="#0284C7"',
        NodeType.TOOL: 'fillcolor="#DCFCE7", fontcolor="#15803D", color="#16A34A"',
        NodeType.API: 'fillcolor="#F3E8FF", fontcolor="#7E22CE", color="#9333EA"',
        NodeType.CONDITION: 'fillcolor="#FEF3C7", fontcolor="#B45309", color="#D97706", shape="diamond"',
        NodeType.HUMAN_APPROVAL: 'fillcolor="#FFEDD5", fontcolor="#C2410C", color="#EA580C", shape="hexagon"',
        NodeType.TRANSFORM: 'fillcolor="#F1F5F9", fontcolor="#334155", color="#64748B"',
        NodeType.NOTIFICATION: 'fillcolor="#CCFBF1", fontcolor="#0F766E", color="#0D9488"'
    }

    for node in workflow.nodes:
        style = type_styles.get(node.type, 'fillcolor="#F8FAFC", fontcolor="#1E293B", color="#94A3B8"')
        status_suffix = ""
        if node.id == current_node_id:
            style += ', penwidth=3, color="#EC4899"'
            status_suffix = "\\n(CURRENT)"
        elif node.id in node_status_map:
            st_val = node_status_map[node.id]
            if st_val == "SUCCESS":
                status_suffix = "\\n(SUCCESS)"
            elif st_val == "WAITING_APPROVAL":
                status_suffix = "\\n(WAITING APPROVAL)"
            elif st_val == "FAILED":
                status_suffix = "\\n(FAILED)"

        label_escaped = node.label.replace('"', '\\"') + status_suffix
        dot_lines.append(f'  "{node.id}" [label="{label_escaped}", {style}];')

    for edge in workflow.edges:
        edge_label = ""
        if edge.condition_branch == "true":
            edge_label = ' [label=" TRUE", fontcolor="#16A34A", color="#16A34A", penwidth=1.5]'
        elif edge.condition_branch == "false":
            edge_label = ' [label=" FALSE", fontcolor="#DC2626", color="#DC2626", penwidth=1.5]'
        dot_lines.append(f'  "{edge.from_node}" -> "{edge.to_node}"{edge_label};')

    dot_lines.append('}')
    return "\n".join(dot_lines)

# State initialization
if "current_workflow" not in st.session_state:
    st.session_state.current_workflow = get_template_as_workflow("wf_refund_guard")

if "current_execution" not in st.session_state:
    st.session_state.current_execution = None

if "prompt_text" not in st.session_state:
    st.session_state.prompt_text = (
        "When a refund request arrives, validate that amount is positive and email is valid. "
        "Run the fraud detector tool. If amount > $500 or risk score > 0.65, request manager approval. "
        "Once approved, call the Stripe refund API. If Stripe fails, alert support on Slack. "
        "Finally send a confirmation email to customer."
    )

# --- Header ---
st.markdown('<div class="main-header">Natural Language Workflow Generator</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Compile business objectives into deterministic, executable DAGs with APIs, validation, conditional branching, and human approval gates.</div>', unsafe_allow_html=True)

# Live Backend Health Status Bar
backend_online = check_backend_health()
status_class = "status-online" if backend_online else "status-offline"
status_text = f"Connected ({BACKEND_BASE_URL})" if backend_online else f"Direct Engine Mode ({BACKEND_BASE_URL} offline)"
st.markdown(f"""
<div class="status-bar">
    <span><b>Backend Engine:</b> <span class="{status_class}">{status_text}</span></span>
    <span style="color: #64748B;">|</span>
    <span><b>Execution Mode:</b> REST API / In-Process Fallback</span>
</div>
""", unsafe_allow_html=True)

# Quick Preset Buttons
st.markdown("**Quick Preset Scenarios:**")
pcol1, pcol2, pcol3, pcol4 = st.columns(4)

with pcol1:
    if st.button("Refund & Fraud Guard", use_container_width=True):
        st.session_state.prompt_text = (
            "When a refund request arrives, validate that amount is positive and email is valid. "
            "Run the fraud detector tool. If amount > $500 or risk score > 0.65, request manager approval. "
            "Once approved, call the Stripe refund API and notify the customer via email."
        )
        st.session_state.current_workflow = api_generate_workflow(st.session_state.prompt_text)
        st.session_state.current_execution = None
        st.rerun()

with pcol2:
    if st.button("Loan Underwriting", use_container_width=True):
        st.session_state.prompt_text = (
            "When customer loan application arrives, validate amount > 1000 and email format. "
            "Run fraud risk assessment. If amount >= 5000 or risk score > 0.65, require credit officer human approval. "
            "Once approved, disburse funds via Core Banking ACH API and notify the applicant."
        )
        st.session_state.current_workflow = api_generate_workflow(st.session_state.prompt_text)
        st.session_state.current_execution = None
        st.rerun()

with pcol3:
    if st.button("Customer Support Triage", use_container_width=True):
        st.session_state.prompt_text = (
            "When a customer support ticket arrives, validate ticket ID and email. "
            "Analyze customer sentiment. If priority is HIGH or sentiment is NEGATIVE, escalate to support lead for approval. "
            "Once approved, create a Jira priority incident and alert support channel on Slack."
        )
        st.session_state.current_workflow = api_generate_workflow(st.session_state.prompt_text)
        st.session_state.current_execution = None
        st.rerun()

with pcol4:
    if st.button("Employee IT Access", use_container_width=True):
        st.session_state.prompt_text = (
            "When a new employee onboarding request arrives, validate corporate email and role. "
            "If role is DevOps or Admin, require IT Security Manager approval. "
            "Once approved, provision AWS and Okta access, and post a welcome message to Slack."
        )
        st.session_state.current_workflow = api_generate_workflow(st.session_state.prompt_text)
        st.session_state.current_execution = None
        st.rerun()

st.markdown("---")

# Main Tabs
tab_gen, tab_run = st.tabs(["1. Generator & Flow Graph", "2. Live Execution & Approval Gate"])

# TAB 1: GENERATOR & FLOW GRAPH
with tab_gen:
    col_input, col_graph = st.columns([1, 1])

    with col_input:
        st.subheader("Natural Language Objective")
        
        prompt_input = st.text_area(
            "Describe any operational workflow to compile:",
            value=st.session_state.prompt_text,
            height=140
        )

        if st.button("Compile into Workflow", type="primary", use_container_width=True):
            with st.spinner("Analyzing intent and compiling executable DAG..."):
                try:
                    wf = api_generate_workflow(prompt_input)
                    st.session_state.current_workflow = wf
                    st.session_state.current_execution = None
                    st.session_state.prompt_text = prompt_input
                    st.success(f"Successfully compiled: {wf.name} ({len(wf.nodes)} steps)")
                    st.rerun()
                except Exception as e:
                    st.error(f"Compilation error: {e}")

        st.markdown("---")
        st.markdown(f"**Loaded Workflow**: `{st.session_state.current_workflow.name}`")
        st.markdown(f"**Description**: {st.session_state.current_workflow.description}")
        st.markdown(f"**Entrypoint**: `{st.session_state.current_workflow.entrypoint}`")
        st.markdown(f"**Node Count**: `{len(st.session_state.current_workflow.nodes)}` | **Edge Count**: `{len(st.session_state.current_workflow.edges)}`")

    with col_graph:
        st.subheader("Visual Graph (DAG)")
        dot_code = render_workflow_graph(
            st.session_state.current_workflow,
            current_node_id=st.session_state.current_execution.current_node_id if st.session_state.current_execution else None,
            execution_logs=st.session_state.current_execution.logs if st.session_state.current_execution else None
        )
        st.graphviz_chart(dot_code, use_container_width=True)

# TAB 2: LIVE EXECUTION & APPROVAL GATE
with tab_run:
    col_run_config, col_run_console = st.columns([1, 2])

    with col_run_config:
        st.subheader("Trigger Parameters")
        st.caption("Provide mock initial payload to feed into workflow entrypoint:")
        
        sample_input_str = json.dumps(st.session_state.current_workflow.sample_input, indent=2)
        user_input_json = st.text_area("Initial Input Payload (JSON)", value=sample_input_str, height=180)

        if st.button("Start Workflow Execution", type="primary", use_container_width=True):
            try:
                parsed_input = json.loads(user_input_json)
                wf = st.session_state.current_workflow
                save_workflow(wf)
                
                with st.spinner("Dispatching execution to workflow engine..."):
                    updated_exec = api_execute_workflow(wf.id, parsed_input)
                    st.session_state.current_execution = updated_exec
                    st.rerun()
            except Exception as e:
                st.error(f"Execution failed to start: {e}")

    with col_run_console:
        st.subheader("Runtime Execution Console")

        curr_exec = st.session_state.current_execution
        if not curr_exec:
            st.info("No active execution. Click 'Start Workflow Execution' to run.")
        else:
            status_colors = {
                ExecutionStatus.RUNNING: "orange",
                ExecutionStatus.WAITING_APPROVAL: "gold",
                ExecutionStatus.COMPLETED: "green",
                ExecutionStatus.FAILED: "red",
                ExecutionStatus.REJECTED: "red"
            }
            color = status_colors.get(curr_exec.status, "grey")
            st.markdown(f"**Execution ID**: `{curr_exec.id}` | **Status**: :{color}[**{curr_exec.status.value}**]")

            # HUMAN APPROVAL GATE INTERFACE
            if curr_exec.status == ExecutionStatus.WAITING_APPROVAL and curr_exec.pending_approval:
                st.markdown(f"""
                <div class="approval-card">
                    <h4 style="color: #D97706; margin-top: 0;">Human Approval Required</h4>
                    <p><b>Prompt:</b> {curr_exec.pending_approval.prompt}</p>
                    <p><b>Required Role:</b> <span style="background: #FDE68A; color: #78350F; padding: 2px 6px; border-radius: 4px;">{curr_exec.pending_approval.required_role}</span></p>
                </div>
                """, unsafe_allow_html=True)

                appr_comment = st.text_input("Reviewer Comment / Reason:", value="Verified risk criteria and authorized.")
                
                btn_col1, btn_col2 = st.columns(2)
                with btn_col1:
                    if st.button("Approve & Continue", type="primary", use_container_width=True):
                        with st.spinner("Processing approval and resuming downstream steps..."):
                            resumed = api_submit_decision(curr_exec.id, "APPROVE", appr_comment)
                            st.session_state.current_execution = resumed
                            st.rerun()
                with btn_col2:
                    if st.button("Reject Workflow", use_container_width=True):
                        with st.spinner("Rejecting workflow..."):
                            resumed = api_submit_decision(curr_exec.id, "REJECT", appr_comment)
                            st.session_state.current_execution = resumed
                            st.rerun()

            elif curr_exec.status == ExecutionStatus.COMPLETED:
                st.markdown("""
                <div class="success-card">
                    <h4 style="color: #059669; margin: 0;">Workflow Successfully Completed</h4>
                    <p style="margin: 0.5rem 0 0 0; color: #065F46;">All operations, data transformations, and external API calls finished.</p>
                </div>
                """, unsafe_allow_html=True)

            elif curr_exec.status == ExecutionStatus.REJECTED:
                st.markdown("""
                <div class="rejected-card">
                    <h4 style="color: #EF4444; margin: 0;">Workflow Terminated (Rejected)</h4>
                    <p style="margin: 0.5rem 0 0 0; color: #991B1B;">The human reviewer rejected this execution. Downstream actions have been blocked.</p>
                </div>
                """, unsafe_allow_html=True)

            # Step-by-Step Logs Viewer
            st.markdown("#### Step Execution Audit Trail")
            for i, log in enumerate(curr_exec.logs):
                badge_icon = "[PASS]" if log.status == "SUCCESS" else ("[PENDING]" if log.status == "WAITING_APPROVAL" else "[FAILED]")
                with st.expander(f"{badge_icon} Step {i+1}: {log.label} ({log.node_type}) - {log.execution_time_ms} ms"):
                    col_l, col_r = st.columns(2)
                    with col_l:
                        st.markdown("**Inputs / Config:**")
                        st.json(log.input_data)
                    with col_r:
                        st.markdown("**Outputs / Result:**")
                        st.json(log.output_data)
                        if log.error_message:
                            st.error(f"Error: {log.error_message}")

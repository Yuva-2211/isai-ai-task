import streamlit as st
import json
import os
import time
from typing import Dict, Any

from src.models.schema import (
    WorkflowDefinition,
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
    .badge {
        padding: 4px 8px;
        border-radius: 4px;
        font-size: 0.8rem;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

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

    # Node styling dictionary based on type
    type_styles = {
        NodeType.VALIDATION: 'fillcolor="#E0F2FE", fontcolor="#0369A1", color="#0284C7"',
        NodeType.TOOL: 'fillcolor="#DCFCE7", fontcolor="#15803D", color="#16A34A"',
        NodeType.API: 'fillcolor="#F3E8FF", fontcolor="#7E22CE", color="#9333EA"',
        NodeType.CONDITION: 'fillcolor="#FEF3C7", fontcolor="#B45309", color="#D97706", shape="diamond"',
        NodeType.HUMAN_APPROVAL: 'fillcolor="#FFEDD5", fontcolor="#C2410C", color="#EA580C", shape="hexagon"',
        NodeType.TRANSFORM: 'fillcolor="#F1F5F9", fontcolor="#334155", color="#64748B"',
        NodeType.NOTIFICATION: 'fillcolor="#CCFBF1", fontcolor="#0F766E", color="#0D9488"'
    }

    # Add Nodes
    for node in workflow.nodes:
        style = type_styles.get(node.type, 'fillcolor="#F8FAFC", fontcolor="#1E293B", color="#94A3B8"')
        
        # Highlight active node or status
        status_suffix = ""
        if node.id == current_node_id:
            style += ', penwidth=3, color="#EC4899"'  # Vibrant pink highlight for active
            status_suffix = "\\n(⏳ CURRENT)"
        elif node.id in node_status_map:
            st_val = node_status_map[node.id]
            if st_val == "SUCCESS":
                status_suffix = "\\n(✓ SUCCESS)"
            elif st_val == "WAITING_APPROVAL":
                status_suffix = "\\n(⏸ WAITING APPROVAL)"
            elif st_val == "FAILED":
                status_suffix = "\\n(✕ FAILED)"

        label_escaped = node.label.replace('"', '\\"') + status_suffix
        dot_lines.append(f'  "{node.id}" [label="{label_escaped}", {style}];')

    # Add Edges
    for edge in workflow.edges:
        edge_label = ""
        edge_style = ""
        if edge.condition_branch == "true":
            edge_label = ' [label=" TRUE", fontcolor="#16A34A", color="#16A34A", penwidth=1.5]'
        elif edge.condition_branch == "false":
            edge_label = ' [label=" FALSE", fontcolor="#DC2626", color="#DC2626", penwidth=1.5]'
        dot_lines.append(f'  "{edge.from_node}" -> "{edge.to_node}"{edge_label};')

    dot_lines.append('}')
    return "\n".join(dot_lines)

# --- Sidebar ---
with st.sidebar:
    st.image("https://img.icons8.com/isometric/100/workflow.png", width=64)
    st.title("Workflow Studio")
    st.markdown("Convert plain English into enterprise-grade executable DAGs.")

    st.subheader("LLM Configuration")
    user_api_key = st.text_input("Groq API Key (Optional)", type="password", help="Leave blank to use environment key or smart demo templates.")
    if user_api_key:
        os.environ["GROQ_API_KEY"] = user_api_key

    groq_model = st.selectbox(
        "LLM Model",
        ["openai/gpt-oss-120b", "llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
        index=0
    )
    os.environ["GROQ_MODEL"] = groq_model

    st.divider()
    st.subheader("Example Blueprints")
    templates = get_predefined_templates()
    template_names = ["-- Select Pre-built Template --"] + [t["name"] for t in templates]
    selected_template_idx = st.selectbox("Load Example Prompt:", range(len(template_names)), format_func=lambda i: template_names[i])

# --- Header ---
st.markdown('<div class="main-header">⚡ Natural Language Workflow Generator</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Compile business objectives into deterministic, executable DAGs with APIs, validation, conditional branching, and human approval gates.</div>', unsafe_allow_html=True)

# State initialization
if "current_workflow" not in st.session_state:
    st.session_state.current_workflow = get_template_as_workflow("wf_refund_guard")

if "current_execution" not in st.session_state:
    st.session_state.current_execution = None

# If user picks a template from sidebar
if selected_template_idx > 0:
    picked_template = templates[selected_template_idx - 1]
    if st.button(f"Load '{picked_template['name']}'"):
        st.session_state.current_workflow = get_template_as_workflow(picked_template["id"])
        st.session_state.current_execution = None
        st.rerun()

# --- Main Tabs ---
tab_gen, tab_run, tab_spec = st.tabs(["🛠 1. Generator & Flow Graph", "🚀 2. Live Execution & Approval Gate", "📄 3. JSON Spec & DB"])

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

        generate_col, reset_col = st.columns([1, 1])
        with generate_col:
            if st.button("✨ Compile into Workflow", type="primary", use_container_width=True):
                with st.spinner("AI analyzing intent and constructing DAG..."):
                    try:
                        wf = generate_workflow_from_prompt(prompt_input, user_api_key)
                        save_workflow(wf)
                        st.session_state.current_workflow = wf
                        st.session_state.current_execution = None
                        st.success(f"Generated workflow: {wf.name} ({len(wf.nodes)} steps)")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Compilation error: {e}")

        st.markdown("---")
        st.markdown(f"**Loaded Workflow**: `{st.session_state.current_workflow.name}`")
        st.markdown(f"**Description**: {st.session_state.current_workflow.description}")
        st.markdown(f"**Entrypoint**: `{st.session_state.current_workflow.entrypoint}`")
        st.markdown(f"**Node Count**: `{len(st.session_state.current_workflow.nodes)}` | **Edge Count**: `{len(st.session_state.current_workflow.edges)}`")

    with col_graph:
        st.subheader("Interactive Visual Graph (DAG)")
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

        if st.button("▶ Start Workflow Execution", type="primary", use_container_width=True):
            try:
                parsed_input = json.loads(user_input_json)
                wf = st.session_state.current_workflow
                save_workflow(wf)  # Ensure saved in DB
                
                # Initialize execution
                exec_obj = WorkflowRunner.initialize_execution(wf, parsed_input)
                # Run until complete or waiting for approval
                updated_exec = WorkflowRunner.run_step_by_step(exec_obj.id)
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
            # Status Badge
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
                    <h4 style="color: #D97706; margin-top: 0;">⏸ Human Approval Required</h4>
                    <p><b>Prompt:</b> {curr_exec.pending_approval.prompt}</p>
                    <p><b>Required Role:</b> <span style="background: #FDE68A; color: #78350F; padding: 2px 6px; border-radius: 4px;">{curr_exec.pending_approval.required_role}</span></p>
                </div>
                """, unsafe_allow_html=True)

                appr_comment = st.text_input("Reviewer Comment / Reason:", value="Verified risk criteria and authorized.")
                
                btn_col1, btn_col2 = st.columns(2)
                with btn_col1:
                    if st.button("✅ Approve & Continue", type="primary", use_container_width=True):
                        with st.spinner("Processing approval and resuming downstream steps..."):
                            resumed = WorkflowRunner.resume_approval(curr_exec.id, "APPROVE", appr_comment)
                            st.session_state.current_execution = resumed
                            st.rerun()
                with btn_col2:
                    if st.button("❌ Reject Workflow", use_container_width=True):
                        with st.spinner("Rejecting workflow..."):
                            resumed = WorkflowRunner.resume_approval(curr_exec.id, "REJECT", appr_comment)
                            st.session_state.current_execution = resumed
                            st.rerun()

            elif curr_exec.status == ExecutionStatus.COMPLETED:
                st.markdown("""
                <div class="success-card">
                    <h4 style="color: #059669; margin: 0;">🎉 Workflow Successfully Completed!</h4>
                    <p style="margin: 0.5rem 0 0 0; color: #065F46;">All operations, data transformations, and external API calls finished.</p>
                </div>
                """, unsafe_allow_html=True)

            # Step-by-Step Logs Viewer
            st.markdown("#### Step Execution Audit Trail")
            for i, log in enumerate(curr_exec.logs):
                badge_icon = "✅" if log.status == "SUCCESS" else ("⏸" if log.status == "WAITING_APPROVAL" else "❌")
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

# TAB 3: JSON SPEC & DB
with tab_spec:
    st.subheader("Workflow Definition (JSON Specification)")
    st.json(st.session_state.current_workflow.model_dump())

    st.divider()
    st.subheader("All Saved Workflows in SQLite Database")
    saved_list = list_workflows()
    st.write(f"Total stored workflows: {len(saved_list)}")
    for wf in saved_list:
        with st.expander(f"📁 {wf.name} (`{wf.id}`)"):
            st.write(f"Description: {wf.description}")
            st.write(f"Entrypoint: `{wf.entrypoint}` | Steps: {len(wf.nodes)}")

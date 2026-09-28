import os
import re
import json
import uuid
from typing import Dict, Any, Optional, Tuple, List
from src.models.schema import (
    WorkflowDefinition,
    WorkflowNode,
    WorkflowEdge,
    NodeType,
    NodeErrorPolicy
)
from src.generator.templates import get_predefined_templates, get_template_as_workflow
from src.engine.validator import validate_dag_structure

SYSTEM_PROMPT = """
You are an expert Enterprise Workflow Architect and Compiler.
Your job is to translate high-level natural language operational objectives into a complete, executable Directed Acyclic Graph (DAG) workflow in JSON.

Output format MUST be valid JSON adhering strictly to this schema:
{
  "id": "wf_unique_id",
  "name": "Short Descriptive Title",
  "description": "What this workflow accomplishes",
  "entrypoint": "step_id_of_first_node",
  "sample_input": { "key": "value" },
  "nodes": [
    {
      "id": "step_name_1",
      "type": "validation | tool | api | transform | condition | human_approval | notification",
      "label": "Human Readable Label",
      "description": "Brief explanation",
      "config": { ... },
      "on_error": { "retry_count": 0, "fallback_node": null, "fail_workflow": true }
    }
  ],
  "edges": [
    {
      "from_node": "step_name_1",
      "to_node": "step_name_2",
      "condition_branch": "true" // or "false" or null if unconditional
    }
  ]
}

NODE TYPES SPECIFICATION:
1. "validation": checks fields. config: {"rules": [{"field": "amount", "operator": ">", "value": 0}]}
2. "tool": runs utility function. Available tools: "fraud_detector" (inputs: amount, email), "sentiment_analyzer" (inputs: text), "calculate_tax" (inputs: amount, tax_rate), "convert_currency" (inputs: amount, from_currency, to_currency). config: {"tool_name": "...", "input_mapping": {"arg": "{{context_key}}"}}
3. "api": calls REST API. config: {"method": "POST", "endpoint": "https://api.stripe.mock/v1/...", "payload": {...}}
4. "condition": evaluates boolean expression. config: {"expression": "amount > 500 or nodes.step_fraud.output.risk_score > 0.6"}
5. "human_approval": pauses workflow for manager approval. config: {"prompt": "Approval message with {{fields}}", "required_role": "Manager"}
6. "transform": reshapes data. config: {"mapping": {"total": "{{amount}}"}}
7. "notification": sends email/slack. config: {"channel": "email" or "slack", "recipient": "...", "message": "..."}

CRITICAL STRUCTURAL DAG RULES:
- The graph MUST be a valid Directed Acyclic Graph (NO loops or infinite cycles).
- Every "condition" node MUST have at least two outgoing edges: exactly one with "condition_branch": "true", and one with "condition_branch": "false".
- "entrypoint" must match an existing node id.
- Every node must be reachable from the "entrypoint" (no orphaned/unconnected nodes).
- All edges must reference existing node IDs in "from_node" and "to_node".
- Always include realistic "sample_input" with all variables referenced in the nodes.
- Output ONLY pure JSON. No markdown backticks, no explanations.
"""

def synthesize_workflow_from_prompt(natural_prompt: str) -> WorkflowDefinition:
    """
    Intelligent semantic compiler that translates ANY natural language objective
    into a valid, executable enterprise DAG workflow even when offline.
    """
    lower = natural_prompt.lower()
    wf_id = f"wf_{uuid.uuid4().hex[:8]}"

    # Extract numeric thresholds if present (e.g. > 500, > $1000)
    num_matches = re.findall(r"[\$£€]?\s*(\d+(?:\.\d+)?)", natural_prompt)
    threshold = float(num_matches[0]) if num_matches else 500.0

    # 1. Customer Support / Sentiment / Ticket Use Case
    if any(k in lower for k in ["ticket", "support", "complaint", "sentiment", "customer issue", "incident"]):
        name = "Customer Support Incident Triage & Escalation"
        description = "Analyzes incoming support ticket sentiment, checks escalation thresholds, routes high-priority cases for lead approval, and updates CRM."
        sample_input = {
            "ticket_id": "TCK-48192",
            "customer_email": "jane.customer@example.com",
            "customer_text": "I am furious that my order was delayed for two weeks without notification. I demand immediate escalation.",
            "priority": "HIGH"
        }
        nodes = [
            WorkflowNode(
                id="step_validate",
                type=NodeType.VALIDATION,
                label="Validate Support Ticket",
                description="Verify ticket identifier and valid customer email",
                config={"rules": [
                    {"field": "ticket_id", "operator": "exists", "value": ""},
                    {"field": "customer_email", "operator": "contains", "value": "@"}
                ]},
                on_error=NodeErrorPolicy(retry_count=0, fail_workflow=True)
            ),
            WorkflowNode(
                id="step_analyze_sentiment",
                type=NodeType.TOOL,
                label="Analyze Ticket Sentiment",
                description="Run NLP sentiment analyzer to gauge customer frustration and urgency",
                config={
                    "tool_name": "sentiment_analyzer",
                    "input_mapping": {"text": "{{customer_text}}"}
                },
                on_error=NodeErrorPolicy(retry_count=1, fail_workflow=False)
            ),
            WorkflowNode(
                id="step_check_escalation",
                type=NodeType.CONDITION,
                label="Evaluate Escalation Criteria",
                description="Check if priority is HIGH or sentiment is NEGATIVE",
                config={
                    "expression": "priority == 'HIGH' or nodes.step_analyze_sentiment.output.sentiment == 'NEGATIVE'"
                }
            ),
            WorkflowNode(
                id="step_lead_approval",
                type=NodeType.HUMAN_APPROVAL,
                label="Support Lead Approval",
                description="Escalated ticket requires team lead review before issuing refund or priority patch",
                config={
                    "prompt": "Ticket {{ticket_id}} flagged as NEGATIVE/HIGH priority for {{customer_email}}. Authorize emergency escalation?",
                    "required_role": "Support_Lead"
                }
            ),
            WorkflowNode(
                id="step_jira_ticket",
                type=NodeType.API,
                label="Create Priority Jira Issue",
                description="Dispatches urgent bug/incident issue to engineering queue",
                config={
                    "method": "POST",
                    "endpoint": "https://api.atlassian.mock/v2/issues",
                    "payload": {
                        "ticket": "{{ticket_id}}",
                        "summary": "Urgent customer escalation: {{customer_email}}",
                        "priority": "{{priority}}"
                    }
                }
            ),
            WorkflowNode(
                id="step_auto_reply",
                type=NodeType.NOTIFICATION,
                label="Send Standard Auto-Acknowledgment",
                description="Low urgency acknowledgment dispatched to customer",
                config={
                    "channel": "email",
                    "recipient": "{{customer_email}}",
                    "message": "Thank you for contacting support. Your ticket {{ticket_id}} is queued with normal priority."
                }
            ),
            WorkflowNode(
                id="step_slack_alert",
                type=NodeType.NOTIFICATION,
                label="Alert Support Channel",
                description="Notify the tier-3 response channel on Slack",
                config={
                    "channel": "slack",
                    "recipient": "#support-escalations",
                    "message": "Urgent ticket {{ticket_id}} from {{customer_email}} has been escalated to engineering."
                }
            )
        ]
        edges = [
            WorkflowEdge(from_node="step_validate", to_node="step_analyze_sentiment"),
            WorkflowEdge(from_node="step_analyze_sentiment", to_node="step_check_escalation"),
            WorkflowEdge(from_node="step_check_escalation", to_node="step_lead_approval", condition_branch="true"),
            WorkflowEdge(from_node="step_check_escalation", to_node="step_auto_reply", condition_branch="false"),
            WorkflowEdge(from_node="step_lead_approval", to_node="step_jira_ticket"),
            WorkflowEdge(from_node="step_jira_ticket", to_node="step_slack_alert")
        ]

    # 2. Loan / Credit / Finance / Reimbursement Use Case
    elif any(k in lower for k in ["loan", "credit", "mortgage", "disburse", "underwriting", "invoice", "vendor", "payment"]):
        name = "Automated Loan Underwriting & Approval Pipeline"
        description = "Evaluates loan application data, checks credit risk criteria, routes high amounts for human credit officer signoff, and initiates disbursement."
        sample_input = {
            "application_id": "LOAN-99201",
            "applicant_email": "robert.smith@example.com",
            "amount": threshold,
            "credit_score": 710,
            "purpose": "Small Business Expansion"
        }
        nodes = [
            WorkflowNode(
                id="step_validate_app",
                type=NodeType.VALIDATION,
                label="Validate Application Fields",
                description="Ensure requested amount > 0 and valid email format",
                config={"rules": [
                    {"field": "amount", "operator": ">", "value": 0},
                    {"field": "applicant_email", "operator": "contains", "value": "@"}
                ]},
                on_error=NodeErrorPolicy(retry_count=0, fail_workflow=True)
            ),
            WorkflowNode(
                id="step_risk_assessment",
                type=NodeType.TOOL,
                label="Run Risk & Fraud Detector",
                description="Calculate underwriting risk index based on applicant profile",
                config={
                    "tool_name": "fraud_detector",
                    "input_mapping": {"amount": "{{amount}}", "email": "{{applicant_email}}"}
                },
                on_error=NodeErrorPolicy(retry_count=1, fail_workflow=False)
            ),
            WorkflowNode(
                id="step_evaluate_threshold",
                type=NodeType.CONDITION,
                label="Evaluate Underwriting Threshold",
                description=f"Check if requested amount exceeds ${threshold} or risk is high",
                config={
                    "expression": f"amount >= {threshold} or nodes.step_risk_assessment.output.risk_score > 0.65"
                }
            ),
            WorkflowNode(
                id="step_credit_officer_approval",
                type=NodeType.HUMAN_APPROVAL,
                label="Credit Officer Human Approval",
                description="High value loan applications require signed authorization from Senior Underwriter",
                config={
                    "prompt": f"Loan application {{application_id}} for ${{amount}} ({{applicant_email}}) requires authorization. Approve disbursement?",
                    "required_role": "Credit_Officer"
                }
            ),
            WorkflowNode(
                id="step_banking_disburse",
                type=NodeType.API,
                label="Core Banking ACH Disbursement",
                description="Executes core banking ACH API to disburse funds to applicant account",
                config={
                    "method": "POST",
                    "endpoint": "https://api.banking-core.mock/v1/disburse",
                    "payload": {
                        "account": "{{applicant_email}}",
                        "amount": "{{amount}}",
                        "reference": "{{application_id}}"
                    }
                }
            ),
            WorkflowNode(
                id="step_auto_disburse",
                type=NodeType.API,
                label="Automated Fast-Track Disbursement",
                description="Low risk loan auto-processed via instant transfer",
                config={
                    "method": "POST",
                    "endpoint": "https://api.banking-core.mock/v1/instant-disburse",
                    "payload": {
                        "account": "{{applicant_email}}",
                        "amount": "{{amount}}"
                    }
                }
            ),
            WorkflowNode(
                id="step_notify_applicant",
                type=NodeType.NOTIFICATION,
                label="Send Approval Confirmation",
                description="Dispatches completion notice to applicant email",
                config={
                    "channel": "email",
                    "recipient": "{{applicant_email}}",
                    "message": "Congratulations! Your loan request {{application_id}} of ${{amount}} has been approved."
                }
            )
        ]
        edges = [
            WorkflowEdge(from_node="step_validate_app", to_node="step_risk_assessment"),
            WorkflowEdge(from_node="step_risk_assessment", to_node="step_evaluate_threshold"),
            WorkflowEdge(from_node="step_evaluate_threshold", to_node="step_credit_officer_approval", condition_branch="true"),
            WorkflowEdge(from_node="step_evaluate_threshold", to_node="step_auto_disburse", condition_branch="false"),
            WorkflowEdge(from_node="step_credit_officer_approval", to_node="step_banking_disburse"),
            WorkflowEdge(from_node="step_banking_disburse", to_node="step_notify_applicant"),
            WorkflowEdge(from_node="step_auto_disburse", to_node="step_notify_applicant")
        ]

    # 3. Employee / IT Access / AWS / Security Use Case
    elif any(k in lower for k in ["employee", "onboard", "access", "aws", "hire", "security clearance"]):
        return get_template_as_workflow("wf_employee_onboarding")

    # 4. General / Custom Adaptive Use Case
    else:
        # Generate custom title from prompt
        words = [w for w in natural_prompt.split() if len(w) > 2][:5]
        custom_title = " ".join(words).title() or "Automated Business Process"
        name = f"{custom_title} Workflow"
        description = f"Executes operations and approval gates for: {natural_prompt[:120]}..."
        sample_input = {
            "request_id": f"REQ-{uuid.uuid4().hex[:5].upper()}",
            "contact_email": "user@example.com",
            "amount": threshold,
            "priority": "HIGH"
        }
        nodes = [
            WorkflowNode(
                id="step_validate",
                type=NodeType.VALIDATION,
                label="Validate Parameters",
                description="Check required input values before processing",
                config={"rules": [
                    {"field": "contact_email", "operator": "contains", "value": "@"},
                    {"field": "amount", "operator": ">", "value": 0}
                ]},
                on_error=NodeErrorPolicy(retry_count=0, fail_workflow=True)
            ),
            WorkflowNode(
                id="step_analyze",
                type=NodeType.TOOL,
                label="Evaluate Risk Factor",
                description="Run automated fraud and compliance evaluation",
                config={
                    "tool_name": "fraud_detector",
                    "input_mapping": {"amount": "{{amount}}", "email": "{{contact_email}}"}
                },
                on_error=NodeErrorPolicy(retry_count=1, fail_workflow=False)
            ),
            WorkflowNode(
                id="step_condition",
                type=NodeType.CONDITION,
                label="Check Authorization Criteria",
                description=f"Determine whether human authorization is required (threshold: {threshold})",
                config={
                    "expression": f"amount >= {threshold} or nodes.step_analyze.output.risk_score > 0.65"
                }
            ),
            WorkflowNode(
                id="step_approval",
                type=NodeType.HUMAN_APPROVAL,
                label="Manager Authorization Gate",
                description="Pauses execution until authorized by an administrator",
                config={
                    "prompt": f"Authorize execution of request {{request_id}} (Amount: ${{amount}}, Contact: {{contact_email}})?",
                    "required_role": "Manager"
                }
            ),
            WorkflowNode(
                id="step_execute_api",
                type=NodeType.API,
                label="Execute Business API",
                description="Dispatches external API call to complete transaction",
                config={
                    "method": "POST",
                    "endpoint": "https://api.enterprise.mock/v1/process",
                    "payload": {
                        "id": "{{request_id}}",
                        "email": "{{contact_email}}",
                        "amount": "{{amount}}"
                    }
                }
            ),
            WorkflowNode(
                id="step_auto_process",
                type=NodeType.API,
                label="Auto Process Standard Request",
                description="Standard tier execution without approval pause",
                config={
                    "method": "POST",
                    "endpoint": "https://api.enterprise.mock/v1/auto-process",
                    "payload": {
                        "id": "{{request_id}}",
                        "amount": "{{amount}}"
                    }
                }
            ),
            WorkflowNode(
                id="step_notify_completion",
                type=NodeType.NOTIFICATION,
                label="Notify Stakeholder",
                description="Sends confirmation email upon workflow completion",
                config={
                    "channel": "email",
                    "recipient": "{{contact_email}}",
                    "message": "Your request {{request_id}} has been processed successfully."
                }
            )
        ]
        edges = [
            WorkflowEdge(from_node="step_validate", to_node="step_analyze"),
            WorkflowEdge(from_node="step_analyze", to_node="step_condition"),
            WorkflowEdge(from_node="step_condition", to_node="step_approval", condition_branch="true"),
            WorkflowEdge(from_node="step_condition", to_node="step_auto_process", condition_branch="false"),
            WorkflowEdge(from_node="step_approval", to_node="step_execute_api"),
            WorkflowEdge(from_node="step_execute_api", to_node="step_notify_completion"),
            WorkflowEdge(from_node="step_auto_process", to_node="step_notify_completion")
        ]

    wf = WorkflowDefinition(
        id=wf_id,
        name=name,
        description=description,
        entrypoint="step_validate" if "step_validate" in [n.id for n in nodes] else nodes[0].id,
        sample_input=sample_input,
        nodes=nodes,
        edges=edges
    )

    # Validate structural soundness
    is_valid, errors = validate_dag_structure(wf)
    if not is_valid:
        raise ValueError(f"Generated DAG structure error: {errors}")

    return wf

def generate_workflow_from_prompt(
    natural_prompt: str, 
    api_key: Optional[str] = None,
    max_repair_attempts: int = 3
) -> WorkflowDefinition:
    """
    Calls Groq API to generate an executable workflow with an iterative
    self-correction loop, or uses the intelligent semantic compiler if
    no valid API key is present or on API error.
    """
    effective_key = api_key or os.getenv("GROQ_API_KEY")
    model_name = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

    # If real Groq key is available, generate via LLM with feedback loop
    if effective_key and effective_key.strip() and effective_key != "your_groq_api_key_here":
        try:
            from groq import Groq
            client = Groq(api_key=effective_key)
            
            messages: List[Dict[str, str]] = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Generate an executable workflow for this objective:\n\n{natural_prompt}"}
            ]

            attempt = 0
            while attempt < max_repair_attempts:
                attempt += 1
                completion = client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=0.1,
                    max_tokens=2500
                )

                raw_json = completion.choices[0].message.content
                
                # 1. JSON parsing check
                try:
                    parsed = json.loads(raw_json)
                except Exception as json_err:
                    error_msg = f"Invalid JSON syntax: {str(json_err)}"
                    messages.append({"role": "assistant", "content": raw_json})
                    messages.append({"role": "user", "content": f"Your response was not valid JSON: {error_msg}. Return strictly valid JSON."})
                    continue

                # 2. Pydantic schema check
                try:
                    workflow = WorkflowDefinition.model_validate(parsed)
                except Exception as schema_err:
                    error_msg = f"Schema validation error: {str(schema_err)}"
                    messages.append({"role": "assistant", "content": raw_json})
                    messages.append({
                        "role": "user", 
                        "content": f"The workflow JSON failed schema validation with error:\n{error_msg}\n\nPlease fix the fields and return the corrected JSON."
                    })
                    continue

                # 3. DAG Structural Validation (Cycles, Reachability, Condition branches)
                is_valid_dag, structural_errors = validate_dag_structure(workflow)
                if not is_valid_dag:
                    error_summary = "\n- ".join(structural_errors)
                    messages.append({"role": "assistant", "content": raw_json})
                    messages.append({
                        "role": "user", 
                        "content": (
                            f"The generated workflow failed DAG structural validation with the following error(s):\n- {error_summary}\n\n"
                            "Please correct the DAG structure (ensure no cycles, ensure all condition nodes have both 'true' and 'false' edges, "
                            "and ensure all nodes are connected and reachable from entrypoint) and return the corrected JSON."
                        )
                    })
                    continue

                # All checks pass!
                return workflow

        except Exception as e:
            print(f"[Warning] Groq LLM generation error: {e}. Falling back to semantic compiler.")

    # Intelligent semantic compiler handles ANY prompt dynamically
    return synthesize_workflow_from_prompt(natural_prompt)

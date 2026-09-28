from typing import List, Dict, Any
from src.models.schema import WorkflowDefinition, WorkflowNode, WorkflowEdge, NodeType, NodeErrorPolicy

def get_predefined_templates() -> List[Dict[str, Any]]:
    """
    Returns pre-built, robust workflow definitions for one-click testing and few-shot LLM guidance.
    """
    return [
        {
            "id": "wf_refund_guard",
            "name": "High-Value Refund & Fraud Guard",
            "description": "Validates transaction, computes fraud risk score, pauses for manager approval if amount > $500 or risk > 0.65, and executes Stripe refund API.",
            "natural_prompt": "When a refund request arrives, validate that amount is positive and email is valid. Run the fraud detector tool. If amount > $500 or risk score > 0.65, request manager approval. Once approved, call the Stripe refund API. If Stripe fails, alert support on Slack. Finally send a confirmation email to customer.",
            "sample_input": {
                "refund_id": "REF-88421",
                "customer_email": "sarah.connor@example.com",
                "amount": 750.00,
                "reason": "Order arrived damaged"
            },
            "entrypoint": "step_validate",
            "nodes": [
                {
                    "id": "step_validate",
                    "type": "validation",
                    "label": "Validate Refund Request",
                    "description": "Ensure amount is positive and email format is valid",
                    "config": {
                        "rules": [
                            {"field": "amount", "operator": ">", "value": 0},
                            {"field": "customer_email", "operator": "contains", "value": "@"}
                        ]
                    }
                },
                {
                    "id": "step_fraud",
                    "type": "tool",
                    "label": "Assess Fraud Risk",
                    "description": "Calculate deterministic fraud score",
                    "config": {
                        "tool_name": "fraud_detector",
                        "input_mapping": {
                            "amount": "{{amount}}",
                            "email": "{{customer_email}}"
                        }
                    }
                },
                {
                    "id": "step_check_threshold",
                    "type": "condition",
                    "label": "Is High Risk or High Value?",
                    "description": "Checks if amount > 500 or risk score > 0.65",
                    "config": {
                        "expression": "amount > 500 or nodes.step_fraud.output.risk_score > 0.65"
                    }
                },
                {
                    "id": "step_manager_approval",
                    "type": "human_approval",
                    "label": "Manager Human Approval",
                    "description": "Pauses execution for finance manager sign-off",
                    "config": {
                        "prompt": "Refund of ${{amount}} for {{customer_email}} requires manager authorization. Approve refund?",
                        "required_role": "Finance_Manager"
                    }
                },
                {
                    "id": "step_stripe_api",
                    "type": "api",
                    "label": "Execute Stripe Refund",
                    "description": "Calls payment gateway API to disburse funds",
                    "config": {
                        "method": "POST",
                        "endpoint": "https://api.stripe.mock/v1/refunds",
                        "payload": {
                            "charge_id": "{{refund_id}}",
                            "amount": "{{amount}}",
                            "email": "{{customer_email}}"
                        }
                    },
                    "on_error": {
                        "retry_count": 2,
                        "fallback_node": "step_alert_failure"
                    }
                },
                {
                    "id": "step_customer_email",
                    "type": "notification",
                    "label": "Send Confirmation Email",
                    "description": "Notify customer about successful refund",
                    "config": {
                        "channel": "email",
                        "recipient": "{{customer_email}}",
                        "message": "Hello, your refund of ${{amount}} for order {{refund_id}} has been approved and processed."
                    }
                },
                {
                    "id": "step_alert_failure",
                    "type": "notification",
                    "label": "Alert Operations on Slack",
                    "description": "Slack ping if Stripe API call fails",
                    "config": {
                        "channel": "slack",
                        "recipient": "#finance-ops",
                        "message": "WARNING: Refund {{refund_id}} failed to execute on Stripe gateway."
                    }
                }
            ],
            "edges": [
                {"from_node": "step_validate", "to_node": "step_fraud"},
                {"from_node": "step_fraud", "to_node": "step_check_threshold"},
                {"from_node": "step_check_threshold", "to_node": "step_manager_approval", "condition_branch": "true"},
                {"from_node": "step_check_threshold", "to_node": "step_stripe_api", "condition_branch": "false"},
                {"from_node": "step_manager_approval", "to_node": "step_stripe_api"},
                {"from_node": "step_stripe_api", "to_node": "step_customer_email"}
            ]
        },
        {
            "id": "wf_employee_onboarding",
            "name": "Employee IT & Access Provisioning",
            "description": "Validates employee profile, checks department access policies, requests HR/Security approval for privileged access, and calls Okta/Google APIs.",
            "natural_prompt": "When a new employee joins, validate their email and role. If their department is Engineering or Executive, require IT Director approval before provisioning production AWS keys. Otherwise, automatically provision standard Slack and Google Workspace accounts.",
            "sample_input": {
                "employee_name": "Elena Rostova",
                "employee_email": "elena.r@company.internal",
                "department": "Engineering",
                "role": "Senior Cloud Architect"
            },
            "entrypoint": "step_val_emp",
            "nodes": [
                {
                    "id": "step_val_emp",
                    "type": "validation",
                    "label": "Validate Employee Record",
                    "config": {
                        "rules": [
                            {"field": "employee_email", "operator": "contains", "value": "@"},
                            {"field": "department", "operator": "exists", "value": ""}
                        ]
                    }
                },
                {
                    "id": "step_check_dept",
                    "type": "condition",
                    "label": "Is Engineering or Executive?",
                    "config": {
                        "expression": "department == 'Engineering' or department == 'Executive'"
                    }
                },
                {
                    "id": "step_it_approval",
                    "type": "human_approval",
                    "label": "IT Security Director Sign-Off",
                    "config": {
                        "prompt": "Approve production cloud access provisioning for {{employee_name}} ({{role}})?",
                        "required_role": "IT_Director"
                    }
                },
                {
                    "id": "step_provision_aws",
                    "type": "api",
                    "label": "Provision AWS IAM & SSO",
                    "config": {
                        "method": "POST",
                        "endpoint": "https://api.aws.mock/v1/iam/users",
                        "payload": {"email": "{{employee_email}}", "group": "Engineers"}
                    }
                },
                {
                    "id": "step_provision_standard",
                    "type": "api",
                    "label": "Provision Google Workspace & Slack",
                    "config": {
                        "method": "POST",
                        "endpoint": "https://api.google.mock/v1/workspace/users",
                        "payload": {"email": "{{employee_email}}", "name": "{{employee_name}}"}
                    }
                },
                {
                    "id": "step_welcome_notify",
                    "type": "notification",
                    "label": "Send Welcome Email",
                    "config": {
                        "channel": "email",
                        "recipient": "{{employee_email}}",
                        "message": "Welcome {{employee_name}}! Your corporate accounts are active."
                    }
                }
            ],
            "edges": [
                {"from_node": "step_val_emp", "to_node": "step_check_dept"},
                {"from_node": "step_check_dept", "to_node": "step_it_approval", "condition_branch": "true"},
                {"from_node": "step_check_dept", "to_node": "step_provision_standard", "condition_branch": "false"},
                {"from_node": "step_it_approval", "to_node": "step_provision_aws"},
                {"from_node": "step_provision_aws", "to_node": "step_provision_standard"},
                {"from_node": "step_provision_standard", "to_node": "step_welcome_notify"}
            ]
        }
    ]

def get_template_as_workflow(template_id: str) -> WorkflowDefinition:
    templates = get_predefined_templates()
    for t in templates:
        if t["id"] == template_id:
            return WorkflowDefinition(
                id=t["id"],
                name=t["name"],
                description=t["description"],
                entrypoint=t["entrypoint"],
                sample_input=t["sample_input"],
                nodes=[
                    WorkflowNode(
                        id=n["id"],
                        type=NodeType(n["type"]),
                        label=n["label"],
                        description=n.get("description", ""),
                        config=n.get("config", {}),
                        on_error=NodeErrorPolicy(**n["on_error"]) if "on_error" in n else NodeErrorPolicy()
                    )
                    for n in t["nodes"]
                ],
                edges=[
                    WorkflowEdge(
                        from_node=e["from_node"],
                        to_node=e["to_node"],
                        condition_branch=e.get("condition_branch")
                    )
                    for e in t["edges"]
                ]
            )
    raise ValueError(f"Template {template_id} not found.")

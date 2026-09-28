# Workflow Schema Specification (JSON Contract)

This document formalizes the exact data structure produced by the Groq LLM and consumed by the Execution Runtime.

---

## 1. Top-Level Workflow Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "ExecutableWorkflow",
  "type": "object",
  "required": ["id", "name", "description", "entrypoint", "nodes", "edges"],
  "properties": {
    "id": { "type": "string" },
    "name": { "type": "string" },
    "description": { "type": "string" },
    "entrypoint": { "type": "string", "description": "The ID of the first node to execute" },
    "sample_input": {
      "type": "object",
      "description": "Mock inputs needed to trigger and test this workflow"
    },
    "nodes": {
      "type": "array",
      "items": { "$ref": "#/definitions/Node" }
    },
    "edges": {
      "type": "array",
      "items": { "$ref": "#/definitions/Edge" }
    }
  },
  "definitions": {
    "Node": {
      "type": "object",
      "required": ["id", "type", "label"],
      "properties": {
        "id": { "type": "string", "example": "validate_input_1" },
        "type": {
          "type": "string",
          "enum": ["validation", "tool", "api", "transform", "condition", "human_approval", "notification"]
        },
        "label": { "type": "string", "description": "Human readable name of the step" },
        "description": { "type": "string" },
        "config": {
          "type": "object",
          "description": "Node specific configuration parameters"
        },
        "on_error": {
          "type": "object",
          "properties": {
            "retry_count": { "type": "integer", "default": 0 },
            "fallback_node": { "type": "string" },
            "fail_workflow": { "type": "boolean", "default": true }
          }
        }
      }
    },
    "Edge": {
      "type": "object",
      "required": ["from_node", "to_node"],
      "properties": {
        "from_node": { "type": "string" },
        "to_node": { "type": "string" },
        "condition_branch": {
          "type": "string",
          "enum": ["true", "false", "default"],
          "description": "Optional branch condition if from_node is a condition node"
        }
      }
    }
  }
}
```

---

## 2. Concrete Example: High-Value Refund Workflow

```json
{
  "id": "wf_refund_guard_001",
  "name": "High-Value Refund & Fraud Review",
  "description": "Validates incoming refund request, runs fraud score check, pauses for manager approval if high risk, and triggers Stripe API.",
  "entrypoint": "step_validate_request",
  "sample_input": {
    "refund_id": "REF-9921",
    "customer_email": "alex@example.com",
    "amount": 750.00,
    "reason": "Damaged goods upon delivery"
  },
  "nodes": [
    {
      "id": "step_validate_request",
      "type": "validation",
      "label": "Validate Refund Payload",
      "config": {
        "rules": [
          { "field": "amount", "operator": ">", "value": 0 },
          { "field": "customer_email", "operator": "contains", "value": "@" }
        ]
      }
    },
    {
      "id": "step_fraud_check",
      "type": "tool",
      "label": "Calculate Fraud Risk Score",
      "config": {
        "tool_name": "fraud_detector",
        "input_mapping": {
          "email": "{{context.customer_email}}",
          "amount": "{{context.amount}}"
        }
      }
    },
    {
      "id": "step_check_threshold",
      "type": "condition",
      "label": "Is Amount > $500 or Fraud Score > 0.6?",
      "config": {
        "expression": "context.amount > 500 or context.nodes.step_fraud_check.output.risk_score > 0.6"
      }
    },
    {
      "id": "step_manager_approval",
      "type": "human_approval",
      "label": "Manager Human Approval",
      "config": {
        "prompt": "Refund of ${{context.amount}} for {{context.customer_email}} exceeds threshold. Approve refund?",
        "required_role": "Finance_Manager"
      }
    },
    {
      "id": "step_stripe_refund",
      "type": "api",
      "label": "Call Stripe Refund API",
      "config": {
        "method": "POST",
        "endpoint": "https://api.stripe.mock/v1/refunds",
        "payload": {
          "amount": "{{context.amount}}",
          "reference": "{{context.refund_id}}"
        }
      },
      "on_error": {
        "retry_count": 2,
        "fallback_node": "step_notify_failure"
      }
    },
    {
      "id": "step_notify_customer_success",
      "type": "notification",
      "label": "Send Refund Confirmation Email",
      "config": {
        "channel": "email",
        "recipient": "{{context.customer_email}}",
        "message": "Your refund of ${{context.amount}} has been processed successfully."
      }
    },
    {
      "id": "step_notify_failure",
      "type": "notification",
      "label": "Alert Support on Refund Failure",
      "config": {
        "channel": "slack",
        "recipient": "#finance-ops",
        "message": "Refund failed for {{context.refund_id}}."
      }
    }
  ],
  "edges": [
    { "from_node": "step_validate_request", "to_node": "step_fraud_check" },
    { "from_node": "step_fraud_check", "to_node": "step_check_threshold" },
    { "from_node": "step_check_threshold", "to_node": "step_manager_approval", "condition_branch": "true" },
    { "from_node": "step_check_threshold", "to_node": "step_stripe_refund", "condition_branch": "false" },
    { "from_node": "step_manager_approval", "to_node": "step_stripe_refund" },
    { "from_node": "step_stripe_refund", "to_node": "step_notify_customer_success" }
  ]
}
```

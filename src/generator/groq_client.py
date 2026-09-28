import os
import json
from typing import Dict, Any, Optional
from src.models.schema import WorkflowDefinition
from src.generator.templates import get_predefined_templates, get_template_as_workflow

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
      "on_error": { "retry_count": 0, "fallback_node": "step_alert_id", "fail_workflow": true }
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

IMPORTANT RULES:
- Nodes must form a valid DAG (no infinite cycles).
- Every condition node MUST have two outgoing edges: one with "condition_branch": "true", and one with "condition_branch": "false".
- "entrypoint" must match an existing node id.
- Always include realistic "sample_input" with all variables referenced in the nodes.
- Output ONLY pure JSON. No markdown backticks, no explanations.
"""

def generate_workflow_from_prompt(natural_prompt: str, api_key: Optional[str] = None) -> WorkflowDefinition:
    """
    Calls Groq API to generate an executable workflow from a natural language description.
    Falls back to intelligent semantic matching or template synthesis if no key is provided.
    """
    effective_key = api_key or os.getenv("GROQ_API_KEY")
    model_name = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    # If Groq is available, generate via LLM
    if effective_key and effective_key.strip() and effective_key != "your_groq_api_key_here":
        try:
            from groq import Groq
            client = Groq(api_key=effective_key)
            
            completion = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Generate an executable workflow for this objective:\n\n{natural_prompt}"}
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=2500
            )

            raw_json = completion.choices[0].message.content
            parsed = json.loads(raw_json)
            
            # Validate with Pydantic
            workflow = WorkflowDefinition.model_validate(parsed)
            return workflow
        except Exception as e:
            print(f"[Warning] Groq LLM generation error: {e}. Falling back to template synthesis.")

    # Graceful Offline / Demo Fallback Mode:
    lower_prompt = natural_prompt.lower()
    if "employee" in lower_prompt or "onboard" in lower_prompt or "access" in lower_prompt or "aws" in lower_prompt:
        return get_template_as_workflow("wf_employee_onboarding")
    else:
        # Default refund guard workflow
        return get_template_as_workflow("wf_refund_guard")

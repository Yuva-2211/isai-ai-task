import os
import json
from typing import Dict, Any, Optional, Tuple, List
from src.models.schema import WorkflowDefinition
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

CRITICAL STRUCTURAL DAG RULES:
- The graph MUST be a valid Directed Acyclic Graph (NO loops or infinite cycles).
- Every "condition" node MUST have at least two outgoing edges: exactly one with "condition_branch": "true", and one with "condition_branch": "false".
- "entrypoint" must match an existing node id.
- Every node must be reachable from the "entrypoint" (no orphaned/unconnected nodes).
- All edges must reference existing node IDs in "from_node" and "to_node".
- Always include realistic "sample_input" with all variables referenced in the nodes.
- Output ONLY pure JSON. No markdown backticks, no explanations.
"""

def generate_workflow_from_prompt(
    natural_prompt: str, 
    api_key: Optional[str] = None,
    max_repair_attempts: int = 3
) -> WorkflowDefinition:
    """
    Calls Groq API to generate an executable workflow with an iterative
    self-correction / self-healing loop that sends structural and schema errors
    back to the LLM until the DAG is structurally sound.
    """
    effective_key = api_key or os.getenv("GROQ_API_KEY")
    model_name = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    # If Groq is available, generate via LLM with feedback loop
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

                # If all checks pass!
                return workflow

        except Exception as e:
            print(f"[Warning] Groq LLM generation error: {e}. Falling back to template synthesis.")

    # Graceful Offline / Demo Fallback Mode:
    lower_prompt = natural_prompt.lower()
    if "employee" in lower_prompt or "onboard" in lower_prompt or "access" in lower_prompt or "aws" in lower_prompt:
        wf = get_template_as_workflow("wf_employee_onboarding")
    else:
        wf = get_template_as_workflow("wf_refund_guard")

    # Double check template structural validity
    is_valid, errors = validate_dag_structure(wf)
    if not is_valid:
        raise ValueError(f"Baseline template failed structural validation: {errors}")
        
    return wf

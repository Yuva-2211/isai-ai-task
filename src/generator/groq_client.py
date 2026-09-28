import os
import json
import logging
from typing import Dict, Any, Optional, Tuple, List
from pydantic import ValidationError
from dotenv import load_dotenv

load_dotenv(override=True)

from src.models.schema import (
    WorkflowDefinition,
    WorkflowNode,
    WorkflowEdge,
    NodeType,
    NodeErrorPolicy
)
from src.generator.templates import get_template_as_workflow
from src.engine.validator import (
    validate_dag_structure,
    validate_semantic_integrity,
    validate_complete_workflow
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are an expert Enterprise Workflow Architect and Compiler.
Your role is to translate natural language operational requirements into complete, deterministic, executable Directed Acyclic Graph (DAG) workflows formatted strictly in JSON.

Output format MUST be valid JSON adhering strictly to this schema:
{
  "id": "wf_unique_id",
  "name": "Short Descriptive Title",
  "description": "Comprehensive explanation of what this workflow achieves",
  "entrypoint": "step_id_of_first_node",
  "sample_input": {
    "key": "value"
  },
  "nodes": [
    {
      "id": "step_id_1",
      "type": "validation | tool | api | transform | condition | human_approval | notification",
      "label": "Human Readable Label",
      "description": "Brief description of this operation",
      "config": { ... },
      "on_error": {
        "retry_count": 0,
        "fallback_node": null,
        "fail_workflow": true
      }
    }
  ],
  "edges": [
    {
      "from_node": "step_id_1",
      "to_node": "step_id_2",
      "condition_branch": "true" // Use "true" or "false" for condition nodes, null for normal transitions
    }
  ]
}

NODE TYPES SPECIFICATION:
1. "validation": checks data constraints before downstream actions.
   config: {"rules": [{"field": "amount", "operator": ">", "value": 0}]}
   Operators supported: ">", ">=", "<", "<=", "==", "!=", "contains", "exists"

2. "tool": executes registered utility algorithms.
   Available tools:
   - "fraud_detector" (inputs: {"amount": "{{amount}}", "email": "{{email}}"}) -> outputs: risk_score, risk_level, recommendation
   - "sentiment_analyzer" (inputs: {"text": "{{text}}"}) -> outputs: sentiment, score, urgency
   - "calculate_tax" (inputs: {"amount": "{{amount}}", "tax_rate": 0.08}) -> outputs: subtotal, tax_amount, total
   - "convert_currency" (inputs: {"amount": "{{amount}}", "from_currency": "USD", "to_currency": "EUR"}) -> outputs: converted_amount
   config: {"tool_name": "...", "input_mapping": {"arg": "{{context_key}}"}}

3. "api": performs HTTP REST API interactions with external services.
   config: {"method": "POST" | "GET" | "PUT" | "DELETE", "endpoint": "https://...", "payload": {...}}

4. "condition": evaluates boolean criteria to branch execution.
   config: {"expression": "amount > 500 or nodes.step_fraud.output.risk_score > 0.65"}

5. "human_approval": pauses execution until a designated reviewer approves or rejects.
   config: {"prompt": "Review request for {{email}}", "required_role": "Manager" | "Admin" | "Lead"}

6. "transform": reshapes context data.
   config: {"mapping": {"new_key": "{{existing_key}}"}}

7. "notification": sends email or chat alert.
   config: {"channel": "email" | "slack", "recipient": "...", "message": "..."}

STRICT ARCHITECTURAL & DAG INTEGRITY RULES:
- The graph MUST be a valid Directed Acyclic Graph (NO circular loops or cycles).
- Every "condition" node MUST have at least two outgoing edges: exactly one with "condition_branch": "true", and one with "condition_branch": "false".
- "entrypoint" must match an existing node id.
- Every node must be reachable from the "entrypoint" (no disconnected or orphaned nodes).
- All edges must reference valid existing node IDs in "from_node" and "to_node".
- All "{{variable}}" interpolations in configs must reference keys declared in "sample_input" or upstream node outputs ("nodes.<node_id>.output.<field>").
- Output ONLY pure JSON. No markdown backticks, no explanations.

MANDATORY SEMANTIC FIDELITY RULES:
1. The generated workflow MUST be derived from the user's current objective.
2. Do not reuse business entities, field names, APIs, tools, roles, thresholds, or terminology from previous examples unless they are explicitly relevant to the current objective.
3. Do not convert one business domain into another. For example, an invoice request must not become a loan workflow.
4. Every major operation explicitly requested by the user must appear as a workflow node or be represented in an appropriate node configuration.
5. Do not invent unnecessary operations.
6. Preserve exact numeric thresholds from the user.
7. Preserve the direction of comparisons:
   - "exceeds $10,000" means > 10000,
   - "at least $10,000" means >= 10000.
8. Preserve requested roles:
   - "finance manager" must not become "credit officer".
9. Preserve requested systems:
   - "payment API" must not become "banking disbursement API".
10. Error handling requirements must be represented through on_error or explicit workflow nodes.
"""


def compile_workflow_with_groq(
    natural_prompt: str,
    api_key: str,
    model_name: str = "openai/gpt-oss-120b",
    max_repair_attempts: int = 3
) -> WorkflowDefinition:
    """
    Core NL -> Workflow compiler using Groq LLM with a 4-stage validation
    and iterative self-correction loop.
    """
    from groq import Groq
    client = Groq(api_key=api_key)

    messages: List[Dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Compile this operational requirement into an executable DAG workflow:\n\n{natural_prompt}"}
    ]

    attempt = 0
    last_errors: List[str] = []

    while attempt < max_repair_attempts:
        attempt += 1
        logger.info(f"Groq workflow compilation attempt {attempt}/{max_repair_attempts}")

        try:
            completion = client.chat.completions.create(
                model=model_name,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=3000
            )
            raw_json = completion.choices[0].message.content
        except Exception as api_err:
            raise RuntimeError(f"Groq API connection error: {api_err}")

        # --- Stage 1: JSON Syntax Validation ---
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError as json_err:
            error_msg = f"JSON Syntax Error: {json_err.msg} at line {json_err.lineno}, col {json_err.colno}"
            logger.warning(f"Attempt {attempt} failed JSON syntax: {error_msg}")
            messages.append({"role": "assistant", "content": raw_json})
            messages.append({
                "role": "user",
                "content": f"Your response was not valid JSON:\n{error_msg}\n\nReturn strictly valid JSON conforming to the schema."
            })
            continue

        # --- Stage 2: Pydantic Schema Validation ---
        try:
            workflow = WorkflowDefinition.model_validate(parsed)
        except ValidationError as val_err:
            schema_issues = [f"{err['loc']}: {err['msg']}" for err in val_err.errors()]
            error_summary = "\n- ".join(schema_issues)
            logger.warning(f"Attempt {attempt} failed Pydantic schema validation: {error_summary}")
            messages.append({"role": "assistant", "content": raw_json})
            messages.append({
                "role": "user",
                "content": (
                    f"The workflow failed Pydantic schema validation with the following error(s):\n- {error_summary}\n\n"
                    "Please correct the fields, types, and structure according to the specification and return valid JSON."
                )
            })
            continue

        # --- Stage 3, 4 & 5: Semantic Integrity, Fidelity & DAG Structural Validation ---
        is_valid, validation_errors = validate_complete_workflow(workflow, natural_prompt=natural_prompt)
        if not is_valid:
            error_summary = "\n- ".join(validation_errors)
            logger.warning(f"Attempt {attempt} failed validation:\n{error_summary}")
            last_errors = validation_errors
            messages.append({"role": "assistant", "content": raw_json})
            messages.append({
                "role": "user",
                "content": (
                    f"The generated workflow failed architectural and structural validation:\n- {error_summary}\n\n"
                    "Self-Correction Instructions:\n"
                    "1. If cycles are detected, remove the back-edges to ensure an acyclic DAG.\n"
                    "2. If condition nodes are missing branches, ensure EVERY condition node has both 'true' and 'false' edges.\n"
                    "3. If unreachable nodes are detected, ensure a path exists from entrypoint to every node.\n"
                    "4. If template references are invalid, ensure node IDs match exactly.\n\n"
                    "Please repair the workflow JSON to resolve every error above."
                )
            })
            continue

        # All 4 validation stages passed successfully!
        logger.info(f"Workflow '{workflow.name}' successfully compiled and validated in {attempt} attempt(s).")
        return workflow

    # If maximum repair attempts reached without resolving all errors
    raise ValueError(
        f"Workflow compilation failed after {max_repair_attempts} self-correction attempts. "
        f"Unresolved errors:\n- " + "\n- ".join(last_errors)
    )


def generate_workflow_from_prompt(
    natural_prompt: str,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    max_repair_attempts: int = 3
) -> WorkflowDefinition:
    """
    Public entry point for Natural Language -> Executable Workflow generation.
    Invokes Groq LLM compiler with self-correction. If no API key is provided,
    raises a descriptive error or returns a clean baseline template for testing.
    """
    effective_key = api_key or os.getenv("GROQ_API_KEY", "")
    model_name = model or os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

    # Check if a real Groq key is configured
    if effective_key and effective_key.strip() and effective_key.strip() != "your_groq_api_key_here":
        return compile_workflow_with_groq(
            natural_prompt=natural_prompt,
            api_key=effective_key.strip(),
            model_name=model_name,
            max_repair_attempts=max_repair_attempts
        )

    # When no Groq key is present, inform the user clearly
    raise ValueError(
        "Groq API key required for AI workflow compilation. "
        "Please provide your Groq API key in the configuration or set GROQ_API_KEY in the .env file."
    )

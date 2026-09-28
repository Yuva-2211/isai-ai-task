import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.models.schema import ExecutionStatus, NodeType, WorkflowDefinition
from src.generator.templates import get_template_as_workflow
from src.engine.runner import WorkflowRunner
from src.engine.evaluator import safe_eval_expression, interpolate_string
from src.engine.tool_registry import tool_fraud_detector, tool_tax_calculator

def test_tool_fraud_detector():
    res = tool_fraud_detector({"amount": 800, "email": "suspicious@tempmail.com"})
    assert "risk_score" in res
    assert res["risk_level"] in ["LOW", "MEDIUM", "HIGH"]
    print("✓ test_tool_fraud_detector passed")

def test_tool_tax_calculator():
    res = tool_tax_calculator({"amount": 100, "tax_rate": 0.10})
    assert res["tax_amount"] == 10.0
    assert res["total"] == 110.0
    print("✓ test_tool_tax_calculator passed")

def test_evaluator_conditions():
    ctx = {"amount": 750, "nodes": {"step_fraud": {"output": {"risk_score": 0.8}}}}
    assert safe_eval_expression("amount > 500", ctx) is True
    assert safe_eval_expression("amount < 100", ctx) is False
    assert safe_eval_expression("nodes.step_fraud.output.risk_score > 0.5", ctx) is True
    print("✓ test_evaluator_conditions passed")

def test_evaluator_interpolator():
    ctx = {"customer_name": "Alice", "amount": 250}
    res = interpolate_string("Refund ${{amount}} for {{customer_name}}", ctx)
    assert res == "Refund $250 for Alice"
    print("✓ test_evaluator_interpolator passed")

def test_end_to_end_dag_with_approval():
    wf = get_template_as_workflow("wf_refund_guard")
    
    # 1. Initialize execution
    exec_obj = WorkflowRunner.initialize_execution(wf, {
        "refund_id": "TEST-001",
        "customer_email": "test@example.com",
        "amount": 900.0,
        "reason": "Defective item"
    })
    assert exec_obj.status == ExecutionStatus.RUNNING

    # 2. Run step-by-step -> Should pause at manager approval
    paused_exec = WorkflowRunner.run_step_by_step(exec_obj.id)
    assert paused_exec.status == ExecutionStatus.WAITING_APPROVAL
    assert paused_exec.pending_approval is not None
    print(f"✓ Workflow correctly paused on Human Approval: {paused_exec.pending_approval.prompt}")

    # 3. Resume with Approval
    resumed_exec = WorkflowRunner.resume_approval(paused_exec.id, "APPROVE", "Manager signed off.")
    assert resumed_exec.status == ExecutionStatus.COMPLETED
    assert len(resumed_exec.logs) > 0
    print(f"✓ Workflow completed after approval with {len(resumed_exec.logs)} logged steps!")

from src.engine.validator import validate_dag_structure
from src.models.schema import WorkflowNode, WorkflowEdge

def test_dag_cycle_detection():
    # Construct an invalid cyclic graph: step_1 -> step_2 -> step_1
    wf = WorkflowDefinition(
        id="wf_cyclic",
        name="Cyclic Test",
        description="Graph with cycle",
        entrypoint="step_1",
        nodes=[
            WorkflowNode(id="step_1", type=NodeType.TOOL, label="Step 1"),
            WorkflowNode(id="step_2", type=NodeType.TOOL, label="Step 2")
        ],
        edges=[
            WorkflowEdge(from_node="step_1", to_node="step_2"),
            WorkflowEdge(from_node="step_2", to_node="step_1")
        ]
    )
    is_valid, errors = validate_dag_structure(wf)
    assert not is_valid
    assert any("cycle" in e.lower() for e in errors)
    print("✓ test_dag_cycle_detection passed (cycle caught correctly)")

def test_dag_condition_branch_validation():
    # Construct a condition node with only 'true' branch
    wf = WorkflowDefinition(
        id="wf_incomplete_cond",
        name="Incomplete Condition Test",
        description="Missing false branch",
        entrypoint="step_check",
        nodes=[
            WorkflowNode(id="step_check", type=NodeType.CONDITION, label="Check"),
            WorkflowNode(id="step_target", type=NodeType.TOOL, label="Target")
        ],
        edges=[
            WorkflowEdge(from_node="step_check", to_node="step_target", condition_branch="true")
        ]
    )
    is_valid, errors = validate_dag_structure(wf)
    assert not is_valid
    assert any("false" in e for e in errors)
    print("✓ test_dag_condition_branch_validation passed (missing branch caught)")

def test_dag_predefined_templates_validity():
    templates = ["wf_refund_guard", "wf_employee_onboarding"]
    for t_id in templates:
        wf = get_template_as_workflow(t_id)
        is_valid, errors = validate_dag_structure(wf)
        assert is_valid, f"Template {t_id} failed DAG validation: {errors}"
    print("✓ test_dag_predefined_templates_validity passed (all baseline templates valid)")

if __name__ == "__main__":
    print("Running Engine Test Suite...")
    test_dag_cycle_detection()
    test_dag_condition_branch_validation()
    test_dag_predefined_templates_validity()
    test_tool_fraud_detector()
    test_tool_tax_calculator()
    test_evaluator_conditions()
    test_evaluator_interpolator()
    test_end_to_end_dag_with_approval()
    print("All tests passed successfully! 🎉")

import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.models.schema import ExecutionStatus, NodeType
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

if __name__ == "__main__":
    print("Running Engine Test Suite...")
    test_tool_fraud_detector()
    test_tool_tax_calculator()
    test_evaluator_conditions()
    test_evaluator_interpolator()
    test_end_to_end_dag_with_approval()
    print("All tests passed successfully! 🎉")

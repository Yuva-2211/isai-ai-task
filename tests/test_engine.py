import os
import sys
import pytest

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.models.schema import ExecutionStatus, NodeType, WorkflowDefinition, WorkflowNode, WorkflowEdge
from src.generator.templates import get_template_as_workflow
from src.engine.runner import WorkflowRunner
from src.engine.evaluator import safe_eval_expression, interpolate_string
from src.engine.tool_registry import tool_fraud_detector, tool_tax_calculator
from src.engine.validator import validate_dag_structure


# ─── Tool Tests ──────────────────────────────────────────

class TestTools:
    def test_fraud_detector_returns_risk_fields(self):
        res = tool_fraud_detector({"amount": 800, "email": "suspicious@tempmail.com"})
        assert "risk_score" in res
        assert "risk_level" in res
        assert res["risk_level"] in ["LOW", "MEDIUM", "HIGH"]

    def test_fraud_detector_high_risk_domain(self):
        res = tool_fraud_detector({"amount": 500, "email": "user@fakemail.com"})
        assert res["risk_score"] > 0.5

    def test_tax_calculator_basic(self):
        res = tool_tax_calculator({"amount": 100, "tax_rate": 0.10})
        assert res["tax_amount"] == 10.0
        assert res["total"] == 110.0

    def test_tax_calculator_default_rate(self):
        res = tool_tax_calculator({"amount": 200})
        assert res["tax_rate"] == 0.08
        assert res["tax_amount"] == 16.0


# ─── Evaluator Tests ─────────────────────────────────────

class TestEvaluator:
    def test_simple_comparison(self):
        ctx = {"amount": 750}
        assert safe_eval_expression("amount > 500", ctx) is True
        assert safe_eval_expression("amount < 100", ctx) is False

    def test_nested_context_path(self):
        ctx = {"amount": 750, "nodes": {"step_fraud": {"output": {"risk_score": 0.8}}}}
        assert safe_eval_expression("nodes.step_fraud.output.risk_score > 0.5", ctx) is True

    def test_boolean_operators(self):
        ctx = {"amount": 200, "nodes": {"step_fraud": {"output": {"risk_score": 0.9}}}}
        assert safe_eval_expression("amount > 500 or nodes.step_fraud.output.risk_score > 0.6", ctx) is True
        assert safe_eval_expression("amount > 500 and nodes.step_fraud.output.risk_score > 0.6", ctx) is False

    def test_string_interpolation(self):
        ctx = {"customer_name": "Alice", "amount": 250}
        res = interpolate_string("Refund ${{amount}} for {{customer_name}}", ctx)
        assert res == "Refund $250 for Alice"

    def test_interpolation_missing_key(self):
        ctx = {"amount": 100}
        res = interpolate_string("Hello {{missing_field}}, amount is {{amount}}", ctx)
        assert "100" in res


# ─── DAG Structural Validation Tests ─────────────────────

class TestDAGValidator:
    def test_cycle_detection(self):
        wf = WorkflowDefinition(
            id="wf_cyclic", name="Cyclic", description="Has cycle",
            entrypoint="s1",
            nodes=[
                WorkflowNode(id="s1", type=NodeType.TOOL, label="Step 1"),
                WorkflowNode(id="s2", type=NodeType.TOOL, label="Step 2")
            ],
            edges=[
                WorkflowEdge(from_node="s1", to_node="s2"),
                WorkflowEdge(from_node="s2", to_node="s1")
            ]
        )
        is_valid, errors = validate_dag_structure(wf)
        assert not is_valid
        assert any("cycle" in e.lower() for e in errors)

    def test_missing_condition_branch(self):
        wf = WorkflowDefinition(
            id="wf_bad_cond", name="Bad Cond", description="Missing false",
            entrypoint="check",
            nodes=[
                WorkflowNode(id="check", type=NodeType.CONDITION, label="Check"),
                WorkflowNode(id="target", type=NodeType.TOOL, label="Target")
            ],
            edges=[
                WorkflowEdge(from_node="check", to_node="target", condition_branch="true")
            ]
        )
        is_valid, errors = validate_dag_structure(wf)
        assert not is_valid
        assert any("false" in e for e in errors)

    def test_invalid_entrypoint(self):
        wf = WorkflowDefinition(
            id="wf_bad_entry", name="Bad Entry", description="Wrong entrypoint",
            entrypoint="nonexistent",
            nodes=[WorkflowNode(id="s1", type=NodeType.TOOL, label="S1")],
            edges=[]
        )
        is_valid, errors = validate_dag_structure(wf)
        assert not is_valid
        assert any("entrypoint" in e.lower() for e in errors)

    def test_predefined_templates_all_valid(self):
        for t_id in ["wf_refund_guard", "wf_employee_onboarding"]:
            wf = get_template_as_workflow(t_id)
            is_valid, errors = validate_dag_structure(wf)
            assert is_valid, f"Template {t_id} failed: {errors}"


# ─── End-to-End Execution Tests ──────────────────────────

class TestWorkflowExecution:
    def test_full_refund_flow_with_approval(self):
        wf = get_template_as_workflow("wf_refund_guard")

        # Initialize
        exec_obj = WorkflowRunner.initialize_execution(wf, {
            "refund_id": "TEST-001",
            "customer_email": "test@example.com",
            "amount": 900.0,
            "reason": "Defective item"
        })
        assert exec_obj.status == ExecutionStatus.RUNNING

        # Run until approval pause
        paused = WorkflowRunner.run_step_by_step(exec_obj.id)
        assert paused.status == ExecutionStatus.WAITING_APPROVAL
        assert paused.pending_approval is not None
        assert "900.0" in paused.pending_approval.prompt

        # Approve and resume
        completed = WorkflowRunner.resume_approval(paused.id, "APPROVE", "Authorized.")
        assert completed.status == ExecutionStatus.COMPLETED
        assert len(completed.logs) >= 5  # validate, fraud, condition, approval decision, stripe, email

    def test_rejection_terminates_workflow(self):
        wf = get_template_as_workflow("wf_refund_guard")

        exec_obj = WorkflowRunner.initialize_execution(wf, {
            "refund_id": "TEST-REJECT",
            "customer_email": "reject@example.com",
            "amount": 1200.0,
            "reason": "Test rejection"
        })

        paused = WorkflowRunner.run_step_by_step(exec_obj.id)
        assert paused.status == ExecutionStatus.WAITING_APPROVAL

        rejected = WorkflowRunner.resume_approval(paused.id, "REJECT", "Denied by manager.")
        assert rejected.status == ExecutionStatus.REJECTED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

import time
import datetime
from typing import Dict, Any, Optional, List
from src.models.schema import (
    WorkflowDefinition,
    WorkflowExecution,
    ExecutionStatus,
    StepLog,
    ApprovalRequest,
    NodeType
)
from src.database.db import (
    save_execution,
    get_execution,
    add_step_log,
    get_workflow,
    save_workflow
)
from src.engine.evaluator import safe_eval_expression, interpolate_string
from src.engine.tool_registry import (
    execute_validation,
    execute_tool,
    execute_api,
    execute_transform,
    execute_notification
)

class WorkflowRunner:
    @staticmethod
    def initialize_execution(workflow: WorkflowDefinition, initial_input: Optional[Dict[str, Any]] = None) -> WorkflowExecution:
        """
        Creates a new execution record in the database with initial context.
        """
        save_workflow(workflow)
        context = dict(initial_input or workflow.sample_input)
        context["nodes"] = {}

        execution = WorkflowExecution(
            workflow_id=workflow.id,
            status=ExecutionStatus.RUNNING,
            current_node_id=workflow.entrypoint,
            context=context,
            logs=[],
            started_at=datetime.datetime.utcnow().isoformat()
        )
        save_execution(execution)
        return execution

    @staticmethod
    def run_step_by_step(execution_id: str) -> WorkflowExecution:
        """
        Executes the workflow graph node-by-node until completion or until paused by Human Approval.
        """
        execution = get_execution(execution_id)
        if not execution:
            raise ValueError(f"Execution {execution_id} not found.")

        workflow = get_workflow(execution.workflow_id)
        if not workflow:
            raise ValueError(f"Workflow {execution.workflow_id} not found.")

        node_map = {n.id: n for n in workflow.nodes}
        current_node_id = execution.current_node_id

        while current_node_id:
            node = node_map.get(current_node_id)
            if not node:
                raise ValueError(f"Node '{current_node_id}' does not exist in workflow definition.")

            # Check if this node is Human Approval
            if node.type == NodeType.HUMAN_APPROVAL:
                # Interpolate prompt
                prompt_text = interpolate_string(node.config.get("prompt", "Approval requested"), execution.context)
                approval = ApprovalRequest(
                    execution_id=execution.id,
                    node_id=node.id,
                    prompt=prompt_text,
                    required_role=node.config.get("required_role", "Manager")
                )
                execution.status = ExecutionStatus.WAITING_APPROVAL
                execution.current_node_id = node.id
                execution.pending_approval = approval
                save_execution(execution)

                # Log step pause
                log = StepLog(
                    node_id=node.id,
                    node_type=node.type.value,
                    label=node.label,
                    status="WAITING_APPROVAL",
                    input_data={"prompt": prompt_text, "role": approval.required_role},
                    output_data={"status": "PAUSED_FOR_HUMAN_APPROVAL"},
                    execution_time_ms=0.0
                )
                add_step_log(execution.id, log)
                execution.logs.append(log)
                return execution

            # Execute regular node
            t_start = time.time()
            success, output_data, msg, error_msg = WorkflowRunner._execute_single_node(node, execution.context)
            elapsed_ms = round((time.time() - t_start) * 1000, 2)

            # Store node output into execution context
            execution.context["nodes"][node.id] = {
                "output": output_data,
                "status": "SUCCESS" if success else "FAILED"
            }

            # Record step log
            log = StepLog(
                node_id=node.id,
                node_type=node.type.value,
                label=node.label,
                status="SUCCESS" if success else "FAILED",
                input_data=node.config,
                output_data=output_data,
                error_message=error_msg,
                execution_time_ms=elapsed_ms
            )
            add_step_log(execution.id, log)
            execution.logs.append(log)

            # Handle Node Failure & Error Policy
            if not success:
                err_policy = node.on_error
                if err_policy and err_policy.fallback_node:
                    current_node_id = err_policy.fallback_node
                    execution.current_node_id = current_node_id
                    save_execution(execution)
                    continue
                elif err_policy and not err_policy.fail_workflow:
                    # Continue anyway
                    pass
                else:
                    execution.status = ExecutionStatus.FAILED
                    execution.completed_at = datetime.datetime.utcnow().isoformat()
                    save_execution(execution)
                    return execution

            # Determine next node based on edges and conditions
            current_node_id = WorkflowRunner._determine_next_node(node, workflow, execution.context, output_data)
            execution.current_node_id = current_node_id
            save_execution(execution)

        # Reached the end of workflow
        execution.status = ExecutionStatus.COMPLETED
        execution.completed_at = datetime.datetime.utcnow().isoformat()
        save_execution(execution)
        return execution

    @staticmethod
    def _execute_single_node(node, context: Dict[str, Any]):
        retries = getattr(node.on_error, "retry_count", 0) if node.on_error else 0
        attempts = 0
        
        while attempts <= retries:
            attempts += 1
            try:
                if node.type == NodeType.VALIDATION:
                    success, output, msg = execute_validation(node.config, context)
                elif node.type == NodeType.TOOL:
                    success, output, msg = execute_tool(node.config, context)
                elif node.type == NodeType.API:
                    success, output, msg = execute_api(node.config, context)
                elif node.type == NodeType.TRANSFORM:
                    success, output, msg = execute_transform(node.config, context)
                elif node.type == NodeType.NOTIFICATION:
                    success, output, msg = execute_notification(node.config, context)
                elif node.type == NodeType.CONDITION:
                    expr = node.config.get("expression", "")
                    condition_val = safe_eval_expression(expr, context)
                    return True, {"evaluation_result": condition_val, "expression": expr}, "Condition evaluated", None
                else:
                    return True, {"status": "ok"}, "Default execution", None

                if success:
                    return True, output, msg, None
                elif attempts <= retries:
                    time.sleep(0.2)  # Short retry delay
            except Exception as e:
                if attempts > retries:
                    return False, {}, "Exception during execution", str(e)
                time.sleep(0.2)

        return False, output, msg, msg

    @staticmethod
    def _determine_next_node(current_node, workflow: WorkflowDefinition, context: Dict[str, Any], last_output: Dict[str, Any]) -> Optional[str]:
        outgoing_edges = [e for e in workflow.edges if e.from_node == current_node.id]
        if not outgoing_edges:
            return None

        # If current node is a Condition node, inspect the condition outcome
        if current_node.type == NodeType.CONDITION:
            eval_result = last_output.get("evaluation_result", False)
            expected_branch = "true" if eval_result else "false"
            
            # Find edge matching the branch
            for edge in outgoing_edges:
                if edge.condition_branch == expected_branch:
                    return edge.to_node
            
            # Fallback to unconditional or default edge
            for edge in outgoing_edges:
                if not edge.condition_branch or edge.condition_branch == "default":
                    return edge.to_node
            return None

        # For standard nodes, follow the first available edge
        return outgoing_edges[0].to_node

    @staticmethod
    def resume_approval(execution_id: str, decision: str, comment: Optional[str] = "") -> WorkflowExecution:
        """
        Resumes a paused workflow execution after human manager approval or rejection.
        """
        execution = get_execution(execution_id)
        if not execution:
            raise ValueError(f"Execution {execution_id} not found.")

        if execution.status != ExecutionStatus.WAITING_APPROVAL or not execution.pending_approval:
            raise ValueError(f"Execution {execution_id} is not waiting for approval.")

        workflow = get_workflow(execution.workflow_id)
        current_node_id = execution.current_node_id

        # Update approval record
        approval = execution.pending_approval
        approval.status = "APPROVED" if decision.upper() == "APPROVE" else "REJECTED"
        approval.decision_comment = comment
        approval.resolved_at = datetime.datetime.utcnow().isoformat()

        # Update step log for the approval node
        log = StepLog(
            node_id=current_node_id,
            node_type=NodeType.HUMAN_APPROVAL.value,
            label="Human Decision",
            status="SUCCESS" if decision.upper() == "APPROVE" else "REJECTED",
            input_data={"prompt": approval.prompt},
            output_data={"decision": approval.status, "comment": comment},
            execution_time_ms=0.0
        )
        add_step_log(execution.id, log)
        execution.logs.append(log)

        # Put decision in context
        execution.context["nodes"][current_node_id] = {
            "output": {"decision": approval.status, "comment": comment},
            "status": approval.status
        }

        if decision.upper() == "REJECT":
            execution.status = ExecutionStatus.REJECTED
            execution.completed_at = datetime.datetime.utcnow().isoformat()
            execution.pending_approval = None
            save_execution(execution)
            return execution

        # Find next node from approval node
        outgoing_edges = [e for e in workflow.edges if e.from_node == current_node_id]
        if outgoing_edges:
            execution.current_node_id = outgoing_edges[0].to_node
            execution.status = ExecutionStatus.RUNNING
            execution.pending_approval = None
            save_execution(execution)
            # Resume loop
            return WorkflowRunner.run_step_by_step(execution.id)
        else:
            execution.status = ExecutionStatus.COMPLETED
            execution.completed_at = datetime.datetime.utcnow().isoformat()
            execution.pending_approval = None
            save_execution(execution)
            return execution

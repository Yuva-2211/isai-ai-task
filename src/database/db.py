import sqlite3
import json
import os
from typing import Optional, List, Dict, Any
from src.models.schema import (
    WorkflowDefinition, 
    WorkflowExecution, 
    StepLog, 
    ApprovalRequest,
    ExecutionStatus
)

DB_PATH = os.getenv("SQLITE_DB_PATH", "workflows.db")

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # 1. Workflows Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS workflows (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT,
        entrypoint TEXT NOT NULL,
        sample_input TEXT,
        definition_json TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 2. Workflow Executions Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS executions (
        id TEXT PRIMARY KEY,
        workflow_id TEXT NOT NULL,
        status TEXT NOT NULL,
        current_node_id TEXT,
        context_json TEXT NOT NULL,
        started_at TEXT,
        completed_at TEXT,
        FOREIGN KEY (workflow_id) REFERENCES workflows(id)
    );
    """)

    # 3. Step Logs Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS step_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        execution_id TEXT NOT NULL,
        node_id TEXT NOT NULL,
        node_type TEXT NOT NULL,
        label TEXT,
        status TEXT NOT NULL,
        input_data_json TEXT,
        output_data_json TEXT,
        error_message TEXT,
        execution_time_ms REAL,
        timestamp TEXT,
        FOREIGN KEY (execution_id) REFERENCES executions(id)
    );
    """)

    # 4. Approval Requests Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS approval_requests (
        id TEXT PRIMARY KEY,
        execution_id TEXT NOT NULL,
        node_id TEXT NOT NULL,
        prompt TEXT NOT NULL,
        required_role TEXT,
        status TEXT NOT NULL,
        decision_comment TEXT,
        requested_at TEXT,
        resolved_at TEXT,
        FOREIGN KEY (execution_id) REFERENCES executions(id)
    );
    """)

    conn.commit()
    conn.close()

# --- Repository Methods ---

def save_workflow(wf: WorkflowDefinition) -> WorkflowDefinition:
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO workflows (id, name, description, entrypoint, sample_input, definition_json)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        wf.id,
        wf.name,
        wf.description,
        wf.entrypoint,
        json.dumps(wf.sample_input),
        wf.model_dump_json()
    ))
    conn.commit()
    conn.close()
    return wf

def get_workflow(wf_id: str) -> Optional[WorkflowDefinition]:
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT definition_json FROM workflows WHERE id = ?", (wf_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return WorkflowDefinition.model_validate_json(row["definition_json"])
    return None

def list_workflows() -> List[WorkflowDefinition]:
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT definition_json FROM workflows ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [WorkflowDefinition.model_validate_json(r["definition_json"]) for r in rows]

def save_execution(exec_obj: WorkflowExecution) -> WorkflowExecution:
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO executions (id, workflow_id, status, current_node_id, context_json, started_at, completed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        exec_obj.id,
        exec_obj.workflow_id,
        exec_obj.status.value,
        exec_obj.current_node_id,
        json.dumps(exec_obj.context),
        exec_obj.started_at,
        exec_obj.completed_at
    ))

    # Save pending approval if exists
    if exec_obj.pending_approval:
        appr = exec_obj.pending_approval
        cursor.execute("""
            INSERT OR REPLACE INTO approval_requests (id, execution_id, node_id, prompt, required_role, status, decision_comment, requested_at, resolved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            appr.id,
            appr.execution_id,
            appr.node_id,
            appr.prompt,
            appr.required_role,
            appr.status,
            appr.decision_comment,
            appr.requested_at,
            appr.resolved_at
        ))

    conn.commit()
    conn.close()
    return exec_obj

def add_step_log(execution_id: str, log: StepLog):
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO step_logs (execution_id, node_id, node_type, label, status, input_data_json, output_data_json, error_message, execution_time_ms, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        execution_id,
        log.node_id,
        log.node_type,
        log.label,
        log.status,
        json.dumps(log.input_data),
        json.dumps(log.output_data),
        log.error_message,
        log.execution_time_ms,
        log.timestamp
    ))
    conn.commit()
    conn.close()

def get_execution(execution_id: str) -> Optional[WorkflowExecution]:
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM executions WHERE id = ?", (execution_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None
    
    # Fetch logs
    cursor.execute("SELECT * FROM step_logs WHERE execution_id = ? ORDER BY id ASC", (execution_id,))
    log_rows = cursor.fetchall()
    logs = [
        StepLog(
            node_id=lr["node_id"],
            node_type=lr["node_type"],
            label=lr["label"] or "",
            status=lr["status"],
            input_data=json.loads(lr["input_data_json"] or "{}"),
            output_data=json.loads(lr["output_data_json"] or "{}"),
            error_message=lr["error_message"],
            execution_time_ms=lr["execution_time_ms"] or 0.0,
            timestamp=lr["timestamp"]
        )
        for lr in log_rows
    ]

    # Fetch pending approval if any
    cursor.execute("SELECT * FROM approval_requests WHERE execution_id = ? AND status = 'PENDING'", (execution_id,))
    appr_row = cursor.fetchone()
    pending_approval = None
    if appr_row:
        pending_approval = ApprovalRequest(
            id=appr_row["id"],
            execution_id=appr_row["execution_id"],
            node_id=appr_row["node_id"],
            prompt=appr_row["prompt"],
            required_role=appr_row["required_role"],
            status=appr_row["status"],
            decision_comment=appr_row["decision_comment"],
            requested_at=appr_row["requested_at"],
            resolved_at=appr_row["resolved_at"]
        )

    conn.close()

    return WorkflowExecution(
        id=row["id"],
        workflow_id=row["workflow_id"],
        status=ExecutionStatus(row["status"]),
        current_node_id=row["current_node_id"],
        context=json.loads(row["context_json"]),
        logs=logs,
        pending_approval=pending_approval,
        started_at=row["started_at"],
        completed_at=row["completed_at"]
    )

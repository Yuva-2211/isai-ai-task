from typing import List, Tuple, Dict, Set
from collections import defaultdict
from src.models.schema import WorkflowDefinition, NodeType

class DAGValidationError(Exception):
    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__("; ".join(errors))

def validate_dag_structure(wf: WorkflowDefinition) -> Tuple[bool, List[str]]:
    """
    Validates structural integrity of the workflow graph:
    1. Entrypoint existence
    2. Node ID uniqueness
    3. Edge validity (from_node and to_node existence)
    4. Acyclicity (No cycles; must be a valid Directed Acyclic Graph)
    5. Condition node completeness (both 'true' and 'false' branches present)
    6. Reachability (no orphaned/unreachable nodes from entrypoint)
    """
    errors: List[str] = []

    # 1. Node ID uniqueness and existence mapping
    node_ids = set()
    node_type_map = {}
    for node in wf.nodes:
        if node.id in node_ids:
            errors.append(f"Duplicate node ID detected: '{node.id}'")
        node_ids.add(node.id)
        node_type_map[node.id] = node.type

    if not node_ids:
        errors.append("Workflow has no nodes defined.")
        return False, errors

    # 2. Entrypoint check
    if not wf.entrypoint or wf.entrypoint not in node_ids:
        errors.append(f"Invalid entrypoint '{wf.entrypoint}'. It must match an existing node ID in: {list(node_ids)}")

    # Build adjacency list
    adj: Dict[str, List[str]] = defaultdict(list)
    condition_edges: Dict[str, Set[str]] = defaultdict(set)

    # 3. Edge references integrity
    for edge in wf.edges:
        if edge.from_node not in node_ids:
            errors.append(f"Edge 'from_node' '{edge.from_node}' does not exist in nodes.")
        if edge.to_node not in node_ids:
            errors.append(f"Edge 'to_node' '{edge.to_node}' does not exist in nodes.")
        
        if edge.from_node in node_ids and edge.to_node in node_ids:
            adj[edge.from_node].append(edge.to_node)
            if edge.condition_branch:
                condition_edges[edge.from_node].add(edge.condition_branch.lower())

    # Include on_error fallback_nodes as valid transition edges
    for node in wf.nodes:
        if node.on_error and node.on_error.fallback_node:
            fallback = node.on_error.fallback_node
            if fallback not in node_ids:
                errors.append(f"Node '{node.id}' references non-existent fallback_node '{fallback}'.")
            else:
                adj[node.id].append(fallback)

    # 4. Condition Node branch completeness check
    for node in wf.nodes:
        if node.type == NodeType.CONDITION:
            branches = condition_edges.get(node.id, set())
            missing = []
            if "true" not in branches:
                missing.append("true")
            if "false" not in branches:
                missing.append("false")
            if missing:
                errors.append(
                    f"Condition node '{node.id}' ('{node.label}') is missing outgoing edge(s) for branch: {missing}. "
                    f"A condition node must branch to both 'true' and 'false' target nodes."
                )

    # 5. Cycle Detection using DFS (3-color tracking: 0=unvisited, 1=visiting, 2=visited)
    color = {nid: 0 for nid in node_ids}
    cycle_nodes = []

    def dfs_cycle(curr: str, path: List[str]) -> bool:
        color[curr] = 1  # visiting
        path.append(curr)

        for neighbor in adj.get(curr, []):
            if color[neighbor] == 1:
                # Found cycle
                cycle_start_idx = path.index(neighbor)
                cycle_path = " -> ".join(path[cycle_start_idx:] + [neighbor])
                cycle_nodes.append(cycle_path)
                return True
            elif color[neighbor] == 0:
                if dfs_cycle(neighbor, path):
                    return True

        path.pop()
        color[curr] = 2  # fully visited
        return False

    # Check cycles starting from all nodes to catch disconnected cycles
    for nid in node_ids:
        if color[nid] == 0:
            dfs_cycle(nid, [])

    if cycle_nodes:
        errors.append(f"Graph cycle detected: {'; '.join(cycle_nodes)}. Workflows must be Directed Acyclic Graphs (DAGs).")

    # 6. Reachability check from entrypoint (BFS)
    if wf.entrypoint in node_ids:
        visited = set()
        queue = [wf.entrypoint]
        visited.add(wf.entrypoint)

        while queue:
            curr = queue.pop(0)
            for nxt in adj.get(curr, []):
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append(nxt)

        unreachable = node_ids - visited
        if unreachable:
            errors.append(
                f"Unreachable / orphaned nodes detected: {list(unreachable)}. "
                f"Every node in the workflow must have a path leading from the entrypoint '{wf.entrypoint}'."
            )

    is_valid = len(errors) == 0
    return is_valid, errors


def validate_semantic_integrity(wf: WorkflowDefinition) -> Tuple[bool, List[str]]:
    """
    Validates semantic correctness and execution-readiness of the workflow:
    1. Node configurations have required fields per NodeType
    2. Tool names are specified
    3. API endpoints and HTTP methods are valid
    4. Condition expressions are non-empty
    5. Human approval prompts are non-empty
    6. Validation rules specify field and operator
    7. Variable references ({{var}}) map to existing nodes or sample inputs
    """
    import re
    errors: List[str] = []
    node_ids = {n.id for n in wf.nodes}

    for node in wf.nodes:
        cfg = node.config or {}

        # 1. Validation node checks
        if node.type == NodeType.VALIDATION:
            rules = cfg.get("rules")
            if not rules or not isinstance(rules, list):
                errors.append(f"Validation node '{node.id}' must define a non-empty 'rules' list in config.")
            else:
                for r in rules:
                    if not isinstance(r, dict) or "field" not in r or "operator" not in r:
                        errors.append(f"Validation node '{node.id}' has invalid rule definition: {r}. Must have 'field' and 'operator'.")

        # 2. Tool node checks
        elif node.type == NodeType.TOOL:
            tool_name = cfg.get("tool_name")
            if not tool_name or not isinstance(tool_name, str):
                errors.append(f"Tool node '{node.id}' must specify a valid string 'tool_name' in config.")

        # 3. API node checks
        elif node.type == NodeType.API:
            method = str(cfg.get("method", "")).upper()
            valid_methods = {"GET", "POST", "PUT", "DELETE", "PATCH"}
            if method not in valid_methods:
                errors.append(f"API node '{node.id}' has invalid HTTP method '{method}'. Must be one of {valid_methods}.")
            endpoint = cfg.get("endpoint")
            if not endpoint or not isinstance(endpoint, str):
                errors.append(f"API node '{node.id}' must specify a non-empty string 'endpoint' in config.")

        # 4. Condition node checks
        elif node.type == NodeType.CONDITION:
            expr = cfg.get("expression")
            if not expr or not isinstance(expr, str) or not expr.strip():
                errors.append(f"Condition node '{node.id}' must specify a non-empty boolean 'expression' string in config.")

        # 5. Human Approval node checks
        elif node.type == NodeType.HUMAN_APPROVAL:
            prompt = cfg.get("prompt")
            if not prompt or not isinstance(prompt, str) or not prompt.strip():
                errors.append(f"Human approval node '{node.id}' must specify a non-empty 'prompt' in config.")

        # 6. Notification node checks
        elif node.type == NodeType.NOTIFICATION:
            msg = cfg.get("message")
            if not msg or not isinstance(msg, str):
                errors.append(f"Notification node '{node.id}' must specify a non-empty 'message' in config.")

        # 7. Check template variable interpolation references {{nodes.xyz.output...}}
        def find_interpolations(obj):
            found = []
            if isinstance(obj, str):
                matches = re.findall(r"\{\{([^}]+)\}\}", obj)
                found.extend(matches)
            elif isinstance(obj, dict):
                for v in obj.values():
                    found.extend(find_interpolations(v))
            elif isinstance(obj, list):
                for item in obj:
                    found.extend(find_interpolations(item))
            return found

        vars_used = find_interpolations(cfg)
        for var_expr in vars_used:
            var_clean = var_expr.strip()
            if var_clean.startswith("nodes."):
                parts = var_clean.split(".")
                if len(parts) >= 2:
                    ref_node_id = parts[1]
                    if ref_node_id not in node_ids:
                        errors.append(f"Node '{node.id}' references non-existent node '{ref_node_id}' in template '{{{{{var_clean}}}}}'.")

    return len(errors) == 0, errors


def validate_complete_workflow(wf: WorkflowDefinition) -> Tuple[bool, List[str]]:
    """
    Executes both DAG structural validation and semantic integrity validation.
    """
    errors: List[str] = []
    dag_valid, dag_errors = validate_dag_structure(wf)
    if not dag_valid:
        errors.extend([f"[DAG Structure] {e}" for e in dag_errors])

    sem_valid, sem_errors = validate_semantic_integrity(wf)
    if not sem_valid:
        errors.extend([f"[Semantic Integrity] {e}" for e in sem_errors])

    return len(errors) == 0, errors

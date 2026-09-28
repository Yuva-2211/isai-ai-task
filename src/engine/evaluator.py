import re
import ast
import operator
from typing import Any, Dict

# Safe operators for condition evaluation
SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.And: lambda a, b: a and b,
    ast.Or: lambda a, b: a or b,
    ast.Not: operator.not_,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}

def resolve_context_path(path: str, context: Dict[str, Any]) -> Any:
    """
    Extracts nested values from context using dot notation (e.g., 'nodes.step_1.output.score' or 'amount').
    """
    parts = path.strip().split(".")
    # If starts with 'context', strip it
    if parts and parts[0] == "context":
        parts = parts[1:]
    
    current = context
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif hasattr(current, part):
            current = getattr(current, part)
        else:
            return None
    return current

def interpolate_string(text: str, context: Dict[str, Any]) -> str:
    """
    Replaces mustache expressions like {{context.amount}} or {{customer_email}} with context values.
    """
    if not isinstance(text, str):
        return text

    def replacer(match):
        raw_key = match.group(1).strip()
        val = resolve_context_path(raw_key, context)
        return str(val) if val is not None else ""

    return re.sub(r"\{\{([^}]+)\}\}", replacer, text)

def interpolate_payload(payload: Any, context: Dict[str, Any]) -> Any:
    """
    Recursively interpolates strings in dictionaries, lists, or primitives.
    """
    if isinstance(payload, str):
        # If the string is purely a template like "{{context.amount}}", return raw typed value
        pure_match = re.fullmatch(r"\{\{([^}]+)\}\}", payload.strip())
        if pure_match:
            resolved = resolve_context_path(pure_match.group(1).strip(), context)
            if resolved is not None:
                return resolved
        return interpolate_string(payload, context)
    elif isinstance(payload, dict):
        return {k: interpolate_payload(v, context) for k, v in payload.items()}
    elif isinstance(payload, list):
        return [interpolate_payload(v, context) for v in payload]
    return payload

def safe_eval_expression(expr_str: str, context: Dict[str, Any]) -> bool:
    """
    Safely parses and evaluates simple boolean and arithmetic expressions without eval() vulnerability.
    Supports syntax like: 'context.amount > 500' or 'risk_score >= 0.7' or 'status == "active"'
    """
    if not expr_str or not expr_str.strip():
        return True

    # Pre-substitute context variables into safe literals or AST lookup
    class SafeEvaluator(ast.NodeVisitor):
        def visit(self, node):
            if isinstance(node, ast.Expression):
                return self.visit(node.body)
            elif isinstance(node, ast.Constant):
                return node.value
            elif isinstance(node, ast.Attribute) or isinstance(node, ast.Name):
                # Reconstruct full dotted variable name
                dotted_path = self._get_full_attr_path(node)
                return resolve_context_path(dotted_path, context)
            elif isinstance(node, ast.UnaryOp):
                operand = self.visit(node.operand)
                op_type = type(node.op)
                if op_type in SAFE_OPERATORS:
                    return SAFE_OPERATORS[op_type](operand)
                raise ValueError(f"Unsupported unary operator: {op_type}")
            elif isinstance(node, ast.BinOp):
                left = self.visit(node.left)
                right = self.visit(node.right)
                op_type = type(node.op)
                if op_type in SAFE_OPERATORS:
                    return SAFE_OPERATORS[op_type](left, right)
                raise ValueError(f"Unsupported binary operator: {op_type}")
            elif isinstance(node, ast.BoolOp):
                values = [self.visit(val) for val in node.values]
                if isinstance(node.op, ast.And):
                    return all(values)
                elif isinstance(node.op, ast.Or):
                    return any(values)
            elif isinstance(node, ast.Compare):
                left = self.visit(node.left)
                for op, comparator in zip(node.ops, node.comparators):
                    right = self.visit(comparator)
                    op_type = type(op)
                    if op_type in SAFE_OPERATORS:
                        if not SAFE_OPERATORS[op_type](left, right):
                            return False
                        left = right
                    else:
                        raise ValueError(f"Unsupported comparison operator: {op_type}")
                return True
            else:
                raise ValueError(f"Unsupported AST node: {type(node)}")

        def _get_full_attr_path(self, node):
            parts = []
            curr = node
            while isinstance(curr, ast.Attribute):
                parts.append(curr.attr)
                curr = curr.value
            if isinstance(curr, ast.Name):
                parts.append(curr.id)
            return ".".join(reversed(parts))

    try:
        parsed = ast.parse(expr_str.strip(), mode="eval")
        evaluator = SafeEvaluator()
        result = evaluator.visit(parsed)
        return bool(result)
    except Exception as e:
        # Fallback evaluation warning
        print(f"[Warning] Safe eval error on '{expr_str}': {e}")
        return False

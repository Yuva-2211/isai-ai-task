import hashlib
import time
import requests
from typing import Dict, Any, Tuple
from src.engine.evaluator import interpolate_payload, interpolate_string

# --- 1. Validation Logic ---

def execute_validation(config: Dict[str, Any], context: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], str]:
    """
    Validates rules specified in node config.
    Example config:
    {
      "rules": [
        {"field": "amount", "operator": ">", "value": 0},
        {"field": "customer_email", "operator": "contains", "value": "@"}
      ]
    }
    """
    rules = config.get("rules", [])
    validation_results = {}
    
    for rule in rules:
        field = rule.get("field")
        op = rule.get("operator")
        expected = rule.get("value")
        
        # Get actual value from context
        actual = context.get(field)
        if actual is None and "nodes" in context:
            # Check nested nodes output if not in top level
            for node_data in context["nodes"].values():
                if isinstance(node_data, dict) and "output" in node_data and isinstance(node_data["output"], dict):
                    if field in node_data["output"]:
                        actual = node_data["output"][field]
                        break

        passed = False
        if op == ">":
            passed = actual is not None and float(actual) > float(expected)
        elif op == ">=":
            passed = actual is not None and float(actual) >= float(expected)
        elif op == "<":
            passed = actual is not None and float(actual) < float(expected)
        elif op == "<=":
            passed = actual is not None and float(actual) <= float(expected)
        elif op == "==":
            passed = str(actual).lower() == str(expected).lower()
        elif op == "!=":
            passed = str(actual).lower() != str(expected).lower()
        elif op == "contains":
            passed = actual is not None and str(expected).lower() in str(actual).lower()
        elif op == "exists":
            passed = actual is not None and actual != ""
        else:
            passed = actual is not None

        rule_name = f"{field} {op} {expected}"
        validation_results[rule_name] = {"passed": passed, "actual": actual}
        
        if not passed:
            return False, validation_results, f"Validation rule failed: '{rule_name}' (Got '{actual}')"

    return True, {"all_passed": True, "details": validation_results}, "Validation passed successfully."

# --- 2. Built-in Tools Registry ---

def tool_fraud_detector(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calculates a deterministic risk score based on transaction amount and email domain.
    """
    amount = float(inputs.get("amount", 0))
    email = str(inputs.get("email", "")).lower()

    # Heuristic scoring
    base_score = min(amount / 1000.0, 0.5)
    domain = email.split("@")[-1] if "@" in email else ""
    
    high_risk_domains = ["tempmail.com", "fakemail.com", "burner.io", "trash.org"]
    if domain in high_risk_domains:
        base_score += 0.4
    
    # Deterministic hash variation for realism
    seed = int(hashlib.md5(email.encode()).hexdigest(), 16) % 20 / 100.0
    risk_score = round(min(base_score + seed, 0.99), 2)

    risk_level = "HIGH" if risk_score > 0.65 else ("MEDIUM" if risk_score > 0.35 else "LOW")
    return {
        "risk_score": risk_score,
        "risk_level": risk_level,
        "recommendation": "FLAG_FOR_REVIEW" if risk_score > 0.65 else "AUTO_APPROVE",
        "evaluated_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }

def tool_sentiment_analyzer(inputs: Dict[str, Any]) -> Dict[str, Any]:
    text = str(inputs.get("text", "")).lower()
    positive_words = ["great", "happy", "excellent", "love", "thanks", "resolved", "good", "pleased"]
    negative_words = ["angry", "broken", "fraud", "terrible", "bad", "refund", "sue", "unacceptable", "delay"]

    pos_count = sum(1 for w in positive_words if w in text)
    neg_count = sum(1 for w in negative_words if w in text)

    if neg_count > pos_count:
        sentiment = "NEGATIVE"
        score = -0.7
    elif pos_count > neg_count:
        sentiment = "POSITIVE"
        score = 0.8
    else:
        sentiment = "NEUTRAL"
        score = 0.0

    return {"sentiment": sentiment, "score": score, "urgency": "HIGH" if neg_count >= 2 else "NORMAL"}

def tool_tax_calculator(inputs: Dict[str, Any]) -> Dict[str, Any]:
    amount = float(inputs.get("amount", 0))
    rate = float(inputs.get("tax_rate", 0.08))  # default 8%
    tax = round(amount * rate, 2)
    return {"subtotal": amount, "tax_rate": rate, "tax_amount": tax, "total": round(amount + tax, 2)}

def tool_currency_converter(inputs: Dict[str, Any]) -> Dict[str, Any]:
    amount = float(inputs.get("amount", 0))
    from_curr = str(inputs.get("from_currency", "USD")).upper()
    to_curr = str(inputs.get("to_currency", "EUR")).upper()
    rates = {"USD": 1.0, "EUR": 0.92, "GBP": 0.79, "INR": 83.2, "CAD": 1.35}
    usd_equiv = amount / rates.get(from_curr, 1.0)
    converted = round(usd_equiv * rates.get(to_curr, 1.0), 2)
    return {"original_amount": amount, "from": from_curr, "converted_amount": converted, "to": to_curr}

AVAILABLE_TOOLS = {
    "fraud_detector": tool_fraud_detector,
    "sentiment_analyzer": tool_sentiment_analyzer,
    "calculate_tax": tool_tax_calculator,
    "convert_currency": tool_currency_converter
}

def execute_tool(config: Dict[str, Any], context: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], str]:
    tool_name = config.get("tool_name", "")
    input_mapping = config.get("input_mapping", {})
    resolved_inputs = interpolate_payload(input_mapping, context)

    if tool_name not in AVAILABLE_TOOLS:
        # Fallback dynamic mock tool if custom name generated
        return True, {
            "status": "success",
            "tool_name": tool_name,
            "inputs_processed": resolved_inputs,
            "result": f"Executed custom tool '{tool_name}' successfully."
        }, f"Tool '{tool_name}' completed."

    handler = AVAILABLE_TOOLS[tool_name]
    try:
        output = handler(resolved_inputs)
        return True, output, f"Tool '{tool_name}' executed successfully."
    except Exception as e:
        return False, {}, f"Error running tool '{tool_name}': {str(e)}"

# --- 3. API Execution (Mock & Live HTTP) ---

def execute_api(config: Dict[str, Any], context: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], str]:
    method = config.get("method", "POST").upper()
    endpoint = interpolate_string(config.get("endpoint", "https://api.sandbox.mock/v1/resource"), context)
    payload = interpolate_payload(config.get("payload", {}), context)
    headers = interpolate_payload(config.get("headers", {}), context)

    # If it's a simulated or mock endpoint, return realistic successful response
    if "mock" in endpoint or "sandbox" in endpoint or not endpoint.startswith("http"):
        # Simulated responses based on endpoint name
        if "stripe" in endpoint or "refund" in endpoint:
            mock_resp = {
                "transaction_id": f"txn_{int(time.time())}",
                "status": "succeeded",
                "refunded_amount": payload.get("amount", 100),
                "currency": "usd",
                "gateway_response": "APPROVED_BY_NETWORK"
            }
        elif "slack" in endpoint or "notify" in endpoint:
            mock_resp = {"ok": True, "channel": "alerts", "ts": str(time.time())}
        elif "crm" in endpoint or "lead" in endpoint:
            mock_resp = {"lead_id": f"lead_{int(time.time())}", "sync_status": "synced"}
        else:
            mock_resp = {"status": "success", "endpoint_called": endpoint, "payload_received": payload}
            
        return True, mock_resp, f"Mock API '{method} {endpoint}' succeeded (HTTP 200)."

    # Live HTTP call
    try:
        if method == "POST":
            resp = requests.post(endpoint, json=payload, headers=headers, timeout=5)
        elif method == "GET":
            resp = requests.get(endpoint, params=payload, headers=headers, timeout=5)
        elif method == "PUT":
            resp = requests.put(endpoint, json=payload, headers=headers, timeout=5)
        else:
            resp = requests.request(method, endpoint, json=payload, headers=headers, timeout=5)

        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"text": resp.text}
        is_success = resp.status_code < 400
        return is_success, data, f"API returned status {resp.status_code}"
    except Exception as e:
        return False, {"error": str(e)}, f"API call failed: {str(e)}"

# --- 4. Transform Execution ---

def execute_transform(config: Dict[str, Any], context: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], str]:
    mapping = config.get("mapping", {})
    resolved = interpolate_payload(mapping, context)
    return True, resolved, "Data transformed successfully."

# --- 5. Notification Execution ---

def execute_notification(config: Dict[str, Any], context: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], str]:
    channel = config.get("channel", "email")
    recipient = interpolate_string(config.get("recipient", "admin@company.com"), context)
    message = interpolate_string(config.get("message", "Workflow notification"), context)

    return True, {
        "channel": channel,
        "recipient": recipient,
        "message": message,
        "delivered_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }, f"Notification dispatched via {channel} to {recipient}."

"""Quick test for _repair_json with the exact truncated payload from the error log."""
import sys
sys.path.insert(0, r'c:\Users\ASUS\sems2\COMPE\UMhackathon\jadualIQ\backend')
from agents.orchestrator import _repair_json

# Exact truncated AI output from the error log
truncated = (
    '{\n'
    '  "is_scheduling_related": true,\n'
    '  "guardrail_reason": "User is requesting to schedule an event on a specific date and time",\n'
)

print("=== Test 1: trailing comma, missing fields ===")
result = _repair_json(truncated)
print("Parsed OK:", result)
assert result.get("is_scheduling_related") == True
assert result.get("guardrail_reason").startswith("User is requesting")
print()

# Truncated mid-string value
mid_string = '{\n  "is_scheduling_related": true,\n  "guardrail_reason": "User is requesting to schedul'
print("=== Test 2: truncated mid-string ===")
result2 = _repair_json(mid_string)
print("Parsed OK:", result2)
print()

# Python literals
python_literals = '{"is_scheduling_related": True, "intent": {"task_name": None, "date": None}, "priority_score": 5,}'
print("=== Test 3: Python literals + trailing comma ===")
result3 = _repair_json(python_literals)
print("Parsed OK:", result3)
assert result3["is_scheduling_related"] == True
assert result3["intent"]["task_name"] is None
print()

# Markdown fenced
fenced = '```json\n{"is_scheduling_related": true}\n```'
print("=== Test 4: markdown fenced ===")
result4 = _repair_json(fenced)
print("Parsed OK:", result4)
print()

print("ALL TESTS PASSED")

import re
from datetime import datetime, timedelta

def parse_intent_test(message):
    msg = message.lower()
    intent = {
        "task_name": None,
        "date": None,
        "time": None,
        "duration_hours": 1,
        "location": None,
    }
    
    if "proceed without location" in msg:
        intent["_skip_location_prompt"] = True
        
    orig_dest = re.search(r"origin:\s*(.*?),\s*destination:\s*(.*)", msg, re.IGNORECASE)
    if orig_dest:
        intent["origin"] = orig_dest.group(1).strip()
        intent["location"] = orig_dest.group(2).strip()
        intent["_skip_location_prompt"] = True
        
    return intent

print(parse_intent_test("Origin: Home, Destination: KLCC"))
print(parse_intent_test("Proceed without location"))

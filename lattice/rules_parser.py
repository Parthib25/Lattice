import re
from typing import List, Dict, Any

DEFAULT_TEMPLATE = """# System Architecture & Team Dependency Rules

This file defines critical system components, architectural keywords, team ownership, and the guardrail policies associated with them. The Feature Feasibility Agent parses this file to detect organizational dependencies when evaluating incoming feature requests.

---

## 1. Component Rules & Ownership

### Component: Global Authentication ("bouncer")
- **Keywords**: bouncer, oauth, token-validation, sso, jwt
- **Owning Team**: IAM Security Team (Contact: #security-iam)
- **Protected Paths**: /src/auth/**/*, /lib/bouncer/**/*
- **Rule Severity**: REQUIRE_REVIEW
- **Guardrail Message**: Any modifications to or integrations with the globally managed authentication system ("bouncer") require approval from the IAM Security Team.

---

### Component: Financial Transactions ("ledger")
- **Keywords**: ledger, billing, stripe, invoice, payout
- **Owning Team**: Finance Engineering (Contact: #eng-finance)
- **Protected Paths**: /services/billing/**/*, /db/migrations/*_billing.sql
- **Rule Severity**: BLOCK
- **Guardrail Message**: Core ledger and transaction logic is locked. Changes must be routed through Finance Engineering; PMs cannot independently authorize modifications here.
"""

def parse_rules_markdown(content: str) -> List[Dict[str, Any]]:
    """
    Parses a markdown configuration file and extracts rules blocks.
    Looks for components defined under ### Component: <Name> headers.
    """
    rules = []
    
    # Split by component blocks
    sections = re.split(r'###\s+Component:', content)
    # The first section is preamble
    for section in sections[1:]:
        lines = section.strip().split('\n')
        if not lines:
            continue
            
        component_name = lines[0].strip()
        rule = {
            "component": component_name,
            "keywords": [],
            "owning_team": "",
            "protected_paths": [],
            "rule_type": "INFORM",
            "guardrail_message": ""
        }
        
        for line in lines[1:]:
            line = line.strip()
            if line.startswith('- **Keywords**:'):
                kws = line.replace('- **Keywords**:', '').strip()
                rule["keywords"] = [k.strip().lower() for k in kws.split(',') if k.strip()]
            elif line.startswith('- **Owning Team**:'):
                rule["owning_team"] = line.replace('- **Owning Team**:', '').strip()
            elif line.startswith('- **Protected Paths**:'):
                paths = line.replace('- **Protected Paths**:', '').strip()
                rule["protected_paths"] = [p.strip() for p in paths.split(',') if p.strip()]
            elif line.startswith('- **Rule Severity**:'):
                rule["rule_type"] = line.replace('- **Rule Severity**:', '').strip().upper()
            elif line.startswith('- **Guardrail Message**:'):
                rule["guardrail_message"] = line.replace('- **Guardrail Message**:', '').strip()
                
        rules.append(rule)
        
    return rules

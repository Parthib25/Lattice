# System Architecture & Team Dependency Rules

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

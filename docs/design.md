# Design Note — ERPNext Onboarding

Written before implementation (phase 2 of the build plan). This is the contract the code
follows; the README's rationale section is derived from it.

## Business record

**Onboarding Request** — one custom parent DocType representing a client's journey from
"interested" to "ready for storage agreement". Created by a Sales Officer against an
existing **Customer**, reviewed and approved by an Operations Manager.

### ERPNext reuse decisions

| Need | Decision | Why |
| --- | --- | --- |
| Client master | Link to standard **Customer** (required) | Customer already carries identity, contacts, addresses, and downstream sales integration. Recreating it would fork the client master and break every standard flow. |
| CRM origin | Optional links to **Lead** / **Opportunity** | Records where the request came from without forcing CRM usage; the approval flow must work even when the handover starts at Customer. |
| Storage packages | Child rows link to standard **Item** (services) | Packages are priceable services — exactly what Item models. Reusing Item gives naming, pricing fields, and future Sales Order compatibility for free. |
| The request itself | **Custom DocType** | No standard DocType models "an approval case with its own lifecycle". Quotation is the nearest, but hijacking its docstatus/workflow for a custody-style approval trail would fight core behaviour on every upgrade. |

## DocTypes

### Onboarding Request (parent)

- **Naming series**: `ONB-.YYYY.-.#####` (e.g. `ONB-2026-00042`) — sortable, year-scoped,
  human-quotable in emails.
- **Not submittable** (no docstatus). Lifecycle is fully expressed by `workflow_state` +
  Python immutability guards. Making it submittable would drag in cancel/amend semantics
  that contradict an append-only history (an amended duplicate would orphan the audit
  trail). This is a deliberate decision to defend in review.
- Key fields: customer (Link, reqd), lead / opportunity (Link, optional), requested_by
  (Link User, set from session, read-only), request_date (Date, reqd), workflow_state
  (Select, read-only, workflow-managed), decision fields (approved_by, decided_on,
  decision_reason), money fields (total_amount, discount_amount, final_amount — all
  Currency, computed server-side, read-only).

### Onboarding Request Item (child table)

- Child table, not a linked DocType: line items have no identity or lifecycle of their
  own — they are never queried, approved, or referenced independently of their parent.
- Fields: item (Link Item, reqd), description, qty (Float, reqd > 0), rate (Currency,
  reqd ≥ 0), discount_percent (Percent, 0–100), amount (Currency, computed, read-only).

### Onboarding Audit Log (phase 6)

- Separate DocType, one row per state transition: request (Link), from_state, to_state,
  actor, timestamp, reason. Append-only: no write, no delete, ever — enforced in its
  controller, not by permissions alone.
- This is a **linked DocType, not a child table**, deliberately: child rows are editable
  whenever the parent is editable, which would let a user rewrite history through the
  parent form. A separate DocType gets its own permission matrix and its own controller
  guards. (This contrast is the README's child-table-vs-linked-DocType answer.)

## State machine

```
Draft → Pending Approval → Approved → Ready → Closed
              ↓
           Rejected → (back to Draft for rework)
```

| State | Meaning | Why it exists |
| --- | --- | --- |
| Draft | Sales Officer is assembling the request | Editable workspace; nothing is promised yet |
| Pending Approval | Formally handed to Operations | Freezes content; the thing the manager reviews is the thing that was submitted |
| Approved | Operations Manager accepted terms | The auditable decision point — who/when/why |
| Rejected | Operations Manager declined, reason mandatory | Terminal for that attempt; re-opens to Draft so rework is a *new visible cycle* in the audit log, not silent edits |
| Ready | Storage agreement prepared; client can sign | The brief's target ("ready for storage agreement") — separates the *decision* (Approved) from *operational fulfilment* (docs drawn up). An approved-but-not-ready backlog is a real operational queue worth reporting on |
| Closed | Agreement executed; case archived | Terminal; record becomes fully immutable |

## Roles & duties

| Action | Sales Officer | Operations Manager |
| --- | --- | --- |
| Create / edit Draft | ✅ | — |
| Submit for approval (Draft → Pending) | ✅ | — |
| Approve / Reject | — | ✅ (never own records) |
| Mark Ready, Close | — | ✅ |
| Reopen Rejected → Draft | ✅ | — |

Separation of duties: the approver must not be the record's creator **or** its
`requested_by` — checked in Python at transition time, independent of workflow config.

## Server-side rules (all enforced in Python, phase 4)

1. Transition whitelist: any state change not in the map above is rejected, regardless of
   how the write arrives (UI, REST, RPC).
2. Role check per transition (in addition to Workflow's own gating).
3. Separation of duties on Approve/Reject.
4. Cannot submit for approval or approve with zero line items.
5. No negative qty/rate/amounts; discount cannot exceed line or total amount.
6. Content freeze: from Pending Approval onward, all fields except the workflow state are
   immutable; Closed/Rejected records accept no edits at all.
7. Rejection requires a reason (it becomes the audit-log entry's reason).
8. Every transition writes exactly one Onboarding Audit Log row.

Frappe Workflow (fixture) drives the UI buttons and state field; the Python layer is the
actual enforcement. Workflow alone cannot stop a direct `frappe.client.set_value` /
REST PUT against `workflow_state` — that is why both layers exist.

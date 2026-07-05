# Copyright (c) 2026, Salamun Fajri and contributors
# For license information, please see license.txt

"""Public REST surface for ERPNext Onboarding.

One whitelisted endpoint returns an onboarding request's current state and its
full, ordered audit history. Security properties (each verified in
docs/../phase8_test.py):

  * @frappe.whitelist() with no allow_guest — an unauthenticated caller is
    rejected by the framework before this code runs.
  * Document-level permission check: frappe.has_permission(..., doc=name)
    on the specific record, not just the doctype. A user who cannot read
    *this* request gets 403 (frappe.PermissionError), even if they can read
    the doctype in general.
  * No cross-permission leak: the audit history is only reachable through a
    request the caller is already allowed to read, so it cannot expose the
    trail of a record they cannot see.
  * Read-only: the endpoint never mutates state.
"""

import frappe
from frappe import _


@frappe.whitelist()
def get_request_status(name: str) -> dict:
	"""Return the current state and audit history of one Onboarding Request.

	Args:
		name: Onboarding Request id, e.g. "ONB-2026-00001".

	Returns:
		dict with the request's identity, current workflow state, decision
		fields, computed totals, and a chronological audit_history list.

	Raises:
		frappe.PermissionError (HTTP 403): caller lacks read on this record.
		frappe.DoesNotExistError (HTTP 404): no such request.
	"""
	if not name:
		frappe.throw(_("Request name is required"), frappe.ValidationError)

	# 404 before 403 would leak existence; Frappe's has_permission on a missing
	# doc raises DoesNotExistError, so check existence explicitly first only to
	# return a clean 404 for ids the caller could otherwise read.
	if not frappe.db.exists("Onboarding Request", name):
		frappe.throw(_("Onboarding Request {0} not found").format(name), frappe.DoesNotExistError)

	# Document-level permission check — the crux of the endpoint's security.
	if not frappe.has_permission("Onboarding Request", ptype="read", doc=name):
		raise frappe.PermissionError(
			_("Not permitted to read Onboarding Request {0}").format(name)
		)

	req = frappe.get_doc("Onboarding Request", name)

	return {
		"name": req.name,
		"customer": req.customer,
		"customer_name": req.customer_name,
		"state": req.workflow_state,
		"requested_by": req.requested_by,
		"request_date": str(req.request_date) if req.request_date else None,
		"approved_by": req.approved_by,
		"decided_on": str(req.decided_on) if req.decided_on else None,
		"decision_reason": req.decision_reason,
		"total_amount": req.total_amount,
		"discount_amount": req.discount_amount,
		"final_amount": req.final_amount,
		"audit_history": _audit_history(req.name),
	}


def _audit_history(request: str) -> list[dict]:
	"""Chronological transition log for a request.

	Reached only after the caller passed the read check on `request`, so the
	trail is never returned for a record the caller cannot see.
	"""
	return frappe.get_all(
		"Onboarding Audit Log",
		filters={"request": request},
		fields=["from_state", "to_state", "action", "actor", "reason", "timestamp"],
		order_by="timestamp asc",
	)

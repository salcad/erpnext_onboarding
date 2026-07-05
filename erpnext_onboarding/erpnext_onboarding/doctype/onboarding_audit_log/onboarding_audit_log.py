# Copyright (c) 2026, Salamun Fajri and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class OnboardingAuditLog(Document):
	"""Append-only record of one Onboarding Request state transition.

	A separate DocType (not a child table) so history cannot be rewritten
	through the parent form: child rows are editable whenever the parent is,
	whereas this DocType has its own controller that refuses every mutation
	after creation.

	Immutability is enforced in three layers:
	  1. DocPerms grant read/report only — no role has create/write/delete,
	     so nothing reaches these records through the normal permission path.
	  2. Rows are written by the request controller via `log_transition`,
	     which passes ignore_permissions=True *for the insert only* — this is
	     the single, auditable place allowed to append.
	  3. The guards below block update / rename / delete even when a caller
	     holds ignore_permissions or is System Manager. `read_only` +
	     `in_create` in the JSON stop the UI; these stop the API.

	Honest limits (see README): this is application-level immutability. A
	database administrator with direct SQL access, or code running as root
	that deletes the whole doctype, is outside what any app can prevent.
	"""

	def on_update(self):
		# Fires on both insert and save. Allow the initial insert only.
		if not self.flags.in_insert:
			frappe.throw(
				_("Audit log entries are append-only and cannot be modified"),
				frappe.PermissionError,
			)

	def on_trash(self):
		frappe.throw(
			_("Audit log entries are append-only and cannot be deleted"),
			frappe.PermissionError,
		)

	def after_rename(self, *args, **kwargs):
		frappe.throw(
			_("Audit log entries cannot be renamed"),
			frappe.PermissionError,
		)


def log_transition(request, from_state, to_state, action=None, reason=None):
	"""Append one immutable audit row for a request transition.

	Called from the Onboarding Request controller after a state change is
	validated. ignore_permissions=True is scoped to this insert so that a
	Sales Officer (who has no write permission on the audit doctype) still
	produces a log entry when they submit or reopen a request.
	"""
	frappe.get_doc(
		{
			"doctype": "Onboarding Audit Log",
			"request": request.name,
			"customer": request.customer,
			"action": action,
			"from_state": from_state,
			"to_state": to_state,
			"actor": frappe.session.user,
			"timestamp": frappe.utils.now_datetime(),
			"reason": reason,
		}
	).insert(ignore_permissions=True)

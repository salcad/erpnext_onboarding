# Copyright (c) 2026, Salamun Fajri and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model import no_value_fields, table_fields
from frappe.model.document import Document
from frappe.utils import cstr, flt, now_datetime

STATE_DRAFT = "Draft"
STATE_PENDING = "Pending Approval"
STATE_APPROVED = "Approved"
STATE_REJECTED = "Rejected"
STATE_READY = "Ready"
STATE_CLOSED = "Closed"

# The only legal state changes, with the rules each one carries.
# Anything not in this map is rejected server-side, no matter how the write
# arrives (UI form save, workflow action, REST PUT, RPC set_value).
TRANSITIONS = {
	(STATE_DRAFT, STATE_PENDING): frappe._dict(
		roles={"Sales Officer"},
		require_items=True,
	),
	(STATE_PENDING, STATE_APPROVED): frappe._dict(
		roles={"Operations Manager"},
		separation_of_duties=True,
		require_items=True,
		record_decision=True,
	),
	(STATE_PENDING, STATE_REJECTED): frappe._dict(
		roles={"Operations Manager"},
		separation_of_duties=True,
		require_reason=True,
		record_decision=True,
	),
	(STATE_APPROVED, STATE_READY): frappe._dict(roles={"Operations Manager"}),
	(STATE_READY, STATE_CLOSED): frappe._dict(roles={"Operations Manager"}),
	(STATE_REJECTED, STATE_DRAFT): frappe._dict(
		roles={"Sales Officer"},
		clear_decision=True,
	),
}

# From Pending Approval onward the content of the request is frozen: the
# reviewed document must be the submitted document.
FROZEN_STATES = {STATE_PENDING, STATE_APPROVED, STATE_REJECTED, STATE_READY, STATE_CLOSED}

# Fields the transition machinery itself is allowed to touch while frozen.
TRANSITION_FIELDS = {"workflow_state", "approved_by", "decided_on", "decision_reason"}

# The reviewer types the rejection reason before triggering the Reject action,
# which saves the form first — so this one field stays writable in Pending.
EDITABLE_WHILE_PENDING = {"decision_reason"}


class OnboardingRequest(Document):
	"""A client's journey from "interested" to "ready for storage agreement".

	Links to the standard Customer (required) and optionally to the Lead /
	Opportunity it originated from. Line items live in the Onboarding Request
	Item child table.

	The Frappe Workflow "Onboarding Request Approval" (shipped as a fixture)
	drives the UI buttons; every rule is enforced again here in Python because
	the workflow layer cannot stop a direct API write to workflow_state.
	See docs/design.md for the full rule list this controller implements.
	"""

	def before_insert(self):
		# Provenance is never taken from user input.
		self.requested_by = frappe.session.user

	def validate(self):
		self.validate_line_values()
		self.calculate_totals()
		self.enforce_state_machine()

	def on_trash(self):
		if self.workflow_state != STATE_DRAFT:
			frappe.throw(
				_("Only Draft requests can be deleted. {0} is {1}.").format(
					self.name, _(self.workflow_state)
				),
				frappe.PermissionError,
			)

	# ------------------------------------------------------------------ #
	# money                                                               #
	# ------------------------------------------------------------------ #

	def validate_line_values(self):
		"""Business-rule validation of line values (design rule 5).

		The schema already sets non_negative on qty/rate; these checks repeat
		the rule in Python so it holds even if the schema is altered later.
		"""
		for row in self.items:
			if flt(row.qty) <= 0:
				frappe.throw(_("Row {0}: quantity must be greater than zero").format(row.idx))
			if flt(row.rate) < 0:
				frappe.throw(_("Row {0}: rate cannot be negative").format(row.idx))
			if not 0 <= flt(row.discount_percent) <= 100:
				frappe.throw(_("Row {0}: discount must be between 0 and 100 percent").format(row.idx))

	def calculate_totals(self):
		"""Recompute line amounts and document totals from qty/rate/discount.

		Runs on every save, so values sent by a client (UI or direct API call)
		can never override the computed amounts.
		"""
		total = 0.0
		discount = 0.0

		for row in self.items:
			gross = flt(row.qty) * flt(row.rate)
			row_discount = gross * flt(row.discount_percent) / 100.0
			row.amount = flt(gross - row_discount, 2)
			total += gross
			discount += row_discount

		self.total_amount = flt(total, 2)
		self.discount_amount = flt(discount, 2)
		self.final_amount = flt(total - discount, 2)

	# ------------------------------------------------------------------ #
	# state machine                                                       #
	# ------------------------------------------------------------------ #

	def enforce_state_machine(self):
		old = self.get_doc_before_save()

		if self.is_new() or not old:
			# Design rule 1: every request starts life in Draft. An insert
			# arriving with any other state is an attempt to skip the flow.
			if not self.workflow_state:
				self.workflow_state = STATE_DRAFT
			if self.workflow_state != STATE_DRAFT:
				frappe.throw(_("New requests must be created in Draft state"))
			return

		old_state = old.workflow_state
		new_state = self.workflow_state

		if old_state == new_state:
			if old_state in FROZEN_STATES:
				allowed = EDITABLE_WHILE_PENDING if old_state == STATE_PENDING else set()
				self.assert_content_unchanged(old, allowed)
			return

		self.validate_transition(old, old_state, new_state)

	def validate_transition(self, old, old_state, new_state):
		rule = TRANSITIONS.get((old_state, new_state))

		# Design rule 1: whitelist. Unknown pairs (including any transition
		# out of Closed) are invalid by construction.
		if not rule:
			frappe.throw(
				_("Invalid workflow transition: {0} → {1}").format(_(old_state), _(new_state))
			)

		user = frappe.session.user

		# Design rule 2: the acting user must hold the business role for this
		# transition — checked here, independent of the Workflow config.
		if not rule.roles & set(frappe.get_roles(user)):
			frappe.throw(
				_("Only {0} can perform {1} → {2}").format(
					_(" / ").join(sorted(rule.roles)), _(old_state), _(new_state)
				),
				frappe.PermissionError,
			)

		# Design rule 3: separation of duties. The creator (session user at
		# insert) and the record owner must not decide on their own request.
		if rule.get("separation_of_duties") and user in (self.owner, self.requested_by):
			frappe.throw(
				_("Separation of duties: {0} created this request and cannot approve or reject it").format(
					user
				),
				frappe.PermissionError,
			)

		# Design rule 4: no approval (or submission) without line items.
		if rule.get("require_items") and not self.items:
			frappe.throw(_("Cannot move to {0}: the request has no line items").format(_(new_state)))

		# Design rule 7: a rejection must say why.
		if rule.get("require_reason") and not cstr(self.decision_reason).strip():
			frappe.throw(_("A decision reason is mandatory when rejecting a request"))

		# Design rule 6: while frozen, a transition may change nothing except
		# the state and the decision fields the server writes below.
		if old_state in FROZEN_STATES:
			self.assert_content_unchanged(old, TRANSITION_FIELDS)

		if rule.get("record_decision"):
			# Who decided and when is recorded server-side, never from input.
			self.approved_by = user
			self.decided_on = now_datetime()

		if rule.get("clear_decision"):
			# Reopening starts a new, clean review cycle; the previous
			# decision remains visible in the audit log, not on the document.
			self.approved_by = None
			self.decided_on = None
			self.decision_reason = None

	# ------------------------------------------------------------------ #
	# immutability                                                        #
	# ------------------------------------------------------------------ #

	def assert_content_unchanged(self, old, allowed_fields):
		"""Throw if any field outside allowed_fields differs from the saved doc.

		Implements design rule 6 (content freeze). Values are normalised per
		fieldtype so recomputed-but-equal floats or date objects vs strings do
		not raise false positives.
		"""
		for df in self.meta.fields:
			if df.fieldname in allowed_fields:
				continue

			if df.fieldtype in table_fields:
				if self._table_signature(df.fieldname) != self._table_signature(df.fieldname, old):
					self._throw_frozen(df, old)
				continue

			if df.fieldtype in no_value_fields:
				continue

			if self._normalize(df, self.get(df.fieldname)) != self._normalize(df, old.get(df.fieldname)):
				self._throw_frozen(df, old)

	def _throw_frozen(self, df, old):
		frappe.throw(
			_("{0} cannot be changed: request {1} is {2} and its content is frozen").format(
				_(df.label or df.fieldname), self.name, _(old.workflow_state)
			)
		)

	def _table_signature(self, fieldname, doc=None):
		rows = (doc or self).get(fieldname) or []
		return [
			(cstr(r.item), flt(r.qty, 6), flt(r.rate, 6), flt(r.discount_percent, 6))
			for r in rows
		]

	@staticmethod
	def _normalize(df, value):
		if df.fieldtype in ("Currency", "Float", "Percent"):
			return flt(value, 6)
		if df.fieldtype in ("Int", "Check"):
			return flt(value)
		return cstr(value)

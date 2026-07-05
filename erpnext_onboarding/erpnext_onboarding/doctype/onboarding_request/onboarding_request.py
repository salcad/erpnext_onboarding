# Copyright (c) 2026, Salamun Fajri and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class OnboardingRequest(Document):
	"""A client's journey from "interested" to "ready for storage agreement".

	Links to the standard Customer (required) and optionally to the Lead /
	Opportunity it originated from. Line items live in the Onboarding Request
	Item child table. All money fields are computed server-side in validate()
	and are read-only in the UI — client-supplied values are always overwritten.
	"""

	def before_insert(self):
		# Provenance is never taken from user input.
		self.requested_by = frappe.session.user

	def validate(self):
		self.calculate_totals()

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

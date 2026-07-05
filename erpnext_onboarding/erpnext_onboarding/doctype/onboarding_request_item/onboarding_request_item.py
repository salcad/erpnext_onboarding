# Copyright (c) 2026, Salamun Fajri and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class OnboardingRequestItem(Document):
	"""Line item of an Onboarding Request.

	Child table by design: rows have no identity or lifecycle of their own and
	are never referenced independently of their parent request. All amount
	calculations happen in the parent controller so totals and line amounts
	are always computed together, server-side.
	"""

	pass

# Copyright (c) 2026, Salamun Fajri and contributors
# For license information, please see license.txt

"""Pending Approvals by Age.

Operational queue: which onboarding requests are waiting for an Operations
Manager decision, and how long each has been waiting.

Permission model: the report reads requests through frappe.get_list(), which
applies the caller's DocPerms — so a user who cannot read Onboarding Request
sees no rows. It deliberately does NOT use raw frappe.db.sql, which would
bypass permissions. "Waiting since" comes from the audit log entry that moved
the request into Pending Approval, so the age reflects the actual review wait,
not the original request date.
"""

import frappe
from frappe import _
from frappe.utils import date_diff, format_datetime, nowdate

PENDING = "Pending Approval"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = get_columns()
	data = get_data(filters)
	chart = get_chart(data)
	return columns, data, None, chart


def get_columns():
	return [
		{
			"label": _("Request"),
			"fieldname": "name",
			"fieldtype": "Link",
			"options": "Onboarding Request",
			"width": 160,
		},
		{
			# Data, not Link: a Link column would make the report engine require
			# the running user to hold read permission on Customer as well, which
			# couples this report to Customer DocPerms. We only want it to respect
			# Onboarding Request permissions (its ref_doctype), so we show the
			# already-fetched customer_name as text instead.
			"label": _("Customer"),
			"fieldname": "customer_name",
			"fieldtype": "Data",
			"width": 200,
		},
		{
			"label": _("Requested By"),
			"fieldname": "requested_by",
			"fieldtype": "Data",
			"width": 180,
		},
		{
			"label": _("Waiting Since"),
			"fieldname": "waiting_since",
			"fieldtype": "Datetime",
			"width": 160,
		},
		{
			"label": _("Days Pending"),
			"fieldname": "days_pending",
			"fieldtype": "Int",
			"width": 110,
		},
		{
			"label": _("Final Amount"),
			"fieldname": "final_amount",
			"fieldtype": "Currency",
			"width": 130,
		},
		{
			"label": _("Ageing"),
			"fieldname": "ageing_bucket",
			"fieldtype": "Data",
			"width": 110,
		},
	]


def get_data(filters):
	list_filters = {"workflow_state": PENDING}
	if filters.get("customer"):
		list_filters["customer"] = filters.customer

	# get_list applies the caller's permissions — the core of "respects perms".
	requests = frappe.get_list(
		"Onboarding Request",
		filters=list_filters,
		fields=["name", "customer", "customer_name", "requested_by", "final_amount"],
	)

	min_days = frappe.utils.cint(filters.get("min_days_pending"))
	rows = []
	for req in requests:
		waiting_since = _pending_since(req.name)
		days = date_diff(nowdate(), waiting_since) if waiting_since else 0
		if days < min_days:
			continue
		req.waiting_since = waiting_since
		req.days_pending = days
		req.ageing_bucket = _bucket(days)
		rows.append(req)

	rows.sort(key=lambda r: r.days_pending, reverse=True)
	return rows


def _pending_since(request):
	"""Timestamp of the most recent transition into Pending Approval.

	Uses the audit trail so 'age' means time actually spent awaiting a
	decision, correctly resetting when a rejected request is reopened and
	resubmitted. Falls back to None if no such entry exists.
	"""
	entry = frappe.get_all(
		"Onboarding Audit Log",
		filters={"request": request, "to_state": PENDING},
		fields=["timestamp"],
		order_by="timestamp desc",
		limit=1,
	)
	return entry[0].timestamp if entry else None


def _bucket(days):
	if days <= 2:
		return _("0-2 days")
	if days <= 5:
		return _("3-5 days")
	if days <= 10:
		return _("6-10 days")
	return _("10+ days")


def get_chart(rows):
	buckets = ["0-2 days", "3-5 days", "6-10 days", "10+ days"]
	counts = {b: 0 for b in buckets}
	for r in rows:
		counts[r.ageing_bucket] = counts.get(r.ageing_bucket, 0) + 1
	return {
		"data": {
			"labels": [_(b) for b in buckets],
			"datasets": [{"name": _("Requests"), "values": [counts[b] for b in buckets]}],
		},
		"type": "bar",
	}

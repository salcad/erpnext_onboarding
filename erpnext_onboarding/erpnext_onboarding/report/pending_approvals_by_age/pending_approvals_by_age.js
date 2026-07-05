// Copyright (c) 2026, Salamun Fajri and contributors
// For license information, please see license.txt

frappe.query_reports["Pending Approvals by Age"] = {
	filters: [
		{
			fieldname: "customer",
			label: __("Customer"),
			fieldtype: "Link",
			options: "Customer",
		},
		{
			fieldname: "min_days_pending",
			label: __("Min Days Pending"),
			fieldtype: "Int",
			default: 0,
		},
	],
	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		// Redden requests that have been waiting the longest.
		if (column.fieldname === "days_pending" && data && data.days_pending > 5) {
			value = `<span style="color:var(--red-600,#c0392b);font-weight:600">${value}</span>`;
		}
		return value;
	},
};

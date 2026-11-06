"""Targets, budget versions and lender schedules (spec 5.3 C05/C15 and 5.4)."""
import base64
import io
import re
from collections import defaultdict
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .gh_mapping import ACCOUNT_ROLES, PAYMENT_CATEGORIES

# metric code -> (label, allowed dimension prefix or None, direction)
TARGET_METRICS = {
    "PL": ("P&L line budget (UGX)", "role", "up"),
    "C05": ("Cash collections target by category (UGX)", "category", "up"),
    "B07": ("Active portfolio at period end (contracts)", None, "up"),
    "B08": ("New riders onboarded, first-time (count)", None, "up"),
    "B09": ("Fleet deployed at period end, by product group (vehicles)", "group", "up"),
    "B10": ("Default loss (UGX)", None, "down"),
    "B11": ("Financing costs (UGX)", None, "down"),
}


class GhKpiTargetVersion(models.Model):
    _name = "gh.kpi.target.version"
    _description = "Green Hub budget / target version"
    _order = "effective_from desc, kind, id"

    name = fields.Char(required=True)
    kind = fields.Selection([("original", "Original"), ("revised", "Revised"), ("forecast", "Forecast")],
                            required=True, default="original")
    state = fields.Selection([("draft", "Working"), ("approved", "Approved")], default="draft", required=True, readonly=True)
    approved_by = fields.Many2one("res.users", readonly=True)
    approved_on = fields.Datetime(readonly=True)
    effective_from = fields.Date(required=True, default=lambda self: date(fields.Date.today().year, 1, 1))
    effective_to = fields.Date(required=True, default=lambda self: date(fields.Date.today().year, 12, 31))
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, required=True)
    line_ids = fields.One2many("gh.kpi.target", "version_id")
    line_count = fields.Integer(compute="_compute_line_count")

    def _compute_line_count(self):
        for version in self:
            version.line_count = len(version.line_ids)

    def write(self, vals):
        if any(v.state == "approved" for v in self) and set(vals) - {"name"}:
            raise UserError(_("An approved version is locked. Create a revised version instead."))
        return super().write(vals)

    def unlink(self):
        if any(v.state == "approved" for v in self):
            raise UserError(_("An approved version can't be deleted."))
        return super().unlink()

    def action_approve(self):
        if not self.env.user.has_group("greenhub_dashboards.group_gh_dashboard_manager"):
            raise UserError(_("Only a Dashboard Manager can approve a version."))
        for version in self.filtered(lambda v: v.state == "draft"):
            super(GhKpiTargetVersion, version).write({
                "state": "approved", "approved_by": self.env.user.id, "approved_on": fields.Datetime.now()})

    def action_new_revision(self):
        self.ensure_one()
        copy = self.copy({"name": _("%s (revision)", self.name), "kind": "revised", "line_ids": False})
        self.line_ids.copy({"version_id": copy.id})
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": copy.id, "view_mode": "form"}


class GhKpiTarget(models.Model):
    _name = "gh.kpi.target"
    _description = "Green Hub KPI target"
    _order = "period_start, metric_code, dim_key"

    version_id = fields.Many2one("gh.kpi.target.version", required=True, ondelete="cascade", index=True)
    metric_code = fields.Selection([(k, f"{k} · {v[0]}") for k, v in TARGET_METRICS.items()], required=True)
    period_type = fields.Selection([("month", "Month"), ("week", "Week")], default="month", required=True)
    period_start = fields.Date(required=True)
    dim_key = fields.Char(default="")
    value = fields.Float(required=True)

    _target_uniq = models.Constraint(
        "unique(version_id, metric_code, period_type, period_start, dim_key)",
        "Only one target per version, metric, period and dimension.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        versions = self.env["gh.kpi.target.version"].browse([v["version_id"] for v in vals_list])
        if any(v.state == "approved" for v in versions):
            raise UserError(_("An approved version is locked."))
        return super().create(vals_list)

    def write(self, vals):
        if any(t.version_id.state == "approved" for t in self):
            raise UserError(_("An approved version is locked."))
        return super().write(vals)

    @api.model
    def _value(self, version, metric, date_from, date_to, dim_key=""):
        """Sum of monthly targets overlapping [date_from, date_to], pro-rated by days.

        Weekly budget rule (shown on the page): a monthly target is spread evenly over
        the days of its month, so any period gets the days it covers.
        """
        if not version:
            return None
        targets = self.sudo().search([("version_id", "=", version.id), ("metric_code", "=", metric),
                                      ("dim_key", "=", dim_key or ""), ("period_type", "=", "month"),
                                      ("period_start", "<=", date_to),
                                      ("period_start", ">=", date_from.replace(day=1))])
        if not targets:
            return None
        total = 0.0
        for t in targets:
            m_start = t.period_start
            m_end = m_start + relativedelta(months=1, days=-1)
            overlap = (min(m_end, date_to) - max(m_start, date_from)).days + 1
            if overlap > 0:
                total += t.value * overlap / ((m_end - m_start).days + 1)
        return total

    @api.model
    def _point_value(self, version, metric, on, dim_key=""):
        """End-date metrics (portfolio counts): the target of the month containing `on`, never summed."""
        if not version:
            return None
        t = self.sudo().search([("version_id", "=", version.id), ("metric_code", "=", metric),
                                ("dim_key", "=", dim_key or ""), ("period_start", "=", on.replace(day=1))], limit=1)
        return t.value if t else None


class GhTargetImportWizard(models.TransientModel):
    """XLSX import with validation. Columns: metric_code, period (YYYY-MM), dimension, value."""

    _name = "gh.target.import.wizard"
    _description = "Import Green Hub targets"

    version_id = fields.Many2one("gh.kpi.target.version", required=True, domain=[("state", "=", "draft")])
    file = fields.Binary(required=True, attachment=False)
    filename = fields.Char()
    report = fields.Text(readonly=True)
    template = fields.Binary(readonly=True, attachment=False)
    template_name = fields.Char(default="greenhub_targets_template.xlsx")

    @api.model
    def _valid_dims(self):
        groups = {g.name.lower(): g.id for g in self.env["gh.product.group"].sudo().search([])}
        return {
            "role": {k for k, _l in ACCOUNT_ROLES},
            "category": {k for k, _l in PAYMENT_CATEGORIES},
            "group": groups,
        }

    def _parse(self, content):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            raise ValidationError(_("The file is empty."))
        header = [str(h or "").strip().lower() for h in rows[0]]
        needed = ["metric_code", "period", "dimension", "value"]
        if header[:4] != needed:
            raise ValidationError(_("The first row must be: %s", ", ".join(needed)))
        dims = self._valid_dims()
        errors, warnings, out, seen = [], [], [], set()
        for n, row in enumerate(rows[1:], start=2):
            if not any(row):
                continue
            code, period, dim, value = (list(row) + [None] * 4)[:4]
            code = str(code or "").strip().upper()
            if code not in TARGET_METRICS:
                errors.append(_("Row %(n)s: unknown metric code '%(c)s'", n=n, c=code))
                continue
            if isinstance(period, date):
                start = period.replace(day=1) if not hasattr(period, "date") else period.date().replace(day=1)
            elif re.fullmatch(r"\d{4}-\d{2}", str(period or "").strip()):
                y, m = str(period).strip().split("-")
                start = date(int(y), int(m), 1)
            else:
                errors.append(_("Row %(n)s: period must look like 2026-01", n=n))
                continue
            prefix = TARGET_METRICS[code][1]
            dim = str(dim or "").strip()
            dim_key = ""
            if prefix:
                if prefix == "group":
                    gid = dims["group"].get(dim.lower())
                    if not gid:
                        errors.append(_("Row %(n)s: unknown product group '%(d)s'", n=n, d=dim))
                        continue
                    dim_key = f"group:{gid}"
                elif dim not in dims[prefix]:
                    errors.append(_("Row %(n)s: '%(d)s' is not a valid %(p)s", n=n, d=dim, p=prefix))
                    continue
                else:
                    dim_key = f"{prefix}:{dim}"
            try:
                value = float(value)
            except (TypeError, ValueError):
                errors.append(_("Row %(n)s: value must be a number", n=n))
                continue
            key = (code, start, dim_key)
            if key in seen:
                errors.append(_("Row %(n)s: duplicate of an earlier row (%(c)s %(p)s %(d)s)", n=n, c=code, p=start, d=dim))
                continue
            seen.add(key)
            out.append({"metric_code": code, "period_start": start, "dim_key": dim_key, "value": value})
        by_metric = defaultdict(set)
        for line in out:
            by_metric[(line["metric_code"], line["dim_key"])].add(line["period_start"])
        version = self.version_id
        months = []
        d = version.effective_from.replace(day=1)
        while d <= version.effective_to:
            months.append(d)
            d += relativedelta(months=1)
        for (code, dim_key), present in by_metric.items():
            missing = [m.strftime("%Y-%m") for m in months if m not in present]
            if missing:
                warnings.append(_("%(c)s %(d)s: no value for %(m)s", c=code, d=dim_key or "", m=", ".join(missing)))
        return out, errors, warnings

    def action_import(self):
        self.ensure_one()
        if self.version_id.state != "draft":
            raise UserError(_("Import into a working (draft) version."))
        lines, errors, warnings = self._parse(base64.b64decode(self.file))
        if errors:
            self.report = _("Nothing imported. Fix these rows:\n") + "\n".join(errors)
        else:
            Target = self.env["gh.kpi.target"]
            existing = Target.search([("version_id", "=", self.version_id.id)])
            existing.unlink()
            Target.create([dict(line, version_id=self.version_id.id) for line in lines])
            self.report = _("Imported %s rows.", len(lines)) + ("\n" + _("Warnings:\n") + "\n".join(warnings) if warnings else "")
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
                "view_mode": "form", "target": "new"}

    def action_template(self):
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "targets"
        ws.append(["metric_code", "period", "dimension", "value"])
        year = fields.Date.today().year
        group = self.env["gh.product.group"].sudo().search([], limit=1)
        ws.append(["C05", f"{year}-01", "lease", 0])
        ws.append(["PL", f"{year}-01", "revenue_lease", 0])
        ws.append(["B07", f"{year}-01", "", 0])
        ws.append(["B09", f"{year}-01", group.name or "Zembo", 0])
        help_ws = wb.create_sheet("codes")
        help_ws.append(["metric_code", "meaning", "dimension"])
        for code, (label, prefix, _d) in TARGET_METRICS.items():
            help_ws.append([code, label, prefix or ""])
        help_ws.append([])
        help_ws.append(["role values", ", ".join(k for k, _l in ACCOUNT_ROLES)])
        help_ws.append(["category values", ", ".join(k for k, _l in PAYMENT_CATEGORIES)])
        help_ws.append(["group values", ", ".join(self.env["gh.product.group"].sudo().search([]).mapped("name"))])
        buf = io.BytesIO()
        wb.save(buf)
        self.template = base64.b64encode(buf.getvalue())
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
                "view_mode": "form", "target": "new"}


class GhFinancingFacility(models.Model):
    _name = "gh.financing.facility"
    _description = "Green Hub lender facility"

    name = fields.Char(required=True)
    lender_id = fields.Many2one("res.partner", required=True)
    currency_id = fields.Many2one("res.currency", required=True, default=lambda self: self.env.company.currency_id)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, required=True)
    schedule_ids = fields.One2many("gh.financing.schedule", "facility_id")


class GhFinancingSchedule(models.Model):
    _name = "gh.financing.schedule"
    _description = "Green Hub lender repayment line"
    _order = "due_date"

    facility_id = fields.Many2one("gh.financing.facility", required=True, ondelete="cascade")
    currency_id = fields.Many2one(related="facility_id.currency_id")
    due_date = fields.Date(required=True)
    principal = fields.Monetary()
    interest = fields.Monetary()
    fees = fields.Monetary()
    paid_date = fields.Date()
    paid_amount = fields.Monetary()

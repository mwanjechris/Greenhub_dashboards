"""Contract-level definitions shared by every dashboard, live and historical.

Live values come from the greenhub module's stored fields (total_outstanding,
installment_balance, unreconciled_payment, payment_state). Past values are
reconstructed, with these documented assumptions (shown on the dashboards):

1. Contract state and payment state at a date = the last tracked change on or
   before that date (chatter tracking); before the first change, the first
   change's old value; with no changes at all, today's value.
2. Arrears at a past date = instalments due before that date that are still
   unpaid today, plus instalments paid since then whose payment can't be
   dated. Green Hub's receipts are not linked to instalments, so an instalment
   that is paid today is treated as paid on time. This understates past arrears
   for riders who paid late; late fees and credit are not reconstructed.
3. Vehicle categories at a past date use the tracked vehicle state and today's
   tags (tags are not tracked).
"""
import base64
import csv
import io
import logging
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .gh_mapping import INSTALMENT_CATEGORIES

_logger = logging.getLogger(__name__)

ACTIVE_STATES = ("running", "pause")
OPEN_SCHEDULE_STATES = ("unpaid", "partial", "overdue")
WRITTEN_OFF_STATES = ("written_off", "partially_written_off")
RISK_ORDER = ["ahead", "ontrack", "norisk", "low", "atrisk", "high", "critical", "default"]
PAR_ORDER = ["par0", "par7", "par14", "par21", "par28"]


def week_ends(date_from, date_to):
    """Sundays in [date_from, date_to]."""
    d = date_from + timedelta(days=(6 - date_from.weekday()))
    while d <= date_to:
        yield d
        d += timedelta(days=7)


def month_ends(date_from, date_to):
    d = (date_from.replace(day=1) + relativedelta(months=1)) - timedelta(days=1)
    while d <= date_to:
        yield d
        d = (d + timedelta(days=1) + relativedelta(months=1)) - timedelta(days=1)


def period_start(period_type, end):
    return end - timedelta(days=6) if period_type == "week" else end.replace(day=1)


class GhHistoryService(models.AbstractModel):
    _name = "gh.history.service"
    _description = "Green Hub history and contract metrics"

    # ------------------------------------------------------------ classification
    def _config(self):
        return self.env["gh.dashboard.config"]._get_config()

    def _instalment(self, contract, group_refs):
        amount = contract.total_rental_amount if contract.type == "rental" else contract.actual_weekly_payment
        if not amount:
            amount = group_refs.get(contract.id) or 0.0
        return amount or 0.0

    def _risk_category(self, payment_state, arrears, instalment, in_default, config):
        if in_default:
            return "default"
        if payment_state == "ahead":
            return "ahead"
        if arrears <= 0.005 or payment_state == "ontrack":
            return "ontrack"
        limits = config._band_limits()
        measure = arrears if config.risk_band_basis == "ugx" else (arrears / instalment if instalment else float("inf"))
        for limit, category in zip(limits, ["ontrack", "norisk", "low", "atrisk", "high"]):
            if measure <= limit:
                return category
        return "critical"

    def _par_bucket(self, dpd, config):
        if dpd <= 0:
            return "par0"
        if dpd <= config.par_1:
            return "par7"
        if dpd <= config.par_2:
            return "par14"
        if dpd <= config.par_3:
            return "par21"
        return "par28"

    def _group_of(self, contracts):
        by_product, _by_model, _groups = self.env["gh.product.group"]._group_maps()
        return {c.id: by_product.get(c.product_product_id.id) for c in contracts}

    def _group_reference_instalments(self, contracts, groups_of):
        """Per contract: the group's standard instalment, else the group's median live instalment."""
        per_group = defaultdict(list)
        for c in contracts:
            amount = c.total_rental_amount if c.type == "rental" else c.actual_weekly_payment
            if amount and groups_of.get(c.id):
                per_group[groups_of[c.id].id].append(amount)
        medians = {gid: sorted(v)[len(v) // 2] for gid, v in per_group.items() if v}
        out = {}
        for c in contracts:
            group = groups_of.get(c.id)
            if group:
                out[c.id] = group.weekly_instalment_ref or medians.get(group.id, 0.0)
        return out

    def _group_standard_instalment(self):
        """Per product group: standard weekly due for an available bike."""
        contracts = self.env["rider.contract"].sudo().search([("state", "in", ACTIVE_STATES)])
        groups_of = self._group_of(contracts)
        refs = self._group_reference_instalments(contracts, groups_of)
        out = {}
        for group in self.env["gh.product.group"].sudo().search([]):
            if group.weekly_instalment_ref:
                out[group.id] = group.weekly_instalment_ref
            else:
                values = [refs[c.id] for c in contracts if groups_of.get(c.id) == group and refs.get(c.id)]
                out[group.id] = values[0] if values else 0.0
        return out

    def _defaulted_contract_ids(self, until=None):
        domain = [] if until is None else [("date", "<=", until)]
        return set(self.env["default.tracking"].sudo().search(domain).mapped("contract_id").ids)

    def _written_off_contract_ids(self):
        rows = self.env["payment.schedule"].sudo()._read_group(
            [("state", "in", WRITTEN_OFF_STATES)], ["contract_id"], ["__count"])
        return {contract.id for contract, _n in rows}

    def _in_default_ids(self, contracts_state, payment_states, config, until=None):
        """contracts_state / payment_states: {contract_id: value} at the date."""
        defaulted = self._defaulted_contract_ids(until)
        written_off = self._written_off_contract_ids()
        out = set()
        for cid, state in contracts_state.items():
            if state in ACTIVE_STATES and payment_states.get(cid) == "default":
                out.add(cid)
            elif config.default_scope == "episode" and state == "terminated" \
                    and cid in defaulted and cid not in written_off:
                out.add(cid)
        return out

    # ------------------------------------------------------------ period flows
    def _collected_by_contract(self, date_from, date_to, contract_ids=None):
        """Instalment receipts (lease + rental) per contract in [date_from, date_to]."""
        domain = [("status", "=", "success"), ("contract_id", "!=", False),
                  ("attempt_date", ">=", datetime.combine(date_from, time.min)),
                  ("attempt_date", "<=", datetime.combine(date_to, time.max))]
        if contract_ids is not None:
            domain.append(("contract_id", "in", list(contract_ids)))
        classify = self.env["gh.payment.category.rule"]._classifier()
        out = defaultdict(float)
        for log in self.env["payment.log"].sudo().search(domain):
            if classify(log) in INSTALMENT_CATEGORIES:
                out[log.contract_id.id] += log.amount
        return out

    def _due_by_contract(self, date_from, date_to, contract_ids=None):
        domain = [("due_date", ">=", date_from), ("due_date", "<=", date_to), ("state", "!=", "cancelled")]
        if contract_ids is not None:
            domain.append(("contract_id", "in", list(contract_ids)))
        out = defaultdict(float)
        for contract, amount in self.env["payment.schedule"].sudo()._read_group(domain, ["contract_id"], ["amount:sum"]):
            out[contract.id] += amount or 0.0
        return out

    # ------------------------------------------------------------ live rows
    def _live_contract_rows(self, on, period_type=None):
        config = self._config()
        Contract = self.env["rider.contract"].sudo()
        defaulted = self._defaulted_contract_ids()
        contracts = Contract.search(["|", ("state", "in", ACTIVE_STATES),
                                     "&", ("state", "=", "terminated"), ("id", "in", list(defaulted))])
        groups_of = self._group_of(contracts)
        refs = self._group_reference_instalments(contracts, groups_of)
        in_default = self._in_default_ids({c.id: c.state for c in contracts},
                                          {c.id: c.payment_state for c in contracts}, config)
        oldest = {}
        for contract, due in self.env["payment.schedule"].sudo()._read_group(
                [("contract_id", "in", contracts.ids), ("state", "in", OPEN_SCHEDULE_STATES), ("due_date", "<", on)],
                ["contract_id"], ["due_date:min"]):
            oldest[contract.id] = due
        start = period_start(period_type or "week", on)
        collected = self._collected_by_contract(start, on, contracts.ids)
        due = self._due_by_contract(start, on, contracts.ids)
        rows = []
        for c in contracts:
            arrears = c.total_outstanding or 0.0
            instalment = self._instalment(c, refs)
            dpd = (on - oldest[c.id]).days if c.id in oldest else 0
            is_default = c.id in in_default
            rows.append({
                "contract_id": c.id, "rider_id": c.rider_id.id, "bike_id": c.bike_id.id,
                "product_group_id": groups_of[c.id].id if groups_of.get(c.id) else False,
                "state": c.state, "payment_state": c.payment_state, "is_active": c.state in ACTIVE_STATES,
                "in_default": is_default, "arrears": arrears,
                "penalties": max((c.total_outstanding or 0.0) - (c.installment_balance or 0.0), 0.0),
                "credit": max(c.unreconciled_payment or 0.0, 0.0), "instalment": instalment, "dpd": dpd,
                "risk_category": self._risk_category(c.payment_state, arrears, instalment, is_default, config),
                "par_bucket": self._par_bucket(dpd, config),
                "due_in_period": due.get(c.id, 0.0), "collected_in_period": collected.get(c.id, 0.0),
            })
        return rows

    # ------------------------------------------------------------ reconstruction
    def _label_map(self, model, field):
        selection = self.env[model]._fields[field]._description_selection(self.env)
        return {label: key for key, label in selection} | {key: key for key, _label in selection}

    def _tracked_values_at(self, model, field, records, dates):
        """{(record_id, date): technical value} from chatter tracking (assumption 1)."""
        labels = self._label_map(model, field)
        field_rec = self.env["ir.model.fields"].sudo()._get(model, field)
        self.env.cr.execute("""
            SELECT m.res_id, m.date, v.old_value_char, v.new_value_char
              FROM mail_tracking_value v JOIN mail_message m ON m.id = v.mail_message_id
             WHERE m.model = %s AND m.res_id = ANY(%s) AND v.field_id = %s
             ORDER BY m.res_id, m.date, v.id
        """, (model, records.ids, field_rec.id))
        changes = defaultdict(list)
        for res_id, date, old, new in self.env.cr.fetchall():
            changes[res_id].append((date, labels.get(old, old), labels.get(new, new)))
        out = {}
        for record in records:
            current = record[field]
            history = changes.get(record.id, [])
            for d in dates:
                limit = datetime.combine(d, time.max)
                if record.create_date and record.create_date > limit:
                    out[(record.id, d)] = None
                    continue
                before = [h for h in history if h[0] <= limit]
                if before:
                    out[(record.id, d)] = before[-1][2]
                elif history:
                    out[(record.id, d)] = history[0][1]
                else:
                    out[(record.id, d)] = current
        return out

    def _reconstructed_contract_rows(self, period_type, ends):
        """{period_end: [row vals]} for past dates (assumptions 1 and 2)."""
        config = self._config()
        contracts = self.env["rider.contract"].sudo().with_context(active_test=False).search([])
        states = self._tracked_values_at("rider.contract", "state", contracts, ends)
        pstates = self._tracked_values_at("rider.contract", "payment_state", contracts, ends)
        groups_of = self._group_of(contracts)
        refs = self._group_reference_instalments(contracts, groups_of)
        schedules = self.env["payment.schedule"].sudo().search_read(
            [("contract_id", "in", contracts.ids), ("state", "!=", "cancelled")],
            ["contract_id", "due_date", "amount", "balance", "state"])
        by_contract = defaultdict(list)
        for s in schedules:
            by_contract[s["contract_id"][0]].append(s)
        out = {}
        for end in ends:
            start = period_start(period_type, end)
            state_at = {c.id: states[(c.id, end)] for c in contracts if states[(c.id, end)]}
            pstate_at = {cid: pstates[(cid, end)] for cid in state_at}
            in_default = self._in_default_ids(state_at, pstate_at, config, until=end)
            keep = [cid for cid, st in state_at.items() if st in ACTIVE_STATES or cid in in_default]
            collected = self._collected_by_contract(start, end, keep)
            due = self._due_by_contract(start, end, keep)
            rows = []
            for cid in keep:
                contract = contracts.browse(cid)
                open_lines = [s for s in by_contract[cid] if s["due_date"] and s["due_date"] < end
                              and s["state"] in OPEN_SCHEDULE_STATES + WRITTEN_OFF_STATES]
                arrears = sum((s["balance"] if s["state"] == "partial" else s["amount"]) or 0.0 for s in open_lines)
                dpd = (end - min(s["due_date"] for s in open_lines)).days if open_lines else 0
                instalment = self._instalment(contract, refs)
                is_default = cid in in_default
                rows.append({
                    "contract_id": cid, "rider_id": contract.rider_id.id, "bike_id": contract.bike_id.id,
                    "product_group_id": groups_of[cid].id if groups_of.get(cid) else False,
                    "state": state_at[cid], "payment_state": pstate_at.get(cid), "is_active": state_at[cid] in ACTIVE_STATES,
                    "in_default": is_default, "arrears": arrears, "penalties": 0.0, "credit": 0.0,
                    "instalment": instalment, "dpd": dpd,
                    "risk_category": self._risk_category(pstate_at.get(cid), arrears, instalment, is_default, config),
                    "par_bucket": self._par_bucket(dpd, config),
                    "due_in_period": due.get(cid, 0.0), "collected_in_period": collected.get(cid, 0.0),
                })
            out[end] = rows
        return out

    def _vehicle_rows(self, ends, live=False):
        """{period_end: (available_ids, ever_contracted_ids, group_by_vehicle)} for R06/R16."""
        service = self.env["gh.kpi.service"]
        vehicles = self.env["fleet.vehicle"].sudo().search([])
        _p, by_model, _g = self.env["gh.product.group"]._group_maps()
        contracts = self.env["rider.contract"].sudo().with_context(active_test=False).search([("bike_id", "!=", False)])
        cstates = {} if live else self._tracked_values_at("rider.contract", "state", contracts, ends)
        vstates = {} if live else self._tracked_values_at("fleet.vehicle", "state", vehicles, ends)
        out = {}
        for end in ends:
            if live:
                categories = service._vehicle_categories(vehicles)
                ever = service._ever_contracted_vehicle_ids()
            else:
                on_contract = {c.bike_id.id for c in contracts if cstates[(c.id, end)] in ACTIVE_STATES}
                ever = {c.bike_id.id for c in contracts if cstates[(c.id, end)] in
                        ("running", "pause", "expired", "closed", "terminated")}
                categories = service._vehicle_categories(
                    vehicles, state_override={v.id: vstates[(v.id, end)] for v in vehicles},
                    on_contract_override=on_contract)
                categories = {vid: cat for vid, cat in categories.items() if vstates[(vid, end)] is not None}
            available = [vid for vid, cat in categories.items() if cat == "available"]
            out[end] = (available, ever, {v.id: by_model.get(v.model_id.id) for v in vehicles})
        return out

    # ------------------------------------------------------------ KPI rows
    def _kpi_rows(self, rows, end, vehicle_info):
        """gh.kpi.snapshot rows derived from contract rows for one period end."""
        config = self._config()
        active = [r for r in rows if r["is_active"]]
        riders = {r["rider_id"]: r for r in sorted(active, key=lambda r: r["contract_id"]) if r["rider_id"]}
        rider_recs = self.env["rider"].sudo().browse(list(riders))
        limit = config.youth_age_limit
        out = [("R01", "", 0.0, len(riders)), ("P01", "", 0.0, len(active))]
        buckets = Counter()
        for rider in rider_recs:
            age = relativedelta(end, rider.date_of_birth).years if rider.date_of_birth else None
            if rider.gender in ("male", "female") and age is not None:
                buckets[f"{'m' if rider.gender == 'male' else 'f'}_{'u' if age < limit else 'o'}"] += 1
            else:
                buckets["unknown"] += 1
        out += [("R05", f"bucket:{k}", 0.0, buckets.get(k, 0)) for k in ("m_u", "f_u", "m_o", "f_o", "unknown")]
        by_group = Counter(r["product_group_id"] or "unmapped" for r in riders.values())
        out += [("R08", f"product:{k}", 0.0, n) for k, n in by_group.items()]
        total_arrears = sum(r["arrears"] for r in active)
        out += [("P02", "", total_arrears, 0), ("P03", "", total_arrears / len(active) if active else 0.0, 0)]
        risk = Counter(r["risk_category"] for r in active)
        out += [("P11", f"risk:{k}", 0.0, risk.get(k, 0)) for k in RISK_ORDER]
        par = Counter(r["par_bucket"] for r in active)
        out += [("P12", f"par:{k}", 0.0, par.get(k, 0)) for k in PAR_ORDER]
        out.append(("P13", "", 0.0, sum(1 for r in rows if r["in_default"])))
        due_active = sum(r["due_in_period"] for r in active)
        collected_active = sum(r["collected_in_period"] for r in active)
        out += [("C08", "due", due_active, 0), ("C08", "collected", collected_active, 0)]
        if vehicle_info:
            available, ever, groups = vehicle_info
            standard = self._group_standard_instalment()
            weeks = 1 if (end - period_start("week", end)).days == 6 else 4.345
            fleet_due = due_active + sum(standard.get(groups[v].id, 0.0) if groups.get(v) else 0.0
                                         for v in available) * weeks
            out += [("C09", "due", fleet_due, 0), ("C09", "collected", collected_active, 0)]
            out += [("R06", "", 0.0, len(available)),
                    ("R06", "kind:new", 0.0, sum(1 for v in available if v not in ever)),
                    ("R06", "kind:refinancing", 0.0, sum(1 for v in available if v in ever))]
        return out

    def _write(self, period_type, end, rows, kpi_rows, source, force=False):
        company = self.env.company
        Snap = self.env["gh.contract.snapshot"].sudo()
        existing = Snap.search([("company_id", "=", company.id), ("period_type", "=", period_type),
                                ("period_end", "=", end)])
        if existing and not force and source == "backfill" and set(existing.mapped("source")) - {"backfill"}:
            return False  # frozen: a live (cron/manual) snapshot exists for this period
        existing.unlink()
        Snap.create([dict(r, company_id=company.id, period_type=period_type, period_end=end, source=source)
                     for r in rows])
        self.env["gh.kpi.snapshot"]._upsert(company, period_type, period_start(period_type, end), end, kpi_rows, source)
        return True

    @api.model
    def _snapshot_live(self, period_type, on, source="cron"):
        rows = self._live_contract_rows(on, period_type)
        vehicle_info = self._vehicle_rows([on], live=True)[on]
        kpi_rows = self._kpi_rows(rows, on, vehicle_info) + \
            self.env["gh.kpi.service"]._riders_snapshot_rows(on)
        return self._write(period_type, on, rows, kpi_rows, source, force=True)

    @api.model
    def backfill(self, date_from, date_to, period_types=("week", "month"), force=False):
        """Reconstruct and store every week end / month end in [date_from, date_to)."""
        today = fields.Date.context_today(self)
        date_to = min(date_to, today - timedelta(days=1))
        written = Counter()
        for period_type in period_types:
            ends = list(week_ends(date_from, date_to) if period_type == "week" else month_ends(date_from, date_to))
            if not ends:
                continue
            contract_rows = self._reconstructed_contract_rows(period_type, ends)
            vehicle_rows = self._vehicle_rows(ends)
            for end in ends:
                kpi_rows = self._kpi_rows(contract_rows[end], end, vehicle_rows[end])
                if self._write(period_type, end, contract_rows[end], kpi_rows, "backfill", force):
                    written[period_type] += 1
                else:
                    written["frozen_" + period_type] += 1
                    self._compare_with_live(period_type, end, kpi_rows, written)
        _logger.info("Green Hub backfill wrote %s", dict(written))
        return dict(written)

    def _compare_with_live(self, period_type, end, kpi_rows, out):
        """Check 7: a frozen live snapshot vs the reconstruction for the same period end."""
        live = {(s.metric_code, s.dim_key or ""): (s.value_count or s.value_float)
                for s in self.env["gh.kpi.snapshot"].sudo().search([
                    ("period_type", "=", period_type), ("period_end", "=", end),
                    ("company_id", "=", self.env.company.id), ("metric_code", "in", ["R01", "P01", "P02"])])}
        rebuilt = {(c, d or ""): (n or f) for c, d, f, n in kpi_rows if c in ("R01", "P01", "P02")}
        diffs = [f"{c}{':' + d if d else ''} live {live[(c, d)]:,.0f} vs rebuilt {v:,.0f}"
                 for (c, d), v in rebuilt.items() if (c, d) in live and abs(live[(c, d)] - v) > 0.5]
        out.setdefault("check7", []).append(f"{end}: " + ("; ".join(diffs) if diffs else "matches"))

    @api.model
    def comparison_csv(self, period_type="week"):
        """Per period: the figures Green Hub keeps by hand, for sign-off against their sheets."""
        snaps = self.env["gh.kpi.snapshot"].sudo().search(
            [("period_type", "=", period_type), ("company_id", "=", self.env.company.id),
             ("metric_code", "in", ["R01", "P01", "P02", "P13", "R06"])], order="period_end")
        table = defaultdict(dict)
        for s in snaps:
            key = s.metric_code if not s.dim_key else f"{s.metric_code}:{s.dim_key}"
            table[s.period_end][key] = s.value_count or round(s.value_float)
        growth = self.env["gh.kpi.service"]._growth_rows(period_type, None, 400)
        growth_by_end = {g["end"]: g for g in growth}
        risk = defaultdict(dict)
        for s in self.env["gh.kpi.snapshot"].sudo().search(
                [("period_type", "=", period_type), ("metric_code", "=", "P11"),
                 ("company_id", "=", self.env.company.id)]):
            risk[s.period_end][s.dim_key.split(":", 1)[1]] = s.value_count
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["period_end", "active_riders", "new_first_time", "returning", "exits", "active_contracts",
                         "total_arrears_ugx", "in_default", "available_bikes"] + [f"risk_{k}" for k in RISK_ORDER])
        for end in sorted(table):
            g = growth_by_end.get(fields.Date.to_string(end), {})
            writer.writerow([end, table[end].get("R01", ""), g.get("first_time", ""), g.get("returning", ""),
                             g.get("exits", ""), table[end].get("P01", ""), table[end].get("P02", ""),
                             table[end].get("P13", ""), table[end].get("R06", "")] +
                            [risk[end].get(k, "") for k in RISK_ORDER])
        return buf.getvalue()


class GhBackfillWizard(models.TransientModel):
    _name = "gh.backfill.wizard"
    _description = "Green Hub history backfill"

    date_from = fields.Date(required=True, default=lambda self: self.env["gh.dashboard.config"]._get_config().history_start)
    date_to = fields.Date(required=True, default=fields.Date.context_today)
    weekly = fields.Boolean(default=True)
    monthly = fields.Boolean(default=True)
    force = fields.Boolean("Overwrite live snapshots too",
                           help="Off: periods that already have a cron or manual snapshot are left frozen.")
    result = fields.Text(readonly=True)
    csv_file = fields.Binary("Comparison CSV", readonly=True, attachment=False)
    csv_name = fields.Char(default="greenhub_backfill_comparison.csv")

    def action_run(self):
        self.ensure_one()
        if not self.env.user.has_group("greenhub_dashboards.group_gh_dashboard_manager"):
            raise UserError(_("Only a Dashboard Manager can run the backfill."))
        types = [t for t, on in (("week", self.weekly), ("month", self.monthly)) if on]
        written = self.env["gh.history.service"].backfill(self.date_from, self.date_to, types, self.force)
        csv_text = self.env["gh.history.service"].comparison_csv("week")
        check7 = written.get("check7", [])
        self.write({
            "result": _("Written: %(w)s weekly and %(m)s monthly periods, by %(u)s at %(t)s.",
                        w=written.get("week", 0), m=written.get("month", 0), u=self.env.user.name,
                        t=fields.Datetime.now())
                      + ("\n" + _("Frozen live periods compared with the reconstruction (check 7):") + "\n"
                         + "\n".join(check7) if check7 else ""),
            "csv_file": base64.b64encode(csv_text.encode()),
        })
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
                "view_mode": "form", "target": "new"}

    def action_snapshot_now(self):
        self.ensure_one()
        today = fields.Date.context_today(self)
        self.env["gh.history.service"]._snapshot_live("week", today, source="manual")
        self.result = _("Live snapshot written for %s by %s.", today, self.env.user.name)
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
                "view_mode": "form", "target": "new"}

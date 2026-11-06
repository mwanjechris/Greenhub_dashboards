"""Every Green Hub KPI is defined once, here.

Rules this file keeps (see the rebuild brief, sections 0 and 5):
- all maths runs on the server; the browser only renders the JSON;
- one definition per KPI, reused by every dashboard that shows it;
- no matching on names or tags for business logic: products, vehicle
  models and vehicle categories come from the mapping models;
- every figure carries the domain that opens its records.
"""
import logging
from collections import Counter, defaultdict
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)

ACTIVE_STATES = ("running", "pause")
# A vehicle "has had a contract" once a contract on it actually started.
STARTED_STATES = ("running", "pause", "expired", "closed", "terminated")
UNMAPPED = "unmapped"


class GhKpiService(models.AbstractModel):
    _name = "gh.kpi.service"
    _description = "Green Hub KPI service"

    # ------------------------------------------------------------------ helpers
    def _check_access(self):
        if not self.env.user.has_group("greenhub_dashboards.group_gh_dashboard_user"):
            raise AccessError(_("You need the Green Hub Dashboard User group to open this dashboard."))

    def _today(self):
        return fields.Date.context_today(self)

    def _panel(self, func, *args):
        """Run one panel; a failure is reported on that panel only."""
        try:
            with self.env.cr.savepoint():
                return dict(func(*args), ok=True)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, never swallowed silently
            _logger.exception("Green Hub dashboard panel %s failed", func.__name__)
            return {"ok": False, "error": str(exc)}

    @staticmethod
    def _pct(part, whole):
        return round(100.0 * part / whole, 1) if whole else None

    @staticmethod
    def _age_at(dob, on):
        if not dob:
            return None
        return relativedelta(on, dob).years

    def _active_contracts(self, product_group_id=None):
        contracts = self.env["rider.contract"].sudo().search([("state", "in", ACTIVE_STATES)])
        if product_group_id:
            by_product, _by_model, _groups = self.env["gh.product.group"]._group_maps()
            contracts = contracts.filtered(
                lambda c: by_product.get(c.product_product_id.id)
                and by_product[c.product_product_id.id].id == product_group_id
            )
        return contracts

    def _rider_contract_map(self, contracts):
        """One contract per rider: the most recently started active contract."""
        best = {}
        for contract in contracts:
            if not contract.rider_id:
                continue
            current = best.get(contract.rider_id.id)
            key = (contract.contract_start_date or fields.Date.to_date("1900-01-01"), contract.id)
            if not current or key > current[0]:
                best[contract.rider_id.id] = (key, contract)
        return {rid: c for rid, (_k, c) in best.items()}

    def _group_payload(self, groups):
        return [{"id": g.id, "name": g.name, "slot": g.color_slot} for g in groups]

    # ---------------------------------------------------------- vehicle category
    def _vehicle_categories(self, vehicles, state_override=None, on_contract_override=None):
        """Map vehicle id -> category using the ordered rules (first match wins).

        The overrides let the history service categorise vehicles at a past date.
        """
        rules = self.env["gh.vehicle.category.rule"].sudo().search([])
        loaner_ids, contract_ids = set(), set()
        if on_contract_override is not None:
            contract_ids = set(on_contract_override)
        elif any(rule.on_active_contract for rule in rules):
            contract_ids = set(self.env["rider.contract"].sudo().search(
                [("state", "in", ACTIVE_STATES), ("bike_id", "!=", False)]).mapped("bike_id").ids)
        if any(rule.ongoing_loaner for rule in rules):
            loaner_ids = set(self.env["loaner.bike.tracking"].sudo().search(
                [("status", "=", "ongoing")]).mapped("loaner_bike").ids)
        result = {}
        for vehicle in vehicles:
            category = "other"
            vstate = state_override.get(vehicle.id) if state_override is not None else vehicle.state
            for rule in rules:
                states = rule._state_list()
                if states and vstate not in states:
                    continue
                if rule.tag_ids and not (rule.tag_ids & vehicle.tag_ids):
                    continue
                if rule.on_active_contract and vehicle.id not in contract_ids:
                    continue
                if rule.ongoing_loaner and vehicle.id not in loaner_ids:
                    continue
                category = rule.category
                break
            result[vehicle.id] = category
        return result

    def _ever_contracted_vehicle_ids(self):
        rows = self.env["rider.contract"].sudo()._read_group(
            [("state", "in", STARTED_STATES), ("bike_id", "!=", False)], ["bike_id"], ["__count"])
        return {bike.id for bike, _count in rows}

    # ------------------------------------------------------------------ R panels
    def _riders_core(self, on, product_group_id):
        """R01-R05 and R08."""
        config = self.env["gh.dashboard.config"]._get_config()
        contracts = self._active_contracts(product_group_id)
        per_rider = self._rider_contract_map(contracts)
        riders = self.env["rider"].sudo().browse(list(per_rider))
        total = len(riders)
        running = len(set(contracts.filtered(lambda c: c.state == "running").mapped("rider_id").ids))
        paused = total - running

        women = riders.filtered(lambda r: r.gender == "female")
        men = riders.filtered(lambda r: r.gender == "male")
        limit = config.youth_age_limit
        ages = {r.id: self._age_at(r.date_of_birth, on) for r in riders}
        youth = riders.filtered(lambda r: ages[r.id] is not None and ages[r.id] < limit)

        buckets = [
            ("m_u", _("Men under %s", limit), lambda r: r.gender == "male" and ages[r.id] is not None and ages[r.id] < limit),
            ("f_u", _("Women under %s", limit), lambda r: r.gender == "female" and ages[r.id] is not None and ages[r.id] < limit),
            ("m_o", _("Men %s+", limit), lambda r: r.gender == "male" and ages[r.id] is not None and ages[r.id] >= limit),
            ("f_o", _("Women %s+", limit), lambda r: r.gender == "female" and ages[r.id] is not None and ages[r.id] >= limit),
        ]
        rows, used = [], riders.browse()
        for key, label, test in buckets:
            members = riders.filtered(test)
            used |= members
            rows.append({"key": key, "label": label, "count": len(members), "pct": self._pct(len(members), total),
                         "domain": [("id", "in", members.ids)]})
        unknown = riders - used
        rows.append({"key": "unknown", "label": _("Unknown age or gender"), "count": len(unknown),
                     "pct": self._pct(len(unknown), total), "domain": [("id", "in", unknown.ids)]})

        by_product, _by_model, groups = self.env["gh.product.group"]._group_maps()
        product_counts = Counter()
        product_members = defaultdict(list)
        for rider_id, contract in per_rider.items():
            group = by_product.get(contract.product_product_id.id)
            key = group.id if group else UNMAPPED
            product_counts[key] += 1
            product_members[key].append(contract.id)
        product_rows = [
            {"group_id": g.id, "label": g.name, "slot": g.color_slot, "count": product_counts.get(g.id, 0),
             "pct": self._pct(product_counts.get(g.id, 0), total),
             "domain": [("id", "in", product_members.get(g.id, []))]}
            for g in groups
        ]
        if product_counts.get(UNMAPPED):
            product_rows.append({"group_id": False, "label": _("Product not mapped to a group"), "slot": False,
                                 "count": product_counts[UNMAPPED], "pct": self._pct(product_counts[UNMAPPED], total),
                                 "domain": [("id", "in", product_members[UNMAPPED])], "warn": True})

        rider_domain = [("id", "in", riders.ids)]
        return {
            "active_riders": {"value": total, "running": running, "paused": paused, "domain": rider_domain},
            "active_contracts": {"value": len(contracts), "domain": [("id", "in", contracts.ids)]},
            "women": {"value": len(women), "pct": self._pct(len(women), total), "domain": [("id", "in", women.ids)]},
            "men": {"value": len(men), "pct": self._pct(len(men), total), "domain": [("id", "in", men.ids)]},
            "youth": {"value": len(youth), "pct": self._pct(len(youth), total), "limit": limit,
                      "no_dob": sum(1 for a in ages.values() if a is None), "domain": [("id", "in", youth.ids)]},
            "gender_age": rows,
            "by_product": product_rows,
            "multi_contract_riders": sorted(
                rid for rid, n in Counter(c.rider_id.id for c in contracts if c.rider_id).items() if n > 1
            ),
        }

    def _fleet(self, on, product_group_id):
        """R06, R07, R09."""
        config = self.env["gh.dashboard.config"]._get_config()
        vehicles = self.env["fleet.vehicle"].sudo().search([])
        _by_product, by_model, groups = self.env["gh.product.group"]._group_maps()
        if product_group_id:
            vehicles = vehicles.filtered(
                lambda v: by_model.get(v.model_id.id) and by_model[v.model_id.id].id == product_group_id)
        categories = self._vehicle_categories(vehicles)
        ever = self._ever_contracted_vehicle_ids()
        test_ids = {vid for vid, cat in categories.items() if cat == "test"}
        fleet_ids = [v.id for v in vehicles if not (config.exclude_test_vehicles and v.id in test_ids)]
        fleet_total = len(fleet_ids)

        available = [vid for vid in fleet_ids if categories[vid] == "available"]
        available_new = [vid for vid in available if vid not in ever]
        available_refi = [vid for vid in available if vid in ever]

        cat_labels = dict(self.env["gh.vehicle.category.rule"]._fields["category"].selection)
        shown_cats = [c for c, _l in self.env["gh.vehicle.category.rule"]._fields["category"].selection
                      if c != "test" or not config.exclude_test_vehicles]
        group_keys = [(g.id, g.name, g.color_slot) for g in groups] + [(UNMAPPED, _("Model not mapped"), False)]
        matrix = {gk[0]: defaultdict(list) for gk in group_keys}
        for vid in fleet_ids:
            vehicle = vehicles.browse(vid)
            group = by_model.get(vehicle.model_id.id)
            matrix[group.id if group else UNMAPPED][categories[vid]].append(vid)
        matrix_rows = []
        for gid, name, slot in group_keys:
            cells = matrix[gid]
            row_total = sum(len(v) for v in cells.values())
            if gid == UNMAPPED and not row_total:
                continue
            matrix_rows.append({
                "group_id": gid if gid != UNMAPPED else False, "label": name, "slot": slot, "total": row_total,
                "warn": gid == UNMAPPED,
                "cells": [{"category": c, "count": len(cells.get(c, [])),
                           "domain": [("id", "in", cells.get(c, []))]} for c in shown_cats],
            })
        column_totals = [{"category": c, "label": cat_labels[c],
                          "count": sum(len(matrix[g[0]].get(c, [])) for g in group_keys),
                          "pct": self._pct(sum(len(matrix[g[0]].get(c, [])) for g in group_keys), fleet_total)}
                         for c in shown_cats]

        by_model_rows = Counter(vehicles.browse(available).mapped(lambda v: v.model_id.id))
        models_ = self.env["fleet.vehicle.model"].sudo().browse(list(by_model_rows))
        available_by_model = sorted(
            [{"label": m.display_name, "count": by_model_rows[m.id], "pct": self._pct(by_model_rows[m.id], fleet_total),
              "domain": [("id", "in", [vid for vid in available if vehicles.browse(vid).model_id == m])]}
             for m in models_], key=lambda r: -r["count"])

        on_contract = [vid for vid in fleet_ids if categories[vid] == "on_contract"]
        return {
            "fleet_total": fleet_total,
            "test_excluded": len(test_ids) if config.exclude_test_vehicles else 0,
            "fleet_domain": [("id", "in", fleet_ids)],
            "unassigned": {"value": len(available), "pct": self._pct(len(available), fleet_total),
                           "new": len(available_new), "refinancing": len(available_refi),
                           "domain": [("id", "in", available)],
                           "new_domain": [("id", "in", available_new)],
                           "refi_domain": [("id", "in", available_refi)]},
            "on_contract": {"value": len(on_contract), "pct": self._pct(len(on_contract), fleet_total),
                            "domain": [("id", "in", on_contract)]},
            "uncategorised": sum(1 for vid in fleet_ids if categories[vid] == "other"),
            "has_rules": bool(self.env["gh.vehicle.category.rule"].sudo().search_count([])),
            "matrix": {"columns": column_totals, "rows": matrix_rows},
            "available_by_model": available_by_model,
        }

    def _referrals(self, on, product_group_id):
        """R14: contracts started in the look-back window, by referral source."""
        config = self.env["gh.dashboard.config"]._get_config()
        since = on - timedelta(weeks=config.referral_window_weeks)
        domain = [("contract_start_date", ">", since), ("contract_start_date", "<=", on),
                  ("state", "in", STARTED_STATES)]
        contracts = self.env["rider.contract"].sudo().search(domain)
        if product_group_id:
            by_product, _m, _g = self.env["gh.product.group"]._group_maps()
            contracts = contracts.filtered(lambda c: by_product.get(c.product_product_id.id)
                                           and by_product[c.product_product_id.id].id == product_group_id)
        # Green Hub records the source on the rider's UTM source; the older
        # selection field is the fallback for riders captured before that.
        labels = dict(self.env["rider"]._fields["source_of_information"]._description_selection(self.env))
        buckets = defaultdict(list)
        for contract in contracts:
            rider = contract.rider_id
            if rider.source_id:
                label = rider.source_id.name
            elif rider.source_of_information:
                label = labels.get(rider.source_of_information, rider.source_of_information)
            else:
                label = _("Not recorded")
            buckets[label].append(contract.id)
        total = len(contracts)
        rows = sorted(
            [{"label": label, "count": len(ids), "pct": self._pct(len(ids), total),
              "domain": [("id", "in", ids)]} for label, ids in buckets.items()],
            key=lambda r: -r["count"])
        return {"weeks": config.referral_window_weeks, "total": total, "rows": rows}

    def _safety(self, on, product_group_id):
        """R17 accidents and R18 licences."""
        config = self.env["gh.dashboard.config"]._get_config()
        since = on - timedelta(days=config.accident_window_days)
        accidents = self.env["fleet.vehicle.accident"].sudo().search([("date", ">", since), ("date", "<=", on)])
        fleet = self._fleet(on, product_group_id)
        if product_group_id:
            fleet_ids = set(fleet["fleet_domain"][0][2])
            accidents = accidents.filtered(lambda a: a.vehicle_id.id in fleet_ids)
        active_bikes = fleet["on_contract"]["value"]

        contracts = self._active_contracts(product_group_id)
        riders = self.env["rider"].sudo().browse(list(self._rider_contract_map(contracts)))
        notice = on + timedelta(days=config.licence_notice_days)
        groups = {"valid": [], "expiring": [], "expired": [], "none": [], "unknown": []}
        for rider in riders:
            if rider.license_status == "no_license":
                groups["none"].append(rider.id)
            elif not rider.license_end_date:
                groups["unknown"].append(rider.id)
            elif rider.license_end_date < on:
                groups["expired"].append(rider.id)
            elif rider.license_end_date <= notice:
                groups["expiring"].append(rider.id)
            else:
                groups["valid"].append(rider.id)
        expiring = riders.browse(groups["expiring"]).sorted("license_end_date")
        per_rider = self._rider_contract_map(contracts)
        by_product, _m, _g = self.env["gh.product.group"]._group_maps()
        expiring_rows = []
        for rider in expiring:
            contract = per_rider.get(rider.id)
            group = contract and by_product.get(contract.product_product_id.id)
            expiring_rows.append({
                "rider_id": rider.id, "name": rider.display_name, "product": group.name if group else "",
                "end": fields.Date.to_string(rider.license_end_date),
                "days_left": (rider.license_end_date - on).days,
            })
        total = len(riders)
        return {
            "accidents": {"value": len(accidents), "days": config.accident_window_days,
                          "per_100": round(100.0 * len(accidents) / active_bikes, 1) if active_bikes else None,
                          "domain": [("id", "in", accidents.ids)]},
            "licences": {
                "total": total, "notice_days": config.licence_notice_days,
                "counts": {k: {"count": len(v), "pct": self._pct(len(v), total), "domain": [("id", "in", v)]}
                           for k, v in groups.items()},
                "learner_supported": False,
                "expiring": expiring_rows,
            },
        }

    def _history(self, metric_codes, period_type, limit_periods):
        """Trend series straight from the snapshot store."""
        snaps = self.env["gh.kpi.snapshot"].sudo().search(
            [("metric_code", "in", metric_codes), ("period_type", "=", period_type),
             ("company_id", "=", self.env.company.id)], order="period_end asc")
        ends = sorted(set(snaps.mapped("period_end")))[-limit_periods:]
        series = defaultdict(dict)
        for snap in snaps:
            if snap.period_end in ends:
                series[f"{snap.metric_code}|{snap.dim_key or ''}"][fields.Date.to_string(snap.period_end)] = \
                    snap.value_count or snap.value_float
        return {"periods": [fields.Date.to_string(d) for d in ends], "series": dict(series)}

    # ------------------------------------------------------------------ history
    def _range_start(self, range_key, grain, on):
        if range_key == "ytd":
            return on.replace(month=1, day=1)
        if range_key == "12m":
            return on - relativedelta(months=12)
        return on - timedelta(weeks=26) if grain == "week" else on - relativedelta(months=6)

    def _period_ends(self, grain, date_from=None, date_to=None):
        domain = [("period_type", "=", grain), ("company_id", "=", self.env.company.id)]
        if date_from:
            domain.append(("period_end", ">=", date_from))
        if date_to:
            domain.append(("period_end", "<=", date_to))
        rows = self.env["gh.contract.snapshot"].sudo()._read_group(domain, ["period_end:day"], ["__count"])
        return sorted(d for d, _n in rows)

    def _active_sets(self, grain, ends, product_group_id=None):
        domain = [("period_type", "=", grain), ("period_end", "in", ends), ("is_active", "=", True),
                  ("company_id", "=", self.env.company.id)]
        if product_group_id:
            domain.append(("product_group_id", "=", product_group_id))
        sets, contracts = defaultdict(set), defaultdict(dict)
        for snap in self.env["gh.contract.snapshot"].sudo().search_read(domain, ["period_end", "rider_id", "contract_id"]):
            if snap["rider_id"]:
                sets[snap["period_end"]].add(snap["rider_id"][0])
                contracts[snap["period_end"]][snap["rider_id"][0]] = snap["contract_id"][0]
        return sets, contracts

    def _growth_rows(self, grain, product_group_id, limit, date_from=None, date_to=None):
        all_ends = self._period_ends(grain, None, date_to)
        if len(all_ends) < 2:
            return []
        sets, contracts = self._active_sets(grain, all_ends, product_group_id)
        Exit = self.env["gh.exit.type.rule"]
        Contract = self.env["rider.contract"].sudo()
        seen, rows = set(), []
        for i, end in enumerate(all_ends):
            cur = sets.get(end, set())
            if i == 0:
                seen |= cur
                continue
            prev = sets.get(all_ends[i - 1], set())
            additions, exits = cur - prev, prev - cur
            first = {r for r in additions if r not in seen}
            exit_types = Counter(Exit._exit_type(Contract.browse(contracts[all_ends[i - 1]][r])) for r in exits)
            seen |= cur
            if date_from and end < date_from:
                continue
            rows.append({
                "end": fields.Date.to_string(end), "opening": len(prev), "first_time": len(first),
                "returning": len(additions - first), "exits": len(exits), "closing": len(cur),
                "exits_planned": exit_types.get("completion", 0) + exit_types.get("upgrade", 0),
                "exits_default": exit_types.get("repossession_default", 0),
                "exits_other": exit_types.get("voluntary_return", 0) + exit_types.get("other", 0),
                "retention": self._pct(len(prev & cur), len(prev)),
                "ok": len(prev) + len(additions) - len(exits) == len(cur),
            })
        return rows[-limit:]

    def _riders_trends(self, on, product_group_id, grain, range_key):
        config = self.env["gh.dashboard.config"]._get_config()
        date_from = self._range_start(range_key, grain, on)
        growth = self._growth_rows(grain, product_group_id, 400, date_from, on)
        ends = [fields.Date.to_date(g["end"]) for g in growth]
        # lifetime retention: riders active at the first snapshot on/after history_start
        all_ends = self._period_ends("week", config.history_start, on)
        lifetime = None
        if len(all_ends) >= 2:
            sets, _c = self._active_sets("week", [all_ends[0], all_ends[-1]], product_group_id)
            base = sets.get(all_ends[0], set())
            lifetime = {"pct": self._pct(len(base & sets.get(all_ends[-1], set())), len(base)),
                        "since": fields.Date.to_string(all_ends[0]), "cohort": len(base)}
        month_ends = self._period_ends("month", None, on)
        monthly = None
        if len(month_ends) >= 2:
            sets, _c = self._active_sets("month", month_ends[-2:], product_group_id)
            prev, cur = sets.get(month_ends[-2], set()), sets.get(month_ends[-1], set())
            monthly = {"pct": self._pct(len(prev & cur), len(prev)), "retained": len(prev & cur),
                       "cohort": len(prev), "month": fields.Date.to_string(month_ends[-1])}
        weekly = [g["retention"] for g in growth if g["retention"] is not None]
        snaps = self.env["gh.kpi.snapshot"].sudo().search([
            ("period_type", "=", grain), ("period_end", "in", ends), ("company_id", "=", self.env.company.id),
            ("metric_code", "in", ["R05", "R06"])])
        demo, unassigned = defaultdict(dict), defaultdict(dict)
        for snap in snaps:
            key = fields.Date.to_string(snap.period_end)
            if snap.metric_code == "R05":
                demo[key][snap.dim_key.split(":", 1)[1]] = snap.value_count
            elif snap.dim_key:
                unassigned[key][snap.dim_key.split(":", 1)[1]] = snap.value_count
        return {
            "grain": grain, "range": range_key, "periods": [g["end"] for g in growth],
            "active": [g["closing"] for g in growth], "growth": growth,
            "lifetime": lifetime, "monthly": monthly,
            "weekly_avg": round(sum(weekly) / len(weekly), 1) if weekly else None,
            "demo": [demo.get(g["end"], {}) for g in growth],
            "unassigned": [unassigned.get(g["end"], {}) for g in growth],
            "product_filtered": bool(product_group_id),
            "assumptions": [
                _("Past status comes from Odoo's change history; before a contract's first change, its first old value."),
                _("Unassigned history uses the tracked vehicle state and today's tags."),
            ],
        }

    def _riders_core_hist(self, end, product_group_id):
        """R01-R05, R08 at a past period end, from contract snapshots."""
        config = self.env["gh.dashboard.config"]._get_config()
        domain = [("period_type", "=", "week"), ("period_end", "=", end), ("is_active", "=", True),
                  ("company_id", "=", self.env.company.id)]
        if product_group_id:
            domain.append(("product_group_id", "=", product_group_id))
        snaps = self.env["gh.contract.snapshot"].sudo().search(domain)
        per_rider = {}
        for snap in snaps.sorted("contract_id"):
            if snap.rider_id:
                per_rider[snap.rider_id.id] = snap
        riders = self.env["rider"].sudo().browse(list(per_rider))
        total, limit = len(riders), config.youth_age_limit
        ages = {r.id: self._age_at(r.date_of_birth, end) for r in riders}
        def pick(test):
            return riders.filtered(test)
        women, men = pick(lambda r: r.gender == "female"), pick(lambda r: r.gender == "male")
        youth = pick(lambda r: ages[r.id] is not None and ages[r.id] < limit)
        rows = []
        used = riders.browse()
        for key, label, g, young in (("m_u", _("Men under %s", limit), "male", True), ("f_u", _("Women under %s", limit), "female", True),
                                     ("m_o", _("Men %s+", limit), "male", False), ("f_o", _("Women %s+", limit), "female", False)):
            members = pick(lambda r: r.gender == g and ages[r.id] is not None and (ages[r.id] < limit) == young)
            used |= members
            rows.append({"key": key, "label": label, "count": len(members), "pct": self._pct(len(members), total),
                         "domain": [("id", "in", members.ids)]})
        unknown = riders - used
        rows.append({"key": "unknown", "label": _("Unknown age or gender"), "count": len(unknown),
                     "pct": self._pct(len(unknown), total), "domain": [("id", "in", unknown.ids)]})
        groups = self.env["gh.product.group"].sudo().search([])
        counts = Counter(s.product_group_id.id or UNMAPPED for s in per_rider.values())
        members = defaultdict(list)
        for s in per_rider.values():
            members[s.product_group_id.id or UNMAPPED].append(s.contract_id.id)
        by_product = [{"group_id": g.id, "label": g.name, "slot": g.color_slot, "count": counts.get(g.id, 0),
                       "pct": self._pct(counts.get(g.id, 0), total), "domain": [("id", "in", members.get(g.id, []))]}
                      for g in groups]
        if counts.get(UNMAPPED):
            by_product.append({"group_id": False, "label": _("Product not mapped to a group"), "slot": False,
                               "count": counts[UNMAPPED], "pct": self._pct(counts[UNMAPPED], total),
                               "domain": [("id", "in", members[UNMAPPED])], "warn": True})
        running = sum(1 for s in per_rider.values() if s.state == "running")
        return {
            "active_riders": {"value": total, "running": running, "paused": total - running,
                              "domain": [("id", "in", riders.ids)]},
            "active_contracts": {"value": len(snaps), "domain": [("id", "in", snaps.mapped("contract_id").ids)]},
            "women": {"value": len(women), "pct": self._pct(len(women), total), "domain": [("id", "in", women.ids)]},
            "men": {"value": len(men), "pct": self._pct(len(men), total), "domain": [("id", "in", men.ids)]},
            "youth": {"value": len(youth), "pct": self._pct(len(youth), total), "limit": limit,
                      "no_dob": sum(1 for a in ages.values() if a is None), "domain": [("id", "in", youth.ids)]},
            "gender_age": rows, "by_product": by_product,
            "multi_contract_riders": sorted(r for r, n in Counter(s.rider_id.id for s in snaps if s.rider_id).items() if n > 1),
        }

    def _as_of(self, as_of):
        today = self._today()
        if not as_of:
            return today, False
        d = fields.Date.to_date(as_of)
        return (today, False) if d >= today else (d, True)

    def _as_of_options(self):
        ends = self._period_ends("week")
        return [fields.Date.to_string(d) for d in reversed(ends[-26:])]

    # ------------------------------------------------------------------ checks
    def _riders_checks(self, core, fleet):
        checks = []
        if core.get("ok"):
            total = core["active_riders"]["value"]
            s05 = sum(r["count"] for r in core["gender_age"])
            checks.append({"code": "R05", "ok": s05 == total,
                           "message": _("Gender and age categories sum to %(s)s of %(t)s active riders", s=s05, t=total)})
            s08 = sum(r["count"] for r in core["by_product"])
            unmapped = sum(r["count"] for r in core["by_product"] if r.get("warn"))
            checks.append({"code": "R08", "ok": s08 == total and not unmapped,
                           "message": _("Products sum to %(s)s of %(t)s; %(u)s not mapped to a group", s=s08, t=total, u=unmapped)})
            contracts = core["active_contracts"]["value"]
            checks.append({"code": "P01", "ok": contracts >= total,
                           "message": _("%(c)s active contracts for %(t)s riders; %(m)s riders hold more than one",
                                        c=contracts, t=total, m=len(core["multi_contract_riders"]))})
        if fleet.get("ok"):
            s07 = sum(r["total"] for r in fleet["matrix"]["rows"])
            checks.append({"code": "R07", "ok": s07 == fleet["fleet_total"] and not fleet["uncategorised"],
                           "message": _("Vehicle categories sum to %(s)s of %(t)s; %(u)s match no category rule",
                                        s=s07, t=fleet["fleet_total"], u=fleet["uncategorised"])})
        return checks

    # ------------------------------------------------------------------ public
    @api.model
    def get_riders_dashboard(self, product_group_id=None, grain="week", as_of=False, range_key="26w"):
        """Riders & Customers payload. Today = live; a past week end = snapshots."""
        self._check_access()
        on, historic = self._as_of(as_of)
        product_group_id = product_group_id or None
        if historic:
            core = self._panel(self._riders_core_hist, on, product_group_id)
            fleet = {"ok": False, "error": "live_only"}
        else:
            core = self._panel(self._riders_core, on, product_group_id)
            fleet = self._panel(self._fleet, on, product_group_id)
        groups = self.env["gh.product.group"].sudo().search([])
        last_snapshot = self.env["gh.kpi.snapshot"].sudo().search(
            [("company_id", "=", self.env.company.id)], order="period_end desc", limit=1)
        return {
            "as_of": fields.Date.to_string(on),
            "computed_at": fields.Datetime.to_string(fields.Datetime.now()),
            "company": self.env.company.name,
            "product_groups": self._group_payload(groups),
            "product_group_id": product_group_id,
            "last_snapshot": fields.Date.to_string(last_snapshot.period_end) if last_snapshot else False,
            "core": core,
            "fleet": fleet,
            "historic": historic,
            "as_of_options": self._as_of_options(),
            "referrals": self._panel(self._referrals, on, product_group_id),
            "safety": self._panel(self._safety, on, product_group_id) if not historic else {"ok": False, "error": "live_only"},
            "history": self._panel(lambda: self._history(["R01", "R05", "R06"], grain, 26 if grain == "week" else 12)),
            "trends": self._panel(self._riders_trends, on, product_group_id, grain, range_key),
            "checks": self._riders_checks(core, fleet),
            "is_manager": self.env.user.has_group("greenhub_dashboards.group_gh_dashboard_manager"),
        }

    @api.model
    def _riders_snapshot_rows(self, on):
        core = self._riders_core(on, None)
        fleet = self._fleet(on, None)
        rows = [
            ("R01", "", 0.0, core["active_riders"]["value"]),
            ("R02", "", core["women"]["pct"] or 0.0, core["women"]["value"]),
            ("R03", "", core["men"]["pct"] or 0.0, core["men"]["value"]),
            ("R04", "", core["youth"]["pct"] or 0.0, core["youth"]["value"]),
            ("P01", "", 0.0, core["active_contracts"]["value"]),
        ]
        rows += [("R05", f"bucket:{r['key']}", r["pct"] or 0.0, r["count"]) for r in core["gender_age"]]
        rows += [("R08", f"product:{r['group_id'] or UNMAPPED}", r["pct"] or 0.0, r["count"]) for r in core["by_product"]]
        rows += [
            ("R06", "", fleet["unassigned"]["pct"] or 0.0, fleet["unassigned"]["value"]),
            ("R06", "kind:new", 0.0, fleet["unassigned"]["new"]),
            ("R06", "kind:refinancing", 0.0, fleet["unassigned"]["refinancing"]),
        ]
        return rows


class GhLicenceReminder(models.AbstractModel):
    _name = "gh.licence.reminder"
    _description = "Green Hub licence expiry reminders (R18)"

    @api.model
    def _cron_licence_reminders(self):
        """One to-do per rider whose licence ends within the notice window (spec R18).

        Only riders on a running/paused contract; assigned to the rider's responsible
        user; never duplicated while an open reminder exists.
        """
        config = self.env["gh.dashboard.config"]._get_config()
        today = fields.Date.context_today(self)
        limit = today + timedelta(days=config.licence_notice_days)
        contracts = self.env["rider.contract"].sudo().search([("state", "in", ACTIVE_STATES)])
        riders = contracts.mapped("rider_id").filtered(
            lambda r: r.license_end_date and today <= r.license_end_date <= limit and r.license_status != "no_license")
        todo = self.env.ref("mail.mail_activity_data_todo")
        model_id = self.env["ir.model"]._get_id("rider")
        Activity = self.env["mail.activity"].sudo()
        existing = set(Activity.search([("res_model", "=", "rider"), ("res_id", "in", riders.ids),
                                        ("summary", "=like", "Licence expires%")]).mapped("res_id"))
        created = Activity.browse()
        for rider in riders:
            if rider.id in existing:
                continue
            created |= Activity.create({
                "res_model_id": model_id, "res_id": rider.id, "activity_type_id": todo.id,
                "summary": _("Licence expires on %s", rider.license_end_date),
                "date_deadline": rider.license_end_date,
                "user_id": (rider.responsible_user or self.env.user).id,
            })
        return created

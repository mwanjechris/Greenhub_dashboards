from odoo import api, fields, models

VEHICLE_CATEGORIES = [
    ("on_contract", "On contract"),
    ("outright_sold", "Outright sold"),
    ("loan_complete", "Loan complete"),
    ("available", "Available"),
    ("decommissioned", "Decommissioned"),
    ("in_house", "In-house"),
    ("loaner", "Loaner"),
    ("in_repair", "In repair"),
    ("test", "Test bike"),
    ("pending", "Not yet in service"),
    ("other", "Other"),
]

# Fixed colour slot per product group. Colour follows the entity: filtering
# must never repaint the survivors, so the slot is stored, not derived by rank.
COLOR_SLOTS = [
    ("zembo", "Slot 1 (blue)"),
    ("iqube", "Slot 2 (amber, always direct-labelled)"),
    ("niu", "Slot 3 (violet)"),
    ("s4", "Slot 4 (orange)"),
]


class GhProductGroup(models.Model):
    """Product family used to split every KPI (Zembo, iQube, NIU, ...).

    Contracts map through their product, vehicles through their model, so no
    KPI ever matches on a product or model name.
    """

    _name = "gh.product.group"
    _description = "Green Hub product group"
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    color_slot = fields.Selection(COLOR_SLOTS, default="s4", required=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
    product_ids = fields.Many2many(
        "product.product", string="Contract products", context={"active_test": False},
        help="Contracts whose product is in this list belong to this group.",
    )
    vehicle_model_ids = fields.Many2many(
        "fleet.vehicle.model", string="Vehicle models", context={"active_test": False},
        help="Vehicles of these models belong to this group.",
    )

    @api.model
    def _group_maps(self):
        """Return (product_id -> group, model_id -> group, groups)."""
        groups = self.sudo().search([])
        by_product, by_model = {}, {}
        # Archived products and models still sit on live contracts and vehicles,
        # so the mapping must see them.
        for group in groups.with_context(active_test=False):
            for product in group.product_ids:
                by_product.setdefault(product.id, group)
            for model in group.vehicle_model_ids:
                by_model.setdefault(model.id, group)
        return by_product, by_model, groups


class GhVehicleCategoryRule(models.Model):
    """Ordered rules that put each vehicle in exactly one category.

    The first matching rule wins. A rule matches when every condition it sets
    holds: vehicle state in the listed states, at least one of the tags, and,
    if ticked, the vehicle is on an active contract or out as a loaner. Vehicles no rule
    matches land in 'other' and raise a reconciliation warning.
    """

    _name = "gh.vehicle.category.rule"
    _description = "Green Hub vehicle category rule"
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    category = fields.Selection(VEHICLE_CATEGORIES, required=True)
    vehicle_states = fields.Char(
        help="Comma-separated technical vehicle states, e.g. 'contract,rent'. Empty = any state.",
    )
    tag_ids = fields.Many2many(
        "fleet.vehicle.tag", string="Any of these tags", help="Empty = tags are not checked."
    )
    on_active_contract = fields.Boolean(
        string="On a running or paused contract",
        help="Match only vehicles that are the bike on a running or paused rider contract.",
    )
    ongoing_loaner = fields.Boolean(
        string="Currently out as loaner",
        help="Match only vehicles that are the loaner bike on an ongoing loaner tracking record.",
    )

    def _state_list(self):
        self.ensure_one()
        return [s.strip() for s in (self.vehicle_states or "").split(",") if s.strip()]

    @api.model
    def action_suggest_tag_rules(self):
        """One-off setup helper for a Manager: propose tag rules from the tags in use.

        It only creates configuration records, which the Manager reviews and
        edits. KPI code never looks at tag names.
        """
        suggestions = [
            (5, "Test bikes", "test", "test bike"),
            (20, "Decommissioned", "decommissioned", "decomissioned"),
            (21, "Decommissioned", "decommissioned", "decommissioned"),
            (30, "Sold outright (tag)", "outright_sold", "sold outright"),
            (40, "Loan complete", "loan_complete", "loan complete"),
            (50, "In-house", "in_house", "inhouse"),
        ]
        tags = self.env["fleet.vehicle.tag"].sudo().search([])
        created = self.browse()
        for sequence, name, category, needle in suggestions:
            matched = tags.filtered(lambda t: (t.name or "").strip().lower() == needle)
            if matched and not self.search([("category", "=", category), ("tag_ids", "in", matched.ids)], limit=1):
                created |= self.create({"name": name, "sequence": sequence, "category": category,
                                        "tag_ids": [(6, 0, matched.ids)]})
        return created

"""The dashboards' own documentation: one explainer per card, plus the guide page.

One source for both uses. The hover explainer on a card and the Guide menu read
the same entries from ``get_guide``, so they can never disagree. Thresholds are
read from the live settings, so the text always states the rule in force.

Keys: a KPI code (R01, P11, C08, B05 ...), or a named key for a card or control
that has no code in the specification (P22A, LOGS, B_PL, "F:as of" ...).
tests/test_guide.py fails when a card on a dashboard has no entry here.
"""
from odoo import _, api, fields, models


class GhKpiServiceGuide(models.AbstractModel):
    _inherit = "gh.kpi.service"

    # ------------------------------------------------------------------ live settings
    def _guide_settings(self):
        config = self.env["gh.dashboard.config"]._get_config()
        lim = config._band_limits()
        if config.risk_band_basis == "instalments":
            basis = _("multiples of the contract's own weekly instalment")
            bands = [f"{v:g}×" for v in lim]
        else:
            basis = _("fixed amounts in the company currency")
            bands = [f"{v:,.0f}" for v in lim]
        return {
            "youth": config.youth_age_limit,
            "notice": config.licence_notice_days,
            "accident_days": config.accident_window_days,
            "referral_weeks": config.referral_window_weeks,
            "exclude_test": config.exclude_test_vehicles,
            "history_start": fields.Date.to_string(config.history_start),
            "basis": basis,
            "bands": bands,
            "par_1": config.par_1, "par_1n": config.par_1 + 1,
            "par_2": config.par_2, "par_2n": config.par_2 + 1,
            "par_3": config.par_3, "par_3n": config.par_3 + 1,
            "default_scope": dict(config._fields["default_scope"]._description_selection(self.env))[config.default_scope],
            "forecast_weeks": config.forecast_weeks,
            "rate_weeks": config.rate_window_weeks,
            "loss_accounts": ", ".join(config.default_loss_account_ids.mapped("display_name")) or _("not chosen yet"),
            "loan_accounts": ", ".join(config.loan_account_ids.mapped("display_name")) or _("not chosen yet"),
            "interest_accounts": ", ".join(config.loan_interest_account_ids.mapped("display_name")) or _("not chosen yet"),
            "pl_report": config._pl_report().display_name if config._pl_report() else _("Odoo's standard Profit and Loss"),
        }

    # ------------------------------------------------------------------ entries
    def _guide_entries(self, s):
        """Every explainer. ``s`` = the live settings from _guide_settings."""
        E = []

        def add(key, dash, title, what, how, source, click="", note="", code=None):
            E.append({"key": key, "code": code if code is not None else key, "dash": dash, "title": title,
                      "what": what, "how": how, "source": source, "click": click, "note": note})

        # ---------------------------------------------------------- Riders & Customers
        add("R01", "riders", _("Active riders"),
            _("How many different people are riding a Green Hub bike under a live contract."),
            _("Distinct riders who have at least one contract in the state Running or Paused. A rider with two live "
              "contracts is counted once. The line under the figure splits Running and Paused."),
            _("Contracts and their state, in the Green Hub app."),
            _("Opens the list of those riders."),
            _("Paused contracts count as active. The small line in the tile is the trend over the last 12 periods."))
        add("R02", "riders", _("Women"),
            _("How many active riders are women, and their share of all active riders."),
            _("Active riders (R01) whose gender on the rider record is Female. Share = women ÷ active riders."),
            _("Gender on the rider record."),
            _("Opens the women riders."),
            _("A rider with no gender recorded is in neither the Women nor the Men tile. They show as "
              "\"Unknown age or gender\" in the Gender and age table."))
        add("R03", "riders", _("Men"),
            _("How many active riders are men, and their share of all active riders."),
            _("Active riders (R01) whose gender on the rider record is Male. Share = men ÷ active riders."),
            _("Gender on the rider record."),
            _("Opens the men riders."))
        add("R04", "riders", _("Youth"),
            _("How many active riders are young people, the group most funders ask about."),
            _("Active riders younger than %(youth)s on the as-of date. Age is worked out from the date of birth, "
              "so it is right for past dates too.", youth=s["youth"]),
            _("Date of birth on the rider record. The age limit is in Dashboard settings."),
            _("Opens the youth riders."),
            _("A rider with no date of birth cannot be counted as youth. The tile says how many have none."))
        add("R05", "riders", _("Gender and age"),
            _("The active riders split into four groups: men and women, under and over the youth age."),
            _("Each active rider goes into exactly one row. Riders with no gender or no date of birth go into "
              "\"Unknown age or gender\". The rows must add up to Active riders; the tick under the table confirms it."),
            _("Gender and date of birth on the rider record."),
            _("Click a row to open the riders in it."))
        add("R06", "riders", _("Unassigned e-bodas"),
            _("Bikes that are ready but earning nothing because no rider has them."),
            _("Vehicles in the category Available, as a share of the whole fleet. \"New\" = the bike has never had a "
              "contract that started. \"Re-financing\" = it had a contract before and is waiting for the next rider."),
            _("Vehicle state and tags, sorted into categories by Configuration › Vehicle category rules."),
            _("Opens the available vehicles. The two links open the new and the re-financing ones."),
            _("Test bikes are left out of the fleet total when that option is on in Dashboard settings."))
        add("R07", "riders", _("On contract and vehicle distribution"),
            _("Where every bike in the fleet is: with a rider, available, in repair, sold, decommissioned and so on."),
            _("Each vehicle is placed in exactly one category by the vehicle category rules, read in order; the first "
              "rule that matches wins. The table shows product group by category. Every row and column adds up to "
              "the fleet, and the tick under the table confirms it."),
            _("Vehicle state, vehicle tags, active contracts and the loaner-bike log."),
            _("Click a cell to open those vehicles, a row total for the product group, a column total for the category."),
            _("A warning here usually means a bike matches no rule, or a bike was left in the state Active after its "
              "contract was terminated. Fix the bike's state, or add a rule."))
        add("R08", "riders", _("Active riders by product"),
            _("Which product the active riders are on: Zembo, iQube, NIU and any group added later."),
            _("Each active rider is counted under the product group of their most recently started live contract. "
              "Share = riders in the group ÷ active riders. The rows must add up to Active riders."),
            _("The product on the contract, mapped to a group in Configuration › Product groups."),
            _("Click a row to open the contracts."),
            _("A row \"Product not mapped to a group\" means a contract uses a product that no group lists. "
              "Add the product to a group."))
        add("R09", "riders", _("Available by model"),
            _("Which bike models are sitting available."),
            _("The Available vehicles (R06) counted by vehicle model. Share = that model's available bikes ÷ whole fleet."),
            _("Vehicle model on the vehicle record."),
            _("Click a row to open those vehicles."))
        add("R10", "riders", _("Lifetime retention"),
            _("Of the riders Green Hub had at the start of its records, how many are still riding."),
            _("Take the riders who were active at the first week end on or after %(start)s. Lifetime retention = "
              "those still active at the latest week end ÷ that starting group. A rider who upgraded to a new contract "
              "is still retained.", start=s["history_start"]),
            _("Weekly contract snapshots. The start date is \"History start\" in Dashboard settings."),
            _("Opens the retained riders."))
        add("R11", "riders", _("Monthly retention"),
            _("Of the riders active at the end of last month, how many are still active at the end of this one."),
            _("Riders active at both month ends ÷ riders active at the earlier month end. Riders who joined during "
              "the month are not in the starting group, so new sign-ups cannot push the figure up."),
            _("Month-end contract snapshots."),
            _("Opens the retained riders."))
        add("R12", "riders", _("Weekly retention and its trend"),
            _("How well Green Hub keeps its riders from one period to the next, over time."),
            _("For each period: riders active at both ends ÷ riders active at the start. The tile is the plain "
              "average over the selected range; the chart shows each period."),
            _("Weekly or monthly contract snapshots, following the Trend filter."),
            _("Click a point on the chart to open the riders retained in that period."))
        add("R13", "riders", _("Customer growth"),
            _("How the number of active riders moved in each period, and why."),
            _("Opening riders + first-time riders + returning riders − exits = closing riders. First-time = never "
              "active in any earlier period. Returning = was active before, left, and came back. Exits are split into "
              "planned (completed or upgraded), default (repossessed) and other (voluntary return or no reason recorded). "
              "The Check column confirms the sum for every period."),
            _("Contract snapshots at each period end. Exit reasons come from Configuration › Exit types."),
            _("Click a bar or a number to open exactly those riders."),
            _("If many exits fall under \"other\", closure reasons are not being recorded on contracts or terminations."))
        add("R14", "riders", _("Referral sources"),
            _("How new riders heard about Green Hub."),
            _("Contracts that started in the last %(weeks)s weeks, grouped by the source on the rider record. "
              "Share = contracts from that source ÷ all contracts started in the window.", weeks=s["referral_weeks"]),
            _("The rider's Source (the same sources as Odoo marketing). The older \"How did you hear about us\" field "
              "is used when Source is empty. The window is in Dashboard settings."),
            _("Click a row to open the contracts."),
            _("\"Not recorded\" means neither field was filled when the rider was registered."))
        add("R15", "riders", _("Gender and age over time"),
            _("Whether the mix of men, women, youth and older riders is changing."),
            _("The Gender and age split (R05) at each period end, as shares of the active riders at that date. "
              "Age is taken at each date, so a rider moves group on their birthday."),
            _("Stored weekly and monthly snapshots."),
            _("Click a column to open the riders active at that date."),
            _("Kept for the whole portfolio only, so it is hidden when a product filter is on."))
        add("R16", "riders", _("Unassigned e-bodas over time"),
            _("Whether the pile of idle bikes is growing or shrinking."),
            _("The Unassigned count (R06) at each period end, split into new and re-financing."),
            _("Stored snapshots. Past dates use the vehicle's tracked state and today's tags, because Odoo does not "
              "keep a history of tags."),
            _("Click a bar to open the stored figures for that period."),
            _("Kept for the whole fleet only, so it is hidden when a product filter is on."))
        add("R17", "riders", _("Accidents"),
            _("How many accidents were reported recently, and how that compares with the size of the fleet on the road."),
            _("Accident records dated in the last %(days)s days. Rate = accidents ÷ bikes on contract × 100, "
              "that is, accidents per 100 bikes on contract.", days=s["accident_days"]),
            _("Accident records in Fleet. The number of days is in Dashboard settings."),
            _("Opens the accident records."),
            _("There is no split by type of accident because the accident record has no type field."))
        add("R18", "riders", _("Licences expiring"),
            _("Which active riders are about to ride without a valid licence."),
            _("Active riders whose licence end date falls within the next %(notice)s days. The line under the figure "
              "counts riders whose licence already expired, and riders with no licence or no end date recorded. "
              "The table lists who is expiring, soonest first.", notice=s["notice"]),
            _("Licence status and licence end date on the rider record. The notice period is in Dashboard settings."),
            _("Opens the riders. Click a row in the table to open that rider."),
            _("Every day Odoo creates one to-do for the rider's responsible user when a licence enters the notice "
              "period. Learner's permits are not recorded in Odoo, so a learner shows as valid or as no licence."))

        # ---------------------------------------------------------- Portfolio & Credit Risk
        add("P01", "portfolio", _("Active contracts"),
            _("The size of the live lending book: how many contracts Green Hub is collecting on."),
            _("Contracts in the state Running or Paused. This is contracts, not people, so it can be higher than "
              "Active riders when a rider holds two contracts."),
            _("Contracts and their state."),
            _("Opens the active contracts."))
        add("P02", "portfolio", _("Total arrears"),
            _("How much money riders owe that is already late."),
            _("For each active contract: instalments whose due date has passed and that are unpaid or part-paid, plus "
              "unpaid late fees. Added up across all active contracts. Instalments not yet due are left out, and a "
              "rider's credit is never used to reduce another rider's arrears. Late fees are shown separately "
              "under the figure."),
            _("\"Total outstanding\" on each contract, which the Green Hub app keeps up to date from the payment schedule "
              "and the late-fee invoices."),
            _("Opens the contracts that have arrears."))
        add("P03", "portfolio", _("Average arrears per contract"),
            _("How late the typical contract is, in money."),
            _("Total arrears (P02) ÷ Active contracts (P01). Contracts with no arrears are included in the count."),
            _("Same as Total arrears."))
        add("P04", "portfolio", _("Arrears in default"),
            _("How much of the late money sits on contracts that are already in default."),
            _("Total arrears restricted to the contracts counted as in default (see Current default rate)."),
            _("Same as Total arrears."),
            _("Opens the contracts in default."),
            _("Shown inside the Default position block, not as its own tile."))
        add("P05", "portfolio", _("Total rider credit"),
            _("Money riders have paid ahead of their schedule."),
            _("For each active contract, the payments received and not yet matched to an instalment, when positive. "
              "Added up. It is not subtracted from arrears: one rider being ahead does not cancel another being behind."),
            _("\"Unreconciled payment\" on each contract."),
            _("Opens the contracts holding credit."))
        add("P06", "portfolio", _("Ahead and on track"),
            _("Contracts with nothing to worry about."),
            _("Active contracts in the risk categories Ahead and On track, and their share of all active contracts."),
            _("The risk category of each contract. See Portfolio risk distribution (P11) for the rules."),
            _("Opens those contracts."))
        add("P07", "portfolio", _("Behind"),
            _("Contracts that are late but not yet critical."),
            _("Active contracts in the risk categories No risk, Low risk, At risk and High risk."),
            _("The risk category of each contract (P11)."),
            _("Opens those contracts."))
        add("P08", "portfolio", _("In default"),
            _("Contracts that have crossed the default line."),
            _("Active contracts in the risk category Default. In the Green Hub app a contract goes into default when "
              "its arrears reach three times its instalment."),
            _("Payment status on the contract, and the definition of \"in default\" chosen in Dashboard settings."),
            _("Opens those contracts."))
        add("P09", "portfolio", _("Critical and default"),
            _("The contracts most likely to be lost: the ones to act on first."),
            _("Active contracts in the risk categories Critical and Default together."),
            _("The risk category of each contract (P11)."),
            _("Opens those contracts."))
        add("P10", "portfolio", _("Perfect payment history"),
            _("How many live contracts have never been charged a late fee."),
            _("Active contracts with no late fee ever: no penalty on any instalment and no late fees charged or paid. "
              "Share = those ÷ active contracts."),
            _("Penalty dates and penalty invoices on the payment schedule, and the late-fee totals on the contract."),
            _("Opens those contracts."))
        add("P11", "portfolio", _("Portfolio risk distribution"),
            _("Every active contract sorted into eight levels of risk, from Ahead to Default."),
            _("Read in this order. Default: the contract is in default. Ahead: payment status is Ahead. On track: no "
              "arrears, or payment status is On track. Otherwise the size of the arrears decides, measured in "
              "%(basis)s: On track up to %(b0)s, No risk up to %(b1)s, Low risk up to %(b2)s, At risk up to %(b3)s, "
              "High risk up to %(b4)s, Critical above that. The bar and table must add up to Active contracts.",
              basis=s["basis"], b0=s["bands"][0], b1=s["bands"][1], b2=s["bands"][2], b3=s["bands"][3], b4=s["bands"][4]),
            _("Payment status and arrears on each contract. The limits are in Dashboard settings."),
            _("Click a segment or a row to open the contracts in that category."))
        add("P12", "portfolio", _("Portfolio at risk (PAR)"),
            _("How long contracts have been late, which is the standard way lenders measure a loan book."),
            _("Days past due = days since the due date of the oldest instalment that is still unpaid. "
              "PAR0 = not late. PAR7 = 1 to %(p1)s days. PAR14 = %(p1n)s to %(p2)s. PAR21 = %(p2n)s to %(p3)s. "
              "PAR28 = %(p3n)s days or more. The table also shows the arrears held in each bucket. The buckets "
              "must add up to Active contracts.",
              p1=s["par_1"], p1n=s["par_1n"], p2=s["par_2"], p2n=s["par_2n"], p3=s["par_3"], p3n=s["par_3n"]),
            _("Due dates and states on the payment schedule. The day limits are in Dashboard settings."),
            _("Click a segment or a row to open the contracts in that bucket."),
            _("PAR looks at time; the risk distribution looks at amount. A contract can be a few days late on a "
              "large amount, or long overdue on a small one."))
        add("P13", "portfolio", _("Current default rate"),
            _("What share of the lending book is in default right now."),
            _("Contracts in default ÷ reporting portfolio. The reporting portfolio is the active contracts plus the "
              "contracts counted as in default. Definition of \"in default\" in force: %(scope)s.", scope=s["default_scope"]),
            _("Payment status, the default-tracking log and written-off instalments. The definition is chosen in "
              "Dashboard settings."),
            _("Opens the contracts in default."))
        add("P14", "portfolio", _("Default losses, year to date"),
            _("Money actually written off this year because riders defaulted. A loss, not arrears."),
            _("The posted journal entries on the write-off account(s) from 1 January to the as-of date. "
              "Account(s) in use: %(accounts)s.", accounts=s["loss_accounts"]),
            _("Odoo Accounting. The account is chosen in Dashboard settings, so the figure always equals the "
              "General Ledger."),
            _("Opens the journal items. \"GL\" opens Odoo's General Ledger for the same dates."))
        add("P15", "portfolio", _("Average monthly default loss"),
            _("The typical loss per month so far this year."),
            _("Default losses year to date (P14) ÷ months elapsed in the year, counted in days so a part month "
              "counts as a part."),
            _("Same as Default losses."))
        add("P16", "portfolio", _("Monthly default losses"),
            _("How much was written off in each month of the year."),
            _("Posted journal entries on the write-off account(s), month by month."),
            _("Odoo Accounting."),
            _("Click a bar to open that month's journal items."),
            _("This panel is also the default-loss trend (P19 in the specification)."))
        add("P17", "portfolio", _("Default loss against revenue"),
            _("How big the losses are compared with what the business earned in the same month."),
            _("That month's default loss ÷ that month's Revenue."),
            _("Loss from the write-off account(s); Revenue is the Revenue line of Odoo's Profit and Loss."),
            _("Opens Odoo's Profit and Loss for that month."))
        add("P18", "portfolio", _("Default rate trend"),
            _("Whether defaults are speeding up or easing."),
            _("Two series per month: contracts that entered default during the month, and contracts in default at "
              "the month end."),
            _("New defaults from the default-tracking log; contracts in default from stored snapshots."),
            _("Click a point to open the contracts."))
        add("P20", "portfolio", _("Repossession to refinancing"),
            _("How fast a repossessed bike gets back on the road with a new rider."),
            _("Contracts that ended in the selected year because of repossession or default. For each bike, the days "
              "from the end of that contract to the start of the next contract on the same bike. The panel shows the "
              "average, the median and the bikes still waiting."),
            _("Contract end and termination dates, and Configuration › Exit types (which decides what counts as a "
              "repossession)."),
            _("Opens the contracts, the refinanced ones, or the bikes still waiting."),
            _("Empty until exit types are set up and closure reasons are recorded on contracts or terminations."))
        add("P21", "portfolio", _("Arrears recovery"),
            _("How much of the money that was late at the start of the month was collected during it."),
            _("Opening arrears = arrears at the previous month end. Recovered = instalment money received in the month "
              "from the contracts that had arrears at the opening, never more than each contract's opening arrears. "
              "Recovery rate = recovered ÷ opening arrears."),
            _("Month-end contract snapshots recorded at the time, and the payment logs."),
            _("Click a cell to open the contracts or receipts behind it."),
            _("Needs two recorded month ends. Earlier months are not rebuilt (see Total arrears over time)."))
        add("P22A", "portfolio", _("Total arrears over time"),
            _("Whether the late money is growing or shrinking."),
            _("Total arrears (P02) at each period end."),
            _("Stored snapshots."),
            _("Click a point to open the contracts at that date."),
            _("Only snapshots recorded at the time (the weekly snapshot, or Snapshot now) are shown, so the chart "
              "starts at the first recorded week. Earlier weeks are not rebuilt: Odoo keeps only today's instalment "
              "states, and some payments are entered in Odoo without an app receipt, so past arrears cannot be "
              "rebuilt exactly."), code="P22")
        add("P22B", "portfolio", _("Average arrears per active contract over time"),
            _("Whether the typical contract is getting later or catching up."),
            _("Average arrears per contract (P03) at each period end. A separate chart from total arrears on purpose: "
              "the two are in very different sizes and would mislead on one axis."),
            _("Stored snapshots."),
            _("Click a point to open the contracts at that date."), code="P22")
        add("P22C", "portfolio", _("Risk distribution over time"),
            _("Whether the book is drifting towards safer or riskier categories."),
            _("The eight risk categories (P11) as shares of the active contracts at each period end."),
            _("Stored contract snapshots."),
            _("Click a column to open the contracts at that date."), code="P22")

        # ---------------------------------------------------------- Collections & Payments
        add("C01", "collections", _("Lease collections"),
            _("Cash received from riders for lease instalments in the period."),
            _("Successful incoming mobile-money receipts in the period that fall in the category Lease. The app labels "
              "every instalment payment LEASE, so late fees paid by riders are inside this figure; the line under it "
              "says how much, from Odoo: the part of each receipt's Odoo payment that settled a penalty (late-fee) "
              "invoice. Deposits are a separate category and are not included."),
            _("Payment logs from the Green Hub app, sorted by Configuration › Payment category rules; late fees from "
              "Odoo's reconciliations of penalty invoices with those receipts' payments."),
            _("Opens the lease receipts. The late-fee figure opens the Odoo reconciliations behind it."),
            _("This is cash received. It is not revenue: revenue is on Budget & Performance and comes from Accounting."))
        add("C02", "collections", _("Lease instalments due"),
            _("What riders were supposed to pay on lease contracts in the period."),
            _("The instalment amounts on lease-to-own contracts whose due date falls in the period. Cancelled "
              "instalments are left out."),
            _("The payment schedule on each contract."),
            _("Opens the instalments."))
        add("C03", "collections", _("Collection progress"),
            _("How the cash coming in compares with what fell due."),
            _("Lease collections (C01) ÷ Lease instalments due (C02). It is a cash ratio: money received in the period "
              "may be paying off older instalments, so it can pass 100. The line under the figure also gives the share "
              "of the month that has gone by, and the share of the instalments due in the period that are fully paid."),
            _("Payment logs and the payment schedule."),
            _("Opens the lease receipts. The link opens the instalments paid."))
        add("C04", "collections", _("Cash collected by category"),
            _("All the cash received from riders, by what it was for."),
            _("Every successful incoming receipt in the period is put in exactly one category: lease, rental, deposit, "
              "battery swap, late fee or spare parts. Failed and outgoing transactions are left out. The categories "
              "must add up to the total."),
            _("Payment logs from the Green Hub app, sorted by Configuration › Payment category rules."),
            _("Click a row to open its receipts. An \"of which late fees\" line opens the Odoo reconciliations behind it."),
            _("An \"of which late fees\" line is part of the row above it, not an extra category: late fees paid inside "
              "lease or rental receipts, from Odoo. Late fees written off (not cash) are not counted. A row \"Other\" "
              "with a warning means some receipts matched no rule. Add a rule for them."))
        add("C05", "collections", _("Collections target"),
            _("What Green Hub planned to collect in the period, by category."),
            _("The target lines for the period from the approved operational target version."),
            _("Configuration › Operational target versions. Targets can be imported from a spreadsheet."),
            _("Click a target to open its lines."),
            _("Shows a dash when there is no approved target version covering today."))
        add("C06", "collections", _("Collections against target"),
            _("How much of the period's target has been collected so far."),
            _("Total cash collected ÷ the full target for the period."),
            _("Payment logs and the approved target version."),
            _("Opens the target lines."))
        add("C07", "collections", _("Variance to pro-rata target"),
            _("Whether collections are ahead of or behind where they should be at this point in the month."),
            _("Pro-rata target = the month's target × days elapsed ÷ days in the month. Variance = cash collected − "
              "pro-rata target. Positive is favourable."),
            _("Payment logs and the approved target version."),
            _("Opens the receipts."))
        add("C08", "collections", _("Active-contract collection rate"),
            _("Of what the live contracts were due to pay last month, how much they paid."),
            _("For the last full month: instalment money received (lease and rental) ÷ instalments due, for the "
              "contracts that were active at that month end."),
            _("Payment logs, the payment schedule and the month-end snapshot."),
            _("Opens the contracts in the rate. The links open the receipts and the instalments due."),
            _("Not capped at 100: riders catching up on arrears can push it above."))
        add("C09", "collections", _("Entire-fleet collection rate"),
            _("What the whole fleet earned against what it could have earned, idle bikes included."),
            _("The same cash as C08 ÷ (instalments due + what the available bikes would have owed). An available bike "
              "is counted at the standard weekly instalment of its product group for the weeks in the month."),
            _("As C08, plus the available vehicles and the standard instalment in Configuration › Product groups."),
            _("Opens the contracts in the rate. The link opens the available bikes."),
            _("The gap between C08 and C09 is the cost of idle bikes."))
        add("C10", "collections", _("Collection rates over time"),
            _("Whether riders are paying better or worse, period by period."),
            _("The active-contract rate (C08) and the entire-fleet rate (C09) for each week or month. The dotted line "
              "is 100; the rates are not capped."),
            _("Stored snapshots."),
            _("Click a point to open that period."))
        add("C11", "collections", _("Monthly collections against amount due"),
            _("Month by month, cash received for instalments next to what fell due."),
            _("Bar = lease and rental receipts in the month. Tick = instalments due in the month. Label = bar ÷ tick."),
            _("Payment logs and the payment schedule."),
            _("Click a bar to open that month's receipts."))
        add("C12", "collections", _("Collections by bike model"),
            _("Which products bring in the cash."),
            _("Last full month's instalment receipts by product group, and each group's share of the total."),
            _("Payment logs, with the product taken from the contract on the receipt."),
            _("Click a row to open the receipts."),
            _("Grouped by product group (Zembo, iQube, NIU), which is what the specification calls bike model."))
        add("C13", "collections", _("Collection performance by model"),
            _("Which products' riders pay best."),
            _("For each product group last month: instalment receipts ÷ instalments due."),
            _("Payment logs and the payment schedule."),
            _("Click Due to open the instalments."))
        add("C14", "collections", _("Defaults and losses"),
            _("The headline default figures, repeated here so collections can be read alongside them."),
            _("The same figures as on Portfolio & Credit Risk: current default rate, arrears in default, losses year to "
              "date, and last month's loss against revenue. One calculation feeds both dashboards."),
            _("See P13, P04, P14 and P17."),
            _("Each figure opens its records."))
        add("C15", "collections", _("Collections against lender repayments"),
            _("Whether rider payments cover what Green Hub pays its lenders."),
            _("For the last full month: instalment cash collected, next to principal repaid and interest paid. "
              "Principal = debits on the loan accounts (%(loans)s). Interest = debits on the lender interest "
              "accounts (%(interest)s).", loans=s["loan_accounts"], interest=s["interest_accounts"]),
            _("Payment logs for the cash; Odoo Accounting for the repayments. Accounts are chosen in Dashboard settings."),
            _("Each figure opens its receipts or journal items."),
            _("These are repayments actually posted, not a forward schedule: Green Hub does not use Odoo's Loans app."))
        add("C16", "collections", _("Debt-service cash coverage"),
            _("How many times over the instalment cash covers the lender repayments."),
            _("Instalment cash collected ÷ (principal repaid + interest paid), last full month."),
            _("Same as C15."),
            "",
            _("A cash coverage figure. It is not the DSCR a lender calculates from profit."))
        add("C17", "collections", _("Cash collection forecast"),
            _("How much cash to expect over the coming weeks."),
            _("Contractual = the open instalments falling due in each of the next %(weeks)s weeks on active contracts. "
              "Risk-adjusted = each instalment × the share that contracts in the same risk category actually paid of "
              "what they were due over the last %(rate)s weeks.", weeks=s["forecast_weeks"], rate=s["rate_weeks"]),
            _("The payment schedule, each contract's risk category and stored weekly snapshots."),
            _("Click a bar to open the instalments due that week."),
            _("A risk category with no history yet is counted in full, and the panel says so."))
        add("LOGS", "collections", _("Green Hub payment logs against Odoo payments"),
            _("Proof that the cash on this dashboard is the same cash finance sees in Accounting."),
            _("Left: successful incoming receipts logged by the Green Hub app. Right: posted customer payments in Odoo "
              "for the same dates. A pair is matched when both carry the same payment reference. \"Only on one side\" "
              "lists what has no partner. The difference should be zero."),
            _("Payment logs and Odoo customer payments."),
            _("Every number opens its records."),
            _("A payment dated a day apart from its log can fall on the other side of a period edge."), code="Odoo")

        # ---------------------------------------------------------- Budget & Performance
        add("B01", "budget", _("Importing targets"),
            _("How the operational targets get into Odoo."),
            _("A manager imports a spreadsheet of targets into a target version. The import refuses unknown KPI codes, "
              "bad periods and duplicate rows, and warns about missing months."),
            _("Configuration › Import targets. The wizard offers a template to download."),
            _("\"Import targets\" opens the wizard (managers only)."))
        add("B02", "budget", _("Budgets and target versions"),
            _("Which budget and which set of targets the dashboard is comparing against."),
            _("Two kinds of plan. P&L budgets are Odoo's own report budgets, kept by finance in Accounting. "
              "Operational targets (riders, fleet, collections, default loss) are kept in target versions here. "
              "An approved version is locked: it cannot be edited or deleted, only replaced by a revision."),
            _("Accounting › Reporting › Profit and Loss › Budget, and Configuration › Operational target versions."),
            _("Click a budget to open Odoo's P&L with it; click a version to open it."))
        add("B03", "budget", _("Revenue"),
            _("What the business earned in the period, against budget."),
            _("The Revenue line of the profit and loss report, exactly as Odoo computes it, next to the same line of "
              "the selected budget. Variance = (actual − budget) ÷ budget. The filter Revenue › Excl. principal takes "
              "the lease-principal accounts (Dashboard settings) out of Revenue and of every line built on it; an "
              "amber label then says the figures differ from Odoo's P&L by design. The default is exactly Odoo's."),
            _("Odoo Accounting: %(report)s.", report=s["pl_report"]),
            _("Opens Odoo's own audit of the figure (without the principal accounts in the Excl. principal view). "
              "\"P&L\" opens the report for the same dates."),
            _("Revenue is whatever Accounting books to income accounts: lease principal and deposits are included when "
              "they are booked as income. Use Excl. principal to see revenue without the principal."))
        add("B04", "budget", _("Gross profit"),
            _("What is left of revenue after the direct costs of earning it."),
            _("The Gross Profit line of the profit and loss report (revenue less cost of revenue), against the same "
              "line of the selected budget."),
            _("Odoo Accounting: %(report)s.", report=s["pl_report"]),
            _("Opens Odoo's own audit of the figure."))
        add("B05", "budget", _("EBITDA"),
            _("Operating result before interest, tax, depreciation and amortisation: the usual measure of whether the "
              "operation itself makes money."),
            _("Operating income plus the depreciation accounts added back, as a line of the report "
              "\"GreenHub P&L (EBITDA)\". If that report is not set up, the tile shows Odoo's Operating Income instead "
              "and says so."),
            _("Odoo Accounting. The report and the add-back accounts are in Dashboard settings."),
            _("Opens Odoo's own audit of the figure."))
        add("B11", "budget", _("Net profit"),
            _("The bottom line for the period, against budget."),
            _("The Net Profit line of the profit and loss report against the same line of the selected budget."),
            _("Odoo Accounting: %(report)s.", report=s["pl_report"]),
            _("Opens Odoo's own audit of the figure."),
            _("The specification asked for financing costs here. Odoo's P&L has no financing line (interest sits in "
              "other expenses), so Net profit is shown instead."))
        add("B_PL", "budget", _("Profit and loss: actual against budget"),
            _("The full profit and loss, line by line, for the month and the selected period."),
            _("Every line, sign and total is read from Odoo's report engine; the dashboard does no accounting of its "
              "own. Variance = actual − budget; variance share = that ÷ budget. For costs, spending less than budget "
              "is favourable. \"no plan\" = no budget on that line; \"no actuals\" = a budget but nothing posted."),
            _("Odoo Accounting: %(report)s, with the budget picked in the filter bar.", report=s["pl_report"]),
            _("An actual opens Odoo's audit of that cell. A budget opens Odoo's P&L with the budget column."),
            _("In the default view this table and Accounting › Reporting must match; if they ever differ, treat it as a "
              "bug and report it. In the Excl. principal view they differ by the principal, by design."), code="B03–B05")
        add("B03M", "budget", _("Revenue: actual against budget by month"),
            _("How revenue has tracked the budget through the year."),
            _("The Revenue line for each month (bar) with that month's budget (dashed mark)."),
            _("Odoo's profit and loss, run once per month."),
            _("Click a bar to open Odoo's audit of that month's revenue."), code="B03")
        add("B06", "budget", _("Cash collections against target"),
            _("Cash received from riders in the period, against the plan."),
            _("All successful receipts in the period, next to the collections targets (all categories) for the same "
              "period."),
            _("Payment logs and the selected target version."),
            _("Opens the receipts; the plan figure opens the target lines."))
        add("B07", "budget", _("Active rider portfolio against plan"),
            _("The size of the live book at the end of the period shown, against where the plan said it would be."),
            _("Active contracts at the end of the period (today when the period runs to today, else the recorded "
              "month-end snapshot), next to the target in force on that date. A point-in-time figure: it is never "
              "added up across months."),
            _("Contracts, month-end contract snapshots and the selected target version."),
            _("Opens the active contracts."))
        add("B08", "budget", _("New rider onboarding against plan"),
            _("How many brand-new riders joined in the period, against the plan."),
            _("Riders whose first-ever contract started in the period (from contract start dates, so it is exact for "
              "any period). Returning riders are shown in the note, with the count from Customer growth (R13), and "
              "are not counted against the plan."),
            _("Contract start dates, weekly contract snapshots and the selected target version."),
            _("Opens the first-time riders."))
        add("B09", "budget", _("Fleet deployment against plan"),
            _("How many bikes are out with riders, against the plan."),
            _("Bikes on an active contract at the end of the period (today: the vehicle distribution's On contract; a "
              "past month: the recorded month-end snapshot), in total on the tile and by product group in the table, "
              "next to the target in force on that date."),
            _("The vehicle distribution (R07), month-end contract snapshots and the selected target version."),
            _("Opens the vehicles on contract."))
        add("B10", "budget", _("Default loss against budget"),
            _("Money written off in the period, against what was allowed for."),
            _("Posted journal entries on the write-off account(s) in the period, next to the target. Lower than plan "
              "is favourable. This is the loss, not the arrears at the time of default."),
            _("Odoo Accounting and the selected target version."),
            _("Opens the journal items. \"GL\" opens the General Ledger."))
        add("B_OPS", "budget", _("Operational KPIs against plan"),
            _("The non-financial targets in one table."),
            _("Each row is one operational KPI with its actual, its plan and whether it is favourable. \"End-date\" rows "
              "are a count on the day; \"sum\" rows add up over the period."),
            _("See B06 to B10."),
            _("Actuals open their records; plans open the target lines."), code="B06–B10")
        add("B12", "budget", _("Year-end outlook"),
            _("Where the year is likely to finish."),
            _("Actual year to date + the forecast budget for the remaining months. Shown next to the approved budget "
              "for the full year, and deliberately drawn differently so a forecast is never mistaken for the budget."),
            _("Odoo's profit and loss. The forecast budget is an Odoo report budget picked in Dashboard settings."),
            _("Each figure opens Odoo's P&L for its dates."),
            _("Uses the EBITDA line, or Operating Income when the EBITDA report is not set up."))
        add("B_AN", "budget", _("Analytic budgets"),
            _("Finance's project and cost-centre budgets, as kept in Odoo's Budgets app."),
            _("Every analytic budget overlapping the period, with planned, theoretical (what should have been used by "
              "now) and achieved amounts exactly as Odoo computes them."),
            _("Accounting › Budgets."),
            _("A budget opens in Odoo; a line opens the entries behind its achieved amount; \"Report\" opens Odoo's "
              "budget analysis."), code="Odoo")

        # ---------------------------------------------------------- filters and controls
        add("F:as of", "controls", _("As of"),
            _("The date the status figures are for."),
            _("\"Today (live)\" reads the current records. A past week end reads the snapshot stored for that Sunday."),
            _("Stored weekly snapshots."),
            "",
            _("Fleet, licence and accident panels exist only live, so they are hidden for a past date."), code="")
        add("F:trend", "controls", _("Trend"),
            _("Whether the charts step by week or by month."),
            _("Weeks run Monday to Sunday. Months are calendar months."),
            _("Stored weekly and month-end snapshots."), code="")
        add("F:range", "controls", _("Range"),
            _("How far back the charts go."),
            _("26 weeks (or 6 months), year to date, or 12 months."),
            _("Stored snapshots; nothing earlier than the history start date exists."), code="")
        add("F:product", "controls", _("Product"),
            _("Restricts the whole dashboard to one product group."),
            _("Riders and contracts follow the product on the contract; vehicles follow the vehicle model."),
            _("Configuration › Product groups."),
            "",
            _("Colours follow the product: filtering never repaints the ones that remain."), code="")
        add("F:year", "controls", _("Year"),
            _("The year for the default-loss and repossession panels."),
            _("Losses run from 1 January of the chosen year to the as-of date, or to 31 December for a past year."),
            _("Odoo Accounting."), code="")
        add("F:period", "controls", _("Period"),
            _("The dates the figures cover."),
            _("On Collections: this month to date, last month, or custom dates. On Budget: the month, the quarter to "
              "date, or the year to date, each ending at the month picked under Through."),
            "", code="")
        add("F:through", "controls", _("Through"),
            _("The last month included."),
            _("Defaults to the last completed month, so a half-finished month does not look like a shortfall."),
            "", code="")
        add("F:revenue", "controls", _("Revenue"),
            _("Which revenue the Budget dashboard shows."),
            _("As Odoo P&L (default): exactly Odoo's profit and loss. Excl. principal: the lease-principal accounts "
              "(Dashboard settings) are taken out of Revenue and of every line built on it (gross profit, operating "
              "income, EBITDA, net profit); costs are unchanged. An amber label marks this view, because it then "
              "differs from Odoo's P&L by design."),
            "", code="")
        add("F:currency", "controls", _("Currency"),
            _("Shows the Collections amounts in the lender currency."),
            _("Converted with Odoo's exchange rate at the end of the period."),
            _("Currency rates in Accounting. The lender currency is in Dashboard settings."), code="")
        add("F:budget (odoo)", "controls", _("Budget (Odoo)"),
            _("Which Odoo report budget fills the budget columns."),
            _("The budgets finance keeps on the Profit and Loss report."),
            _("Accounting › Reporting › Profit and Loss › Budget."), code="")
        add("F:targets", "controls", _("Targets"),
            _("Which operational target version the plan figures come from."),
            _("By default the approved version in force today."),
            _("Configuration › Operational target versions."), code="")
        add("F:checks", "controls", _("Reconciliation checks"),
            _("The dashboard checking its own arithmetic."),
            _("Each check confirms that figures which must agree do agree: the gender and age rows add up to active "
              "riders, vehicle categories add up to the fleet, risk and PAR each add up to active contracts, payment "
              "categories add up to total receipts. Click to see every check and what it found."),
            _("Computed on each load."),
            "",
            _("A failed check almost always points at data to tidy up or a rule to add, not at a wrong formula."), code="")
        add("F:codes", "controls", _("KPI codes"),
            _("Shows the reference code of every card."),
            _("The codes are the ones in the client specification (R = riders, P = portfolio, C = collections, "
              "B = budget). Use them to look a card up in the Guide."),
            "", code="")
        return E

    # ------------------------------------------------------------------ guide page
    def _guide_dashboards(self):
        return [
            {"key": "riders", "name": _("Riders & Customers"), "action": "Greenhub_dashboards.action_gh_riders_dashboard",
             "intro": _("Who Green Hub's riders are, how many it keeps, how the fleet is deployed and whether riders are "
                        "licensed and safe. Counts people and bikes, not money.")},
            {"key": "portfolio", "name": _("Portfolio & Credit Risk"),
             "action": "Greenhub_dashboards.action_gh_portfolio_dashboard",
             "intro": _("The health of the lending book: how much is late, how late, how risky each contract is, what has "
                        "defaulted and what was lost.")},
            {"key": "collections", "name": _("Collections & Payments"),
             "action": "Greenhub_dashboards.action_gh_collections_dashboard",
             "intro": _("Cash actually received from riders: by category, against what fell due, against target, against "
                        "lender repayments, and what to expect next.")},
            {"key": "budget", "name": _("Budget & Performance"), "action": "Greenhub_dashboards.action_gh_budget_dashboard",
             "intro": _("Actuals against plan: the profit and loss straight from Odoo Accounting, the operational targets, "
                        "and the year-end outlook.")},
            {"key": "controls", "name": _("Filters and controls"), "action": False,
             "intro": _("The bar under each dashboard title. A filter changes every card on that dashboard.")},
        ]

    def _guide_sections(self, s):
        return [
            {"key": "start", "title": _("Start here"), "items": [
                {"h": _("What these dashboards are"),
                 "p": _("Four screens that replace Green Hub's spreadsheet dashboards. Every number is worked out by "
                        "Odoo from the live records each time the page opens, so there is nothing to refresh, paste or "
                        "re-key.")},
                {"h": _("Three things every card does"),
                 "p": _("Hover over a card (or the title of a larger panel) for a short explanation. Click a figure to "
                        "open the exact records it was counted from. Turn on \"Show KPI codes\" to see each card's "
                        "reference code, then look it up on this page.")},
                {"h": _("Live figures and history"),
                 "p": _("Status figures (how many riders, how much arrears) are live. Trend charts come from snapshots: "
                        "a copy of the key figures stored every Sunday night and on the last day of each month. The "
                        "header of each dashboard shows when it was read and the date of the last snapshot.")},
            ]},
            {"key": "reading", "title": _("Reading the figures"), "items": [
                {"h": _("A dash instead of a number"),
                 "p": _("A dash means the figure cannot be worked out, usually because there is nothing to divide by or a "
                        "setting is missing. It never means zero.")},
                {"h": _("Hatched \"Awaiting\" boxes"),
                 "p": _("The panel is built but its data does not exist yet, for example no history has been stored or no "
                        "budget has been entered. The box says what to load.")},
                {"h": _("A red box on one panel"),
                 "p": _("That panel failed and says why. The rest of the dashboard is unaffected.")},
                {"h": _("Favourable and unfavourable"),
                 "p": _("Status always shows a symbol and a word, never colour alone. For income, above plan is "
                        "favourable. For costs and losses, below plan is favourable.")},
                {"h": _("Shares always say of what"),
                 "p": _("Every share names its denominator, for example \"of 197 active riders\" or \"of 65 fleet\".")},
                {"h": _("Reconciliation checks"),
                 "p": _("The right of the filter bar shows whether the dashboard's own cross-checks pass. Click it for the "
                        "list. A failing check usually means records to tidy up, for example a bike that matches no "
                        "category rule.")},
            ]},
            {"key": "money", "title": _("Where the money figures come from"), "items": [
                {"h": _("Accounting figures are Odoo's, not ours"),
                 "p": _("Revenue, gross profit, EBITDA, net profit, budgets, default losses and lender repayments are read "
                        "from Odoo Accounting. The dashboard does no accounting arithmetic of its own, so it cannot "
                        "disagree with finance's reports. Profit and loss report in use: %(report)s.", report=s["pl_report"])},
                {"h": _("Cash collected is not revenue"),
                 "p": _("Collections & Payments counts cash received from riders, from the Green Hub app's payment logs. "
                        "Cash collected and revenue differ: revenue is what Accounting books to income accounts for the "
                        "period (on Budget & Performance, with an optional view without lease principal). The panel \"Green Hub payment logs against Odoo payments\" proves the logs match the "
                        "payments posted in Accounting.")},
                {"h": _("Arrears are not losses"),
                 "p": _("Arrears is money that is late but still owed. A loss is money written off in the books. They are "
                        "reported separately and never added together.")},
                {"h": _("Accounts in use"),
                 "p": _("Default losses: %(loss)s. Loans: %(loans)s. Lender interest: %(interest)s. A manager changes "
                        "these in Configuration › Dashboard settings.",
                        loss=s["loss_accounts"], loans=s["loan_accounts"], interest=s["interest_accounts"])},
            ]},
            {"key": "history", "title": _("History and snapshots"), "items": [
                {"h": _("When snapshots are taken"),
                 "p": _("Every Sunday night for the week (weeks run Monday to Sunday) and on the last day of each month. "
                        "A closed period is frozen: it does not change when records are edited later.")},
                {"h": _("History before the dashboards existed"),
                 "p": _("Configuration › History backfill rebuilds past weeks from %(start)s using Odoo's record of "
                        "changes on each contract and vehicle. It also produces a file to compare with Green Hub's own "
                        "weekly sheets.", start=s["history_start"])},
                {"h": _("What the rebuilt history covers"),
                 "p": _("A contract's past status is the last recorded change on or before that date, so rider counts, "
                        "growth, retention and defaults are rebuilt. Past vehicle categories use today's tags. Past "
                        "arrears are NOT rebuilt: Odoo keeps only today's instalment states and some payments are entered "
                        "in Odoo without an app receipt, so they cannot be rebuilt exactly. Arrears, risk and PAR history, "
                        "arrears recovery and past \"as of\" weeks on Portfolio use only snapshots recorded at the time.")},
            ]},
            {"key": "setup", "title": _("Setting up and keeping it right (managers)"), "items": [
                {"h": _("Dashboard settings"),
                 "p": _("Every threshold: youth age, licence notice days, risk bands, PAR day limits, what counts as in "
                        "default, forecast length, and the accounting report, budgets and accounts to read.")},
                {"h": _("Product groups"),
                 "p": _("Which contract products and vehicle models make up Zembo, iQube, NIU and any new group, and each "
                        "group's standard weekly instalment.")},
                {"h": _("Vehicle category rules"),
                 "p": _("Ordered rules that put each bike in one category from its state and tags. The first matching "
                        "rule wins.")},
                {"h": _("Payment category rules"),
                 "p": _("Ordered rules that put each receipt in one category: lease, rental, deposit, battery swap, late "
                        "fee or spare parts.")},
                {"h": _("Exit types"),
                 "p": _("Which closure reasons count as completion, upgrade, voluntary return or repossession. Drives the "
                        "exit split in Customer growth and the repossession panel.")},
                {"h": _("Operational target versions and Import targets"),
                 "p": _("The plan for riders, fleet, collections and default loss. Approving a version locks it.")},
                {"h": _("KPI snapshots and History backfill"),
                 "p": _("The stored history, and the tool that rebuilds it.")},
                {"h": _("Who can see what"),
                 "p": _("Dashboard User can open the four dashboards and this guide. Dashboard Manager can also open "
                        "Configuration.")},
            ]},
            {"key": "limits", "title": _("Known limits"), "items": [
                {"h": _("Learner's permits"), "p": _("Not recorded in Odoo, so learners show as valid or as no licence.")},
                {"h": _("Accident types"), "p": _("The accident record has no type field, so accidents are counted but not split.")},
                {"h": _("Receipts and instalments"),
                 "p": _("The Green Hub app does not link a receipt to the instalment it paid. Receipts are therefore "
                        "categorised by their purpose text, and past arrears are approximate.")},
                {"h": _("Lender repayments"),
                 "p": _("Actual repayments posted in the books. There is no forward repayment schedule.")},
            ]},
        ]

    def _guide_terms(self, s):
        return [
            {"term": _("Active"), "meaning": _("A contract in the state Running or Paused. An active rider has at least one.")},
            {"term": _("Arrears"), "meaning": _("Instalments past their due date and not fully paid, plus unpaid late fees. "
                                                "Instalments not yet due are never arrears.")},
            {"term": _("As of"), "meaning": _("The date a status figure describes.")},
            {"term": _("Credit"), "meaning": _("Money a rider has paid ahead, not yet matched to an instalment.")},
            {"term": _("Days past due (DPD)"), "meaning": _("Days since the due date of the oldest instalment still unpaid.")},
            {"term": _("Default"), "meaning": _("In the Green Hub app, a contract whose arrears reach three times its "
                                                "instalment. Definition used on the dashboards: %(scope)s.", scope=s["default_scope"])},
            {"term": _("EBITDA"), "meaning": _("Earnings before interest, tax, depreciation and amortisation.")},
            {"term": _("Exit"), "meaning": _("A rider who was active at the start of a period and is not at its end.")},
            {"term": _("Favourable"), "meaning": _("Better than plan: higher for income, lower for costs and losses.")},
            {"term": _("First-time rider"), "meaning": _("A rider whose first-ever contract started in the period. In Customer "
                                                      "growth (weekly), a rider not active in any earlier recorded week.")},
            {"term": _("Fleet"), "meaning": _("All vehicles, leaving out test bikes when that option is on.")},
            {"term": _("Instalment"), "meaning": _("One line of a contract's payment schedule, normally weekly.")},
            {"term": _("PAR"), "meaning": _("Portfolio at risk: contracts grouped by how many days late they are.")},
            {"term": _("Pro-rata target"), "meaning": _("The share of a month's target that should be reached by today.")},
            {"term": _("Product group"), "meaning": _("Zembo, iQube, NIU and so on: a set of contract products and vehicle models.")},
            {"term": _("Re-financing"), "meaning": _("An available bike that has had a rider before.")},
            {"term": _("Retention"), "meaning": _("The share of a starting group of riders still active later.")},
            {"term": _("Returning rider"), "meaning": _("A rider who was active before, left, and came back.")},
            {"term": _("Snapshot"), "meaning": _("A stored copy of the figures at a week end or month end.")},
            {"term": _("Target version"), "meaning": _("One set of operational targets: original, revised or forecast.")},
            {"term": _("Write-off"), "meaning": _("An accounting entry that records a defaulted balance as a loss.")},
            {"term": _("YTD / MTD"), "meaning": _("Year to date / month to date.")},
        ]

    @api.model
    def get_guide(self):
        """Explainers for every card and the content of the Guide page."""
        self._check_access()
        s = self._guide_settings()
        return {
            "company": self.env.company.name,
            "dashboards": self._guide_dashboards(),
            "entries": self._guide_entries(s),
            "sections": self._guide_sections(s),
            "terms": self._guide_terms(s),
            "is_manager": self.env.user.has_group("Greenhub_dashboards.group_gh_dashboard_manager"),
        }

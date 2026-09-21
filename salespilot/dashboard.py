# -*- coding: utf-8 -*-
"""Text sales dashboard (FR-11/FR-12; replace with a web dashboard later)."""
from .models import Priority
from .storage import Repository


def render_dashboard(repo: Repository) -> str:
    opps = repo.list_opportunities()
    counts = {Priority.HIGH: 0, Priority.MEDIUM: 0, Priority.LOW: 0}
    for opp in opps:
        if opp.score:
            counts[opp.score.priority] += 1
        else:
            counts[Priority.LOW] += 1

    lines = [
        "=" * 74,
        "SALES DASHBOARD - CareSure SalesPilot",
        "=" * 74,
        f"  [ HIGH {counts[Priority.HIGH]} ]   "
        f"[ MEDIUM {counts[Priority.MEDIUM]} ]   "
        f"[ LOW {counts[Priority.LOW]} ]",
        "-" * 74,
        f"{'Customer':<16}{'State':<26}{'Product':<11}{'Score':>6}  {'Action'}",
        "-" * 74,
    ]

    priority_order = {Priority.HIGH: 0, Priority.MEDIUM: 1, Priority.LOW: 2}
    ordered = sorted(
        opps,
        key=lambda o: priority_order[o.score.priority] if o.score else 3,
    )
    for opp in ordered:
        signals = _signal_summary(opp)
        score = str(opp.score.total) if opp.score else "-"
        action = "Take Over" if opp.human_takeover else "Follow Up"
        lines.append(
            f"{opp.customer_name:<16}{opp.state.value:<26}"
            f"{opp.product.value.title():<11}{score:>6}  {action} {signals}"
        )

    cases = repo.list_cases()
    lines.append("-" * 74)
    lines.append(f"HUMAN CASES (Open: {sum(1 for c in cases if c.status.value == 'Open')})")
    for case in cases:
        lines.append(
            f"  [{case.status.value}] {case.id} | {case.customer_name} | "
            f"{case.reason}"
        )
    lines.append("=" * 74)
    return "\n".join(lines)


def render_customer(opp) -> str:
    score = opp.score
    rows = [
        ("CUSTOMER", opp.customer_name),
        ("STATE", opp.state.value),
        ("PRODUCT", opp.product.value),
        ("PURCHASE INTENT", str(score.purchase_intent) if score else "-"),
        ("SIGNALS", ", ".join(s.value for s in opp.signals) or "-"),
        ("CONCERN", opp.main_concern or "-"),
        ("COMPETITIVE RISK", "High" if opp.competitive_risk else "None"),
        ("CHURN RISK", "Yes" if opp.churn_risk else "No"),
        ("COMPLIANCE RISK", "Yes" if opp.compliance_risk else "No"),
        ("EXPANSION", ", ".join(opp.expansion) if opp.expansion else "None"),
        ("SCORE / PRIORITY",
         f"{score.total}/100 ({score.priority.value})" if score else "-"),
        ("HUMAN TAKEOVER", "Yes" if opp.human_takeover else "No"),
    ]
    width = 74
    out = ["=" * width, "CUSTOMER OPPORTUNITY VIEW", "=" * width]
    for label, value in rows:
        out.append(f"{label:<22}{value}")
    out.append("=" * width)
    return "\n".join(out)


def _signal_summary(opp) -> str:
    names = {
        "Purchase": "Purchase",
        "Hesitation": "Hesitation",
        "Competitive": "Competitive",
        "Expansion: Family": "FamilyExp",
        "Expansion: Corporate": "CorpExp",
        "Human Request": "HumanReq",
        "Compliance Risk": "ComplianceRisk",
        "Negotiation": "Negotiation",
        "Conversion": "Converted",
        "Withdrawal": "Withdrawn",
    }
    picked = [names[s.value] for s in opp.signals if s.value in names]
    return ("[" + "+".join(picked) + "]") if picked else ""

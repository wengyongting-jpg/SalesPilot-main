# -*- coding: utf-8 -*-
"""Human escalation / HITL manager.

Escalates when:
  - personalised underwriting
  - personal medical / pre-existing-condition decision
  - claim decision / dispute
  - custom quotation
  - corporate quotation / negotiation
  - complaint
  - explicit human request
  - low / conflicting retrieval confidence (only for specific product-detail queries)
  - high-value sales opportunity requiring human intervention (not every message)

When Human Takeover is active, the AI stops making autonomous customer-facing
sales decisions (while continuing to log conversation, update observable
signals, and update the opportunity profile/state).

IMPORTANT: One active HITL case per opportunity. If a case already exists,
update it instead of creating a new one.
"""
import uuid
from typing import Optional

from .. import config
from ..models import (
    CaseStatus,
    Detection,
    HumanCase,
    Intent,
    Opportunity,
    OpportunityState,
    Product,
    RetrievalResult,
    Signal,
)

# Intents that are factual product queries — safe for AI to answer
_FACTUAL_INTENTS = {
    Intent.PRICE,
    Intent.COVERAGE,
    Intent.ELIGIBILITY,
    Intent.CLAIMS,
    Intent.WAITING_PERIOD,
    Intent.PAYMENT,
    Intent.APPLICATION,
    Intent.COMPARISON,
}

# Messages that should NEVER trigger escalation — answered directly by AI
_SAFE_PATTERNS = (
    "introduce", "basic info", "basic information", "what plans",
    "what do you have", "tell me about", "learn about",
    "what products", "what options",
)


class HITLManager:
    def evaluate(
        self,
        opp: Opportunity,
        det: Detection,
        retrieval: RetrievalResult,
        latest_text: str,
    ) -> Optional[str]:
        """Return the escalation reason, or None when no escalation is needed.

        Only truly restricted cases escalate. Generic product questions,
        basic info requests, and general enquiries are answered directly.
        """
        text = latest_text.lower().strip()
        current_signals = set(det.signals)

        # --- Explicit human request ---
        if Signal.HUMAN_REQUEST in current_signals:
            return "Customer explicitly asked to speak to a person"

        # --- Complaint ---
        if det.intent == Intent.COMPLAINT:
            return "Complaint handling is outside AI authority"

        # --- Commercial negotiation / discount / price-match (P0-4) ---
        # A price *concern* ("it's a bit expensive") is NOT a negotiation and
        # must not escalate. Only explicit negotiation / discount / price-match
        # requests escalate, and with a reason that clearly says so — never
        # mislabelled as medical / underwriting / compliance.
        if Signal.NEGOTIATION in current_signals:
            return "Commercial negotiation / discount request requires human handling"

        # --- Compliance / restricted (underwriting, medical, claims, custom quotes) ---
        if Signal.COMPLIANCE_RISK in current_signals or det.intent == Intent.UNDERWRITING:
            return "Personalised medical / underwriting question requires human assessment"

        # --- Corporate quotation ---
        if opp.product == Product.CORPORATE and (
            "quote" in text or "quotation" in text
        ):
            return "Corporate quotation / negotiation requires human handling"

        # --- Low retrieval confidence (ONLY for specific product-detail queries) ---
        # Don't escalate for generic questions or basic info requests
        if (
            opp.product != Product.UNKNOWN
            and det.intent in _FACTUAL_INTENTS
            and det.intent != Intent.APPLICATION
            and retrieval.confidence < config.RETRIEVAL_CONFIDENCE_ESCALATE
            and not any(p in text for p in _SAFE_PATTERNS)
        ):
            return "Low / conflicting retrieval confidence — do not guess"

        # --- High intent + competitive risk: recommend human intervention ---
        # Check both current-turn competitive signal and accumulated competitive_risk flag
        if (
            opp.state == OpportunityState.HIGH_INTENT
            and (Signal.COMPETITIVE in current_signals or opp.competitive_risk)
            and not opp.human_takeover
        ):
            return "High purchase intent with competitive comparison — recommend human sales intervention"

        # --- Withdrawal: NOT an escalation reason ---
        if Signal.WITHDRAWAL in current_signals:
            return None

        return None

    def create_case(
        self,
        opp: Opportunity,
        reason: str,
        recommended_action: str,
    ) -> HumanCase:
        signals = ", ".join(s.value for s in opp.signals) or "-"
        product = opp.product.value if opp.product != Product.UNKNOWN else "Unknown"
        summary = (
            f"Customer is in state '{opp.state.value}' interested in {product}. "
            f"Signals: {signals}. Main concern: "
            f"{opp.main_concern or '-'}. Competitive risk: "
            f"{'High' if opp.competitive_risk else 'None'}. "
            f"Expansion: {', '.join(opp.expansion) if opp.expansion else 'None'}."
        )
        return HumanCase(
            id=f"H-{uuid.uuid4().hex[:6].upper()}",
            opportunity_id=opp.id,
            customer_name=opp.customer_name,
            state=opp.state,
            product=opp.product,
            reason=reason,
            summary=summary,
            recommended_action=recommended_action,
            status=CaseStatus.OPEN,
        )

    def update_case(
        self,
        case: HumanCase,
        reason: str,
        opp: Opportunity,
        recommended_action: str,
    ) -> HumanCase:
        """Update an existing case with new information instead of creating a new one."""
        signals = ", ".join(s.value for s in opp.signals) or "-"
        product = opp.product.value if opp.product != Product.UNKNOWN else "Unknown"
        new_info = (
            f" [Update] Customer state: {opp.state.value}. "
            f"Signals: {signals}. Score: {opp.score.total if opp.score else '-'}. "
            f"Reason: {reason}."
        )
        case.summary = case.summary + new_info
        case.reason = reason
        case.recommended_action = recommended_action
        case.state = opp.state
        return case

# -*- coding: utf-8 -*-
"""The rule-based extractor: the offline peer of model-based extraction.

Deterministic, standard library only, no network. This is what runs when no model is
configured, and it is a first-class path rather than a fallback hack — the whole
system completes a conversation on it, which is what makes the demo independent of a
provider being reachable.

It is honest about its own limits in one specific way. `genuine_enquiry` stays true
unless a deterministic solicitation marker fires: a keyword list is not in a position
to judge whether somebody is a real prospective customer, so it does not accuse. The
qualification gate then requires two strikes before acting, which means a rule-based
misjudgement costs a customer nothing.
"""
from __future__ import annotations

import re
from typing import Optional

from ....domain.detection import (
    BuyingPosture, Detection, EvidenceQuality, ObservationEvidence,
    TransactionIssue,
)
from ....domain.enums import Intent, Product, Signal
from ....observability import RunRecorder
from .. import ExtractionOutcome
from . import intent as intent_rules
from . import product as product_rules
from . import signals as signal_rules

_RESTRICTED_SIGNALS = frozenset(
    {Signal.HUMAN_REQUEST, Signal.COMPLIANCE_RISK, Signal.NEGOTIATION}
)
_RESTRICTED_INTENTS = frozenset({Intent.UNDERWRITING, Intent.COMPLAINT})


def _buying_posture(text: str, intent: Intent) -> tuple[BuyingPosture, str]:
    """Return a conservative current-turn posture and the exact supporting span."""
    import re

    candidates = (
        (BuyingPosture.DECLINED, r"\b(?:not buying|won't buy|will not buy|don't want to buy|do not want to buy|no thanks,? not|cancel (?:my )?(?:purchase|application))\b"),
        (BuyingPosture.DEFERRED, r"\b(?:not now|maybe later|revisit (?:this )?(?:in|next)|leave this until|next (?:month|quarter|year)|put (?:this|it) off|hold off)\b"),
        (BuyingPosture.CONDITIONAL, r"\b(?:if|only if|depends on|provided that|once)\b.{0,100}\b(?:buy|apply|sign|price|budget|discount|agree|approve|qualif)\w*\b"),
        (BuyingPosture.READY_NOW, r"\b(?:ready to (?:apply|buy|proceed|sign up)|want to (?:buy|apply|proceed) (?:today|now)|please proceed with|let's (?:apply|proceed|sign up)|i want to proceed today)\b"),
        (BuyingPosture.EVALUATING, r"\b(?:comparing|compare|still deciding|not decided|need to think|considering|weighing|discuss with)\b"),
    )
    lowered = text.casefold()
    for posture, pattern in candidates:
        match = re.search(pattern, lowered)
        if match:
            return posture, text[match.start():match.end()]
    if intent in {Intent.PRICE, Intent.COVERAGE, Intent.ELIGIBILITY, Intent.CLAIMS,
                  Intent.WAITING_PERIOD, Intent.PAYMENT, Intent.COMPARISON,
                  Intent.APPLICATION, Intent.FAMILY_NEED, Intent.CORPORATE_NEED}:
        return BuyingPosture.BROWSING, text[:min(len(text), 160)]
    return BuyingPosture.UNKNOWN, ""


_TRANSACTION_ISSUE_PATTERNS = (
    (TransactionIssue.PAYMENT_UNCONFIRMED, re.compile(
        r"\b(?:money|funds) (?:was )?(?:deducted|taken|charged)\b.{0,80}\b(?:but|and)\b.{0,50}\b(?:no|not|haven't|hasn't|didn't)\b.{0,35}\b(?:confirmation|receipt|show|reflect|receive|arrive)\w*\b"
        r"|\bcharged\b.{0,50}\b(?:but|without)\b.{0,35}\b(?:confirmation|receipt|policy|order)\b"
        r"|\b(?:payment|transaction)\b.{0,20}\b(?:pending|processing|not confirmed|unconfirmed)\b"
        r"|\b(?:did|has)\b.{0,20}\b(?:my )?payment\b.{0,15}\b(?:go through|succeed|arrive|process\w*)\b"
        r"|(?:扣款了|扣了款|钱被扣).{0,12}(?:但|可是|没有|没收到).{0,12}(?:确认|收据|保单|订单)"
        r"|(?:付款|支付)(?:处理中|待确认)"
    , re.IGNORECASE)),
    (TransactionIssue.PAYMENT_FAILED, re.compile(
        r"\b(?:payment|transaction|card payment)\b.{0,35}\b(?:failed|declined|unsuccessful|didn't go through|did not go through|not successful|error)\b"
        r"|\b(?:failed|declined|unsuccessful)\b.{0,25}\b(?:payment|transaction)\b"
        r"|\b(?:can't|cannot|couldn't|could not) pay\b"
        r"|(?:付款|支付|交易).{0,5}(?:失败|不成功|未成功|被拒绝)"
    , re.IGNORECASE)),
    (TransactionIssue.ORDER_STATUS, re.compile(
        r"\b(?:where is|where's|what is the status of|check the status of|did you receive)\b.{0,50}\b(?:my )?(?:order|application|payment|policy)\b"
        r"|\b(?:order|application|policy) status\b"
        r"|\b(?:check|confirm|verify)\b.{0,35}\b(?:my )?(?:order|application|policy)\b.{0,25}\b(?:received|submitted|processed|active|status)\b"
        r"|(?:订单|申请|保单).{0,6}(?:状态|进度)"
    , re.IGNORECASE)),
    (TransactionIssue.PAYMENT_REPORTED, re.compile(
        r"\b(?:i have paid|i've paid|i paid|already paid|payment (?:was )?(?:made|completed|successful|went through)|paid successfully|completed (?:the )?payment|made (?:the )?payment)\b"
        r"|\b(?:i|we) (?:have |'ve )?(?:bought|purchased|signed up|submitted (?:the )?application)\b"
        r"|\b(?:my )?policy (?:has been )?(?:issued|activated|started)\b"
        r"|(?:我)?(?:已经|已)?(?:付款成功|付了款|支付成功|完成付款)"
    , re.IGNORECASE)),
)


def _transaction_issue(text: str) -> tuple[TransactionIssue, str]:
    """Detect only transaction-status problems, not general payment-method questions."""
    for issue, pattern in _TRANSACTION_ISSUE_PATTERNS:
        match = pattern.search(text)
        if match:
            return issue, match.group(0)
    return TransactionIssue.NONE, ""


class RuleExtractor:
    """Phrase matching over intent, product and signals."""

    def extract(
        self,
        text: str,
        context: Optional[list] = None,
        *,
        recorder: Optional[RunRecorder] = None,
    ) -> ExtractionOutcome:
        # Record extraction step if recorder is provided
        if recorder:
            with recorder.step("extraction", "rule") as step:
                intent = intent_rules.detect(text, context=context)
                product = product_rules.detect(text, context=context)
                signals, concerns = signal_rules.detect(text, intent, product, context=context)
                step.note(f"intent={intent.value} product={product.value} signals={len(signals)}")
        else:
            intent = intent_rules.detect(text, context=context)
            product = product_rules.detect(text, context=context)
            signals, concerns = signal_rules.detect(text, intent, product, context=context)

        solicitation = signal_rules.is_solicitation(text)
        posture, span = _buying_posture(text, intent)
        transaction_issue, transaction_span = _transaction_issue(text)
        detection = Detection(
            intent=intent,
            product=product,
            signals=signals,
            concerns=concerns,
            restricted=(
                bool(set(signals) & _RESTRICTED_SIGNALS)
                or intent in _RESTRICTED_INTENTS
            ),
            buying_posture=posture,
            posture_evidence=(
                [ObservationEvidence(span=span, quality=EvidenceQuality.CLEAR)]
                if span else []
            ),
            transaction_issue=transaction_issue,
            transaction_evidence=(
                [ObservationEvidence(span=transaction_span, quality=EvidenceQuality.CLEAR)]
                if transaction_span else []
            ),
            cancellation=signal_rules.is_cancellation(text),
            postponement=signal_rules.is_postponement(text),
            # A keyword list cannot judge genuineness, so it only reports the
            # deterministic marker and leaves the semantic call to a model or,
            # failing that, to the gate's two-strike rule.
            genuine_enquiry=not solicitation,
            solicitation=solicitation,
            greeting=signal_rules.is_greeting(text),
        )
        return ExtractionOutcome(detection=detection, source="rules")


def extract(text: str, context: Optional[list] = None) -> Detection:
    """Convenience function for rule-based extraction."""
    extractor = RuleExtractor()
    outcome = extractor.extract(text, context=context)
    return outcome.detection

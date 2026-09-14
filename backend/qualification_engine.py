"""Provider-independent, deterministic qualification decisions. No database or voice SDK."""
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Outcome(str, Enum):
    INVALID_NUMBER = "INVALID_NUMBER"
    WRONG_NUMBER = "WRONG_NUMBER"
    DUPLICATE_OR_SPAM = "DUPLICATE_OR_SPAM"
    NO_ANSWER = "NO_ANSWER"
    BUSY = "BUSY"
    SWITCHED_OFF = "SWITCHED_OFF"
    UNREACHABLE = "UNREACHABLE"
    TECHNICAL_ISSUE = "TECHNICAL_ISSUE"
    DROPPED_CALL = "DROPPED_CALL"
    CALLBACK_REQUESTED = "CALLBACK_REQUESTED"
    CONNECTED = "CONNECTED"
    DND_REQUESTED = "DND_REQUESTED"


class LeadStatus(str, Enum):
    NEW = "NEW"
    PENDING = "PENDING"
    JUNK = "JUNK"
    UNQUALIFIED = "UNQUALIFIED"
    PARTIALLY_QUALIFIED = "PARTIALLY_QUALIFIED"
    QUALIFIED = "QUALIFIED"
    SALES_READY = "SALES_READY"


RETRYABLE = {Outcome.NO_ANSWER, Outcome.BUSY, Outcome.SWITCHED_OFF, Outcome.UNREACHABLE, Outcome.TECHNICAL_ISSUE, Outcome.DROPPED_CALL}
JUNK = {Outcome.INVALID_NUMBER, Outcome.WRONG_NUMBER, Outcome.DUPLICATE_OR_SPAM}
ACTIONS = ["RETRY_CALL", "CALLBACK", "SALES_CALL", "SITE_VISIT", "BOOK_DEMO", "SEND_QUOTATION", "FOLLOW_UP", "NO_ACTION", "DND"]


class Budget(BaseModel):
    value: float | None = None
    min: float | None = None
    max: float | None = None
    currency: str | None = None


class QualificationData(BaseModel):
    requirement: str | None = None
    product_fit: bool | None = None
    budget: Budget = Field(default_factory=Budget)
    eligibility: bool | None = None
    purchase_timeline: str | None = None
    buying_intent: str | None = None
    decision_maker_status: str | None = None
    location: str | None = None
    preferences: list[str] = Field(default_factory=list)
    objections: list[str] = Field(default_factory=list)
    not_interested: bool = False
    dnd_requested: bool = False
    # Custom facts support new industries without adding business logic to the engine.
    attributes: dict[str, Any] = Field(default_factory=dict)


def validated_facts(values):
    """Invalid individual provider facts become unknown, without losing valid fields."""
    from pydantic import TypeAdapter, ValidationError
    values = values if isinstance(values, dict) else {}
    clean = {}
    for name, field in QualificationData.model_fields.items():
        if name not in values or values[name] is None:
            continue
        value = values[name]
        if name == "budget" and isinstance(value, dict):
            budget = {}
            for key, definition in Budget.model_fields.items():
                try:
                    budget[key] = TypeAdapter(definition.annotation).validate_python(value.get(key))
                except (ValidationError, TypeError, ValueError):
                    budget[key] = None
            value = budget
        try:
            clean[name] = TypeAdapter(field.annotation).validate_python(value)
        except (ValidationError, TypeError, ValueError):
            continue
    return QualificationData.model_validate(clean)


class CallResult(BaseModel):
    provider: str
    provider_call_id: str
    lead_id: str
    call_status: str | None = None
    connection_status: str | None = None
    hangup_reason: str | None = None
    started_at: datetime | None = None
    answered_at: datetime | None = None
    ended_at: datetime | None = None
    duration_seconds: float = Field(default=0, ge=0)
    transcript: str = ""
    summary: str = ""
    recording_url: str | None = None
    extracted_data: dict = Field(default_factory=dict)
    callback_requested: bool = False
    callback_at: datetime | None = None
    outcome_hint: Outcome | None = None
    terminal: bool = True
    raw_provider_data: dict = Field(default_factory=dict)


def fact(data, path):
    for part in path.split("."):
        if not isinstance(data, dict):
            return None
        data = data.get(part)
    return data


def has_fact(value):
    if isinstance(value, dict):
        return any(has_fact(v) for v in value.values())
    if isinstance(value, list):
        return any(has_fact(v) for v in value)
    return value is not None and value != ""


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    operator: Literal["eq", "ne", "gte", "lte", "gt", "lt", "contains", "in", "exists"] = "eq"
    value: Any = True
    reason: str = ""

    @model_validator(mode="after")
    def validate_operand(self):
        if self.operator in {"gte", "lte", "gt", "lt"} and (not isinstance(self.value, (int, float)) or isinstance(self.value, bool)):
            raise ValueError("Numeric rules require a numeric value")
        if self.operator == "in" and not isinstance(self.value, list):
            raise ValueError("in requires a list")
        return self


class RetryRule(BaseModel):
    outcome: Outcome
    delay_minutes: int = Field(ge=1, le=43200)


class RetryConfig(BaseModel):
    max_attempts: int = Field(default=4, ge=1, le=20)
    retry_rules: list[RetryRule] = Field(default_factory=list)


class QualificationProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_name: str = "General qualification"
    product_description: str = ""
    target_customer: str = ""
    campaign_id: str | None = None
    price_range: Budget = Field(default_factory=Budget)
    qualification_criteria: list[Rule] = Field(default_factory=list)
    mandatory_qualification_criteria: list[Rule] = Field(default_factory=list)
    disqualification_criteria: list[Rule] = Field(default_factory=list)
    required_information: list[str] = Field(default_factory=lambda: ["product_fit", "buying_intent"])
    service_locations: list[str] = Field(default_factory=list)
    desired_next_action: str = "SALES_CALL"
    available_next_actions: list[str] = Field(default_factory=lambda: list(ACTIONS))
    special_rules: list[Rule] = Field(default_factory=list)
    weights: dict[str, int] = Field(default_factory=lambda: {"product_fit": 25, "budget_eligibility": 20, "buying_intent": 25, "purchase_timeline": 20, "decision_readiness": 10})
    scoring_rules: dict[str, Rule] = Field(default_factory=dict)
    qualified_threshold: int = Field(default=50, ge=0, le=100)
    sales_ready_threshold: int = Field(default=85, ge=85, le=100)
    retry: RetryConfig = Field(default_factory=RetryConfig)

    @model_validator(mode="after")
    def validate_config(self):
        self.required_information = [v.strip() for v in self.required_information if v.strip()]
        self.service_locations = [v.strip() for v in self.service_locations if v.strip()]
        self.available_next_actions = [v.strip() for v in self.available_next_actions if v.strip()]
        self.campaign_id = self.campaign_id.strip() or None if self.campaign_id else None
        keys = {"product_fit", "budget_eligibility", "buying_intent", "purchase_timeline", "decision_readiness"}
        if set(self.weights) != keys or any(v < 0 for v in self.weights.values()) or sum(self.weights.values()) != 100:
            raise ValueError("The five scoring weights must be non-negative and total 100")
        if not set(self.scoring_rules) <= keys:
            raise ValueError("Unknown scoring dimension")
        if not set(self.available_next_actions) <= set(ACTIONS) or self.desired_next_action not in self.available_next_actions:
            raise ValueError("Invalid available or desired next action")
        if self.qualified_threshold > self.sales_ready_threshold:
            raise ValueError("Qualified threshold cannot exceed sales-ready threshold")
        if self.price_range.min is not None and self.price_range.max is not None and self.price_range.min > self.price_range.max:
            raise ValueError("Price minimum cannot exceed maximum")
        if len({r.outcome for r in self.retry.retry_rules}) != len(self.retry.retry_rules):
            raise ValueError("Only one retry interval is allowed per outcome")
        if any(r.outcome not in RETRYABLE for r in self.retry.retry_rules):
            raise ValueError("Retry intervals can only target retryable outcomes")
        return self


class QualificationRuleEngine:
    @staticmethod
    def evaluate(rule: Rule, data: dict):
        value = fact(data, rule.field)
        if not has_fact(value):
            return None  # Unknown is never a failed mandatory criterion.
        target = rule.value
        if rule.operator == "exists":
            return True
        if rule.operator in {"gte", "lte", "gt", "lt"}:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return None
            return {"gte": value >= target, "lte": value <= target, "gt": value > target, "lt": value < target}[rule.operator]
        if isinstance(value, str):
            value = value.casefold().strip()
        if isinstance(target, str):
            target = target.casefold().strip()
        if rule.operator == "contains":
            return str(target) in value if isinstance(value, str) else target in value if isinstance(value, list) else None
        if rule.operator == "in":
            return value in [v.casefold().strip() if isinstance(v, str) else v for v in target]
        return value == target if rule.operator == "eq" else value != target

    def evaluate_all(self, profile, data):
        mandatory = list(profile.mandatory_qualification_criteria) + list(profile.special_rules)
        if profile.price_range.min is not None:
            # A range which straddles the minimum is unknown rather than invented affordability.
            budget = data.get("budget") or {}
            amount = budget.get("value") if budget.get("value") is not None else budget.get("min")
            ceiling = budget.get("max")
            currency_ok = not profile.price_range.currency or str(budget.get("currency") or "").upper() == profile.price_range.currency.upper()
            affordable = None
            if currency_ok and amount is not None and amount >= profile.price_range.min:
                affordable = True
            elif currency_ok and (ceiling if ceiling is not None else amount) is not None:
                if (ceiling if ceiling is not None else amount) < profile.price_range.min:
                    affordable = False
            data = {**data, "_affordable": affordable}
            mandatory.append(Rule(field="_affordable", value=True, reason="Budget does not meet the configured minimum price"))
        if profile.service_locations:
            mandatory.append(Rule(field="location", operator="in", value=profile.service_locations, reason="Location is outside service coverage"))
        failed = [r.reason or f"Mandatory rule failed: {r.field}" for r in mandatory if self.evaluate(r, data) is False]
        disqualified = [r.reason or f"Disqualification rule matched: {r.field}" for r in profile.disqualification_criteria if self.evaluate(r, data) is True]
        missing = [r.field for r in mandatory + profile.disqualification_criteria if self.evaluate(r, data) is None]
        missing += [path for path in profile.required_information if not has_fact(fact(data, path))]
        return failed + disqualified, sorted(set(missing))


class CallOutcomeClassifier:
    def classify(self, call, data):
        if data.dnd_requested or call.outcome_hint == Outcome.DND_REQUESTED:
            return Outcome.DND_REQUESTED
        if call.outcome_hint in JUNK:
            return call.outcome_hint
        if call.callback_requested or call.outcome_hint == Outcome.CALLBACK_REQUESTED:
            return Outcome.CALLBACK_REQUESTED
        if call.outcome_hint:
            return call.outcome_hint
        if call.connection_status == "connected" or call.transcript or call.extracted_data:
            return Outcome.CONNECTED
        return Outcome.DROPPED_CALL if call.answered_at or call.duration_seconds else Outcome.TECHNICAL_ISSUE


class QualificationScoringEngine:
    def score(self, data: QualificationData, profile):
        normalized = data.model_dump()
        intent = (data.buying_intent or "").casefold()
        timeline = (data.purchase_timeline or "").casefold()
        decision = (data.decision_maker_status or "").casefold()
        factors = {
            "product_fit": 1 if data.product_fit is True else 0,
            "budget_eligibility": 1 if data.eligibility is True else 0,
            "buying_intent": {"high": 1, "medium": .6, "low": .2}.get(intent, 0),
            "purchase_timeline": {"immediate": 1, "soon": .75, "later": .25}.get(timeline, 0),
            "decision_readiness": {"decision_maker": 1, "shared": .5, "not_decision_maker": 0}.get(decision, 0),
        }
        if data.eligibility is None and profile.price_range.min is not None:
            budget = data.budget
            amount = budget.value if budget.value is not None else budget.min
            currency_ok = not profile.price_range.currency or (budget.currency or "").upper() == profile.price_range.currency.upper()
            factors["budget_eligibility"] = 1 if currency_ok and amount is not None and amount >= profile.price_range.min else 0
        for key, rule in profile.scoring_rules.items():
            factors[key] = 1 if QualificationRuleEngine.evaluate(rule, normalized) is True else 0
        # Qualification criteria optionally define the product-fit dimension.
        if profile.qualification_criteria:
            factors["product_fit"] = sum(QualificationRuleEngine.evaluate(r, normalized) is True for r in profile.qualification_criteria) / len(profile.qualification_criteria)
        breakdown = {key: round(profile.weights[key] * factor, 2) for key, factor in factors.items()}
        return round(sum(breakdown.values())), breakdown


class LeadTemperatureEngine:
    @staticmethod
    def temperature(score):
        return "VERY_HOT" if score >= 85 else "HOT" if score >= 70 else "WARM" if score >= 50 else "COLD" if score >= 30 else "LOW"


class RetryPolicyEngine:
    @staticmethod
    def eligible(outcome, attempts, config):
        return outcome in RETRYABLE and attempts < config.max_attempts

    @staticmethod
    def delay(outcome, config):
        return next((r.delay_minutes for r in config.retry_rules if r.outcome == outcome), None)


class NextActionEngine:
    @staticmethod
    def determine(outcome, status, retry, profile):
        if outcome == Outcome.DND_REQUESTED:
            return "DND"
        if status in {LeadStatus.JUNK, LeadStatus.UNQUALIFIED}:
            return "NO_ACTION"
        desired = "RETRY_CALL" if retry else "CALLBACK" if outcome == Outcome.CALLBACK_REQUESTED else profile.desired_next_action if status in {LeadStatus.QUALIFIED, LeadStatus.SALES_READY} else "FOLLOW_UP" if status == LeadStatus.PARTIALLY_QUALIFIED else "NO_ACTION"
        return desired if desired in profile.available_next_actions else "NO_ACTION"


class QualificationResult(BaseModel):
    lead_id: str
    call_outcome: Outcome
    lead_status: LeadStatus
    qualification_score: int | None = None
    lead_temperature: str | None = None
    confidence_score: int = 0
    qualification_reason: str
    disqualification_reason: str | None = None
    qualification_data: QualificationData
    next_action: str = "NO_ACTION"
    callback_at: datetime | None = None
    retry_eligible: bool = False
    conversation_summary: str = ""
    missing_information: list[str] = Field(default_factory=list)
    score_breakdown: dict = Field(default_factory=dict)


class LeadQualificationEngine:
    def process(self, call: CallResult, profile: QualificationProfile, data: QualificationData | None = None, attempts=1, extraction_confidence=100):
        data = data or QualificationData.model_validate(call.extracted_data)
        outcome = CallOutcomeClassifier().classify(call, data)
        meaningful = bool(len(call.transcript.split()) >= 4 or data.not_interested or data.dnd_requested or any(has_fact(v) for k, v in data.model_dump().items() if k not in {"not_interested", "dnd_requested"}))
        result = QualificationResult(lead_id=call.lead_id, call_outcome=outcome, lead_status=LeadStatus.PENDING, qualification_reason=outcome.value.replace("_", " ").capitalize(), qualification_data=data, conversation_summary=call.summary, callback_at=call.callback_at)
        if outcome == Outcome.DND_REQUESTED:
            result.lead_status = LeadStatus.UNQUALIFIED
            result.disqualification_reason = "Do not call requested"
        elif outcome in JUNK:
            result.lead_status = LeadStatus.JUNK
            result.disqualification_reason = result.qualification_reason
        elif outcome == Outcome.CONNECTED:
            failures, missing = QualificationRuleEngine().evaluate_all(profile, data.model_dump())
            result.missing_information = missing
            if data.not_interested:
                failures.insert(0, "Customer is not interested")
            if meaningful:
                result.qualification_score, result.score_breakdown = QualificationScoringEngine().score(data, profile)
                fields = ["product_fit", "eligibility", "buying_intent", "purchase_timeline", "decision_maker_status"]
                known = sum(fact(data.model_dump(), path) not in (None, "", []) for path in fields)
                result.confidence_score = max(0, min(100, extraction_confidence, round(100 * known / len(fields))) - min(40, len(missing) * 10))
            if failures:
                result.lead_status = LeadStatus.UNQUALIFIED
                result.disqualification_reason = "; ".join(failures)
                result.qualification_reason = "Business rules did not pass"
            elif not meaningful or missing or result.confidence_score == 0:
                result.lead_status = LeadStatus.PARTIALLY_QUALIFIED
                result.qualification_reason = "More qualification information is required"
            elif result.qualification_score >= profile.sales_ready_threshold:
                result.lead_status = LeadStatus.SALES_READY
                result.qualification_reason = "Mandatory rules passed; sales-ready score reached"
            elif result.qualification_score >= profile.qualified_threshold:
                result.lead_status = LeadStatus.QUALIFIED
                result.qualification_reason = "Mandatory rules and qualification threshold passed"
            else:
                result.lead_status = LeadStatus.UNQUALIFIED
                result.disqualification_reason = "Below qualification threshold"
            # A failed mandatory rule must not produce a misleading HOT label.
            if result.qualification_score is not None and not failures:
                result.lead_temperature = LeadTemperatureEngine.temperature(result.qualification_score)
        result.retry_eligible = RetryPolicyEngine.eligible(outcome, attempts, profile.retry)
        result.next_action = NextActionEngine.determine(outcome, result.lead_status, result.retry_eligible, profile)
        return result

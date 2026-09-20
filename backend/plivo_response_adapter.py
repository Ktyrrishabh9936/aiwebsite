"""Plivo field aliases end here. The engine only receives CallResult."""
import hashlib
import json
import re
from datetime import datetime, timezone

from qualification_engine import CallResult, Outcome, QualificationData, validated_facts


def parse_time(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except (ValueError, TypeError):
        return None


def truth(value):
    return value is True or str(value).strip().lower() in {"true", "yes", "1"}


def budget_fact(value):
    """Parse explicit amounts only; no inferred currency or exchange conversion."""
    if isinstance(value, dict):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return {"value": value}
    if not isinstance(value, str):
        return {}
    text = value.lower().replace(",", "")
    matches = re.findall(r"(\d+(?:\.\d+)?)\s*(crores?|cr\b|lakhs?|lacs?|million|mn\b|thousand|k\b)?", text)
    if not 1 <= len(matches) <= 2:
        return {}
    units = {"crore": 10000000, "crores": 10000000, "cr": 10000000, "lakh": 100000, "lakhs": 100000, "lac": 100000, "lacs": 100000, "million": 1000000, "mn": 1000000, "thousand": 1000, "k": 1000}
    trailing_unit = matches[-1][1]
    amounts = [float(number) * units.get(unit or trailing_unit, 1) for number, unit in matches]
    currency = next((code for code, pattern in [("INR", r"₹|\binr\b|\brupees?\b"), ("USD", r"\busd\b"), ("EUR", r"€|\beur\b"), ("GBP", r"£|\bgbp\b")] if re.search(pattern, text)), None)
    if len(amounts) == 2:
        if not re.search(r"[-–—]|\bto\b", text) or amounts[0] > amounts[1]:
            return {}
        return {"min": amounts[0], "max": amounts[1], "currency": currency}
    key = "max" if re.search(r"up to|at most|under|below", text) else "min" if re.search(r"at least|above|over|minimum", text) else "value"
    return {key: amounts[0], "currency": currency}


class PlivoResponseAdapter:
    STATUS_MAP = {
        "invalid_number": Outcome.INVALID_NUMBER, "invalid_destination": Outcome.INVALID_NUMBER,
        "wrong_number": Outcome.WRONG_NUMBER, "wrong_contact": Outcome.WRONG_NUMBER,
        "duplicate": Outcome.DUPLICATE_OR_SPAM, "spam": Outcome.DUPLICATE_OR_SPAM, "fake_lead": Outcome.DUPLICATE_OR_SPAM,
        "duplicate_or_spam": Outcome.DUPLICATE_OR_SPAM,
        "no_answer": Outcome.NO_ANSWER, "noanswer": Outcome.NO_ANSWER, "busy": Outcome.BUSY,
        "user_busy": Outcome.BUSY, "switched_off": Outcome.SWITCHED_OFF,
        "unreachable": Outcome.UNREACHABLE, "number_unreachable": Outcome.UNREACHABLE,
        "technical_issue": Outcome.TECHNICAL_ISSUE, "failed": Outcome.TECHNICAL_ISSUE, "error": Outcome.TECHNICAL_ISSUE,
        "timeout": Outcome.TECHNICAL_ISSUE, "cancelled": Outcome.TECHNICAL_ISSUE, "canceled": Outcome.TECHNICAL_ISSUE,
        "dropped": Outcome.DROPPED_CALL, "dropped_call": Outcome.DROPPED_CALL,
        "callback_requested": Outcome.CALLBACK_REQUESTED, "do_not_call": Outcome.DND_REQUESTED,
        "dnd": Outcome.DND_REQUESTED, "dnd_requested": Outcome.DND_REQUESTED,
        "invalid_destination_address": Outcome.INVALID_NUMBER, "unallocated_number": Outcome.INVALID_NUMBER,
        "destination_out_of_service": Outcome.UNREACHABLE, "endpoint_not_registered": Outcome.UNREACHABLE,
        "busy_line": Outcome.BUSY, "busy_everywhere": Outcome.BUSY,
        "ring_timeout_reached": Outcome.NO_ANSWER, "media_timeout": Outcome.DROPPED_CALL,
        "normal_temporary_failure": Outcome.TECHNICAL_ISSUE, "network_out_of_order": Outcome.TECHNICAL_ISSUE,
    }

    def adapt(self, raw, lead_id, fallback_call_id=""):
        from plivo_calls import normalize_contacto_qualification_payload, unwrap_qualification_payload, normalized_answers
        payload = unwrap_qualification_payload(normalize_contacto_qualification_payload(raw))
        def pick(*keys):
            return next((payload[k] for k in keys if payload.get(k) not in (None, "")), None)
        def token(value):
            return re.sub(r"[\s-]+", "_", str(value or "").strip().lower())
        status = token(pick("CallStatus", "call_status", "Status", "status", "qualification_status"))
        if status in {"qualified", "unqualified", "not_qualified", "not_interested", "declined"}:
            status = "completed"  # A disposition is evidence of completion, not qualification.
        hangup = token(pick("hangup_cause_name", "HangupCause", "DialHangupCause", "hangup_reason", "hangup_cause", "disconnection_reason"))
        hint = self.STATUS_MAP.get(hangup) or self.STATUS_MAP.get(status)
        code = str(pick("HangupCauseCode", "hangup_cause_code") or "")
        hint = hint or {"2000": Outcome.INVALID_NUMBER, "3050": Outcome.INVALID_NUMBER, "3120": Outcome.INVALID_NUMBER, "2010": Outcome.UNREACHABLE, "2020": Outcome.UNREACHABLE, "3000": Outcome.NO_ANSWER, "6010": Outcome.NO_ANSWER, "3010": Outcome.BUSY, "3100": Outcome.BUSY, "6020": Outcome.DROPPED_CALL}.get(code)
        if not hint and code and code not in {"0", "4000", "4010", "4020", "4030", "6000"}:
            hint = Outcome.TECHNICAL_ISSUE
        transcript = pick("transcript", "transcription", "Transcription", "Transcript") or ""
        if isinstance(transcript, list):
            transcript = "\n".join(str(turn.get("text") or turn.get("content") or "") if isinstance(turn, dict) else str(turn) for turn in transcript)
        summary = pick("conversation_summary", "summary", "call_summary", "final_summary") or ""
        source = pick("qualification_data", "extracted_data", "structured_qualification", "structured_data") or normalized_answers(payload)
        source = source if isinstance(source, dict) else {}
        # Only facts, never provider-owned scores/status/category, enter the engine.
        allowed = QualificationData.model_fields
        extracted = {key: value for key, value in source.items() if key in allowed}
        for key in allowed:
            if key not in extracted and key in payload:
                extracted[key] = payload[key]
        if "budget" in extracted:
            extracted["budget"] = budget_fact(extracted["budget"])
        if not extracted.get("location") and source.get("preferred_location"):
            extracted["location"] = source["preferred_location"]
        if not extracted.get("purchase_timeline") and source.get("timeline") in ("immediate", "soon", "later"):
            extracted["purchase_timeline"] = source["timeline"]
        for key in ("product_fit", "eligibility", "not_interested", "dnd_requested"):
            if key in extracted and extracted[key] is not None:
                raw_bool = str(extracted[key]).strip().lower()
                if raw_bool in {"true", "yes", "1", "false", "no", "0"}:
                    extracted[key] = truth(extracted[key])
                else:
                    extracted.pop(key)  # e.g. "unknown" is not evidence of false.
        for key in ("preferences", "objections"):
            if key in extracted and not isinstance(extracted[key], list):
                extracted[key] = [str(extracted[key])]
        # Explicit caller requests override all sales scoring, including a provider's "hot" label.
        if re.search(r"\b(do not call me|don't call me|stop calling me|remove my number)\b", str(transcript), re.I):
            extracted["dnd_requested"] = True
        if re.search(r"\b(not interested|no longer interested)\b", str(transcript), re.I):
            extracted["not_interested"] = True
        result_token = token(pick("qualification_status", "result", "outcome"))
        if result_token in {"wrong_number", "wrong_contact", "invalid_number", "do_not_call", "dnd", "fake_lead", "duplicate", "spam"}:
            hint = self.STATUS_MAP.get(result_token) or hint
        if result_token in {"not_interested", "declined"}:
            extracted["not_interested"] = True
        extracted = validated_facts(extracted).model_dump(exclude_unset=True)
        callback = truth(pick("callback_requested")) or bool(re.search(r"\b(call me back|call back later|please call later)\b", str(transcript), re.I))
        try:
            duration = max(0, float(pick("duration", "CallDuration", "Duration", "RecordingDuration", "recording_duration") or 0))
        except (ValueError, TypeError):
            duration = 0
        terminal = status not in {"ringing", "queued", "initiated", "started", "accepted", "answered", "in_progress", "unknown"} or bool(transcript or source)
        connected = bool(transcript or source or status in {"completed", "answered", "connected", "hangup"})
        call_id = str(pick("call_uuid", "CallUUID", "CallUuid", "RecordingCallUUID", "request_uuid", "conversation_id", "session_id") or fallback_call_id or "")
        if not call_id:
            # Missing identifiers are isolated, never merged with an unrelated known call.
            call_id = "unidentified:" + hashlib.sha256(json.dumps(raw, sort_keys=True, default=str).encode()).hexdigest()
        return CallResult(provider="plivo", provider_call_id=call_id, lead_id=str(lead_id), call_status=status, connection_status="connected" if connected else "not_connected", hangup_reason=hangup, started_at=parse_time(pick("StartTime", "started_at", "call_timestamp")), answered_at=parse_time(pick("AnswerTime", "answered_at")), ended_at=parse_time(pick("EndTime", "ended_at", "timestamp")), duration_seconds=duration, transcript=str(transcript), summary=str(summary), recording_url=pick("recording_url", "recordingUrl", "RecordUrl", "RecordingUrl"), extracted_data=extracted, callback_requested=callback, callback_at=parse_time(pick("callback_at", "callback_time")), outcome_hint=hint, terminal=terminal, raw_provider_data=raw)

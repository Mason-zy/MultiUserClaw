"""Offline DDI eval seed and scorer for training-data PoCs."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

DEFAULT_DDI_EVAL_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ddi_v0.jsonl"


@dataclass(frozen=True)
class DdiEvalCase:
    case_id: str
    prompt: str
    expected_drugs: tuple[str, ...]
    expected_severity: str
    expected_risk_terms: tuple[str, ...]
    expected_actions: tuple[str, ...]
    reference: str
    privacy_level: str
    expected_interaction: bool = True


@dataclass(frozen=True)
class DdiPrediction:
    case_id: str
    drugs: tuple[str, ...]
    severity: str
    answer: str


@dataclass(frozen=True)
class DdiStructuredPrediction:
    case_id: str
    drugs: tuple[str, ...]
    interaction_present: bool | None
    severity: str
    risk_terms: tuple[str, ...]
    management_actions: tuple[str, ...]
    answer_text: str = ""


@dataclass(frozen=True)
class DdiCaseScore:
    case_id: str
    score: float
    drug_match: bool
    severity_match: bool
    risk_terms_present: bool
    safe_action_present: bool
    missing_signals: tuple[str, ...]


@dataclass(frozen=True)
class DdiStructuredCaseScore:
    case_id: str
    mode: str
    score: float
    drug_set_match: bool
    interaction_match: bool
    severity_match: bool
    risk_terms_match: bool
    management_match: bool
    missing_signals: tuple[str, ...]


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Iterable):
        return tuple(str(item) for item in value if str(item).strip())
    return ()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"DDI eval fixture record must be an object: {path}")
        records.append(value)
    return records


def _case_from_record(record: dict[str, Any]) -> DdiEvalCase:
    return DdiEvalCase(
        case_id=str(record["case_id"]),
        prompt=str(record["prompt"]),
        expected_drugs=_string_tuple(record.get("expected_drugs")),
        expected_severity=str(record["expected_severity"]),
        expected_risk_terms=_string_tuple(record.get("expected_risk_terms")),
        expected_actions=_string_tuple(record.get("expected_actions")),
        reference=str(record.get("reference") or ""),
        privacy_level=str(record.get("privacy_level") or ""),
        expected_interaction=bool(record.get("expected_interaction", True)),
    )


def _prediction_from_record(record: dict[str, Any]) -> DdiPrediction:
    return DdiPrediction(
        case_id=str(record["case_id"]),
        drugs=_string_tuple(record.get("drugs")),
        severity=str(record.get("severity") or ""),
        answer=str(record.get("answer") or ""),
    )


def _bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = _normalize(value)
        if normalized in {"true", "yes", "1", "present", "interaction"}:
            return True
        if normalized in {"false", "no", "0", "absent", "none"}:
            return False
    return None


def _structured_prediction_from_record(record: dict[str, Any]) -> DdiStructuredPrediction:
    actions = record.get("management_actions", record.get("actions", ()))
    return DdiStructuredPrediction(
        case_id=str(record["case_id"]),
        drugs=_string_tuple(record.get("drugs")),
        interaction_present=_bool_or_none(record.get("interaction_present")),
        severity=str(record.get("severity") or ""),
        risk_terms=_string_tuple(record.get("risk_terms")),
        management_actions=_string_tuple(actions),
        answer_text=str(record.get("answer_text") or record.get("answer") or ""),
    )


def load_ddi_eval_cases(path: str | Path | None = None) -> list[DdiEvalCase]:
    """Load synthetic DDI eval cases from JSONL."""
    fixture_path = Path(path) if path is not None else DEFAULT_DDI_EVAL_FIXTURE
    return [_case_from_record(record) for record in _read_jsonl(fixture_path)]


def load_default_ddi_eval_cases() -> list[DdiEvalCase]:
    """Load the checked-in synthetic DDI seed fixture."""
    return load_ddi_eval_cases(DEFAULT_DDI_EVAL_FIXTURE)


def _normalize(value: str) -> str:
    lowered = value.lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", lowered)).strip()


def _normalized_set(values: tuple[str, ...]) -> set[str]:
    return {normalized for value in values if (normalized := _normalize(value))}


def _contains_all(terms: tuple[str, ...], text: str) -> bool:
    normalized = _normalize(text)
    return all(_normalize(term) in normalized for term in terms)


def _contains_any(terms: tuple[str, ...], text: str) -> bool:
    normalized = _normalize(text)
    return any(_normalize(term) in normalized for term in terms)


def _record_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_record_text(item) for item in value.values())
    if isinstance(value, Iterable):
        return " ".join(_record_text(item) for item in value)
    return str(value or "")


def _trace_text(record: dict[str, Any]) -> str:
    return " ".join(
        (
            _record_text(record.get("messages") or []),
            _record_text(record.get("tool_events") or []),
            _record_text(record.get("final_output") or ""),
        )
    )


def _detect_severity(text: str) -> str:
    normalized = _normalize(text)
    severity_aliases = (
        ("contraindicated", ("contraindicated", "禁忌")),
        ("major", ("major", "severe", "serious", "严重", "重大")),
        ("moderate", ("moderate", "中等", "中度")),
        ("minor", ("minor", "mild", "轻微", "轻度")),
        ("none", ("none", "no interaction", "未见", "无相互作用")),
    )
    for severity, aliases in severity_aliases:
        if any(
            (alias_normalized and alias_normalized in normalized) or alias in text
            for alias in aliases
            if (alias_normalized := _normalize(alias)) or alias
        ):
            return severity
    return ""


def extract_ddi_predictions_from_trace_records(
    trace_records: list[dict[str, Any]],
    *,
    cases: list[DdiEvalCase] | None = None,
) -> list[DdiPrediction]:
    """Extract DDI prediction records from completed sanitized trace records."""
    eval_cases = cases if cases is not None else load_default_ddi_eval_cases()
    predictions: list[DdiPrediction] = []
    for record in trace_records:
        status = str(record.get("status") or "").lower()
        if status and status != "completed":
            continue
        trace_text = _trace_text(record)
        final_output = str(record.get("final_output") or "")
        severity = _detect_severity(final_output) or _detect_severity(trace_text)
        for case in eval_cases:
            if not _contains_all(case.expected_drugs, trace_text):
                continue
            predictions.append(
                DdiPrediction(
                    case_id=case.case_id,
                    drugs=case.expected_drugs,
                    severity=severity,
                    answer=final_output,
                )
            )
    return predictions


def score_ddi_prediction(case: DdiEvalCase, prediction: DdiPrediction) -> DdiCaseScore:
    """Score one DDI prediction with simple step-level binary signals."""
    combined_text = " ".join((*prediction.drugs, prediction.answer))
    drug_match = _contains_all(case.expected_drugs, combined_text)
    severity_match = _normalize(case.expected_severity) in _normalize(
        " ".join((prediction.severity, prediction.answer))
    )
    risk_terms_present = _contains_all(case.expected_risk_terms, prediction.answer)
    safe_action_present = _contains_any(case.expected_actions, prediction.answer)
    components = {
        "drug_match": drug_match,
        "severity_match": severity_match,
        "risk_terms_present": risk_terms_present,
        "safe_action_present": safe_action_present,
    }
    missing_signals = tuple(name for name, passed in components.items() if not passed)
    return DdiCaseScore(
        case_id=case.case_id,
        score=sum(1 for passed in components.values() if passed) / len(components),
        drug_match=drug_match,
        severity_match=severity_match,
        risk_terms_present=risk_terms_present,
        safe_action_present=safe_action_present,
        missing_signals=missing_signals,
    )


def summarize_ddi_scores(scores: list[DdiCaseScore]) -> dict[str, float | int]:
    """Summarize per-case scores into baseline metrics."""
    case_count = len(scores)
    if case_count == 0:
        return {
            "case_count": 0,
            "average_score": 0.0,
            "drug_match_rate": 0.0,
            "severity_match_rate": 0.0,
            "risk_terms_present_rate": 0.0,
            "safe_action_present_rate": 0.0,
        }
    return {
        "case_count": case_count,
        "average_score": sum(score.score for score in scores) / case_count,
        "drug_match_rate": sum(score.drug_match for score in scores) / case_count,
        "severity_match_rate": sum(score.severity_match for score in scores) / case_count,
        "risk_terms_present_rate": sum(score.risk_terms_present for score in scores) / case_count,
        "safe_action_present_rate": sum(score.safe_action_present for score in scores) / case_count,
    }


def score_structured_ddi_prediction(
    case: DdiEvalCase,
    prediction: DdiStructuredPrediction,
) -> DdiStructuredCaseScore:
    """Score one structured DDI prediction against ground-truth fields."""
    expected_drugs = _normalized_set(case.expected_drugs)
    predicted_drugs = _normalized_set(prediction.drugs)
    expected_risks = _normalized_set(case.expected_risk_terms)
    predicted_risks = _normalized_set(prediction.risk_terms)
    expected_actions = _normalized_set(case.expected_actions)
    predicted_actions = _normalized_set(prediction.management_actions)
    components = {
        "drug_set_match": predicted_drugs == expected_drugs,
        "interaction_match": prediction.interaction_present is case.expected_interaction,
        "severity_match": _normalize(prediction.severity) == _normalize(case.expected_severity),
        "risk_terms_match": expected_risks.issubset(predicted_risks),
        "management_match": bool(expected_actions & predicted_actions),
    }
    missing_signals = tuple(name for name, passed in components.items() if not passed)
    return DdiStructuredCaseScore(
        case_id=case.case_id,
        mode="structured_baseline",
        score=sum(1 for passed in components.values() if passed) / len(components),
        drug_set_match=components["drug_set_match"],
        interaction_match=components["interaction_match"],
        severity_match=components["severity_match"],
        risk_terms_match=components["risk_terms_match"],
        management_match=components["management_match"],
        missing_signals=missing_signals,
    )


def summarize_structured_ddi_scores(scores: list[DdiStructuredCaseScore]) -> dict[str, float | int]:
    """Summarize structured baseline DDI scores."""
    case_count = len(scores)
    if case_count == 0:
        return {
            "case_count": 0,
            "average_score": 0.0,
            "drug_set_match_rate": 0.0,
            "interaction_match_rate": 0.0,
            "severity_match_rate": 0.0,
            "risk_terms_match_rate": 0.0,
            "management_match_rate": 0.0,
        }
    return {
        "case_count": case_count,
        "average_score": sum(score.score for score in scores) / case_count,
        "drug_set_match_rate": sum(score.drug_set_match for score in scores) / case_count,
        "interaction_match_rate": sum(score.interaction_match for score in scores) / case_count,
        "severity_match_rate": sum(score.severity_match for score in scores) / case_count,
        "risk_terms_match_rate": sum(score.risk_terms_match for score in scores) / case_count,
        "management_match_rate": sum(score.management_match for score in scores) / case_count,
    }


def evaluate_prediction_records(
    prediction_records: list[dict[str, Any]],
    *,
    cases: list[DdiEvalCase] | None = None,
) -> dict[str, Any]:
    """Evaluate JSONL prediction records against DDI eval cases."""
    eval_cases = cases if cases is not None else load_ddi_eval_cases()
    cases_by_id = {case.case_id: case for case in eval_cases}
    scores: list[DdiCaseScore] = []
    unknown_case_ids: list[str] = []
    for record in prediction_records:
        prediction = _prediction_from_record(record)
        case = cases_by_id.get(prediction.case_id)
        if case is None:
            unknown_case_ids.append(prediction.case_id)
            continue
        scores.append(score_ddi_prediction(case, prediction))
    return {
        "mode": "answer_keyword_smoke",
        "limitations": (
            "not_medical_eval",
            "free_text_keyword_matching_only",
            "do_not_use_as_training_reward",
        ),
        "summary": summarize_ddi_scores(scores),
        "scores": [score.__dict__ for score in scores],
        "unknown_case_ids": unknown_case_ids,
    }


def evaluate_structured_prediction_records(
    prediction_records: list[dict[str, Any]],
    *,
    cases: list[DdiEvalCase] | None = None,
) -> dict[str, Any]:
    """Evaluate structured DDI prediction records against ground-truth fields."""
    eval_cases = cases if cases is not None else load_ddi_eval_cases()
    cases_by_id = {case.case_id: case for case in eval_cases}
    scores: list[DdiStructuredCaseScore] = []
    unknown_case_ids: list[str] = []
    for record in prediction_records:
        prediction = _structured_prediction_from_record(record)
        case = cases_by_id.get(prediction.case_id)
        if case is None:
            unknown_case_ids.append(prediction.case_id)
            continue
        scores.append(score_structured_ddi_prediction(case, prediction))
    return {
        "mode": "structured_baseline",
        "summary": summarize_structured_ddi_scores(scores),
        "scores": [score.__dict__ for score in scores],
        "unknown_case_ids": unknown_case_ids,
    }


def evaluate_trace_records(
    trace_records: list[dict[str, Any]],
    *,
    cases: list[DdiEvalCase] | None = None,
) -> dict[str, Any]:
    """Extract DDI predictions from trace records and evaluate them."""
    predictions = extract_ddi_predictions_from_trace_records(trace_records, cases=cases)
    result = evaluate_prediction_records([prediction.__dict__ for prediction in predictions], cases=cases)
    result["mode"] = "trace_smoke"
    result["limitations"] = (
        "not_medical_eval",
        "trace_extraction_and_keyword_matching_only",
        "do_not_use_as_training_reward",
    )
    result["extracted_prediction_count"] = len(predictions)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate DDI prediction JSONL records.")
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--predictions", help="Path to free-text prediction JSONL smoke file.")
    input_group.add_argument("--structured-predictions", help="Path to structured DDI prediction JSONL file.")
    input_group.add_argument("--traces", help="Path to sanitized trace JSONL file.")
    parser.add_argument("--cases", default=None, help="Optional DDI case JSONL file.")
    args = parser.parse_args(argv)
    cases = load_ddi_eval_cases(args.cases) if args.cases else None
    if args.traces:
        result = evaluate_trace_records(_read_jsonl(Path(args.traces)), cases=cases)
    elif args.structured_predictions:
        result = evaluate_structured_prediction_records(
            _read_jsonl(Path(args.structured_predictions)),
            cases=cases,
        )
    else:
        result = evaluate_prediction_records(_read_jsonl(Path(args.predictions)), cases=cases)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

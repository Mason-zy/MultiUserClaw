"""EviMedBench rubric judge task generation.

This module prepares evaluation inputs only. It does not grade medical answers.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

EVIMEDBENCH_DATASET_URL = (
    "https://modelscope.cn/datasets/InfoxmedModel/EviMedBench/resolve/master/"
    "eval_dataset_final_v5.json"
)


@dataclass(frozen=True)
class EviMedBenchRubric:
    rubric_id: str
    dimension: str
    dimension_id: str
    criterion: str
    weight: int
    verification_hint: str


@dataclass(frozen=True)
class EviMedBenchCase:
    eval_id: str
    final_eval_id: str
    question: str
    pico: dict[str, str]
    specialty: str
    grade: str
    question_type: str
    rubrics: tuple[EviMedBenchRubric, ...]


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"JSONL record must be an object: {path}")
        records.append(value)
    return records


def _string_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _rubric_from_record(record: dict[str, Any]) -> EviMedBenchRubric:
    return EviMedBenchRubric(
        rubric_id=str(record.get("rubric_id") or ""),
        dimension=str(record.get("dimension") or ""),
        dimension_id=str(record.get("dimension_id") or ""),
        criterion=str(record.get("criterion") or ""),
        weight=int(record.get("weight") or 0),
        verification_hint=str(record.get("verification_hint") or ""),
    )


def _case_from_record(record: dict[str, Any]) -> EviMedBenchCase:
    rubrics = record.get("rubrics") if isinstance(record.get("rubrics"), list) else []
    return EviMedBenchCase(
        eval_id=str(record.get("eval_id") or ""),
        final_eval_id=str(record.get("final_eval_id") or ""),
        question=str(record.get("question") or ""),
        pico=_string_dict(record.get("pico")),
        specialty=str(record.get("specialty") or ""),
        grade=str(record.get("grade") or ""),
        question_type=str(record.get("question_type") or ""),
        rubrics=tuple(_rubric_from_record(rubric) for rubric in rubrics if isinstance(rubric, dict)),
    )


def load_evimedbench_cases(path: str | Path) -> list[EviMedBenchCase]:
    """Load EviMedBench cases from the dataset JSON file."""
    value = _read_json(Path(path))
    if not isinstance(value, list):
        raise ValueError("EviMedBench dataset must be a JSON list")
    return [_case_from_record(record) for record in value if isinstance(record, dict)]


def summarize_evimedbench_cases(cases: list[EviMedBenchCase]) -> dict[str, Any]:
    """Return structural dataset statistics for sanity checks."""
    rubrics = [rubric for case in cases for rubric in case.rubrics]
    return {
        "case_count": len(cases),
        "rubric_count": len(rubrics),
        "specialty_counts": dict(Counter(case.specialty for case in cases)),
        "grade_counts": dict(Counter(case.grade for case in cases)),
        "question_type_counts": dict(Counter(case.question_type for case in cases)),
        "dimension_counts": dict(Counter(rubric.dimension for rubric in rubrics)),
        "negative_weight_rubric_count": sum(1 for rubric in rubrics if rubric.weight < 0),
    }


def _answer_key(record: dict[str, Any]) -> str:
    return str(record.get("final_eval_id") or record.get("eval_id") or "")


def _answer_meta(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: record[key]
        for key in ("trace_id", "run_id", "model", "runtime", "source")
        if key in record and record[key] not in (None, "")
    }


def _normalize_match_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _last_user_message_content(record: dict[str, Any]) -> str:
    messages = record.get("messages")
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "") == "user":
            return str(message.get("content") or "")
    return ""


def _trace_label_key(record: dict[str, Any]) -> str:
    labels = record.get("labels")
    if isinstance(labels, dict):
        label_key = str(labels.get("final_eval_id") or labels.get("eval_id") or "")
        if label_key:
            return label_key
    return str(record.get("final_eval_id") or record.get("eval_id") or "")


def _case_lookups(cases: list[EviMedBenchCase]) -> tuple[dict[str, EviMedBenchCase], dict[str, EviMedBenchCase]]:
    cases_by_id: dict[str, EviMedBenchCase] = {}
    cases_by_question: dict[str, EviMedBenchCase] = {}
    for case in cases:
        if case.final_eval_id:
            cases_by_id[case.final_eval_id] = case
        if case.eval_id:
            cases_by_id[case.eval_id] = case
        normalized_question = _normalize_match_text(case.question)
        if normalized_question:
            cases_by_question[normalized_question] = case
    return cases_by_id, cases_by_question


def _trace_case(
    record: dict[str, Any],
    cases_by_id: dict[str, EviMedBenchCase],
    cases_by_question: dict[str, EviMedBenchCase],
) -> EviMedBenchCase | None:
    label_key = _trace_label_key(record)
    if label_key and label_key in cases_by_id:
        return cases_by_id[label_key]
    question_key = _normalize_match_text(_last_user_message_content(record))
    if question_key:
        return cases_by_question.get(question_key)
    return None


def extract_evimedbench_answer_records_from_traces(
    cases: list[EviMedBenchCase],
    trace_records: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Extract matched EviMedBench answer records from sanitized training traces."""
    cases_by_id, cases_by_question = _case_lookups(cases)
    answers: list[dict[str, Any]] = []
    for record in trace_records:
        if str(record.get("status") or "") != "completed":
            continue
        answer = str(record.get("final_output") or "").strip()
        if not answer:
            continue
        case = _trace_case(record, cases_by_id, cases_by_question)
        if case is None:
            continue
        answers.append(
            {
                "eval_id": case.eval_id,
                "final_eval_id": case.final_eval_id,
                "answer": answer,
                "trace_id": record.get("trace_id"),
                "run_id": record.get("run_id"),
                "model": record.get("model"),
                "runtime": record.get("runtime"),
                "source": "training_trace",
                "trace_source": record.get("source"),
                "created_at": record.get("created_at"),
            }
        )
    return answers


def _rubric_to_judge_input(rubric: EviMedBenchRubric) -> dict[str, Any]:
    return {
        "rubric_id": rubric.rubric_id,
        "dimension": rubric.dimension,
        "dimension_id": rubric.dimension_id,
        "criterion": rubric.criterion,
        "weight": rubric.weight,
        "verification_hint": rubric.verification_hint,
        "judge_schema": {
            "passed": "boolean",
            "confidence": "number_0_to_1",
            "rationale": "short_text",
            "evidence_spans": "list_of_answer_spans",
        },
    }


def build_evimedbench_judge_tasks(
    cases: list[EviMedBenchCase],
    answer_records: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build LLM/human judge tasks from EviMedBench cases and model answers."""
    cases_by_id, _ = _case_lookups(cases)
    tasks: list[dict[str, Any]] = []
    for answer_record in answer_records:
        answer_key = _answer_key(answer_record)
        if not answer_key:
            continue
        case = cases_by_id.get(answer_key)
        if case is None:
            continue
        tasks.append(
            {
                "mode": "evimedbench_rubric_judge_task",
                "dataset": {
                    "name": "EviMedBench",
                    "source_url": EVIMEDBENCH_DATASET_URL,
                },
                "eval_id": case.eval_id,
                "final_eval_id": case.final_eval_id,
                "specialty": case.specialty,
                "grade": case.grade,
                "question_type": case.question_type,
                "question": case.question,
                "pico": case.pico,
                "answer": str(answer_record.get("answer") or answer_record.get("final_output") or ""),
                "answer_meta": _answer_meta(answer_record),
                "rubrics": [_rubric_to_judge_input(rubric) for rubric in case.rubrics],
            }
        )
    return tasks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export EviMedBench rubric judge tasks as JSONL.")
    parser.add_argument("--cases", required=True, help="Path to EviMedBench JSON dataset.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--answers", help="Path to answer JSONL records.")
    source.add_argument("--traces", help="Path to sanitized training trace JSONL records.")
    args = parser.parse_args(argv)
    cases = load_evimedbench_cases(args.cases)
    if args.traces:
        answers = extract_evimedbench_answer_records_from_traces(cases, _read_jsonl(Path(args.traces)))
    else:
        answers = _read_jsonl(Path(args.answers))
    for task in build_evimedbench_judge_tasks(cases, answers):
        print(json.dumps(task, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

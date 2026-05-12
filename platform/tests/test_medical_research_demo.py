import json
from pathlib import Path

from app.routes import medical_research_demo as demo


ROOT = Path(__file__).resolve().parents[2]


def test_discover_benchmark_reports_reads_runs_jsonl_and_report(tmp_path, monkeypatch):
    run_dir = tmp_path / "20260509-174100"
    run_dir.mkdir()
    (run_dir / "report.md").write_text("# Blank Spot Benchmark\n\nreport body\n", encoding="utf-8")
    (run_dir / "runs.jsonl").write_text(
        json.dumps(
            {
                "run_id": "hermes-shared-warm-1",
                "backend_label": "hermes",
                "runtime_mode": "shared",
                "startup_state": "warm",
                "status": "completed",
                "total_ms": 70113.3,
                "first_tool_ms": 3880.3,
                "last_tool_ms": 20263.3,
                "completion_ms": 69896.6,
                "event_count": 3131,
                "usage": {"total_tokens": 116410},
                "full_chain": True,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(demo, "BENCHMARK_ROOTS", (tmp_path,))

    reports = demo.discover_benchmark_reports()

    assert len(reports) == 1
    assert reports[0]["label"] == "20260509-174100"
    assert reports[0]["reportUrl"].endswith(f"/api/medical-research-demo/benchmarks/{reports[0]['id']}/report")
    assert reports[0]["runs"][0]["backend"] == "Hermes"
    assert reports[0]["runs"][0]["runtimeMode"] == "shared"
    assert reports[0]["runs"][0]["totalMs"] == 70113.3
    assert reports[0]["runs"][0]["tokens"] == 116410


def test_read_benchmark_report_rejects_unknown_id(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "BENCHMARK_ROOTS", (tmp_path,))

    assert demo.read_benchmark_report("missing") is None


def test_collect_implementation_evidence_reads_current_code():
    evidence = demo.collect_implementation_evidence(repo_root=ROOT)
    labels = {item["label"] for item in evidence}
    joined_symbols = " ".join(item["symbol"] for item in evidence)

    assert "记录 run ownership" in labels
    assert "校验 wait 归属" in labels
    assert "Hermes session header" in labels
    assert "Dedicated 容器入口" in labels
    assert "record_runtime_run" in joined_symbols
    assert "ensure_runtime_run_owned" in joined_symbols
    assert "X-Hermes-Session-Key" in joined_symbols
    assert all(item["line"] > 0 for item in evidence)


def test_collect_implementation_evidence_supports_container_platform_root(tmp_path):
    app_root = tmp_path / "app"
    (app_root / "runtime_backends").mkdir(parents=True)
    (app_root / "runtime").mkdir()
    (app_root / "db").mkdir()
    (app_root / "container").mkdir()
    (app_root / "runtime_backends" / "shared_hermes.py").write_text(
        "record_runtime_run(\nensure_runtime_run_owned(\n",
        encoding="utf-8",
    )
    (app_root / "runtime" / "run_ownership.py").write_text(
        "async def ensure_runtime_run_owned():\n",
        encoding="utf-8",
    )
    (app_root / "db" / "models.py").write_text("class RuntimeRun:\n", encoding="utf-8")
    (app_root / "hermes_client.py").write_text('"X-Hermes-Session-Key"\n', encoding="utf-8")
    (app_root / "runtime_backends" / "dedicated_hermes.py").write_text(
        "ensure_running(db, ctx.user.id)\n",
        encoding="utf-8",
    )
    (app_root / "container" / "manager.py").write_text(
        "async def create_container():\n",
        encoding="utf-8",
    )

    evidence = demo.collect_implementation_evidence(repo_root=tmp_path)

    assert all(item["line"] > 0 for item in evidence)

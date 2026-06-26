"""Unit tests for evaluation result export repositories.

The JSON repository touches the filesystem, so every test writes only under
pytest's tmp_path. The model objects are real dataclasses because the important
contract here is recursive serialization of the same shape produced by the
evals engine.
"""

import csv
import json
from datetime import datetime, timezone
from uuid import UUID

from agent_shell.models.agent import AgentType

from main import _get_results_service
from src.models import (
    AgentConfig,
    AgentEvalExecution,
    AgentEvalStatus,
    Eval,
    EvalExecution,
    ResultFormat,
)
from src.repositories.evaluation_results import (
    CsvEvaluationResultsRepository,
    EvaluationResultsService,
    JsonEvaluationResultsRepository,
)

EXPECTED_CSV_COLUMNS = [
    "agent_type",
    "agent_model",
    "agent_effort",
    "agent_status",
    "agent_total_score",
    "agent_total_tokens",
    "agent_total_time_taken_seconds",
    "eval_execution_id",
    "eval_number",
    "eval_dir",
    "eval_description",
    "eval_run_count",
    "eval_tags",
    "eval_score",
    "eval_total_tokens",
    "eval_time_taken_seconds",
    "eval_date_executed",
]


def _eval_execution(
    *,
    id_: UUID = UUID("00000000-0000-0000-0000-000000000001"),
    agent: AgentConfig | None = None,
    number: int = 1,
    eval_dir: str = "encode_repo_forgetful",
    description: str | None = None,
    run_count: int = 1,
    tags: list[str] | None = None,
    score: float | None = 0.75,
    total_tokens: float | None = 42,
    time_taken_seconds: float | None = 12.5,
    date_executed: datetime | None = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
) -> EvalExecution:
    agent = agent or AgentConfig(agent_type=AgentType.OPENCODE, agent_model="model-a")
    return EvalExecution(
        id=id_,
        eval=Eval(
            number=number,
            eval_dir=eval_dir,
            description=description or f"description for {eval_dir}",
            run_count=run_count,
            tags=tags or ["unit", "json"],
        ),
        agent_config=agent,
        total_tokens=total_tokens,
        score=score,
        time_taken_seconds=time_taken_seconds,
        date_executed=date_executed,
    )


def _agent_eval_execution(
    *,
    agent: AgentConfig | None = None,
    evals: list[EvalExecution] | None = None,
    status: AgentEvalStatus = AgentEvalStatus.COMPLETED,
) -> AgentEvalExecution:
    agent = agent or AgentConfig(
        agent_type=AgentType.OPENCODE,
        agent_model="model-a",
        effort="high",
    )
    evals = evals or [_eval_execution(agent=agent)]
    return AgentEvalExecution(
        agent_config=agent,
        total_score=0.75,
        total_tokens=42,
        total_time_taken_seconds=12.5,
        evals_executions=evals,
        status=status,
    )


def _read_results(run_dir) -> list[dict]:
    return json.loads((run_dir / "results.json").read_text(encoding="utf-8"))


def _read_csv_results(run_dir) -> tuple[list[str], list[dict[str, str]]]:
    with open(run_dir / "results.csv", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames or [], list(reader)


class TestJsonEvaluationResultsRepository:
    def test_writes_results_json_under_run_dir(self, tmp_path):
        # Arrange
        repo = JsonEvaluationResultsRepository(run_dir=tmp_path)

        # Act
        repo.export([_agent_eval_execution()])

        # Assert
        assert (tmp_path / "results.json").is_file()

    def test_exports_top_level_agent_results_as_json_array(self, tmp_path):
        # Arrange
        repo = JsonEvaluationResultsRepository(run_dir=tmp_path)
        first = _agent_eval_execution()
        second_agent = AgentConfig(agent_type=AgentType.CLAUDE_CODE, agent_model="haiku")
        second = _agent_eval_execution(
            agent=second_agent,
            evals=[_eval_execution(agent=second_agent, eval_dir="inflection_bug_fix")],
        )

        # Act
        repo.export([first, second])

        # Assert
        results = _read_results(tmp_path)
        assert isinstance(results, list)
        assert [r["agent_config"]["agent_model"] for r in results] == ["model-a", "haiku"]

    def test_serializes_nested_eval_executions(self, tmp_path):
        # Arrange
        repo = JsonEvaluationResultsRepository(run_dir=tmp_path)
        agent = AgentConfig(agent_type=AgentType.OPENCODE, agent_model="model-a")
        first_eval_id = UUID("00000000-0000-0000-0000-000000000101")
        second_eval_id = UUID("00000000-0000-0000-0000-000000000102")
        aee = _agent_eval_execution(
            agent=agent,
            evals=[
                _eval_execution(
                    id_=first_eval_id,
                    agent=agent,
                    number=1,
                    eval_dir="encode_repo_forgetful",
                    score=0.25,
                ),
                _eval_execution(
                    id_=second_eval_id,
                    agent=agent,
                    number=2,
                    eval_dir="inflection_bug_fix",
                    score=1.0,
                ),
            ],
        )

        # Act
        repo.export([aee])

        # Assert
        nested = _read_results(tmp_path)[0]["evals_executions"]
        assert [e["id"] for e in nested] == [str(first_eval_id), str(second_eval_id)]
        assert [e["eval"]["number"] for e in nested] == [1, 2]
        assert [e["eval"]["eval_dir"] for e in nested] == [
            "encode_repo_forgetful",
            "inflection_bug_fix",
        ]
        assert [e["score"] for e in nested] == [0.25, 1.0]

    def test_serializes_uuid_datetime_and_enums(self, tmp_path):
        # Arrange
        repo = JsonEvaluationResultsRepository(run_dir=tmp_path)
        eval_id = UUID("00000000-0000-0000-0000-000000000201")
        executed = datetime(2026, 6, 26, 9, 30, 15, tzinfo=timezone.utc)
        aee = _agent_eval_execution(
            evals=[
                _eval_execution(
                    id_=eval_id,
                    date_executed=executed,
                )
            ],
            status=AgentEvalStatus.COMPLETED,
        )

        # Act
        repo.export([aee])

        # Assert
        result = _read_results(tmp_path)[0]
        nested = result["evals_executions"][0]
        assert result["agent_config"]["agent_type"] == "opencode"
        assert result["status"] == "completed"
        assert nested["id"] == str(eval_id)
        assert nested["date_executed"] == executed.isoformat()
        assert nested["agent_config"]["agent_type"] == "opencode"

    def test_preserves_none_values_as_json_null(self, tmp_path):
        # Arrange
        repo = JsonEvaluationResultsRepository(run_dir=tmp_path)
        aee = _agent_eval_execution(
            evals=[
                _eval_execution(
                    score=None,
                    total_tokens=None,
                    time_taken_seconds=None,
                    date_executed=None,
                )
            ]
        )

        # Act
        repo.export([aee])

        # Assert
        nested = _read_results(tmp_path)[0]["evals_executions"][0]
        assert nested["score"] is None
        assert nested["total_tokens"] is None
        assert nested["time_taken_seconds"] is None
        assert nested["date_executed"] is None

    def test_creates_missing_run_dir(self, tmp_path):
        # Arrange
        run_dir = tmp_path / "nested" / "run"
        repo = JsonEvaluationResultsRepository(run_dir=run_dir)

        # Act
        repo.export([_agent_eval_execution()])

        # Assert
        assert (run_dir / "results.json").is_file()

    def test_overwrites_existing_results_file(self, tmp_path):
        # Arrange
        results_file = tmp_path / "results.json"
        results_file.write_text("old content", encoding="utf-8")
        repo = JsonEvaluationResultsRepository(run_dir=tmp_path)

        # Act
        repo.export([_agent_eval_execution()])

        # Assert
        assert results_file.read_text(encoding="utf-8") != "old content"
        assert _read_results(tmp_path)[0]["agent_config"]["agent_model"] == "model-a"


class TestCsvEvaluationResultsRepository:
    def test_writes_results_csv_under_run_dir(self, tmp_path):
        # Arrange
        repo = CsvEvaluationResultsRepository(run_dir=tmp_path)

        # Act
        repo.export([_agent_eval_execution()])

        # Assert
        results_file = tmp_path / "results.csv"
        fieldnames, _ = _read_csv_results(tmp_path)
        assert results_file.is_file()
        assert fieldnames == EXPECTED_CSV_COLUMNS
        assert "\r\n" not in results_file.read_text(encoding="utf-8")

    def test_writes_one_row_per_nested_eval_execution(self, tmp_path):
        # Arrange
        repo = CsvEvaluationResultsRepository(run_dir=tmp_path)
        first_agent = AgentConfig(agent_type=AgentType.OPENCODE, agent_model="model-a")
        second_agent = AgentConfig(agent_type=AgentType.CLAUDE_CODE, agent_model="haiku")
        first_eval_id = UUID("00000000-0000-0000-0000-000000000301")
        second_eval_id = UUID("00000000-0000-0000-0000-000000000302")
        third_eval_id = UUID("00000000-0000-0000-0000-000000000303")

        # Act
        repo.export(
            [
                _agent_eval_execution(
                    agent=first_agent,
                    evals=[
                        _eval_execution(
                            id_=first_eval_id,
                            agent=first_agent,
                            number=1,
                            eval_dir="encode_repo_forgetful",
                        ),
                        _eval_execution(
                            id_=second_eval_id,
                            agent=first_agent,
                            number=2,
                            eval_dir="inflection_bug_fix",
                        ),
                    ],
                ),
                _agent_eval_execution(
                    agent=second_agent,
                    evals=[
                        _eval_execution(
                            id_=third_eval_id,
                            agent=second_agent,
                            number=3,
                            eval_dir="chess_engine",
                        ),
                    ],
                ),
            ]
        )

        # Assert
        _, rows = _read_csv_results(tmp_path)
        assert [row["eval_execution_id"] for row in rows] == [
            str(first_eval_id),
            str(second_eval_id),
            str(third_eval_id),
        ]
        assert [row["eval_number"] for row in rows] == ["1", "2", "3"]
        assert [row["agent_model"] for row in rows] == ["model-a", "model-a", "haiku"]

    def test_duplicates_agent_summary_fields_on_each_row(self, tmp_path):
        # Arrange
        repo = CsvEvaluationResultsRepository(run_dir=tmp_path)
        agent = AgentConfig(
            agent_type=AgentType.OPENCODE,
            agent_model="model-a",
            effort="high",
        )
        aee = _agent_eval_execution(
            agent=agent,
            evals=[
                _eval_execution(agent=agent, number=1),
                _eval_execution(agent=agent, number=2),
            ],
            status=AgentEvalStatus.FAILED,
        )
        aee.total_score = 1.25
        aee.total_tokens = 300
        aee.total_time_taken_seconds = 44.5

        # Act
        repo.export([aee])

        # Assert
        _, rows = _read_csv_results(tmp_path)
        assert [
            (
                row["agent_type"],
                row["agent_model"],
                row["agent_effort"],
                row["agent_status"],
                row["agent_total_score"],
                row["agent_total_tokens"],
                row["agent_total_time_taken_seconds"],
            )
            for row in rows
        ] == [
            ("opencode", "model-a", "high", "failed", "1.25", "300", "44.5"),
            ("opencode", "model-a", "high", "failed", "1.25", "300", "44.5"),
        ]

    def test_serializes_enum_uuid_datetime_tags_and_none_values(self, tmp_path):
        # Arrange
        repo = CsvEvaluationResultsRepository(run_dir=tmp_path)
        eval_id = UUID("00000000-0000-0000-0000-000000000401")
        executed = datetime(2026, 6, 26, 9, 30, 15, tzinfo=timezone.utc)
        agent = AgentConfig(
            agent_type=AgentType.CLAUDE_CODE,
            agent_model="haiku",
            effort=None,
        )
        aee = _agent_eval_execution(
            agent=agent,
            evals=[
                _eval_execution(
                    id_=eval_id,
                    agent=agent,
                    number=4,
                    eval_dir="saleor_spree_mapping",
                    description="mapping eval",
                    run_count=2,
                    tags=["python", "bugs,with comma"],
                    score=None,
                    total_tokens=None,
                    time_taken_seconds=None,
                    date_executed=executed,
                )
            ],
            status=AgentEvalStatus.COMPLETED,
        )

        # Act
        repo.export([aee])

        # Assert
        _, rows = _read_csv_results(tmp_path)
        row = rows[0]
        assert row["agent_type"] == "claude_code"
        assert row["agent_effort"] == ""
        assert row["agent_status"] == "completed"
        assert row["eval_execution_id"] == str(eval_id)
        assert row["eval_number"] == "4"
        assert row["eval_run_count"] == "2"
        assert row["eval_tags"] == json.dumps(["python", "bugs,with comma"])
        assert row["eval_score"] == ""
        assert row["eval_total_tokens"] == ""
        assert row["eval_time_taken_seconds"] == ""
        assert row["eval_date_executed"] == executed.isoformat()

    def test_creates_missing_run_dir(self, tmp_path):
        # Arrange
        run_dir = tmp_path / "nested" / "run"
        repo = CsvEvaluationResultsRepository(run_dir=run_dir)

        # Act
        repo.export([_agent_eval_execution()])

        # Assert
        assert (run_dir / "results.csv").is_file()

    def test_overwrites_existing_results_file(self, tmp_path):
        # Arrange
        results_file = tmp_path / "results.csv"
        results_file.write_text("old content", encoding="utf-8")
        repo = CsvEvaluationResultsRepository(run_dir=tmp_path)

        # Act
        repo.export([_agent_eval_execution()])

        # Assert
        assert results_file.read_text(encoding="utf-8") != "old content"
        _, rows = _read_csv_results(tmp_path)
        assert rows[0]["agent_model"] == "model-a"


class TestEvaluationResultsService:
    def test_delegates_export_to_repository(self):
        # Arrange
        class FakeRepository:
            def __init__(self):
                self.exported = None

            def export(self, aees):
                self.exported = aees

        repo = FakeRepository()
        service = EvaluationResultsService(results_repo=repo)
        results = [_agent_eval_execution()]

        # Act
        service.export(results)

        # Assert
        assert repo.exported is results


class TestGetResultsService:
    def test_maps_json_format_to_json_repository(self, tmp_path):
        # Arrange
        service = _get_results_service(ResultFormat.JSON, tmp_path)

        # Act
        service.export([_agent_eval_execution()])

        # Assert
        assert (tmp_path / "results.json").is_file()

    def test_maps_csv_format_to_csv_repository(self, tmp_path):
        # Arrange
        service = _get_results_service(ResultFormat.CSV, tmp_path)

        # Act
        service.export([_agent_eval_execution()])

        # Assert
        assert (tmp_path / "results.csv").is_file()

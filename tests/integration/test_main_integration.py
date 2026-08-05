"""Docker-backed integration coverage for the main.py entrypoint."""

import json
import runpy
import sys
from pathlib import Path

import pytest
from agent_shell.models.agent import HealthCheckResult

pytestmark = pytest.mark.integration


IMAGE = "eval-harness:latest"
BUILD_COMMAND = "docker build -t eval-harness:latest -f src/docker/Dockerfile src/docker/"


EVAL_SOURCE = r"""
class MainIntegrationEval:
    image = "eval-harness:latest"
    score_embedded_values = {
        "EXPECTED_CONTENTS": "arrange\nact\n",
    }

    async def arrange(self):
        from pathlib import Path
        Path("/workspace/main-entrypoint-marker.txt").write_text("arrange\n")
        print("arranged by main integration eval")

    async def act(self):
        from pathlib import Path
        path = Path("/workspace/main-entrypoint-marker.txt")
        path.write_text(path.read_text() + "act\n")
        print("acted by main integration eval")

    async def score(self):
        from pathlib import Path
        contents = Path("/workspace/main-entrypoint-marker.txt").read_text()
        assert contents == EXPECTED_CONTENTS
        print("EVAL_TOTAL_TOKENS=13")
        print("EVAL_SCORE=0.625")
"""


@pytest.fixture
def main_script() -> Path:
    return Path(__file__).resolve().parents[2] / "main.py"


@pytest.fixture
def eval_config(tmp_path: Path) -> Path:
    eval_dir = tmp_path / "main_integration_eval"
    eval_dir.mkdir()
    (eval_dir / "eval.py").write_text(EVAL_SOURCE, encoding="utf-8")

    config = tmp_path / "evals.json"
    config.write_text(
        json.dumps(
            {
                "evals": [
                    {
                        "number": 1,
                        "eval_dir": "main_integration_eval",
                        "description": "main entrypoint integration eval",
                        "run_count": 1,
                        "tags": [],
                    }
                ],
                "agents": [
                    {
                        "agent_type": "claude_code",
                        "agent_model": "main-integration",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return config


@pytest.fixture
def restore_eval_signal_handlers():
    import signal

    original_handlers = {
        signal.SIGINT: signal.getsignal(signal.SIGINT),
        signal.SIGTERM: signal.getsignal(signal.SIGTERM),
    }
    yield
    for signal_number, handler in original_handlers.items():
        signal.signal(signal_number, handler)


def test_main_run_eval_runs_real_docker_phases(
    monkeypatch,
    capsys,
    main_script: Path,
    eval_config: Path,
    tmp_path: Path,
    require_docker_image,
    fake_claude_token,
    assert_container_removed,
    restore_eval_signal_handlers,
):
    # Arrange
    require_docker_image(IMAGE, BUILD_COMMAND)
    output_dir = tmp_path / "output"
    monkeypatch.setattr("src.evals_engine.settings.EVALS_DIRS", str(eval_config.parent))
    monkeypatch.setattr("src.evals_engine.settings.OUTPUT_DIR", str(output_dir))
    monkeypatch.setattr(
        "src.evals_engine.DockerRunner.health_check",
        lambda self, image: HealthCheckResult(healthy=True),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "--run_eval", "--eval_file", str(eval_config)],
    )

    # Act
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(str(main_script), run_name="__main__")

    # Assert
    assert exit_info.value.code == 0
    assert_container_removed("eval_harness_claude_code_main-integration")

    run_dirs = list(output_dir.iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]

    results = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    assert results[0]["status"] == "completed"
    assert results[0]["total_score"] == pytest.approx(0.625)
    assert results[0]["total_tokens"] == 13
    assert results[0]["evals_executions"][0]["score"] == pytest.approx(0.625)
    assert results[0]["evals_executions"][0]["total_tokens"] == 13

    agent_log = run_dir / "claude_code_main-integration.log"
    assert agent_log.is_file()
    log_contents = agent_log.read_text(encoding="utf-8")
    assert "arranged by main integration eval" in log_contents
    assert "acted by main integration eval" in log_contents

    output = capsys.readouterr().out
    assert "1 agent(s) completed, 0 failed" in output
    assert "results file saved" in output

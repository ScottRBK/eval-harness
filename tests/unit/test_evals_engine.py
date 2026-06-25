"""Unit tests for the evals engine.

Hermetic and CI-safe: ``DockerRunner`` is replaced with an in-memory recorder so
the docker daemon is never contacted, ``_load_eval_class`` is stubbed so no real
eval module is imported, and ``_method_to_script`` is stubbed to a deterministic
marker so script wiring can be asserted without ``inspect.getsource``. The few
tests that exercise the helpers directly stay pure (no docker, no real evals).

The suite guards the orchestration contract ``main.py`` relies on: per-agent
status transitions, score/time accumulation, and — critically — the number and
ordering of ``progress`` events the threaded drain loop consumes.
"""

import threading
from datetime import datetime
from queue import Queue
from types import SimpleNamespace
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor

import pytest
from agent_shell.models.agent import AgentType

from src.evals_engine import run_agent, run_session, _load_eval_class, _method_to_script
from src.models import (
    AgentConfig,
    AgentEvalExecution,
    AgentEvalStatus,
    Eval,
    EvalExecution,
)


# --------------------------------------------------------------------------- #
# Builders and test doubles
# --------------------------------------------------------------------------- #


def _make_aee(eval_dirs, agent_type=AgentType.CLAUDE_CODE, agent_model="model"):
    """An AgentEvalExecution with one pending EvalExecution per eval dir."""
    agent = AgentConfig(agent_type=agent_type, agent_model=agent_model)
    evals = [
        Eval(number=i, eval_dir=d, description=f"desc {d}", run_count=1, tags=[])
        for i, d in enumerate(eval_dirs)
    ]
    return AgentEvalExecution(
        agent_config=agent,
        total_score=0,
        total_tokens=0,
        total_time_taken_seconds=0,
        evals_executions=[
            EvalExecution(id=uuid4(), eval=e, agent_config=agent) for e in evals
        ],
        status=AgentEvalStatus.PENDING,
    )


def _drain(progress: Queue) -> list:
    """Empty a queue into a list without blocking."""
    items = []
    while not progress.empty():
        items.append(progress.get_nowait())
    return items


@pytest.fixture
def fake_runner(monkeypatch):
    """Install a recording stand-in for ``src.evals_engine.DockerRunner``.

    Call the returned factory with a list of per-eval results, where each result
    is either a ``(score, time_taken)`` tuple or an ``Exception`` to raise. The
    returned recorder exposes ``constructed`` (the (agent_type, agent_model) each
    runner was built with) and ``calls`` (the kwargs each ``docker_run`` saw).
    Index advancement is locked so the recorder is safe under concurrent agents.
    """

    def _install(results):
        recorder = SimpleNamespace(constructed=[], calls=[], results=list(results), idx=0)
        lock = threading.Lock()

        def _factory(agent_type, agent_model):
            recorder.constructed.append((agent_type, agent_model))

            def _docker_run(arrange_script, act_script, score_script, image):
                recorder.calls.append(
                    SimpleNamespace(
                        arrange=arrange_script,
                        act=act_script,
                        score=score_script,
                        image=image,
                    )
                )
                with lock:
                    result = recorder.results[recorder.idx]
                    recorder.idx += 1
                if isinstance(result, Exception):
                    raise result
                return result

            return SimpleNamespace(docker_run=_docker_run)

        monkeypatch.setattr("src.evals_engine.DockerRunner", _factory)
        return recorder

    return _install


@pytest.fixture
def fake_eval_loading(monkeypatch):
    """Stub eval-module loading + script building.

    ``_method_to_script`` becomes a deterministic ``script::<method>`` marker and
    ``_load_eval_class`` returns a namespace with arrange/act/score attributes.
    Pass ``image`` to give the fake module an ``image`` attribute; omit it to
    exercise the default-image path.
    """

    def _fake_method_to_script(method, embedded_values=None):
        return f"script::{method}"

    monkeypatch.setattr("src.evals_engine._method_to_script", _fake_method_to_script)

    def _install(image=None):
        mod = SimpleNamespace(arrange="ARRANGE", act="ACT", score="SCORE")
        if image is not None:
            mod.image = image
        monkeypatch.setattr("src.evals_engine._load_eval_class", lambda eval_dir: mod)
        return mod

    return _install


# --------------------------------------------------------------------------- #
# A. run_agent — orchestration over one agent's evals (single thread)
# --------------------------------------------------------------------------- #


class TestRunAgent:
    def test_marks_agent_completed(self, fake_runner, fake_eval_loading):
        # Arrange
        fake_eval_loading()
        fake_runner([(1.0, 1.0)])
        aee = _make_aee(["e1"])

        # Act
        run_agent(aee, Queue())

        # Assert
        assert aee.status == AgentEvalStatus.COMPLETED

    def test_accumulates_total_score(self, fake_runner, fake_eval_loading):
        # Arrange
        fake_eval_loading()
        fake_runner([(0.5, 1.0), (0.25, 1.0)])
        aee = _make_aee(["e1", "e2"])

        # Act
        run_agent(aee, Queue())

        # Assert
        assert aee.total_score == 0.75

    def test_sets_each_eval_execution_score(self, fake_runner, fake_eval_loading):
        # Arrange
        fake_eval_loading()
        fake_runner([(0.5, 1.0), (0.25, 1.0)])
        aee = _make_aee(["e1", "e2"])

        # Act
        run_agent(aee, Queue())

        # Assert
        assert [e.score for e in aee.evals_executions] == [0.5, 0.25]

    def test_accumulates_total_time(self, fake_runner, fake_eval_loading):
        # Arrange
        fake_eval_loading()
        fake_runner([(1.0, 2.0), (1.0, 3.5)])
        aee = _make_aee(["e1", "e2"])

        # Act
        run_agent(aee, Queue())

        # Assert
        assert aee.total_time_taken_seconds == 5.5
        assert [e.time_taken_seconds for e in aee.evals_executions] == [2.0, 3.5]

    def test_stamps_date_executed_on_each_eval(self, fake_runner, fake_eval_loading):
        # Arrange
        fake_eval_loading()
        fake_runner([(1.0, 1.0), (1.0, 1.0)])
        aee = _make_aee(["e1", "e2"])

        # Act
        run_agent(aee, Queue())

        # Assert
        assert all(isinstance(e.date_executed, datetime) for e in aee.evals_executions)

    def test_emits_update_per_phase_plus_bookends(self, fake_runner, fake_eval_loading):
        # Arrange — the contract main's drain loop depends on
        fake_eval_loading()
        fake_runner([(1.0, 1.0), (1.0, 1.0), (1.0, 1.0)])
        aee = _make_aee(["e1", "e2", "e3"])
        progress: Queue = Queue()

        # Act
        run_agent(aee, progress)

        # Assert — one update on entering, one per eval, one on completion (N + 2)
        assert _drain(progress) == ["update"] * 5

    def test_runs_one_docker_run_per_eval(self, fake_runner, fake_eval_loading):
        # Arrange
        fake_eval_loading()
        recorder = fake_runner([(1.0, 1.0), (1.0, 1.0), (1.0, 1.0)])
        aee = _make_aee(["e1", "e2", "e3"])

        # Act
        run_agent(aee, Queue())

        # Assert
        assert len(recorder.calls) == 3

    def test_builds_a_runner_per_eval_with_agent_identity(
        self, fake_runner, fake_eval_loading
    ):
        # Arrange
        fake_eval_loading()
        recorder = fake_runner([(1.0, 1.0), (1.0, 1.0)])
        aee = _make_aee(["e1", "e2"], agent_type=AgentType.OPENCODE, agent_model="m-x")

        # Act
        run_agent(aee, Queue())

        # Assert — every runner is built for this agent's type/model
        assert recorder.constructed == [(AgentType.OPENCODE, "m-x")] * 2

    def test_passes_three_distinct_phase_scripts(self, fake_runner, fake_eval_loading):
        # Arrange — guards the host/container split: arrange/act/score stay separate
        fake_eval_loading()
        recorder = fake_runner([(1.0, 1.0)])
        aee = _make_aee(["e1"])

        # Act
        run_agent(aee, Queue())

        # Assert
        call = recorder.calls[0]
        assert call.arrange == "script::ARRANGE"
        assert call.act == "script::ACT"
        assert call.score == "script::SCORE"

    def test_uses_eval_declared_image_when_present(self, fake_runner, fake_eval_loading):
        # Arrange
        fake_eval_loading(image="eval-harness-rust:latest")
        recorder = fake_runner([(1.0, 1.0)])
        aee = _make_aee(["e1"])

        # Act
        run_agent(aee, Queue())

        # Assert
        assert recorder.calls[0].image == "eval-harness-rust:latest"

    def test_defaults_image_when_eval_declares_none(self, fake_runner, fake_eval_loading):
        # Arrange — fake module has no ``image`` attribute
        fake_eval_loading()
        recorder = fake_runner([(1.0, 1.0)])
        aee = _make_aee(["e1"])

        # Act
        run_agent(aee, Queue())

        # Assert
        assert recorder.calls[0].image == "eval-harness:latest"


# --------------------------------------------------------------------------- #
# B. run_agent — failure behaviour
# --------------------------------------------------------------------------- #


class TestRunAgentFailure:
    def test_propagates_runner_exception(self, fake_runner, fake_eval_loading):
        # Arrange — so main's ``f.result()`` re-raises it on the main thread
        fake_eval_loading()
        fake_runner([RuntimeError("phase boom")])
        aee = _make_aee(["e1"])

        # Act / Assert
        with pytest.raises(RuntimeError, match="phase boom"):
            run_agent(aee, Queue())

    def test_failed_agent_marked_failed(self, fake_runner, fake_eval_loading):
        # Arrange
        fake_eval_loading()
        fake_runner([RuntimeError("phase boom")])
        aee = _make_aee(["e1"])

        # Act
        with pytest.raises(RuntimeError):
            run_agent(aee, Queue())

        # Assert
        assert aee.status == AgentEvalStatus.FAILED

    def test_failure_emits_final_update_for_the_display(
        self, fake_runner, fake_eval_loading
    ):
        # Arrange — the TUI must learn about the failure: one update on entry,
        # then one when the agent flips to FAILED.
        fake_eval_loading()
        fake_runner([RuntimeError("phase boom")])
        aee = _make_aee(["e1"])
        progress: Queue = Queue()

        # Act
        with pytest.raises(RuntimeError):
            run_agent(aee, progress)

        # Assert
        assert _drain(progress) == ["update", "update"]

    def test_stops_after_failing_eval(self, fake_runner, fake_eval_loading):
        # Arrange — second eval must not run once the first raises
        fake_eval_loading()
        recorder = fake_runner([RuntimeError("phase boom"), (1.0, 1.0)])
        aee = _make_aee(["e1", "e2"])

        # Act
        with pytest.raises(RuntimeError):
            run_agent(aee, Queue())

        # Assert — only the first eval was attempted
        assert len(recorder.calls) == 1
        assert aee.evals_executions[1].score is None


# --------------------------------------------------------------------------- #
# C. run_agent — concurrent agents (real threads, the way main runs it)
# --------------------------------------------------------------------------- #


class TestRunAgentConcurrency:
    def test_concurrent_agents_keep_independent_state(
        self, fake_runner, fake_eval_loading
    ):
        # Arrange — two agents, two evals each, run on a real pool sharing one queue
        fake_eval_loading()
        fake_runner([(1.0, 1.0)] * 4)
        progress: Queue = Queue()
        aee1 = _make_aee(["e1", "e2"], agent_model="m1")
        aee2 = _make_aee(["e3", "e4"], agent_model="m2")

        # Act
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run_agent, a, progress) for a in (aee1, aee2)]
            for f in futures:
                f.result()

        # Assert — each agent accumulated only its own scores, both completed
        assert aee1.status == AgentEvalStatus.COMPLETED
        assert aee2.status == AgentEvalStatus.COMPLETED
        assert aee1.total_score == 2.0
        assert aee2.total_score == 2.0
        # 2 agents * (2 evals + 2 bookends) updates land on the shared queue
        assert _drain(progress).count("update") == 8

    def test_one_failing_agent_does_not_sink_the_other(
        self, fake_runner, fake_eval_loading
    ):
        # Arrange — agent A's eval raises; agent B must still complete
        fake_eval_loading()
        # results are pulled in call order across both threads; all the same shape
        # except one raises, so whichever agent draws it fails and the other does not
        fake_runner([RuntimeError("boom"), (1.0, 1.0), (1.0, 1.0), (1.0, 1.0)])
        aee_a = _make_aee(["a1", "a2"], agent_model="A")
        aee_b = _make_aee(["b1", "b2"], agent_model="B")

        # Act
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {
                pool.submit(run_agent, a, Queue()): a for a in (aee_a, aee_b)
            }
            statuses = []
            errors = 0
            for f in futures:
                try:
                    f.result()
                    statuses.append(futures[f].status)
                except RuntimeError:
                    errors += 1

        # Assert — exactly one agent raised, the surviving one completed
        assert errors == 1
        assert AgentEvalStatus.COMPLETED in statuses


# --------------------------------------------------------------------------- #
# D. run_session — fans out agents, aggregates failures instead of panicking
# --------------------------------------------------------------------------- #


class TestRunSession:
    def test_returns_no_failures_when_all_agents_succeed(
        self, fake_runner, fake_eval_loading
    ):
        # Arrange
        fake_eval_loading()
        fake_runner([(1.0, 1.0), (1.0, 1.0)])
        agents = [_make_aee(["e1"], agent_model="m1"), _make_aee(["e2"], agent_model="m2")]

        # Act
        failed = run_session(agents, on_update=lambda: None, max_workers=2)

        # Assert
        assert failed == []
        assert all(a.status == AgentEvalStatus.COMPLETED for a in agents)

    def test_does_not_raise_when_an_agent_fails(self, fake_runner, fake_eval_loading):
        # Arrange — one agent's eval raises; the other succeeds
        fake_eval_loading()
        fake_runner([RuntimeError("boom"), (1.0, 1.0)])
        agents = [_make_aee(["e1"], agent_model="m1"), _make_aee(["e2"], agent_model="m2")]

        # Act — must return, not propagate
        failed = run_session(agents, on_update=lambda: None, max_workers=2)

        # Assert — the failure is collected, the survivor completes
        assert len(failed) == 1
        assert failed[0].status == AgentEvalStatus.FAILED
        completed = [a for a in agents if a.status == AgentEvalStatus.COMPLETED]
        assert len(completed) == 1

    def test_collects_every_failure_not_just_the_first(
        self, fake_runner, fake_eval_loading
    ):
        # Arrange — both agents fail; the old `f.result()` lost all but the first
        fake_eval_loading()
        fake_runner([RuntimeError("boom-1"), RuntimeError("boom-2")])
        agents = [_make_aee(["e1"], agent_model="m1"), _make_aee(["e2"], agent_model="m2")]

        # Act
        failed = run_session(agents, on_update=lambda: None, max_workers=2)

        # Assert
        assert len(failed) == 2
        assert all(a.status == AgentEvalStatus.FAILED for a in failed)

    def test_invokes_on_update_for_each_progress_event(
        self, fake_runner, fake_eval_loading
    ):
        # Arrange — one agent, two evals: N + 2 = 4 progress events
        fake_eval_loading()
        fake_runner([(1.0, 1.0), (1.0, 1.0)])
        agent = _make_aee(["e1", "e2"])
        calls = []

        # Act
        run_session([agent], on_update=lambda: calls.append(1), max_workers=1)

        # Assert
        assert len(calls) == 4


# --------------------------------------------------------------------------- #
# E. _method_to_script — pure script builder
# --------------------------------------------------------------------------- #


def _sample_method(self):
    value = 41
    return value + 1


class TestMethodToScript:
    def test_wraps_body_in_async_main_runner(self):
        # Act
        script = _method_to_script(_sample_method)

        # Assert
        assert "async def _main():" in script
        assert script.strip().endswith("asyncio.run(_main())")

    def test_drops_signature_but_keeps_body(self):
        # Act
        script = _method_to_script(_sample_method)

        # Assert — body survives, the `def` signature line does not
        assert "value = 41" in script
        assert "def _sample_method" not in script

    def test_embeds_values_as_repr_constants(self):
        # Act — embedded values are injected as assignments using repr()
        script = _method_to_script(_sample_method, embedded_values={"ANSWER": "secret"})

        # Assert
        assert "ANSWER = 'secret'" in script


# --------------------------------------------------------------------------- #
# F. _load_eval_class — dir -> class-name convention (importlib stubbed)
# --------------------------------------------------------------------------- #


class TestLoadEvalClass:
    def test_derives_pascal_case_class_name_from_dir(self, monkeypatch):
        # Arrange — capture the import target, return a module exposing the class
        captured = {}
        module = SimpleNamespace(SaleorSpreeMapping="THE_CLASS")

        def _fake_import(name):
            captured["name"] = name
            return module

        monkeypatch.setattr("src.evals_engine.importlib.import_module", _fake_import)

        # Act
        result = _load_eval_class("saleor_spree_mapping")

        # Assert
        assert captured["name"] == "src.evals.saleor_spree_mapping"
        assert result == "THE_CLASS"

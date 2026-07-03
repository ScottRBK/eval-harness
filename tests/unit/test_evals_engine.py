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

import logging
import threading
import time
from datetime import datetime
from queue import Queue
from types import SimpleNamespace
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor

import pytest
from agent_shell.models.agent import AgentType, HealthCheckResult

from src.evals_engine import run_agent, run_session, _load_eval_class, _method_to_script
from src.models import (
    AgentConfig,
    AgentEvalExecution,
    AgentEvalStatus,
    DockerRunResult,
    Eval,
    EvalExecution,
)


# --------------------------------------------------------------------------- #
# Builders and test doubles
# --------------------------------------------------------------------------- #


def _make_aee(
    eval_dirs,
    agent_type=AgentType.CLAUDE_CODE,
    agent_model="model",
    processing_group=None,
    effort=None,
    run_count=1,
):
    """An AgentEvalExecution with one pending EvalExecution per eval dir."""
    agent = AgentConfig(
        agent_type=agent_type,
        agent_model=agent_model,
        effort=effort,
        processing_group=processing_group,
    )
    evals = [
        Eval(number=i, eval_dir=d, description=f"desc {d}", run_count=run_count, tags=[])
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
    is either a ``(score, time_taken)``, ``(score, time_taken, total_tokens)``
    tuple or an ``Exception`` to raise. The
    returned recorder exposes ``constructed`` (the (agent_type, agent_model) each
    runner was built with), ``efforts`` (the agent_effort each runner was built
    with) and ``calls`` (the kwargs each ``docker_run`` saw).
    Index advancement is locked so the recorder is safe under concurrent agents.

    Each returned runner also exposes a ``health_check`` stub defaulting to a
    healthy verdict. A test can flip ``recorder.health_result`` to a
    ``HealthCheckResult(healthy=False, ...)`` (the probe returns it; run_agent
    marks the agent UNHEALTHY and skips all evals) or an ``Exception`` (the
    probe raises; run_agent marks the agent FAILED and re-raises).
    """

    def _install(results):
        recorder = SimpleNamespace(
            constructed=[],
            efforts=[],
            session_ids=[],
            calls=[],
            results=list(results),
            idx=0,
            health_calls=[],
            health_result=HealthCheckResult(healthy=True),
        )
        lock = threading.Lock()

        def _factory(agent_type, agent_model, agent_effort=None, logger=None, session_id=None):
            recorder.constructed.append((agent_type, agent_model))
            recorder.efforts.append(agent_effort)
            recorder.session_ids.append(session_id)

            def _health_check(image):
                recorder.health_calls.append(image)
                if isinstance(recorder.health_result, Exception):
                    raise recorder.health_result
                return recorder.health_result

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
                if isinstance(result, tuple):
                    if len(result) == 2:
                        score, time_taken = result
                        return DockerRunResult(
                            score=score,
                            time_taken_seconds=time_taken,
                            total_tokens=0,
                        )
                    if len(result) == 3:
                        score, time_taken, total_tokens = result
                        return DockerRunResult(
                            score=score,
                            time_taken_seconds=time_taken,
                            total_tokens=total_tokens,
                        )
                return result

            return SimpleNamespace(docker_run=_docker_run, health_check=_health_check)

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
# Processing-group scheduler probe
# --------------------------------------------------------------------------- #


@pytest.fixture
def recording_run_agent(monkeypatch):
    """Replace ``run_agent`` with a recorder so ``run_session``'s *scheduling* can
    be asserted without Docker.

    The real ``run_agent`` drives a container, so we substitute it at the module
    boundary ``run_session`` resolves it from and observe which agents run, in what
    order, and — the point of the feature — which run concurrently.

    ``install(...)`` configures the stand-in and returns a recorder exposing:
      - ``entries``     (processing_group, agent_model) in the order agents start
      - ``completed``   agent_models that finished without raising
      - ``max_active``  processing_group -> peak number running at once

    Knobs:
      - ``hold``        seconds each agent stays "running" — an overlap window, so
                        a bug that runs one group in parallel is actually observable
      - ``barrier``     a ``threading.Barrier`` each agent waits on, to prove N
                        agents are genuinely in flight together (else it times out)
      - ``fail_models`` agent_models whose run marks the aee FAILED then raises,
                        mirroring the real ``run_agent`` failure contract
    """
    recorder = SimpleNamespace(entries=[], completed=[], active={}, max_active={})
    lock = threading.Lock()

    def _install(hold=0.0, barrier=None, fail_models=()):
        def _fake_run_agent(aee, progress, run_dir=None, session_id=None):
            group = aee.agent_config.processing_group
            model = aee.agent_config.agent_model
            with lock:
                recorder.entries.append((group, model))
                recorder.active[group] = recorder.active.get(group, 0) + 1
                recorder.max_active[group] = max(
                    recorder.max_active.get(group, 0), recorder.active[group]
                )
            try:
                if barrier is not None:
                    barrier.wait(timeout=5)
                if hold:
                    time.sleep(hold)
                if model in fail_models:
                    aee.status = AgentEvalStatus.FAILED
                    progress.put("update")
                    raise RuntimeError(f"{model} boom")
                aee.status = AgentEvalStatus.COMPLETED
                recorder.completed.append(model)
                progress.put("update")
            finally:
                with lock:
                    recorder.active[group] -= 1

        monkeypatch.setattr("src.evals_engine.run_agent", _fake_run_agent)
        return recorder

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

    def test_accumulates_total_tokens(self, fake_runner, fake_eval_loading):
        # Arrange
        fake_eval_loading()
        fake_runner([(1.0, 2.0, 10), (1.0, 3.5, 15)])
        aee = _make_aee(["e1", "e2"])

        # Act
        run_agent(aee, Queue())

        # Assert
        assert aee.total_tokens == 25
        assert [e.total_tokens for e in aee.evals_executions] == [10, 15]

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

        # Assert — the pre-flight health probe + one per-eval runner, all built
        # for this agent's type/model
        assert recorder.constructed == [(AgentType.OPENCODE, "m-x")] * 3

    def test_forwards_agent_effort_to_the_runner(self, fake_runner, fake_eval_loading):
        # Arrange — the configured reasoning effort must reach DockerRunner, which
        # forwards it to the container as AGENT_EFFORT for the agent to consume
        fake_eval_loading()
        recorder = fake_runner([(1.0, 1.0)])
        aee = _make_aee(["e1"], effort="high")

        # Act
        run_agent(aee, Queue())

        # Assert — the health probe + the per-eval runner both carry the effort
        assert recorder.efforts == ["high", "high"]

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
# A2. run_agent — repeats each eval run_count times and aggregates
# --------------------------------------------------------------------------- #


class TestRunAgentRunCount:
    def test_runs_docker_run_once_per_run_count(self, fake_runner, fake_eval_loading):
        # Arrange — one eval, run_count=3 → three independent containers
        fake_eval_loading()
        recorder = fake_runner([(0.6, 1.0), (0.9, 1.0), (0.3, 1.0)])
        aee = _make_aee(["e1"], run_count=3)

        # Act
        run_agent(aee, Queue())

        # Assert
        assert len(recorder.calls) == 3

    def test_averages_score_across_runs(self, fake_runner, fake_eval_loading):
        # Arrange — 0.3/0.9/0.6 average to 0.6; first run (0.3) differs from the
        # mean so this fails if we ever keep only one run's score
        fake_eval_loading()
        fake_runner([(0.3, 1.0), (0.9, 1.0), (0.6, 1.0)])
        aee = _make_aee(["e1"], run_count=3)

        # Act
        run_agent(aee, Queue())

        # Assert
        assert aee.evals_executions[0].score == pytest.approx(0.6)
        assert aee.total_score == pytest.approx(0.6)

    def test_sums_tokens_across_runs(self, fake_runner, fake_eval_loading):
        # Arrange — 10/15/5 total 30 (a TOTAL, never an average)
        fake_eval_loading()
        fake_runner([(1.0, 1.0, 10), (1.0, 1.0, 15), (1.0, 1.0, 5)])
        aee = _make_aee(["e1"], run_count=3)

        # Act
        run_agent(aee, Queue())

        # Assert
        assert aee.evals_executions[0].total_tokens == 30
        assert aee.total_tokens == 30

    def test_sums_time_across_runs(self, fake_runner, fake_eval_loading):
        # Arrange — 2.0/3.0/1.5 total 6.5 (real wall time accrued)
        fake_eval_loading()
        fake_runner([(1.0, 2.0), (1.0, 3.0), (1.0, 1.5)])
        aee = _make_aee(["e1"], run_count=3)

        # Act
        run_agent(aee, Queue())

        # Assert
        assert aee.evals_executions[0].time_taken_seconds == pytest.approx(6.5)
        assert aee.total_time_taken_seconds == pytest.approx(6.5)

    def test_total_score_sums_per_eval_means(self, fake_runner, fake_eval_loading):
        # Arrange — two evals, run_count=2:
        # e1 runs 0.4/0.8 → mean 0.6 ; e2 runs 1.0/0.0 → mean 0.5
        fake_eval_loading()
        fake_runner([(0.4, 1.0), (0.8, 1.0), (1.0, 1.0), (0.0, 1.0)])
        aee = _make_aee(["e1", "e2"], run_count=2)

        # Act
        run_agent(aee, Queue())

        # Assert — agent total is the sum of per-eval means
        assert [e.score for e in aee.evals_executions] == pytest.approx([0.6, 0.5])
        assert aee.total_score == pytest.approx(1.1)

    def test_emits_one_update_per_eval_not_per_run(self, fake_runner, fake_eval_loading):
        # Arrange — one eval at run_count=3 still emits entry + 1 + completion
        fake_eval_loading()
        fake_runner([(1.0, 1.0), (1.0, 1.0), (1.0, 1.0)])
        aee = _make_aee(["e1"], run_count=3)
        progress: Queue = Queue()

        # Act
        run_agent(aee, progress)

        # Assert — progress is per-eval, not per-run (3, not 5)
        assert _drain(progress) == ["update"] * 3


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
# B2. run_agent — health check integration (UNHEALTHY vs FAILED split)
# --------------------------------------------------------------------------- #


class TestRunAgentHealthCheck:
    """The pre-flight probe decides, before any eval runs, whether the agent is
    reachable. The two outcomes must land in distinct statuses:

      - probe returns unhealthy -> agent UNHEALTHY, no evals run, no raise
      - probe raises            -> agent FAILED, re-raised so run_session collects it

    E3 pins the clean-return decision: had run_agent raised on unhealthy, the
    except block would have clobbered UNHEALTHY -> FAILED -- exactly the bug the
    split exists to avoid. E5 pins the other half: real infra failure still
    propagates as FAILED.
    """

    def test_unhealthy_probe_marks_agent_unhealthy_and_skips_evals(
        self, fake_runner, fake_eval_loading
    ):
        # Arrange — probe returns unhealthy; one eval would otherwise run
        fake_eval_loading()
        recorder = fake_runner([(1.0, 1.0)])
        recorder.health_result = HealthCheckResult(healthy=False, exception="backend down")
        aee = _make_aee(["e1"])
        progress: Queue = Queue()

        # Act — must NOT raise; a raise would let the except block overwrite
        # UNHEALTHY with FAILED, collapsing the distinction the split exists for.
        run_agent(aee, progress)

        # Assert
        assert aee.status == AgentEvalStatus.UNHEALTHY
        # probe ran once, against the base image; no eval containers were started
        assert recorder.health_calls == ["eval-harness:latest"]
        assert recorder.calls == []

    def test_probe_raising_marks_failed_and_propagates(
        self, fake_runner, fake_eval_loading
    ):
        # Arrange — a real infra failure (missing image, exec crash) raises out
        # of the probe rather than returning an unhealthy verdict; run_agent must
        # mark FAILED and re-raise so run_session can collect the failure.
        fake_eval_loading()
        recorder = fake_runner([(1.0, 1.0)])
        recorder.health_result = RuntimeError("probe boom")
        aee = _make_aee(["e1"])

        # Act / Assert
        with pytest.raises(RuntimeError, match="probe boom"):
            run_agent(aee, Queue())
        assert aee.status == AgentEvalStatus.FAILED
        assert recorder.calls == []  # no evals ran


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
# D2. run_session — UNHEALTHY surfaces distinctly from FAILED
# --------------------------------------------------------------------------- #


class TestRunSessionHealthSplit:
    """The point of the new UNHEALTHY status: a caller can tell 'model backend
    down' from 'eval code crashed'. An unhealthy agent and a failed agent in the
    same session must both surface in the returned list with their distinct
    statuses, while a healthy agent is excluded.

    Uses ``recording_run_agent`` (which swaps in a fake ``run_agent``), so the
    probe/docker layer is bypassed entirely and the test asserts purely on what
    ``run_session``'s return filter does with the statuses the chain sets.
    """

    def test_unhealthy_and_failed_agents_both_surface_with_distinct_statuses(
        self, monkeypatch
    ):
        # Arrange — three agents: one completes, one comes back UNHEALTHY, one
        # comes back FAILED. Mirror run_agent's real contract: failed raises
        # (so _run_chain logs and swallows it), unhealthy returns cleanly with
        # the status already set (so _run_chain logs the 'skipped' line).
        def _per_model_run_agent(aee, progress, run_dir=None, session_id=None):
            model = aee.agent_config.agent_model
            aee.status = {
                "ok-model": AgentEvalStatus.COMPLETED,
                "down-model": AgentEvalStatus.UNHEALTHY,
                "fail-model": AgentEvalStatus.FAILED,
            }[model]
            progress.put("update")
            if model == "fail-model":
                raise RuntimeError("eval crash")

        monkeypatch.setattr("src.evals_engine.run_agent", _per_model_run_agent)

        healthy = _make_aee(["e_h"], agent_model="ok-model")
        unhealthy = _make_aee(["e_u"], agent_model="down-model")
        failed = _make_aee(["e_f"], agent_model="fail-model")

        # Act
        returned = run_session(
            [healthy, unhealthy, failed], on_update=lambda: None, max_workers=3
        )

        # Assert — the failed and unhealthy agents are both returned, each with
        # its own status; the healthy agent is excluded.
        by_model = {a.agent_config.agent_model: a for a in returned}
        assert set(by_model) == {"down-model", "fail-model"}
        assert by_model["down-model"].status == AgentEvalStatus.UNHEALTHY
        assert by_model["fail-model"].status == AgentEvalStatus.FAILED
        assert healthy.status == AgentEvalStatus.COMPLETED


# --------------------------------------------------------------------------- #
# E. _method_to_script — pure script builder
# --------------------------------------------------------------------------- #


def _sample_method(self):
    value = 41
    return value + 1


def _identity_decorator(func):
    return func


@_identity_decorator
def _decorated_sample_method(self):
    value = "decorated"
    return value


def _multi_line_signature_method(
    self,
    answer=42,
):
    return answer


def _one_line_sample_method(self): return 42


def _leading_comment_sample_method(self):
    # This comment should stay inside the generated script body.
    return 42


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

    def test_rejects_invalid_embedded_value_names(self):
        # Act / Assert
        with pytest.raises(ValueError, match="Invalid embedded value name"):
            _method_to_script(_sample_method, embedded_values={"not-valid": "secret"})

    def test_injects_agent_shell_token_tracker(self):
        # Act
        script = _method_to_script(_sample_method)

        # Assert
        assert "AgentShell as _EvalHarnessAgentShell" in script
        assert "EVAL_TOTAL_TOKENS=" in script
        assert "response.output_tokens" in script

    def test_extracts_decorated_method_body(self):
        # Act
        script = _method_to_script(_decorated_sample_method)

        # Assert
        assert 'value = "decorated"' in script
        assert "@_identity_decorator" not in script
        assert "def _decorated_sample_method" not in script

    def test_extracts_multi_line_signature_method_body(self):
        # Act
        script = _method_to_script(_multi_line_signature_method)

        # Assert
        assert "return answer" in script
        assert "def _multi_line_signature_method" not in script

    def test_extracts_one_line_method_body(self):
        # Act
        script = _method_to_script(_one_line_sample_method)

        # Assert
        assert "return 42" in script
        assert "def _one_line_sample_method" not in script

    def test_preserves_leading_body_comments(self):
        # Act
        script = _method_to_script(_leading_comment_sample_method)

        # Assert
        assert "# This comment should stay inside the generated script body." in script
        assert "return 42" in script


# --------------------------------------------------------------------------- #
# F. _load_eval_class — dir -> class-name convention (importlib stubbed)
# --------------------------------------------------------------------------- #


class TestLoadEvalClass:
    def test_derives_pascal_case_class_name_from_dir(self, monkeypatch):
        # Arrange — capture the import target, return a module exposing the class
        class SaleorSpreeMapping:
            async def arrange(self): ...
            async def act(self): ...
            async def score(self): ...

        captured = {}
        module = SimpleNamespace(SaleorSpreeMapping=SaleorSpreeMapping)

        def _fake_import(name):
            captured["name"] = name
            return module

        monkeypatch.setattr("src.evals_engine.importlib.import_module", _fake_import)

        # Act
        result = _load_eval_class("saleor_spree_mapping")

        # Assert
        assert captured["name"] == "example_evals.saleor_spree_mapping"
        assert result is SaleorSpreeMapping

    def test_rejects_class_missing_a_phase(self, monkeypatch):
        # Arrange — satisfies arrange/act but not score
        class SaleorSpreeMapping:
            async def arrange(self): ...
            async def act(self): ...

        module = SimpleNamespace(SaleorSpreeMapping=SaleorSpreeMapping)
        monkeypatch.setattr(
            "src.evals_engine.importlib.import_module", lambda name: module
        )

        # Act / Assert
        with pytest.raises(TypeError, match="must be a class implementing"):
            _load_eval_class("saleor_spree_mapping")

    def test_rejects_non_class_attribute(self, monkeypatch):
        # Arrange — the resolved attribute is not a class at all
        module = SimpleNamespace(SaleorSpreeMapping="THE_CLASS")
        monkeypatch.setattr(
            "src.evals_engine.importlib.import_module", lambda name: module
        )

        # Act / Assert
        with pytest.raises(TypeError, match="must be a class implementing"):
            _load_eval_class("saleor_spree_mapping")


# --------------------------------------------------------------------------- #
# G. run_session — processing groups (serialise within a group, parallel across)
# --------------------------------------------------------------------------- #


class TestProcessingGroups:
    def test_agents_in_the_same_group_never_run_concurrently(
        self, recording_run_agent
    ):
        # Arrange — two agents pinned to one shared backend ("bosman-server").
        # max_workers is generous so only the grouping, not the pool size, can
        # keep them apart.
        recorder = recording_run_agent(hold=0.05)
        agents = [
            _make_aee(["e1"], agent_model="b1", processing_group="bosman-server"),
            _make_aee(["e2"], agent_model="b2", processing_group="bosman-server"),
        ]

        # Act
        run_session(agents, on_update=lambda: None, max_workers=4)

        # Assert — never more than one of the group running at any instant
        assert recorder.max_active["bosman-server"] == 1

    def test_agents_in_different_groups_run_concurrently(self, recording_run_agent):
        # Arrange — distinct groups must NOT serialise against each other. The
        # barrier only releases if both agents are in flight together.
        barrier = threading.Barrier(2)
        recorder = recording_run_agent(barrier=barrier)
        agents = [
            _make_aee(["e1"], agent_model="a", processing_group="ai-server"),
            _make_aee(["e2"], agent_model="b", processing_group="bosman-server"),
        ]

        # Act
        run_session(agents, on_update=lambda: None, max_workers=4)

        # Assert — both reached the barrier, so both ran at the same time
        assert set(recorder.completed) == {"a", "b"}

    def test_ungrouped_agents_run_concurrently(self, recording_run_agent):
        # Arrange — the default path: agents with no group must each run freely,
        # never collapsed together into one serial chain.
        barrier = threading.Barrier(3)
        recorder = recording_run_agent(barrier=barrier)
        agents = [
            _make_aee(["e1"], agent_model="haiku"),
            _make_aee(["e2"], agent_model="sonnet"),
            _make_aee(["e3"], agent_model="opus"),
        ]

        # Act
        run_session(agents, on_update=lambda: None, max_workers=4)

        # Assert
        assert set(recorder.completed) == {"haiku", "sonnet", "opus"}

    def test_a_group_runs_its_agents_in_submission_order(self, recording_run_agent):
        # Arrange — within a group, order is deterministic: first listed runs first
        recorder = recording_run_agent(hold=0.01)
        agents = [
            _make_aee(["e1"], agent_model="first", processing_group="g"),
            _make_aee(["e2"], agent_model="second", processing_group="g"),
            _make_aee(["e3"], agent_model="third", processing_group="g"),
        ]

        # Act
        run_session(agents, on_update=lambda: None, max_workers=4)

        # Assert
        assert [model for _, model in recorder.entries] == ["first", "second", "third"]

    def test_failure_in_a_group_is_isolated_and_still_reported(
        self, recording_run_agent
    ):
        # Arrange — the first agent in a group fails; the rest of the group must
        # still run, and the failure must still surface in the returned list.
        recorder = recording_run_agent(fail_models={"b1"})
        agents = [
            _make_aee(["e1"], agent_model="b1", processing_group="bosman-server"),
            _make_aee(["e2"], agent_model="b2", processing_group="bosman-server"),
        ]

        # Act
        failed = run_session(agents, on_update=lambda: None, max_workers=4)

        # Assert — survivor ran despite the earlier failure; failure aggregated
        assert "b2" in recorder.completed
        assert [a.agent_config.agent_model for a in failed] == ["b1"]

    def test_failure_emits_a_session_level_log_line(self, recording_run_agent, caplog):
        # Arrange — the one-line summary the old future.exception() collector used
        # to emit must still reach the module logger (session.log) now that the
        # chain swallows the exception to stay cascade-free.
        recording_run_agent(fail_models={"b1"})
        agents = [
            _make_aee(["e1"], agent_model="b1", processing_group="bosman-server"),
            _make_aee(["e2"], agent_model="b2", processing_group="bosman-server"),
        ]

        # Act
        with caplog.at_level(logging.ERROR, logger="src.evals_engine"):
            run_session(agents, on_update=lambda: None, max_workers=4)

        # Assert — the failed agent is named in an ERROR record; the survivor is not
        failure_logs = [
            record.getMessage()
            for record in caplog.records
            if record.levelno == logging.ERROR and "failed" in record.getMessage().lower()
        ]
        assert any("b1" in message for message in failure_logs)
        assert not any("b2" in message for message in failure_logs)

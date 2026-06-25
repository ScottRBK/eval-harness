"""Unit tests for logging_config.

Filesystem-touching but hermetic: every run is redirected into a pytest
``tmp_path`` via the ``OUTPUT_DIR`` setting, and an autouse fixture restores the
global logging state (root handlers/level + the ``eval.agent.*`` loggers) after
each test so handlers never leak between tests or hold files open.
"""

import logging
from uuid import uuid4

import pytest
from agent_shell.models.agent import AgentType

from src.logging_config import agent_label, agent_logger, configure_logging
from src.models import AgentConfig


@pytest.fixture(autouse=True)
def _isolate_logging():
    """Snapshot global logging state and tear down anything a test adds."""
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level

    yield

    for handler in root.handlers[:]:
        if handler not in saved_handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(saved_level)

    for name in list(logging.root.manager.loggerDict):
        if name.startswith("eval.agent."):
            log = logging.getLogger(name)
            for handler in log.handlers[:]:
                log.removeHandler(handler)
                handler.close()


@pytest.fixture
def output_dir(tmp_path, monkeypatch):
    """Point OUTPUT_DIR at a throwaway dir so runs never touch the real tree."""
    monkeypatch.setattr("src.logging_config.settings.OUTPUT_DIR", str(tmp_path))
    return tmp_path


def _cfg(agent_type=AgentType.CLAUDE_CODE, agent_model="haiku", effort=None):
    return AgentConfig(agent_type=agent_type, agent_model=agent_model, effort=effort)


# --------------------------------------------------------------------------- #
# agent_label
# --------------------------------------------------------------------------- #


class TestAgentLabel:
    def test_joins_type_and_model(self):
        assert agent_label(_cfg(agent_model="haiku")) == "claude_code_haiku"

    def test_includes_effort_when_present(self):
        assert agent_label(_cfg(agent_model="gpt5", effort="high")) == "claude_code_gpt5_high"


# --------------------------------------------------------------------------- #
# configure_logging
# --------------------------------------------------------------------------- #


class TestConfigureLogging:
    def test_creates_run_dir_under_output_dir(self, output_dir):
        # Act
        run_dir = configure_logging(uuid4())

        # Assert
        assert run_dir.parent == output_dir
        assert run_dir.is_dir()

    def test_session_log_captures_root_records(self, output_dir):
        # Arrange
        run_dir = configure_logging(uuid4())

        # Act
        logging.getLogger("anything").warning("hello-session")
        logging.shutdown()  # flush handlers

        # Assert
        assert "hello-session" in (run_dir / "session.log").read_text()


# --------------------------------------------------------------------------- #
# agent_logger
# --------------------------------------------------------------------------- #


class TestAgentLogger:
    def test_writes_to_per_agent_file(self, output_dir):
        # Arrange
        run_dir = configure_logging(uuid4())
        cfg = _cfg(agent_model="haiku")

        # Act
        agent_logger(cfg, run_dir).info("only-haiku")
        logging.shutdown()

        # Assert
        assert "only-haiku" in (run_dir / "claude_code_haiku.log").read_text()

    def test_agent_record_also_reaches_session_log(self, output_dir):
        # Arrange — per-agent loggers propagate, so session.log is the catch-all
        run_dir = configure_logging(uuid4())

        # Act
        agent_logger(_cfg(agent_model="haiku"), run_dir).info("bubbles-up")
        logging.shutdown()

        # Assert
        assert "bubbles-up" in (run_dir / "session.log").read_text()

    def test_two_agents_get_separate_files(self, output_dir):
        # Arrange
        run_dir = configure_logging(uuid4())

        # Act
        agent_logger(_cfg(agent_model="haiku"), run_dir).info("for-haiku")
        agent_logger(_cfg(agent_model="sonnet"), run_dir).info("for-sonnet")
        logging.shutdown()

        # Assert — each file holds only its own agent's record
        haiku = (run_dir / "claude_code_haiku.log").read_text()
        sonnet = (run_dir / "claude_code_sonnet.log").read_text()
        assert "for-haiku" in haiku and "for-sonnet" not in haiku
        assert "for-sonnet" in sonnet and "for-haiku" not in sonnet

    def test_is_idempotent_no_duplicate_handlers(self, output_dir):
        # Arrange — a reused worker thread calls agent_logger again for the same agent
        run_dir = configure_logging(uuid4())
        cfg = _cfg(agent_model="haiku")

        # Act
        first = agent_logger(cfg, run_dir)
        second = agent_logger(cfg, run_dir)

        # Assert — same logger, one file handler (no double-logging)
        assert first is second
        assert len(first.handlers) == 1

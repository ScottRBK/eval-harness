"""Unit tests for logging_config.

Filesystem-touching but hermetic: every run is redirected into a pytest
``tmp_path`` via the ``OUTPUT_DIR`` setting, and an autouse fixture restores the
global logging state (root handlers/level + the ``eval.agent.*`` loggers) after
each test so handlers never leak between tests or hold files open.
"""

import logging

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
def run_dir(tmp_path):
    """Provide a throwaway directory for one logging session."""
    return tmp_path / "run"


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
    def test_creates_and_yields_run_dir(self, run_dir):
        # Arrange
        assert not run_dir.exists()

        # Act
        with configure_logging(run_dir) as configured_run_dir:
            yielded_run_dir = configured_run_dir

        # Assert
        assert yielded_run_dir == run_dir
        assert run_dir.is_dir()

    def test_session_log_captures_root_records(self, run_dir):
        # Arrange
        message = "hello-session"

        # Act
        with configure_logging(run_dir):
            logging.getLogger("anything").warning(message)

        # Assert
        assert message in (run_dir / "session.log").read_text()

    def test_removes_session_handler_on_exit(self, run_dir):
        # Arrange
        root = logging.getLogger()
        original_handlers = root.handlers[:]

        # Act
        with configure_logging(run_dir):
            added_handlers = [
                handler for handler in root.handlers if handler not in original_handlers
            ]

        # Assert
        assert len(added_handlers) == 1
        assert added_handlers[0] not in root.handlers


# --------------------------------------------------------------------------- #
# agent_logger
# --------------------------------------------------------------------------- #


class TestAgentLogger:
    def test_writes_to_per_agent_file(self, run_dir):
        # Arrange
        cfg = _cfg(agent_model="haiku")
        message = "only-haiku"

        # Act
        with configure_logging(run_dir):
            agent_logger(cfg, run_dir).info(message)

        # Assert
        assert message in (run_dir / "claude_code_haiku.log").read_text()

    def test_agent_record_also_reaches_session_log(self, run_dir):
        # Arrange 
        message = "bubbles-up"

        # Act
        with configure_logging(run_dir):
            agent_logger(_cfg(agent_model="haiku"), run_dir).info(message)

        # Assert
        assert message in (run_dir / "session.log").read_text()

    def test_two_agents_get_separate_files(self, run_dir):
        # Arrange
        haiku_message = "for-haiku"
        sonnet_message = "for-sonnet"

        # Act
        with configure_logging(run_dir):
            agent_logger(_cfg(agent_model="haiku"), run_dir).info(haiku_message)
            agent_logger(_cfg(agent_model="sonnet"), run_dir).info(sonnet_message)

        # Assert — each file holds only its own agent's record
        haiku = (run_dir / "claude_code_haiku.log").read_text()
        sonnet = (run_dir / "claude_code_sonnet.log").read_text()
        assert haiku_message in haiku and sonnet_message not in haiku
        assert sonnet_message in sonnet and haiku_message not in sonnet

    def test_is_idempotent_no_duplicate_handlers(self, run_dir):
        # Arrange 
        cfg = _cfg(agent_model="haiku")

        # Act
        with configure_logging(run_dir):
            first = agent_logger(cfg, run_dir)
            second = agent_logger(cfg, run_dir)
            handler_count = len(first.handlers)

        # Assert 
        assert first is second
        assert handler_count == 1

    def test_removes_agent_handler_on_context_exit(self, run_dir):
        # Arrange
        cfg = _cfg(agent_model="haiku")

        # Act
        with configure_logging(run_dir):
            log = agent_logger(cfg, run_dir)
            handler_count_during_run = len(log.handlers)
        handler_count_after_run = len(log.handlers)

        # Assert
        assert handler_count_during_run == 1
        assert handler_count_after_run == 0

    def test_same_agent_writes_to_separate_session_files(self, run_dir):
        # Arrange
        cfg = _cfg(agent_model="haiku")
        first_run_dir = run_dir.parent / "first-run"
        second_run_dir = run_dir.parent / "second-run"
        first_message = "first-session"
        second_message = "second-session"

        # Act
        with configure_logging(first_run_dir):
            agent_logger(cfg, first_run_dir).info(first_message)
        with configure_logging(second_run_dir):
            agent_logger(cfg, second_run_dir).info(second_message)

        # Assert
        first_log = (first_run_dir / "claude_code_haiku.log").read_text()
        second_log = (second_run_dir / "claude_code_haiku.log").read_text()
        assert first_message in first_log
        assert second_message not in first_log
        assert second_message in second_log
        assert first_message not in second_log

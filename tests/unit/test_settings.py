from src.config.settings import Settings


def test_capture_failure_diagnostics_defaults_off_and_reads_boolean_environment(monkeypatch):
    # Arrange
    monkeypatch.delenv("EVAL_HARNESS_CAPTURE_FAILURE_DIAGNOSTICS", raising=False)

    # Act
    default_settings = Settings(_env_file=None)
    monkeypatch.setenv("EVAL_HARNESS_CAPTURE_FAILURE_DIAGNOSTICS", "true")
    enabled_settings = Settings(_env_file=None)
    monkeypatch.setenv("EVAL_HARNESS_CAPTURE_FAILURE_DIAGNOSTICS", "false")
    disabled_settings = Settings(_env_file=None)

    # Assert
    assert default_settings.CAPTURE_FAILURE_DIAGNOSTICS is False
    assert enabled_settings.CAPTURE_FAILURE_DIAGNOSTICS is True
    assert disabled_settings.CAPTURE_FAILURE_DIAGNOSTICS is False


def test_agent_pid_namespace_isolation_defaults_off_and_reads_boolean_environment(monkeypatch):
    # Arrange
    variable = "EVAL_HARNESS_AGENT_PID_NAMESPACE_ISOLATION"
    monkeypatch.delenv(variable, raising=False)

    # Act
    default_settings = Settings(_env_file=None)
    monkeypatch.setenv(variable, "true")
    enabled_settings = Settings(_env_file=None)
    monkeypatch.setenv(variable, "false")
    disabled_settings = Settings(_env_file=None)

    # Assert
    assert default_settings.AGENT_PID_NAMESPACE_ISOLATION is False
    assert enabled_settings.AGENT_PID_NAMESPACE_ISOLATION is True
    assert disabled_settings.AGENT_PID_NAMESPACE_ISOLATION is False

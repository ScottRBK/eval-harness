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

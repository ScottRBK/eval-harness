import json
import traceback
from pathlib import Path

import pytest

from src.evals_engine import build_eval_session
from src.helpers.redaction import redact_secrets
from src.models import CapabilityProfile, ResultFormat


EXAMPLE_EVALS_DIR = Path(__file__).resolve().parents[2] / "example_evals"


@pytest.fixture(autouse=True)
def use_repository_example_evals(monkeypatch):
    monkeypatch.setattr("src.evals_engine.settings.EVALS_DIRS", str(EXAMPLE_EVALS_DIR))


def _valid_config() -> dict:
    return {
        "evals": [
            {
                "number": 1,
                "eval_dir": "basic_eval",
                "description": "a valid evaluation",
                "run_count": 1,
                "tags": ["example"],
            }
        ],
        "agents": [
            {
                "agent_type": "copilot_cli",
                "agent_model": "test-model",
            }
        ],
    }


def _write_config(tmp_path: Path, value: object, *, raw: bool = False) -> Path:
    path = tmp_path / "evals.json"
    contents = value if raw else json.dumps(value)
    path.write_text(contents, encoding="utf-8")
    return path


def test_build_eval_session_accepts_valid_config(tmp_path):
    # Arrange
    config_path = _write_config(tmp_path, _valid_config())

    # Act
    session = build_eval_session(config_path, ResultFormat.JSON)

    # Assert
    assert len(session.evals) == 1
    assert len(session.agents) == 1
    assert session.agents[0].eval_retries == 0


def test_build_eval_session_accepts_agent_eval_retries(tmp_path):
    # Arrange
    config = _valid_config()
    config["agents"][0]["eval_retries"] = 2
    config_path = _write_config(tmp_path, config)

    # Act
    session = build_eval_session(config_path, ResultFormat.JSON)

    # Assert
    assert session.agents[0].eval_retries == 2


def test_build_eval_session_loads_capability_profile_for_agent(tmp_path):
    # Arrange
    config = _valid_config()
    config["capability_profiles"] = {
        "base": {},
        "pi-tools": {"packages": ["npm:@example/tools@1.2.3"]},
    }
    config["agents"][0].update(
        {
            "id": "pi-with-tools",
            "agent_type": "pi",
            "capability_profile": "pi-tools",
        }
    )
    config_path = _write_config(tmp_path, config)

    # Act
    session = build_eval_session(config_path, ResultFormat.JSON)

    # Assert
    assert session.agents[0].agent_id == "pi-with-tools"
    assert session.agents[0].capability_profile == "pi-tools"
    assert session.agents[0].capability_manifest == {
        "packages": [
            {
                "source": "npm:@example/tools@1.2.3",
                "sha256": "127e333f60a1d333d5f3c3d80c10479c5602d6add24f9ef5de4861a3d81088ec",
            }
        ],
        "mcp_servers": [],
    }
    assert session.capability_profiles["pi-tools"].packages == ("npm:@example/tools@1.2.3",)


def test_build_eval_session_rejects_nonempty_base_capability_profile(tmp_path):
    # Arrange
    config = _valid_config()
    config["capability_profiles"] = {
        "base": {"packages": ["npm:tools@1.2.3"]},
    }
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match=r"capability_profiles\['base'\].*must be empty"):
        build_eval_session(config_path, ResultFormat.JSON)


def test_build_eval_session_defaults_to_empty_base_capability_profile(tmp_path):
    # Arrange
    config_path = _write_config(tmp_path, _valid_config())

    # Act
    session = build_eval_session(config_path, ResultFormat.JSON)

    # Assert
    assert session.agents[0].capability_profile == "base"
    assert session.capability_profiles["base"].packages == ()
    assert session.capability_profiles["base"].mcp_servers == ()


def test_build_eval_session_loads_mcp_capability_profile(tmp_path):
    # Arrange
    config = _valid_config()
    config["capability_profiles"] = {
        "forgetful": {
            "mcp_servers": [
                {
                    "name": "forgetful",
                    "type": "stdio",
                    "command": "uvx",
                    "args": ["forgetful-ai"],
                }
            ],
        },
    }
    config["agents"][0].update(
        {
            "agent_type": "opencode",
            "capability_profile": "forgetful",
        }
    )
    config_path = _write_config(tmp_path, config)

    # Act
    session = build_eval_session(config_path, ResultFormat.JSON)

    # Assert
    assert session.capability_profiles["forgetful"].mcp_servers == (
        {
            "name": "forgetful",
            "type": "stdio",
            "command": "uvx",
            "args": ["forgetful-ai"],
        },
    )


@pytest.mark.parametrize("field", ["id", "capability_profile"])
def test_build_eval_session_rejects_unsafe_variant_identifiers(tmp_path, field):
    # Arrange
    config = _valid_config()
    if field == "id":
        config["agents"][0][field] = "pi with tools"
    else:
        config["capability_profiles"] = {"pi tools": {}}
        config["agents"][0][field] = "pi tools"
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match=field):
        build_eval_session(config_path, ResultFormat.JSON)


def test_build_eval_session_rejects_capability_profile_for_unknown_agent(tmp_path):
    # Arrange
    config = _valid_config()
    config["capability_profiles"] = {"tools": {"packages": ["npm:tools@1.2.3"]}}
    config["agents"][0]["capability_profile"] = "missing"
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match=r"agents\[0\].capability_profile.*not found"):
        build_eval_session(config_path, ResultFormat.JSON)


def test_build_eval_session_rejects_pi_package_profile_for_non_pi_agent(tmp_path):
    # Arrange
    config = _valid_config()
    config["capability_profiles"] = {"tools": {"packages": ["npm:tools@1.2.3"]}}
    config["agents"][0]["capability_profile"] = "tools"
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match=r"capability profile.*packages.*only supported for Pi"):
        build_eval_session(config_path, ResultFormat.JSON)


def test_build_eval_session_rejects_mcp_profile_for_pi_agent(tmp_path):
    # Arrange
    config = _valid_config()
    config["capability_profiles"] = {
        "mcp": {
            "mcp_servers": [
                {
                    "name": "server",
                    "type": "stdio",
                    "command": "server",
                }
            ],
        },
    }
    config["agents"][0].update(
        {
            "agent_type": "pi",
            "capability_profile": "mcp",
        }
    )
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match=r"capability profile.*MCP.*not supported for Pi"):
        build_eval_session(config_path, ResultFormat.JSON)


def test_build_eval_session_rejects_codex_http_mcp_headers(tmp_path):
    # Arrange
    config = _valid_config()
    config["capability_profiles"] = {
        "remote": {
            "mcp_servers": [
                {
                    "name": "remote",
                    "type": "http",
                    "url": "https://example.test/mcp",
                    "headers": {"Authorization": "Bearer secret"},
                }
            ],
        },
    }
    config["agents"][0].update(
        {
            "agent_type": "codex",
            "capability_profile": "remote",
        }
    )
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match=r"Codex.*HTTP.*headers"):
        build_eval_session(config_path, ResultFormat.JSON)


def test_capability_manifest_redacts_mcp_secret_values(tmp_path):
    # Arrange
    config = _valid_config()
    config["capability_profiles"] = {
        "remote": {
            "mcp_servers": [
                {
                    "name": "remote",
                    "type": "http",
                    "url": "https://example.test/mcp?token=secret",
                    "headers": {"Authorization": "Bearer secret"},
                }
            ],
        },
    }
    config["agents"][0].update({"agent_type": "opencode", "capability_profile": "remote"})
    config_path = _write_config(tmp_path, config)

    # Act
    session = build_eval_session(config_path, ResultFormat.JSON)

    # Assert
    manifest = session.agents[0].capability_manifest
    server_manifest = manifest["mcp_servers"][0]
    assert server_manifest["name"] == "remote"
    assert server_manifest["type"] == "http"
    assert server_manifest["env_keys"] == []
    assert server_manifest["header_keys"] == ["Authorization"]
    assert server_manifest["url"] == "https://example.test"
    assert "url_path_sha256" in server_manifest
    assert "secret" not in json.dumps(manifest)


def test_capability_manifest_hides_mcp_url_path_credentials(tmp_path):
    # Arrange
    config = _valid_config()
    secret = "path-secret"
    config["capability_profiles"] = {
        "remote": {
            "mcp_servers": [
                {
                    "name": "remote",
                    "type": "http",
                    "url": f"https://example.test/mcp/s/{secret}",
                },
            ],
        },
    }
    config["agents"][0].update({"agent_type": "opencode", "capability_profile": "remote"})
    config_path = _write_config(tmp_path, config)

    # Act
    session = build_eval_session(config_path, ResultFormat.JSON)

    # Assert
    server_manifest = session.agents[0].capability_manifest["mcp_servers"][0]
    assert server_manifest["url"] == "https://example.test"
    assert "url_path_sha256" in server_manifest
    assert secret not in json.dumps(session.agents[0].capability_manifest)


def test_capability_manifest_does_not_export_mcp_argument_values(tmp_path):
    # Arrange
    config = _valid_config()
    config["capability_profiles"] = {
        "tools": {
            "mcp_servers": [
                {
                    "name": "server",
                    "type": "stdio",
                    "command": "server",
                    "args": ["--api-key", "argument-secret", "--mode", "safe"],
                },
            ],
        },
    }
    config["agents"][0].update({"agent_type": "opencode", "capability_profile": "tools"})
    config_path = _write_config(tmp_path, config)

    # Act
    session = build_eval_session(config_path, ResultFormat.JSON)

    # Assert
    manifest = session.agents[0].capability_manifest
    encoded = json.dumps(manifest)
    assert "argument-secret" not in encoded
    assert manifest["mcp_servers"][0]["args_count"] == 4
    assert "args" not in manifest["mcp_servers"][0]


def test_build_eval_session_rejects_whitespace_only_mcp_command(tmp_path):
    # Arrange
    config = _valid_config()
    config["capability_profiles"] = {
        "tools": {
            "mcp_servers": [{"name": "same", "type": "stdio", "command": "   "}],
        },
    }
    config["agents"][0].update({"agent_type": "opencode", "capability_profile": "tools"})
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match=r"stdio MCP servers require 'command'"):
        build_eval_session(config_path, ResultFormat.JSON)


def test_build_eval_session_rejects_duplicate_mcp_server_names(tmp_path):
    # Arrange
    config = _valid_config()
    config["capability_profiles"] = {
        "tools": {
            "mcp_servers": [
                {"name": "same", "type": "stdio", "command": "first"},
                {"name": "same", "type": "stdio", "command": "second"},
            ],
        },
    }
    config["agents"][0].update({"agent_type": "opencode", "capability_profile": "tools"})
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match=r"mcp_servers.*duplicate.*same"):
        build_eval_session(config_path, ResultFormat.JSON)


@pytest.mark.parametrize("source", ["npm:tools", "git:github.com/org/tools"])
def test_build_eval_session_rejects_unpinned_pi_package_source(tmp_path, source):
    # Arrange
    config = _valid_config()
    config["capability_profiles"] = {"tools": {"packages": [source]}}
    config["agents"][0].update({"agent_type": "pi", "capability_profile": "tools"})
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match=r"packages.*pinned"):
        build_eval_session(config_path, ResultFormat.JSON)


def test_build_eval_session_rejects_duplicate_pi_package_source(tmp_path):
    # Arrange
    config = _valid_config()
    config["capability_profiles"] = {"tools": {"packages": ["npm:tools@1.2.3", "npm:tools@1.2.3"]}}
    config["agents"][0].update({"agent_type": "pi", "capability_profile": "tools"})
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match=r"packages.*duplicate package sources"):
        build_eval_session(config_path, ResultFormat.JSON)


def test_build_eval_session_rejects_conflicting_pi_package_versions(tmp_path):
    # Arrange
    config = _valid_config()
    config["capability_profiles"] = {"tools": {"packages": ["npm:tools@1.2.3", "npm:tools@2.0.0"]}}
    config["agents"][0].update({"agent_type": "pi", "capability_profile": "tools"})
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match=r"packages.*conflicting versions.*npm:tools"):
        build_eval_session(config_path, ResultFormat.JSON)


def test_build_eval_session_rejects_conflicting_pi_git_package_refs(tmp_path):
    # Arrange
    config = _valid_config()
    config["capability_profiles"] = {
        "tools": {
            "packages": [
                "git:https://github.com/org/tools@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "git:https://github.com/org/tools@bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            ]
        }
    }
    config["agents"][0].update({"agent_type": "pi", "capability_profile": "tools"})
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(
        ValueError, match=r"packages.*conflicting versions.*git:github.com/org/tools"
    ):
        build_eval_session(config_path, ResultFormat.JSON)


def test_build_eval_session_rejects_git_aliases_for_same_repository(tmp_path):
    # Arrange
    config = _valid_config()
    refs = [
        "git:https://github.com/org/tools.git@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "git:ssh://git@github.com/org/tools@bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "git:github.com/org/tools.git@cccccccccccccccccccccccccccccccccccccccc",
        "git:https://github.com:443/org/tools@dddddddddddddddddddddddddddddddddddddddd",
        "git:ssh://git@github.com:22/org/tools@eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
        "git:github.com/org/./tools@ffffffffffffffffffffffffffffffffffffffff",
        "git:github.com/org/foo/../tools@1111111111111111111111111111111111111111",
    ]
    config["capability_profiles"] = {"tools": {"packages": refs}}
    config["agents"][0].update({"agent_type": "pi", "capability_profile": "tools"})
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(
        ValueError, match=r"packages.*conflicting versions.*git:github.com/org/tools"
    ):
        build_eval_session(config_path, ResultFormat.JSON)


@pytest.mark.parametrize(
    "alias",
    [
        "git:https://github.com:443/org/tools@bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "git:ssh://git@github.com:22/org/tools@bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "git:github.com/org/./tools@bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "git:github.com/org/foo/../tools@bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "git:https://github.com/org/%2E/tools@bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "git:github.com/org/%2E/tools@bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "git:https://github.com/org/team/%2E%2E/tools@bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    ],
)
def test_build_eval_session_rejects_git_alias_pair(tmp_path, alias):
    # Arrange
    config = _valid_config()
    config["capability_profiles"] = {
        "tools": {
            "packages": [
                "git:https://github.com/org/tools@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                alias,
            ]
        }
    }
    config["agents"][0].update({"agent_type": "pi", "capability_profile": "tools"})
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match=r"packages.*conflicting versions"):
        build_eval_session(config_path, ResultFormat.JSON)


def test_capability_redactions_include_transformed_url_secret_parts():
    # Arrange
    profile = CapabilityProfile(
        packages=(
            "git:https://user:git-secret@example.com/org/tools@"
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        ),
        mcp_servers=(
            {
                "name": "remote",
                "type": "http",
                "url": "https://example.com/mcp/s/path-secret?token=query-secret",
            },
        ),
    )

    # Act
    redactions = profile.redaction_values()

    # Assert
    assert "git-secret" in redactions
    assert "https://user:git-secret@example.com/org/tools" in redactions
    assert "/mcp/s/path-secret" in redactions
    assert "path-secret" in redactions
    assert "query-secret" in redactions
    message = (
        "clone failed: https://user:git-secret@example.com/org/tools; "
        "request /mcp/s/path-secret?token=query-secret"
    )
    safe_message = redact_secrets(message, redactions)
    assert "git-secret" not in safe_message
    assert "path-secret" not in safe_message
    assert "query-secret" not in safe_message


def test_build_eval_session_rejects_git_shorthand_credentials(tmp_path):
    # Arrange
    config = _valid_config()
    config["capability_profiles"] = {
        "tools": {
            "packages": ["git:github.com/org:secret/tools@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]
        }
    }
    config["agents"][0].update({"agent_type": "pi", "capability_profile": "tools"})
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match=r"packages.*credentials") as error:
        build_eval_session(config_path, ResultFormat.JSON)
    assert "secret" not in str(error.value)


def test_build_eval_session_rejects_git_shorthand_hostname_credentials(tmp_path):
    # Arrange
    config = _valid_config()
    config["capability_profiles"] = {
        "tools": {
            "packages": [
                "git:sentinel@github.com/org/tools@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            ]
        }
    }
    config["agents"][0].update({"agent_type": "pi", "capability_profile": "tools"})
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match=r"packages.*credentials") as error:
        build_eval_session(config_path, ResultFormat.JSON)
    assert "sentinel" not in str(error.value)


def test_build_eval_session_rejects_git_shorthand_embedded_credentials(tmp_path):
    # Arrange
    config = _valid_config()
    config["capability_profiles"] = {
        "tools": {
            "packages": [
                "git:git@sentinel@example.com/org/tools@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            ]
        }
    }
    config["agents"][0].update({"agent_type": "pi", "capability_profile": "tools"})
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match=r"packages.*credentials") as error:
        build_eval_session(config_path, ResultFormat.JSON)
    assert "sentinel" not in str(error.value)


def test_build_eval_session_accepts_credential_free_git_scp_shorthand(tmp_path):
    # Arrange
    config = _valid_config()
    source = "git:git@github.com:org/tools@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    config["capability_profiles"] = {"tools": {"packages": [source]}}
    config["agents"][0].update({"agent_type": "pi", "capability_profile": "tools"})
    config_path = _write_config(tmp_path, config)

    # Act
    session = build_eval_session(config_path, ResultFormat.JSON)

    # Assert
    assert session.capability_profiles["tools"].packages == (source,)


def test_build_eval_session_rejects_malformed_git_url_without_echoing_credentials(tmp_path):
    # Arrange
    config = _valid_config()
    config["capability_profiles"] = {
        "tools": {
            "packages": [
                "git:https://user:sentinel@example.com：443/org/tools@"
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            ]
        }
    }
    config["agents"][0].update({"agent_type": "pi", "capability_profile": "tools"})
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match=r"packages.*valid pinned Git package source") as error:
        build_eval_session(config_path, ResultFormat.JSON)
    assert "sentinel" not in str(error.value)
    assert "sentinel" not in "".join(traceback.format_exception(error.value))


def test_build_eval_session_rejects_git_url_credentials(tmp_path):
    # Arrange
    config = _valid_config()
    config["capability_profiles"] = {
        "tools": {
            "packages": [
                "git:https://user:sentinel@example.com/org/tools@"
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            ]
        }
    }
    config["agents"][0].update({"agent_type": "pi", "capability_profile": "tools"})
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match=r"packages.*credentials") as error:
        build_eval_session(config_path, ResultFormat.JSON)
    assert "sentinel" not in str(error.value)


def test_build_eval_session_rejects_malformed_http_mcp_url(tmp_path):
    # Arrange
    config = _valid_config()
    config["capability_profiles"] = {
        "remote": {
            "mcp_servers": [
                {"name": "remote", "type": "http", "url": "not-a-url"},
            ],
        },
    }
    config["agents"][0].update({"agent_type": "opencode", "capability_profile": "remote"})
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match=r"remote.*url.*valid HTTP URL"):
        build_eval_session(config_path, ResultFormat.JSON)


def test_build_eval_session_rejects_malformed_mcp_url_without_echoing_credentials(tmp_path):
    # Arrange
    config = _valid_config()
    config["capability_profiles"] = {
        "remote": {
            "mcp_servers": [
                {
                    "name": "remote",
                    "type": "http",
                    "url": "https://user:sentinel@example.com：443/mcp",
                },
            ],
        },
    }
    config["agents"][0].update({"agent_type": "opencode", "capability_profile": "remote"})
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match=r"remote.*url.*valid HTTP URL") as error:
        build_eval_session(config_path, ResultFormat.JSON)
    assert "sentinel" not in str(error.value)
    assert "sentinel" not in "".join(traceback.format_exception(error.value))


def test_build_eval_session_rejects_mcp_url_control_characters(tmp_path):
    # Arrange
    config = _valid_config()
    config["capability_profiles"] = {
        "remote": {
            "mcp_servers": [
                {"name": "remote", "type": "http", "url": "https://example.\x01test/mcp"},
            ],
        },
    }
    config["agents"][0].update({"agent_type": "opencode", "capability_profile": "remote"})
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match=r"remote.*url.*valid HTTP URL"):
        build_eval_session(config_path, ResultFormat.JSON)


def test_build_eval_session_rejects_malformed_http_mcp_port(tmp_path):
    # Arrange
    config = _valid_config()
    config["capability_profiles"] = {
        "remote": {
            "mcp_servers": [
                {"name": "remote", "type": "http", "url": "https://example.test:bad/mcp"},
            ],
        },
    }
    config["agents"][0].update({"agent_type": "opencode", "capability_profile": "remote"})
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match=r"remote.*url.*valid HTTP URL"):
        build_eval_session(config_path, ResultFormat.JSON)


def test_build_eval_session_rejects_duplicate_sanitized_agent_identity(tmp_path):
    # Arrange
    config = _valid_config()
    config["agents"][0]["effort"] = "high"
    config["agents"].append(
        {
            "agent_type": "copilot_cli",
            "agent_model": "test-model",
            "id": "high",
        }
    )
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match=r"sanitized agent identities.*unique"):
        build_eval_session(config_path, ResultFormat.JSON)


def test_build_eval_session_rejects_id_profile_identity_collision(tmp_path):
    # Arrange
    config = _valid_config()
    config["capability_profiles"] = {"tools": {}}
    config["agents"][0]["id"] = "tools"
    config["agents"].append(
        {
            "agent_type": "copilot_cli",
            "agent_model": "test-model",
            "capability_profile": "tools",
        }
    )
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match=r"sanitized agent identities.*unique"):
        build_eval_session(config_path, ResultFormat.JSON)


@pytest.mark.parametrize("value", [-1, True, 1.5, "1"])
def test_build_eval_session_rejects_invalid_agent_eval_retries(tmp_path, value):
    # Arrange
    config = _valid_config()
    config["agents"][0]["eval_retries"] = value
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match=r"agents\[0\].eval_retries.*non-negative integer"):
        build_eval_session(config_path, ResultFormat.JSON)


def test_build_eval_session_reports_invalid_json(tmp_path):
    # Arrange
    config_path = _write_config(tmp_path, "{", raw=True)

    # Act / Assert
    with pytest.raises(ValueError, match="Invalid evaluation configuration.*invalid JSON"):
        build_eval_session(config_path, ResultFormat.JSON)


def test_build_eval_session_reports_missing_top_level_field(tmp_path):
    # Arrange
    config = _valid_config()
    del config["agents"]
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match="missing required field 'agents'"):
        build_eval_session(config_path, ResultFormat.JSON)


def test_build_eval_session_rejects_unknown_agent_field(tmp_path):
    # Arrange
    config = _valid_config()
    config["agents"][0]["unexpected"] = True
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match=r"agents\[0\].*unknown field.*unexpected"):
        build_eval_session(config_path, ResultFormat.JSON)


def test_build_eval_session_reports_invalid_agent_type(tmp_path):
    # Arrange
    config = _valid_config()
    config["agents"][0]["agent_type"] = "not_an_agent"
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match=r"agents\[0\].agent_type"):
        build_eval_session(config_path, ResultFormat.JSON)


def test_build_eval_session_reports_invalid_run_count(tmp_path):
    # Arrange
    config = _valid_config()
    config["evals"][0]["run_count"] = 0
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match=r"evals\[0\].run_count.*positive integer"):
        build_eval_session(config_path, ResultFormat.JSON)


def test_build_eval_session_reports_unknown_eval_directory(tmp_path):
    # Arrange
    config = _valid_config()
    config["evals"][0]["eval_dir"] = "does_not_exist"
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match=r"evals\[0\].eval_dir.*not found"):
        build_eval_session(config_path, ResultFormat.JSON)

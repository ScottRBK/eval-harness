"""Unit tests for the naming helper.

``safe_name`` is the single source of truth for turning an agent's identity
(type + model, sometimes with a '/' or space) into a string that is legal as
both a Docker container name and a log filename.
"""

import pytest

from src.helpers.naming import safe_name


class TestSafeName:
    def test_leaves_already_safe_strings_untouched(self):
        assert safe_name("eval_harness_claude_code_haiku") == "eval_harness_claude_code_haiku"

    def test_keeps_dots_dashes_and_underscores(self):
        # all three are inside Docker's allowed [a-zA-Z0-9_.-] set
        assert safe_name("qwen3.6-27b_8Q") == "qwen3.6-27b_8Q"

    def test_replaces_slash(self):
        assert safe_name("bosman/ornith-1.0") == "bosman_ornith-1.0"

    def test_replaces_space(self):
        # the real failure: "llama.cpp ai/qwen..." broke Docker container create
        assert safe_name("llama.cpp ai/qwen3.6-27b-8Q") == "llama.cpp_ai_qwen3.6-27b-8Q"

    def test_replaces_every_disallowed_char(self):
        assert safe_name("a:b@c d/e") == "a_b_c_d_e"

    @pytest.mark.parametrize(
        "raw",
        ["eval_harness_opencode_llama.cpp ai/qwen3.6-27b-8Q", "anthropic/claude-sonnet-4-5"],
    )
    def test_output_is_a_legal_docker_name(self, raw):
        import re

        # Docker container names must match this pattern.
        assert re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", safe_name(raw))

import re

# Docker permits [a-zA-Z0-9][a-zA-Z0-9_.-]* in a container name. This is also a
# strict superset of what a clean log filename needs, so the same rule serves
# both: container names and per-agent log files.
_DISALLOWED = re.compile(r"[^a-zA-Z0-9_.-]")


def safe_name(s: str) -> str:
    """Collapse every character outside Docker's container-name charset to '_'.

    Agent/model identifiers routinely carry '/' and spaces (e.g.
    "llama.cpp ai/qwen3.6-27b-8Q"), which are illegal in a Docker container name
    and awkward in a filename. Replacing against an allowlist means any future
    stray character is handled too - no per-character whack-a-mole.
    """
    return _DISALLOWED.sub("_", s)

import json
import re
import shlex
from urllib.parse import quote, quote_plus
from collections.abc import Iterable


def _secret_variants(secret: str) -> set[str]:
    """Return literal, escaped, and line-by-line forms of one secret."""
    variants = {secret}
    for _ in range(2):
        generated = set()
        for value in variants:
            escaped = value.encode("unicode_escape").decode("ascii")
            escaped_single = value.replace("\\", "\\\\").replace("'", "\\'")
            escaped_double = value.replace("\\", "\\\\").replace('"', '\\"')
            python_repr = repr(value)
            json_ascii = json.dumps(value, ensure_ascii=True)
            json_unicode = json.dumps(value, ensure_ascii=False)
            escaped_json_ascii = json.dumps(escaped, ensure_ascii=True)
            escaped_json_unicode = json.dumps(escaped, ensure_ascii=False)
            url_quoted = quote(value, safe="")
            url_plus = quote_plus(value)
            shell_quoted = shlex.quote(value)
            generated.update(
                {
                    python_repr,
                    python_repr[1:-1],
                    json_unicode,
                    json_ascii,
                    json_unicode[1:-1],
                    json_ascii[1:-1],
                    escaped,
                    escaped_single,
                    escaped_double,
                    repr(escaped),
                    repr(escaped_single),
                    repr(escaped_double),
                    escaped_json_unicode,
                    escaped_json_ascii,
                    escaped_json_unicode[1:-1],
                    escaped_json_ascii[1:-1],
                    url_quoted,
                    url_plus,
                    shell_quoted,
                }
            )
        variants.update(generated)
    variants.update(part for part in secret.splitlines() if part)
    return {variant for variant in variants if variant}


def redact_secrets(text: str, secrets: Iterable[str]) -> str:
    """Replace known secret values and their common escaped forms."""
    variants = {
        variant
        for secret in secrets
        if isinstance(secret, str) and secret
        for variant in _secret_variants(secret)
    }
    if not variants:
        return text
    pattern = "|".join(re.escape(value) for value in sorted(variants, key=len, reverse=True))
    return re.sub(pattern, "[REDACTED]", text)

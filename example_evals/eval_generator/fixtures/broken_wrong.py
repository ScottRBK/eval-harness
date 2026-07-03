def is_balanced(text: str) -> bool:
    # BUG: counts brackets but ignores nesting order and type matching.
    # e.g. "([)]" returns True here (should be False).
    # Catches an empty-stack-underflow case, so simple cases still work.
    depth = 0
    for ch in text:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0
def is_balanced(text: str) -> bool:
    # BUG: raises on square brackets — a hard crash, a distinct failure mode
    # from the "subtly wrong" broken solution.
    if "[" in text or "]" in text:
        raise ValueError("square brackets not supported")
    depth = 0
    for ch in text:
        if ch in "({":
            depth += 1
        elif ch in ")}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0
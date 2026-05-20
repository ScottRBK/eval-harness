from pathlib import Path

def read_eval_fixture(eval_file: str, relative_path: str) -> str:
    try:
        path = Path(eval_file).parent / "fixtures" / relative_path 
        return path.read_text(encoding="utf-8")
    except OSError as exc: 
        raise RuntimeError(f"Failed to read eval fixture: {relative_path}") from exc





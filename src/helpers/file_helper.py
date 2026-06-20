import csv
import io
import json
from pathlib import Path

def read_eval_fixture(eval_file: str, relative_path: str) -> str:
    try:
        path = Path(eval_file).parent / "fixtures" / relative_path 
        return path.read_text(encoding="utf-8")
    except OSError as exc: 
        raise RuntimeError(f"Failed to read eval fixture: {relative_path}") from exc

def read_mapping(eval_file: str, mapping_file: str, columns_to_remove: list[str] | None = None) -> str: 
    """
        Reads a fixture for evals that hold a cannonical data mapping, optionally remove columns from 
        a list of column indexes
    """
    
    raw_file = read_eval_fixture(eval_file, mapping_file)

    if not columns_to_remove:
        return raw_file

    reader  = csv.DictReader(io.StringIO(raw_file))
    
    if reader.fieldnames is None: 
        raise ValueError(f"{mapping_file} is empty or has no header rows")

    missing = [c for c in columns_to_remove if c not in reader.fieldnames]

    if missing:
        raise ValueError(f"{mapping_file}: can't strip missing column(s) {missing}")
        
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=reader.fieldnames, extrasaction="ignore", lineterminator="\n")
    writer.writeheader() 

    for row in reader:
        for col in columns_to_remove:
            row[col] = ""
        writer.writerow(row)

    return out.getvalue() 


def read_questions(eval_file: str, include_answers: bool) -> str:
    """
    Reads questions.json fixtures for evals that hold required multiple-choice questions and answers.

    When include_answers is False (for example in the act phase of an eval) the answer key and source
    references and maintenance note are stripped so they are never embedded into the act script.
    The full file is returned for scoring. 
    """
    raw_file = read_eval_fixture(eval_file, "questions.json")


    try:
        data = json.loads(raw_file)
    except json.JSONDecodeError as exc:
        raise ValueError(f"question.json is not valid JSON: {exc}") from exc    

    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ValueError("questions.json must contain a non-empty 'questions' list")

    ids = [q.get("id") for q in questions]
    if len(ids) != len(set(ids)):
        raise ValueError(f"questions.json has duplicate question ids: {ids}")
    
    for q in questions:
        if q.get("answer") not in q.get("choices", {}):
            raise ValueError(
                f"question {q.get('id')!r}: answer {q.get('answer')!r} is not one of its choices"
            )

    if include_answers:
        return raw_file

    data.pop("note", None)
    for question in data["questions"]:
        question.pop("answer", None)
        question.pop("source", None)

    return json.dumps(data, indent=2)
        


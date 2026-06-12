# -*- coding: utf-8 -*-
"""Flask + tiny local LLM standardizer with incremental JSONL CLI output."""

from __future__ import annotations

import json
import os
import re
import sys
import difflib
from typing import Any, Dict, List, Tuple

from flask import Flask, jsonify, request
from huggingface_hub import hf_hub_download
from llama_cpp import Llama

app = Flask(__name__)

# ---------------- Model config ----------------
MODEL_REPO = os.getenv(
    "MODEL_REPO",
    "TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF",
)
MODEL_FILE = os.getenv(
    "MODEL_FILE",
    "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
)

N_THREADS = int(os.getenv("N_THREADS", str(os.cpu_count() or 2)))
N_CTX = int(os.getenv("N_CTX", "2048"))
N_GPU_LAYERS = int(os.getenv("N_GPU_LAYERS", "0"))

CANON_UNIS_PATH = os.getenv("CANON_UNIS_PATH", "canon_universities.txt")
CANON_PROGS_PATH = os.getenv("CANON_PROGS_PATH", "canon_programs.txt")

JSON_OBJ_RE = re.compile(r"\{.*?\}", re.DOTALL)

# ---------------- Canonical lists + abbrev maps ----------------
def _read_lines(path: str) -> List[str]:
    """Read non-empty lines from a text file.

    :param path: Path to the canonical list file.
    :type path: str
    :returns: Stripped non-empty lines, or an empty list if missing.
    :rtype: list[str]
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [ln.strip() for ln in f if ln.strip()]
    except FileNotFoundError:
        return []


CANON_UNIS = _read_lines(CANON_UNIS_PATH)
CANON_PROGS = _read_lines(CANON_PROGS_PATH)

ABBREV_UNI: Dict[str, str] = {
    r"(?i)^mcg(\.|ill)?$": "McGill University",
    r"(?i)^(ubc|u\.?b\.?c\.?)$": "University of British Columbia",
    r"(?i)^uoft$": "University of Toronto",
}

COMMON_UNI_FIXES: Dict[str, str] = {
    "McGiill University": "McGill University",
    "Mcgill University": "McGill University",
    "University Of British Columbia": "University of British Columbia",
}

COMMON_PROG_FIXES: Dict[str, str] = {
    "Mathematic": "Mathematics",
    "Info Studies": "Information Studies",
}

# ---------------- Few-shot prompt ----------------
SYSTEM_PROMPT = (
    "You are a data cleaning assistant. Standardize degree program and university "
    "names.\n\n"
    "Rules:\n"
    "- Input provides a single string under key `program` that may contain both "
    "program and university.\n"
    "- Split into (program name, university name).\n"
    "- Trim extra spaces and commas.\n"
    '- Expand obvious abbreviations (e.g., "McG" -> "McGill University", '
    '"UBC" -> "University of British Columbia").\n'
    "- Use Title Case for program; use official capitalization for university "
    'names (e.g., "University of X").\n'
    '- Ensure correct spelling (e.g., "McGill", not "McGiill").\n'
    '- If university cannot be inferred, return "Unknown".\n\n'
    "Return JSON ONLY with keys:\n"
    "  standardized_program, standardized_university\n"
)

FEW_SHOTS: List[Tuple[Dict[str, str], Dict[str, str]]] = [
    (
        {"program": "Information Studies, McGill University"},
        {
            "standardized_program": "Information Studies",
            "standardized_university": "McGill University",
        },
    ),
    (
        {"program": "Information, McG"},
        {
            "standardized_program": "Information Studies",
            "standardized_university": "McGill University",
        },
    ),
    (
        {"program": "Mathematics, University Of British Columbia"},
        {
            "standardized_program": "Mathematics",
            "standardized_university": "University of British Columbia",
        },
    ),
]

_LLM: Llama | None = None


def _load_llm() -> Llama:
    """Load and cache the local GGUF language model.

    :returns: Initialized ``Llama`` instance (singleton).
    :rtype: llama_cpp.Llama
    """
    global _LLM
    if _LLM is not None:
        return _LLM

    model_path = hf_hub_download(
        repo_id=MODEL_REPO,
        filename=MODEL_FILE,
        local_dir="models",
        local_dir_use_symlinks=False,
        force_filename=MODEL_FILE,
    )

    _LLM = Llama(
        model_path=model_path,
        n_ctx=N_CTX,
        n_threads=N_THREADS,
        n_gpu_layers=N_GPU_LAYERS,
        verbose=False,
    )
    return _LLM


def _norm_key(key: str) -> str:
    """Normalize a dict key for case-insensitive lookup.

    :param key: Original field name from an input row.
    :type key: str
    :returns: Lowercase alphanumeric key.
    :rtype: str
    """
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _get_row_value(row: Dict[str, Any], *aliases: str) -> str:
    """Return the first non-empty value for any alias key in a row.

    :param row: Input record dictionary.
    :type row: dict[str, Any]
    :param aliases: Candidate field names, matched case-insensitively.
    :type aliases: str
    :returns: First matching non-empty string value.
    :rtype: str
    """
    if not row:
        return ""

    normalized = {_norm_key(k): v for k, v in row.items()}

    for alias in aliases:
        value = normalized.get(_norm_key(alias))
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text

    return ""


def _looks_like_university(text: str) -> bool:
    """Heuristically determine whether text refers to a university.

    :param text: Candidate university or institution string.
    :type text: str
    :returns: ``True`` if the text looks like a university name.
    :rtype: bool
    """
    t = (text or "").strip()
    if not t:
        return False

    lowered = t.lower()
    university_markers = (
        "university",
        "college",
        "institute",
        "school",
        "polytechnic",
    )
    if any(marker in lowered for marker in university_markers):
        return True

    return any(re.fullmatch(pattern, t) for pattern in ABBREV_UNI)


def _split_fallback(text: str) -> Tuple[str, str]:
    """Split combined program/university text without LLM assistance.

    :param text: Raw combined program and university string.
    :type text: str
    :returns: Tuple of ``(program, university)``; university defaults to
        ``"Unknown"`` when missing.
    :rtype: tuple[str, str]
    """
    s = re.sub(r"\s+", " ", (text or "")).strip().strip(",")
    if not s:
        return "", "Unknown"

    parts = [p.strip() for p in re.split(r",|\sat\s|\s@\s", s, flags=re.IGNORECASE) if p.strip()]

    if len(parts) == 1:
        if _looks_like_university(parts[0]):
            prog = ""
            uni = parts[0]
        else:
            prog = parts[0]
            uni = ""
    else:
        prog = ", ".join(parts[:-1]).strip()
        uni = parts[-1].strip()

    if re.fullmatch(r"(?i)mcg(ill)?(\.)?", uni or ""):
        uni = "McGill University"
    if re.fullmatch(r"(?i)(ubc|u\.?b\.?c\.?|university of british columbia)", uni or ""):
        uni = "University of British Columbia"

    prog = prog.title() if prog else ""
    if uni:
        uni = re.sub(r"\bOf\b", "of", uni.title())
    else:
        uni = "Unknown"

    return prog, uni


def _best_match(name: str, candidates: List[str], cutoff: float = 0.86) -> str | None:
    """Find the closest fuzzy match for a name in a candidate list.

    :param name: Value to match.
    :type name: str
    :param candidates: Canonical names to compare against.
    :type candidates: list[str]
    :param cutoff: Minimum similarity ratio (0–1) to accept a match.
    :type cutoff: float
    :returns: Best matching candidate, or ``None`` if below cutoff.
    :rtype: str | None
    """
    if not name or not candidates:
        return None
    matches = difflib.get_close_matches(name, candidates, n=1, cutoff=cutoff)
    return matches[0] if matches else None


def _post_normalize_program(prog: str) -> str:
    """Apply canonical fixes and fuzzy matching to a program name.

    :param prog: Raw or LLM-generated program name.
    :type prog: str
    :returns: Normalized program name.
    :rtype: str
    """
    p = (prog or "").strip()
    if not p:
        return ""

    p = COMMON_PROG_FIXES.get(p, p)
    p = p.title()
    if p in CANON_PROGS:
        return p
    match = _best_match(p, CANON_PROGS, cutoff=0.84)
    return match or p


def _post_normalize_university(uni: str) -> str:
    """Apply canonical fixes and fuzzy matching to a university name.

    :param uni: Raw or LLM-generated university name.
    :type uni: str
    :returns: Normalized university name, or ``"Unknown"`` if empty.
    :rtype: str
    """
    u = (uni or "").strip()
    if not u:
        return "Unknown"

    for pat, full in ABBREV_UNI.items():
        if re.fullmatch(pat, u):
            u = full
            break

    u = COMMON_UNI_FIXES.get(u, u)
    u = re.sub(r"\bOf\b", "of", u.title())

    if u in CANON_UNIS:
        return u
    match = _best_match(u, CANON_UNIS, cutoff=0.86)
    return match or u or "Unknown"


def _build_program_text(row: Dict[str, Any]) -> str:
    """Build the combined program/university string sent to the LLM.

    :param row: Input applicant record.
    :type row: dict[str, Any]
    :returns: Combined text for standardization, or an empty string.
    :rtype: str
    """
    program = _get_row_value(
        row,
        "program",
        "program_name",
        "degree_program",
        "degree",
        "major",
        "course",
        "field_of_study",
    )
    university = _get_row_value(
        row,
        "university",
        "university_name",
        "school",
        "institution",
        "college",
        "campus",
    )
    combined = _get_row_value(
        row,
        "program_text",
        "raw_program",
        "raw_text",
        "education",
        "input",
        "text",
    )

    if program and university:
        return f"{program}, {university}"
    if combined:
        return combined
    return program or university


def _extract_json_payload(text: str) -> Dict[str, Any]:
    """Extract a JSON object from raw LLM output text.

    :param text: Model response that may contain embedded JSON.
    :type text: str
    :returns: Parsed JSON dict, or an empty dict on failure.
    :rtype: dict[str, Any]
    """
    if not text:
        return {}

    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass

    match = JSON_OBJ_RE.search(text)
    if not match:
        return {}

    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _call_llm(program_text: str) -> Dict[str, str]:
    """Standardize program and university names using the local LLM.

    :param program_text: Combined program/university input string.
    :type program_text: str
    :returns: Dict with ``standardized_program`` and
        ``standardized_university`` keys.
    :rtype: dict[str, str]
    """
    if not (program_text or "").strip():
        return {
            "standardized_program": "",
            "standardized_university": "",
        }

    llm = _load_llm()

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for x_in, x_out in FEW_SHOTS:
        messages.append({"role": "user", "content": json.dumps(x_in, ensure_ascii=False)})
        messages.append({"role": "assistant", "content": json.dumps(x_out, ensure_ascii=False)})
    messages.append(
        {
            "role": "user",
            "content": json.dumps({"program": program_text}, ensure_ascii=False),
        }
    )

    out = llm.create_chat_completion(
        messages=messages,
        temperature=0.0,
        max_tokens=128,
        top_p=1.0,
    )

    text = (out["choices"][0]["message"]["content"] or "").strip()
    obj = _extract_json_payload(text)

    std_prog = str(obj.get("standardized_program", "")).strip()
    std_uni = str(obj.get("standardized_university", "")).strip()

    if not std_prog or not std_uni:
        fallback_prog, fallback_uni = _split_fallback(program_text)
        std_prog = std_prog or fallback_prog
        std_uni = std_uni or fallback_uni

    std_prog = _post_normalize_program(std_prog)
    std_uni = _post_normalize_university(std_uni)

    return {
        "standardized_program": std_prog,
        "standardized_university": std_uni,
    }


def _normalize_input(payload: Any) -> List[Dict[str, Any]]:
    """Normalize API/CLI payload into a list of row dicts.

    :param payload: JSON body as a list or ``{"rows": [...]}`` dict.
    :type payload: Any
    :returns: List of input rows; empty list if format is unsupported.
    :rtype: list[dict[str, Any]]
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        return payload["rows"]
    return []


@app.get("/")
def health() -> Any:
    """Health-check endpoint.

    :returns: JSON payload ``{"ok": true}``.
    :rtype: flask.Response
    """
    return jsonify({"ok": True})


@app.post("/standardize")
def standardize() -> Any:
    """Standardize program and university fields for a batch of rows.

    :returns: JSON payload ``{"rows": [...]}`` with LLM-generated fields
        added to each row.
    :rtype: flask.Response
    """
    payload = request.get_json(force=True, silent=True)
    rows = _normalize_input(payload)

    if payload is None or not rows:
        return jsonify({"rows": []})

    out: List[Dict[str, Any]] = []
    for row in rows:
        row = dict(row or {})
        program_text = _build_program_text(row)

        if not program_text:
            row["llm-generated-program"] = ""
            row["llm-generated-university"] = ""
            out.append(row)
            continue

        result = _call_llm(program_text)
        row["llm-generated-program"] = result["standardized_program"]
        row["llm-generated-university"] = result["standardized_university"]
        out.append(row)

    return jsonify({"rows": out})


def _cli_process_file(
    in_path: str,
    out_path: str | None,
    append: bool,
    to_stdout: bool,
) -> None:
    """Process a JSON input file and write standardized rows as JSONL.

    :param in_path: Path to input JSON file.
    :type in_path: str
    :param out_path: Output JSONL path; defaults to ``<input>.jsonl``.
    :type out_path: str | None
    :param append: Append to the output file instead of overwriting.
    :type append: bool
    :param to_stdout: Write JSONL to stdout instead of a file.
    :type to_stdout: bool
    :returns: ``None``
    :rtype: None
    """
    with open(in_path, "r", encoding="utf-8") as f:
        rows = _normalize_input(json.load(f))

    sink = sys.stdout if to_stdout else None
    if not to_stdout:
        out_path = out_path or (in_path + ".jsonl")
        mode = "a" if append else "w"
        sink = open(out_path, mode, encoding="utf-8")

    assert sink is not None

    try:
        for row in rows:
            row = dict(row or {})
            program_text = _build_program_text(row)

            if not program_text:
                row["llm-generated-program"] = ""
                row["llm-generated-university"] = ""
            else:
                result = _call_llm(program_text)
                row["llm-generated-program"] = result["standardized_program"]
                row["llm-generated-university"] = result["standardized_university"]

            json.dump(row, sink, ensure_ascii=False)
            sink.write("\n")
            sink.flush()
    finally:
        if sink is not sys.stdout:
            sink.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Standardize program/university with a tiny local LLM.",
    )
    parser.add_argument(
        "--file",
        help="Path to JSON input (list of rows or {'rows': [...]})",
        default=None,
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Run the HTTP server instead of CLI.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output path for JSON Lines (ndjson). Defaults to <input>.jsonl when --file is set.",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append to the output file instead of overwriting.",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Write JSON Lines to stdout instead of a file.",
    )
    args = parser.parse_args()

    if args.serve or args.file is None:
        port = int(os.getenv("PORT", "8080"))
        app.run(host="0.0.0.0", port=port, debug=False)
    else:
        _cli_process_file(
            in_path=args.file,
            out_path=args.out,
            append=bool(args.append),
            to_stdout=bool(args.stdout),
        )
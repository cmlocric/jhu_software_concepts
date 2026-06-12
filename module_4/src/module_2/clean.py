from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import requests
from tqdm import tqdm

def load_rows(path: str) -> List[Dict[str, Any]]:
    """Load applicant rows from a JSON input file.

    :param path: Path to JSON file (list or ``{"rows": [...]}``).
    :type path: str
    :returns: List of record dictionaries.
    :rtype: list[dict[str, Any]]
    :raises ValueError: If the file format is not supported.
    """
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        return payload["rows"]

    raise ValueError("Input JSON must be a list of objects or {'rows': [...]}.")

def chunk_rows(rows: List[Dict[str, Any]], batch_size: int) -> List[List[Dict[str, Any]]]:
    """Split rows into fixed-size batches for API processing.

    :param rows: Full list of input records.
    :type rows: list[dict[str, Any]]
    :param batch_size: Maximum number of rows per batch.
    :type batch_size: int
    :returns: List of row batches.
    :rtype: list[list[dict[str, Any]]]
    """
    return [rows[i:i + batch_size] for i in range(0, len(rows), batch_size)]

def process_batch(batch_index: int, rows: List[Dict[str, Any]], base_url: str, timeout: int) -> List[Dict[str, Any]]:
    """Send a batch of rows to the LLM standardizer API.

    :param batch_index: Zero-based batch index (for error messages).
    :type batch_index: int
    :param rows: Records to standardize in this batch.
    :type rows: list[dict[str, Any]]
    :param base_url: Base URL of the standardizer service.
    :type base_url: str
    :param timeout: HTTP request timeout in seconds.
    :type timeout: int
    :returns: Standardized rows returned by the API.
    :rtype: list[dict[str, Any]]
    :raises requests.HTTPError: If the API returns a non-2xx status.
    :raises ValueError: If the API response format is unexpected.
    """
    url = f"{base_url.rstrip('/')}/standardize"

    response = requests.post(url, json={"rows": rows}, timeout=timeout)
    response.raise_for_status()

    data = response.json()
    if not isinstance(data, dict) or "rows" not in data:
        raise ValueError(f"Unexpected response format for batch {batch_index}: {data}")

    return data["rows"]

def write_json(path: str, rows: List[Dict[str, Any]]) -> None:
    """Write cleaned rows to a JSON file.

    :param path: Output file path.
    :type path: str
    :param rows: Cleaned records to persist.
    :type rows: list[dict[str, Any]]
    :returns: ``None``
    :rtype: None
    """
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"rows": rows}, f, ensure_ascii=False, indent=2)

def load_existing_output(path: str) -> List[Dict[str, Any]]:
    """Load previously cleaned rows from an output file.

    :param path: Path to existing output JSON file.
    :type path: str
    :returns: Stored rows, or an empty list if the file does not exist.
    :rtype: list[dict[str, Any]]
    :raises ValueError: If the file exists but has an invalid format.
    """
    p = Path(path)
    if not p.exists():
        return []

    with open(p, "r", encoding="utf-8") as f:
        payload = json.load(f)

    if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        return payload["rows"]

    raise ValueError(f"Existing output file has invalid format: {path}")

def load_progress(progress_path: str) -> int:
    """Load the last completed batch index from a progress file.

    :param progress_path: Path to the ``.progress.json`` sidecar file.
    :type progress_path: str
    :returns: Last completed batch index, or ``-1`` if no progress saved.
    :rtype: int
    """
    p = Path(progress_path)
    if not p.exists():
        return -1

    with open(p, "r", encoding="utf-8") as f:
        payload = json.load(f)

    return int(payload.get("last_completed_batch", -1))

def save_progress(progress_path: str, last_completed_batch: int) -> None:
    """Persist the last completed batch index for resumable processing.

    :param progress_path: Path to the ``.progress.json`` sidecar file.
    :type progress_path: str
    :param last_completed_batch: Zero-based index of the last finished batch.
    :type last_completed_batch: int
    :returns: ``None``
    :rtype: None
    """
    with open(progress_path, "w", encoding="utf-8") as f:
        json.dump({"last_completed_batch": last_completed_batch}, f, indent=2)

def run_clean(
    input_path: str,
    output_path: str,
    base_url: str = "http://127.0.0.1:8080",
    batch_size: int = 50,
    timeout: int = 120,
    max_batches: int | None = None,
) -> None:
    """Standardize applicant rows via the LLM API in resumable batches.

    :param input_path: Path to raw JSON input file.
    :type input_path: str
    :param output_path: Path to write cleaned JSON output.
    :type output_path: str
    :param base_url: Base URL of the standardizer service.
    :type base_url: str
    :param batch_size: Number of rows per API request.
    :type batch_size: int
    :param timeout: HTTP request timeout in seconds.
    :type timeout: int
    :param max_batches: Optional cap on batches to process this run.
    :type max_batches: int | None
    :returns: ``None``
    :rtype: None
    :raises ValueError: If the input file contains no rows.
    """
    rows = load_rows(input_path)
    batches = chunk_rows(rows, batch_size)

    if not batches:
        raise ValueError("No rows found in input file.")

    progress_path = f"{output_path}.progress.json"
    last_completed_batch = load_progress(progress_path)

    all_cleaned = load_existing_output(output_path)

    start_batch = last_completed_batch + 1
    if start_batch >= len(batches):
        print("All batches already processed.", file=sys.stderr)
        return

    remaining_batch_indices = list(range(start_batch, len(batches)))
    if max_batches is not None:
        remaining_batch_indices = remaining_batch_indices[:max_batches]

    for batch_index in tqdm(remaining_batch_indices, desc="Cleaning batches", unit="batch"):
        cleaned_rows = process_batch(batch_index, batches[batch_index], base_url, timeout)

        all_cleaned.extend(cleaned_rows)
        write_json(output_path, all_cleaned)
        save_progress(progress_path, batch_index)

    print(
        f"Wrote {len(all_cleaned)} cleaned rows to {output_path}\n"
        f"Last completed batch: {load_progress(progress_path)}",
        file=sys.stderr,
    )

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input_path")
    parser.add_argument("output_path")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--max-batches", type=int, default=None)
    args = parser.parse_args()

    run_clean(
        input_path=args.input_path,
        output_path=args.output_path,
        base_url=args.base_url,
        batch_size=args.batch_size,
        timeout=args.timeout,
        max_batches=args.max_batches,
    )
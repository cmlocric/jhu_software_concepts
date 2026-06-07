from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import requests
from tqdm import tqdm

def load_rows(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        return payload["rows"]

    raise ValueError("Input JSON must be a list of objects or {'rows': [...]}.")

def chunk_rows(rows: List[Dict[str, Any]], batch_size: int) -> List[List[Dict[str, Any]]]:
    return [rows[i:i + batch_size] for i in range(0, len(rows), batch_size)]

def process_batch(batch_index: int, rows: List[Dict[str, Any]], base_url: str, timeout: int) -> List[Dict[str, Any]]:
    url = f"{base_url.rstrip('/')}/standardize"

    response = requests.post(url, json={"rows": rows}, timeout=timeout)
    response.raise_for_status()

    data = response.json()
    if not isinstance(data, dict) or "rows" not in data:
        raise ValueError(f"Unexpected response format for batch {batch_index}: {data}")

    return data["rows"]

def write_json(path: str, rows: List[Dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"rows": rows}, f, ensure_ascii=False, indent=2)

def load_existing_output(path: str) -> List[Dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []

    with open(p, "r", encoding="utf-8") as f:
        payload = json.load(f)

    if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        return payload["rows"]

    raise ValueError(f"Existing output file has invalid format: {path}")

def load_progress(progress_path: str) -> int:
    p = Path(progress_path)
    if not p.exists():
        return -1

    with open(p, "r", encoding="utf-8") as f:
        payload = json.load(f)

    return int(payload.get("last_completed_batch", -1))

def save_progress(progress_path: str, last_completed_batch: int) -> None:
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
    parser.add_argument("--batch-size", type=int, default=50)
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
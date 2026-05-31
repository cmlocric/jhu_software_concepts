#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Tuple

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

def process_batch(args: Tuple[int, List[Dict[str, Any]], str, int]) -> Tuple[int, List[Dict[str, Any]]]:
    batch_index, rows, base_url, timeout = args
    url = f"{base_url.rstrip('/')}/standardize"

    response = requests.post(url, json={"rows": rows}, timeout=timeout)
    response.raise_for_status()

    data = response.json()
    if not isinstance(data, dict) or "rows" not in data:
        raise ValueError(f"Unexpected response format for batch {batch_index}: {data}")

    return batch_index, data["rows"]

def write_json(path: str, rows: List[Dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"rows": rows}, f, ensure_ascii=False, indent=2)

def write_jsonl(path: str, rows: List[Dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            json.dump(row, f, ensure_ascii=False)
            f.write("\n")

def run_clean(
    input_path: str,
    output_path: str = "cleaned_output.json",
    base_url: str = "http://127.0.0.1:8000",
    batch_size: int = 50,
    workers: int = 4,
    timeout: int = 120,
    jsonl: bool = False,
) -> None:
    rows = load_rows(input_path)
    batches = chunk_rows(rows, batch_size)

    if not batches:
        raise ValueError("No rows found in input file.")

    batch_results: Dict[int, List[Dict[str, Any]]] = {}
    worker_args = [(i, batch, base_url, timeout) for i, batch in enumerate(batches)]

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(process_batch, arg): arg[0]
            for arg in worker_args
        }

        for future in tqdm(
            as_completed(futures),
            total=len(futures),
            desc="Cleaning batches",
            unit="batch",
        ):
            batch_index, cleaned_rows = future.result()
            batch_results[batch_index] = cleaned_rows

    all_cleaned: List[Dict[str, Any]] = []
    for i in range(len(batches)):
        all_cleaned.extend(batch_results[i])

    output = Path(output_path)
    if jsonl:
        write_jsonl(str(output), all_cleaned)
    else:
        write_json(str(output), all_cleaned)

    print(f"Wrote {len(all_cleaned)} cleaned rows to {output}", file=sys.stderr)

if __name__ == "__main__":
    run_clean(
    input_path=r"C:\Users\hz98yb\Training_Files\jhu_software_concepts\module_2\json_files\applicant_data.json",
    output_path=r"C:\Users\hz98yb\Training_Files\jhu_software_concepts\module_2\json_files\llm_extend_applicant_data.json",
    workers=1,
    batch_size=50

)
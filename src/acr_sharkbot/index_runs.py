from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIRED_SEGMENT_FILES = ("frames.csv", "telemetry.csv", "meta.json")
REQUIRED_SEGMENT_DIRS = ("frames",)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an index of recorded runs and segments.")
    parser.add_argument("--runs-dir", default="runs", help="Runs root directory")
    parser.add_argument("--out", default="runs/index.json", help="Output JSON index path")
    return parser.parse_args(argv)


def as_number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def load_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fp:
        data = json.load(fp)
    if not isinstance(data, dict):
        return {}
    return data


def count_rows(csv_path: Path) -> int:
    with open(csv_path, "r", newline="", encoding="utf-8") as fp:
        reader = csv.reader(fp)
        try:
            next(reader)
        except StopIteration:
            return 0
        return sum(1 for _ in reader)


def read_t_range(csv_path: Path) -> tuple[float | None, float | None]:
    with open(csv_path, "r", newline="", encoding="utf-8") as fp:
        reader = csv.DictReader(fp)
        if reader.fieldnames is None or "t_ms" not in reader.fieldnames:
            return None, None
        start: float | None = None
        end: float | None = None
        for row in reader:
            raw = row.get("t_ms")
            if raw is None:
                continue
            try:
                t_ms = float(raw)
            except ValueError:
                continue
            if start is None or t_ms < start:
                start = t_ms
            if end is None or t_ms > end:
                end = t_ms
    return start, end


def rel_or_abs(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def valid_segment_paths(segment_dir: Path) -> bool:
    missing_files = [name for name in REQUIRED_SEGMENT_FILES if not (segment_dir / name).is_file()]
    missing_dirs = [name for name in REQUIRED_SEGMENT_DIRS if not (segment_dir / name).is_dir()]
    missing = missing_files + missing_dirs
    if missing:
        print(
            f"Skipping {segment_dir}: missing {', '.join(missing)}",
            file=sys.stderr,
        )
        return False
    return True


def build_index(runs_dir: Path, out_path: Path) -> dict[str, Any]:
    sessions: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    session_dirs = sorted(path for path in runs_dir.glob("session_*") if path.is_dir())

    for session_dir in session_dirs:
        session_id = session_dir.name
        session_meta_path = session_dir / "session_meta.json"
        session_meta = load_json(session_meta_path) if session_meta_path.is_file() else {}
        capture_region = session_meta.get("capture_region")

        segment_dirs = sorted(path for path in session_dir.glob("segment_*") if path.is_dir())
        session_valid_segments = 0

        for segment_dir in segment_dirs:
            if not valid_segment_paths(segment_dir):
                continue
            session_valid_segments += 1
            segment_id = segment_dir.name
            frames_csv = segment_dir / "frames.csv"
            telemetry_csv = segment_dir / "telemetry.csv"
            meta_json = segment_dir / "meta.json"
            segment_meta = load_json(meta_json)

            frames_count = count_rows(frames_csv)
            telemetry_count = count_rows(telemetry_csv)
            frame_start, frame_end = read_t_range(frames_csv)
            telemetry_start, telemetry_end = read_t_range(telemetry_csv)

            computed_start_candidates = [v for v in (frame_start, telemetry_start) if v is not None]
            computed_end_candidates = [v for v in (frame_end, telemetry_end) if v is not None]
            computed_start = min(computed_start_candidates) if computed_start_candidates else None
            computed_end = max(computed_end_candidates) if computed_end_candidates else None

            start_t_ms = as_number(segment_meta.get("start_t_ms"))
            end_t_ms = as_number(segment_meta.get("end_t_ms"))
            if start_t_ms is None:
                start_t_ms = computed_start
            if end_t_ms is None:
                end_t_ms = computed_end

            duration_ms = as_number(segment_meta.get("duration_ms"))
            if duration_ms is None:
                if start_t_ms is not None and end_t_ms is not None:
                    duration_ms = max(0.0, end_t_ms - start_t_ms)
                else:
                    duration_ms = 0.0

            if capture_region is None:
                capture_region = segment_meta.get("capture_region")

            segments.append(
                {
                    "session_id": session_id,
                    "segment_id": segment_id,
                    "path": rel_or_abs(segment_dir, runs_dir.parent),
                    "frames_csv": rel_or_abs(frames_csv, runs_dir.parent),
                    "telemetry_csv": rel_or_abs(telemetry_csv, runs_dir.parent),
                    "meta_json": rel_or_abs(meta_json, runs_dir.parent),
                    "frames_count": frames_count,
                    "telemetry_count": telemetry_count,
                    "start_t_ms": start_t_ms,
                    "end_t_ms": end_t_ms,
                    "duration_ms": duration_ms,
                    "capture_region": capture_region,
                    "notes": "",
                }
            )

        sessions.append(
            {
                "session_id": session_id,
                "path": rel_or_abs(session_dir, runs_dir.parent),
                "segment_count": session_valid_segments,
                "capture_region": capture_region,
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runs_dir": rel_or_abs(runs_dir, runs_dir.parent),
        "sessions": sessions,
        "segments": segments,
    }


def run(args: argparse.Namespace) -> int:
    runs_dir = Path(args.runs_dir)
    if not runs_dir.is_dir():
        print(f"Runs directory not found: {runs_dir}", file=sys.stderr)
        return 1

    out_path = Path(args.out)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        index_payload = build_index(runs_dir, out_path)
        with open(out_path, "w", encoding="utf-8") as fp:
            json.dump(index_payload, fp, indent=2)
    except Exception as exc:
        print(f"Failed to build index: {exc}", file=sys.stderr)
        return 1

    print(f"Indexed sessions: {len(index_payload['sessions'])}")
    print(f"Indexed segments: {len(index_payload['segments'])}")
    print(f"Wrote index: {out_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())

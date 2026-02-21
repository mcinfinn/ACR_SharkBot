from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GAS_ACTIVE_THRESHOLD = 0.05
BRAKE_ACTIVE_THRESHOLD = 0.05
REQUIRED_TELEMETRY_COLUMNS = ("t_ms", "speed_kmh", "steer", "gas", "brake")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute dataset summary statistics for indexed runs.")
    parser.add_argument("--runs-dir", default="runs", help="Runs root directory")
    return parser.parse_args(argv)


def as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def load_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fp:
        data = json.load(fp)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object at {path}")
    return data


def rel_or_abs(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def resolve_telemetry_path(segment: dict[str, Any], runs_dir: Path) -> Path:
    candidates: list[Path] = []
    raw_path = segment.get("telemetry_csv")
    if isinstance(raw_path, str) and raw_path.strip():
        candidate = Path(raw_path)
        if candidate.is_absolute():
            candidates.append(candidate)
        else:
            candidates.extend([candidate, runs_dir.parent / candidate, runs_dir / candidate])

    session_id = segment.get("session_id")
    segment_id = segment.get("segment_id")
    if isinstance(session_id, str) and isinstance(segment_id, str):
        candidates.append(runs_dir / session_id / segment_id / "telemetry.csv")

    seen: set[Path] = set()
    ordered_candidates: list[Path] = []
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        ordered_candidates.append(path)

    for path in ordered_candidates:
        if path.is_file():
            return path

    segment_label = f"{segment.get('session_id', '?')}/{segment.get('segment_id', '?')}"
    checked = ", ".join(str(path) for path in ordered_candidates) or "(no candidates)"
    raise FileNotFoundError(f"Could not locate telemetry.csv for {segment_label}. Checked: {checked}")


def require_columns(reader: csv.DictReader, csv_path: Path) -> None:
    if reader.fieldnames is None:
        raise ValueError(f"{csv_path} is missing a header row")
    missing = [name for name in REQUIRED_TELEMETRY_COLUMNS if name not in reader.fieldnames]
    if missing:
        raise ValueError(f"{csv_path} is missing required column(s): {', '.join(missing)}")


@dataclass(slots=True)
class SegmentSummary:
    session_id: str
    segment_id: str
    telemetry_csv: Path
    telemetry_rows: int
    duration_sec: float
    speed_sum: float
    speed_count: int
    max_speed: float
    steer_abs_sum: float
    steer_count: int
    gas_active_count: int
    gas_count: int
    brake_active_count: int
    brake_count: int

    @property
    def mean_speed(self) -> float:
        if self.speed_count <= 0:
            return 0.0
        return self.speed_sum / self.speed_count

    @property
    def mean_abs_steer(self) -> float:
        if self.steer_count <= 0:
            return 0.0
        return self.steer_abs_sum / self.steer_count

    @property
    def gas_active_ratio(self) -> float:
        if self.gas_count <= 0:
            return 0.0
        return self.gas_active_count / self.gas_count

    @property
    def brake_active_ratio(self) -> float:
        if self.brake_count <= 0:
            return 0.0
        return self.brake_active_count / self.brake_count


def summarize_segment(segment: dict[str, Any], runs_dir: Path) -> SegmentSummary:
    session_id = str(segment.get("session_id", "unknown_session"))
    segment_id = str(segment.get("segment_id", "unknown_segment"))
    telemetry_csv = resolve_telemetry_path(segment, runs_dir)

    telemetry_rows = 0
    t_min: float | None = None
    t_max: float | None = None
    speed_sum = 0.0
    speed_count = 0
    max_speed = 0.0
    steer_abs_sum = 0.0
    steer_count = 0
    gas_active_count = 0
    gas_count = 0
    brake_active_count = 0
    brake_count = 0

    with open(telemetry_csv, "r", newline="", encoding="utf-8") as fp:
        reader = csv.DictReader(fp)
        require_columns(reader, telemetry_csv)
        for row in reader:
            telemetry_rows += 1

            t_ms = as_float(row.get("t_ms"))
            if t_ms is not None:
                if t_min is None or t_ms < t_min:
                    t_min = t_ms
                if t_max is None or t_ms > t_max:
                    t_max = t_ms

            speed = as_float(row.get("speed_kmh"))
            if speed is not None:
                speed_sum += speed
                speed_count += 1
                if speed_count == 1 or speed > max_speed:
                    max_speed = speed

            steer = as_float(row.get("steer"))
            if steer is not None:
                steer_abs_sum += abs(steer)
                steer_count += 1

            gas = as_float(row.get("gas"))
            if gas is not None:
                gas_count += 1
                if gas > GAS_ACTIVE_THRESHOLD:
                    gas_active_count += 1

            brake = as_float(row.get("brake"))
            if brake is not None:
                brake_count += 1
                if brake > BRAKE_ACTIVE_THRESHOLD:
                    brake_active_count += 1

    duration_sec = 0.0
    if t_min is not None and t_max is not None and t_max >= t_min:
        duration_sec = (t_max - t_min) / 1000.0

    return SegmentSummary(
        session_id=session_id,
        segment_id=segment_id,
        telemetry_csv=telemetry_csv,
        telemetry_rows=telemetry_rows,
        duration_sec=duration_sec,
        speed_sum=speed_sum,
        speed_count=speed_count,
        max_speed=max_speed if speed_count > 0 else 0.0,
        steer_abs_sum=steer_abs_sum,
        steer_count=steer_count,
        gas_active_count=gas_active_count,
        gas_count=gas_count,
        brake_active_count=brake_active_count,
        brake_count=brake_count,
    )


def build_summary_payload(
    index_payload: dict[str, Any],
    runs_dir: Path,
    segment_summaries: list[SegmentSummary],
) -> dict[str, Any]:
    raw_sessions = index_payload.get("sessions")
    raw_segments = index_payload.get("segments")
    sessions = raw_sessions if isinstance(raw_sessions, list) else []
    segments = raw_segments if isinstance(raw_segments, list) else []

    total_frames = 0
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        frames_count = as_int(segment.get("frames_count"))
        if frames_count is not None and frames_count > 0:
            total_frames += frames_count

    total_duration_sec = sum(item.duration_sec for item in segment_summaries)
    total_telemetry_rows = sum(item.telemetry_rows for item in segment_summaries)

    speed_sum = sum(item.speed_sum for item in segment_summaries)
    speed_count = sum(item.speed_count for item in segment_summaries)
    speed_max = max((item.max_speed for item in segment_summaries), default=0.0)
    steer_abs_sum = sum(item.steer_abs_sum for item in segment_summaries)
    steer_count = sum(item.steer_count for item in segment_summaries)
    gas_active = sum(item.gas_active_count for item in segment_summaries)
    gas_count = sum(item.gas_count for item in segment_summaries)
    brake_active = sum(item.brake_active_count for item in segment_summaries)
    brake_count = sum(item.brake_count for item in segment_summaries)

    speed_mean = speed_sum / speed_count if speed_count > 0 else 0.0
    steer_mean_abs = steer_abs_sum / steer_count if steer_count > 0 else 0.0
    gas_active_ratio = gas_active / gas_count if gas_count > 0 else 0.0
    brake_active_ratio = brake_active / brake_count if brake_count > 0 else 0.0

    segment_payload = []
    for item in segment_summaries:
        segment_payload.append(
            {
                "session_id": item.session_id,
                "segment_id": item.segment_id,
                "telemetry_csv": rel_or_abs(item.telemetry_csv, runs_dir.parent),
                "telemetry_rows": item.telemetry_rows,
                "duration_sec": item.duration_sec,
                "mean_speed": item.mean_speed,
                "max_speed": item.max_speed,
                "mean_abs_steer": item.mean_abs_steer,
                "gas_active_ratio": item.gas_active_ratio,
                "brake_active_ratio": item.brake_active_ratio,
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runs_dir": rel_or_abs(runs_dir, runs_dir.parent),
        "totals": {
            "sessions": len(sessions),
            "segments": len(segment_summaries),
            "duration_sec": total_duration_sec,
            "duration_min": total_duration_sec / 60.0,
            "frames": total_frames,
            "telemetry_rows": total_telemetry_rows,
        },
        "speed": {
            "mean_kmh": speed_mean,
            "max_kmh": speed_max,
        },
        "control_usage": {
            "mean_abs_steer": steer_mean_abs,
            "gas_active_ratio": gas_active_ratio,
            "brake_active_ratio": brake_active_ratio,
        },
        "segments": segment_payload,
    }


def print_summary_console(summary: dict[str, Any]) -> None:
    totals = summary["totals"]
    speed = summary["speed"]
    controls = summary["control_usage"]

    print("Dataset Summary")
    print("---------------")
    print(f"Sessions: {totals['sessions']}")
    print(f"Segments: {totals['segments']}")
    print(f"Total duration: {totals['duration_min']:.1f} min")
    print(f"Total frames: {totals['frames']}")
    print(f"Total telemetry rows: {totals['telemetry_rows']}")
    print()
    print("Speed:")
    print(f"  mean: {speed['mean_kmh']:.2f} km/h")
    print(f"  max: {speed['max_kmh']:.2f} km/h")
    print()
    print("Control usage:")
    print(f"  mean |steer|: {controls['mean_abs_steer']:.3f}")
    print(f"  gas active: {controls['gas_active_ratio'] * 100.0:.1f}%")
    print(f"  brake active: {controls['brake_active_ratio'] * 100.0:.1f}%")


def run(args: argparse.Namespace) -> int:
    runs_dir = Path(args.runs_dir)
    if not runs_dir.is_dir():
        print(f"Runs directory not found: {runs_dir}", file=sys.stderr)
        return 1

    index_path = runs_dir / "index.json"
    if not index_path.is_file():
        print(f"Index not found: {index_path}", file=sys.stderr)
        print("Run index_runs first: py -3.12 -m acr_sharkbot.index_runs --runs-dir runs", file=sys.stderr)
        return 1

    try:
        index_payload = load_json(index_path)
    except Exception as exc:
        print(f"Failed to load index: {exc}", file=sys.stderr)
        return 1

    raw_segments = index_payload.get("segments")
    if not isinstance(raw_segments, list):
        print(f"Index is missing a valid 'segments' list: {index_path}", file=sys.stderr)
        return 1

    segment_summaries: list[SegmentSummary] = []
    for segment in raw_segments:
        if not isinstance(segment, dict):
            print("Index contains a non-object segment entry", file=sys.stderr)
            return 1
        try:
            segment_summaries.append(summarize_segment(segment, runs_dir))
        except Exception as exc:
            label = f"{segment.get('session_id', '?')}/{segment.get('segment_id', '?')}"
            print(f"Failed to summarize segment {label}: {exc}", file=sys.stderr)
            return 1

    summary = build_summary_payload(index_payload, runs_dir, segment_summaries)
    out_path = runs_dir / "summary.json"
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fp:
            json.dump(summary, fp, indent=2)
    except Exception as exc:
        print(f"Failed to write summary: {exc}", file=sys.stderr)
        return 1

    print_summary_console(summary)
    print(f"Wrote summary: {out_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())

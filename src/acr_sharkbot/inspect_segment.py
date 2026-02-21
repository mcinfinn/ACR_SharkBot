from __future__ import annotations

import argparse
import csv
import sys
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class FrameRow:
    t_ms: float
    frame_idx: int
    path: Path


@dataclass(slots=True)
class TelemetryData:
    t_ms: list[float]
    fields: dict[str, list[float | int]]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect a recorded segment with telemetry overlay.")
    parser.add_argument("--segment", required=True, help="Path to segment folder")
    parser.add_argument(
        "--match",
        choices=("nearest", "prev"),
        default="prev",
        help="Telemetry matching mode for each frame timestamp",
    )
    parser.add_argument(
        "--start-ms",
        type=float,
        default=0.0,
        help="Start offset in milliseconds from the first frame timestamp",
    )
    parser.add_argument("--no-overlay", action="store_true", help="Disable telemetry overlay text")
    parser.add_argument(
        "--show-dt",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Show frame-to-telemetry dt in milliseconds",
    )
    args = parser.parse_args(argv)
    if args.start_ms < 0:
        parser.error("--start-ms must be >= 0")
    return args


def _require_columns(reader: csv.DictReader, required: list[str], csv_path: Path) -> None:
    if reader.fieldnames is None:
        raise ValueError(f"{csv_path} is missing a header row")
    missing = [name for name in required if name not in reader.fieldnames]
    if missing:
        raise ValueError(f"{csv_path} is missing required column(s): {', '.join(missing)}")


def validate_segment(segment_dir: Path) -> None:
    if not segment_dir.is_dir():
        raise FileNotFoundError(f"Segment folder not found: {segment_dir}")
    required = [
        segment_dir / "frames.csv",
        segment_dir / "telemetry.csv",
        segment_dir / "frames",
    ]
    for path in required:
        if not path.exists():
            raise FileNotFoundError(f"Missing required segment path: {path}")


def load_frames(segment_dir: Path) -> list[FrameRow]:
    frames_csv = segment_dir / "frames.csv"
    rows: list[FrameRow] = []
    with open(frames_csv, "r", newline="", encoding="utf-8") as fp:
        reader = csv.DictReader(fp)
        _require_columns(reader, ["t_ms", "frame_idx", "path"], frames_csv)
        for raw in reader:
            rel = (raw.get("path") or "").strip()
            if not rel:
                continue
            frame_path = Path(rel)
            if not frame_path.is_absolute():
                frame_path = segment_dir / frame_path
            rows.append(
                FrameRow(
                    t_ms=float(raw["t_ms"]),
                    frame_idx=int(raw["frame_idx"]),
                    path=frame_path,
                )
            )
    if not rows:
        raise ValueError(f"No frame rows found in {frames_csv}")
    rows.sort(key=lambda row: row.t_ms)
    return rows


def load_telemetry(segment_dir: Path) -> TelemetryData:
    telemetry_csv = segment_dir / "telemetry.csv"
    records: list[tuple[float, float, float, float, float, int, int]] = []
    with open(telemetry_csv, "r", newline="", encoding="utf-8") as fp:
        reader = csv.DictReader(fp)
        _require_columns(
            reader,
            ["t_ms", "speed_kmh", "steer", "gas", "brake", "gear", "rpms"],
            telemetry_csv,
        )
        for raw in reader:
            records.append(
                (
                    float(raw["t_ms"]),
                    float(raw["speed_kmh"]),
                    float(raw["steer"]),
                    float(raw["gas"]),
                    float(raw["brake"]),
                    int(raw["gear"]),
                    int(raw["rpms"]),
                )
            )
    if not records:
        raise ValueError(f"No telemetry rows found in {telemetry_csv}")
    records.sort(key=lambda row: row[0])
    return TelemetryData(
        t_ms=[row[0] for row in records],
        fields={
            "speed_kmh": [row[1] for row in records],
            "steer": [row[2] for row in records],
            "gas": [row[3] for row in records],
            "brake": [row[4] for row in records],
            "gear": [row[5] for row in records],
            "rpms": [row[6] for row in records],
        },
    )


def estimate_rate(count: int, start_ms: float, end_ms: float) -> float:
    if count < 2:
        return 0.0
    delta_ms = end_ms - start_ms
    if delta_ms <= 0:
        return 0.0
    return (count - 1) / (delta_ms / 1000.0)


def print_stats(segment_dir: Path, frames: list[FrameRow], telemetry: TelemetryData) -> None:
    frame_start = frames[0].t_ms
    frame_end = frames[-1].t_ms
    tele_start = telemetry.t_ms[0]
    tele_end = telemetry.t_ms[-1]
    duration_ms = max(frame_end, tele_end) - min(frame_start, tele_start)
    fps = estimate_rate(len(frames), frame_start, frame_end)
    telemetry_hz = estimate_rate(len(telemetry.t_ms), tele_start, tele_end)

    print(f"Segment: {segment_dir}")
    print(f"Frames: {len(frames)}")
    print(f"Telemetry rows: {len(telemetry.t_ms)}")
    print(f"Approx FPS: {fps:.2f}")
    print(f"Approx telemetry_hz: {telemetry_hz:.2f}")
    print(f"Duration: {duration_ms / 1000.0:.3f}s")


def choose_start_frame(frames: list[FrameRow], start_ms: float) -> int:
    target = frames[0].t_ms + start_ms
    frame_times = [row.t_ms for row in frames]
    idx = bisect_left(frame_times, target)
    if idx >= len(frames):
        return len(frames) - 1
    return idx


def match_telemetry_index(frame_t_ms: float, telemetry_t_ms: list[float], mode: str) -> int:
    if mode == "prev":
        idx = bisect_right(telemetry_t_ms, frame_t_ms) - 1
        return max(idx, 0)

    idx = bisect_left(telemetry_t_ms, frame_t_ms)
    if idx <= 0:
        return 0
    if idx >= len(telemetry_t_ms):
        return len(telemetry_t_ms) - 1
    prev_idx = idx - 1
    if abs(telemetry_t_ms[prev_idx] - frame_t_ms) <= abs(telemetry_t_ms[idx] - frame_t_ms):
        return prev_idx
    return idx


def _arrow_keys() -> tuple[set[int], set[int], set[int], set[int]]:
    left = {81, 2424832, 65361}
    right = {83, 2555904, 65363}
    up = {82, 2490368, 65362}
    down = {84, 2621440, 65364}
    return left, right, up, down


def draw_overlay(
    cv2: Any,
    frame_bgr: Any,
    frame_t_ms: float,
    dt_to_telemetry_ms: float,
    telemetry: TelemetryData,
    telemetry_idx: int,
    playback_speed: float,
    show_dt: bool,
    frame_pos: int,
    frame_count: int,
) -> Any:
    speed_kmh = float(telemetry.fields["speed_kmh"][telemetry_idx])
    steer = float(telemetry.fields["steer"][telemetry_idx])
    gas = float(telemetry.fields["gas"][telemetry_idx])
    brake = float(telemetry.fields["brake"][telemetry_idx])
    gear = int(telemetry.fields["gear"][telemetry_idx])
    rpms = int(telemetry.fields["rpms"][telemetry_idx])

    lines = [f"t_ms: {frame_t_ms:.1f}"]
    if show_dt:
        lines.append(f"dt_to_telemetry_ms: {dt_to_telemetry_ms:+.2f}")
    lines.extend(
        [
            f"speed_kmh: {speed_kmh:.2f}",
            f"steer: {steer:.3f}",
            f"gas: {gas:.3f}",
            f"brake: {brake:.3f}",
            f"gear: {gear}",
            f"rpms: {rpms}",
            f"playback: {playback_speed:.2f}x",
            f"frame: {frame_pos + 1}/{frame_count}",
        ]
    )

    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.45
    thickness = 1
    line_height = 18
    origin_x = 12
    origin_y = 22

    max_width = 0
    for line in lines:
        (text_w, _), _ = cv2.getTextSize(line, font, scale, thickness)
        if text_w > max_width:
            max_width = text_w
    box_height = (line_height * len(lines)) + 10
    cv2.rectangle(frame_bgr, (6, 6), (origin_x + max_width + 10, box_height), (0, 0, 0), -1)
    cv2.rectangle(frame_bgr, (6, 6), (origin_x + max_width + 10, box_height), (255, 255, 255), 1)

    y = origin_y
    for line in lines:
        cv2.putText(frame_bgr, line, (origin_x, y), font, scale, (255, 255, 255), thickness, cv2.LINE_AA)
        y += line_height
    return frame_bgr


def import_cv2() -> Any:
    try:
        import cv2
    except ImportError:
        raise RuntimeError("OpenCV is required for inspect_segment. Install with: pip install opencv-python")
    return cv2


def run(args: argparse.Namespace) -> int:
    segment_dir = Path(args.segment).resolve()
    try:
        validate_segment(segment_dir)
        frames = load_frames(segment_dir)
        telemetry = load_telemetry(segment_dir)
        cv2 = import_cv2()
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print_stats(segment_dir, frames, telemetry)
    print("Controls: Space pause/resume | Left/Right step (paused) | Up/Down speed | r reset | Esc/q quit")

    speeds = [0.25, 0.5, 1.0, 2.0, 4.0]
    speed_idx = 2
    paused = False
    frame_idx = choose_start_frame(frames, args.start_ms)
    frame_count = len(frames)
    last_frame_idx = frame_count - 1
    left_keys, right_keys, up_keys, down_keys = _arrow_keys()

    window_name = f"Segment Inspector - {segment_dir.name}"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

    while True:
        frame_row = frames[frame_idx]
        frame_bgr = cv2.imread(str(frame_row.path), cv2.IMREAD_COLOR)
        if frame_bgr is None:
            print(f"Could not load frame: {frame_row.path}", file=sys.stderr)
            if frame_idx >= last_frame_idx:
                break
            frame_idx += 1
            continue

        telemetry_idx = match_telemetry_index(frame_row.t_ms, telemetry.t_ms, args.match)
        dt_to_telemetry_ms = telemetry.t_ms[telemetry_idx] - frame_row.t_ms
        if not args.no_overlay:
            frame_bgr = draw_overlay(
                cv2=cv2,
                frame_bgr=frame_bgr,
                frame_t_ms=frame_row.t_ms,
                dt_to_telemetry_ms=dt_to_telemetry_ms,
                telemetry=telemetry,
                telemetry_idx=telemetry_idx,
                playback_speed=speeds[speed_idx],
                show_dt=args.show_dt,
                frame_pos=frame_idx,
                frame_count=frame_count,
            )

        cv2.imshow(window_name, frame_bgr)

        if paused:
            wait_ms = 30
        elif frame_idx < last_frame_idx:
            frame_delta_ms = frames[frame_idx + 1].t_ms - frame_row.t_ms
            if frame_delta_ms <= 0:
                frame_delta_ms = 1.0
            wait_ms = max(1, min(250, int(frame_delta_ms / speeds[speed_idx])))
        else:
            wait_ms = 30

        key = cv2.waitKeyEx(wait_ms)
        if key in (27, ord("q"), ord("Q")):
            break
        if key == ord(" "):
            paused = not paused
        elif key in left_keys and paused:
            frame_idx = max(0, frame_idx - 1)
        elif key in right_keys and paused:
            frame_idx = min(last_frame_idx, frame_idx + 1)
        elif key in up_keys:
            speed_idx = min(speed_idx + 1, len(speeds) - 1)
            print(f"Playback speed: {speeds[speed_idx]:.2f}x")
        elif key in down_keys:
            speed_idx = max(speed_idx - 1, 0)
            print(f"Playback speed: {speeds[speed_idx]:.2f}x")
        elif key in (ord("r"), ord("R")):
            frame_idx = 0
            print("Reset to start")

        if not paused:
            if frame_idx < last_frame_idx:
                frame_idx += 1
            else:
                paused = True

    cv2.destroyAllWindows()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())

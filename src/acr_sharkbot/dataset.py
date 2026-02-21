from __future__ import annotations

import argparse
import csv
import sys
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


def _import_cv2() -> Any:
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("OpenCV is required. Install with: pip install opencv-python") from exc
    return cv2


def _require_columns(reader: csv.DictReader, required: list[str], csv_path: Path) -> None:
    if reader.fieldnames is None:
        raise ValueError(f"{csv_path} is missing a header row")
    missing = [name for name in required if name not in reader.fieldnames]
    if missing:
        raise ValueError(f"{csv_path} is missing required column(s): {', '.join(missing)}")


def _match_telemetry_index(frame_t_ms: float, telemetry_t_ms: list[float], mode: str) -> int:
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


@dataclass(slots=True)
class FrameRow:
    t_ms: float
    path: Path


@dataclass(slots=True)
class TelemetryData:
    t_ms: list[float]
    steer: list[float]
    speed_kmh: list[float]
    gas: list[float]
    brake: list[float]


@dataclass(slots=True)
class SampleMeta:
    image_path: Path
    t_ms: float
    steer: float
    speed: float
    gas: float
    brake: float


class SegmentDataset:
    def __init__(
        self,
        segment_path: str | Path,
        image_size: tuple[int, int] = (160, 90),
        match: str = "prev",
    ) -> None:
        if match not in ("prev", "nearest"):
            raise ValueError("match must be one of: 'prev', 'nearest'")
        if len(image_size) != 2:
            raise ValueError("image_size must be a (width, height) tuple")
        width, height = int(image_size[0]), int(image_size[1])
        if width <= 0 or height <= 0:
            raise ValueError("image_size width and height must be > 0")

        self.segment_path = Path(segment_path).resolve()
        if not self.segment_path.is_dir():
            raise FileNotFoundError(f"Segment folder not found: {self.segment_path}")

        self.image_size = (width, height)
        self.match = match
        self._cv2 = _import_cv2()
        self._frames = self._load_frames()
        telemetry = self._load_telemetry()
        self._samples = self._build_samples(telemetry)
        if not self._samples:
            raise ValueError(f"No aligned frame samples found in {self.segment_path}")

    def _load_frames(self) -> list[FrameRow]:
        frames_csv = self.segment_path / "frames.csv"
        if not frames_csv.is_file():
            raise FileNotFoundError(f"Missing required file: {frames_csv}")

        rows: list[FrameRow] = []
        with open(frames_csv, "r", newline="", encoding="utf-8") as fp:
            reader = csv.DictReader(fp)
            _require_columns(reader, ["t_ms", "path"], frames_csv)
            for raw in reader:
                rel = (raw.get("path") or "").strip()
                if not rel:
                    continue
                frame_path = Path(rel)
                if not frame_path.is_absolute():
                    frame_path = self.segment_path / frame_path
                rows.append(FrameRow(t_ms=float(raw["t_ms"]), path=frame_path))

        if not rows:
            raise ValueError(f"No frame rows found in {frames_csv}")
        rows.sort(key=lambda row: row.t_ms)
        return rows

    def _load_telemetry(self) -> TelemetryData:
        telemetry_csv = self.segment_path / "telemetry.csv"
        if not telemetry_csv.is_file():
            raise FileNotFoundError(f"Missing required file: {telemetry_csv}")

        records: list[tuple[float, float, float, float, float]] = []
        with open(telemetry_csv, "r", newline="", encoding="utf-8") as fp:
            reader = csv.DictReader(fp)
            _require_columns(reader, ["t_ms", "steer", "speed_kmh", "gas", "brake"], telemetry_csv)
            for raw in reader:
                records.append(
                    (
                        float(raw["t_ms"]),
                        float(raw["steer"]),
                        float(raw["speed_kmh"]),
                        float(raw["gas"]),
                        float(raw["brake"]),
                    )
                )

        if not records:
            raise ValueError(f"No telemetry rows found in {telemetry_csv}")
        records.sort(key=lambda row: row[0])
        return TelemetryData(
            t_ms=[row[0] for row in records],
            steer=[row[1] for row in records],
            speed_kmh=[row[2] for row in records],
            gas=[row[3] for row in records],
            brake=[row[4] for row in records],
        )

    def _build_samples(self, telemetry: TelemetryData) -> list[SampleMeta]:
        samples: list[SampleMeta] = []
        for frame in self._frames:
            telemetry_idx = _match_telemetry_index(frame.t_ms, telemetry.t_ms, self.match)
            samples.append(
                SampleMeta(
                    image_path=frame.path,
                    t_ms=frame.t_ms,
                    steer=float(telemetry.steer[telemetry_idx]),
                    speed=float(telemetry.speed_kmh[telemetry_idx]),
                    gas=float(telemetry.gas[telemetry_idx]),
                    brake=float(telemetry.brake[telemetry_idx]),
                )
            )
        return samples

    def __len__(self) -> int:
        return len(self._samples)

    def __getitem__(self, index: int) -> dict[str, Any]:
        if not isinstance(index, int):
            raise TypeError("index must be int")
        if index < 0:
            index += len(self._samples)
        if index < 0 or index >= len(self._samples):
            raise IndexError("index out of range")

        sample = self._samples[index]
        image_bgr = self._cv2.imread(str(sample.image_path), self._cv2.IMREAD_COLOR)
        if image_bgr is None:
            raise FileNotFoundError(f"Could not load image: {sample.image_path}")

        width, height = self.image_size
        image_bgr = self._cv2.resize(image_bgr, (width, height), interpolation=self._cv2.INTER_AREA)
        image_rgb = self._cv2.cvtColor(image_bgr, self._cv2.COLOR_BGR2RGB)
        image = image_rgb.astype(np.float32) / 255.0

        return {
            "image": image,
            "steer": sample.steer,
            "speed": sample.speed,
            "gas": sample.gas,
            "brake": sample.brake,
        }

    @property
    def cv2(self) -> Any:
        return self._cv2


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Quick visualization test for SegmentDataset.")
    parser.add_argument("segment_path", help="Path to segment directory")
    parser.add_argument(
        "--image-size",
        nargs=2,
        type=int,
        metavar=("WIDTH", "HEIGHT"),
        default=(160, 90),
        help="Output image size as WIDTH HEIGHT",
    )
    parser.add_argument("--match", choices=("prev", "nearest"), default="prev")
    parser.add_argument("--index", type=int, default=0, help="Sample index to inspect")
    return parser.parse_args(argv)


def _run_main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        dataset = SegmentDataset(
            segment_path=args.segment_path,
            image_size=(args.image_size[0], args.image_size[1]),
            match=args.match,
        )
        sample = dataset[args.index]
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    image = sample["image"]
    print(f"Dataset length: {len(dataset)}")
    print(f"Image shape: {image.shape}")
    print(f"Image dtype: {image.dtype}")
    print(
        "Values:"
        f" steer={sample['steer']:.4f}"
        f" speed={sample['speed']:.2f}"
        f" gas={sample['gas']:.3f}"
        f" brake={sample['brake']:.3f}"
    )

    image_u8 = np.clip(image * 255.0, 0.0, 255.0).astype(np.uint8)
    image_bgr = dataset.cv2.cvtColor(image_u8, dataset.cv2.COLOR_RGB2BGR)
    dataset.cv2.imshow("SegmentDataset sample", image_bgr)
    print("Press any key in the image window to close.")
    dataset.cv2.waitKey(0)
    dataset.cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(_run_main())

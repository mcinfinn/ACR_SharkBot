from __future__ import annotations

import argparse
import csv
import ctypes as C
import io
import json
import os
import sys
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque

from acr_sharkbot.physics_struct import Physics, looks_uninitialized
from acr_sharkbot.shm import MappedView, open_mmf_readonly

PHYSICS_MAP_DEFAULT = r"Local\acpmf_physics"

DEFAULT_GAS_TH = 0.05
DEFAULT_BRAKE_TH = 0.05
DEFAULT_STEER_TH = 0.02
DEFAULT_SPEED_TH = 1.0
DEFAULT_START_DEBOUNCE = 0.25
DEFAULT_STOP_AFTER = 2.0
DEFAULT_PRE_ROLL = 1.0
DEFAULT_POST_ROLL = 1.0

TELEMETRY_COLUMNS = [
    "t_ms",
    "packet_id",
    "speed_kmh",
    "steer",
    "gas",
    "brake",
    "gear",
    "rpms",
    "heading",
    "pitch",
    "roll",
    "accg_x",
    "accg_y",
    "accg_z",
    "vel_x",
    "vel_y",
    "vel_z",
    "wheel_slip_fl",
    "wheel_slip_fr",
    "wheel_slip_rl",
    "wheel_slip_rr",
]

FRAME_COLUMNS = ["t_ms", "frame_idx", "path"]

if os.name == "nt":
    import msvcrt
else:
    msvcrt = None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


@dataclass(slots=True)
class TelemetrySample:
    t_ms: float
    packet_id: int
    speed_kmh: float
    steer: float
    gas: float
    brake: float
    gear: int
    rpms: int
    heading: float
    pitch: float
    roll: float
    accg_x: float
    accg_y: float
    accg_z: float
    vel_x: float
    vel_y: float
    vel_z: float
    wheel_slip_fl: float
    wheel_slip_fr: float
    wheel_slip_rl: float
    wheel_slip_rr: float

    def csv_row(self) -> list[Any]:
        return [
            f"{self.t_ms:.3f}",
            self.packet_id,
            self.speed_kmh,
            self.steer,
            self.gas,
            self.brake,
            self.gear,
            self.rpms,
            self.heading,
            self.pitch,
            self.roll,
            self.accg_x,
            self.accg_y,
            self.accg_z,
            self.vel_x,
            self.vel_y,
            self.vel_z,
            self.wheel_slip_fl,
            self.wheel_slip_fr,
            self.wheel_slip_rl,
            self.wheel_slip_rr,
        ]


@dataclass(slots=True)
class FrameSample:
    t_ms: float
    jpeg_bytes: bytes


class TimedRingBuffer:
    def __init__(self, window_sec: float):
        self.window_ms = max(window_sec, 0.0) * 1000.0
        self._items: Deque[Any] = deque()

    def append(self, item: Any) -> None:
        self._items.append(item)
        self.prune(item.t_ms)

    def prune(self, now_ms: float) -> None:
        cutoff = now_ms - self.window_ms
        while self._items and self._items[0].t_ms < cutoff:
            self._items.popleft()

    def since(self, cutoff_ms: float) -> list[Any]:
        return [item for item in self._items if item.t_ms >= cutoff_ms]


class PhysicsSharedMemory:
    def __init__(self, map_name: str, struct_size: int):
        self.map_name = map_name
        self.struct_size = struct_size
        self._buf = Physics()
        self.view: MappedView | None = None
        self.connected = False
        self.next_retry_at = 0.0
        self.last_wait_notice = 0.0

    def close(self) -> None:
        if self.view is not None:
            self.view.close()
            self.view = None
        if self.connected:
            print(f"Disconnected shared memory: {self.map_name}")
        self.connected = False

    def _try_connect(self, now: float) -> None:
        if self.view is not None or now < self.next_retry_at:
            return
        view = open_mmf_readonly(self.map_name, self.struct_size)
        self.next_retry_at = now + 1.0
        if view is None:
            if now - self.last_wait_notice >= 5.0:
                print(f"Waiting for shared memory: {self.map_name}")
                self.last_wait_notice = now
            return
        self.view = view
        self.connected = True
        self.last_wait_notice = 0.0
        print(f"Connected shared memory: {self.map_name}")

    def read(self, now: float) -> Physics | None:
        self._try_connect(now)
        if self.view is None:
            return None
        try:
            C.memmove(C.addressof(self._buf), self.view.addr, self.struct_size)
            return self._buf
        except Exception:
            self.close()
            self.next_retry_at = now + 1.0
            return None


class SegmentWriter:
    def __init__(
        self,
        session_dir: Path,
        segment_index: int,
        map_name: str,
        struct_size: int,
        capture_region: dict[str, int],
        rates: dict[str, float],
        thresholds: dict[str, float],
        timing: dict[str, float],
        jpeg_quality: int,
        config_snapshot: dict[str, Any],
    ):
        self.segment_index = segment_index
        self.segment_name = f"segment_{segment_index:04d}"
        self.segment_dir = session_dir / self.segment_name
        self.frames_dir = self.segment_dir / "frames"
        self.segment_dir.mkdir(parents=True, exist_ok=False)
        self.frames_dir.mkdir(parents=True, exist_ok=True)

        self.telemetry_fp = open(self.segment_dir / "telemetry.csv", "w", newline="", encoding="utf-8")
        self.frames_fp = open(self.segment_dir / "frames.csv", "w", newline="", encoding="utf-8")
        self.telemetry_writer = csv.writer(self.telemetry_fp)
        self.frames_writer = csv.writer(self.frames_fp)
        self.telemetry_writer.writerow(TELEMETRY_COLUMNS)
        self.frames_writer.writerow(FRAME_COLUMNS)

        self.telemetry_rows = 0
        self.frame_rows = 0
        self.frame_idx = 0
        self.last_telemetry_t_ms = -1.0
        self.last_frame_t_ms = -1.0
        self.start_time = utc_now_iso()
        self.start_t_ms = 0.0
        self.map_name = map_name
        self.struct_size = struct_size
        self.capture_region = capture_region
        self.rates = rates
        self.thresholds = thresholds
        self.timing = timing
        self.jpeg_quality = jpeg_quality
        self.config_snapshot = config_snapshot
        self.closed = False

    def mark_start(self, start_t_ms: float) -> None:
        self.start_t_ms = start_t_ms

    def write_telemetry(self, sample: TelemetrySample) -> None:
        if sample.t_ms < self.last_telemetry_t_ms:
            return
        self.telemetry_writer.writerow(sample.csv_row())
        self.telemetry_rows += 1
        self.last_telemetry_t_ms = sample.t_ms

    def write_frame(self, sample: FrameSample) -> None:
        if sample.t_ms < self.last_frame_t_ms:
            return
        frame_name = f"frame_{self.frame_idx:06d}.jpg"
        frame_rel_path = f"frames/{frame_name}"
        frame_path = self.frames_dir / frame_name
        with open(frame_path, "wb") as fp:
            fp.write(sample.jpeg_bytes)
        self.frames_writer.writerow([f"{sample.t_ms:.3f}", self.frame_idx, frame_rel_path])
        self.frame_rows += 1
        self.frame_idx += 1
        self.last_frame_t_ms = sample.t_ms

    def close(self, end_t_ms: float, reason: str) -> None:
        if self.closed:
            return
        self.telemetry_fp.flush()
        self.frames_fp.flush()
        self.telemetry_fp.close()
        self.frames_fp.close()
        meta = {
            "segment_index": self.segment_index,
            "segment_name": self.segment_name,
            "start_time": self.start_time,
            "end_time": utc_now_iso(),
            "start_t_ms": round(self.start_t_ms, 3),
            "end_t_ms": round(end_t_ms, 3),
            "duration_ms": round(max(0.0, end_t_ms - self.start_t_ms), 3),
            "stop_reason": reason,
            "physics_map": self.map_name,
            "physics_struct_size": self.struct_size,
            "capture_region": self.capture_region,
            "rates": self.rates,
            "activity_thresholds": self.thresholds,
            "timing": self.timing,
            "jpeg_quality": self.jpeg_quality,
            "rows": {
                "telemetry": self.telemetry_rows,
                "frames": self.frame_rows,
            },
            "output_files": {
                "telemetry_csv": "telemetry.csv",
                "frames_csv": "frames.csv",
                "frames_dir": "frames",
            },
            "config_snapshot": self.config_snapshot,
        }
        write_json(self.segment_dir / "meta.json", meta)
        self.closed = True


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record AC Rally telemetry + screen segments.")
    parser.add_argument("--physics-map", default=PHYSICS_MAP_DEFAULT, help="Physics map name")
    parser.add_argument("--telemetry-hz", type=float, default=100.0, help="Telemetry poll rate")
    parser.add_argument("--fps", type=float, default=20.0, help="Frame capture rate while armed/recording")
    parser.add_argument("--disarmed-fps", type=float, default=2.0, help="Frame capture rate while disarmed")
    parser.add_argument("--quality", type=int, default=85, help="JPEG quality (1-95)")
    parser.add_argument("--runs-dir", default="runs", help="Output root directory")
    parser.add_argument("--full-monitor", action="store_true", help="Capture full primary monitor")
    parser.add_argument("--left", type=int, default=None, help="Capture region left")
    parser.add_argument("--top", type=int, default=None, help="Capture region top")
    parser.add_argument("--width", type=int, default=640, help="Capture region width")
    parser.add_argument("--height", type=int, default=360, help="Capture region height")

    parser.add_argument("--gas-th", type=float, default=DEFAULT_GAS_TH, help="Activity threshold for gas")
    parser.add_argument("--brake-th", type=float, default=DEFAULT_BRAKE_TH, help="Activity threshold for brake")
    parser.add_argument("--steer-th", type=float, default=DEFAULT_STEER_TH, help="Activity threshold for steer")
    parser.add_argument("--speed-th", type=float, default=DEFAULT_SPEED_TH, help="Activity threshold for speed")
    parser.add_argument("--start-debounce", type=float, default=DEFAULT_START_DEBOUNCE, help="Seconds active before start")
    parser.add_argument("--stop-after", type=float, default=DEFAULT_STOP_AFTER, help="Seconds inactive before stop countdown")
    parser.add_argument("--pre-roll", type=float, default=DEFAULT_PRE_ROLL, help="Seconds of pre-roll to flush on start")
    parser.add_argument("--post-roll", type=float, default=DEFAULT_POST_ROLL, help="Seconds to keep recording after stop")

    args = parser.parse_args(argv)
    if args.telemetry_hz <= 0:
        parser.error("--telemetry-hz must be > 0")
    if args.fps <= 0:
        parser.error("--fps must be > 0")
    if args.disarmed_fps <= 0:
        parser.error("--disarmed-fps must be > 0")
    if not (1 <= args.quality <= 95):
        parser.error("--quality must be between 1 and 95")
    if args.width <= 0 or args.height <= 0:
        parser.error("--width and --height must be > 0")
    if args.start_debounce < 0 or args.stop_after < 0 or args.pre_roll < 0 or args.post_roll < 0:
        parser.error("Debounce and roll values must be >= 0")
    return args


def load_capture_libs() -> tuple[Any, Any]:
    try:
        import mss
    except ImportError:
        raise RuntimeError("Missing dependency: mss. Install with: pip install mss pillow")
    try:
        from PIL import Image
    except ImportError:
        raise RuntimeError("Missing dependency: pillow. Install with: pip install mss pillow")
    return mss, Image


def resolve_capture_region(sct: Any, args: argparse.Namespace) -> tuple[dict[str, int], dict[str, int]]:
    if len(sct.monitors) < 2:
        raise RuntimeError("No monitor found for mss capture.")
    primary = {k: int(sct.monitors[1][k]) for k in ("left", "top", "width", "height")}
    if args.full_monitor:
        return dict(primary), primary

    left = args.left
    top = args.top
    width = int(args.width)
    height = int(args.height)
    if left is None:
        left = primary["left"] + max((primary["width"] - width) // 2, 0)
    if top is None:
        top = primary["top"] + max((primary["height"] - height) // 2, 0)
    region = {"left": int(left), "top": int(top), "width": width, "height": height}
    return region, primary


def physics_to_sample(t_ms: float, p: Physics) -> TelemetrySample:
    return TelemetrySample(
        t_ms=t_ms,
        packet_id=int(p.PacketId),
        speed_kmh=float(p.SpeedKmh),
        steer=float(p.SteerAngle),
        gas=float(p.Gas),
        brake=float(p.Brake),
        gear=int(p.Gear),
        rpms=int(p.Rpms),
        heading=float(p.Heading),
        pitch=float(p.Pitch),
        roll=float(p.Roll),
        accg_x=float(p.AccG[0]),
        accg_y=float(p.AccG[1]),
        accg_z=float(p.AccG[2]),
        vel_x=float(p.Velocity[0]),
        vel_y=float(p.Velocity[1]),
        vel_z=float(p.Velocity[2]),
        wheel_slip_fl=float(p.WheelSlip[0]),
        wheel_slip_fr=float(p.WheelSlip[1]),
        wheel_slip_rl=float(p.WheelSlip[2]),
        wheel_slip_rr=float(p.WheelSlip[3]),
    )


def is_active(sample: TelemetrySample, args: argparse.Namespace) -> bool:
    return (
        sample.gas > args.gas_th
        or sample.brake > args.brake_th
        or abs(sample.steer) > args.steer_th
        or sample.speed_kmh > args.speed_th
    )


def is_inactive_for_stop(sample: TelemetrySample, args: argparse.Namespace) -> bool:
    return (
        sample.gas <= args.gas_th
        and sample.brake <= args.brake_th
        and abs(sample.steer) <= args.steer_th
        and sample.speed_kmh <= args.speed_th
    )


def capture_frame_sample(sct: Any, image_module: Any, region: dict[str, int], quality: int, t_ms: float) -> FrameSample:
    raw = sct.grab(region)
    image = image_module.frombytes("RGB", raw.size, raw.rgb)
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=quality)
    return FrameSample(t_ms=t_ms, jpeg_bytes=buf.getvalue())


def poll_hotkeys() -> list[str]:
    if msvcrt is None:
        return []
    keys: list[str] = []
    while msvcrt.kbhit():
        key = msvcrt.getwch()
        if key in ("\x00", "\xe0"):
            if msvcrt.kbhit():
                msvcrt.getwch()
            continue
        keys.append(key.lower())
    return keys


def session_folder(base_dir: Path) -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    session_dir = base_dir / f"session_{stamp}"
    suffix = 1
    while session_dir.exists():
        suffix += 1
        session_dir = base_dir / f"session_{stamp}_{suffix:02d}"
    session_dir.mkdir(parents=True, exist_ok=False)
    return session_dir


def run(args: argparse.Namespace) -> int:
    try:
        mss, image_module = load_capture_libs()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    runs_dir = Path(args.runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    session_dir = session_folder(runs_dir)

    struct_size = C.sizeof(Physics)
    thresholds = {
        "gas_th": args.gas_th,
        "brake_th": args.brake_th,
        "steer_th": args.steer_th,
        "speed_th": args.speed_th,
    }
    timing = {
        "start_debounce": args.start_debounce,
        "stop_after": args.stop_after,
        "pre_roll": args.pre_roll,
        "post_roll": args.post_roll,
    }
    rates = {
        "telemetry_hz": args.telemetry_hz,
        "frame_fps": args.fps,
        "disarmed_fps": args.disarmed_fps,
    }
    config_snapshot = {
        "physics_map": args.physics_map,
        "thresholds": thresholds,
        "timing": timing,
        "rates": rates,
        "jpeg_quality": args.quality,
        "capture": {
            "full_monitor": bool(args.full_monitor),
            "left": args.left,
            "top": args.top,
            "width": args.width,
            "height": args.height,
        },
    }
    session_meta_path = session_dir / "session_meta.json"
    session_meta: dict[str, Any] = {
        "start_time": utc_now_iso(),
        "session_dir": str(session_dir),
        "physics_map": args.physics_map,
        "physics_struct_size": struct_size,
        "config_snapshot": config_snapshot,
    }
    write_json(session_meta_path, session_meta)

    print(f"Session: {session_dir}")
    print(f"Physics struct size: {struct_size} bytes")
    print("Hotkeys: [l] arm/disarm auto-record, [q] quit")
    print("Armed: OFF")

    reader = PhysicsSharedMemory(args.physics_map, struct_size)
    pre_roll_window = max(args.pre_roll, args.start_debounce, 0.0)
    telemetry_buffer = TimedRingBuffer(pre_roll_window)
    frame_buffer = TimedRingBuffer(max(args.pre_roll, 0.0))

    armed = False
    segment_count = 0
    segment_writer: SegmentWriter | None = None
    active_since_ms: float | None = None
    inactive_since_ms: float | None = None
    pending_stop_deadline_ms: float | None = None
    pending_stop_reason: str = "inactive"
    last_telemetry_t_ms: float | None = None
    status_last_print = 0.0

    t0 = time.perf_counter()
    next_telemetry = t0
    next_frame = t0
    frame_fps = max(args.disarmed_fps, 0.1)
    telemetry_interval = 1.0 / args.telemetry_hz
    start_debounce_ms = args.start_debounce * 1000.0
    stop_after_ms = args.stop_after * 1000.0
    post_roll_ms = args.post_roll * 1000.0

    with mss.mss() as sct:
        capture_region, primary_monitor = resolve_capture_region(sct, args)
        config_snapshot["capture"]["resolved_region"] = capture_region
        config_snapshot["capture"]["primary_monitor"] = primary_monitor
        session_meta["capture_region"] = capture_region
        session_meta["primary_monitor"] = primary_monitor
        write_json(session_meta_path, session_meta)
        print(f"Capture region: {capture_region}")

        def start_segment(trigger_t_ms: float) -> None:
            nonlocal segment_count, segment_writer, active_since_ms, inactive_since_ms, pending_stop_deadline_ms
            segment_count += 1
            segment_writer = SegmentWriter(
                session_dir=session_dir,
                segment_index=segment_count,
                map_name=args.physics_map,
                struct_size=struct_size,
                capture_region=capture_region,
                rates=rates,
                thresholds=thresholds,
                timing=timing,
                jpeg_quality=args.quality,
                config_snapshot=config_snapshot,
            )
            segment_writer.mark_start(trigger_t_ms)
            cutoff = trigger_t_ms - (args.pre_roll * 1000.0)
            for sample in telemetry_buffer.since(cutoff):
                segment_writer.write_telemetry(sample)
            for frame in frame_buffer.since(cutoff):
                segment_writer.write_frame(frame)
            active_since_ms = None
            inactive_since_ms = None
            pending_stop_deadline_ms = None
            print(f"Segment recording ON: {segment_writer.segment_name} (segments={segment_count})")

        def stop_segment(now_t_ms: float, reason: str) -> None:
            nonlocal segment_writer, active_since_ms, inactive_since_ms, pending_stop_deadline_ms
            if segment_writer is None:
                return
            name = segment_writer.segment_name
            segment_writer.close(now_t_ms, reason)
            segment_writer = None
            active_since_ms = None
            inactive_since_ms = None
            pending_stop_deadline_ms = None
            print(f"Segment recording OFF: {name} reason={reason} (segments={segment_count})")

        running = True
        try:
            while running:
                now = time.perf_counter()
                for key in poll_hotkeys():
                    if key == "q":
                        running = False
                        break
                    if key == "l":
                        armed = not armed
                        print(f"Armed: {'ON' if armed else 'OFF'}")
                        active_since_ms = None
                        if armed:
                            pending_stop_deadline_ms = None
                            inactive_since_ms = None
                        elif segment_writer is not None and pending_stop_deadline_ms is None:
                            pending_stop_deadline_ms = ((time.perf_counter() - t0) * 1000.0) + post_roll_ms
                            pending_stop_reason = "disarmed"
                            print(f"Disarmed while recording: stopping after post-roll ({args.post_roll:.2f}s)")
                if not running:
                    break

                while now >= next_telemetry:
                    telemetry_t_ms = (time.perf_counter() - t0) * 1000.0
                    physics = reader.read(now)
                    next_telemetry += telemetry_interval
                    if physics is None or looks_uninitialized(physics):
                        now = time.perf_counter()
                        continue
                    sample = physics_to_sample(telemetry_t_ms, physics)
                    last_telemetry_t_ms = sample.t_ms
                    telemetry_buffer.append(sample)

                    active_now = is_active(sample, args)
                    started_this_tick = False
                    if segment_writer is None:
                        if armed and active_now:
                            if active_since_ms is None:
                                active_since_ms = sample.t_ms
                            if sample.t_ms - active_since_ms >= start_debounce_ms:
                                start_segment(sample.t_ms)
                                started_this_tick = True
                        else:
                            active_since_ms = None

                    if segment_writer is not None and not started_this_tick:
                        segment_writer.write_telemetry(sample)

                    if segment_writer is not None:
                        inactive_for_stop = is_inactive_for_stop(sample, args)
                        if not armed:
                            if pending_stop_deadline_ms is None:
                                pending_stop_deadline_ms = sample.t_ms + post_roll_ms
                                pending_stop_reason = "disarmed"
                        elif not inactive_for_stop:
                            inactive_since_ms = None
                            pending_stop_deadline_ms = None
                        else:
                            if inactive_since_ms is None:
                                inactive_since_ms = sample.t_ms
                            if pending_stop_deadline_ms is None and (sample.t_ms - inactive_since_ms) >= stop_after_ms:
                                pending_stop_deadline_ms = sample.t_ms + post_roll_ms
                                pending_stop_reason = "inactive"
                                print(f"Stop countdown started: post-roll {args.post_roll:.2f}s")
                    now = time.perf_counter()

                desired_fps = args.fps if (armed or segment_writer is not None) else args.disarmed_fps
                desired_fps = max(desired_fps, 0.1)
                if desired_fps != frame_fps:
                    frame_fps = desired_fps
                    next_frame = now
                frame_interval = 1.0 / frame_fps
                if now >= next_frame:
                    frame_t_ms = (time.perf_counter() - t0) * 1000.0
                    try:
                        frame_sample = capture_frame_sample(sct, image_module, capture_region, args.quality, frame_t_ms)
                    except Exception as exc:
                        print(f"Frame capture error: {exc}")
                        next_frame = now + frame_interval
                    else:
                        frame_buffer.append(frame_sample)
                        if segment_writer is not None:
                            segment_writer.write_frame(frame_sample)
                        next_frame = now + frame_interval

                now_t_ms = (time.perf_counter() - t0) * 1000.0
                if (
                    segment_writer is not None
                    and armed
                    and pending_stop_deadline_ms is None
                    and not reader.connected
                    and last_telemetry_t_ms is not None
                    and (now_t_ms - last_telemetry_t_ms) >= stop_after_ms
                ):
                    pending_stop_deadline_ms = now_t_ms + post_roll_ms
                    pending_stop_reason = "telemetry_disconnect"
                    print("Telemetry disconnected during segment: stopping after post-roll")

                if segment_writer is not None and pending_stop_deadline_ms is not None and now_t_ms >= pending_stop_deadline_ms:
                    stop_segment(now_t_ms, pending_stop_reason)

                if now - status_last_print >= 2.0:
                    print(
                        "Status | connected={} armed={} recording={} segments={}".format(
                            "YES" if reader.connected else "NO",
                            "ON" if armed else "OFF",
                            "ON" if segment_writer is not None else "OFF",
                            segment_count,
                        )
                    )
                    status_last_print = now

                next_wake = min(next_telemetry, next_frame)
                if pending_stop_deadline_ms is not None:
                    next_wake = min(next_wake, t0 + (pending_stop_deadline_ms / 1000.0))
                sleep_s = max(0.0, min(0.02, next_wake - time.perf_counter()))
                if sleep_s > 0:
                    time.sleep(sleep_s)
        except KeyboardInterrupt:
            print("KeyboardInterrupt received. Shutting down.")
        finally:
            now_t_ms = (time.perf_counter() - t0) * 1000.0
            if segment_writer is not None:
                stop_segment(now_t_ms, "shutdown")
            reader.close()

    session_meta["end_time"] = utc_now_iso()
    session_meta["duration_sec"] = round(time.perf_counter() - t0, 3)
    session_meta["segment_count"] = segment_count
    session_meta["final_state"] = {"armed": armed}
    write_json(session_meta_path, session_meta)
    print(f"Session complete. Segments recorded: {segment_count}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())

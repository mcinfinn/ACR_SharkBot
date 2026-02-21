from __future__ import annotations

import argparse
import sys
import time
from typing import Any

from acr_sharkbot.gamepad import GamepadController

try:
    import msvcrt
except ImportError:  # pragma: no cover - Windows-only hotkeys.
    msvcrt = None


INSTALL_CAPTURE_DEPS = "pip install mss pillow opencv-python"
DEFAULT_WIDTH = 640
DEFAULT_HEIGHT = 360
MODEL_INPUT_SIZE = (160, 90)  # (width, height)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Real-time driving scaffold with screen capture.")
    parser.add_argument("--fps", type=float, default=20.0, help="Capture/control update rate")
    parser.add_argument("--full-monitor", action="store_true", help="Capture full primary monitor")
    parser.add_argument("--left", type=int, default=None, help="Capture region left")
    parser.add_argument("--top", type=int, default=None, help="Capture region top")
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH, help="Capture region width")
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT, help="Capture region height")
    parser.add_argument("--throttle", type=float, default=0.5, help="Fixed throttle command [0, 1]")
    parser.add_argument("--brake", type=float, default=0.0, help="Fixed brake command [0, 1]")
    parser.add_argument("--seconds", type=float, default=None, help="Optional loop duration")
    parser.add_argument("--no-gamepad", action="store_true", help="Dry run: print outputs only")

    args = parser.parse_args(argv)
    if args.fps <= 0:
        parser.error("--fps must be > 0")
    if args.width <= 0 or args.height <= 0:
        parser.error("--width and --height must be > 0")
    if args.seconds is not None and args.seconds <= 0:
        parser.error("--seconds must be > 0 when provided")
    if not (0.0 <= args.throttle <= 1.0):
        parser.error("--throttle must be in [0, 1]")
    if not (0.0 <= args.brake <= 1.0):
        parser.error("--brake must be in [0, 1]")
    if args.full_monitor and (
        args.left is not None
        or args.top is not None
        or args.width != DEFAULT_WIDTH
        or args.height != DEFAULT_HEIGHT
    ):
        parser.error("--full-monitor cannot be combined with --left/--top/--width/--height")
    return args


def load_capture_libs() -> tuple[Any, Any, Any, Any]:
    try:
        import mss
    except ImportError as exc:
        raise RuntimeError(f"Missing dependency: mss. Install with: {INSTALL_CAPTURE_DEPS}") from exc
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(f"Missing dependency: pillow. Install with: {INSTALL_CAPTURE_DEPS}") from exc
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError(
            f"Missing dependency: opencv-python. Install with: {INSTALL_CAPTURE_DEPS}"
        ) from exc
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(
            f"Missing dependency: numpy (installed by opencv-python). Install with: {INSTALL_CAPTURE_DEPS}"
        ) from exc
    return mss, Image, cv2, np


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


def preprocess_frame(raw: Any, image_module: Any, cv2_module: Any, np_module: Any) -> Any:
    image = image_module.frombytes("RGB", raw.size, raw.rgb)
    rgb = np_module.asarray(image, dtype=np_module.uint8)
    resized = cv2_module.resize(rgb, MODEL_INPUT_SIZE, interpolation=cv2_module.INTER_AREA)
    return resized.astype(np_module.float32) / 255.0


def policy_steer(_frame: Any) -> float:
    # Placeholder policy until model inference is integrated.
    return 0.0


def run(args: argparse.Namespace) -> int:
    try:
        mss, image_module, cv2_module, np_module = load_capture_libs()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    controller: GamepadController | None = None
    if not args.no_gamepad:
        try:
            controller = GamepadController()
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    period = 1.0 / args.fps
    start = time.monotonic()
    next_tick = start
    paused = False

    try:
        with mss.mss() as sct:
            capture_region, primary_monitor = resolve_capture_region(sct, args)
            print(f"Primary monitor: {primary_monitor}")
            print(f"Capture region: {capture_region}")
            print(f"Running at {args.fps:.2f} FPS. Hotkeys: p=pause/resume, q=quit")

            running = True
            while running:
                now = time.monotonic()
                if args.seconds is not None and (now - start) >= args.seconds:
                    break

                for key in poll_hotkeys():
                    if key == "q":
                        running = False
                        break
                    if key == "p":
                        paused = not paused
                        print(f"Paused: {'ON' if paused else 'OFF'}")
                        if paused and controller is not None:
                            controller.reset()
                if not running:
                    break

                if now < next_tick:
                    time.sleep(min(0.01, next_tick - now))
                    continue

                try:
                    raw = sct.grab(capture_region)
                    frame = preprocess_frame(raw, image_module, cv2_module, np_module)
                except Exception as exc:
                    print(f"Frame capture error: {exc}", file=sys.stderr)
                    next_tick = now + period
                    continue

                steer = policy_steer(frame)
                if not paused:
                    if controller is not None:
                        controller.set_controls(steer=steer, throttle=args.throttle, brake=args.brake)
                    else:
                        elapsed = now - start
                        print(
                            f"t={elapsed:7.3f}s steer={steer:+.3f}"
                            f" throttle={args.throttle:.3f} brake={args.brake:.3f}"
                        )

                next_tick += period
                if next_tick < time.monotonic() - period:
                    next_tick = time.monotonic()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted.")
        return 130
    finally:
        if controller is not None:
            try:
                controller.reset()
            finally:
                controller.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())

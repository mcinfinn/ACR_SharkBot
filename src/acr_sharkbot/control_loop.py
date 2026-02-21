from __future__ import annotations

import argparse
import math
import sys
import time

from acr_sharkbot.gamepad import GamepadController


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Minimal control loop scaffold.")
    parser.add_argument("--hz", type=float, default=20.0, help="Control update rate")
    parser.add_argument("--seconds", type=float, default=None, help="Optional loop duration")
    parser.add_argument(
        "--throttle-sweep",
        action="store_true",
        help="Run a diagnostic throttle sweep (0->1 in 2s, then 1->0 in 2s)",
    )
    parser.add_argument(
        "--brake-sweep",
        action="store_true",
        help="Run a diagnostic brake sweep (0->1 in 2s, then 1->0 in 2s)",
    )
    parser.add_argument(
        "--full-smoke",
        action="store_true",
        help="Run a 10s smoke test with sinusoidal steering, fixed throttle, and pulsed brake",
    )
    args = parser.parse_args(argv)
    if args.hz <= 0:
        parser.error("--hz must be > 0")
    if args.seconds is not None and args.seconds <= 0:
        parser.error("--seconds must be > 0 when provided")
    mode_count = int(args.throttle_sweep) + int(args.brake_sweep) + int(args.full_smoke)
    if mode_count > 1:
        parser.error("--throttle-sweep, --brake-sweep, and --full-smoke are mutually exclusive")
    if args.full_smoke and args.seconds is not None:
        parser.error("--full-smoke runs for a fixed 10s; omit --seconds")
    return args


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _trigger_int(value: float) -> int:
    clipped = _clip(value, 0.0, 1.0)
    return int(round(clipped * 255.0))


def _steer_int(value: float) -> int:
    clipped = _clip(value, -1.0, 1.0)
    return int(round(clipped * 32767.0))


def _sweep_throttle(elapsed_sec: float) -> float:
    phase = elapsed_sec % 4.0
    if phase < 2.0:
        return phase / 2.0
    return 1.0 - ((phase - 2.0) / 2.0)


def _full_smoke_controls(elapsed_sec: float) -> tuple[float, float, float]:
    steer = math.sin((2.0 * math.pi) * elapsed_sec)
    throttle = 0.3
    brake = 0.0 if (elapsed_sec % 1.5) < 1.0 else 0.6
    return steer, throttle, brake


def run(args: argparse.Namespace) -> int:
    controller: GamepadController | None = None
    steer = 0.0
    throttle = 0.0 if (args.throttle_sweep or args.brake_sweep or args.full_smoke) else 1.0
    brake = 0.0
    period = 1.0 / args.hz
    duration = 10.0 if args.full_smoke else args.seconds

    try:
        controller = GamepadController()
        start = time.monotonic()
        next_tick = start
        next_report = start

        while True:
            now = time.monotonic()
            elapsed = now - start
            if duration is not None and elapsed >= duration:
                break

            if args.full_smoke:
                steer, throttle, brake = _full_smoke_controls(elapsed)
            elif args.throttle_sweep:
                throttle = _sweep_throttle(elapsed)
                steer = 0.0
                brake = 0.0
            elif args.brake_sweep:
                brake = _sweep_throttle(elapsed)
                steer = 0.0
                throttle = 0.0

            controller.set_controls(steer=steer, throttle=throttle, brake=brake)

            if now >= next_report:
                if args.full_smoke:
                    steer_int = _steer_int(steer)
                    throttle_int = _trigger_int(throttle)
                    brake_int = _trigger_int(brake)
                    print(
                        f"t={elapsed:6.2f}s steer={steer:+.3f}({steer_int:+6d})"
                        f" throttle={throttle:.3f}({throttle_int:3d})"
                        f" brake={brake:.3f}({brake_int:3d})"
                    )
                elif args.throttle_sweep:
                    throttle_int = _trigger_int(throttle)
                    print(
                        f"t={elapsed:6.2f}s throttle={throttle:.3f} trigger={throttle_int:3d}"
                    )
                elif args.brake_sweep:
                    brake_int = _trigger_int(brake)
                    print(
                        f"t={elapsed:6.2f}s brake={brake:.3f} trigger={brake_int:3d}"
                    )
                else:
                    throttle_int = _trigger_int(throttle)
                    print(
                        f"t={elapsed:6.2f}s steer={steer:+.3f} throttle={throttle:.3f}"
                        f" brake={brake:.3f} trigger={throttle_int:3d}"
                    )
                next_report += 1.0

            next_tick += period
            sleep_for = next_tick - time.monotonic()
            if sleep_for > 0:
                time.sleep(sleep_for)
            else:
                next_tick = time.monotonic()

        print("Control loop complete.")
        return 0
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


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import math
import sys
import time

from acr_sharkbot.gamepad import GamepadController


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Virtual gamepad smoke test.")
    parser.add_argument("--seconds", type=float, default=5.0, help="Test duration in seconds")
    args = parser.parse_args(argv)
    if args.seconds <= 0:
        parser.error("--seconds must be > 0")
    return args


def run(args: argparse.Namespace) -> int:
    controller: GamepadController | None = None
    hz = 30.0
    period = 1.0 / hz
    frequency_hz = 0.5

    try:
        controller = GamepadController()
        start = time.monotonic()
        next_tick = start
        next_report = 1

        while True:
            now = time.monotonic()
            elapsed = now - start
            if elapsed >= args.seconds:
                break

            steer = math.sin(2.0 * math.pi * frequency_hz * elapsed)
            controller.set_controls(steer=steer, throttle=0.0, brake=0.0)

            if elapsed >= float(next_report):
                print(f"{next_report}s steer={steer:+.3f}")
                next_report += 1

            next_tick += period
            sleep_for = next_tick - time.monotonic()
            if sleep_for > 0:
                time.sleep(sleep_for)
            else:
                next_tick = time.monotonic()

        print("Gamepad test complete.")
        return 0
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
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

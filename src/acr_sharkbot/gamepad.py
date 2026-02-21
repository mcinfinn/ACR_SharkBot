from __future__ import annotations

import math
from typing import Any


def _import_vgamepad() -> Any:
    try:
        import vgamepad
    except ImportError as exc:
        raise RuntimeError("vgamepad is required. Install with: pip install vgamepad") from exc
    return vgamepad


def _clip(value: float, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    if not math.isfinite(number):
        number = 0.0
    return max(low, min(high, number))


class GamepadController:
    def __init__(self) -> None:
        vg = _import_vgamepad()
        self._pad = vg.VX360Gamepad()
        self.reset()

    def set_controls(self, steer: float, throttle: float, brake: float) -> None:
        steer_value = _clip(steer, -1.0, 1.0)
        throttle_value = _clip(throttle, 0.0, 1.0)
        brake_value = _clip(brake, 0.0, 1.0)
        throttle_int = int(round(throttle_value * 255.0))
        brake_int = int(round(brake_value * 255.0))

        self._pad.left_joystick_float(x_value_float=steer_value, y_value_float=0.0)
        self._pad.right_trigger(throttle_int)
        self._pad.left_trigger(brake_int)
        self._pad.update()

    def reset(self) -> None:
        self._pad.left_joystick_float(x_value_float=0.0, y_value_float=0.0)
        self._pad.right_trigger(0)
        self._pad.left_trigger(0)
        self._pad.update()

    def close(self) -> None:
        try:
            self.reset()
        except Exception:
            pass

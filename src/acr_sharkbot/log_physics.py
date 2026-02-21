from __future__ import annotations
import csv
import os
import time
from pathlib import Path

from acr_sharkbot.physics_struct import Physics, looks_uninitialized
from acr_sharkbot.shm import open_mmf_readonly

PHYSICS_MAP = r"Local\acpmf_physics"


def main() -> None:
    runs_dir = Path("runs")
    runs_dir.mkdir(exist_ok=True)

    out_path = runs_dir / f"physics_{time.strftime('%Y%m%d_%H%M%S')}.csv"

    size = __import__("ctypes").sizeof(Physics)

    print(f"Physics struct size: {size} bytes")
    print("Waiting for shared memory... (Start AC Rally and load into a session)")

    view = None
    while view is None:
        view = open_mmf_readonly(PHYSICS_MAP, size)
        if view is None:
            time.sleep(1.0)

    print(f"Connected to {PHYSICS_MAP}")
    t0 = time.perf_counter()

    with view, open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t_ms", "packet_id", "speed_kmh", "steer", "gas", "brake", "gear", "rpms", "heading", "pitch", "roll", "accg_x", "accg_y", "accg_z"])

        p_ptr = __import__("ctypes").cast(view.addr, __import__("ctypes").POINTER(Physics))

        while True:
            p = p_ptr.contents

            if not looks_uninitialized(p):
                t_ms = (time.perf_counter() - t0) * 1000.0
                w.writerow([
                    f"{t_ms:.3f}",
                    int(p.PacketId),
                    float(p.SpeedKmh),
                    float(p.SteerAngle),
                    float(p.Gas),
                    float(p.Brake),
                    int(p.Gear),
                    int(p.Rpms),
                    float(p.Heading),
                    float(p.Pitch),
                    float(p.Roll),
                    float(p.AccG[0]),
                    float(p.AccG[1]),
                    float(p.AccG[2]),
                ])

                if int(p.PacketId) % 50 == 0:
                    print(f"Speed {float(p.SpeedKmh):6.1f} | Steer {float(p.SteerAngle):6.3f} | Gas {float(p.Gas):4.2f} | Brake {float(p.Brake):4.2f}")

            time.sleep(0.01)


if __name__ == "__main__":
    main()
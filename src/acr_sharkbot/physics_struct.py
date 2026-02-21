from __future__ import annotations

import ctypes as C


class Coordinates(C.Structure):
    _pack_ = 4
    _fields_ = [
        ("x", C.c_float),
        ("y", C.c_float),
        ("z", C.c_float),
    ]


class Physics(C.Structure):
    _pack_ = 4
    _fields_ = [
        ("PacketId", C.c_int),
        ("Gas", C.c_float),
        ("Brake", C.c_float),
        ("Fuel", C.c_float),
        ("Gear", C.c_int),
        ("Rpms", C.c_int),
        ("SteerAngle", C.c_float),
        ("SpeedKmh", C.c_float),
        ("Velocity", C.c_float * 3),
        ("AccG", C.c_float * 3),
        ("WheelSlip", C.c_float * 4),
        ("WheelLoad", C.c_float * 4),
        ("WheelsPressure", C.c_float * 4),
        ("WheelAngularSpeed", C.c_float * 4),
        ("TyreWear", C.c_float * 4),
        ("TyreDirtyLevel", C.c_float * 4),
        ("TyreCoreTemperature", C.c_float * 4),
        ("CamberRad", C.c_float * 4),
        ("SuspensionTravel", C.c_float * 4),
        ("Drs", C.c_float),
        ("TC", C.c_float),
        ("Heading", C.c_float),
        ("Pitch", C.c_float),
        ("Roll", C.c_float),
        ("CgHeight", C.c_float),
        ("CarDamage", C.c_float * 5),
        ("NumberOfTyresOut", C.c_int),
        ("PitLimiterOn", C.c_int),
        ("Abs", C.c_float),
        ("KersCharge", C.c_float),
        ("KersInput", C.c_float),
        ("AutoShifterOn", C.c_int),
        ("RideHeight", C.c_float * 2),
        ("Turbo", C.c_float),
        ("Ballast", C.c_float),
        ("AirDensity", C.c_float),
        ("AirTemp", C.c_float),
        ("RoadTemp", C.c_float),
        ("LocalAngularVelocity", C.c_float * 3),
        ("FinalFF", C.c_float),
        ("PerformanceMeter", C.c_float),
        ("EngineBrake", C.c_int),
        ("ErsRecoveryLevel", C.c_int),
        ("ErsPowerLevel", C.c_int),
        ("ErsHeatCharging", C.c_int),
        ("ErsIsCharging", C.c_int),
        ("KersCurrentKJ", C.c_float),
        ("DrsAvailable", C.c_int),
        ("DrsEnabled", C.c_int),
        ("BrakeTemp", C.c_float * 4),
        ("Clutch", C.c_float),
        ("TyreTempI", C.c_float * 4),
        ("TyreTempM", C.c_float * 4),
        ("TyreTempO", C.c_float * 4),
        ("IsAIControlled", C.c_int),
        ("TyreContactPoint", Coordinates * 4),
        ("TyreContactNormal", Coordinates * 4),
        ("TyreContactHeading", Coordinates * 4),
        ("BrakeBias", C.c_float),
        ("LocalVelocity", C.c_float * 3),
        ("P2PActivation", C.c_int),
        ("P2PStatus", C.c_int),
        ("CurrentMaxRpm", C.c_float),
        ("mz", C.c_float * 4),
        ("fx", C.c_float * 4),
        ("fy", C.c_float * 4),
        ("slipRatio", C.c_float * 4),
        ("slipAngle", C.c_float * 4),
        ("tcinAction", C.c_int),
        ("absinAction", C.c_int),
        ("suspensionDamage", C.c_float * 4),
        ("tyreTemp", C.c_float * 4),
        ("waterTemperature", C.c_float),
        ("brakePressure", C.c_float * 4),
        ("frontBrakeCompound", C.c_int),
        ("rearBrakeCompound", C.c_int),
        ("padLife", C.c_float * 4),
        ("discLife", C.c_float * 4),
        ("ignitionOn", C.c_int),
        ("starterEngineOn", C.c_int),
        ("isEngineRunning", C.c_int),
        ("kerbVibration", C.c_float),
        ("slipVibrations", C.c_float),
        ("gVibrations", C.c_float),
        ("absVibrations", C.c_float),
    ]


def looks_uninitialized(physics: Physics) -> bool:
    pressures_zero = all(float(physics.WheelsPressure[i]) == 0.0 for i in range(4))
    return pressures_zero and float(physics.AirDensity) == 0.0


__all__ = ["Coordinates", "Physics", "looks_uninitialized"]

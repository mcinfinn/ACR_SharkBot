# Run Recorder

## Setup

1. Create and activate a virtual environment.

```powershell
python -m venv .venv
.venv\Scripts\activate
```

2. Install dependencies:

```powershell
pip install mss pillow
```

## Run

From repo root:

```powershell
python -m acr_sharkbot.record_run
```

Optional region controls:

```powershell
python -m acr_sharkbot.record_run --full-monitor
python -m acr_sharkbot.record_run --left 640 --top 360 --width 640 --height 360
```

Useful options:

```powershell
python -m acr_sharkbot.record_run --telemetry-hz 100 --fps 20 --quality 85
```

Hotkeys while running:

- `l`: toggle logging on/off
- `q`: quit gracefully

## Output

Each run creates:

`runs/run_YYYYMMDD_HHMMSS/`

- `telemetry.csv`
- `frames.csv`
- `frames/frame_000000.jpg`, `frames/frame_000001.jpg`, ...
- `meta.json`

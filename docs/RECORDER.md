# Run Recorder

## Setup

1. Create and activate a virtual environment.

```powershell
python -m venv .venv
.venv\Scripts\activate
```

2. Install in editable mode:

```powershell
pip install -e .
```

This project uses a `src/` layout; editable install keeps `acr_sharkbot` imports bound to `src/acr_sharkbot`.

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

`runs/session_YYYYMMDD_HHMMSS/`

- `session_meta.json`
- `segment_0001/`
- `segment_0001/telemetry.csv`
- `segment_0001/frames.csv`
- `segment_0001/frames/frame_000000.jpg`, `segment_0001/frames/frame_000001.jpg`, ...
- `segment_0001/meta.json`

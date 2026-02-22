# blink-lapse

Captures still frames from Blink cameras on a configurable interval for assembly into a timelapse video.

## Requirements

- Python 3.12+
- A Blink account with at least one camera

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Copy the example env file and fill in your details:

```bash
cp .env.example .env
```

| Variable | Description | Default |
|---|---|---|
| `BLINK_USERNAME` | Blink account email | *(prompted)* |
| `BLINK_PASSWORD` | Blink account password | *(prompted)* |
| `BLINK_CAMERAS` | Comma-separated camera name(s) to capture | all cameras |
| `BLINK_INTERVAL` | Capture interval in seconds | `600` (10 min) |
| `BLINK_FRAMES_DIR` | Directory to save frames | `./frames` |
| `BLINK_CREDENTIALS` | Path to cached auth token file | `.credentials.json` |

## Usage

```bash
# First run — prompts for credentials and 2FA, then caches the token
.venv/bin/python capture.py

# Single test shot
.venv/bin/python capture.py --once

# Override interval or camera via flags
.venv/bin/python capture.py --interval 300 --cameras "Front"

# Verbose logging
.venv/bin/python capture.py --verbose
```

Frames are saved to `frames/<camera-name>/YYYYMMDD_HHMMSS.jpg`. After the first successful login, credentials are cached in `.credentials.json` so subsequent runs skip the login prompt.

## Compiling the Timelapse

Once you have frames collected, use `ffmpeg` to compile them:

```bash
ffmpeg -framerate 24 -pattern_type glob -i 'frames/Front/*.jpg' \
  -c:v libx264 -pix_fmt yuv420p timelapse.mp4
```

Adjust `-framerate` to control playback speed (higher = faster).

## Notes

- The Blink XT2 is a battery-powered camera. Each snapshot request wakes the camera, which contributes to battery usage. A 10-minute interval is a reasonable balance between timelapse resolution and battery life.
- `.credentials.json` and `frames/` are gitignored — keep credentials off version control and manage frames separately.

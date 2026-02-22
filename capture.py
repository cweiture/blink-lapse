#!/usr/bin/env python3
"""blink-lapse: Capture still frames from Blink cameras for timelapse creation."""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from blinkpy.auth import Auth, BlinkTwoFARequiredError
from blinkpy.blinkpy import Blink

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# How long to wait after triggering a snapshot before downloading the result.
# XT2 cameras are battery-powered and need time to wake, capture, and upload.
SNAP_SETTLE_DELAY = 10  # seconds

DEFAULT_INTERVAL = 600  # 10 minutes


async def _do_2fa(blink: Blink) -> None:
    """Prompt for and submit a 2FA code."""
    code = input("Enter the 2FA pin sent to your registered device/email: ").strip()
    ok = await blink.send_2fa_code(code)
    if not ok:
        log.error("2FA verification failed.")
        sys.exit(1)


async def authenticate(credentials_file: Path) -> Blink:
    """
    Authenticate with Blink.

    Tries saved credentials first. Falls back to username/password prompt
    (respecting BLINK_USERNAME / BLINK_PASSWORD env vars). Saves credentials
    after a successful login so subsequent runs skip the interactive prompt.
    """
    blink = Blink(refresh_rate=30)

    # --- Try saved credentials ---
    if credentials_file.exists():
        log.info("Loading saved credentials from %s", credentials_file)
        creds = json.loads(credentials_file.read_text())
        blink.auth = Auth(creds, no_prompt=True)
        try:
            started = await blink.start()
            if started:
                await blink.save(str(credentials_file))  # refresh token on disk
                return blink
            log.warning("Saved credentials failed, falling back to login.")
        except BlinkTwoFARequiredError:
            await _do_2fa(blink)
            await blink.save(str(credentials_file))
            return blink

    # --- Fresh login ---
    username = os.environ.get("BLINK_USERNAME") or input("Blink username (email): ")
    password = os.environ.get("BLINK_PASSWORD") or input("Blink password: ")

    blink = Blink(refresh_rate=30)
    blink.auth = Auth({"username": username, "password": password})

    try:
        await blink.start()
    except BlinkTwoFARequiredError:
        await _do_2fa(blink)

    await blink.save(str(credentials_file))
    log.info("Credentials saved to %s", credentials_file)
    return blink


async def capture_frame(
    blink: Blink, camera, output_dir: Path, camera_name: str
) -> bool:
    """
    Trigger a snapshot on the camera, wait for it to upload, then save to disk.

    Filenames use the local timestamp at the moment of capture so they sort
    naturally into a timelapse sequence.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = output_dir / f"{timestamp}.jpg"

    log.info("Triggering snapshot on '%s'...", camera_name)
    await camera.snap_picture()

    # Give the camera (especially XT2 battery cameras) time to wake,
    # take the photo, and upload the new thumbnail to Blink's servers.
    log.debug("Waiting %ds for '%s' to upload...", SNAP_SETTLE_DELAY, camera_name)
    await asyncio.sleep(SNAP_SETTLE_DELAY)

    # Refresh blink state so the camera object has the updated thumbnail URL.
    await blink.refresh(force=True)

    # Download and persist the image.
    await camera.image_to_file(str(filename))

    if filename.exists() and filename.stat().st_size > 0:
        log.info("Saved %s (%d bytes)", filename, filename.stat().st_size)
        return True

    log.warning("Frame capture failed for '%s' — file missing or empty.", camera_name)
    return False


async def run_collector(
    interval: int,
    camera_filter: list[str] | None,
    frames_dir: Path,
    credentials_file: Path,
    once: bool = False,
) -> None:
    """Authenticate, then loop forever capturing frames at the given interval."""
    blink = await authenticate(credentials_file)

    if not blink.available:
        log.error("Blink system not available after authentication.")
        return

    cameras = dict(blink.cameras)
    if not cameras:
        log.error("No cameras found in your Blink account.")
        return

    log.info("Cameras found: %s", list(cameras.keys()))

    if camera_filter:
        cameras = {k: v for k, v in cameras.items() if k in camera_filter}
        if not cameras:
            log.error(
                "None of the specified cameras were found. Available: %s",
                list(blink.cameras.keys()),
            )
            return

    # Ensure output directories exist.
    for name in cameras:
        (frames_dir / name).mkdir(parents=True, exist_ok=True)

    log.info(
        "Starting capture: %d camera(s), interval=%ds%s",
        len(cameras),
        interval,
        " [single shot]" if once else "",
    )

    try:
        while True:
            await blink.refresh(force=True)

            for name, camera in cameras.items():
                try:
                    await capture_frame(blink, camera, frames_dir / name, name)
                except Exception:
                    log.exception("Unexpected error capturing from '%s'", name)

            if once:
                break

            log.info("Next capture in %ds. Press Ctrl+C to stop.", interval)
            await asyncio.sleep(interval)
    except KeyboardInterrupt:
        log.info("Stopped by user.")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Capture timelapse frames from Blink cameras.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.environ.get("BLINK_INTERVAL", DEFAULT_INTERVAL)),
        metavar="SECONDS",
        help="Capture interval in seconds",
    )
    _cameras_env = os.environ.get("BLINK_CAMERAS")
    parser.add_argument(
        "--cameras",
        nargs="+",
        default=_cameras_env.split(",") if _cameras_env else None,
        metavar="NAME",
        help="Camera name(s) to capture. Defaults to all cameras.",
    )
    parser.add_argument(
        "--frames-dir",
        type=Path,
        default=Path(os.environ.get("BLINK_FRAMES_DIR", "frames")),
        metavar="DIR",
        help="Directory to store captured frames",
    )
    parser.add_argument(
        "--credentials",
        type=Path,
        default=Path(os.environ.get("BLINK_CREDENTIALS", ".credentials.json")),
        metavar="FILE",
        help="Path to credentials cache file",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Capture a single frame then exit (useful for testing)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose/debug logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger("blinkpy").setLevel(logging.DEBUG)

    asyncio.run(
        run_collector(
            interval=args.interval,
            camera_filter=args.cameras,
            frames_dir=args.frames_dir,
            credentials_file=args.credentials,
            once=args.once,
        )
    )


if __name__ == "__main__":
    main()

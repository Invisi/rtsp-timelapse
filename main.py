import datetime
import logging
import os
import signal
import time
from pathlib import Path
from typing import Self

import apprise
import ffmpeg
import schedule


# rtsp settings
RTSP_USER = os.environ.get("RTSP_USER", "")
RTSP_PASS = os.environ.get("RTSP_PASS", "")
RTSP_HOST = os.environ.get("RTSP_HOST")
RTSP_PORT = os.environ.get("RTSP_PORT", 554)
RTSP_PATH = os.environ.get("RTSP_PATH", "stream1")

# interval settings
INTERVAL_SCREENSHOT_MINUTES = os.environ.get("INTERVAL_SCREENSHOT_MINUTES", 1)
INTERVAL_TIMELAPSE_HOURS = os.environ.get("INTERVAL_TIMELAPSE_HOURS", 24)

# misc settings
DATA_PATH = Path(os.environ.get("DATA_PATH", "./data"))
LOGGING_LEVEL = os.environ.get("LOGGING_LEVEL", "INFO")
TIMELAPSE_CRF = os.environ.get("TIMELAPSE_CRF", 28)
APPRISE_SERVERS = os.environ.get("APPRISE_SERVERS", "")
IMAGE_EXTENSION = os.environ.get("IMAGE_EXTENSION", "jpg")

# image & video paths
TIMELAPSE_PATH = DATA_PATH / "timelapses"
SCREENSHOT_PATH = DATA_PATH / "screenshots"
TIMELAPSE_PATH.mkdir(parents=True, exist_ok=True)
SCREENSHOT_PATH.mkdir(parents=True, exist_ok=True)


class SignalHandler:
    """Contact manager for handling SIGTERM"""

    def __enter__(self) -> Self:
        self.stop = False

        def handler(_signum, _frame):
            self.stop = True

        signal.signal(signal.SIGTERM, handler)
        return self

    def __exit__(self, _exc_type, _exc_val, _exc_tb) -> None:
        pass


def generate_filename(
    is_timelapse: bool = False, timelapse_framerate: int = 24
) -> Path:
    """Generate timestamped filename for screenshot or timelapse"""
    dt = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    if is_timelapse:
        path = TIMELAPSE_PATH / f"{dt}_fps_{timelapse_framerate}.mp4"
    else:
        path = SCREENSHOT_PATH / f"{dt}.{IMAGE_EXTENSION}"

    return path


def take_screenshot() -> None:
    """Take screenshot of RTSP stream and save it"""
    rtsp_path = RTSP_PATH.lstrip("/")
    if RTSP_USER and RTSP_PASS:
        rtsp_url = f"rtsp://{RTSP_USER}:{RTSP_PASS}@{RTSP_HOST}:{RTSP_PORT}/{rtsp_path}"
    elif RTSP_USER:
        rtsp_url = f"rtsp://{RTSP_USER}@{RTSP_HOST:{RTSP_PORT}}/{rtsp_path}"
    else:
        rtsp_url = f"rtsp://{RTSP_HOST}:{RTSP_PORT}/{rtsp_path}"

    try:
        ffmpeg.input(rtsp_url, loglevel="error", rtsp_transport="tcp").output(
            str(generate_filename()), vframes=1, timeout=5
        ).run()
        log.info("took screenshot")
    except ffmpeg.Error:
        log.exception("failed to take screenshot")


def generate_timelapse() -> tuple[Path, Path] | None:
    """Generate 24 fps & 60 fps timelapse from images"""
    log.info("generating timelapses")

    fps_24 = generate_filename(is_timelapse=True, timelapse_framerate=24)
    fps_60 = generate_filename(is_timelapse=True, timelapse_framerate=60)

    try:
        ffmpeg.input(
            SCREENSHOT_PATH / f"*.{IMAGE_EXTENSION}",
            loglevel="error",
            framerate=24,
            pattern_type="glob",
        ).output(
            str(fps_24),
            crf=TIMELAPSE_CRF,
        ).run()
    except ffmpeg.Error:
        log.exception("failed to generate 24fps timelapse")
        return None

    try:
        ffmpeg.input(
            SCREENSHOT_PATH / f"*.{IMAGE_EXTENSION}",
            loglevel="error",
            framerate=60,
            pattern_type="glob",
        ).output(
            str(fps_60),
            crf=TIMELAPSE_CRF,
        ).run()
    except ffmpeg.Error:
        log.exception("failed to generate 60fps timelapse")
        return None

    return fps_24, fps_60


def send_timelapse() -> None:
    """Generate and send timelapse via apprise"""
    result = generate_timelapse()
    if result is None:
        return

    fps_24, fps_60 = result

    if APPRISE_SERVERS:
        log.info("sending notification")
        app = apprise.Apprise(servers=APPRISE_SERVERS)
        log.info("sending apprise notification")
        app.notify(
            title="RTSP Timelapse (24 FPS)",
            body=f"Timelapse generated every {INTERVAL_TIMELAPSE_HOURS} hours",
            attach=apprise.AppriseAttachment(str(fps_24)),
        )
        app.notify(
            title="RTSP Timelapse (60 FPS)",
            body=f"Timelapse generated every {INTERVAL_TIMELAPSE_HOURS} hours",
            attach=apprise.AppriseAttachment(str(fps_60)),
        )

    for image in SCREENSHOT_PATH.iterdir():
        if not image.is_file():
            continue

        image.unlink(missing_ok=True)

    log.info("cleaned up images")


def run_schedule() -> None:
    schedule.every(int(INTERVAL_SCREENSHOT_MINUTES)).minutes.do(take_screenshot)
    schedule.every(int(INTERVAL_TIMELAPSE_HOURS)).hours.do(send_timelapse)

    # take initial screenshot to check if everything works as expected
    take_screenshot()

    with SignalHandler() as s:
        while True:
            # check for SIGTERM
            if s.stop:
                log.info("exiting")
                return

            schedule.run_pending()
            time.sleep(1)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.getLevelName(LOGGING_LEVEL),
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler()],
    )

    if os.name == "nt":
        raise RuntimeError("Windows is not supported due to glob.h not existing.")

    log = logging.getLogger("rtsp")

    run_schedule()

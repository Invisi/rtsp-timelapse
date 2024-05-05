import datetime
import logging
import os
import signal
import time
from pathlib import Path
from types import FrameType, TracebackType
from typing import Annotated, Self

import apprise
import ffmpeg
import schedule
from pydantic import Field, UrlConstraints, model_validator
from pydantic_settings import BaseSettings
from pydantic_core import Url

RtspUrl = Annotated[Url, UrlConstraints(allowed_schemes=["rtsp"])]


class Settings(BaseSettings):
    rtsp_url: RtspUrl

    # job settings
    screenshot_interval: int = Field(5, alias="INTERVAL_SCREENSHOT_MINUTES")
    timelapse_generation_time: datetime.time = datetime.time(0, 0)
    timelapse_crf: int = 28

    # time range to skip generation of a screenshot
    skip_time_start: datetime.time | None = None
    skip_time_end: datetime.time | None = None

    data_path: Path = Path("./data")
    logging_level: str = "INFO"

    apprise_servers: str | None = None

    @model_validator(mode="after")
    def check_skip_time_range(self) -> Self:
        if (
            self.skip_time_start is None
            and self.skip_time_end is not None
            or self.skip_time_end is None
            and self.skip_time_start is not None
        ):
            raise ValueError(
                "Both start and end have to be defined to properly skip time"
            )

        if (
            self.skip_time_start is not None
            and self.skip_time_end is not None
            and self.skip_time_start > self.skip_time_end
        ):
            raise ValueError("Start cannot be after end")

        return self


settings = Settings()

# image & video paths
TIMELAPSE_PATH = settings.data_path / "timelapses"
SCREENSHOT_PATH = settings.data_path / "screenshots"
TIMELAPSE_PATH.mkdir(parents=True, exist_ok=True)
SCREENSHOT_PATH.mkdir(parents=True, exist_ok=True)


class SignalHandler:
    """Contact manager for handling SIGTERM"""

    def __enter__(self) -> Self:
        self.stop = False

        def handler(_signum: int, _frame: FrameType | None) -> None:
            self.stop = True

        signal.signal(signal.SIGTERM, handler)
        return self

    def __exit__(
        self,
        _exc_type: type,
        _exc_val: Exception,
        _exc_tb: TracebackType,
    ) -> None:
        pass


def image_filename() -> str:
    dt = datetime.datetime.now()
    if settings.timelapse_generation_time != datetime.time(0, 0):
        dt = dt - datetime.timedelta(
            hours=settings.timelapse_generation_time.hour,
            minutes=settings.timelapse_generation_time.minute,
        )

    return str(SCREENSHOT_PATH / f"{dt.strftime('%Y-%m-%d_%H-%M-%S')}.jpg")


def timelapse_filename(framerate: int = 24, week: bool = False) -> str:
    dt = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    if week:
        return str(TIMELAPSE_PATH / f"{dt}_fps_{framerate}_week.mp4")
    return str(TIMELAPSE_PATH / f"{dt}_fps_{framerate}.mp4")


def take_screenshot() -> None:
    """Take screenshot of RTSP stream and save it"""

    now = datetime.datetime.now().time()
    if (
        settings.skip_time_start is not None
        and settings.skip_time_end is not None
        and settings.skip_time_start <= now <= settings.skip_time_end
    ):
        log.info("skipping screenshot")
        return

    try:
        ffmpeg.input(
            str(settings.rtsp_url), loglevel="error", rtsp_transport="tcp"
        ).output(
            image_filename(),
            vframes=1,
            timeout=5,
            qmin=1,
            qscale=1,
        ).run()
        log.info("took screenshot")
    except ffmpeg.Error:
        log.exception("failed to take screenshot")


def generate_timelapse(week: bool) -> tuple[str, str] | None:
    """Generate 24 fps & 60 fps timelapse from images"""
    log.info("generating timelapses")

    fps_24 = timelapse_filename(framerate=24, week=week)
    fps_60 = timelapse_filename(framerate=60, week=week)

    if week:
        filename_glob = SCREENSHOT_PATH / "*.jpg"
    else:
        dt = datetime.datetime.today() - datetime.timedelta(days=1)
        filename_glob = SCREENSHOT_PATH / f"{dt.strftime('%Y-%m-%d')}*.jpg"

    try:
        ffmpeg.input(
            filename_glob,
            framerate=24,
            pattern_type="glob",
        ).output(
            fps_24,
            crf=settings.timelapse_crf,
        ).run()
    except ffmpeg.Error:
        log.exception("failed to generate 24fps timelapse")
        return None

    try:
        ffmpeg.input(
            filename_glob,
            framerate=60,
            pattern_type="glob",
        ).output(
            fps_60,
            crf=settings.timelapse_crf,
        ).run()
    except ffmpeg.Error:
        log.exception("failed to generate 60fps timelapse")
        return None

    return fps_24, fps_60


def send_timelapse(week: bool = False) -> None:
    """Generate and send timelapse via apprise"""
    result = generate_timelapse(week)
    if result is None:
        return

    fps_24, fps_60 = result

    if week:
        title = "Weekly RTSP Timelapse"
    else:
        title = "Daily RTSP Timelapse"

    if settings.apprise_servers:
        log.info("sending notification")
        app = apprise.Apprise(servers=settings.apprise_servers)
        app.notify(
            title=f"{title} (24 FPS)",
            body="",
            attach=apprise.AppriseAttachment(fps_24),
        )
        app.notify(
            title=f"{title} (60 FPS)",
            body="",
            attach=apprise.AppriseAttachment(fps_60),
        )

    if week:
        for image in SCREENSHOT_PATH.iterdir():
            if not image.is_file():
                continue

            image.unlink(missing_ok=True)

        log.info("cleaned up images")


def run_schedule() -> None:
    schedule.every(settings.screenshot_interval).minutes.do(take_screenshot)
    schedule.every().day.at(str(settings.timelapse_generation_time)).do(send_timelapse)
    schedule.every().monday.at(str(settings.timelapse_generation_time)).do(
        send_timelapse, week=True
    )

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
        level=logging.getLevelName(settings.logging_level),
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler()],
    )

    if os.name == "nt":
        raise RuntimeError("Windows is not supported due to glob.h not existing.")

    log = logging.getLogger("rtsp")

    run_schedule()

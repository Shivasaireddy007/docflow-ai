import logging
import signal
import time
from types import FrameType
from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db import close_old_connections

from documents import jobs

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Process queued documents until stopped (or once, with --once)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--once", action="store_true", help="Process at most one job, then exit")
        parser.add_argument("--idle-seconds", type=float, default=1.0)

    def handle(self, *args: Any, **options: Any) -> None:
        if options["once"]:
            jobs.run_once()
            return

        stopping = False

        def stop(signum: int, frame: FrameType | None) -> None:
            nonlocal stopping
            stopping = True  # finish the current document, then exit

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        log.info("Worker started")
        while not stopping:
            close_old_connections()
            if not jobs.run_once():
                time.sleep(options["idle_seconds"])
        log.info("Worker stopped")

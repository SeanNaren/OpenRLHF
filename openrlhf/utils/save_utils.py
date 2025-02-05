import re
import time

from openrlhf.utils.logging_utils import init_logger

logger = init_logger(__name__)


class TimeCallback:
    def __init__(self, max_time: str):
        """
        Signals after time interval has been reached.
        Args:
            max_time (str): The time interval to signal when reached in HH:MM:SS format.

        Raises:
            ValueError: If the time interval format is invalid.
        """
        self.save_interval = self._parse_time_interval(max_time)
        self.max_time_reached = False
        self.last_save_time = time.time()
        logger.info(f"Set to save after {max_time} has been reached.")

    def _parse_time_interval(self, interval_str) -> float:
        match = re.fullmatch(r"(\d+):([0-5]?\d):([0-5]?\d)", interval_str)
        if not match:
            raise ValueError(
                f"Invalid time interval format: '{interval_str}'. Use HH:MM:SS format."
            )
        hours, minutes, seconds = map(int, match.groups())
        return hours * 3600 + minutes * 60 + seconds

    def time_reached(self) -> bool:
        current_time = time.time()
        if current_time - self.last_save_time >= self.save_interval and (not self.max_time_reached):
            self.last_save_time = current_time
            logger.info("Time interval has been reached, signalling to save checkpoint.")
            return True
        return False

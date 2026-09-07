"""
This script contains utility static methods and data structures.
"""

from collections import OrderedDict
from typing import Any


class BoundedLRUDict(OrderedDict):
    """
    A dictionary with a maximum size that evicts the least recently accessed
    item when its capacity is reached.
    """
    def __init__(self, maxsize: int = 1000, *args: Any, **kwargs: Any) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be at least 1")
        self.maxsize = maxsize
        super().__init__(*args, **kwargs)

    def __setitem__(self, key: Any, value: Any) -> None:
        super().__setitem__(key, value)
        self.move_to_end(key)
        if len(self) > self.maxsize:
            self.popitem(last=False)


def convert_to_seconds(time_str: str | int | None) -> int:
    """
    Converts a time string (e.g., "1m", "5s", "1h", "2d") or an integer / integer
    string (e.g., 60, "60") to seconds.

    Args:
        time_str (str | int | None): The time value or string to convert.

    Returns:
        int: The time in seconds.
    """
    if time_str is None:
        return 0

    if isinstance(time_str, int):
        return time_str

    if not isinstance(time_str, str) or not time_str:
        return 0

    # Convert to lowercase
    time_str = time_str.strip().lower()

    # If time_str is an integer string, return that value
    if time_str.isdigit():
        return int(time_str)

    if time_str.endswith("s"):
        return int(time_str[:-1])
    if time_str.endswith("m"):
        return int(time_str[:-1]) * 60
    if time_str.endswith("h"):
        return int(time_str[:-1]) * 3600
    if time_str.endswith("d"):
        return int(time_str[:-1]) * 86400

    return 0


def find_by_id(items: list[dict], item_id: int) -> dict | None:
    """Return the first item whose ``id`` matches ``item_id``, or None.

    Used by the CLI selection prompts so users can pick database entities by
    their stable id instead of a transient 1..n list index.
    """
    for item in items:
        if item.get("id") == item_id:
            return item
    return None

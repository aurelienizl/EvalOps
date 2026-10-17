"""Bounded polling for asynchronous deployment actions."""

import time


def eventually(check, *, timeout=120, description="operation"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(0.2)
    raise AssertionError(f"Timed out waiting for {description}")

import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass


@dataclass
class TestResult:
    passed: bool
    returncode: int
    timed_out: bool
    tests_run: int
    output: str


class TestRunner:
    """Fixed unittest runner for trusted Python repositories, with bounded output."""
    def __init__(self, timeout: float = 15):
        if timeout <= 0:
            raise ValueError("Test timeout must be positive")
        self.timeout = timeout

    def run(self, root: Path) -> TestResult:
        # API keys and other inherited credentials are not passed to child tests.
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
               "HOME": str(root), "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}
        proc = subprocess.Popen(
            [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        tail = bytearray()

        def drain():
            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                tail.extend(chunk)
                if len(tail) > 32_768:
                    del tail[:-32_768]

        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        timed_out = False
        try:
            proc.wait(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            # Also terminate descendants retaining stdout after the parent exits.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
            reader.join(timeout=2)
            if not reader.is_alive():
                proc.stdout.close()
        output = bytes(tail).decode("utf-8", errors="replace")
        counts = re.findall(r"^Ran (\d+) tests? in ", output, flags=re.MULTILINE)
        count = int(counts[-1]) if counts else 0
        skipped = re.findall(r"skipped=(\d+)", output)
        skipped_count = int(skipped[-1]) if skipped else 0
        passed = proc.returncode == 0 and not timed_out and count > skipped_count
        return TestResult(passed, proc.returncode, timed_out, count, output)

"""Trusted adapter for the existing exercise evaluators, executed only in Docker.

Student subprocesses have UID/GID 1000 and bounded file-backed output. The result
writer remains root in a read-only image with a root-only result tmpfs.
"""

import os
import resource
import runpy
import signal
import sys
import time
import traceback
import subprocess
import tarfile
import tempfile
from pathlib import Path

_original_popen = subprocess.Popen
_original_tempdir = tempfile.TemporaryDirectory
_original_named = tempfile.NamedTemporaryFile
_original_extract = tarfile.TarFile.extractall


class StudentTempDirectory(_original_tempdir):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        os.chown(self.name, 1000, 1000)


def student_named_file(*args, **kwargs):
    value = _original_named(*args, **kwargs)
    os.chown(value.name, 1000, 1000)
    return value


def demote():
    resource.setrlimit(resource.RLIMIT_FSIZE, (65536, 65536))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.setgroups([])
    os.setgid(1000)
    os.setuid(1000)


class StudentProcess(_original_popen):
    def __init__(self, *args, **kwargs):
        self._captures = {}
        for channel in ("stdout", "stderr"):
            if kwargs.get(channel) == subprocess.PIPE:
                value = tempfile.TemporaryFile()
                self._captures[channel] = value
                kwargs[channel] = value
        kwargs.update(preexec_fn=demote, start_new_session=True)
        super().__init__(*args, **kwargs)

    def communicate(self, input=None, timeout=None):
        try:
            super().communicate(input=input, timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(self.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            super().communicate()
            raise
        finally:
            # Terminate descendants even when their parent has already exited.
            try:
                os.killpg(self.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        output = []
        for channel in ("stdout", "stderr"):
            value = self._captures.get(channel)
            if value is None:
                output.append(None)
            else:
                value.seek(0)
                data = value.read(65536)
                output.append(
                    data.decode(self.encoding or "utf-8", self.errors or "replace")
                    if self.text_mode
                    else data
                )
        return tuple(output)

    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            for value in self._captures.values():
                value.close()


def safe_extract(self, path=".", members=None, **kwargs):
    selected = list(self if members is None else members)
    if len(selected) > 10000 or sum(m.size for m in selected) > 100 * 1024 * 1024:
        raise ValueError("Archive exceeds limits")
    base = Path(path).resolve()
    for member in selected:
        target = base / member.name
        if not target.resolve().is_relative_to(base) or not (member.isfile() or member.isdir()):
            raise ValueError("Unsafe archive member")
        member.uid = 1000
        member.gid = 1000
        member.uname = ""
        member.gname = ""
        member.mode &= 0o777
    kwargs.pop("filter", None)
    return _original_extract(self, path, selected, filter="fully_trusted", **kwargs)


os.umask(0o022)
os.chmod("/result", 0o700)
subprocess.Popen = StudentProcess
tempfile.TemporaryDirectory = StudentTempDirectory
tempfile.NamedTemporaryFile = student_named_file
tarfile.TarFile.extractall = safe_extract
# Keep tmpfs mounted until the manager has collected the protected report.
status = 0
try:
    runpy.run_path("/app/evaluate.py", run_name="__main__")
except SystemExit as exc:
    status = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
except BaseException:
    traceback.print_exc()
    status = 1
Path("/result/exit_code").write_text(str(status))
signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(0))
while True:
    time.sleep(60)

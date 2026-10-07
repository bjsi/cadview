"""Shared fixtures: the module under test (loaded by path), a serialised kicad-cli runner, and an output directory
the tests leave their boards / Gerbers / reports in.

The module is found, in order: $CADPCB_PATH, `../cadpcb.py` (next to this tests/ dir), `../cadview/pcb.py` (the
cadview repo layout), then the installed `cadview` package's `pcb.py`.  It is loaded from its file so the same tests
run unchanged wherever the module lives.

kicad-cli: $KICAD_CLI (default: `kicad-cli` on PATH).  If the binary fails to start because of a missing
libprotobuf (a partially upgraded Arch box), $KICAD_CLI_LD_LIBRARY_PATH or any `~/.claude/jobs/*/tmp/pb36/usr/lib`
is tried as LD_LIBRARY_PATH.  Every invocation runs under `nice -n 10`, one at a time.
"""
from __future__ import annotations

import glob
import importlib.util
import os
import pathlib
import shutil
import subprocess
import sys
import threading

import pytest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))          # kicad_parse / helpers import as plain modules
REPORT: list[str] = []                 # lines the tests add; printed in the terminal summary


# ------------------------------------------------------------------------------------ module under test ----
def _module_candidates():
    env = os.environ.get("CADPCB_PATH")
    if env:
        yield pathlib.Path(env)
    yield HERE.parent / "cadpcb.py"
    yield HERE.parent / "cadview" / "pcb.py"
    yield HERE.parent.parent / "cadview" / "pcb.py"      # the cadview repo layout: tests/pcb/ under the repo root
    try:
        spec = importlib.util.find_spec("cadview")
    except (ImportError, ValueError):
        spec = None
    if spec and spec.submodule_search_locations:
        for loc in spec.submodule_search_locations:
            yield pathlib.Path(loc) / "pcb.py"


def load_cadpcb():
    for p in _module_candidates():
        if p.is_file():
            spec = importlib.util.spec_from_file_location("cadpcb_under_test", p)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod               # dataclasses need the module registered before exec
            spec.loader.exec_module(mod)
            mod.__test_path__ = str(p)
            return mod
    raise RuntimeError("cadpcb.py / cadview/pcb.py not found: set CADPCB_PATH")


@pytest.fixture(scope="session")
def cadpcb():
    mod = load_cadpcb()
    if not os.path.isdir(mod.KICAD_FP):
        pytest.skip(f"KiCad footprint libraries not found at {mod.KICAD_FP} (set KICAD_FOOTPRINTS)")
    REPORT.append(f"module under test: {mod.__test_path__}")
    REPORT.append(f"KiCad footprints: {mod.KICAD_FP}")
    return mod


# -------------------------------------------------------------------------------------------- kicad-cli ----
class KicadCli:
    def __init__(self, exe: str, env: dict):
        self.exe, self.env, self.lock = exe, env, threading.Lock()
        self.calls = 0

    def run(self, *args, timeout=900) -> subprocess.CompletedProcess:
        cmd = [self.exe, *map(str, args)]
        if shutil.which("nice"):
            cmd = ["nice", "-n", "10", *cmd]
        with self.lock:
            self.calls += 1
            return subprocess.run(cmd, env=self.env, capture_output=True, text=True, timeout=timeout)

    def ok(self, *args, timeout=900) -> subprocess.CompletedProcess:
        r = self.run(*args, timeout=timeout)
        assert r.returncode == 0, f"kicad-cli {' '.join(map(str, args))} failed ({r.returncode}):\n{r.stdout}\n{r.stderr}"
        return r


def _shim_dirs():
    env = os.environ.get("KICAD_CLI_LD_LIBRARY_PATH")
    if env:
        yield env
    for d in sorted(glob.glob(os.path.expanduser("~/.claude/jobs/*/tmp/pb36/usr/lib")), reverse=True):
        yield d
    yield "/tmp/pb36/usr/lib"


def find_kicad_cli() -> KicadCli | None:
    exe = os.environ.get("KICAD_CLI") or shutil.which("kicad-cli")
    if not exe:
        return None
    base = dict(os.environ)
    tries = [base] + [dict(base, LD_LIBRARY_PATH=d + (":" + base["LD_LIBRARY_PATH"] if base.get("LD_LIBRARY_PATH") else ""))
                      for d in _shim_dirs() if os.path.isdir(d)]
    for env in tries:
        try:
            r = subprocess.run([exe, "--version"], env=env, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if r.returncode == 0 and r.stdout.strip():
            k = KicadCli(exe, env)
            k.version = r.stdout.strip().splitlines()[-1]
            return k
    return None


@pytest.fixture(scope="session")
def kicad(cadpcb):
    k = find_kicad_cli()
    if k is None:
        pytest.skip("kicad-cli not runnable (set KICAD_CLI / KICAD_CLI_LD_LIBRARY_PATH)")
    REPORT.append(f"kicad-cli {k.version} at {k.exe}" + (f" (LD_LIBRARY_PATH={k.env['LD_LIBRARY_PATH']})" if k.env.get("LD_LIBRARY_PATH") else ""))
    return k


# ------------------------------------------------------------------------------------------- output dir ----
@pytest.fixture(scope="session")
def outdir(tmp_path_factory) -> pathlib.Path:
    """where the suite writes boards, Gerbers, STEPs and diff reports (kept: $PCB_TEST_OUT or pytest's tmp dir)"""
    env = os.environ.get("PCB_TEST_OUT")
    d = pathlib.Path(env) if env else tmp_path_factory.mktemp("pcb-dsl")
    d.mkdir(parents=True, exist_ok=True)
    REPORT.append(f"outputs: {d}")
    return d


def pytest_terminal_summary(terminalreporter):
    if REPORT:
        terminalreporter.section("pcb-dsl conformance")
        for line in REPORT:
            terminalreporter.write_line(line)

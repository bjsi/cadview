#!/usr/bin/env python3
"""freeroute.py — autoroute a .kicad_pcb with Freerouting, the way KiCad's plugin does it.

    python3 tools/pcb/freeroute.py board.kicad_pcb [-o routed.kicad_pcb] [--passes 20] [--threads N]
                                   [--ignore-nets GND,VCC] [--improvement 2.5] [--neckdown] [--drc]

Steps: KiCad's own Python (`pcbnew`) exports a Specctra DSN -> `java -jar freerouting.jar -de … -do …` routes it ->
`pcbnew` imports the SES back onto the board and saves it (next to the input as <name>.routed.kicad_pcb unless -o).
Everything KiCad knows about the board — pads, keepouts, net classes, clearances, existing tracks — goes to the router
through the DSN, and the result is a normal .kicad_pcb that `kicad-cli pcb drc` can check (`--drc` does, and prints
the counts). Freerouting's automatic neck-down is off (it narrows trace ends to 0.15 mm, under KiCad's usual 0.2 mm
minimum, and DRC flags every one); `--neckdown` turns it back on.

Needs: KiCad with its Python bindings (run this with KiCad's Python: KICAD_PYTHON, default `python3`), Java 21+
(FREEROUTING_JAVA, default `java`), and the Freerouting jar: FREEROUTING_JAR, else ~/.cache/openworkshop/freerouting-<v>.jar,
which this script downloads from GitHub on first use. The other autorouter here is tools/pcb/export.mjs (tscircuit,
from Circuit JSON, no KiCad needed); this one is the stronger push-and-shove router for dense boards.
"""
from __future__ import annotations

import argparse
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

FREEROUTING_VERSION = "2.5.0"
JAR_URL = f"https://github.com/freerouting/freerouting/releases/download/v{FREEROUTING_VERSION}/freerouting-{FREEROUTING_VERSION}.jar"


def jar_path() -> Path:
    p = os.environ.get("FREEROUTING_JAR")
    if p:
        return Path(p)
    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "openworkshop"
    cache.mkdir(parents=True, exist_ok=True)
    jar = cache / f"freerouting-{FREEROUTING_VERSION}.jar"
    if not jar.exists():
        print(f"downloading Freerouting {FREEROUTING_VERSION} -> {jar}", file=sys.stderr)
        with urllib.request.urlopen(JAR_URL, timeout=600) as r, open(jar, "wb") as f:
            shutil.copyfileobj(r, f)
    return jar


def java_bin() -> str:
    """FREEROUTING_JAVA, else the first Java >= 21 among `java` on PATH and the JVMs under /usr/lib/jvm
    (Freerouting 2.x is built for a recent JDK; a distro's default `java` is often older)."""
    if os.environ.get("FREEROUTING_JAVA"):
        return os.environ["FREEROUTING_JAVA"]
    candidates = ([shutil.which("java")] if shutil.which("java") else []) + sorted(
        glob.glob("/usr/lib/jvm/*/bin/java") + glob.glob("/Library/Java/JavaVirtualMachines/*/Contents/Home/bin/java"),
        reverse=True)
    for java in candidates:
        try:
            out = subprocess.run([java, "-version"], capture_output=True, text=True, timeout=20).stderr
            ver = out.split('version "')[1].split('"')[0].split(".")       # "26.0.2" / "17.0.20" / "1.8.0_392"
            major = int(ver[1]) if ver[0] == "1" else int(ver[0])
        except (OSError, IndexError, ValueError, subprocess.TimeoutExpired):
            continue
        if major >= 21:
            return java
    sys.exit("Freerouting needs Java 21 or newer: install a JDK or set FREEROUTING_JAVA")


def kicad_env():
    """KiCad's Python/CLI sometimes need a libprotobuf the system lacks (a half-upgraded box):
    KICAD_CLI_LD_LIBRARY_PATH, or a pb36 shim left by a job, goes on LD_LIBRARY_PATH."""
    env = dict(os.environ)
    extra = env.get("KICAD_CLI_LD_LIBRARY_PATH")
    if not extra:
        shims = sorted(glob.glob(os.path.expanduser("~/.claude/jobs/*/tmp/pb36/usr/lib")))
        extra = shims[-1] if shims else ""
    if extra:
        env["LD_LIBRARY_PATH"] = extra + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
    return env


PCBNEW_STEP = r'''
import sys, pcbnew
cmd, board_path, other = sys.argv[1:4]
b = pcbnew.LoadBoard(board_path)
if cmd == "dsn":
    ok = pcbnew.ExportSpecctraDSN(b, other)
elif cmd == "ses":
    ok = pcbnew.ImportSpecctraSES(b, other)
    if ok:
        pcbnew.SaveBoard(sys.argv[4], b)
sys.exit(0 if ok else 2)
'''


def pcbnew_call(cmd, *args):
    py = os.environ.get("KICAD_PYTHON", "python3")
    r = subprocess.run([py, "-c", PCBNEW_STEP, cmd, *map(str, args)], env=kicad_env(), capture_output=True, text=True)
    noise = [l for l in r.stderr.splitlines() if "assert" not in l and l.strip()]
    if r.returncode != 0:
        sys.exit(f"pcbnew {cmd} failed ({r.returncode}):\n" + "\n".join(noise[-8:]))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("board", help="the .kicad_pcb to route")
    ap.add_argument("-o", "--output", help="routed board (default: <name>.routed.kicad_pcb next to the input)")
    ap.add_argument("--passes", type=int, default=20, help="autorouter pass limit (default 20)")
    ap.add_argument("--threads", type=int, default=None, help="optimizer threads (default: Freerouting's, cores-1)")
    ap.add_argument("--improvement", type=float, default=2.5, help="optimizer stop threshold %% (default 2.5)")
    ap.add_argument("--ignore-nets", default="", help="net classes to leave unrouted, comma-separated")
    ap.add_argument("--neckdown", action="store_true", help="let Freerouting neck traces down at narrow pads")
    ap.add_argument("--drc", action="store_true", help="run `kicad-cli pcb drc` on the result and print the counts")
    ap.add_argument("--keep", action="store_true", help="keep the .dsn / .ses next to the output")
    a = ap.parse_args(argv)
    src = Path(a.board).resolve()
    out = Path(a.output).resolve() if a.output else src.with_name(src.stem + ".routed.kicad_pcb")
    work = Path(tempfile.mkdtemp(prefix="freeroute-"))
    dsn, ses = work / (src.stem + ".dsn"), work / (src.stem + ".ses")
    pcbnew_call("dsn", src, dsn)
    cmd = [java_bin(), "-jar", str(jar_path()), "-de", str(dsn), "-do", str(ses), "-mp", str(a.passes), "-l", "en",
           "--gui.enabled=false", f"--router.automatic_neckdown={'true' if a.neckdown else 'false'}",
           f"--router.optimizer.improvement_threshold={a.improvement}"]
    if a.threads is not None:
        cmd += ["-mt", str(a.threads)]
    if a.ignore_nets:
        cmd += ["-inc", a.ignore_nets]
    print("freerouting:", " ".join(cmd[3:]), file=sys.stderr)
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=work)      # cwd: it drops freerouting.json / logs there
    if not ses.exists():
        sys.exit("Freerouting wrote no session file:\n" + (r.stdout + r.stderr)[-2000:])
    for line in r.stdout.splitlines():
        if "Auto-routing stage completed" in line or "Job " in line and "finished" in line:
            print(line.split("INFO", 1)[-1].split("]", 1)[-1].strip(), file=sys.stderr)
    pcbnew_call("ses", src, ses, out)
    if a.keep:
        shutil.copy(dsn, out.with_suffix(".dsn"))
        shutil.copy(ses, out.with_suffix(".ses"))
    shutil.rmtree(work, ignore_errors=True)
    print(out)
    if a.drc:
        drc(out)


def drc(board: Path):
    """`kicad-cli pcb drc` on the routed board; prints unconnected / error / warning counts and the error types."""
    import collections
    import json
    report = board.with_suffix(".drc.json")
    r = subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--severity-all", "--refill-zones",
                        "-o", str(report), str(board)], env=kicad_env(), capture_output=True, text=True)
    if r.returncode != 0 or not report.exists():
        sys.exit("kicad-cli drc failed:\n" + (r.stdout + r.stderr)[-1500:])
    d = json.loads(report.read_text())
    errors = [v for v in d["violations"] if v["severity"] == "error"]
    print(f"drc: {len(d['unconnected_items'])} unconnected, {len(errors)} errors, "
          f"{len(d['violations']) - len(errors)} warnings  ({report.name})", file=sys.stderr)
    for t, n in collections.Counter(v["type"] for v in errors).most_common():
        print(f"  {n:4d}  {t}", file=sys.stderr)


if __name__ == "__main__":
    main()

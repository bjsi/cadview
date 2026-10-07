#!/usr/bin/env bash
# kicad_export.sh <board.kicad_pcb> <outdir>  - DRC + STEP/GLB/Gerber/drill/pos from a .kicad_pcb with kicad-cli (KiCad 10).
# KICAD_CLI overrides the binary.  On the hub (2026-10-07) /usr/bin/kicad-cli is linked against libprotobuf.so.36 while the
# system has 35: point LD_LIBRARY_PATH at an extracted protobuf-36.0-1 (README.md) - no system change.
set -u
PCB=$1; OUT=$2; K=${KICAD_CLI:-kicad-cli}
mkdir -p "$OUT/gerbers"
run() { echo "== $*"; "$@" 2>&1 | grep -v "^$" | tail -4; }
echo "== $K pcb drc"; "$K" pcb drc --refill-zones --save-board --format json --severity-all --exit-code-violations -o "$OUT/drc.json" "$PCB" 2>&1 | grep -v "^$" | tail -3
echo "   drc exit ${PIPESTATUS[0]} (nonzero = violations)"
python3 - "$OUT/drc.json" <<'EOF'
import json, sys, collections
d = json.load(open(sys.argv[1])); v = d.get("violations", []); u = d.get("unconnected_items", [])
print(f"   {len(v)} violations, {len(u)} unconnected:", dict(collections.Counter(x["type"] for x in v + u)))
for x in (v + u)[:8]: print("    -", x["type"], "|", x["description"][:110])
EOF
run "$K" pcb export step --subst-models --include-tracks --include-pads -f -o "$OUT/board.step" "$PCB"
run "$K" pcb export glb --subst-models --include-tracks --include-pads -f -o "$OUT/board.glb" "$PCB"
run "$K" pcb export gerbers -o "$OUT/gerbers/" "$PCB"
run "$K" pcb export drill --excellon-separate-th --generate-map --map-format gerberx2 -o "$OUT/gerbers/" "$PCB"
run "$K" pcb export pos --format csv --units mm --side both -o "$OUT/pos.csv" "$PCB"
(cd "$OUT/gerbers" && rm -f ../gerbers.zip && zip -q ../gerbers.zip *.g* *.drl && echo "== gerbers.zip: $(ls | wc -l) files (KiCad Protel extensions, what JLCPCB's upload expects)")
run "$K" pcb export svg --layers F.Cu,B.Cu,Edge.Cuts,F.SilkS -o "$OUT/board.svg" "$PCB"
ls -la "$OUT" "$OUT/gerbers" | sed 's/^/   /'

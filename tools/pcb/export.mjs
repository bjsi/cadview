// export.mjs - SPIKE (2026-10-07): route a Circuit JSON file and export fab outputs with tscircuit's npm packages.
//   node export.mjs <in.circuit.json> <outdir>
// Steps: validate (circuit-json zod) -> autoroute source_traces (@tscircuit/capacity-autorouter, local, MIT) -> write
// routed.circuit.json, gerbers/*.gbr + drill (circuit-json-to-gerber), pnp.csv, bom.csv, board.kicad_pcb, board.svg,
// board.glb (circuit-json-to-gltf), board.step (circuit-json-to-step).  Each export is independent: a failure is logged
// and the rest still run.  Packages resolve from NODE_PATH (see README.md).
import { readFileSync, writeFileSync, mkdirSync } from "node:fs"
import { join } from "node:path"

const [inPath, outDir] = process.argv.slice(2)
mkdirSync(outDir, { recursive: true })
let cj = JSON.parse(readFileSync(inPath, "utf8"))
const log = (...a) => console.log("[export]", ...a)
const step = async (name, fn) => { try { const t = Date.now(); await fn(); log(name, "ok", `${Date.now() - t} ms`) } catch (e) { log(name, "FAILED:", e?.message ?? e); if (process.env.EXPORT_TRACE) console.log(e?.stack) } }

// 1. validate against the spec
await step("validate", async () => {
  const { any_circuit_element } = await import("circuit-json")
  let bad = 0
  cj = cj.map((e, i) => { const r = any_circuit_element.safeParse(e); if (!r.success) { bad++; if (bad < 6) log("  invalid", i, e.type, JSON.stringify(r.error.issues[0])); return e } return r.data })
  if (bad) throw new Error(`${bad} elements failed schema validation`)
})

// 2. autoroute: Circuit JSON -> SimpleRouteJson -> traces -> pcb_trace elements
await step("autoroute", async () => {
  const { AutoroutingPipelineSolver } = await import("@tscircuit/capacity-autorouter")
  const board = cj.find(e => e.type === "pcb_board")
  const xs = board.outline.map(p => p.x), ys = board.outline.map(p => p.y)
  const bounds = { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) }
  const portNet = {}                                                                  // source_port_id -> source_trace_id
  const traces = cj.filter(e => e.type === "source_trace")
  for (const t of traces) for (const p of t.connected_source_port_ids) portNet[p] = t.source_trace_id
  const pcbPorts = Object.fromEntries(cj.filter(e => e.type === "pcb_port").map(p => [p.pcb_port_id, p]))
  const CLR = Number(process.env.PCB_CLEARANCE ?? 0.2)                                 // KiCad min_clearance; obstacles grow by 2 x CLR so the router keeps it
  const obstacles = [], points = {}, thtPads = []
  for (const e of cj) {
    const net = e.pcb_port_id && pcbPorts[e.pcb_port_id] ? portNet[pcbPorts[e.pcb_port_id].source_port_id] : undefined
    if (e.type === "pcb_smtpad") {
      const w = e.shape === "circle" ? e.radius * 2 : e.width, h = e.shape === "circle" ? e.radius * 2 : e.height
      obstacles.push({ type: "rect", layers: [e.layer], center: { x: e.x, y: e.y }, width: w + 2 * CLR, height: h + 2 * CLR, connectedTo: net ? [net] : [] })
      if (net) (points[net] ??= []).push({ x: e.x, y: e.y, layer: e.layer })
    } else if (e.type === "pcb_plated_hole") {
      const d = e.outer_diameter ?? Math.max(e.outer_width, e.outer_height)
      obstacles.push({ type: "rect", layers: ["top", "bottom"], center: { x: e.x, y: e.y }, width: d + 2 * CLR, height: d + 2 * CLR, connectedTo: net ? [net] : [] })
      thtPads.push({ x: e.x, y: e.y })
      if (net) (points[net] ??= []).push({ x: e.x, y: e.y, layers: ["top", "bottom"] })
    } else if (e.type === "pcb_hole") {
      obstacles.push({ type: "rect", layers: ["top", "bottom"], center: { x: e.x, y: e.y }, width: e.hole_diameter + 0.5, height: e.hole_diameter + 0.5, connectedTo: [] })
    } else if (e.type === "pcb_cutout" && e.shape === "polygon") {
      const px = e.points.map(p => p.x), py = e.points.map(p => p.y)
      obstacles.push({ type: "rect", layers: ["top", "bottom"], center: { x: (Math.min(...px) + Math.max(...px)) / 2, y: (Math.min(...py) + Math.max(...py)) / 2 },
        width: Math.max(...px) - Math.min(...px) + 0.5, height: Math.max(...py) - Math.min(...py) + 0.5, connectedTo: [] })
    } else if (e.type === "pcb_keepout") {
      obstacles.push({ type: "rect", layers: e.layers, center: e.center, width: e.width, height: e.height, connectedTo: [] })
    } else if (e.type === "pcb_via") {
      const d = e.outer_diameter + 2 * CLR
      obstacles.push({ type: "rect", layers: ["top", "bottom"], center: { x: e.x, y: e.y }, width: d, height: d, connectedTo: [] })
    } else if (e.type === "pcb_trace") {                                                 // hand-placed copper: each segment as a rect
      const w = e.route.map(r => r.route_type === "wire" ? r : null).filter(Boolean)
      for (let i = 0; i + 1 < w.length; i++) {
        const a = w[i], b = w[i + 1], W = (a.width ?? 0.3) + 2 * CLR
        obstacles.push({ type: "rect", layers: [a.layer], center: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }, width: Math.abs(b.x - a.x) + W, height: Math.abs(b.y - a.y) + W, connectedTo: [] })
      }
    }
  }
  const skip = new Set((process.env.PCB_SKIP_NETS ?? "").split(",").filter(Boolean))     // e.g. GND when a pour carries it
  const connections = traces.filter(t => points[t.source_trace_id]?.length > 1 && !skip.has(t.display_name)).map(t => ({ name: t.source_trace_id, pointsToConnect: points[t.source_trace_id] }))
  // the router keeps traces about one trace width apart: route at ROUTE_WIDTH, emit at TRACE_WIDTH, and the gap is the difference plus its own
  const TRACE_WIDTH = Number(process.env.PCB_TRACE_WIDTH ?? 0.3), ROUTE_WIDTH = Number(process.env.PCB_ROUTE_WIDTH ?? TRACE_WIDTH)
  const srj = { layerCount: 2, minTraceWidth: ROUTE_WIDTH, obstacles, connections, bounds }
  writeFileSync(join(outDir, "simple_route.json"), JSON.stringify(srj))
  const solver = new AutoroutingPipelineSolver(srj)
  const t0 = Date.now()
  while (!solver.solved && !solver.failed) { solver.step(); if (Date.now() - t0 > 120000) throw new Error("autorouter timeout 120 s") }
  if (solver.failed) throw new Error("autorouter failed: " + solver.error)
  const out = solver.getOutputSimpleRouteJson()
  let n = 0
  for (const t of out.traces ?? []) {
    let last = { x: 0, y: 0 }                                                   // a via point may omit x/y: it sits on the previous wire point
    const route = t.route.map(r => {
      if (r.x !== undefined) last = { x: r.x, y: r.y }
      return r.route_type === "wire" ? { route_type: "wire", x: last.x, y: last.y, width: TRACE_WIDTH, layer: r.layer }
                                     : { route_type: "via", x: last.x, y: last.y, from_layer: r.from_layer, to_layer: r.to_layer }
    })
    // a via sitting on a through-hole pad is a layer change the pad already provides: drop it (KiCad flags co-located drills)
    const onTht = r => r.route_type === "via" && thtPads.some(p => Math.hypot(p.x - r.x, p.y - r.y) < 0.05)
    const kept = route.filter(r => !onTht(r))
    cj.push({ type: "pcb_trace", pcb_trace_id: `pcb_trace_${n++}`, source_trace_id: t.connection_name ?? t.pcb_trace_id, route: kept })
    for (const r of kept) if (r.route_type === "via")
      cj.push({ type: "pcb_via", pcb_via_id: `pcb_via_${n}_${Math.random().toString(36).slice(2, 6)}`, x: r.x, y: r.y, outer_diameter: 0.6, hole_diameter: 0.3, layers: ["top", "bottom"] })
  }
  log(`  routed ${n} of ${connections.length} connections, ${obstacles.length} obstacles`)
})
writeFileSync(join(outDir, "routed.circuit.json"), JSON.stringify(cj))

// 3. fab outputs
await step("gerbers+drill", async () => {
  const { convertCircuitJsonToGerberFiles } = await import("circuit-json-to-gerber")
  const files = convertCircuitJsonToGerberFiles(cj)
  mkdirSync(join(outDir, "gerbers"), { recursive: true })
  for (const [name, content] of Object.entries(files)) writeFileSync(join(outDir, "gerbers", name), content)
  log("  files:", Object.keys(files).join(" "))
})
await step("pnp.csv", async () => {
  const { convertCircuitJsonToPickAndPlaceCsv } = await import("circuit-json-to-pnp-csv")
  writeFileSync(join(outDir, "pnp.csv"), convertCircuitJsonToPickAndPlaceCsv(cj))
})
await step("bom.csv", async () => {
  const { convertCircuitJsonToBomRows, convertBomRowsToCsv } = await import("circuit-json-to-bom-csv")
  const rows = await convertCircuitJsonToBomRows({ circuitJson: cj })
  writeFileSync(join(outDir, "bom.csv"), convertBomRowsToCsv(rows))
})
await step("board.kicad_pcb", async () => {
  const { CircuitJsonToKicadPcbConverter } = await import("circuit-json-to-kicad")
  const c = new CircuitJsonToKicadPcbConverter(cj); c.runUntilFinished()
  writeFileSync(join(outDir, "board.kicad_pcb"), c.getOutputString())
})
await step("board.svg", async () => {
  const { convertCircuitJsonToPcbSvg } = await import("circuit-to-svg")
  writeFileSync(join(outDir, "board.svg"), convertCircuitJsonToPcbSvg(cj))
})
await step("board.glb", async () => {
  const { convertCircuitJsonToGltf } = await import("circuit-json-to-gltf")
  const glb = await convertCircuitJsonToGltf(cj, { format: "glb", includeModels: true })
  writeFileSync(join(outDir, "board.glb"), Buffer.from(glb))
})
await step("board.step", async () => {
  const { circuitJsonToStep } = await import("circuit-json-to-step")
  const txt = await circuitJsonToStep(cj, { productName: "board", includeComponents: true, includeExternalMeshes: true })
  writeFileSync(join(outDir, "board.step"), txt)
})

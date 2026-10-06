// cadview lite — minimal viewer core on bare three.js (see index.html rules).
// Renders the same scene JSON the tcv viewer eats: shapes tree (loc = [[t],[q]]
// accumulated down the tree, per-part color/alpha) + flat deduped instance
// buffers. Event-driven rendering only — no requestAnimationFrame loop, so it
// keeps working in occluded windows and throttled WebViews.

import * as THREE from "three";
import { OrbitControls } from "./vendor/OrbitControls.js";

const view = document.getElementById("view");
const hud = document.getElementById("hud");
const hudText = document.getElementById("hud-text");
const emptyMsg = document.getElementById("empty");

// ---- renderer / scene / camera ---------------------------------------------
let renderer;
try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
} catch (e) {
    emptyMsg.textContent = "No WebGL in this browser — the 3D viewer needs it. " +
        "Open this URL in a regular browser tab.";
    throw e;
}
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
view.appendChild(renderer.domElement);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 1e6);
camera.up.set(0, 0, 1);                       // build123d is Z-up
scene.add(camera);
camera.add(new THREE.DirectionalLight(0xffffff, 1.6));   // headlight
scene.add(new THREE.AmbientLight(0xffffff, 1.1));

const controls = new OrbitControls(camera, renderer.domElement);
controls.addEventListener("change", render);

const modelGroup = new THREE.Group();
scene.add(modelGroup);

function render() { renderer.render(scene, camera); drawGizmo(); }

// ---- xyz orientation gizmo (bottom-left): shows camera orientation; click
// an axis ball to snap the view down that axis ----------------------------
const gizmo = document.getElementById("gizmo");
const gtx = gizmo.getContext("2d");
const GAXES = [
    { v: [1, 0, 0], color: "#e0656f", label: "X" },
    { v: [0, 1, 0], color: "#8fbf6a", label: "Y" },
    { v: [0, 0, 1], color: "#5aa0e8", label: "Z" },
];
const _gq = new THREE.Quaternion(), _gv = new THREE.Vector3();
let gizmoHits = [];

function drawGizmo() {
    const C = 55, R = 38;
    _gq.copy(camera.quaternion).invert();
    gtx.clearRect(0, 0, 110, 110);
    const pts = GAXES.map((a) => {
        _gv.set(...a.v).applyQuaternion(_gq);
        return { ...a, x: C + _gv.x * R, y: C - _gv.y * R, z: _gv.z };
    }).sort((p, q) => p.z - q.z);
    gizmoHits = pts;
    for (const p of pts) {
        const front = p.z >= -0.01;
        gtx.strokeStyle = p.color;
        gtx.globalAlpha = front ? 0.95 : 0.45;
        gtx.lineWidth = 2;
        gtx.beginPath(); gtx.moveTo(C, C); gtx.lineTo(p.x, p.y); gtx.stroke();
        gtx.globalAlpha = front ? 1 : 0.5;
        gtx.fillStyle = p.color;
        gtx.beginPath(); gtx.arc(p.x, p.y, 8.5, 0, 7); gtx.fill();
        gtx.fillStyle = "#1b1f27";
        gtx.font = "700 10px system-ui, sans-serif";
        gtx.textAlign = "center"; gtx.textBaseline = "middle";
        gtx.fillText(p.label, p.x, p.y + 0.5);
    }
    gtx.globalAlpha = 1;
}

gizmo.addEventListener("click", (e) => {
    const r = gizmo.getBoundingClientRect();
    const mx = (e.clientX - r.left) * (110 / r.width), my = (e.clientY - r.top) * (110 / r.height);
    const hit = [...gizmoHits].reverse().find((p) => Math.hypot(p.x - mx, p.y - my) < 12);
    if (!hit) return;
    const dist = camera.position.distanceTo(controls.target) || 100;
    camera.up.set(...(hit.v[2] ? [0, 1, 0] : [0, 0, 1]));   // looking down ±Z needs a Y up
    camera.position.copy(controls.target).addScaledVector(_gv.set(...hit.v), dist);
    controls.update();
    render();
});

let trayAutoOpened = false;
function resize() {
    const w = view.clientWidth, h = view.clientHeight;
    renderer.setSize(w, h);   // sets canvas CSS size too — without it the DPR-scaled canvas overflows, cropping the view and dropping effective resolution
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    // wide layout -> the parts tree docks open by default (unless this
    // viewer explicitly closed it — remembered per browser). Decided HERE,
    // not at module eval: chromeless app windows can evaluate JS before the
    // compositor sizes the surface, so a load-time width check sees ~0.
    // James's desk windows sit ~760 CSS px wide, so the bar is 600.
    if (!trayAutoOpened && w >= 600) {
        trayAutoOpened = true;
        tray.hidden = false;            // permanent dock — no close affordance
        if (lastShapes) buildTray();
    }
    render();
}
new ResizeObserver(resize).observe(view);

// ---- scene JSON -> three objects -------------------------------------------
const DTYPES = { float32: Float32Array, int32: Int32Array };

function decode(field) {
    const bin = atob(field.buffer);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new DTYPES[field.dtype](bytes.buffer);
}

const partsIndex = new Map();   // id -> { meshes: [], node, group }
const nodeGroups = new Map();   // id -> THREE.Group (animation targets)
let lastShapes = null;
let lastMsg = null;             // kept for topo arrays (face picking) + meta
let bbox = null;

export const timings = {};

function disposeModel() {
    modelGroup.traverse((o) => { o.geometry?.dispose(); o.material?.dispose?.(); });
    modelGroup.clear();
    partsIndex.clear();
    nodeGroups.clear();
    stopAnimation();
}

function buildModel(msg) {
    const t0 = performance.now();
    disposeModel();
    lastMsg = msg;
    topoCache.clear();
    lastShapes = msg.data.shapes;
    const instances = msg.data.instances;

    // decoded geometry per instance ref, shared across parts using it
    const geomCache = new Map();
    const edgeCache = new Map();
    const matCache = new Map();

    const geomFor = (ref) => {
        if (!geomCache.has(ref)) {
            const inst = instances[ref];
            const g = new THREE.BufferGeometry();
            g.setAttribute("position", new THREE.BufferAttribute(decode(inst.vertices), 3));
            g.setAttribute("normal", new THREE.BufferAttribute(decode(inst.normals), 3));
            g.setIndex(new THREE.BufferAttribute(new Uint32Array(decode(inst.triangles).buffer), 1));
            geomCache.set(ref, g);
        }
        return geomCache.get(ref);
    };
    const edgesFor = (ref) => {
        if (!edgeCache.has(ref)) {
            const inst = instances[ref];
            if (!inst.edges || !inst.edges.shape?.[0]) { edgeCache.set(ref, null); return null; }
            const g = new THREE.BufferGeometry();
            g.setAttribute("position", new THREE.BufferAttribute(decode(inst.edges), 3));
            edgeCache.set(ref, g);
        }
        return edgeCache.get(ref);
    };
    const matFor = (color, alpha) => {
        const key = color + "/" + alpha;
        if (!matCache.has(key)) {
            matCache.set(key, new THREE.MeshStandardMaterial({
                color: new THREE.Color(color || "#e8b024"),
                metalness: 0.3, roughness: 0.65,
                transparent: alpha < 1, opacity: alpha,
                depthWrite: alpha >= 1,
                side: THREE.DoubleSide,
                polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1,
            }));
        }
        return matCache.get(key);
    };
    const edgeMat = new THREE.LineBasicMaterial({ color: 0x707070 });

    // real group hierarchy mirroring the shapes tree, so animation tracks
    // can drive any node (subassembly or leaf) by its path
    const applyLoc = (obj, loc) => {
        if (!loc) return;
        obj.position.set(...loc[0]);
        obj.quaternion.set(...loc[1]);
    };
    const walk = (node, parent) => {
        const g = new THREE.Group();
        g.name = node.name || "";
        applyLoc(g, node.loc);
        g.userData.id = node.id;
        g.userData.basePos = g.position.clone();
        g.userData.baseQuat = g.quaternion.clone();
        parent.add(g);
        nodeGroups.set(node.id, g);
        if (node.parts) { node.parts.forEach((c) => walk(c, g)); return; }
        if (node.type !== "shapes" || !Number.isInteger(node.shape?.ref)) return;
        const alpha = node.alpha ?? 1;
        const mesh = new THREE.Mesh(geomFor(node.shape.ref), matFor(node.color, alpha));
        mesh.userData.id = node.id;
        mesh.userData.ref = node.shape.ref;
        mesh.userData.node = node;
        g.add(mesh);
        const objs = [mesh];
        const eg = edgesFor(node.shape.ref);
        if (eg) {
            const lines = new THREE.LineSegments(eg, edgeMat);
            lines.userData.id = node.id;
            g.add(lines);
            objs.push(lines);
        }
        partsIndex.set(node.id, { meshes: objs, node, group: g });
    };
    walk(lastShapes, modelGroup);
    modelGroup.updateMatrixWorld(true);
    setupAnimation(msg.animations ?? (msg.animation ? [{ name: "animation", ...msg.animation }] : []));

    const bb = lastShapes.bb;
    bbox = bb ? new THREE.Box3(
        new THREE.Vector3(bb.xmin, bb.ymin, bb.zmin),
        new THREE.Vector3(bb.xmax, bb.ymax, bb.zmax)) : null;

    timings.build_ms = performance.now() - t0;
    emptyMsg.hidden = true;
    if (!restoreCamera) fitView();
    restoreCamera = false;
    render();
    if (!tray.hidden) buildTray();
}

// ---- camera ----------------------------------------------------------------
let restoreCamera = false;   // set when a re-push arrives with a live camera

function fitView() {
    if (!bbox) return;
    const center = bbox.getCenter(new THREE.Vector3());
    const radius = bbox.getSize(new THREE.Vector3()).length() / 2 || 10;
    const dir = new THREE.Vector3(1, -1, 0.7).normalize();   // iso-ish, Z-up
    camera.position.copy(center).addScaledVector(dir, radius * 2.4);
    camera.near = radius / 100;
    camera.far = radius * 100;
    camera.updateProjectionMatrix();
    controls.target.copy(center);
    controls.update();
    render();
}

// double click/tap: on a part -> open the tray at it (quick hide);
// on empty space -> fit. The two single-tap picks toggle-cancel first.
function dblAction(clientX, clientY) {
    const hit = lastMsg ? pickAt(clientX, clientY) : null;
    if (hit) openTrayFor(hit.mesh.userData.id);
    else fitView();
}
let lastTap = 0;
renderer.domElement.addEventListener("touchend", (e) => {
    if (e.touches.length > 0 || e.changedTouches.length !== 1) return;
    const now = Date.now();
    const t = e.changedTouches[0];
    if (now - lastTap < 300) dblAction(t.clientX, t.clientY);
    lastTap = now;
}, { passive: true });
renderer.domElement.addEventListener("dblclick", (e) => dblAction(e.clientX, e.clientY));

// ---- parts tray (same UX as the main shell's mobile tray) ------------------
const tray = document.getElementById("tray");
const trayExpanded = new Set();
function setTrayOpen(open) {
    if (open) {
        pickPanel.hidden = true;
        buildTray();
        tray.hidden = false;
    } else tray.hidden = true;
    try { localStorage.setItem("lite-tray", open ? "open" : "closed"); } catch { }
}
document.getElementById("traybtn").addEventListener("click", () => setTrayOpen(tray.hidden));

// crisp inline icons (feather-style strokes) — the emoji eyes looked off
const SVG_EYE = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-7.5 11-7.5S23 12 23 12s-4 7.5-11 7.5S1 12 1 12z"/><circle cx="12" cy="12" r="3"/></svg>';
const SVG_EYE_OFF = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 19.5c-7 0-11-7.5-11-7.5a18.45 18.45 0 0 1 5.06-5.94M9.9 4.74A9.12 9.12 0 0 1 12 4.5c7 0 11 7.5 11 7.5a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>';
const SVG_X = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
const SVG_PLAY = '<svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"><polygon points="6 4 20 12 6 20"/></svg>';
const SVG_PAUSE = '<svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor"><rect x="5" y="4" width="5" height="16" rx="1"/><rect x="14" y="4" width="5" height="16" rx="1"/></svg>';
const SVG_WARN = '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>';
const SVG_CHEV = '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 6 15 12 9 18"/></svg>';

const leafIds = (node, out = []) => {
    if (node.parts) node.parts.forEach((c) => leafIds(c, out));
    else if (node.id) out.push(node.id);
    return out;
};

function setVisible(ids, v) {
    for (const id of ids) {
        const part = partsIndex.get(id);
        part?.meshes.forEach((o) => { o.visible = v; });
    }
    render();
    buildTray();
}

let traySeeded = null;              // root id we auto-expanded (once per model)
function buildTray() {
    if (!lastShapes) { tray.textContent = ""; return; }
    // seed the root expanded ONCE; after that the user's collapse state is
    // law (the old "re-seed when empty" made the root uncollapsible)
    if (traySeeded !== lastShapes.id) {
        traySeeded = lastShapes.id;
        if (trayExpanded.size === 0) trayExpanded.add(lastShapes.id);
    }
    const scroll = tray.scrollTop;
    tray.textContent = "";
    const head = document.createElement("div");
    head.className = "phead";
    const mkBtn = (text, title, onClick) => {
        const b = document.createElement("button");
        b.textContent = text;
        b.title = title;
        b.addEventListener("click", onClick);
        return b;
    };
    // left: the designs picker (rebuilds are automatic — the hub watches
    // every registered module, no buttons); right: tray controls
    const designCtl = document.createElement("span");
    if (connected) designCtl.append(mkBtn("designs", "this folder's designs", () => openPicker()));
    const btns = document.createElement("span");
    const allBtn = mkBtn("show all", "show every hidden part again", () => setVisible(leafIds(lastShapes), true));
    btns.append(allBtn);
    head.append(designCtl, btns);
    tray.append(head);

    const visibleOf = (id) => partsIndex.get(id)?.meshes[0]?.visible ?? true;
    const walk = (node, depth) => {
        const isGroup = !!node.parts;
        const ids = leafIds(node);
        if (!ids.length) return;
        const anyOn = ids.some(visibleOf);
        const row = document.createElement("div");
        row.className = "prow" + (anyOn ? "" : " off");
        row.style.paddingLeft = 6 + depth * 18 + "px";
        const chev = document.createElement("span");
        chev.className = "pchev" + (isGroup && trayExpanded.has(node.id) ? " open" : "");
        if (isGroup) chev.innerHTML = SVG_CHEV;
        const swatch = document.createElement("span");
        swatch.className = "pswatch";
        swatch.style.background = (!isGroup && node.color) || "transparent";
        const name = document.createElement("span");
        name.className = "pname";
        name.textContent = node.name || node.id;
        const eye = document.createElement("button");
        eye.className = "peye";
        eye.innerHTML = anyOn ? SVG_EYE : SVG_EYE_OFF;
        eye.addEventListener("click", (e) => { e.stopPropagation(); setVisible(ids, !anyOn); });
        row.dataset.id = node.id;
        if (!isGroup && mySel.some((s) => s.key === node.id)) row.classList.add("sel");
        row.append(chev, swatch, name, eye);
        row.addEventListener("click", () => {
            // ocp-viewer semantics: the eye hides, the LABEL selects (leaf)
            // or expands (group)
            if (isGroup) {
                trayExpanded.has(node.id) ? trayExpanded.delete(node.id) : trayExpanded.add(node.id);
                buildTray();
            } else toggleSelectById(node.id);
        });
        tray.append(row);
        if (isGroup && trayExpanded.has(node.id)) node.parts.forEach((c) => walk(c, depth + 1));
    };
    walk(lastShapes, 0);
    tray.scrollTop = scroll;
}

function openTrayFor(id) {
    // expand every ancestor group of the part, open the tray, flash its row
    const segs = id.split("/").filter(Boolean);
    let path = "";
    for (const s of segs.slice(0, -1)) { path += "/" + s; trayExpanded.add(path); }
    buildTray();
    tray.hidden = false;
    const row = tray.querySelector(`[data-id="${CSS.escape(id)}"]`);
    if (row) {
        row.scrollIntoView({ block: "center" });
        row.classList.add("flash");
        setTimeout(() => row.classList.remove("flash"), 1700);
    }
}



// ---- animation (M3): tracks pushed with the scene drive node groups --------
// track = [selector, action, times[], values[]]; actions: t/tx/ty/tz (mm,
// relative to the node's base position), rx/ry/rz (degrees about the node's
// local axis), q (quaternion). RAF runs ONLY while playing.
const animBar = document.getElementById("animbar");
const playBtn = document.getElementById("anim-play");
const scrub = document.getElementById("anim-scrub");
const timeLabel = document.getElementById("anim-time");
const clipSel = document.getElementById("anim-clip");
let anim = null, animRAF = 0, animPrev = 0;
let animClips = [];             // a design can carry several named animations
const DEG = Math.PI / 180;

function resolveTargets(selector) {
    // a selector is an id or a path suffix and drives EVERY match — scope
    // with parent segments (".../level 1/runner inner ...") to single out
    // one of several same-labelled parts; duplicate labels get (2), (3)…
    if (nodeGroups.has(selector)) return [nodeGroups.get(selector)];
    const out = [];
    for (const [id, g] of nodeGroups)
        if (id.endsWith("/" + selector)) out.push(g);
    return out;
}

function setupAnimation(clips) {
    animBar.hidden = true;
    anim = null;
    animClips = (clips || []).filter((c) => Array.isArray(c?.tracks) && c.tracks.length);
    clipSel.textContent = "";
    clipSel.hidden = animClips.length < 2;
    animClips.forEach((c, i) => {
        const o = document.createElement("option");
        o.value = i;
        o.textContent = c.name || `clip ${i + 1}`;
        clipSel.append(o);
    });
    if (animClips.length) loadClip(0);
}

function loadClip(index) {
    // switching clips: stop playback, put every previously animated node
    // back on base, drop collision tints, then rebuild for the new tracks
    if (animRAF) cancelAnimationFrame(animRAF);
    playBtn.innerHTML = SVG_PLAY;
    if (anim) {
        for (const g of anim.animated) {
            g.position.copy(g.userData.basePos);
            g.quaternion.copy(g.userData.baseQuat);
        }
        modelGroup.updateMatrixWorld(true);
    }
    resetClearance();
    anim = null;
    const spec = animClips[index];
    if (!spec) { animBar.hidden = true; return; }
    const tracks = [];
    let duration = 0;
    for (const tr of spec.tracks) {
        const [selector, action, times, values] = Array.isArray(tr)
            ? tr : [tr.selector, tr.action, tr.times, tr.values];
        const groups = resolveTargets(selector);
        if (!groups.length || !Array.isArray(times) || times.length < 2) continue;
        duration = Math.max(duration, times[times.length - 1]);
        tracks.push({ groups, action, times, values });
    }
    if (!tracks.length || duration <= 0) { animBar.hidden = true; render(); return; }
    const animated = new Set();
    tracks.forEach((tr) => tr.groups.forEach((g) => animated.add(g)));
    anim = { tracks, animated, duration, speed: spec.speed || 1, playing: false, t: 0 };
    scrub.max = duration;
    scrub.step = duration / 500;
    clipSel.value = index;
    animBar.hidden = false;
    collectClearance();
    if (!clearance) applyAnimTime(0);   // rest pose (vis tracks) even with the checker off
}
clipSel.addEventListener("change", () => loadClip(+clipSel.value));

function sampleTrack(times, values, t) {
    if (t <= times[0]) return values[0];
    const n = times.length;
    if (t >= times[n - 1]) return values[n - 1];
    let i = 1;
    while (times[i] < t) i++;
    let f = (t - times[i - 1]) / (times[i] - times[i - 1]);
    f = f * f * (3 - 2 * f);        // smoothstep: things accelerate and settle
    const a = values[i - 1], b = values[i];
    if (Array.isArray(a)) {
        if (a.length === 4)
            return new THREE.Quaternion(...a).slerp(new THREE.Quaternion(...b), f);
        return a.map((x, k) => x + (b[k] - x) * f);
    }
    return a + (b - a) * f;
}

function applyAnimTime(t) {
    if (!anim) return;
    anim.t = t;
    // tracks COMPOSE: reset every animated node to its base transform, then
    // accumulate each track's contribution (a ty slide + tz lift on the same
    // node must add, not last-writer-wins — the rack box bug)
    for (const g of anim.animated) {
        g.position.copy(g.userData.basePos);
        g.quaternion.copy(g.userData.baseQuat);
        g.visible = true;
    }
    for (const { groups, action, times, values } of anim.tracks) {
      const v = sampleTrack(times, values, t);
      for (const group of groups) {
        if (action === "vis") group.visible = v > 0.5;
        else if (action === "t") { group.position.x += v[0]; group.position.y += v[1]; group.position.z += v[2]; }
        else if (action === "tx") group.position.x += v;
        else if (action === "ty") group.position.y += v;
        else if (action === "tz") group.position.z += v;
        else if (action === "q") group.quaternion
            .multiply(v.isQuaternion ? v : new THREE.Quaternion(...v));
        else if (action === "rx" || action === "ry" || action === "rz") {
            const axis = { rx: [1, 0, 0], ry: [0, 1, 0], rz: [0, 0, 1] }[action];
            group.quaternion.multiply(
                new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(...axis), v * DEG));
        }
      }
    }
    modelGroup.updateMatrixWorld(true);
    // keep face-selection overlays glued to their (possibly moving) parts
    for (const m of selMarks.values())
        if (m.overlay && m.srcMesh) m.overlay.matrix.copy(m.srcMesh.matrixWorld);
    if (hoverMark && hoverSrcMesh) hoverMark.matrix.copy(hoverSrcMesh.matrixWorld);
    updateClearance();
    scrub.value = t;
    timeLabel.textContent = t.toFixed(1) + "s";
    render();
}


// ---- animated clearance check: coarse world AABBs, baseline-excluded ------
// Everything in an assembly touches at rest, so only NEW overlaps (pairs not
// overlapping at t=0) count as collisions. Coarse by design: no false
// negatives, cheap enough to run every animation frame.
const CLEAR_EPS = 0.4;                 // mm shrink: resting contact isn't a hit
let clearance = null;                  // { moving, stat, baseline, hits }
let clearanceOn = true;                // toggleable; remembered per browser
try { clearanceOn = localStorage.getItem("lite-clearance") !== "off"; } catch { }
const clearBadge = document.getElementById("anim-clear");
const clearToggle = document.getElementById("anim-clear-toggle");
const collTint = new Map();            // mesh -> original material

function setClearanceOn(on) {
    clearanceOn = on;
    try { localStorage.setItem("lite-clearance", on ? "on" : "off"); } catch { }
    clearToggle.classList.toggle("off", !on);
    if (!on) resetClearance();
    else if (anim) collectClearance();
    render();
}
clearToggle.addEventListener("click", () => setClearanceOn(!clearanceOn));

const _cv = new THREE.Vector3();
function worldAABB(mesh, out) {
    if (!mesh.geometry.boundingBox) mesh.geometry.computeBoundingBox();
    const bb = mesh.geometry.boundingBox;
    out.min.set(Infinity, Infinity, Infinity);
    out.max.set(-Infinity, -Infinity, -Infinity);
    for (let i = 0; i < 8; i++) {
        _cv.set(i & 1 ? bb.max.x : bb.min.x, i & 2 ? bb.max.y : bb.min.y,
                i & 4 ? bb.max.z : bb.min.z).applyMatrix4(mesh.matrixWorld);
        out.min.min(_cv); out.max.max(_cv);
    }
    return out;
}
const _overlaps = (a, b) =>
    a.min.x < b.max.x - CLEAR_EPS && b.min.x < a.max.x - CLEAR_EPS &&
    a.min.y < b.max.y - CLEAR_EPS && b.min.y < a.max.y - CLEAR_EPS &&
    a.min.z < b.max.z - CLEAR_EPS && b.min.z < a.max.z - CLEAR_EPS;

function collectClearance() {
    clearance = null;
    clearToggle.hidden = !anim;
    clearToggle.classList.toggle("off", !clearanceOn);
    if (!anim || !clearanceOn) return;
    const moving = [], stat = [];
    const sig = new Map();
    for (const { meshes } of partsIndex.values()) {
        const mesh = meshes.find((m) => m.isMesh);
        if (!mesh) continue;
        const chain = [];
        for (let p = mesh; p; p = p.parent)
            if (anim.animated.has(p)) chain.push(p.userData.id ?? p.uuid);
        sig.set(mesh, chain.join(">"));
        (chain.length ? moving : stat).push(mesh);
    }
    clearance = { moving, stat, sig, baseline: null, hits: new Set() };
    applyAnimTime(0);                          // computes + records the baseline
}

const _effVisible = (o) => {
    for (let p = o; p; p = p.parent) if (!p.visible) return false;
    return true;
};

function collidingPairs() {
    const boxes = new Map();
    const bbOf = (m) => {
        let b = boxes.get(m);
        if (!b) { b = worldAABB(m, new THREE.Box3()); boxes.set(m, b); }
        return b;
    };
    // the BASELINE pass is pure geometry (a vis-tracked pellet resting
    // inside its outlet must still earn baseline exclusion); visibility
    // only filters live reporting
    const skipHidden = clearance.baseline !== null;
    const pairs = new Map();                   // key -> [meshA, meshB]
    for (const m of clearance.moving) {
        if (skipHidden && !_effVisible(m)) continue;
        const bm = bbOf(m);
        for (const other of [...clearance.stat, ...clearance.moving]) {
            if (other === m) continue;
            if (skipHidden && !_effVisible(other)) continue;
            if (clearance.sig.get(m) === clearance.sig.get(other)) continue;   // rigid together
            const ka = m.userData.id, kb = other.userData.id;
            const key = ka < kb ? ka + "|" + kb : kb + "|" + ka;
            if (pairs.has(key)) continue;
            if (_overlaps(bm, bbOf(other))) pairs.set(key, [m, other]);
        }
    }
    return pairs;
}

function updateClearance() {
    if (!clearance) return;
    const pairs = collidingPairs();
    if (clearance.baseline === null) {         // first call = rest pose
        clearance.baseline = new Set(pairs.keys());
        return;
    }
    const hitMeshes = new Set();
    const hitNames = [];
    for (const [key, [a, b]] of pairs) {
        if (clearance.baseline.has(key)) continue;
        hitMeshes.add(a); hitMeshes.add(b);
        hitNames.push(a.userData.node.name + " ✕ " + b.userData.node.name);
    }
    for (const [mesh, orig] of collTint) {
        if (!hitMeshes.has(mesh)) { mesh.material = orig; collTint.delete(mesh); }
    }
    for (const mesh of hitMeshes) {
        if (collTint.has(mesh)) continue;
        collTint.set(mesh, mesh.material);
        const red = mesh.material.clone();
        red.emissive = new THREE.Color(0xcc2222);
        red.emissiveIntensity = 0.7;
        mesh.material = red;
    }
    clearance.hits = new Set(hitNames);
    clearBadge.hidden = hitNames.length === 0;
    clearBadge.innerHTML = SVG_WARN + "<span>" + hitNames.length + "</span>";
    clearBadge.title = hitNames.join("\n");
}

function resetClearance() {
    for (const [mesh, orig] of collTint) mesh.material = orig;
    collTint.clear();
    clearBadge.hidden = true;
    clearance = null;
}

function animStep(now) {
    if (!anim?.playing) return;
    const dt = ((now - animPrev) / 1000) * anim.speed;
    animPrev = now;
    applyAnimTime((anim.t + dt) % anim.duration);
    animRAF = requestAnimationFrame(animStep);
}

function clearHover() {
    if (!hoverMark) return;
    overlayGroup.remove(hoverMark);
    hoverMark.geometry.dispose();
    hoverMark = null; hoverKey = null; hoverSrcMesh = null;
    render();
}

function playPause() {
    if (!anim) return;
    clearHover();
    anim.playing = !anim.playing;
    playBtn.innerHTML = anim.playing ? SVG_PAUSE : SVG_PLAY;
    if (anim.playing) { animPrev = performance.now(); animRAF = requestAnimationFrame(animStep); }
    else cancelAnimationFrame(animRAF);
}

function stopAnimation() {
    if (animRAF) cancelAnimationFrame(animRAF);
    if (anim) anim.playing = false;
    anim = null;
    animClips = [];
    collTint.clear();           // model is being disposed with its materials
    clearance = null;
    clearBadge.hidden = true;
    clearToggle.hidden = true;
    animBar.hidden = true;
    playBtn.innerHTML = SVG_PLAY;
}

playBtn.addEventListener("click", playPause);
scrub.addEventListener("input", () => applyAnimTime(+scrub.value));

// ---- record: one loop of the current clip -> video download ---------------
// canvas.captureStream + MediaRecorder — mp4 where the browser muxes it
// (Chrome 126+), else webm. Frames only advance while the rAF playback
// loop renders, so this records from a VISIBLE window.
const recBtn = document.getElementById("anim-rec");
let recorder = null;
function recordClip() {
    if (!anim || recorder) return;
    const type = ["video/mp4;codecs=avc1", "video/mp4", "video/webm;codecs=vp9", "video/webm"]
        .find((t) => window.MediaRecorder && MediaRecorder.isTypeSupported(t));
    if (!type) return;
    const chunks = [];
    recorder = new MediaRecorder(renderer.domElement.captureStream(60),
                                 { mimeType: type, videoBitsPerSecond: 8e6 });
    recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    recorder.onstop = () => {
        const ext = type.startsWith("video/mp4") ? "mp4" : "webm";
        const clip = (animClips[+clipSel.value]?.name || "clip").replace(/[^\w-]+/g, "_");
        const url = URL.createObjectURL(new Blob(chunks, { type }));
        const a = document.createElement("a");
        a.href = url;
        a.download = `${project || "scene"}-${clip}.${ext}`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 5000);
        recorder = null;
        recBtn.classList.remove("rec");
        if (anim?.playing) playPause();
        applyAnimTime(0);
    };
    recBtn.classList.add("rec");
    applyAnimTime(0);
    if (!anim.playing) playPause();
    recorder.start();
    setTimeout(() => recorder?.stop(), (anim.duration / anim.speed) * 1000 + 150);
}
recBtn.addEventListener("click", () => { if (recorder) recorder.stop(); else recordClip(); });

// ---- select + say (M2): pick faces/objects, message the model's owner -----
const SURFACE_TYPES = ["Plane", "Cylinder", "Cone", "Sphere", "Torus", "BezierSurface",
    "BSplineSurface", "SurfaceOfRevolution", "SurfaceOfExtrusion", "OffsetSurface", "OtherSurface"];
// selection is always on, face mode (James, 2026-09-30 — no mode button):
// tap/click picks a face; long-press (touch) or alt/shift-click (desktop)
// picks the whole object. setSelMode stays as a programmatic override.
let selMode = "face";
let mySel = [];                          // [{key, part, topo, ...}] payload = main-shell shape
const selMarks = new Map();              // key -> { overlay | mesh+origMat }

const topoCache = new Map();             // ref -> { tpf, prefix, faceTypes }
function topoFor(ref) {
    if (!topoCache.has(ref)) {
        const inst = lastMsg.data.instances[ref];
        const tpf = decode(inst.triangles_per_face);
        const prefix = new Uint32Array(tpf.length);
        for (let i = 1; i < tpf.length; i++) prefix[i] = prefix[i - 1] + tpf[i - 1];
        topoCache.set(ref, { tpf, prefix, faceTypes: decode(inst.face_types) });
    }
    return topoCache.get(ref);
}

function faceOfTriangle(ref, triIndex) {
    const { prefix, tpf } = topoFor(ref);
    let lo = 0, hi = tpf.length - 1;
    while (lo < hi) {                          // last face whose prefix <= triIndex
        const mid = (lo + hi + 1) >> 1;
        if (prefix[mid] <= triIndex) lo = mid; else hi = mid - 1;
    }
    return lo;
}

const _va = new THREE.Vector3(), _vb = new THREE.Vector3(), _vc = new THREE.Vector3();
const _ab = new THREE.Vector3(), _ac = new THREE.Vector3(), _cross = new THREE.Vector3();

function faceTriangles(mesh, face) {
    const { prefix, tpf } = topoFor(mesh.userData.ref);
    return { start: prefix[face], count: tpf[face] };
}

function worldTri(mesh, tri, out) {
    const pos = mesh.geometry.attributes.position;
    const idx = mesh.geometry.index.array;
    out[0].fromBufferAttribute(pos, idx[3 * tri]).applyMatrix4(mesh.matrixWorld);
    out[1].fromBufferAttribute(pos, idx[3 * tri + 1]).applyMatrix4(mesh.matrixWorld);
    out[2].fromBufferAttribute(pos, idx[3 * tri + 2]).applyMatrix4(mesh.matrixWorld);
}

function faceMetrics(mesh, face) {
    const { start, count } = faceTriangles(mesh, face);
    const tris = [_va, _vb, _vc];
    const areaVec = new THREE.Vector3();
    const centroid = new THREE.Vector3();
    const bb = new THREE.Box3();
    let area = 0;
    for (let t = start; t < start + count; t++) {
        worldTri(mesh, t, tris);
        _ab.subVectors(_vb, _va); _ac.subVectors(_vc, _va);
        _cross.crossVectors(_ab, _ac);
        const a = _cross.length() / 2;
        area += a;
        areaVec.addScaledVector(_cross, 0.5);
        centroid.addScaledVector(_va, a / 3).addScaledVector(_vb, a / 3).addScaledVector(_vc, a / 3);
        bb.expandByPoint(_va).expandByPoint(_vb).expandByPoint(_vc);
    }
    if (area > 1e-12) centroid.divideScalar(area);
    const n = areaVec.length() > 1e-12 ? areaVec.normalize() : null;
    const size = bb.getSize(new THREE.Vector3());
    const geomType = SURFACE_TYPES[topoFor(mesh.userData.ref).faceTypes[face]] ?? "Other";
    return {
        geomType, area: +area.toFixed(3),
        center: centroid.toArray().map((x) => +x.toFixed(3)),
        normal: n ? n.toArray().map((x) => +x.toFixed(3)) : null,
        size: size.toArray().map((x) => +x.toFixed(3)),
    };
}

function objectMetrics(mesh) {
    // volume by signed tetrahedra (exact for closed meshes), world coords
    const idx = mesh.geometry.index.array;
    const tris = [_va, _vb, _vc];
    let vol = 0;
    const bb = new THREE.Box3().setFromObject(mesh);
    for (let t = 0; t < idx.length / 3; t++) {
        worldTri(mesh, t, tris);
        vol += _va.dot(_cross.crossVectors(_vb, _vc)) / 6;
    }
    const size = bb.getSize(new THREE.Vector3());
    return {
        volume: +Math.abs(vol).toFixed(3),
        center: bb.getCenter(new THREE.Vector3()).toArray().map((x) => +x.toFixed(3)),
        size: size.toArray().map((x) => +x.toFixed(3)),
    };
}

// ---- highlight -------------------------------------------------------------
const overlayGroup = new THREE.Group();
scene.add(overlayGroup);
const faceHiMat = new THREE.MeshBasicMaterial({ color: 0x4da6ff, transparent: true, opacity: 0.6,
    side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2, depthWrite: false });
const hoverHiMat = faceHiMat.clone(); hoverHiMat.opacity = 0.3;

function faceOverlay(mesh, face, material) {
    const { start, count } = faceTriangles(mesh, face);
    const pos = mesh.geometry.attributes.position;
    const idx = mesh.geometry.index.array;
    const arr = new Float32Array(count * 9);
    for (let t = 0; t < count; t++)
        for (let v = 0; v < 3; v++) {
            const i = idx[3 * (start + t) + v];
            arr.set([pos.getX(i), pos.getY(i), pos.getZ(i)], (t * 3 + v) * 3);
        }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(arr, 3));
    const o = new THREE.Mesh(g, material);
    o.matrixAutoUpdate = false;
    o.matrix.copy(mesh.matrixWorld);
    overlayGroup.add(o);
    return o;
}

function markSelected(item, mesh) {
    if (item.topo === "face") {
        selMarks.set(item.key, { overlay: faceOverlay(mesh, item.face, faceHiMat), srcMesh: mesh });
    } else {
        const origMat = mesh.material;
        const hi = origMat.clone();
        hi.emissive = new THREE.Color(0x1d4ed8);
        hi.emissiveIntensity = 0.6;
        mesh.material = hi;
        selMarks.set(item.key, { mesh, origMat, hiMat: hi });
    }
}

function unmark(key) {
    const m = selMarks.get(key);
    if (!m) return;
    if (m.overlay) { overlayGroup.remove(m.overlay); m.overlay.geometry.dispose(); }
    if (m.mesh) { m.mesh.material = m.origMat; m.hiMat.dispose(); }
    selMarks.delete(key);
}

function clearSelection() {
    [...selMarks.keys()].forEach(unmark);
    mySel = [];
    renderSelPanel();
    render();
}

// ---- picking ---------------------------------------------------------------
const raycaster = new THREE.Raycaster();
function pickAt(clientX, clientY) {
    const r = renderer.domElement.getBoundingClientRect();
    raycaster.setFromCamera(new THREE.Vector2(
        ((clientX - r.left) / r.width) * 2 - 1,
        -((clientY - r.top) / r.height) * 2 + 1), camera);
    const meshes = [];
    modelGroup.traverse((o) => { if (o.isMesh && o.visible) meshes.push(o); });
    const hit = raycaster.intersectObjects(meshes, false)[0];
    if (!hit) return null;
    return { mesh: hit.object, face: faceOfTriangle(hit.object.userData.ref, hit.faceIndex) };
}

function describe(mesh, face, asObject) {
    const node = mesh.userData.node;
    const segs = node.id.split("/").filter(Boolean);
    const base = { part: segs[segs.length - 1] || node.id, solidPath: node.id };
    if (asObject) {
        return { ...base, key: node.id, topo: "object", path: node.id, ...objectMetrics(mesh) };
    }
    return { ...base, key: `${node.id}#${face}`, topo: "face", face,
             path: `${node.id}/faces/faces_${face}`, ...faceMetrics(mesh, face) };
}

function toggleSelectById(id) {
    // tray label click = object select, same as an alt-click on the canvas
    const part = partsIndex.get(id);
    const mesh = part?.meshes.find((m) => m.isMesh);
    if (!mesh) return;
    const existing = mySel.findIndex((s) => s.key === id);
    if (existing >= 0) { unmark(id); mySel.splice(existing, 1); }
    else { const item = describe(mesh, 0, true); markSelected(item, mesh); mySel.push(item); }
    renderSelPanel();
    render();
}

function togglePick(clientX, clientY, asObject) {
    if (selMode === "off" || !lastMsg) return;
    const hit = pickAt(clientX, clientY);
    if (!hit) return;
    const item = describe(hit.mesh, hit.face, asObject ?? selMode === "obj");
    const existing = mySel.findIndex((s) => s.key === item.key);
    if (existing >= 0) { unmark(item.key); mySel.splice(existing, 1); }
    else { markSelected(item, hit.mesh); mySel.push(item); }
    renderSelPanel();
    render();
}

// hover pre-highlight (desktop, event-driven — no rAF)
let hoverMark = null, hoverKey = null, hoverSrcMesh = null, lastHover = 0;
renderer.domElement.addEventListener("pointermove", (e) => {
    if (selMode === "off" || e.pointerType === "touch" || !lastMsg) return;
    const now = performance.now();
    if (now - lastHover < 30) return;
    lastHover = now;
    const hit = pickAt(e.clientX, e.clientY);
    const key = hit ? (selMode === "obj" ? hit.mesh.userData.id : `${hit.mesh.userData.id}#${hit.face}`) : null;
    if (key === hoverKey) return;
    if (hoverMark) { overlayGroup.remove(hoverMark); hoverMark.geometry.dispose(); hoverMark = null; hoverSrcMesh = null; }
    hoverKey = key;
    if (hit) {
        hoverSrcMesh = hit.mesh;
        if (selMode === "obj") {
            hoverMark = new THREE.Mesh(hit.mesh.geometry, hoverHiMat);
            hoverMark.matrixAutoUpdate = false;
            hoverMark.matrix.copy(hit.mesh.matrixWorld);
            overlayGroup.add(hoverMark);
        } else {
            hoverMark = faceOverlay(hit.mesh, hit.face, hoverHiMat);
        }
    }
    render();
});

// desktop click-to-pick (drag stays orbit)
let downAt = null;
renderer.domElement.addEventListener("pointerleave", () => clearHover());
renderer.domElement.addEventListener("mousedown", (e) => { if (e.button === 0) downAt = { x: e.clientX, y: e.clientY }; });
renderer.domElement.addEventListener("mouseup", (e) => {
    if (!downAt || e.button !== 0) return;
    const still = Math.hypot(e.clientX - downAt.x, e.clientY - downAt.y) < 6;
    downAt = null;
    if (still && Date.now() - lastTouchPick > 700)
        togglePick(e.clientX, e.clientY, (e.altKey || e.shiftKey) || undefined);
});
window.addEventListener("keydown", (e) => { if (e.key === "Escape") clearSelection(); });

// touch: tap = pick in mode, long-press = whole part; double-tap fit's two
// picks toggle-cancel, so only the re-frame lands
let touchSel = null, longTimer = null, lastTouchPick = 0;
renderer.domElement.addEventListener("touchstart", (e) => {
    clearTimeout(longTimer);
    if (selMode === "off" || e.touches.length !== 1) { touchSel = null; return; }
    const t = e.touches[0];
    touchSel = { x: t.clientX, y: t.clientY, t: Date.now(), moved: false, long: false };
    longTimer = setTimeout(() => {
        if (touchSel && !touchSel.moved) {
            touchSel.long = true;
            lastTouchPick = Date.now();
            togglePick(touchSel.x, touchSel.y, true);
            navigator.vibrate?.(15);
        }
    }, 550);
}, { passive: true });
renderer.domElement.addEventListener("touchmove", (e) => {
    if (!touchSel) return;
    const t = e.touches[0];
    if (!t || e.touches.length !== 1 ||
        Math.hypot(t.clientX - touchSel.x, t.clientY - touchSel.y) > 12) {
        touchSel.moved = true;
        clearTimeout(longTimer);
    }
}, { passive: true });
renderer.domElement.addEventListener("touchend", (e) => {
    clearTimeout(longTimer);
    if (!touchSel) return;
    const st = touchSel; touchSel = null;
    if (st.moved || st.long || Date.now() - st.t > 500) return;
    e.preventDefault();                       // suppress synthetic mouse events
    lastTouchPick = Date.now();
    togglePick(st.x, st.y);
}, { passive: false });

// ---- selection readout -----------------------------------------------------
const selPanel = document.getElementById("selpanel");
const fmtN = (x) => Math.abs(x) >= 100 ? x.toFixed(0) : Math.abs(x) >= 1 ? +x.toFixed(1) + "" : +x.toFixed(2) + "";
function selDetails(s) {
    const dims = s.size ? s.size.filter((d) => Math.abs(d) > 1e-6).map(fmtN).join("×") + " mm" : "";
    const bits = [];
    if (s.topo === "object") {
        if (dims) bits.push(dims);
        if (s.volume) bits.push(s.volume >= 1000
            ? (s.volume / 1000).toFixed(1) + " cm³" : fmtN(s.volume) + " mm³");
    } else {
        if (s.geomType) bits.push(s.geomType.toLowerCase());
        if (dims) bits.push(dims);
        if (s.area) bits.push(fmtN(s.area) + " mm²");
        if (s.normal) bits.push("n=(" + s.normal.map(fmtN).join(",") + ")");
    }
    return bits.join(" · ");
}
// ---- pair measurement: with exactly two selections, distances between them
const _ma = new THREE.Vector3(), _mb = new THREE.Vector3();
function itemVerts(item, cap = 1200) {
    // world-space sample points: a face contributes its own triangles'
    // vertices, an object the whole mesh (strided to the cap)
    const part = partsIndex.get(item.solidPath);
    const mesh = part?.meshes.find((m) => m.isMesh);
    if (!mesh) return [];
    const pos = mesh.geometry.attributes.position;
    const out = [];
    if (item.topo === "face") {
        const { start, count } = faceTriangles(mesh, item.face);
        const idx = mesh.geometry.index.array;
        const seen = new Set();
        for (let t = start; t < start + count; t++)
            for (let v = 0; v < 3; v++) seen.add(idx[3 * t + v]);
        for (const i of seen) out.push(i);
    } else {
        for (let i = 0; i < pos.count; i++) out.push(i);
    }
    const stride = Math.max(1, Math.ceil(out.length / cap));
    const verts = [];
    for (let k = 0; k < out.length; k += stride)
        verts.push(new THREE.Vector3().fromBufferAttribute(pos, out[k]).applyMatrix4(mesh.matrixWorld));
    return verts;
}

function measurePair(a, b) {
    const va = itemVerts(a), vb = itemVerts(b);
    if (!va.length || !vb.length || !a.center || !b.center) return null;
    let min = Infinity;
    for (const p of va) for (const q of vb) {
        const d = p.distanceToSquared(q);
        if (d < min) min = d;
    }
    _ma.set(...a.center); _mb.set(...b.center);
    const dc = _mb.clone().sub(_ma);
    return { dx: dc.x, dy: dc.y, dz: dc.z, center: dc.length(), min: Math.sqrt(min) };
}

function renderSelPanel() {
    if (!tray.hidden) buildTray();          // keep tray rows' sel state live
    pushSelection();
    if (!mySel.length) { selPanel.hidden = true; return; }
    selPanel.hidden = false;
    selPanel.textContent = "";
    mySel.forEach((s) => {
        const row = document.createElement("div");
        row.className = "selrow";
        const body = document.createElement("div");
        body.className = "selbody";
        const name = document.createElement("div");
        name.className = "selname";
        name.textContent = s.part;
        const tag = document.createElement("span");
        tag.className = "seltag";
        tag.textContent = s.topo === "object" ? "object" : "face " + s.face;
        name.append(tag);
        const det = document.createElement("div");
        det.className = "seldet";
        det.textContent = selDetails(s);
        body.append(name, det);
        const x = document.createElement("button");
        x.className = "selx";
        x.innerHTML = SVG_X;
        x.title = "deselect";
        x.addEventListener("click", () => {
            unmark(s.key);
            mySel = mySel.filter((i) => i.key !== s.key);
            renderSelPanel();
            render();
        });
        row.append(body, x);
        selPanel.append(row);
    });
    if (mySel.length === 2) {
        const m = measurePair(mySel[0], mySel[1]);
        if (m) {
            const row = document.createElement("div");
            row.className = "selmeas";
            row.textContent = `Δ ${fmtN(Math.abs(m.dx))} × ${fmtN(Math.abs(m.dy))} × ${fmtN(Math.abs(m.dz))} mm · ` +
                `centres ${fmtN(m.center)} mm · min ≈ ${fmtN(m.min)} mm`;
            row.title = "centre-to-centre delta per axis · straight-line centre distance · " +
                "minimum mesh distance (vertex sampled)";
            selPanel.append(row);
        }
    }
    const clear = document.createElement("button");
    clear.className = "selclear";
    clear.textContent = "clear all";
    clear.addEventListener("click", clearSelection);
    selPanel.append(clear);
}

function setSelMode(mode) {
    selMode = mode;
    if (mode === "off") clearSelection();
    if (hoverMark) { overlayGroup.remove(hoverMark); hoverMark.geometry.dispose(); hoverMark = null; hoverKey = null; render(); }
}

// ---- live selection -> server: agents pull it (GET /api/selection or the
// cadview MCP tool) instead of James typing messages at them from the page
let selPushTimer = 0;
function pushSelection() {
    if (!project || !connected) return;
    clearTimeout(selPushTimer);
    selPushTimer = setTimeout(() => {
        const payload = mySel.map(({ key, ...rest }) => rest);
        fetch(`/api/selection?name=${encodeURIComponent(project)}`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                selection: payload, revision: lastMsg?.meta?.revision,
                camera: { position: camera.position.toArray(), quaternion: camera.quaternion.toArray(),
                          target: controls.target.toArray(), zoom: 1 },
            }),
        }).catch(() => { });
    }, 250);
}

// ---- rebuilds + designs: no buttons — the hub watches every registered
// module and re-runs it on change (rebuild status lands in the hud via
// {type:"run"} WS events); "designs" in the tray header switches scenes.
const hudRun = document.getElementById("hud-run");
let connected = false;

function setRunStatus(text, cls) {
    hudRun.textContent = text ? " · " + text : "";
    hudRun.className = cls || "";
}

function updateRunUI() {
    if (!tray.hidden) buildTray();
}

async function fetchRunnable() {
    try {
        const resp = await fetch("/api/runnable", { cache: "no-store" });
        if (!resp.ok) return null;
        return (await resp.json()).projects || null;
    } catch { return null; }
}

async function runPost(url, body) {
    try {
        const resp = await fetch(url, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        if (!resp.ok)
            setRunStatus("✗ " + ((await resp.text().catch(() => "")) || "HTTP " + resp.status), "err");
        return resp.ok;
    } catch (e) { setRunStatus("✗ " + e.message, "err"); return false; }
}
// designs picker: every project with a scene, tap to open it
const pickPanel = document.getElementById("pickpanel");
async function openPicker(showAll) {
    if (!pickPanel.hidden && showAll === undefined) { pickPanel.hidden = true; return; }
    const all = await fetchRunnable();
    if (!all) return;
    // scope to the current scene's project FOLDER (server groups by the
    // pushing module's repo); "all designs" lifts the scope
    const curGroup = all.find((r) => r.project === project)?.group;
    const rows = (!showAll && curGroup) ? all.filter((r) => r.group === curGroup) : all;
    tray.hidden = true;             // one panel at a time — no stacked soup
    pickPanel.textContent = "";
    for (const r of rows) {
        const row = document.createElement("div");
        row.className = "pkrow" + (r.project === project ? " current" : "");
        const head = document.createElement("div");
        head.className = "pkproj";
        // org-facing: the display title leads; slug + time are fine print
        head.textContent = r.title || r.name || r.project;
        if (r.module) {
            const run = document.createElement("span");
            run.className = "pkrun";
            run.textContent = "⟳";
            run.title = `rebuilds from ${r.module}`;
            head.prepend(run);
        }
        const sub = document.createElement("div");
        sub.className = "pksub";
        const when = (r.received_at || "").replace(/^\d{4}-\d{2}-\d{2}T/, "").replace(/[+-]\d{4}$/, "");
        sub.textContent = [r.project, when].filter(Boolean).join(" · ");
        row.append(head, sub);
        row.addEventListener("click", () => {
            if (r.project === project) { pickPanel.hidden = true; return; }
            location.href = "/lite/" + encodeURIComponent(r.project);
        });
        pickPanel.append(row);
    }
    if (rows.length < all.length || showAll) {
        const foot = document.createElement("div");
        foot.className = "pkrow";
        const lbl = document.createElement("div");
        lbl.className = "pksub";
        lbl.textContent = showAll
            ? "◂ this project only"
            : `all designs (${all.length}) ▸`;
        foot.append(lbl);
        foot.addEventListener("click", () => openPicker(!showAll));
        pickPanel.append(foot);
    }
    pickPanel.hidden = false;
}

function onRunEvent(msg) {
    if (msg.status === "start") {
        setRunStatus(`rebuilding (${msg.path || "…"})`, "");
    } else if (msg.status === "done") {
        setRunStatus(`✓ rebuilt in ${msg.seconds}s`, "ok");
    } else if (msg.status === "error") {
        setRunStatus("✗ " + (msg.tail?.length ? msg.tail[msg.tail.length - 1] : "run failed"), "err");
        console.warn("cadview run failed:\n" + (msg.tail || []).join("\n"));
    }
}

// ---- data in: fetch + live websocket (rule 2: server is an enhancement) ----
const project = location.pathname.replace(/^\/(lite\/?)?/, "").replace(/\/+$/, "");
let lastReceivedAt = null;

async function fetchScene() {
    const url = "/api/scene" + (project ? "?name=" + encodeURIComponent(project) : "");
    const t0 = performance.now();
    let resp;
    try { resp = await fetch(url, { cache: "no-store" }); } catch { resp = null; }
    if (!resp || !resp.ok) {
        // static deployment (rule 2: no server, still a full viewer): a
        // baked scene.json next to the page is the whole install
        try { resp = await fetch("./scene.json", { cache: "no-store" }); } catch { return false; }
        if (!resp.ok) { emptyMsg.textContent = "nothing pushed for " + (project || "any project") + " yet"; return false; }
    }
    const text = await resp.text();
    timings.download_ms = performance.now() - t0;
    const t1 = performance.now();
    const msg = JSON.parse(text);
    timings.parse_ms = performance.now() - t1;
    lastReceivedAt = msg.meta?.received_at ?? null;
    showMsg(msg);
    return true;
}

let serverTitle = null;             // display title from titles.json, if any

function updateHud() {
    const meta = lastMsg?.meta || {};
    const when = (meta.received_at || "").replace(/^\d{4}-\d{2}-\d{2}T/, "").replace(/[+-]\d{4}$/, "");
    hudText.textContent = `${meta.title || serverTitle || meta.name || "scene"}${when ? " · " + when : ""}`;
}

function showMsg(msg) {
    buildModel(msg);
    updateHud();
    updateRunUI();
}

let retryDelay = 1000;
function connect() {
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    let socket;
    try {
        socket = new WebSocket(`${scheme}://${location.host}/ws${project ? "?scene=" + encodeURIComponent(project) : ""}`);
    } catch { return; }   // static deployment: no server, stay a plain viewer
    socket.onopen = () => {
        retryDelay = 1000; hud.classList.add("connected"); connected = true; updateRunUI();
        if (project && serverTitle === null) fetchRunnable().then((rows) => {
            serverTitle = rows?.find((r) => r.project === project)?.title || "";
            if (serverTitle && lastMsg) updateHud();
        });
    };
    socket.onmessage = (event) => {
        let msg;
        try { msg = JSON.parse(event.data); } catch { return; }
        if (msg.type === "data") {
            if (msg.meta?.received_at != null && msg.meta.received_at === lastReceivedAt) return;
            lastReceivedAt = msg.meta?.received_at ?? null;
            restoreCamera = bbox != null;   // keep the camera across re-pushes
            showMsg(msg);
        } else if (msg.type === "run") {
            onRunEvent(msg);
        } else if (msg.type === "hello") {
            // the served page carries a stamp of the lite files; a newer one on
            // the server means this long-lived page should reload itself once
            const mine = document.querySelector("meta[name=lite-stamp]")?.content;
            if (!mine) return;   // static deployment: no stamp, no reload
            fetch(location.pathname, { cache: "no-store" }).then((r) => r.text()).then((t) => {
                const current = t.match(/name="lite-stamp" content="(\d+)"/)?.[1];
                if (!current || current === mine) return;
                let done = null;
                try { done = sessionStorage.getItem("lite-reload"); } catch { }
                if (done !== current) {
                    try { sessionStorage.setItem("lite-reload", current); } catch { }
                    location.reload();
                }
            }).catch(() => { });
        } else if (msg.type === "clear") {
            disposeModel(); render();
            emptyMsg.textContent = "scene cleared";
            emptyMsg.hidden = false;
        }
    };
    socket.onclose = () => {
        hud.classList.remove("connected");
        connected = false; updateRunUI();
        setTimeout(connect, retryDelay);
        retryDelay = Math.min(retryDelay * 1.5, 10000);
    };
    socket.onerror = () => socket.close();
}

// debug/automation handle, mirroring the main shell's
window.cadviewLite = { timings, fitView, togglePick, setSelMode, playPause, applyAnimTime, loadClip, get clips() { return animClips.map((c) => c.name); }, get anim() { return anim; }, get clearanceHits() { return clearance ? [...clearance.hits] : []; }, get selection() { return mySel; }, get selMode() { return selMode; }, get parts() { return partsIndex; }, get scene() { return scene; } };

resize();
fetchScene().finally(connect);

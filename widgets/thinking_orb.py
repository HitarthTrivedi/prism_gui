"""Native PySide6 implementation of ThinkingOrb from thinking-orbs (Libraries.dev).

Pure Python 2D particle & geometric vector engine. Zero WebGL, zero external
dependencies, 100% native QPainter rendering at 60 FPS.
"""
from __future__ import annotations
import math
import time
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


# ── Mathematical primitives from thinking-orbs engine ────────────────────────
def _lerp(n: float, s: float, t: float) -> float:
    return n + (s - n) * t


def _fract(n: float) -> float:
    return n - math.floor(n)


def _hash_rand(n: float, s: float) -> float:
    t = math.sin(n * 12.9898 + s * 78.233) * 43758.5453
    return t - math.floor(t)


def _val_noise(n: float, s: float) -> float:
    t = math.floor(n)
    r = math.floor(s)
    a = n - t
    o = s - r
    a = a * a * (3.0 - 2.0 * a)
    o = o * o * (3.0 - 2.0 * o)
    c = _hash_rand(t, r)
    M = _hash_rand(t + 1.0, r)
    h = _hash_rand(t, r + 1.0)
    m = _hash_rand(t + 1.0, r + 1.0)
    return c + (M - c) * a + (h - c) * o + (c - M - h + m) * a * o


def _fibonacci_sphere(n: int, s: int) -> list[float]:
    t = math.pi * (3.0 - math.sqrt(5.0))
    r = 1.0 - 2.0 * (n + 0.5) / s
    a = math.sqrt(max(0.0, 1.0 - r * r))
    o = n * t
    return [a * math.cos(o), r, a * math.sin(o)]


def _angle_diff(n: float, s: float) -> float:
    return math.atan2(math.sin(n - s), math.cos(n - s))


def _make_proj(yaw: float, pitch: float, cx: float, cy: float, scale: float):
    sin_p = math.sin(pitch)
    cos_p = math.cos(pitch)
    sin_y = math.sin(yaw)
    cos_y = math.cos(yaw)

    def proj(mx: float, my: float, mz: float) -> tuple[float, float, float]:
        e = mx * cos_y + mz * sin_y
        l = -mx * sin_y + mz * cos_y
        R = my * cos_p - l * sin_p
        w = my * sin_p + l * cos_p
        return (cx + e * scale, cy - R * scale, w)

    return proj


def _finalize_frame(dots: list[dict], lines: list[dict], r_min: float = 0.3) -> dict:
    valid_dots = []
    for d in dots:
        if d.get("a", 1.0) >= 0.02:
            d["r"] = max(r_min, d["r"])
            valid_dots.append(d)
    valid_dots.sort(key=lambda d: d["z"])
    valid_lines = [l for l in lines if l.get("a", 1.0) >= 0.02]
    return {"dots": valid_dots, "lines": valid_lines}


def _radius_scale(n: float, s: float) -> float:
    return (n / 300.0) ** s


# ── Shape outline interpolation for "shaping" (morph) ────────────────────────
def _smooth_step(n: float) -> float:
    return n * n * (3.0 - 2.0 * n)


def _polyline_sampler(pts: list[list[float]]):
    s = len(pts)
    segs = []
    total = 0.0
    for a in range(s):
        p1 = pts[a]
        p2 = pts[(a + 1) % s]
        dist = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        segs.append(dist)
        total += dist

    def sample(t: float) -> list[float]:
        target = t * total
        idx = 0
        while target > segs[idx] and idx < s - 1:
            target -= segs[idx]
            idx += 1
        p1 = pts[idx]
        p2 = pts[(idx + 1) % s]
        frac = min(1.0, target / segs[idx]) if segs[idx] > 0 else 0.0
        return [p1[0] + (p2[0] - p1[0]) * frac, p1[1] + (p2[1] - p1[1]) * frac]

    return sample


_SHAPE_CIRCLE = lambda n: [math.cos(-math.pi / 2.0 + n * 2.0 * math.pi) * 0.24,
                          math.sin(-math.pi / 2.0 + n * 2.0 * math.pi) * 0.24]
_SHAPE_TRIANGLE = _polyline_sampler([[0.0, -0.26], [0.24, 0.16], [-0.24, 0.16]])
_SHAPE_SQUARE = _polyline_sampler([[0.0, -0.2], [0.2, -0.2], [0.2, 0.2], [-0.2, 0.2], [-0.2, -0.2]])
_SHAPES = [_SHAPE_CIRCLE, _SHAPE_TRIANGLE, _SHAPE_SQUARE]


# ── 9 Mode Generators ────────────────────────────────────────────────────────

def _mode_orbits(n: float, s: float, opts: dict) -> dict:
    """working — particles on tilted 3D orbital rings."""
    cx = n / 2.0
    cy = n / 2.0
    rad = n / 2.0 * 0.82
    proj = _make_proj(s * 0.12, 0.3, cx, cy, 1.0)
    rs = _radius_scale(n, opts.get("rsPow", 0.6))
    dots = []
    orbit_n = int(opts.get("orbitN", 12))
    ghost_n = int(opts.get("ghostN", 40))
    particles = int(opts.get("particles", 3))

    for e in range(orbit_n):
        l = _hash_rand(e, 1.7)
        R = _hash_rand(e, 5.2)
        w = _hash_rand(e, 8.9)
        ring_r = rad * (0.45 + 0.52 * l)
        u = l * 2.0 * math.pi
        y = math.acos(2.0 * R - 1.0)
        b = math.sin(y) * math.cos(u)
        f = math.cos(y)
        P = math.sin(y) * math.sin(u)
        x = -f
        g = b
        v = max(1e-6, math.sqrt(x * x + g * g))
        x /= v
        g /= v
        k = f * 0.0 - P * g
        N = P * x - b * 0.0
        z = b * g - f * x
        speed_dir = (0.25 + 0.55 * w) * (1.0 if w > 0.5 else -1.0)

        for B in range(ghost_n):
            angle = B / ghost_n * 2.0 * math.pi
            px, py, pz = proj(
                (x * math.cos(angle) + k * math.sin(angle)) * ring_r,
                (g * math.cos(angle) + N * math.sin(angle)) * ring_r,
                (z * math.sin(angle)) * ring_r
            )
            depth_norm = (pz / ring_r + 1.0) / 2.0
            dots.append({
                "x": px, "y": py, "z": pz,
                "r": opts.get("ghostR", 0.9) * rs,
                "white": 0.72,
                "a": opts.get("ghostA", 0.5) * (0.4 + 0.6 * depth_norm)
            })

        for B in range(particles):
            angle = s * speed_dir + B / particles * 2.0 * math.pi + R * 6.0
            px, py, pz = proj(
                (x * math.cos(angle) + k * math.sin(angle)) * ring_r,
                (g * math.cos(angle) + N * math.sin(angle)) * ring_r,
                (z * math.sin(angle)) * ring_r
            )
            depth_norm = (pz / ring_r + 1.0) / 2.0
            dots.append({
                "x": px, "y": py, "z": pz,
                "r": (opts.get("partR", 1.2) + opts.get("partRDepth", 1.6) * depth_norm) * rs,
                "white": 0.3 - 0.22 * depth_norm,
                "a": 1.0
            })

    return _finalize_frame(dots, [], opts.get("rMin", 0.3))


def _mode_globe(n: float, s: float, opts: dict) -> dict:
    """searching — a scan meridian sweeps a dotted globe."""
    cx = n / 2.0
    cy = n / 2.0
    rad = n / 2.0 * 0.82
    pitch = 0.4 + 0.06 * math.sin(s * 0.35)
    proj = _make_proj(s * 0.5, pitch, cx, cy, rad)
    scan_angle = s * (0.5 + 1.2 * opts.get("scanMul", 1.0))
    rs = _radius_scale(n, opts.get("rsPow", 0.6))
    dim_base = opts.get("dimBase", 1.0)
    dots = []
    lat_rings = int(opts.get("latRings", 17))
    lon_density = int(opts.get("lonDensity", 44))

    for w in range(lat_rings + 1):
        lat = -math.pi / 2.0 + w / lat_rings * math.pi
        cos_lat = math.cos(lat)
        sin_lat = math.sin(lat)
        lon_count = max(1, round(abs(cos_lat) * lon_density))
        for f in range(lon_count):
            lon = f / lon_count * 2.0 * math.pi
            px, py, pz = proj(cos_lat * math.cos(lon), sin_lat, cos_lat * math.sin(lon))
            depth_norm = (pz + 1.0) / 2.0
            dist_to_scan = _angle_diff(lon + s * 0.5, scan_angle)
            scan_intensity = math.exp(-(dist_to_scan * dist_to_scan) / 0.18) * max(0.0, pz)
            dots.append({
                "x": px, "y": py, "z": pz,
                "r": (opts.get("rBase", 0.6) + opts.get("rDepth", 1.7) * depth_norm +
                      opts.get("rBoost", 1.0) * scan_intensity) * rs,
                "white": opts.get("inkFar", 0.62) - opts.get("inkSpan", 0.54) * depth_norm,
                "a": dim_base + (1.0 - dim_base) * min(1.0, scan_intensity)
            })

    return _finalize_frame(dots, [], opts.get("rMin", 0.3))


def _mode_rubik(n: float, s: float, opts: dict) -> dict:
    """solving — bands scramble, then click back solved."""
    cx = n / 2.0
    cy = n / 2.0
    rad = n / 2.0 * 0.82
    pitch = 0.35 + 0.1 * math.sin(s * 0.9)
    proj = _make_proj(s * 0.55, pitch, cx, cy, rad)
    rs = _radius_scale(n, opts.get("rsPow", 0.6))
    dots = []
    lat_rings = int(opts.get("latRings", 15))
    lon_density = int(opts.get("lonDensity", 40))

    # Scramble / solve timing cycle
    move_count = int(opts.get("moveCount", 14))
    period = 2 * move_count * 0.42 + 1.2
    t_mod = s % period
    active_move = -1
    amounts = [0.0] * move_count
    if t_mod < 2 * move_count * 0.42:
        step_idx = math.floor(t_mod / 0.42)
        step_frac = (t_mod - step_idx * 0.42) / 0.42
        smooth_frac = 1.0 - (1.0 - min(1.0, step_frac / 0.7)) ** 3
        if step_idx < move_count:
            for e in range(step_idx):
                amounts[e] = 1.0
            amounts[step_idx] = smooth_frac
            active_move = step_idx
        else:
            e = 2 * move_count - 1 - step_idx
            for l in range(e):
                amounts[l] = 1.0
            amounts[e] = 1.0 - smooth_frac
            active_move = e

    # Generate slice moves
    slices = []
    for idx in range(move_count):
        axis = min(2, math.floor(_hash_rand(idx, 2.3) * 3))
        lo = -1.0 + 0.5 * min(3, math.floor(_hash_rand(idx, 5.9) * 4))
        sign = 1.0 if _hash_rand(idx, 7.7) < 0.5 else -1.0
        slices.append({"axis": axis, "lo": lo, "hi": lo + 0.5, "ang": sign * math.pi / 2.0})

    for R_idx in range(lat_rings + 1):
        lat = -math.pi / 2.0 + R_idx / lat_rings * math.pi
        cos_lat = math.cos(lat)
        sin_lat = math.sin(lat)
        lon_count = max(1, round(abs(cos_lat) * lon_density))
        for b_idx in range(lon_count):
            lon = b_idx / lon_count * 2.0 * math.pi
            rx, ry, rz = cos_lat * math.cos(lon), sin_lat, cos_lat * math.sin(lon)
            is_active = False
            for m_idx in range(len(slices)):
                if amounts[m_idx] <= 0:
                    continue
                sl = slices[m_idx]
                coord = rx if sl["axis"] == 0 else (ry if sl["axis"] == 1 else rz)
                if coord < sl["lo"] or coord >= sl["hi"]:
                    continue
                if m_idx == active_move:
                    is_active = True
                ang = sl["ang"] * amounts[m_idx]
                c_ang = math.cos(ang)
                s_ang = math.sin(ang)
                if sl["axis"] == 0:
                    ry, rz = ry * c_ang - rz * s_ang, ry * s_ang + rz * c_ang
                elif sl["axis"] == 1:
                    rx, rz = rx * c_ang + rz * s_ang, -rx * s_ang + rz * c_ang
                else:
                    rx, ry = rx * c_ang - ry * s_ang, rx * s_ang + ry * c_ang

            px, py, pz = proj(rx, ry, rz)
            depth_norm = (pz + 1.0) / 2.0
            dots.append({
                "x": px, "y": py, "z": pz,
                "r": (opts.get("rBase", 0.6) + opts.get("rDepth", 1.7) * depth_norm +
                      (opts.get("rActive", 0.3) if is_active else 0.0)) * rs,
                "white": opts.get("inkFar", 0.62) - opts.get("inkSpan", 0.54) * depth_norm - (0.14 if is_active else 0.0),
                "a": 1.0
            })

    return _finalize_frame(dots, [], opts.get("rMin", 0.3))


def _mode_wave(n: float, s: float, opts: dict) -> dict:
    """listening — a waveform rolls through concentric rings."""
    cx = n / 2.0
    cy = n / 2.0
    rad = n / 2.0 * 0.874
    proj = _make_proj(s * 0.18, 0.38, cx, cy, 1.0)
    rs = _radius_scale(n, opts.get("rsPow", 0.6))
    dots = []
    rings = int(opts.get("rings", 15))
    lon_density = int(opts.get("lonDensity", 40))

    for p in range(rings + 1):
        lat = -math.pi / 2.0 + p / rings * math.pi
        cos_lat = math.cos(lat)
        sin_lat = math.sin(lat)
        w = 0.62 * math.sin(s * 2.1 - p * 0.52) + 0.38 * math.sin(s * 1.27 + p * 0.83)
        curr_r = rad * (0.88 + 0.105 * w)
        lon_count = max(1, round(abs(cos_lat) * lon_density))
        for y_idx in range(lon_count):
            lon = y_idx / lon_count * 2.0 * math.pi
            px, py, pz = proj(cos_lat * math.cos(lon) * curr_r, sin_lat * curr_r, cos_lat * math.sin(lon) * curr_r)
            depth_norm = (pz / rad + 1.0) / 2.0
            wave_boost = max(0.0, w)
            dots.append({
                "x": px, "y": py, "z": pz,
                "r": (opts.get("rBase", 0.6) + opts.get("rDepth", 1.7) * depth_norm) * (1.0 + 0.4 * wave_boost) * rs,
                "white": 0.66 - 0.56 * depth_norm - 0.1 * wave_boost,
                "a": 1.0
            })

    return _finalize_frame(dots, [], opts.get("rMin", 0.3))


def _mode_web(n: float, s: float, opts: dict) -> dict:
    """connecting — a constellation wires itself."""
    cx = n / 2.0
    cy = n / 2.0
    rad = n / 2.0 * 0.8 * opts.get("spread", 1.0)
    proj = _make_proj(s * 0.12, 0.32, cx, cy, rad)
    rs = _radius_scale(n, opts.get("rsPow", 0.6))
    node_n = int(opts.get("nodeN", 30))
    threshold = opts.get("thr", 0.72)
    node_r = opts.get("nodeR", 1.4)
    depth_r = opts.get("nodeRDepth", 1.8)

    nodes = []
    for i in range(node_n):
        fib = _fibonacci_sphere(i, node_n)
        nx = fib[0] + 0.3 * (_val_noise(i * 0.31 + 9.0, s * 0.24) - 0.5) * 2.0
        ny = fib[1] + 0.3 * (_val_noise(i * 0.53 + 27.0, s * 0.21) - 0.5) * 2.0
        nz = fib[2] + 0.3 * (_val_noise(i * 0.77 + 55.0, s * 0.27) - 0.5) * 2.0
        norm = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
        nodes.append([nx / norm, ny / norm, nz / norm])

    lines = []
    dots = []
    for i in range(node_n):
        for u in range(i + 1, node_n):
            dx = nodes[i][0] - nodes[u][0]
            dy = nodes[i][1] - nodes[u][1]
            dz = nodes[i][2] - nodes[u][2]
            dist = math.sqrt(dx * dx + dy * dy + dz * dz)
            if dist >= threshold:
                continue
            x1, y1, z1 = proj(nodes[i][0], nodes[i][1], nodes[i][2])
            x2, y2, z2 = proj(nodes[u][0], nodes[u][1], nodes[u][2])
            depth_norm = ((z1 + z2) / 2.0 + 1.0) / 2.0
            lines.append({
                "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                "white": 0.42,
                "a": (1.0 - dist / threshold) * (0.3 + 0.55 * depth_norm),
                "w": max(0.6, opts.get("lineW", 0.8) * rs)
            })

    for i in range(node_n):
        px, py, pz = proj(nodes[i][0], nodes[i][1], nodes[i][2])
        depth_norm = (pz + 1.0) / 2.0
        pulse = 1.0 + 0.25 * math.sin(s * 1.4 + i * 2.7)
        dots.append({
            "x": px, "y": py, "z": pz,
            "r": (node_r + depth_r * depth_norm) * pulse * rs,
            "white": 0.55 - 0.45 * depth_norm,
            "a": 1.0
        })

    # Floating signals travelling along links
    signals = int(opts.get("signals", 5))
    for i in range(signals):
        clock_sig = math.floor(s * 0.55 + i * 7.31)
        src = math.floor(_hash_rand(clock_sig, i * 3.1 + 1.7) * node_n)
        dst = math.floor(_hash_rand(clock_sig, i * 5.7 + 4.2) * node_n)
        if src == dst:
            continue
        frac = _fract(s * 0.55 + i * 7.31)
        sx = _lerp(nodes[src][0], nodes[dst][0], frac)
        sy = _lerp(nodes[src][1], nodes[dst][1], frac)
        sz = _lerp(nodes[src][2], nodes[dst][2], frac)
        snorm = math.sqrt(sx * sx + sy * sy + sz * sz) or 1.0
        px, py, pz = proj(sx / snorm, sy / snorm, sz / snorm)
        depth_norm = (pz + 1.0) / 2.0
        dots.append({
            "x": px, "y": py, "z": pz,
            "r": (node_r * 1.5 + depth_r * depth_norm) * rs,
            "white": 0.05,
            "a": 0.5 + 0.5 * depth_norm
        })

    return _finalize_frame(dots, lines, opts.get("rMin", 0.3))


def _mode_braid(n: float, s: float, opts: dict) -> dict:
    """weaving — three strands plait around the sphere."""
    cx = n / 2.0
    cy = n / 2.0
    rad = n / 2.0 * 0.76
    proj = _make_proj(s * 0.4, 0.3, cx, cy, 1.0)
    rs = _radius_scale(n, opts.get("rsPow", 0.6))
    dots = []

    ghost_n = int(opts.get("ghostN", 150))
    for e in range(ghost_n):
        fib = _fibonacci_sphere(e, ghost_n)
        px, py, pz = proj(fib[0] * rad, fib[1] * rad, fib[2] * rad)
        depth_norm = (pz / rad + 1.0) / 2.0
        dots.append({"x": px, "y": py, "z": pz, "r": 0.8 * rs, "white": 0.78, "a": 0.1 + 0.22 * depth_norm})

    strand_n = int(opts.get("strandN", 52))
    turns = opts.get("turns", 3.0)
    for e in range(3):
        phase = e / 3.0 * 2.0 * math.pi
        for r_idx in range(strand_n):
            w = (_fract(r_idx / strand_n + s * 0.045) * 2.0 - 1.0) * 0.96
            lat_r = math.sqrt(max(0.0, 1.0 - w * w))
            fade = min(1.0, (1.0 - abs(w)) / 0.1)
            angle = w * math.pi * turns + phase
            ribbon_wob = 1.0 + 0.075 * math.sin(w * math.pi * turns * 2.0 + phase * 2.0 + s * 0.8)
            curr_r = lat_r * rad * ribbon_wob
            px, py, pz = proj(math.cos(angle) * curr_r, w * rad * ribbon_wob, math.sin(angle) * curr_r)
            depth_norm = (pz / rad + 1.0) / 2.0
            dots.append({
                "x": px, "y": py, "z": pz,
                "r": (opts.get("rBase", 1.2) + opts.get("rDepth", 1.8) * depth_norm) * rs,
                "white": 0.55 - 0.45 * depth_norm,
                "a": fade * (0.45 + 0.55 * depth_norm)
            })

    return _finalize_frame(dots, [], opts.get("rMin", 0.3))


def _mode_ribbon(n: float, s: float, opts: dict) -> dict:
    """composing (or breathing if faceOn) — multi-band sash wave."""
    cx = n / 2.0
    cy = n / 2.0
    rad = n / 2.0 * 0.78
    spin = opts.get("spin", 1.0)
    pitch = 0.3
    proj = _make_proj(s * 0.1 * spin, pitch, cx, cy, 1.0)
    rs = _radius_scale(n, opts.get("rsPow", 0.6))
    dots = []

    ghost_n = int(opts.get("ghostN", 150))
    for z in range(ghost_n):
        fib = _fibonacci_sphere(z, ghost_n)
        px, py, pz = proj(fib[0] * rad, fib[1] * rad, fib[2] * rad)
        depth_norm = (pz / rad + 1.0) / 2.0
        dots.append({"x": px, "y": py, "z": pz, "r": 0.8 * rs, "white": 0.78, "a": 0.1 + 0.22 * depth_norm})

    e = s * 0.24 * spin
    face_on = bool(opts.get("faceOn", 0))
    l = -pitch if face_on else 0.55 + 0.3 * math.sin(s * 0.18) * spin
    cos_e = math.cos(e)
    sin_e = math.sin(e)
    sin_l = math.sin(l)
    cos_l = math.cos(l)

    u = -sin_e * sin_l
    b = cos_e * sin_l
    f = -sin_e * cos_l
    P = sin_e * u - cos_e * b
    x = cos_e * cos_l

    wob = 0.23 * opts.get("wobMul", 1.0)
    base_rad = rad / (1.0 + 0.85 * wob) if face_on else rad
    lanes = int(opts.get("lanes", 5))
    segs = int(opts.get("segs", 88))
    lane_count = max(1, round(lanes * opts.get("bandMul", 1.0)))

    for z in range(lane_count):
        offset = (z - (lane_count - 1) / 2.0) * 0.075
        edge_dist = abs(z - (lane_count - 1) / 2.0) / max(1.0, (lane_count - 1) / 2.0)
        for i in range(segs):
            angle = i / segs * 2.0 * math.pi
            wave_mod = (0.16 * math.sin(angle * 3.0 - s * 1.7 + z * 0.22) +
                        0.07 * math.sin(angle * 5.0 + s * 1.1)) * opts.get("wobMul", 1.0)
            scale_r = 1.0 + wave_mod if face_on else 1.0
            shift = offset if face_on else offset + wave_mod
            q = cos_e * math.cos(angle) + u * math.sin(angle) + f * shift
            F = cos_l * math.sin(angle) + P * shift
            j = sin_e * math.cos(angle) + b * math.sin(angle) + x * shift
            dist = math.sqrt(q * q + F * F + j * j) or 1.0
            curr_r = base_rad * scale_r
            px, py, pz = proj(q / dist * curr_r, F / dist * curr_r, j / dist * curr_r)
            depth_norm = (pz / rad + 1.0) / 2.0
            dots.append({
                "x": px, "y": py, "z": pz,
                "r": (opts.get("rBase", 1.1) + opts.get("rDepth", 1.7) * depth_norm) * (1.0 - 0.25 * edge_dist) * rs,
                "white": 0.52 - 0.44 * depth_norm + 0.18 * edge_dist,
                "a": 0.4 + 0.6 * depth_norm
            })

    return _finalize_frame(dots, [], opts.get("rMin", 0.3))


def _mode_morph(n: float, s: float, opts: dict) -> dict:
    """shaping — morphing geometric outline: circle → triangle → square."""
    shape_count = len(_SHAPES)
    stay_time = 1.4
    morph_time = 0.9
    cycle = stay_time + morph_time
    total_cycle = cycle * shape_count

    t_mod = s % total_cycle
    curr_shape_idx = math.floor(t_mod / cycle)
    frac_in_cycle = t_mod - curr_shape_idx * cycle
    morph_factor = _smooth_step((frac_in_cycle - stay_time) / morph_time) if frac_in_cycle > stay_time else 0.0

    spread = opts.get("spread", 1.0)
    s1 = _SHAPES[curr_shape_idx]
    s2 = _SHAPES[(curr_shape_idx + 1) % shape_count]

    samples = 160
    poly = []
    for x in range(samples):
        g = x / samples
        p1 = s1(g)
        p2 = s2(g)
        poly.append([(p1[0] + (p2[0] - p1[0]) * morph_factor) * spread,
                     (p1[1] + (p2[1] - p1[1]) * morph_factor) * spread])

    segs = []
    total_len = 0.0
    for x in range(samples):
        p1 = poly[x]
        p2 = poly[(x + 1) % samples]
        d = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        segs.append(d)
        total_len += d

    dot_count = max(6, round(34 * opts.get("iconD", 1.0)))
    dot_rad = opts.get("rDot", 0.021) * 1.35 * spread
    pulse = 1.0 + 0.02 * math.sin(frac_in_cycle * 3.1)
    dots = []
    center = n / 2.0

    accum = 0.0
    seg_idx = 0
    for x in range(dot_count):
        target = x / dot_count * total_len
        while accum + segs[seg_idx] < target and seg_idx < samples - 1:
            accum += segs[seg_idx]
            seg_idx += 1
        p1 = poly[seg_idx]
        p2 = poly[(seg_idx + 1) % samples]
        frac = min(1.0, (target - accum) / segs[seg_idx]) if segs[seg_idx] > 0 else 0.0
        nx = (p1[0] + (p2[0] - p1[0]) * frac) * pulse
        ny = (p1[1] + (p2[1] - p1[1]) * frac) * pulse
        dots.append({
            "x": center + nx * n,
            "y": center + ny * n,
            "z": 0.0,
            "r": max(0.35, dot_rad * n),
            "white": 0.1,
            "a": 1.0
        })

    return _finalize_frame(dots, [], opts.get("rMin", 0.25))


# ── Presets & State Mappings ─────────────────────────────────────────────────

_STATE_MAP = {
    "working": "orbits",
    "searching": "globe",
    "solving": "rubik",
    "listening": "wave",
    "connecting": "web",
    "weaving": "braid",
    "composing": "ribbon",
    "breathing": "ring",
    "shaping": "morph"
}

_PRESETS_BASE = {
    "globe": {"latRings": 17, "lonDensity": 44, "rBase": 0.6, "rDepth": 1.7, "rBoost": 1.0, "inkFar": 0.62, "inkSpan": 0.54, "rsPow": 0.6, "rMin": 0.3},
    "orbits": {"orbitN": 12, "ghostN": 40, "ghostR": 0.9, "ghostA": 0.5, "particles": 3, "partR": 1.2, "partRDepth": 1.6, "rsPow": 0.6, "rMin": 0.3},
    "rubik": {"latRings": 15, "lonDensity": 40, "moveCount": 14, "rBase": 0.6, "rDepth": 1.7, "rActive": 0.3, "inkFar": 0.62, "inkSpan": 0.54, "rsPow": 0.6, "rMin": 0.3},
    "wave": {"rings": 15, "lonDensity": 40, "rBase": 0.6, "rDepth": 1.7, "rsPow": 0.6, "rMin": 0.3},
    "web": {"nodeN": 30, "thr": 0.72, "signals": 5, "nodeR": 1.4, "nodeRDepth": 1.8, "lineW": 0.8, "rsPow": 0.6, "rMin": 0.3},
    "braid": {"strandN": 52, "turns": 3.0, "ghostN": 150, "rBase": 1.2, "rDepth": 1.8, "rsPow": 0.6, "rMin": 0.3},
    "ribbon": {"lanes": 5, "segs": 88, "ghostN": 150, "rBase": 1.1, "rDepth": 1.7, "rsPow": 0.6, "rMin": 0.3},
    "ring": {"lanes": 5, "segs": 88, "ghostN": 0, "faceOn": 1, "rBase": 1.1, "rDepth": 1.7, "rsPow": 0.6, "rMin": 0.3},
    "morph": {"rDot": 0.021, "iconD": 1.0, "rMin": 0.25}
}

_TUNING = {
    "orbits": {64: {"speed": 1.885, "count": 1.0, "size": 1.0}, 20: {"speed": 3.9, "count": 0.238, "size": 2.4}},
    "globe": {64: {"speed": 2.015, "count": 0.42, "size": 1.15, "extra": {"scanMul": 4.08, "dimBase": 0.45}}, 20: {"speed": 2.665, "count": 0.105, "size": 1.75, "extra": {"scanMul": 4.335, "dimBase": 0.45}}},
    "rubik": {64: {"speed": 1.82, "count": 0.35, "size": 1.05}, 20: {"speed": 1.95, "count": 0.088, "size": 1.9}},
    "wave": {64: {"speed": 4.388, "count": 0.341, "size": 1.0}, 20: {"speed": 3.998, "count": 0.105, "size": 1.6}},
    "web": {64: {"speed": 3.315, "count": 1.35, "size": 0.95}, 20: {"speed": 6.63, "count": 0.25, "size": 1.52}},
    "braid": {64: {"speed": 1.625, "count": 0.5, "size": 1.0}, 20: {"speed": 2.75, "count": 0.1125, "size": 1.36}},
    "ribbon": {64: {"speed": 2.34, "count": 0.25, "size": 0.85, "extra": {"spin": 0.0, "bandMul": 3.9, "wobMul": 1.0}}, 20: {"speed": 3.12, "count": 0.051, "size": 1.073, "extra": {"spin": 0.0, "bandMul": 4.94, "wobMul": 1.0}}},
    "ring": {64: {"speed": 3.24, "count": 0.25, "size": 0.956, "extra": {"spin": 0.0, "bandMul": 3.627, "wobMul": 0.368}}, 20: {"speed": 3.78, "count": 0.028, "size": 1.622, "extra": {"spin": 0.0, "bandMul": 3.968, "wobMul": 0.565}}},
    "morph": {64: {"speed": 2.405, "count": 0.702, "size": 0.395, "extra": {"spread": 1.45}}, 20: {"speed": 2.08, "count": 0.53, "size": 1.011, "extra": {"spread": 1.45}}}
}

_ENGINES = {
    "orbits": _mode_orbits,
    "globe": _mode_globe,
    "rubik": _mode_rubik,
    "wave": _mode_wave,
    "web": _mode_web,
    "braid": _mode_braid,
    "ribbon": _mode_ribbon,
    "ring": _mode_ribbon,
    "morph": _mode_morph
}


def _resolve_config(state: str, size: int) -> tuple[str, float, dict]:
    mode = _STATE_MAP.get(state, "ring")
    base = dict(_PRESETS_BASE[mode])
    tuning_dict = _TUNING.get(mode, {}).get(size if size in (20, 64) else 64, {"speed": 2.0, "count": 1.0, "size": 1.0})
    speed = tuning_dict.get("speed", 2.0)
    count_mul = tuning_dict.get("count", 1.0)
    size_mul = tuning_dict.get("size", 1.0)

    # Scale density
    sqrt_count = math.sqrt(count_mul)
    for pair in (("latRings", "lonDensity"), ("rings", "lonDensity"), ("lanes", "segs")):
        if pair[0] in base and pair[1] in base:
            base[pair[0]] = max(2, round(base[pair[0]] * sqrt_count))
            base[pair[1]] = max(2, round(base[pair[1]] * sqrt_count))
    for k in ("orbitN", "ghostN", "nodeN", "strandN", "signals"):
        if k in base and base[k] != 0:
            base[k] = max(1, round(base[k] * count_mul))
    if "iconD" in base:
        base["iconD"] = max(0.02, base["iconD"] * count_mul)

    # Scale radii
    for k in ("rBase", "rDepth", "rActive", "rDot", "ghostR", "partR", "partRDepth", "nodeR", "nodeRDepth"):
        if k in base:
            base[k] = base[k] * size_mul

    if "extra" in tuning_dict:
        base.update(tuning_dict["extra"])

    return mode, speed, base


VALID_STATES = {
    "working", "searching", "solving", "listening",
    "connecting", "weaving", "composing", "breathing", "shaping"
}


# ── The ThinkingOrb Qt Component ─────────────────────────────────────────────

class ThinkingOrb(QWidget):
    """Hand-tuned animated thought-orb indicator for AI states.

    Supports 9 states:
        breathing   — gentle morphing ring (idle state)
        working     — particles on tilted 3D orbital rings
        searching   — scanning meridian sweeping a dotted globe
        solving     — rotating bands scrambling and locking
        listening   — undulating acoustic wave through rings
        connecting  — dynamic constellation wiring nodes
        weaving     — 3-strand helical braid revolving around sphere
        composing   — harmonic multi-band sash wave
        shaping     — morphing geometric outline (circle → triangle → square)
    """

    def __init__(self, parent=None, state: str = "breathing", size: int = 64,
                 speed: float = 1.0, dark: bool = False, paused: bool = False):
        super().__init__(parent)
        if state not in VALID_STATES:
            state = "breathing"
        self._state = state
        self._orb_size = size
        self._user_speed = speed
        self._dark = dark
        self._paused = paused
        self._clock = 0.0
        self._last_tick = time.perf_counter()

        self.setFixedSize(QSize(size, size))
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_StyledBackground, False)

        self._mode, self._base_speed, self._opts = _resolve_config(self._state, self._orb_size)

        # 60 FPS animation timer (~16ms)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._on_tick)
        if not self._paused:
            self._timer.start()

    def set_state(self, state: str):
        if state not in VALID_STATES:
            return
        if state != self._state:
            self._state = state
            self._mode, self._base_speed, self._opts = _resolve_config(self._state, self._orb_size)
            self.update()

    def sizeHint(self) -> QSize:
        return QSize(self._orb_size, self._orb_size)

    def minimumSizeHint(self) -> QSize:
        return QSize(self._orb_size, self._orb_size)

    @property
    def state(self) -> str:
        return self._state

    @property
    def size_px(self) -> int:
        return self._orb_size

    @property
    def dark(self) -> bool:
        return self._dark

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def speed(self) -> float:
        return self._user_speed

    def set_speed(self, speed: float):
        self._user_speed = max(0.0, speed)

    def set_dark(self, dark: bool):
        if dark != self._dark:
            self._dark = dark
            self.update()

    def set_paused(self, paused: bool):
        self._paused = paused
        if self._paused:
            self._timer.stop()
        else:
            self._last_tick = time.perf_counter()
            self._timer.start()

    def _on_tick(self):
        now = time.perf_counter()
        dt = min(0.05, now - self._last_tick)
        self._last_tick = now
        self._clock += dt * self._base_speed * self._user_speed
        self.update()

    def render(self, painter: QPainter):
        """Render the current orb frame into any QPainter (widget or offscreen pixmap)."""
        painter.setRenderHint(QPainter.Antialiasing, True)

        engine_fn = _ENGINES.get(self._mode, _mode_ribbon)
        frame = engine_fn(self._orb_size, self._clock, self._opts)

        is_dark = self._dark
        # Paint lines (e.g. in 'connecting' web state)
        if frame.get("lines"):
            for line in frame["lines"]:
                alpha = max(0.0, min(1.0, line.get("a", 1.0)))
                white = max(0.0, min(1.0, line.get("white", 0.5)))
                c_val = round((1.0 - white if is_dark else white) * 255.0)
                pen = QPen(QColor(c_val, c_val, c_val, int(alpha * 255)))
                pen.setWidthF(line.get("w", 0.8))
                painter.setPen(pen)
                painter.drawLine(QPointF(line["x1"], line["y1"]), QPointF(line["x2"], line["y2"]))

        # Paint dots
        painter.setPen(Qt.NoPen)
        for dot in frame.get("dots", []):
            alpha = max(0.0, min(1.0, dot.get("a", 1.0)))
            white = max(0.0, min(1.0, dot.get("white", 0.5)))
            c_val = round((1.0 - white if is_dark else white) * 255.0)
            r = dot.get("r", 1.0)
            painter.setBrush(QColor(c_val, c_val, c_val, int(alpha * 255)))
            painter.drawEllipse(QPointF(dot["x"], dot["y"]), r, r)

    def paintEvent(self, event):
        painter = QPainter(self)
        self.render(painter)
        painter.end()


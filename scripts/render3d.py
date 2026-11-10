"""Deterministic CPU renderer for the concept scheme (no WebGL, no GPU).

Pipeline: perspective camera -> z-buffer triangle rasteriser -> per-pixel
Lambert shading with soft-ish shadows (ray/AABB tests against the scene boxes)
-> filmic tone map. Deliberately small and dependency-free apart from numpy so
the render is reproducible on this machine and can run headless.

This is a *concept* renderer: massing, light and material colour only. It is not
a photoreal engine and is labelled 概念效果图 wherever it is shown.
"""
from __future__ import annotations

import numpy as np


def normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n else v


class Camera:
    def __init__(self, eye, target, fov_deg=60.0, up=(0.0, 0.0, 1.0)):
        self.eye = np.array(eye, dtype=np.float64)
        self.target = np.array(target, dtype=np.float64)
        forward = normalize(self.target - self.eye)
        right = normalize(np.cross(forward, np.array(up, dtype=np.float64)))
        upv = np.cross(right, forward)
        self.basis = np.stack([right, upv, forward])
        self.focal = 1.0 / np.tan(np.radians(fov_deg) / 2.0)

    def to_camera(self, points: np.ndarray) -> np.ndarray:
        rel = points - self.eye
        return rel @ self.basis.T


def box_faces(x0, y0, z0, x1, y1, z1, color, emissive=0.0):
    """Six quads of an axis-aligned box (bottom omitted — never visible)."""
    p = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
    ]
    quads = [
        (0, 3, 7, 4),  # south  -y
        (1, 5, 6, 2),  # north  +y
        (0, 4, 5, 1),  # west   -x
        (3, 2, 6, 7),  # east   +x
        (4, 7, 6, 5),  # top
    ]
    return [([p[a], p[b], p[c], p[d]], color, emissive) for a, b, c, d in quads]


def prism_faces(cx, cy, z0, z1, radius, sides, color, emissive=0.0):
    ring = [(cx + radius * np.cos(2 * np.pi * i / sides),
             cy + radius * np.sin(2 * np.pi * i / sides)) for i in range(sides)]
    faces = []
    for i in range(sides):
        x0, y0 = ring[i]
        x1, y1 = ring[(i + 1) % sides]
        faces.append(([(x0, y0, z0), (x1, y1, z0), (x1, y1, z1), (x0, y0, z1)], color, emissive))
    top = [(x, y, z1) for x, y in ring]
    faces.append((top, color, emissive))
    return faces


def _clip_near(cam: np.ndarray, world: np.ndarray, near: float = 0.15):
    """Sutherland–Hodgman clip of one polygon against the near plane."""
    out_c, out_w = [], []
    count = len(cam)
    for i in range(count):
        a, b = cam[i], cam[(i + 1) % count]
        aw, bw = world[i], world[(i + 1) % count]
        a_in, b_in = a[2] >= near, b[2] >= near
        if a_in:
            out_c.append(a)
            out_w.append(aw)
        if a_in != b_in:
            t = (near - a[2]) / (b[2] - a[2])
            out_c.append(a + t * (b - a))
            out_w.append(aw + t * (bw - aw))
    return out_c, out_w


def rasterize(faces, camera: Camera, width: int, height: int):
    """Return depth, world position, normal and albedo buffers."""
    depth = np.full((height, width), np.inf, dtype=np.float32)
    wpos = np.zeros((height, width, 3), dtype=np.float32)
    normal = np.zeros((height, width, 3), dtype=np.float32)
    albedo = np.zeros((height, width, 3), dtype=np.float32)
    emissive = np.zeros((height, width), dtype=np.float32)
    lit = np.zeros((height, width), dtype=bool)
    f = camera.focal

    for quad, color, emis in faces:
        verts = np.array(quad, dtype=np.float64)
        n = normalize(np.cross(verts[1] - verts[0], verts[-1] - verts[0]))
        cam = camera.to_camera(verts)
        clipped_c, clipped_w = _clip_near(cam, verts)
        if len(clipped_c) < 3:
            continue
        for i in range(1, len(clipped_c) - 1):
            tri_c = [clipped_c[0], clipped_c[i], clipped_c[i + 1]]
            tri_w = [clipped_w[0], clipped_w[i], clipped_w[i + 1]]
            z = np.array([p[2] for p in tri_c])
            sx = (np.array([p[0] for p in tri_c]) / z * f * 0.5 + 0.5) * width
            sy = (0.5 - np.array([p[1] for p in tri_c]) / z * f * 0.5) * height
            screen = np.stack([sx, sy], axis=1)
            minx = max(int(np.floor(screen[:, 0].min())), 0)
            maxx = min(int(np.ceil(screen[:, 0].max())), width - 1)
            miny = max(int(np.floor(screen[:, 1].min())), 0)
            maxy = min(int(np.ceil(screen[:, 1].max())), height - 1)
            if minx > maxx or miny > maxy:
                continue
            xs = np.arange(minx, maxx + 1) + 0.5
            ys = np.arange(miny, maxy + 1) + 0.5
            gx, gy = np.meshgrid(xs, ys)
            ax, ay = screen[0]
            bx, by = screen[1]
            cx, cy = screen[2]
            area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
            if abs(area) < 1e-9:
                continue
            w0 = ((bx - gx) * (cy - gy) - (by - gy) * (cx - gx)) / area
            w1 = ((cx - gx) * (ay - gy) - (cy - gy) * (ax - gx)) / area
            w2 = 1.0 - w0 - w1
            mask = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
            if not mask.any():
                continue
            inv = w0 / z[0] + w1 / z[1] + w2 / z[2]
            with np.errstate(divide="ignore"):
                pz = 1.0 / inv
            block = depth[miny:maxy + 1, minx:maxx + 1]
            better = mask & (pz < block)
            if not better.any():
                continue
            block[better] = pz[better]
            b0, b1, b2 = (w0 / z[0])[better], (w1 / z[1])[better], (w2 / z[2])[better]
            total = b0 + b1 + b2
            pos = (np.outer(b0 / total, tri_w[0]) + np.outer(b1 / total, tri_w[1])
                   + np.outer(b2 / total, tri_w[2]))
            wpos[miny:maxy + 1, minx:maxx + 1][better] = pos.astype(np.float32)
            normal[miny:maxy + 1, minx:maxx + 1][better] = n.astype(np.float32)
            albedo[miny:maxy + 1, minx:maxx + 1][better] = np.array(color, dtype=np.float32)
            emissive[miny:maxy + 1, minx:maxx + 1][better] = emis
            lit[miny:maxy + 1, minx:maxx + 1][better] = True
    return depth, wpos, normal, albedo, emissive, lit


def _occluded(origin: np.ndarray, target: np.ndarray, boxes) -> np.ndarray:
    """Ray/AABB slab test, vectorised over rays (origin Nx3, one target)."""
    direction = target - origin
    dist = np.linalg.norm(direction, axis=1)
    direction = direction / dist[:, None]
    hit = np.zeros(len(origin), dtype=bool)
    for (x0, y0, z0, x1, y1, z1) in boxes:
        lo = np.array([x0, y0, z0]) - origin
        hi = np.array([x1, y1, z1]) - origin
        with np.errstate(divide="ignore", invalid="ignore"):
            t1 = lo / direction
            t2 = hi / direction
        tmin = np.nanmax(np.minimum(t1, t2), axis=1)
        tmax = np.nanmin(np.maximum(t1, t2), axis=1)
        hit |= (tmax >= np.maximum(tmin, 0.0)) & (tmin > 0.02) & (tmin < dist - 0.05)
    return hit


def render(faces, boxes, camera: Camera, width: int, height: int, *, supersample: int = 2,
           lights=None, ambient=(0.34, 0.35, 0.38), exposure=1.0):
    rw, rh = width * supersample, height * supersample
    depth, wpos, normal, albedo, emissive, lit = rasterize(faces, camera, rw, rh)

    # two-sided shading: flip normals towards the camera (interior surfaces)
    to_eye = camera.eye[None, None, :] - wpos
    flip = np.einsum("ijk,ijk->ij", normal, to_eye) < 0
    normal[flip] *= -1

    # large-format floor joints (1.8 m grid) — keeps the floor from reading plastic
    floor = (normal[..., 2] > 0.9) & (np.abs(wpos[..., 2]) < 2.0) & lit
    if floor.any():
        seam = (np.mod(wpos[..., 0], 1800.0) < 22.0) | (np.mod(wpos[..., 1], 1800.0) < 22.0)
        albedo[floor & seam] *= 0.78

    # procedural grain on timber surfaces (subtle, breaks up flat fills)
    warm = (albedo[..., 0] > albedo[..., 2] + 0.10) & (albedo[..., 0] < 0.86) & lit
    if warm.any():
        grain = 0.975 + 0.025 * np.sin(wpos[..., 1] * 2.6 + 1.6 * np.sin(wpos[..., 0] * 0.13))
        albedo[warm] *= grain[warm][:, None]

    # material saturation: the filmic curve compresses colour, so lift it first
    grey0 = albedo.mean(axis=2, keepdims=True)
    albedo = np.clip(grey0 + (albedo - grey0) * 1.55, 0.0, 1.0)

    shade = np.zeros((rh, rw, 3), dtype=np.float32)
    amb = np.array(ambient, dtype=np.float32)
    shade += albedo * amb

    for light in lights or []:
        if light.get("window_sun"):
            # Sunlight only enters through the glazing: intersect the wall plane,
            # accept the ray only inside a window band, then occlude normally.
            axis = light["axis"]
            other = 1 if axis == 0 else 0
            direction = np.array(light["dir"], dtype=np.float32)
            direction = direction / np.linalg.norm(direction)
            to_wall = -direction
            with np.errstate(divide="ignore", invalid="ignore"):
                t = (light["wall"] - wpos[..., axis]) / to_wall[axis]
            hit = wpos + to_wall * t[..., None]
            inside = (t > 0) & (hit[..., 2] >= light["z0"]) & (hit[..., 2] <= light["z1"])
            band = np.zeros_like(inside)
            for lo, hi in light["bands"]:
                band |= (hit[..., other] >= lo) & (hit[..., other] <= hi)
            inside &= band
            ndotl = np.clip(np.einsum("ijk,k->ij", normal, to_wall), 0.0, 1.0)
            colour = np.array(light["color"], dtype=np.float32) * light["power"]
            inside_f = inside.astype(np.float32)
            pad_i = np.pad(inside_f, 2, mode="edge")
            acc_i = np.zeros_like(inside_f)
            for dy in range(5):
                for dx in range(5):
                    acc_i += pad_i[dy:dy + rh, dx:dx + rw]
            inside_f = acc_i / 25.0
            contribution = ndotl[..., None] * colour * inside_f[..., None]
            step = 3
            sm_h, sm_w = (rh + step - 1) // step, (rw + step - 1) // step
            sm = np.ones((sm_h, sm_w), dtype=np.float32)
            oy, ox = np.nonzero((ndotl[::step, ::step] > 0.02) & lit[::step, ::step] & inside[::step, ::step])
            if len(oy):
                origin = wpos[oy * step, ox * step] + normal[oy * step, ox * step] * 0.02
                target = hit[oy * step, ox * step]
                keep = np.linalg.norm(target - origin, axis=1) > 0.05
                blocked = np.zeros(len(oy), dtype=bool)
                if keep.any():
                    blocked[keep] = _occluded(origin[keep].astype(np.float64),
                                              target[keep], light.get("occluders", boxes))
                sm[oy[blocked], ox[blocked]] = 0.0
            mask = np.kron(sm, np.ones((step, step), dtype=np.float32))[:rh, :rw]
            pad = np.pad(mask, 1, mode="edge")
            smooth = (pad[:-2, :-2] + pad[:-2, 1:-1] + pad[:-2, 2:]
                      + pad[1:-1, :-2] + pad[1:-1, 1:-1] + pad[1:-1, 2:]
                      + pad[2:, :-2] + pad[2:, 1:-1] + pad[2:, 2:]) / 9.0
            shade += albedo * contribution * smooth[..., None]
            continue

        if light.get("sun"):
            direction = np.broadcast_to(np.array(light["dir"], dtype=np.float32), wpos.shape).astype(np.float32)
            direction = direction / np.linalg.norm(direction, axis=-1, keepdims=True)
            colour = np.array(light["color"], dtype=np.float32) * light["power"]
            ndotl = np.clip(np.einsum("ijk,ijk->ij", normal, -direction), 0.0, 1.0)
            contribution = ndotl[..., None] * colour
            step = 3
            sm_h, sm_w = (rh + step - 1) // step, (rw + step - 1) // step
            sm = np.ones((sm_h, sm_w), dtype=np.float32)
            oy, ox = np.nonzero((ndotl[::step, ::step] > 0.02) & lit[::step, ::step])
            if len(oy):
                origin = wpos[oy * step, ox * step] + normal[oy * step, ox * step] * 0.02
                target = origin - np.array(light["dir"], dtype=np.float64) * 60.0
                blocked = _occluded(origin.astype(np.float64), target,
                                    light.get("occluders", boxes))
                sm[oy[blocked], ox[blocked]] = 0.0
            mask = np.kron(sm, np.ones((step, step), dtype=np.float32))[:rh, :rw]
            pad = np.pad(mask, 1, mode="edge")
            smooth = (pad[:-2, :-2] + pad[:-2, 1:-1] + pad[:-2, 2:]
                      + pad[1:-1, :-2] + pad[1:-1, 1:-1] + pad[1:-1, 2:]
                      + pad[2:, :-2] + pad[2:, 1:-1] + pad[2:, 2:]) / 9.0
            shade += albedo * contribution * smooth[..., None]
            continue

        pos = np.array(light["pos"], dtype=np.float32)
        colour = np.array(light["color"], dtype=np.float32) * light["power"]
        radius = light.get("radius", 6.0)
        to_light = pos - wpos
        dist2 = np.einsum("ijk,ijk->ij", to_light, to_light)
        dist = np.sqrt(np.maximum(dist2, 1e-6))
        direction = to_light / dist[..., None]
        ndotl = np.clip(np.einsum("ijk,ijk->ij", normal, direction), 0.0, 1.0)
        atten = 1.0 / (1.0 + dist2 / (radius * radius))
        contribution = (ndotl * atten)[..., None] * colour
        # shadow pass on a subsampled grid (upsampled + blurred afterwards)
        step = 3
        sm_h, sm_w = (rh + step - 1) // step, (rw + step - 1) // step
        sm = np.ones((sm_h, sm_w), dtype=np.float32)
        oy, ox = np.nonzero((ndotl[::step, ::step] > 0.02) & lit[::step, ::step])
        if len(oy):
            origin = wpos[oy * step, ox * step] + normal[oy * step, ox * step] * 0.02
            blocked = _occluded(origin.astype(np.float64), pos.astype(np.float64), boxes)
            sm[oy[blocked], ox[blocked]] = 0.0
        mask = np.kron(sm, np.ones((step, step), dtype=np.float32))[:rh, :rw]
        k = 5
        pad = np.pad(mask, k // 2, mode="edge")
        smooth = np.zeros_like(mask)
        for dy in range(k):
            for dx in range(k):
                smooth += pad[dy:dy + rh, dx:dx + rw]
        smooth /= k * k
        contribution *= smooth[..., None]
        shade += albedo * contribution

    # contact darkening at the floor line — cheap stand-in for ambient occlusion
    near_floor = (normal[..., 2] < 0.4) & (wpos[..., 2] < 700) & lit
    if near_floor.any():
        shade[near_floor] *= 0.86

    # screen-space contact occlusion: darken surfaces that sit next to closer geometry
    if lit.any():
        d = depth.copy()
        d[~np.isfinite(d)] = 0.0
        pad = np.pad(d, 6, mode="edge")
        acc = np.zeros_like(d)
        for dy in range(13):
            for dx in range(13):
                acc += pad[dy:dy + rh, dx:dx + rw]
        acc /= 169.0
        delta = np.clip((d - acc) / np.maximum(acc * 0.05, 1e-3), 0.0, 1.0)
        shade *= (1.0 - 0.55 * delta)[..., None]

    shade += albedo * np.array([0.05, 0.045, 0.04], dtype=np.float32) * (wpos[..., 2:3] > 0)
    shade += emissive[..., None] * np.array([1.0, 0.92, 0.80], dtype=np.float32) * 2.2

    # sky-ish background where nothing was hit
    if (~lit).any():
        rows = np.arange(rh, dtype=np.float32)[:, None, None]
        bg = 0.78 + 0.16 * (1.0 - rows / rh)
        sky = np.broadcast_to(np.array([0.86, 0.89, 0.92], dtype=np.float32), (rh, rw, 3)) * bg
        shade[~lit] = sky[~lit]

    shade *= exposure
    toned = shade / (1.0 + shade)
    toned = np.power(np.clip(toned, 0.0, 1.0), 1 / 2.2)

    # gentle bloom around the glazing / light fixtures
    lum = toned.mean(axis=2)
    bright = np.clip((lum - 0.72) / 0.28, 0.0, 1.0)[..., None] * toned
    bh, bw = (rh // 4) * 4, (rw // 4) * 4
    small = bright[:bh, :bw].reshape(bh // 4, 4, bw // 4, 4, 3).mean(axis=(1, 3))
    pad = np.pad(small, ((3, 3), (3, 3), (0, 0)), mode="edge")
    glow = np.zeros_like(small)
    for dy in range(7):
        for dx in range(7):
            glow += pad[dy:dy + small.shape[0], dx:dx + small.shape[1]]
    glow /= 49.0
    glow = np.repeat(np.repeat(glow, 4, axis=0), 4, axis=1)
    glow = np.pad(glow, ((0, rh - glow.shape[0]), (0, rw - glow.shape[1]), (0, 0)), mode="edge")
    toned = np.clip(toned + glow * 0.55, 0.0, 1.0)

    # keep material colour from collapsing to grey after the filmic curve
    grey = toned.mean(axis=2, keepdims=True)
    toned = np.clip(grey + (toned - grey) * 1.35, 0.0, 1.0)

    if supersample > 1:
        toned = toned.reshape(height, supersample, width, supersample, 3).mean(axis=(1, 3))
    return (np.clip(toned, 0, 1) * 255).astype(np.uint8)


def save_png(array: np.ndarray, path) -> None:
    """Minimal PNG writer (no Pillow dependency in this venv)."""
    import struct
    import zlib

    h, w, _ = array.shape
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        raw.extend(array[y].tobytes())

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
           + chunk(b"IEND", b""))
    with open(path, "wb") as handle:
        handle.write(png)

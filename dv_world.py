"""DREAM VINE - seeded chunked world: generation, storage, saving and face-culled meshing. (c)2026 EX Inc."""
import json, os, zlib
import numpy as np
import dv_blocks as bl
from dv_noise import Noise

CS = 16          # chunk size (x, y)
H = 128          # world height (z)
SEA = 34


def _hash01(x, y, seed, salt=0):
    x = np.asarray(x, np.int64) & 0xFFFFFFFF
    y = np.asarray(y, np.int64) & 0xFFFFFFFF
    h = (x * 374761393 + y * 668265263 + (seed + salt * 9973) * 144665) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    h = h ^ (h >> 16)
    return (h & 0xFFFFFF) / float(0x1000000)


class World:
    def __init__(self, seed, save_dir=None):
        self.seed = int(seed)
        self.n = Noise(self.seed)
        self.n2 = Noise(self.seed + 1)
        self.n3 = Noise(self.seed + 2)
        self.chunks = {}
        self.modified = set()
        self.save_dir = save_dir
        if save_dir:
            os.makedirs(os.path.join(save_dir, "chunks"), exist_ok=True)

    # ------------------------------------------------------------------ terrain
    def height(self, X, Y):
        n = self.n
        cont = n.fbm2(X / 260.0, Y / 260.0, 3)
        hills = n.fbm2(X / 64.0, Y / 64.0, 4)
        mnt = np.maximum(0, n.fbm2(X / 150.0 + 40, Y / 150.0 - 40, 3) + 0.05) ** 1.6 * 70
        h = 38 + cont * 18 + hills * 7 + mnt
        return np.clip(h, 6, H - 20).astype(np.int32)

    def generate(self, cx, cy):
        M = 3
        xs = np.arange(cx * CS - M, cx * CS + CS + M)
        ys = np.arange(cy * CS - M, cy * CS + CS + M)
        X, Y = np.meshgrid(xs, ys, indexing="ij")
        hh = self.height(X, Y)
        h = hh[M:M + CS, M:M + CS]
        c = np.zeros((CS, CS, H), np.uint8)
        z = np.arange(H)[None, None, :]
        hz = h[..., None]
        c[z <= hz] = bl.STONE
        beach = (h <= SEA + 1)
        dirt_band = (z > hz - 4) & (z < hz)
        top = z == hz
        c[dirt_band & ~beach[..., None]] = bl.DIRT
        c[top & ~beach[..., None]] = bl.GRASS
        deep = (h < SEA - 4)[..., None]
        c[(dirt_band | top) & beach[..., None] & ~deep] = bl.SAND
        c[(dirt_band | top) & deep] = bl.GRAVEL
        c[(z > hz) & (z <= SEA)] = bl.WATER
        # caves: "spaghetti" tunnels where two 3D noises are both near zero
        zmax = int(h.max()) + 1
        Xc, Yc, Zc = np.meshgrid(xs[M:M + CS], ys[M:M + CS], np.arange(zmax), indexing="ij")
        a = self.n2.noise3(Xc / 32.0, Yc / 32.0, Zc / 22.0)
        b = self.n3.noise3(Xc / 32.0 + 50, Yc / 32.0, Zc / 22.0)
        cave = (np.abs(a) < 0.075) & (np.abs(b) < 0.075) & (Zc > 4)
        cave &= ~((Zc >= hh[M:M + CS, M:M + CS, None] - 2) & (hh[M:M + CS, M:M + CS, None] <= SEA + 2))  # keep sea floors sealed
        sub = c[:, :, :zmax]
        sub[cave & (sub != bl.WATER)] = bl.AIR
        # ores (random veins inside stone)
        rng = np.random.RandomState((self.seed * 31 + cx * 7919 + cy * 104729) & 0x7FFFFFFF)
        for ore, veins, zmax_o, size in ((bl.COAL_ORE, 18, 90, 7), (bl.IRON_ORE, 12, 60, 5), (bl.GOLD_ORE, 3, 32, 4),
                                         (bl.DIAMOND_ORE, 2, 16, 4)):
            for _ in range(veins):
                x, y, zz = rng.randint(0, CS), rng.randint(0, CS), rng.randint(2, zmax_o)
                for _ in range(size):
                    if c[x, y, zz] == bl.STONE:
                        c[x, y, zz] = ore
                    x = min(CS - 1, max(0, x + rng.randint(-1, 2))); y = min(CS - 1, max(0, y + rng.randint(-1, 2)))
                    zz = min(H - 1, max(1, zz + rng.randint(-1, 2)))
        # bedrock
        c[:, :, 0] = bl.BEDROCK
        br = _hash01(X[M:M + CS, M:M + CS], Y[M:M + CS, M:M + CS], self.seed, 5)
        c[:, :, 1][br < 0.6] = bl.BEDROCK
        c[:, :, 2][br < 0.25] = bl.BEDROCK
        # trees (decided per column over a margin, so trees crossing chunk borders stay whole)
        t = _hash01(X, Y, self.seed, 1)
        forest = self.n.fbm2(X / 90.0 + 300, Y / 90.0, 2)
        pt = 0.004 + np.clip(forest, 0, 1) * 0.05
        cand = (t < pt) & (hh > SEA + 1)
        # 1.4.0 autumn: low-frequency "Autumn Forest" regions where most trees turn; elsewhere a mix of green and autumn
        aut = self.n2.fbm2(X / 200.0 - 700, Y / 200.0 + 300, 2)
        autumn_trees = []
        for i, j in zip(*np.nonzero(cand)):
            gx, gy = i - M, j - M
            base = int(hh[i, j])
            if 0 <= gx < CS and 0 <= gy < CS and c[gx, gy, base] != bl.GRASS:
                continue
            th = 4 + int(_hash01(X[i, j], Y[i, j], self.seed, 2) * 3)
            ah = _hash01(X[i, j], Y[i, j], self.seed, 3)
            share = 0.85 if aut[i, j] > 0.12 else 0.35
            pal = None
            if ah < share:
                k = int(_hash01(X[i, j], Y[i, j], self.seed, 4) * 100)
                main = bl.AUTUMN_ORANGE if k < 36 else bl.AUTUMN_GOLD if k < 66 else bl.AUTUMN_RED if k < 90 else bl.AUTUMN_BROWN
                pal = (main, int(X[i, j]), int(Y[i, j]))
            self._tree(c, gx, gy, base + 1, th, pal)
            if pal is not None:
                autumn_trees.append((gx, gy, int(X[i, j]), int(Y[i, j])))
        # fallen leaves under autumn trees: leaf-covered grass carpets + the odd leaf pile (order independent, so
        # trees whose litter crosses a chunk border look identical on both sides)
        for gx, gy, wx, wy in autumn_trees:
            for dx in range(-3, 4):
                for dy in range(-3, 4):
                    lx, ly = gx + dx, gy + dy
                    d2 = dx * dx + dy * dy
                    if not (0 <= lx < CS and 0 <= ly < CS) or d2 == 0 or d2 > 10:
                        continue
                    hz = int(h[lx, ly])
                    if c[lx, ly, hz] not in (bl.GRASS, bl.LEAF_LITTER):
                        continue
                    r = _hash01(wx + dx, wy + dy, self.seed, 6)
                    if r < 0.85 - 0.07 * d2:
                        c[lx, ly, hz] = bl.LEAF_LITTER
                    if d2 >= 4 and hz + 1 < H and c[lx, ly, hz + 1] == bl.AIR and \
                            _hash01(wx * 3 + dx, wy * 5 + dy, self.seed, 7) < 0.035:
                        c[lx, ly, hz + 1] = bl.LEAF_PILE
        return c

    def _leaf(self, pal, wx, wy, z):
        if pal is None:
            return bl.LEAVES
        u = ((wx * 73856093) ^ (wy * 19349663) ^ (z * 83492791) ^ self.seed) & 0xFFFF
        if u % 100 < 70:
            return pal[0]
        return bl.AUTUMN_LEAVES[(u >> 7) % 4]

    def _tree(self, c, x, y, z0, th, pal=None):
        top = z0 + th
        for dz in range(-3, 2):
            r = 2 if dz < 0 else 1
            zz = top + dz
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    if r == 2 and abs(dx) == 2 and abs(dy) == 2 and (dz == -1 or (dx + dy + zz) % 2):
                        continue
                    if dz == 1 and abs(dx) + abs(dy) > 1:
                        continue
                    X, Y = x + dx, y + dy
                    if 0 <= X < CS and 0 <= Y < CS and 0 <= zz < H and c[X, Y, zz] == bl.AIR:
                        c[X, Y, zz] = bl.LEAVES if pal is None else self._leaf(pal, pal[1] + dx, pal[2] + dy, zz)
        if 0 <= x < CS and 0 <= y < CS:
            for zz in range(z0, min(H, top)):
                c[x, y, zz] = bl.LOG
            c[x, y, z0 - 1] = bl.DIRT

    def surface_z(self, x, y):
        c = self.chunks.get((x // CS, y // CS))
        if c is None:
            return int(self.height(np.array([x]), np.array([y]))[0]) + 1
        col = c[x % CS, y % CS]
        nz = np.nonzero(bl.SOLID[col])[0]
        return int(nz.max()) + 1 if len(nz) else SEA + 1

    # ------------------------------------------------------------------ storage
    def _path(self, cx, cy):
        return os.path.join(self.save_dir, "chunks", "c_%d_%d.bin" % (cx, cy))

    def ensure(self, cx, cy):
        k = (cx, cy)
        if k in self.chunks:
            return self.chunks[k]
        c = None
        if self.save_dir and os.path.exists(self._path(cx, cy)):
            try:
                c = np.frombuffer(zlib.decompress(open(self._path(cx, cy), "rb").read()), np.uint8).reshape(CS, CS, H).copy()
                self.modified.add(k)
            except Exception:
                c = None
        if c is None:
            c = self.generate(cx, cy)
        self.chunks[k] = c
        return c

    def unload(self, k):
        if k in self.modified and self.save_dir:
            self.save_chunk(k)
            self.modified.discard(k)
        self.chunks.pop(k, None)

    def save_chunk(self, k):
        if self.save_dir and k in self.chunks:
            open(self._path(*k), "wb").write(zlib.compress(self.chunks[k].tobytes(), 6))

    def save_all(self):
        for k in list(self.modified):
            self.save_chunk(k)

    def get(self, x, y, z, missing=bl.AIR):
        if z < 0:
            return bl.BEDROCK
        if z >= H:
            return bl.AIR
        c = self.chunks.get((x // CS, y // CS))
        if c is None:
            return missing
        return int(c[x % CS, y % CS, z])

    def set(self, x, y, z, b):
        if not (0 <= z < H):
            return False
        k = (x // CS, y // CS)
        c = self.chunks.get(k)
        if c is None:
            return False
        c[x % CS, y % CS, z] = b
        self.modified.add(k)
        return True


# ----------------------------------------------------------------------------- meshing
# corner offsets per face (CCW seen from outside), face order +X -X +Y -Y +Z -Z
FACES = np.array([
    [(1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)],
    [(0, 1, 0), (0, 0, 0), (0, 0, 1), (0, 1, 1)],
    [(1, 1, 0), (0, 1, 0), (0, 1, 1), (1, 1, 1)],
    [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)],
    [(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)],
    [(1, 0, 0), (0, 0, 0), (0, 1, 0), (1, 1, 0)],
], np.float32)
DIRS = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]
SHADE = np.array([0.80, 0.80, 0.66, 0.66, 1.0, 0.52], np.float32)
CORNER_UV = np.array([(0, 0), (1, 0), (1, 1), (0, 1)], np.float32)
VDT = np.dtype([("p", np.float32, 3), ("t", np.float32, 2), ("c", np.uint8, 4)])
_UV = np.array([bl.tile_uv(t) for t in range(bl.ATLAS_N * bl.ATLAS_N)], np.float32)
INSET = 0.0008


def padded(world, cx, cy):
    P = np.zeros((CS + 2, CS + 2, H + 2), np.uint8)
    P[:, :, 0] = bl.BEDROCK
    P[1:-1, 1:-1, 1:-1] = world.chunks[(cx, cy)]
    for (dx, dy), (sx, sy, tx, ty) in {(1, 0): (0, slice(None), -1, slice(1, -1)), (-1, 0): (-1, slice(None), 0, slice(1, -1)),
                                         (0, 1): (slice(None), 0, slice(1, -1), -1), (0, -1): (slice(None), -1, slice(1, -1), 0)}.items():
        n = world.chunks.get((cx + dx, cy + dy))
        if n is None:
            P[tx, ty, 1:-1] = bl.STONE
        else:
            P[tx, ty, 1:-1] = n[sx, sy]
    return P


def build_mesh(world, cx, cy):
    """Returns ((vertices, indices) solid, (vertices, indices) water) as numpy arrays (VDT / uint32)."""
    P = padded(world, cx, cy)
    cur = P[1:-1, 1:-1, 1:-1]
    opq = bl.OPAQUE[P]
    tops = np.where(opq.any(2), H + 1 - np.argmax(opq[:, :, ::-1], axis=2), 0)  # highest opaque (padded z index)
    out = {"s": [], "w": []}
    water_above = np.zeros_like(cur, bool)
    water_above[:, :, :-1] = cur[:, :, 1:] == bl.WATER
    for d, (dx, dy, dz) in enumerate(DIRS):
        nb = P[1 + dx:CS + 1 + dx, 1 + dy:CS + 1 + dy, 1 + dz:H + 1 + dz]
        nb_op = bl.OPAQUE[nb]
        solid_vis = (cur != bl.AIR) & (cur != bl.WATER) & ~nb_op & ~((nb == cur) & bl.SELFCULL[cur])
        water_vis = (cur == bl.WATER) & (nb != bl.WATER) & ~nb_op
        for key, vis in (("s", solid_vis), ("w", water_vis)):
            idx = np.nonzero(vis)
            n = len(idx[0])
            if not n:
                continue
            bx, by, bz = idx
            blk = cur[idx]
            # sky light: lit if the cell the face looks into is above the column's highest opaque block
            nx, ny, nz = bx + 1 + dx, by + 1 + dy, bz + 1 + dz
            depth = tops[nx, ny] - nz
            light = np.where(depth < 0, 1.0, np.maximum(0.28, 0.82 - 0.06 * depth)).astype(np.float32)
            col = np.clip(SHADE[d] * light * 255, 0, 255).astype(np.uint8)
            pos = np.stack([bx, by, bz], 1).astype(np.float32)[:, None, :] + FACES[d][None]
            if key == "w":
                topface = ~water_above[idx]
                if d == 4:
                    pos[topface, :, 2] -= 0.12
                elif d < 4:
                    m = topface[:, None] & (FACES[d][None, :, 2] > 0.5)
                    pos[..., 2] -= 0.12 * m
            uv = _UV[bl.FACE_TILE[blk, d]]
            u = uv[:, 0:1] + INSET + CORNER_UV[None, :, 0] * (uv[:, 2:3] - uv[:, 0:1] - 2 * INSET)
            v = uv[:, 1:2] + INSET + CORNER_UV[None, :, 1] * (uv[:, 3:4] - uv[:, 1:2] - 2 * INSET)
            vt = np.empty((n, 4), VDT)
            vt["p"] = pos
            vt["t"] = np.stack([u, v], 2)
            vt["c"][..., 0] = col[:, None]; vt["c"][..., 1] = col[:, None]; vt["c"][..., 2] = col[:, None]
            vt["c"][..., 3] = 255
            out[key].append(vt.reshape(-1))
    res = []
    for key in ("s", "w"):
        if out[key]:
            v = np.concatenate(out[key])
            q = len(v) // 4
            base = (np.arange(q, dtype=np.uint32) * 4)[:, None]
            i = (base + np.array([0, 1, 2, 0, 2, 3], np.uint32)[None]).reshape(-1)
            res.append((v, i))
        else:
            res.append(None)
    return res[0], res[1]

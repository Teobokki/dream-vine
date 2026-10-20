"""VINE BUILD - "Vine AI", the offline building generator for DREAM VINE Creative mode.
(c)2026 EX Inc./HYPERION DIGITAL (c)2026 - all code original.

How it works (fully offline, no network, no API key):
  1. interpret(text)  - a small rule-based parser turns a free-text request ("huge 5 tier japanese temple with
                        cherry trees and a moat") into a Plan: building kind, size modifiers, materials/colours and
                        extra features.
  2. generate(plan)   - a library of parametric generators draws the building into a Canvas (a dict of
                        (x, y, z) -> block id) in local coordinates: x = right, y = depth (front faces -y, towards
                        the player), z = up, z = 0 is the first layer above the ground, negative z digs into it.
  3. The game rotates/places the canvas in front of the player (see dv_game.Game.vine_build).

Plugging in an online AI later: write a function with the same contract as interpret() (text -> Plan) that asks a
language model to fill the Plan fields (kind, scale, height, tiers, mats, features) as JSON, or have the model
return a list of primitive drawing calls (box/hollow/cyl/roof...) that are executed on a Canvas.  Keep this offline
generator as the fallback whenever the network or the service is unavailable.  No network AI is shipped.
"""
import math, random, re, zlib
import dv_blocks as bl

MAX_DIM = 64
AIR = bl.AIR


# ============================================================================ canvas + drawing primitives
class Canvas:
    def __init__(self):
        self.b = {}

    def put(self, x, y, z, b):
        self.b[(int(x), int(y), int(z))] = b

    def soft(self, x, y, z, b):          # only if nothing (or air) is there yet
        k = (int(x), int(y), int(z))
        if self.b.get(k, AIR) == AIR:
            self.b[k] = b

    def get(self, x, y, z):
        return self.b.get((x, y, z))

    def box(self, x0, x1, y0, y1, z0, z1, b):
        for x in range(min(x0, x1), max(x0, x1) + 1):
            for y in range(min(y0, y1), max(y0, y1) + 1):
                for z in range(min(z0, z1), max(z0, z1) + 1):
                    self.b[(x, y, z)] = b

    def hollow(self, x0, x1, y0, y1, z0, z1, b, inner=AIR):
        for z in range(z0, z1 + 1):
            for x in range(x0, x1 + 1):
                for y in range(y0, y1 + 1):
                    edge = x in (x0, x1) or y in (y0, y1)
                    self.b[(x, y, z)] = b if edge else inner

    def ring(self, x0, x1, y0, y1, z, b):
        for x in range(x0, x1 + 1):
            self.b[(x, y0, z)] = b; self.b[(x, y1, z)] = b
        for y in range(y0, y1 + 1):
            self.b[(x0, y, z)] = b; self.b[(x1, y, z)] = b

    def cyl(self, cx, cy, r, z0, z1, b, hollow=False, inner=AIR):
        R = int(math.ceil(r))
        for x in range(-R, R + 1):
            for y in range(-R, R + 1):
                d = math.hypot(x, y)
                if d <= r + 0.35:
                    edge = d > r - 0.75
                    for z in range(z0, z1 + 1):
                        self.b[(cx + x, cy + y, z)] = b if (edge or not hollow) else inner

    def dome(self, cx, cy, cz, r, b, hollow=True, inner=AIR, squash=1.0):
        R = int(math.ceil(r))
        for x in range(-R, R + 1):
            for y in range(-R, R + 1):
                for z in range(0, int(math.ceil(r * squash)) + 1):
                    d = math.sqrt(x * x + y * y + (z / squash) ** 2)
                    if d <= r + 0.3:
                        edge = d > r - 0.9
                        self.b[(cx + x, cy + y, cz + z)] = b if (edge or not hollow) else inner

    def line(self, x0, y0, z0, x1, y1, z1, b):
        n = int(max(abs(x1 - x0), abs(y1 - y0), abs(z1 - z0))) or 1
        for i in range(n + 1):
            t = i / n
            self.b[(int(round(x0 + (x1 - x0) * t)), int(round(y0 + (y1 - y0) * t)), int(round(z0 + (z1 - z0) * t)))] = b

    def bounds(self, solid_only=False):
        ks = [k for k, v in self.b.items() if (v != AIR or not solid_only)]
        if not ks:
            return (0, 0, 0, 0, 0, 0)
        xs, ys, zs = zip(*ks)
        return min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)

    def footprint(self):
        x0, x1, y0, y1, z0, z1 = self.bounds(True)
        return x0, x1, y0, y1


# ---------------------------------------------------------------- roofs
def gable_roof(c, x0, x1, y0, y1, z, b, fill, over=1, axis="x"):
    """Pitched roof; ridge along `axis`. Gable ends filled with `fill`. Returns ridge z."""
    k = 0
    if axis == "y":
        while True:
            a, e = x0 - over + k, x1 + over - k
            if a > e:
                break
            for y in range(y0 - over, y1 + over + 1):
                c.put(a, y, z + k, b); c.put(e, y, z + k, b)
                for x in range(a + 1, e):
                    c.put(x, y, z + k, fill if y in (y0, y1) else AIR)
            k += 1
        return z + k - 1
    while True:
        a, e = y0 - over + k, y1 + over - k
        if a > e:
            break
        for x in range(x0 - over, x1 + over + 1):
            c.put(x, a, z + k, b); c.put(x, e, z + k, b)
            for y in range(a + 1, e):
                c.put(x, y, z + k, fill if x in (x0, x1) else AIR)
        k += 1
    return z + k - 1


def hip_roof(c, x0, x1, y0, y1, z, b, over=1, step=1):
    k = 0
    while True:
        a0, a1, b0, b1 = x0 - over + k, x1 + over - k, y0 - over + k, y1 + over - k
        if a0 > a1 or b0 > b1:
            break
        zz = z + k // step
        if a0 + 1 >= a1 or b0 + 1 >= b1:
            c.box(a0, a1, b0, b1, zz, zz, b)
        else:
            c.ring(a0, a1, b0, b1, zz, b)
            c.box(a0 + 1, a1 - 1, b0 + 1, b1 - 1, zz, zz, AIR)
        k += 1
    return z + (k - 1) // step


def flat_roof(c, x0, x1, y0, y1, z, b, rim=None):
    c.box(x0, x1, y0, y1, z, z, b)
    if rim is not None:
        c.ring(x0, x1, y0, y1, z + 1, rim)


def cone_roof(c, cx, cy, r, z, b, over=1, tip=None):
    rr = r + over
    k = 0
    while rr > 0.2:
        c.cyl(cx, cy, rr, z + k, z + k, b, hollow=True, inner=AIR)
        rr -= 0.75 if r > 4 else 0.6
        k += 1
    c.put(cx, cy, z + k, tip or b)
    return z + k


def eave_roof(c, hx, hy, z, b, eave=3, top=True, tip=None, upturn=1):
    """Japanese/Chinese curved roof around a centred hx*hy body. Concave profile: wide flat eaves, then steep."""
    ox, oy = hx + eave, hy + eave
    c.box(-ox, ox, -oy, oy, z, z, b)
    if upturn:
        for sx in (-1, 1):
            for sy in (-1, 1):
                for u in range(1, upturn + 1):
                    c.put(sx * (ox + u - 1), sy * (oy + u - 1), z + u, tip or b)
    if not top:
        c.box(-(ox - 2), ox - 2, -(oy - 2), oy - 2, z + 1, z + 1, b)
        return z + 2
    k, ax, ay = 1, ox - 2, oy - 2
    while ax >= 0 and ay >= 0:
        c.ring(-ax, ax, -ay, ay, z + k, b)
        if ax > 0 and ay > 0:
            c.box(-ax + 1, ax - 1, -ay + 1, ay - 1, z + k, z + k, AIR)
        ax -= 1; ay -= 1; k += 1
    return z + k - 1


# ============================================================================ palette + helpers
class Pal(dict):
    def __getattr__(self, k):
        return self[k]


BASE_PAL = dict(wall=bl.PLANKS, roof=bl.ROOF_TILE, trim=bl.LOG, pillar=bl.LOG, floor=bl.PLANKS, base=bl.COBBLE,
                glass=bl.GLASS, accent=bl.GOLD_BLOCK)


def S(o, n, lo=1):
    return max(lo, int(round(n * o.scale)))


def windows(c, x0, x1, y0, y1, z, P, every=3, h=2, skip_front_center=True):
    mid = (x0 + x1) // 2
    for x in range(x0 + 2, x1 - 1, every):
        for dz in range(h):
            if not (skip_front_center and abs(x - mid) <= 1):
                c.put(x, y0, z + dz, P.glass)
            c.put(x, y1, z + dz, P.glass)
    for y in range(y0 + 2, y1 - 1, every):
        for dz in range(h):
            c.put(x0, y, z + dz, P.glass); c.put(x1, y, z + dz, P.glass)


def door(c, x, y, z, w=1, h=2):
    for dx in range(-(w // 2), w - w // 2):
        for dz in range(h):
            c.put(x + dx, y, z + dz, AIR)


def battlements(c, x0, x1, y0, y1, z, b):
    for x in range(x0, x1 + 1):
        if (x - x0) % 2 == 0:
            c.put(x, y0, z, b); c.put(x, y1, z, b)
    for y in range(y0, y1 + 1):
        if (y - y0) % 2 == 0:
            c.put(x0, y, z, b); c.put(x1, y, z, b)


def tree(c, x, y, leaves=bl.LEAVES, h=4, r=2.4, trunk=bl.LOG):
    for z in range(h):
        c.put(x, y, z, trunk)
    R = int(math.ceil(r))
    for dx in range(-R, R + 1):
        for dy in range(-R, R + 1):
            for dz in range(-1, R + 1):
                if dx * dx + dy * dy + (dz * 1.3) ** 2 <= r * r:
                    c.soft(x + dx, y + dy, h + dz, leaves)


GEN = {}


def gen(*names, label=None, nominal_h=10, feats=(), uses_height=False):
    def deco(f):
        for n in names:
            GEN[n] = (f, label or n, nominal_h, set(feats), uses_height)
        return f
    return deco


# ============================================================================ generators (part 1)
@gen("japanese", label="Japanese temple", nominal_h=18, feats=("cherry", "lanterns", "path"))
@gen("pagoda", label="Japanese pagoda", nominal_h=26, feats=("cherry", "lanterns", "path"))
@gen("pagoda_cn", label="Chinese pagoda", nominal_h=30, feats=("lanterns", "path"))
def asian(c, P, o):
    chinese = o.kind == "pagoda_cn"
    tall = o.kind != "japanese" or o.castle
    tiers = max(1, min(9, o.tiers or default_tiers(o)))
    hx = S(o, 4 if tall else 7, 2)
    hy = S(o, 4 if tall else 5, 2)
    th = S(o, 4, 3)
    eave = max(2, min(4, hx // 2 + 1))
    bh = S(o, 6, 3) if o.castle else 2
    bx, by = hx + eave + 2, hy + eave + 2
    for z in range(bh):                                    # stone base (sloped for a castle) + front steps
        inset = (bh - 1 - z) // 2 if o.castle else 0
        c.box(-bx + inset, bx - inset, -by + inset, by - inset, z, z, P.base)
    for i in range(bh):
        c.box(-1, 1, -by - 1 - i, -by - 1 - i, 0, bh - 1 - i, P.base)
    z = bh
    shrink = 1 if tall else 2
    for t in range(tiers):
        h = th + (1 if t == 0 else 0)
        c.box(-hx, hx, -hy, hy, z - 1, z - 1, P.floor)
        c.hollow(-hx, hx, -hy, hy, z, z + h - 1, P.wall)
        for x in range(-hx, hx + 1):
            for y in (-hy, hy):
                if (x + hx) % 2 == 0 or x == hx:
                    c.box(x, x, y, y, z, z + h - 1, P.pillar)
        for y in range(-hy, hy + 1):
            for x in (-hx, hx):
                if (y + hy) % 2 == 0 or y == hy:
                    c.box(x, x, y, y, z, z + h - 1, P.pillar)
        c.ring(-hx, hx, -hy, hy, z, P.trim)
        if t == 0:
            door(c, 0, -hy, z, 3, 3)
        else:                                              # balcony with railing
            c.ring(-hx - 1, hx + 1, -hy - 1, hy + 1, z - 1, P.trim)
            c.ring(-hx - 1, hx + 1, -hy - 1, hy + 1, z, P.pillar)
            for x in range(-hx, hx + 1, 2):
                c.put(x, -hy - 1, z, AIR); c.put(x, hy + 1, z, AIR)
        z += h
        c.ring(-hx - 1, hx + 1, -hy - 1, hy + 1, z, P.trim)  # brackets under the eaves
        c.box(-hx, hx, -hy, hy, z, z, P.trim)
        z += 1
        last = t == tiers - 1
        top = eave_roof(c, hx, hy, z, P.roof, eave=eave if t == 0 else max(2, eave - 1), top=last,
                        tip=P.accent if chinese else P.roof, upturn=2 if chinese else 1)
        if not last:
            z = top
            hx, hy = max(2, hx - shrink), max(2, hy - shrink)
        elif tall:                                         # sorin spire
            for k in range(1, S(o, 5, 3) + 1):
                c.put(0, 0, top + k, P.accent)
                if k % 2 == 0:
                    for d in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        c.put(d[0], d[1], top + k, P.accent)
        else:
            c.put(0, 0, top + 1, P.accent)


def default_tiers(o):
    if o.kind == "pagoda_cn":
        return 7
    if o.kind == "pagoda":
        return 5
    if o.castle:
        return 4
    return 1 if o.small_house else 2


@gen("torii", label="torii gate", nominal_h=9)
def torii(c, P, o):
    w, h = S(o, 3, 2), S(o, 8, 5)
    for x in (-w, w):
        c.box(x, x, 0, 0, 0, h - 1, bl.RED_WOOD)
        c.put(x, 0, 0, bl.BLACK_WOOL)
    c.box(-w - 1, w + 1, 0, 0, h - 3, h - 3, bl.RED_WOOD)
    c.box(-w - 2, w + 2, 0, 0, h, h, bl.BLACK_WOOL)
    c.box(-w - 1, w + 1, 0, 0, h - 1, h - 1, bl.RED_WOOD)
    c.put(-w - 2, 0, h + 1, bl.BLACK_WOOL); c.put(w + 2, 0, h + 1, bl.BLACK_WOOL)
    c.put(0, 0, h - 2, bl.RED_WOOD)


@gen("castle", label="medieval castle", nominal_h=16, feats=("path",))
def castle(c, P, o):
    h, wh = S(o, 14, 7), S(o, 7, 5)
    for z in range(wh):
        c.ring(-h, h, -h, h, z, P.wall); c.ring(-h + 1, h - 1, -h + 1, h - 1, z, P.wall)
    battlements(c, -h, h, -h, h, wh, P.wall)
    tr = max(2, S(o, 3)); tz = wh + S(o, 4, 2)
    for sx in (-1, 1):
        for sy in (-1, 1):
            cx, cy = sx * h, sy * h
            c.cyl(cx, cy, tr, 0, tz, P.wall, hollow=True)
            c.cyl(cx, cy, tr - 0.5, tz, tz, P.floor)
            for a in range(0, 360, 45):
                c.put(cx + round(tr * math.cos(math.radians(a))), cy + round(tr * math.sin(math.radians(a))), tz + 1, P.wall)
            for zz in range(3, tz - 1, 4):
                c.put(cx + sx * tr, cy, zz, P.glass); c.put(cx, cy + sy * tr, zz, P.glass)
            if o.fairy:
                cone_roof(c, cx, cy, tr, tz + 1, P.roof, over=1, tip=P.accent)
    for sx in (-1, 1):                                     # gatehouse
        c.hollow(sx * 3 - 1, sx * 3 + 1, -h - 2, -h + 2, 0, wh + 3, P.wall)
        battlements(c, sx * 3 - 1, sx * 3 + 1, -h - 2, -h + 2, wh + 4, P.wall)
    c.box(-2, 2, -h - 2, -h + 2, wh - 1, wh + 1, P.wall)
    for y in range(-h - 2, -h + 3):
        for x in (-1, 0, 1):
            for z in range(0, 4):
                c.put(x, y, z, AIR)
    c.box(-1, 1, -h - 2, -h - 2, 4, 4, P.trim)
    k, kh, ky = S(o, 5, 3), S(o, 15, 9), S(o, 3)           # keep
    c.hollow(-k, k, ky - k, ky + k, 0, kh, P.wall)
    for zz in range(4, kh, 4):
        c.box(-k + 1, k - 1, ky - k + 1, ky + k - 1, zz, zz, P.floor)
    windows(c, -k, k, ky - k, ky + k, 2, P, every=3)
    for zz in range(6, kh - 1, 4):
        windows(c, -k, k, ky - k, ky + k, zz, P, every=3, skip_front_center=False)
    door(c, 0, ky - k, 0, 3, 3)
    c.box(-k, k, ky - k, ky + k, kh, kh, P.wall)
    battlements(c, -k, k, ky - k, ky + k, kh + 1, P.wall)
    for zz in range(kh + 1, kh + 6):
        c.put(0, ky, zz, bl.LOG)
    c.box(1, 3, ky, ky, kh + 4, kh + 5, bl.RED_WOOL)
    for y in range(-h + 2, ky - k):
        for x in (-1, 0, 1):
            c.put(x, y, -1, bl.GRAVEL)


@gen("house", label="house", nominal_h=10)
@gen("cottage", label="cottage", nominal_h=9)
@gen("cabin", label="log cabin", nominal_h=9)
def house(c, P, o):
    hx, hy = S(o, 4, 3), S(o, 3, 2)
    floors = max(1, min(6, o.floors or (2 if o.kind == "house" and o.scale > 1.2 else 1)))
    fh = 4
    c.box(-hx, hx, -hy, hy, 0, 0, P.floor)
    z = 1
    for f in range(floors):
        c.hollow(-hx, hx, -hy, hy, z, z + fh - 1, P.wall)
        for sx in (-hx, hx):
            for sy in (-hy, hy):
                c.box(sx, sx, sy, sy, z, z + fh - 1, P.pillar)
        windows(c, -hx, hx, -hy, hy, z + 1, P, every=3, skip_front_center=(f == 0))
        z += fh
        if f < floors - 1:
            c.box(-hx + 1, hx - 1, -hy + 1, hy - 1, z - 1, z - 1, P.floor)
    door(c, 0, -hy, 1, 1, 2)
    c.put(0, -hy - 1, 0, P.base)
    ridge = gable_roof(c, -hx, hx, -hy, hy, z, P.roof, P.wall, over=1, axis="x")
    if "chimney" in o.features or o.kind in ("cottage", "cabin"):
        for zz in range(1, ridge + 3):
            c.put(hx - 1, hy - 1, zz, bl.BRICKS)
    c.put(-hx + 1, -hy + 1, 1, bl.TABLE)


@gen("modern", label="modern house", nominal_h=9, feats=("pool",))
def modern(c, P, o):
    hx, hy = S(o, 6, 4), S(o, 4, 3)
    c.box(-hx, hx, -hy, hy, 0, 0, P.floor)
    c.hollow(-hx, hx, -hy, hy, 1, 4, P.wall)
    for x in range(-hx + 1, hx):
        for z in range(1, 4):
            c.put(x, -hy, z, P.glass)
    door(c, -hx + 2, -hy, 1, 1, 2)
    c.box(-hx, hx, -hy, hy, 5, 5, P.wall)
    ux0, ux1, uy0, uy1 = -hx // 2, hx + 2, -hy + 1, hy + 1     # cantilevered upper box
    c.hollow(ux0, ux1, uy0, uy1, 6, 8, P.wall)
    for x in range(ux0 + 1, ux1):
        c.put(x, uy0, 7, P.glass); c.put(x, uy0, 6, P.glass)
    for y in range(uy0 + 1, uy1):
        c.put(ux1, y, 7, P.glass)
    flat_roof(c, ux0 - 1, ux1 + 1, uy0 - 1, uy1 + 1, 9, P.roof)
    c.ring(-hx, ux0 - 1, -hy, hy, 6, bl.GLASS)                    # glass terrace rail


@gen("mansion", label="mansion", nominal_h=14, feats=("garden", "path"))
def mansion(c, P, o):
    hx, hy = S(o, 11, 7), S(o, 6, 4)
    floors = max(1, min(5, o.floors or 2))
    fh = 4
    c.box(-hx, hx, -hy, hy, 0, 0, P.floor)
    z = 1
    for f in range(floors):
        c.hollow(-hx, hx, -hy, hy, z, z + fh - 1, P.wall)
        windows(c, -hx, hx, -hy, hy, z + 1, P, every=2, skip_front_center=(f == 0))
        c.ring(-hx, hx, -hy, hy, z + fh - 1, P.trim)
        z += fh
        c.box(-hx + 1, hx - 1, -hy + 1, hy - 1, z - 1, z - 1, P.floor)
    door(c, 0, -hy, 1, 3, 3)
    hip_roof(c, -hx, hx, -hy, hy, z, P.roof, over=1)
    for x in (-3, -1, 1, 3):                                       # columned portico
        c.box(x, x, -hy - 3, -hy - 3, 1, z - 1, bl.WHITE_STONE)
    c.box(-4, 4, -hy - 4, -hy - 1, 0, 0, bl.WHITE_STONE)
    gable_roof(c, -4, 4, -hy - 3, -hy - 1, z, P.roof, bl.WHITE_STONE, over=0, axis="y")


@gen("skyscraper", label="skyscraper", nominal_h=40, uses_height=True)
def skyscraper(c, P, o):
    hx = S(o, 5, 3)
    H = max(12, min(56, o.height or S(o, 40, 16)))
    c.box(-hx, hx, -hx, hx, 0, 0, P.floor)
    for z in range(1, H):
        for x in range(-hx, hx + 1):
            for y in range(-hx, hx + 1):
                if not (x in (-hx, hx) or y in (-hx, hx)):
                    c.put(x, y, z, P.floor if z % 4 == 0 else AIR)
                    continue
                col = (x in (-hx, hx) and y in (-hx, hx)) or (x % 3 == 0 and y in (-hx, hx)) or (y % 3 == 0 and x in (-hx, hx))
                c.put(x, y, z, P.wall if (col or z % 4 == 0) else P.glass)
    door(c, 0, -hx, 1, 3, 3)
    c.box(-hx, hx, -hx, hx, H, H, P.wall)
    c.ring(-hx, hx, -hx, hx, H + 1, P.wall)
    c.box(-1, 1, -1, 1, H + 1, H + 2, P.wall)
    top = min(H + 3 + S(o, 4, 2), MAX_DIM - 1)
    for z in range(H + 3, top):
        c.put(0, 0, z, bl.CONCRETE)
    c.put(0, 0, top, bl.LANTERN)


@gen("lighthouse", label="lighthouse", nominal_h=24, uses_height=True)
def lighthouse(c, P, o):
    H = max(10, min(54, o.height or S(o, 20, 12)))
    r0, r1 = S(o, 4, 3), max(2, S(o, 2.5, 2))
    c.cyl(0, 0, r0 + 2, -1, 0, bl.COBBLE)
    for z in range(1, H):
        r = r0 + (r1 - r0) * z / H
        c.cyl(0, 0, r, z, z, bl.RED_WOOL if (z // 3) % 2 else bl.WHITE_STONE, hollow=True)
    door(c, 0, -r0, 1, 1, 2)
    c.cyl(0, 0, r1 + 1.5, H, H, bl.DARK_WOOD)
    for a in range(0, 360, 30):
        c.put(round((r1 + 1.5) * math.cos(math.radians(a))), round((r1 + 1.5) * math.sin(math.radians(a))), H + 1, bl.DARK_WOOD)
    c.cyl(0, 0, r1, H + 1, H + 3, bl.GLASS, hollow=True)
    c.box(0, 0, 0, 0, H + 1, H + 2, bl.LANTERN)
    c.dome(0, 0, H + 4, r1, bl.RED_WOOL, hollow=False, squash=0.8)
    c.put(0, 0, H + 4 + int(r1 * 0.8) + 1, bl.GOLD_BLOCK)


@gen("windmill", label="windmill", nominal_h=18)
def windmill(c, P, o):
    H = S(o, 12, 8)
    r0, r1 = S(o, 4, 3), max(2, S(o, 2.5, 2))
    for z in range(0, H):
        c.cyl(0, 0, r0 + (r1 - r0) * z / H, z, z, P.wall, hollow=True)
    door(c, 0, -r0, 0, 1, 2)
    for z in range(3, H - 1, 4):
        c.put(r0 - 1, 0, z, bl.GLASS); c.put(-r0 + 1, 0, z, bl.GLASS)
    cone_roof(c, 0, 0, r1, H, P.roof, over=1)
    hub_y, hub_z = -r1 - 2, H
    c.put(0, hub_y + 1, hub_z, bl.LOG); c.put(0, hub_y, hub_z, bl.DARK_WOOD)
    L = S(o, 9, 5)
    for dx, dz in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
        for i in range(1, L + 1):
            x, z = dx * i, hub_z + dz * i
            if z < 1:
                continue
            c.put(x, hub_y, z, bl.DARK_WOOD)
            if i > 2:
                c.put(x + dx, hub_y, z, bl.WOOL); c.put(x, hub_y, z - dz, bl.WOOL)


@gen("pyramid", label="pyramid", nominal_h=13)
@gen("pyramid_step", label="step pyramid", nominal_h=14)
def pyramid(c, P, o):
    step = o.kind == "pyramid_step"
    n = S(o, 13 if not step else 11, 4)
    z, k = 0, n
    while k >= (2 if step else 0):
        c.box(-k, k, -k, k, z, z + (1 if step else 0), P.wall)
        if step:
            c.ring(-k, k, -k, k, z + 1, P.trim)
        z += 2 if step else 1
        k -= 2 if step else 1
    if step:
        c.hollow(-2, 2, -2, 2, z, z + 3, P.wall)
        door(c, 0, -2, z, 1, 2)
        flat_roof(c, -3, 3, -3, 3, z + 4, P.trim)
        for i in range(z):
            c.box(-1, 1, -n - 1 + i, -n - 1 + i, 0, i, P.trim)
    else:
        c.put(0, 0, z - 1, bl.GOLD_BLOCK)
        for y in range(-n, -n + 4):
            for zz in range(1, 3):
                c.put(0, y, zz, AIR)


# ============================================================================ generators (part 2)
@gen("greek", label="Greek temple", nominal_h=12)
def greek(c, P, o):
    hx, hy = S(o, 6, 4), S(o, 10, 6)
    H = S(o, 7, 5)
    for i in range(3):
        c.box(-hx - 3 + i, hx + 3 - i, -hy - 3 + i, hy + 3 - i, i, i, P.base)
    z = 3
    for x in range(-hx, hx + 1, 2):
        for y in (-hy, hy):
            c.box(x, x, y, y, z, z + H - 1, P.pillar)
    for y in range(-hy, hy + 1, 2):
        for x in (-hx, hx):
            c.box(x, x, y, y, z, z + H - 1, P.pillar)
    c.hollow(-hx + 2, hx - 2, -hy + 3, hy - 2, z, z + H - 1, P.wall)
    door(c, 0, -hy + 3, z, 3, 4)
    c.box(-hx, hx, -hy, hy, z + H, z + H, P.trim)
    c.box(-hx - 1, hx + 1, -hy - 1, hy + 1, z + H + 1, z + H + 1, P.trim)
    gable_roof(c, -hx - 1, hx + 1, -hy - 1, hy + 1, z + H + 2, P.roof, P.trim, over=0, axis="y")


@gen("church", label="church", nominal_h=26)
@gen("cathedral", label="cathedral", nominal_h=36)
def church(c, P, o):
    big = o.kind == "cathedral"
    hx, hy = S(o, 7 if big else 5, 3), S(o, 14 if big else 10, 6)
    H = S(o, 10 if big else 7, 5)
    c.box(-hx, hx, -hy, hy, 0, 0, P.floor)
    c.hollow(-hx, hx, -hy, hy, 1, H, P.wall)
    for y in range(-hy + 2, hy - 1, 3):
        for z in range(2, H - 1):
            c.put(-hx, y, z, P.glass); c.put(hx, y, z, P.glass)
    gable_roof(c, -hx, hx, -hy, hy, H + 1, P.roof, P.wall, over=1, axis="y")
    if big:                                                # transept + crossing dome
        ty = S(o, 3)
        c.hollow(-hx - 5, hx + 5, ty - 3, ty + 3, 1, H, P.wall)
        c.box(-hx + 1, hx - 1, ty - 2, ty + 2, 1, H, AIR)
        gable_roof(c, -hx - 5, hx + 5, ty - 3, ty + 3, H + 1, P.roof, P.wall, over=1, axis="x")
        c.dome(0, ty, H + 3, 4, P.roof, hollow=True)
    tw = 2
    tz = S(o, 22 if big else 16, 10)
    for tx in ((-hx + 2, hx - 2) if big else (0,)):
        c.hollow(tx - tw, tx + tw, -hy - 2 * tw, -hy, 0, tz, P.wall)
        for z in range(H + 2, tz - 1, 4):
            c.put(tx, -hy - 2 * tw, z, P.glass); c.put(tx, -hy - 2 * tw, z + 1, P.glass)
        battlements(c, tx - tw, tx + tw, -hy - 2 * tw, -hy, tz + 1, P.wall)
        sp = hip_roof(c, tx - tw + 1, tx + tw - 1, -hy - 2 * tw + 1, -hy - 1, tz + 1, P.roof, over=0, step=2 if big else 3)
        cy = -hy - tw
        c.box(tx, tx, cy, cy, sp + 1, sp + 4, bl.GOLD_BLOCK)
        c.box(tx - 1, tx + 1, cy, cy, sp + 3, sp + 3, bl.GOLD_BLOCK)
        door(c, tx, -hy - 2 * tw, 1, 1, 3)
        door(c, tx, -hy, 1, 1, 3)
    if big:
        door(c, 0, -hy, 1, 3, 4)


@gen("barn", label="barn", nominal_h=11)
def barn(c, P, o):
    hx, hy = S(o, 5, 3), S(o, 7, 4)
    H = S(o, 5, 4)
    c.box(-hx, hx, -hy, hy, 0, 0, bl.PLANKS)
    c.hollow(-hx, hx, -hy, hy, 1, H, P.wall)
    for sx in (-hx, hx):
        for sy in (-hy, hy):
            c.box(sx, sx, sy, sy, 1, H, bl.WHITE_STONE)
    for x in range(-2, 3):
        for z in range(1, 5):
            c.put(x, -hy, z, AIR)
    c.line(-2, -hy - 1, 1, 2, -hy - 1, 4, bl.WHITE_STONE); c.line(-2, -hy - 1, 4, 2, -hy - 1, 1, bl.WHITE_STONE)
    z = H + 1
    widths = [hx + 1, hx + 1, hx, hx - 1, hx - 3, hx - 5]     # gambrel roof profile
    last = 0
    for i, w in enumerate(widths):
        if w < 1:
            break
        last = i
        for y in range(-hy - 1, hy + 2):
            c.put(-w, y, z + i, P.roof); c.put(w, y, z + i, P.roof)
            for x in range(-w + 1, w):
                c.put(x, y, z + i, P.wall if y in (-hy, hy) else AIR)
    w = max(0, widths[last] - 1)
    c.box(-w, w, -hy - 1, hy + 1, z + last + 1, z + last + 1, P.roof)
    for x in range(-hx + 1, hx):
        c.put(x, hy - 1, 1, bl.THATCH); c.put(x, hy - 2, 1, bl.THATCH)


@gen("farm", label="farm", nominal_h=11)
def farm(c, P, o):
    barn(c, P, o)
    x0, x1, y0, y1 = c.footprint()
    fx0, fx1 = x1 + 3, x1 + 3 + S(o, 12, 6)
    for x in range(fx0, fx1 + 1):
        for y in range(y0, y1 + 1):
            if x in (fx0, fx1) or y in (y0, y1):
                c.put(x, y, 0, bl.DARK_WOOD if (x + y) % 2 == 0 else AIR)
            elif (x - fx0) % 3 == 0:
                c.put(x, y, -1, bl.WATER)
            else:
                c.put(x, y, -1, bl.DIRT)
                c.put(x, y, 0, bl.YELLOW_WOOL if (x // 3) % 2 else bl.GREEN_WOOL)
    c.put(fx0, (y0 + y1) // 2, 0, AIR)


@gen("igloo", label="igloo", nominal_h=6)
def igloo(c, P, o):
    r = S(o, 5, 3)
    c.dome(0, 0, 0, r, bl.SNOW, hollow=True)
    for y in range(-r - 2, -r + 2):
        for x in (-1, 1):
            c.put(x, y, 0, bl.SNOW); c.put(x, y, 1, bl.SNOW)
        c.put(0, y, 2, bl.SNOW); c.put(0, y, 0, AIR); c.put(0, y, 1, AIR)
    c.put(0, 0, 0, bl.LANTERN)


@gen("treehouse", label="treehouse", nominal_h=18)
def treehouse(c, P, o):
    th = S(o, 9, 6)
    c.box(0, 1, 0, 1, 0, th + 6, bl.LOG)
    r = S(o, 6, 4)
    for dx in range(-r, r + 2):
        for dy in range(-r, r + 2):
            for dz in range(-2, r):
                if (dx - 0.5) ** 2 + (dy - 0.5) ** 2 + (dz * 1.5) ** 2 <= r * r:
                    c.soft(dx, dy, th + 6 + dz, bl.LEAVES)
    p = S(o, 4, 3)
    c.box(-p, p + 1, -p, p + 1, th, th, bl.PLANKS)
    c.ring(-p, p + 1, -p, p + 1, th + 1, bl.DARK_WOOD)
    c.hollow(-2, 3, -2, 3, th + 1, th + 3, P.wall)
    c.box(-2, 3, -2, 3, th + 4, th + 4, P.roof)
    c.box(0, 1, 0, 1, th + 1, th + 3, bl.LOG)
    door(c, 0, -2, th + 1, 1, 2); c.put(0, -p, th + 1, AIR)
    c.put(-2, 0, th + 2, bl.GLASS); c.put(3, 1, th + 2, bl.GLASS)
    spiral = [(-1, 0), (-1, 1), (0, 2), (1, 2), (2, 1), (2, 0), (1, -1), (0, -1)]
    for z in range(0, th):                                 # spiral stairs around the trunk
        sx, sy = spiral[z % len(spiral)]
        c.put(sx, sy, z, bl.PLANKS)
        c.put(sx, sy, th, AIR) if z == th - 1 else None


@gen("bridge", label="bridge", nominal_h=8)
def bridge(c, P, o):
    L, w, dz = S(o, 14, 6), S(o, 2, 1), S(o, 4, 3)
    for y in range(-L, L + 1):
        ramp = max(1, min(dz, L - abs(y) + 1))
        c.box(-w, w, y, y, ramp - 1, ramp - 1, P.floor)
        c.box(-w, w, y, y, 0, ramp - 2, P.wall) if (abs(y) > L - dz or abs(y) % 8 == 0) and ramp > 1 else None
        for x in (-w - 1, w + 1):
            c.put(x, y, ramp - 1, P.trim); c.put(x, y, ramp, P.trim)
            if y % 4 == 0:
                c.put(x, y, ramp + 1, bl.LANTERN)


@gen("wall", label="great wall", nominal_h=9)
def wall(c, P, o):
    L, H = S(o, 16, 8), S(o, 6, 4)
    for x in range(-L, L + 1):
        c.box(x, x, -1, 1, 0, H - 1, P.wall)
        if x % 2 == 0:
            c.put(x, -1, H, P.wall); c.put(x, 1, H, P.wall)
    for tx in range(-L, L + 1, 10):
        c.hollow(tx - 2, tx + 2, -2, 2, 0, H + 3, P.wall)
        battlements(c, tx - 2, tx + 2, -2, 2, H + 4, P.wall)
        door(c, tx, -2, 0, 1, 2)
        c.put(tx, -2, H + 1, P.glass)


@gen("watchtower", label="watchtower", nominal_h=16, uses_height=True)
def watchtower(c, P, o):
    H = max(8, min(50, o.height or S(o, 12, 8)))
    for sx in (-2, 2):
        for sy in (-2, 2):
            c.box(sx, sx, sy, sy, 0, H + 3, bl.LOG)
    for z in range(3, H, 4):
        c.line(-2, -2, z - 3, 2, -2, z, bl.DARK_WOOD); c.line(-2, 2, z - 3, 2, 2, z, bl.DARK_WOOD)
    c.box(-3, 3, -3, 3, H, H, P.floor)
    c.ring(-3, 3, -3, 3, H + 1, bl.DARK_WOOD)
    for z in range(0, H):
        c.put(0, 1, z, bl.VINE_BLOCK)                      # climbing vine column
    hip_roof(c, -3, 3, -3, 3, H + 4, P.roof, over=1)
    c.put(2, 2, H + 1, bl.LANTERN)


@gen("round_tower", label="round tower", nominal_h=22, uses_height=True)
def round_tower(c, P, o):
    H = max(8, min(50, o.height or S(o, 18, 10)))
    r = S(o, 4, 3)
    c.cyl(0, 0, r, 0, H, P.wall, hollow=True)
    for z in range(4, H, 4):
        c.cyl(0, 0, r - 1, z, z, P.floor)
        c.put(r, 0, z - 2, P.glass); c.put(-r, 0, z - 1, P.glass); c.put(0, r, z - 2, P.glass)
    door(c, 0, -r, 1, 1, 2)
    c.cyl(0, 0, r + 1, H + 1, H + 1, P.trim)
    cone_roof(c, 0, 0, r, H + 2, P.roof, over=1, tip=P.accent)


@gen("fountain", label="fountain", nominal_h=5)
def fountain(c, P, o):
    r = S(o, 4, 3)
    c.cyl(0, 0, r, -1, -1, P.base)
    c.cyl(0, 0, r, 0, 0, P.wall, hollow=True, inner=bl.WATER)
    c.box(0, 0, 0, 0, 0, 2, P.wall)
    c.box(-1, 1, -1, 1, 3, 3, P.wall)
    c.put(0, 0, 4, bl.WATER)


@gen("obelisk", label="obelisk", nominal_h=18, uses_height=True)
def obelisk(c, P, o):
    H = max(8, min(58, o.height or S(o, 16, 8)))
    c.box(-3, 3, -3, 3, 0, 1, P.base)
    for z in range(2, H):
        k = 2 if z < H * 0.4 else 1 if z < H * 0.85 else 0
        c.box(-k, k, -k, k, z, z, P.wall)
    c.put(0, 0, H, bl.GOLD_BLOCK)


@gen("statue", label="statue", nominal_h=14)
def statue(c, P, o):
    s = max(1, int(round(o.scale)))
    m = P.wall
    c.box(-3 * s, 3 * s, -2 * s, 2 * s, 0, s, P.base)
    z = 2 * s
    c.box(-2 * s, -s + (0 if s == 1 else -1) + 1, -s // 2, s // 2, z, z + 4 * s - 1, m)
    c.box(s - 1 + (0 if s == 1 else 1), 2 * s, -s // 2, s // 2, z, z + 4 * s - 1, m)
    z += 4 * s
    c.box(-2 * s, 2 * s, -s, s, z, z + 4 * s - 1, m)
    c.box(-3 * s - s + 1, -2 * s - 1, -s // 2, s // 2, z, z + 4 * s - 1, m)
    c.box(2 * s + 1, 3 * s + s - 1, -s // 2, s // 2, z, z + 4 * s - 1, m)
    z += 4 * s
    c.box(-s, s, -s, s, z, z + 2 * s, m)
    c.put(-max(1, s // 2), -s, z + s, bl.BLACK_WOOL); c.put(max(1, s // 2), -s, z + s, bl.BLACK_WOOL)
    c.box(-s, s, -s, s, z + 2 * s + 1, z + 2 * s + 1, P.accent)


@gen("stadium", label="stadium", nominal_h=9)
def stadium(c, P, o):
    rx, ry = S(o, 16, 9), S(o, 10, 6)
    rows = S(o, 6, 3)
    seats = [bl.RED_WOOL, bl.BLUE_WOOL, bl.YELLOW_WOOL, bl.WHITE_STONE]
    for x in range(-rx - rows - 2, rx + rows + 3):
        for y in range(-ry - rows - 2, ry + rows + 3):
            d = math.sqrt((x / (rx + 0.5)) ** 2 + (y / (ry + 0.5)) ** 2)
            if d <= 1.0:
                c.put(x, y, -1, bl.WHITE_STONE if x == 0 else (bl.GREEN_WOOL if (x // 3) % 2 else bl.GRASS))
                continue
            row = int((d - 1.0) * min(rx, ry))
            if abs(x) <= 1 and y < 0:
                continue                                    # entrance tunnel
            if row < rows:
                c.box(x, x, y, y, 0, row, P.wall)
                c.put(x, y, row, seats[row % 4])
            elif row == rows:
                c.box(x, x, y, y, 0, rows + 1, P.wall)
                if (x + y) % 6 == 0:
                    c.put(x, y, rows + 2, bl.LANTERN)


@gen("shop", label="shop", nominal_h=7)
def shop(c, P, o):
    hx, hy = S(o, 4, 3), S(o, 4, 3)
    c.box(-hx, hx, -hy, hy, 0, 0, P.floor)
    c.hollow(-hx, hx, -hy, hy, 1, 4, P.wall)
    for x in range(-hx + 1, hx):
        c.put(x, -hy, 2, P.glass); c.put(x, -hy, 3, P.glass)
    door(c, 0, -hy, 1, 1, 3)
    for x in range(-hx - 1, hx + 2):                       # striped awning + sign
        c.put(x, -hy - 1, 4, bl.RED_WOOL if x % 2 else bl.WHITE_STONE)
    c.box(-2, 2, -hy, -hy, 5, 5, bl.YELLOW_WOOL)
    flat_roof(c, -hx, hx, -hy, hy, 5, P.roof)
    c.put(-2, -hy, 5, bl.YELLOW_WOOL)
    c.box(-hx + 1, hx - 1, hy - 1, hy - 1, 1, 1, bl.TABLE)


@gen("tent", label="tent", nominal_h=5)
def tent(c, P, o):
    if o.circus:
        r = S(o, 7, 4)
        wz = S(o, 4, 2)
        for z in range(0, wz):
            c.cyl(0, 0, r, z, z, bl.RED_WOOL, hollow=True)
        k, rr = 0, float(r)
        while rr > 0.3:
            R = int(math.ceil(rr))
            for x in range(-R, R + 1):
                for y in range(-R, R + 1):
                    d = math.hypot(x, y)
                    if rr - 0.8 < d <= rr + 0.35:
                        ang = (math.degrees(math.atan2(y, x)) + 360) % 360
                        c.put(x, y, wz + k, bl.RED_WOOL if int(ang // 30) % 2 else bl.WHITE_STONE)
            rr -= 0.9; k += 1
        c.box(0, 0, 0, 0, 0, wz + k + 1, bl.LOG); c.put(0, 0, wz + k + 2, bl.YELLOW_WOOL)
        door(c, 0, -r, 0, 3, 3)
        return
    L, w = S(o, 3, 2), S(o, 3, 2)
    col = P.wall if P.wall != bl.PLANKS else bl.GREEN_WOOL
    for i in range(w + 1):
        for y in range(-L, L + 1):
            c.put(-w + i, y, i, col); c.put(w - i, y, i, col)
            for x in range(-w + i + 1, w - i):
                c.put(x, y, i, AIR)
    for y in range(-L, L + 1):
        c.put(0, y, w, bl.LOG)


@gen("observatory", label="observatory", nominal_h=12)
def observatory(c, P, o):
    r, H = S(o, 6, 4), S(o, 5, 3)
    c.cyl(0, 0, r + 1, 0, 0, P.base)
    c.cyl(0, 0, r, 1, H, P.wall, hollow=True)
    door(c, 0, -r, 1, 1, 2)
    c.dome(0, 0, H + 1, r, P.roof, hollow=True)
    for z in range(H + 1, H + r + 1):                      # telescope slit
        c.put(0, -int(round(math.sqrt(max(0, r * r - (z - H - 1) ** 2)))), z, bl.GLASS)
    c.line(0, 0, 2, 0, -r + 2, H + r - 2, bl.CONCRETE)


@gen("ship", label="ship", nominal_h=15)
def ship(c, P, o):
    small = o.boat
    L = S(o, 5 if small else 12, 4)
    w = S(o, 2 if small else 3, 2)
    D = 2 if small else 3
    for y in range(-L, L + 1):
        hw = max(0, int(round(w * (1 - (abs(y) / L) ** 2.2))))
        for z in range(0, D + 1):
            ww = max(0, hw - (D - z) // 2)
            for x in range(-ww, ww + 1):
                c.put(x, y, z, bl.DARK_WOOD if (abs(x) == ww or z == 0) else AIR)
        if hw > 0:
            c.box(-hw + 1, hw - 1, y, y, D, D, bl.PLANKS)
    c.put(0, -L - 1, D, bl.DARK_WOOD)
    if small:
        return
    for my, mh in ((-L // 3, S(o, 12, 7)), (L // 3, S(o, 10, 6))):
        c.box(0, 0, my, my, D + 1, D + mh, bl.LOG)
        for z in range(D + 4, D + mh - 1):
            sw = max(1, w + 1 - (z - D - 4) // 4)
            c.box(-sw, sw, my - 1, my - 1, z, z, bl.WOOL)
        c.box(0, 1, my, my, D + mh + 1, D + mh + 1, bl.RED_WOOL)
    c.hollow(-w + 1, w - 1, L - 4, L - 1, D + 1, D + 3, bl.PLANKS)
    door(c, 0, L - 4, D + 1, 1, 2)
    c.box(-w + 1, w - 1, L - 4, L - 1, D + 4, D + 4, bl.DARK_WOOD)


@gen("greenhouse", label="greenhouse", nominal_h=7)
def greenhouse(c, P, o):
    hx, hy = S(o, 4, 3), S(o, 6, 4)
    c.box(-hx, hx, -hy, hy, -1, -1, bl.DIRT)
    c.hollow(-hx, hx, -hy, hy, 0, 3, bl.GLASS)
    for sx in (-hx, hx):
        for sy in range(-hy, hy + 1, 3):
            c.box(sx, sx, sy, sy, 0, 3, bl.WHITE_STONE)
    gable_roof(c, -hx, hx, -hy, hy, 4, bl.GLASS, bl.GLASS, over=0, axis="y")
    door(c, 0, -hy, 0, 1, 2)
    for y in range(-hy + 1, hy):
        c.put(-hx + 1, y, 0, bl.LEAVES); c.put(hx - 1, y, 0, bl.CHERRY_LEAVES if y % 2 else bl.LEAVES)


# ============================================================================ generators (part 3, 1.3.1: "understands anything")
def onion(c, cx, cy, z, r, b, tip=None):
    """Onion dome (Russian / Mughal / palace) sitting on z. Returns top z."""
    h = max(3, int(r * 2.3) + 1)
    for k in range(h):
        t = k / float(h)
        rr = r * 1.15 * math.sin(math.pi * (0.35 + 0.65 * t))
        if rr > 0.15:
            c.cyl(cx, cy, rr, z + k, z + k, b)
        else:
            c.put(cx, cy, z + k, b)
    c.put(cx, cy, z + h, tip or bl.GOLD_BLOCK); c.put(cx, cy, z + h + 1, tip or bl.GOLD_BLOCK)
    return z + h + 1


@gen("mushroom", label="mushroom house", nominal_h=14, feats=("garden",))
def mushroom(c, P, o):
    r, H, R = S(o, 3, 2), S(o, 7, 4), S(o, 7, 4)
    c.cyl(0, 0, r, 0, 0, P.floor)
    c.cyl(0, 0, r, 1, H, P.wall, hollow=True)
    door(c, 0, -r, 1, 1, 2)
    for z in range(3, H, 3):
        c.put(r, 0, z, P.glass); c.put(-r, 0, z, P.glass); c.put(0, r, z, P.glass)
    c.cyl(0, 0, R, H + 1, H + 1, P.trim)
    c.dome(0, 0, H + 2, R, P.roof, hollow=True, squash=0.65)
    for k, v in list(c.b.items()):
        if v == P.roof and (k[0] * 7 + k[1] * 13 + k[2] * 5) % 9 == 0:
            c.b[k] = bl.WHITE_STONE
    c.put(r + 1, -r - 1, 0, bl.LANTERN)


@gen("hobbit", label="hobbit hole", nominal_h=7, feats=("garden", "path", "fence"))
def hobbit(c, P, o):
    r = S(o, 7, 5)
    c.dome(0, 0, 0, r, bl.GRASS, hollow=True, squash=0.75)
    c.box(-r + 1, r - 1, -r + 1, r - 1, 0, 0, AIR)
    fy = -r + 2
    for k in [k for k in c.b if k[1] < fy]:
        del c.b[k]
    for k in [k for k in c.b if k[1] == fy and c.b[k] == bl.GRASS]:
        c.b[k] = P.wall
    for x in range(-r + 2, r - 1):                       # fill the facade face
        for z in range(0, r):
            if any(c.get(x, fy, zz) == P.wall for zz in range(z, r + 1)) and c.get(x, fy, z) in (None, AIR):
                c.put(x, fy, z, P.wall)
    for x in range(-2, 3):                               # round door with a frame
        for z in range(0, 4):
            d = x * x + (z - 1.2) ** 2
            if d <= 2.5:
                c.put(x, fy, z, AIR)
            elif d <= 5.5:
                c.put(x, fy, z, P.trim)
    for wx in (-4, 4):
        if abs(wx) < r - 1:
            c.put(wx, fy, 2, P.glass); c.put(wx, fy, 1, P.trim)
    c.box(-r + 2, r - 2, -r + 2, r - 2, -1, -1, P.floor)
    top = int(r * 0.75)
    for zz in range(top - 2, top + 2):
        c.put(r // 2, r // 3, zz, bl.BRICKS)
    for k, v in list(c.b.items()):
        if v == bl.GRASS and (k[0] * 5 + k[1] * 3) % 11 == 0 and c.get(k[0], k[1], k[2] + 1) is None:
            c.put(k[0], k[1], k[2] + 1, random.Random(k[0] * 31 + k[1]).choice([bl.RED_WOOL, bl.YELLOW_WOOL, bl.PINK_WOOL]))


@gen("sphinx", label="sphinx", nominal_h=12)
def sphinx(c, P, o):
    s = max(0.5, o.scale)
    def B(a, b, cc, d, e, f, m): c.box(int(a * s), int(b * s), int(cc * s), int(d * s), int(e * s), int(f * s), m)
    B(-6, 6, -12, 18, -1, 0, P.base)
    B(-3, 3, 0, 14, 1, 5, P.wall)                        # lion body
    B(-3, -1, -9, 0, 1, 2, P.wall); B(1, 3, -9, 0, 1, 2, P.wall)   # front paws
    B(-3, 3, -2, 2, 6, 8, P.wall)                        # chest
    B(-2, 2, -3, 1, 9, 13, P.wall)                       # head
    for z in range(int(6 * s), int(13 * s) + 1):         # striped nemes headdress
        m = P.accent if z % 2 else bl.BLUE_WOOL
        for x in (int(-3 * s), int(3 * s)):
            c.put(x, int(-1 * s), z, m); c.put(x, 0, z, m)
    c.box(int(-2 * s), int(2 * s), int(-2 * s), int(1 * s), int(14 * s), int(14 * s), P.accent)
    c.put(int(-1 * s), int(-3 * s) - 1, int(11 * s), bl.BLACK_WOOL); c.put(int(1 * s), int(-3 * s) - 1, int(11 * s), bl.BLACK_WOOL)
    c.line(int(3 * s), int(14 * s), 1, int(5 * s), int(18 * s), 2, P.wall)


@gen("palace", label="palace", nominal_h=20, feats=("garden", "path"))
def palace(c, P, o):
    hx, hy, H = S(o, 9, 5), S(o, 6, 4), S(o, 7, 5)
    c.box(-hx - 2, hx + 2, -hy - 2, hy + 2, 0, 0, P.base)
    c.hollow(-hx, hx, -hy, hy, 1, H, P.wall)
    c.box(-hx + 1, hx - 1, -hy + 1, hy - 1, 0, 0, P.floor)
    windows(c, -hx, hx, -hy, hy, 2, P, every=2)
    for x in range(-2, 3):                               # big arched entrance
        for z in range(1, 5 if abs(x) < 2 else 4):
            c.put(x, -hy, z, AIR)
    c.ring(-hx, hx, -hy, hy, H, P.trim)
    c.box(-hx, hx, -hy, hy, H + 1, H + 1, P.wall)
    battlements(c, -hx, hx, -hy, hy, H + 2, P.trim)
    r = max(2, min(hx, hy) - 1)
    c.cyl(0, 0, r, H + 2, H + 3, P.wall)
    if o.mosque:
        c.dome(0, 0, H + 4, r, P.roof, hollow=True, squash=1.2)
        c.put(0, 0, H + 5 + int(r * 1.2), P.accent)
    else:
        onion(c, 0, 0, H + 4, r, P.roof, P.accent)
    TH = H + S(o, 8 if o.mosque else 5, 3)
    tr = 1 if o.mosque else 2
    for sx in (-1, 1):
        for sy in (-1, 1):
            cx, cy = sx * (hx + (2 if o.mosque else 0)), sy * (hy + (2 if o.mosque else 0))
            c.cyl(cx, cy, tr, 0, TH, P.wall, hollow=tr > 1)
            c.cyl(cx, cy, tr + 1, TH - 2, TH - 2, P.trim)
            onion(c, cx, cy, TH + 1, tr + 0.5, P.roof, P.accent)


@gen("orb", label="round house", nominal_h=12, feats=("path",))
def orb(c, P, o):
    r = S(o, 5, 3)
    for x in range(-r, r + 1):
        for y in range(-r, r + 1):
            for z in range(0, 2 * r + 1):
                d = math.sqrt(x * x + y * y + (z - r) ** 2)
                if d <= r + 0.3:
                    c.put(x, y, z, P.wall if d > r - 0.9 else AIR)
    c.cyl(0, 0, r - 1, 1, 1, P.floor)
    c.box(-1, 1, -r - 1, -r + 2, 2, 3, AIR)
    for x in (-1, 1):
        c.box(x, x, -r - 1, -r - 1, 0, 1, P.base)
    c.box(-1, 1, -r - 2, -r - 1, 0, 1, P.base)
    for a in (0, 90, 180):
        c.put(round((r - 0.3) * math.cos(math.radians(a))), round((r - 0.3) * math.sin(math.radians(a))), r + 1, P.glass)
    for zz in range(2 * r + 1, 2 * r + 3):
        c.put(0, 0, zz, P.trim)
    c.put(1, 0, 2 * r + 2, bl.GREEN_WOOL); c.put(2, 0, 2 * r + 2, bl.GREEN_WOOL)


@gen("rocket", label="rocket", nominal_h=26, uses_height=True)
def rocket(c, P, o):
    H = max(12, min(48, o.height or S(o, 20, 12)))
    r = S(o, 2.5, 2)
    c.cyl(0, 0, r, 2, H, P.wall, hollow=True)
    cone_roof(c, 0, 0, r, H + 1, P.roof, over=0, tip=P.accent)
    for z in range(5, H - 2, 5):
        c.put(0, -int(r), z, P.glass)
    door(c, 0, -int(r), 2, 1, 2)
    for d in ((1, 0), (-1, 0), (0, 1)):
        for i in range(1, 4):
            for z in range(0, 6 - i):
                c.put(d[0] * (int(r) + i), d[1] * (int(r) + i), z, P.roof)
    c.cyl(0, 0, max(1, r - 1), 0, 1, bl.BLACK_WOOL)
    c.put(0, 0, 0, bl.LANTERN)


@gen("ufo", label="flying saucer", nominal_h=8)
def ufo(c, P, o):
    R, z0 = S(o, 8, 5), S(o, 3, 2)
    for k, rr in enumerate((R - 3, R, R - 1, R - 4)):
        c.cyl(0, 0, max(1, rr), z0 + k, z0 + k, P.wall, hollow=k in (1, 2), inner=AIR)
    c.cyl(0, 0, R - 4, z0, z0, P.floor)
    for a in range(0, 360, 30):
        c.put(round(R * math.cos(math.radians(a))), round(R * math.sin(math.radians(a))), z0 + 1, bl.LANTERN)
    c.dome(0, 0, z0 + 4, max(2, R // 2), bl.GLASS, hollow=True)
    for sx, sy in ((1, 1), (-1, 1), (0, -1)):
        c.line(sx * (R - 4), sy * (R - 4), z0, sx * (R - 2), sy * (R - 2), 0, bl.CONCRETE)


@gen("volcano", label="volcano", nominal_h=16)
def volcano(c, P, o):
    R, H = S(o, 14, 8), S(o, 14, 8)
    for z in range(H):
        rr = R * (1 - z / float(H)) + 3
        c.cyl(0, 0, rr, z, z, bl.STONE if (z * 7) % 5 else bl.COBBLE, hollow=z > H - 4, inner=bl.RED_WOOL)
    c.cyl(0, 0, 3, H - 1, H - 1, bl.YELLOW_WOOL)
    for i in range(H):
        c.put(int(0.6 * i), -int(R * (1 - i / float(H))) - 2, i, bl.RED_WOOL)


@gen("bigtree", label="giant tree", nominal_h=20)
def bigtree(c, P, o):
    H, r = S(o, 14, 8), S(o, 7, 4)
    lv = bl.CHERRY_LEAVES if P.roof in (bl.CHERRY_LEAVES, bl.PINK_WOOL) else bl.LEAVES
    tree(c, -r // 2, 1, lv, h=H - 3, r=r * 0.7)
    tree(c, r // 2 + 1, 0, lv, h=H - 2, r=r * 0.7)
    tree(c, 0, 0, lv, h=H, r=r)
    c.box(0, 1, 0, 1, 0, H, bl.LOG)
    for d in ((-1, 0), (2, 1), (0, -1), (1, 2)):
        c.put(d[0], d[1], 0, bl.LOG); c.put(d[0], d[1], 1, bl.LOG)


@gen("hut", label="round hut", nominal_h=7)
def hut(c, P, o):
    r = S(o, 3, 2)
    c.cyl(0, 0, r, 0, 0, P.floor)
    c.cyl(0, 0, r, 1, 3, P.wall, hollow=True)
    door(c, 0, -r, 1, 1, 2)
    cone_roof(c, 0, 0, r, 4, P.roof, over=1)


@gen("gazebo", label="gazebo", nominal_h=7, feats=("garden",))
def gazebo(c, P, o):
    r = S(o, 4, 3)
    c.cyl(0, 0, r, 0, 0, P.floor)
    for a in range(0, 360, 45):
        x, y = round(r * math.cos(math.radians(a))), round(r * math.sin(math.radians(a)))
        c.box(x, x, y, y, 1, 3, P.pillar)
    c.cyl(0, 0, r + 1, 4, 4, P.trim)
    cone_roof(c, 0, 0, r, 5, P.roof, over=1, tip=P.accent)


@gen("arch", label="triumphal arch", nominal_h=14)
def arch(c, P, o):
    w, h, d = S(o, 7, 4), S(o, 12, 7), S(o, 2, 1)
    c.box(-w, w, -d, d, 0, h, P.wall)
    hw = max(1, w // 2)
    for x in range(-hw, hw + 1):
        top = int(h * 0.55 + math.sqrt(max(0, hw * hw - x * x)) * 0.8)
        c.box(x, x, -d, d, 0, top, AIR)
    c.box(-w - 1, w + 1, -d - 1, d + 1, h + 1, h + 1, P.trim)
    c.box(-w + 1, w - 1, -d, d, h + 2, h + 3, P.wall)


@gen("eiffel", label="lattice tower", nominal_h=40, uses_height=True)
def eiffel(c, P, o):
    H = max(16, min(56, o.height or S(o, 40, 18)))
    W = S(o, 8, 5)
    for z in range(H):
        w = int(round(W * (1 - z / float(H)) ** 1.8)) + 1
        for sx in (-1, 1):
            for sy in (-1, 1):
                c.put(sx * w, sy * w, z, P.wall)
        if z % 7 == 3 or z == int(H * 0.3):
            c.ring(-w, w, -w, w, z, P.wall)
            if z == int(H * 0.3):
                c.box(-w, w, -w, w, z, z, P.floor)
    for x in range(-W + 2, W - 1):                       # arch between the legs
        c.put(x, -W, int(3 + math.sqrt(max(0, (W - 2) ** 2 - x * x)) * 0.5), P.wall)
    for z in range(H, H + 4):
        c.put(0, 0, z, P.wall)
    c.put(0, 0, H + 4, bl.LANTERN)


@gen("stonehenge", label="stone circle", nominal_h=6)
def stonehenge(c, P, o):
    R = S(o, 9, 6)
    n = 10
    for i in range(n):
        a = 2 * math.pi * i / n
        x, y = round(R * math.cos(a)), round(R * math.sin(a))
        c.box(x, x, y, y, 0, 3, bl.STONE)
        x2, y2 = round(R * math.cos(a + math.pi / n)), round(R * math.sin(a + math.pi / n))
        c.line(x, y, 4, x2, y2, 4, bl.STONE)
    c.box(-1, 1, 0, 0, 0, 0, bl.STONE)


@gen("well", label="well", nominal_h=6)
def well(c, P, o):
    c.cyl(0, 0, 2, -2, -2, P.base)
    c.cyl(0, 0, 2, -1, 1, P.base, hollow=True, inner=bl.WATER)
    c.put(0, 0, 1, AIR)
    for x in (-2, 2):
        c.box(x, x, 0, 0, 2, 3, bl.LOG)
    c.box(-1, 1, 0, 0, 3, 3, bl.LOG)
    gable_roof(c, -2, 2, -1, 1, 4, P.roof, AIR, over=0, axis="y")


# ---------------------------------------------------------------- custom / fallback builder
def punch_windows(c, mats, z0, z1, every=3, fh=4):
    """Glass on outward-facing wall cells (neighbour outside the canvas) every few blocks."""
    for (x, y, z), v in list(c.b.items()):
        if v in mats and z0 <= z <= z1 and (z - 1) % fh in (1, 2) and (x + y) % every == 0:
            if any((x + dx, y + dy, z) not in c.b for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                c.b[(x, y, z)] = bl.GLASS


@gen("generic", label="custom building", nominal_h=10)
def generic(c, P, o):
    """Invents a coherent building from the words: footprint shape, floors, roof, towers, entrance, spire."""
    rng = random.Random(zlib.crc32((o.text or "x").lower().encode("utf-8", "ignore")))
    shape = o.shape or rng.choice(["rect", "rect", "rect", "round", "L", "cross"])
    hx = max(3, min(16, (o.width or S(o, 10, 6)) // 2))
    hy = max(3, int(hx * (0.7 if shape == "rect" else 1.0)))
    floors = o.floors or (max(1, o.height // 4) if o.height else (rng.choice([1, 2, 2, 3]) if o.scale >= 1 else 1))
    if o.tall: floors += 2
    floors = max(1, min(12, floors))
    fh = 4
    top = 1 + floors * fh
    def body(x0, x1, y0, y1):
        c.box(x0, x1, y0, y1, 0, 0, P.floor)
        c.hollow(x0, x1, y0, y1, 1, top - 1, P.wall)
        for zz in range(fh, top - 1, fh):
            c.ring(x0, x1, y0, y1, zz, P.trim)
            c.box(x0 + 1, x1 - 1, y0 + 1, y1 - 1, zz, zz, P.floor)
        for sx in (x0, x1):
            for sy in (y0, y1):
                c.box(sx, sx, sy, sy, 1, top - 1, P.pillar)
    roof = o.roof_style or rng.choice(["gable", "hip", "flat", "dome", "eave", "gable", "hip"])
    if shape == "round":
        c.cyl(0, 0, hx, 0, 0, P.floor)
        c.cyl(0, 0, hx, 1, top - 1, P.wall, hollow=True)
        for zz in range(fh, top - 1, fh):
            c.cyl(0, 0, hx - 0.8, zz, zz, P.floor)
        c.cyl(0, 0, hx + 1, top, top, P.trim)
        if roof in ("gable", "hip", "eave", "cone", "spire"):
            cone_roof(c, 0, 0, hx, top + 1, P.roof, over=0, tip=P.accent)
        elif roof == "onion":
            onion(c, 0, 0, top + 1, hx * 0.8, P.roof, P.accent)
        elif roof == "flat":
            c.cyl(0, 0, hx, top, top, P.roof)
        else:
            c.dome(0, 0, top + 1, hx, P.roof, hollow=True)
        yfront = -hx
    else:
        rects = [(-hx, hx, -hy, hy)]
        if shape == "L":
            rects = [(-hx, hx, -hy, 0), (0, hx, -hy, hy)]
        elif shape == "cross":
            a = max(2, hx // 2)
            rects = [(-hx, hx, -a, a), (-a, a, -hy, hy)]
        for r in rects:
            body(*r)
        for x0, x1, y0, y1 in rects:                     # clear interior seams between wings
            for (x0b, x1b, y0b, y1b) in rects:
                if (x0b, x1b, y0b, y1b) != (x0, x1, y0, y1):
                    c.box(max(x0, x0b) + 1, min(x1, x1b) - 1, max(y0, y0b) + 1, min(y1, y1b) - 1, 1, top - 1, AIR)
                    for zz in range(fh, top - 1, fh):
                        c.box(max(x0, x0b) + 1, min(x1, x1b) - 1, max(y0, y0b) + 1, min(y1, y1b) - 1, zz, zz, P.floor)
        for x0, x1, y0, y1 in rects:
            if roof == "flat":
                flat_roof(c, x0, x1, y0, y1, top, P.roof, rim=P.trim)
            elif roof == "dome":
                c.box(x0, x1, y0, y1, top, top, P.roof)
            elif roof == "eave":
                hxx, hyy = (x1 - x0) // 2, (y1 - y0) // 2
                sub = Canvas(); eave_roof(sub, hxx, hyy, top, P.roof, eave=2, tip=P.accent)
                ox, oy = (x0 + x1) // 2, (y0 + y1) // 2
                for (a, b2, z), v in sub.b.items():
                    if v != AIR or (a + ox, b2 + oy, z) not in c.b:
                        c.b[(a + ox, b2 + oy, z)] = v
            elif roof in ("hip", "onion", "spire", "cone"):
                hip_roof(c, x0, x1, y0, y1, top, P.roof)
            else:
                gable_roof(c, x0, x1, y0, y1, top, P.roof, P.wall, over=1, axis="x" if (x1 - x0) >= (y1 - y0) else "y")
        if roof == "dome":
            c.dome(0, 0, top + 1, max(2, min(hx, hy) - 1), P.roof, hollow=True)
        elif roof == "onion":
            onion(c, 0, 0, top + 1, max(2, min(hx, hy) // 2), P.roof, P.accent)
        elif roof == "spire":
            for z in range(top, top + S(o, 10, 5)):
                c.put(0, 0, z, P.accent)
        yfront = -hy
    punch_windows(c, {P.wall}, 1, top - 1, every=2 if o.scale > 1 else 3)
    door(c, 0, yfront, 1, 3 if hx > 4 else 1, 3 if hx > 4 else 2)
    towers = o.towers if o.towers is not None else (rng.choice([0, 0, 2, 4]) if o.scale >= 1 and shape != "round" else 0)
    if towers and shape != "round":
        tr = max(2, hx // 4)
        th = top + S(o, 5, 3)
        spots = [(-hx, -hy), (hx, -hy), (-hx, hy), (hx, hy)]
        spots = spots[:2] if towers <= 2 else spots[:4] if towers <= 4 else spots + [(0, -hy - tr), (0, hy + tr)]
        for cx, cy in spots[:max(1, min(6, towers))]:
            c.cyl(cx, cy, tr, 0, th, P.wall, hollow=True)
            for zz in range(4, th - 1, 4):
                c.put(cx, cy - tr, zz, P.glass)
            if roof == "onion" or o.style in ("arabian", "russian", "indian"):
                onion(c, cx, cy, th + 1, tr, P.roof, P.accent)
            elif roof == "flat":
                c.cyl(cx, cy, tr + 1, th + 1, th + 1, P.trim)
                for a in range(0, 360, 60):
                    c.put(cx + round((tr + 1) * math.cos(math.radians(a))), cy + round((tr + 1) * math.sin(math.radians(a))), th + 2, P.trim)
            else:
                cone_roof(c, cx, cy, tr, th + 1, P.roof, over=1, tip=P.accent)
    if o.columns:
        for x in range(-hx, hx + 1, 2):
            c.box(x, x, yfront - 2, yfront - 2, 1, min(top - 1, 8), bl.WHITE_STONE)
        c.box(-hx, hx, yfront - 2, yfront - 1, min(top, 9), min(top, 9), P.trim)
    if o.factory:
        for x in (-hx + 2, hx - 2):
            for zz in range(top, top + S(o, 8, 5)):
                c.put(x, -yfront - 2, zz, bl.BRICKS)
    if o.spire and roof != "spire":
        mz = c.bounds(True)[5]
        for z in range(mz + 1, mz + S(o, 6, 3)):
            c.put(0, 0, z, P.accent)


# ============================================================================ palettes, parser, features, entry point
KIND_PAL = {
    "japanese": dict(base=bl.STONE_BRICKS, floor=bl.DARK_WOOD, pillar=bl.RED_WOOD, wall=bl.WHITE_STONE, trim=bl.DARK_WOOD, roof=bl.ROOF_TILE),
    "pagoda": dict(base=bl.STONE_BRICKS, floor=bl.DARK_WOOD, pillar=bl.RED_WOOD, wall=bl.WHITE_STONE, trim=bl.DARK_WOOD, roof=bl.ROOF_TILE),
    "pagoda_cn": dict(base=bl.WHITE_STONE, floor=bl.DARK_WOOD, pillar=bl.RED_WOOD, wall=bl.RED_WOOD, trim=bl.GREEN_WOOL, roof=bl.ROOF_TILE),
    "castle": dict(wall=bl.STONE_BRICKS, trim=bl.DARK_WOOD, roof=bl.BLUE_WOOL),
    "house": dict(wall=bl.PLANKS, pillar=bl.LOG, roof=bl.BRICKS, floor=bl.DARK_WOOD),
    "cottage": dict(wall=bl.WHITE_STONE, pillar=bl.DARK_WOOD, roof=bl.THATCH),
    "cabin": dict(wall=bl.LOG, pillar=bl.LOG, roof=bl.DARK_WOOD),
    "modern": dict(wall=bl.WHITE_STONE, roof=bl.CONCRETE, floor=bl.CONCRETE),
    "mansion": dict(wall=bl.BRICKS, trim=bl.WHITE_STONE, floor=bl.DARK_WOOD),
    "skyscraper": dict(wall=bl.CONCRETE, floor=bl.CONCRETE),
    "windmill": dict(wall=bl.WHITE_STONE, roof=bl.DARK_WOOD),
    "pyramid": dict(wall=bl.SANDSTONE),
    "pyramid_step": dict(wall=bl.MOSSY, trim=bl.STONE_BRICKS),
    "greek": dict(base=bl.WHITE_STONE, pillar=bl.WHITE_STONE, wall=bl.WHITE_STONE, trim=bl.WHITE_STONE, roof=bl.RED_WOOL),
    "church": dict(wall=bl.STONE_BRICKS, roof=bl.DARK_WOOD),
    "cathedral": dict(wall=bl.WHITE_STONE, floor=bl.STONE_BRICKS),
    "barn": dict(wall=bl.RED_WOOD, roof=bl.DARK_WOOD), "farm": dict(wall=bl.RED_WOOD, roof=bl.DARK_WOOD),
    "treehouse": dict(roof=bl.LEAVES), "bridge": dict(wall=bl.STONE_BRICKS, floor=bl.COBBLE, trim=bl.STONE_BRICKS),
    "wall": dict(wall=bl.STONE_BRICKS), "watchtower": dict(roof=bl.DARK_WOOD),
    "round_tower": dict(wall=bl.STONE_BRICKS, roof=bl.BLUE_WOOL, trim=bl.STONE_BRICKS),
    "fountain": dict(wall=bl.WHITE_STONE, base=bl.STONE_BRICKS), "obelisk": dict(wall=bl.SANDSTONE, base=bl.STONE_BRICKS),
    "statue": dict(wall=bl.WHITE_STONE, base=bl.STONE_BRICKS), "stadium": dict(wall=bl.CONCRETE),
    "shop": dict(wall=bl.BRICKS, roof=bl.CONCRETE), "observatory": dict(wall=bl.WHITE_STONE, roof=bl.CONCRETE, base=bl.STONE_BRICKS),
    "mushroom": dict(wall=bl.WHITE_STONE, roof=bl.RED_WOOL, trim=bl.SANDSTONE, floor=bl.PLANKS),
    "hobbit": dict(wall=bl.PLANKS, trim=bl.GREEN_WOOL, floor=bl.PLANKS, glass=bl.GLASS),
    "sphinx": dict(wall=bl.SANDSTONE, base=bl.SANDSTONE, accent=bl.GOLD_BLOCK),
    "palace": dict(wall=bl.WHITE_STONE, trim=bl.SANDSTONE, roof=bl.GOLD_BLOCK, floor=bl.STONE_BRICKS, base=bl.WHITE_STONE),
    "orb": dict(wall=bl.WHITE_STONE, trim=bl.LOG, floor=bl.PLANKS),
    "rocket": dict(wall=bl.WHITE_STONE, roof=bl.RED_WOOL, accent=bl.RED_WOOL),
    "ufo": dict(wall=bl.CONCRETE, floor=bl.CONCRETE),
    "hut": dict(wall=bl.SANDSTONE, roof=bl.THATCH, floor=bl.DIRT),
    "gazebo": dict(pillar=bl.WHITE_STONE, roof=bl.GREEN_WOOL, floor=bl.PLANKS, trim=bl.WHITE_STONE),
    "arch": dict(wall=bl.WHITE_STONE, trim=bl.WHITE_STONE), "eiffel": dict(wall=bl.DARK_WOOD, floor=bl.DARK_WOOD),
    "well": dict(base=bl.COBBLE, roof=bl.DARK_WOOD),
    "generic": dict(wall=bl.BRICKS, pillar=bl.STONE_BRICKS, roof=bl.ROOF_TILE, trim=bl.WHITE_STONE),
}

# Ordered: the first rule that matches the *main clause* wins (specific nouns before general ones).
KIND_RULES = [
    ("torii", r"\btorii"), ("hobbit", r"\bhobbit|\bhobbit hole|\bbag end|\bhill ?house|\bunderground house|\bburrow"),
    ("mushroom", r"\bmushroom|\btoadstool|\bfung(i|us)|\bsmurf"),
    ("sphinx", r"\bsphinx"), ("pagoda_cn", r"\bchin(a|ese)|\bforbidden city|\bkorea"), ("pagoda", r"\bpagoda"),
    ("japanese", r"\bjapan|\bshinto|\bshrine|\bbuddhis|\bbuddha|\bzen\b|\bkyoto|\bsamurai|\bdojo|\bshogun|\bninja|\bonsen|\bryokan|\bteahouse|\btea house"),
    ("pyramid_step", r"\bmaya|\bmayan|\baztec|\bstep pyramid|\bziggurat|\binca\b|\bangkor|\bkhmer|\bhindu|\bjungle temple"),
    ("pyramid", r"\bpyramid|\begypt|\bpharaoh|\btomb"),
    ("eiffel", r"\beiffel|\blattice tower|\bradio tower|\bpylon|\bantenna tower|\bcell tower|\btransmission tower"),
    ("stonehenge", r"\bstonehenge|\bstone circle|\bdruid|\bmegalith"),
    ("ufo", r"\bufo\b|\bflying saucer|\bspace ?ship|\bstarship|\balien ship|\bmothership|\bspacecraft"),
    ("rocket", r"\brocket|\bspace shuttle|\bmissile"), ("volcano", r"\bvolcano|\bvolcanic"),
    ("stadium", r"\bstadium|\barena\b|\bcolosseum|\bcoliseum|\bamphithea|\bracetrack|\bbullring"),
    ("arch", r"\barch\b|\btriumph|\barc de|\bgateway\b|\bcity gate|\bportal\b"),
    ("palace", r"\bpalace|\bsultan|\bkremlin|\bst basil|\bmaharaja|\bmughal|\btaj\b|\btaj mahal|\bmosque|\bminaret|\barabian|\bpersian|\bonion dome|\bemperor|\batlantis"),
    ("greek", r"\bgreek|\broman\b|\bparthenon|\bpantheon|\bacropolis|\bolymp"),
    ("cathedral", r"\bcathedral|\bbasilica|\babbey|\bnotre dame|\bminster"), ("church", r"\bchurch|\bchapel|\bmonastery|\bconvent"),
    ("lighthouse", r"\blight ?house|\bbeacon"), ("treehouse", r"\btree ?house|\btree fort"),
    ("greenhouse", r"\bgreen ?house|\bglass ?house|\bconservatory|\borangery"), ("windmill", r"\bwind ?mill|\bmill\b|\bwatermill"),
    ("skyscraper", r"\bsky ?scraper|\boffice|\bapartment|\btower block|\bhigh ?rise|\bhotel|\bcondo|\bempire state|\bburj|\bcorporate|\bheadquarters|\bhq\b|\bflats\b|\bcyber ?punk tower|\bneon tower"),
    ("castle", r"\bcastle|\bfort\b|\bfortress|\bcitadel|\bstronghold|\bkeep\b|\bbastion|\bkingdom"),
    ("watchtower", r"\bwatch ?tower|\blookout|\bguard ?tower|\bfire tower"),
    ("round_tower", r"\bwizard|\bmage\b|\bwitch|\bsorcer|\bround tower|\bturret|\bclock tower|\bbig ben|\bpisa|\bminaret tower|\btower\b|\bspire\b"),
    ("igloo", r"\bigloo|\bsnow ?house|\bice ?house"), ("bridge", r"\bbridge|\baqueduct|\bviaduct"), ("fountain", r"\bfountain"),
    ("well", r"\bwishing well|\bwell\b"),
    ("obelisk", r"\bobelisk|\bmonument|\bmonolith|\bmemorial|\bpillar\b|\btotem"),
    ("statue", r"\bstatue|\bsculpture|\bcolossus|\bbust\b|\bfigure\b|\bliberty"),
    ("observatory", r"\bobservatory|\bplanetarium|\bdome\b|\bspace station|\bmoon base|\bmars base|\bbiodome|\bbio dome|\bradar"),
    ("ship", r"\bship|\bgalleon|\bpirate|\bboat|\byacht|\bcanoe|\bsubmarine|\bark\b|\bferry|\btitanic"),
    ("barn", r"\bbarn|\bstable|\bcoop\b|\bsilo"),
    ("farm", r"\bfarm|\branch|\borchard|\bvineyard"), ("tent", r"\btent|\bcamp\b|\bcampsite|\bteepee|\btipi|\bwigwam|\bcircus|\bmarquee"),
    ("gazebo", r"\bgazebo|\bpavilion|\bbandstand|\bpergola"),
    ("hut", r"\bhut\b|\bshack|\byurt|\bround ?house|\brondavel|\bmud house"),
    ("shop", r"\bshop|\bstore\b|\bmarket|\bcafe|\bcoffee|\bbakery|\brestaurant|\bdiner|\bpub\b|\btavern|\binn\b|\bbar\b|\bpizz|\bburger|\bboutique|\bkiosk|\bstall\b|\bsalon|\bpharmacy|\bbookshop|\bice cream"),
    ("mansion", r"\bmansion|\bmanor|\bvilla|\bchateau|\bestate\b|\bwhite house|\bstately|\bhaunted house|\bhaunted mansion"),
    ("modern", r"\bmodern|\bcontemporary|\bminimalis|\bfuturistic|\bhigh ?tech|\beco house|\bglass house"),
    ("cabin", r"\bcabin|\blog house|\blodge|\bchalet|\bski"), ("cottage", r"\bcottage|\bthatched|\bfairy house|\bgingerbread|\bcandy house"),
    ("orb", r"\bpumpkin|\bapple house|\borange house|\bwatermelon|\begg\b|\bglobe|\bsphere|\bball\b|\bplanet|\bbubble house|\bsnow ?globe"),
    ("bigtree", r"\bgiant tree|\bbig tree|\bworld tree|\btree of life|\boak tree|\btree\b|\bwillow|\bredwood"),
    ("house", r"\bhouse|\bhome\b|\bbungalow|\bshed\b|\bhousing|\bdwelling|\bresidence|\bfarmhouse|\btownhouse|\bkennel"),
    ("greek", r"\btemple|\bcourthouse"),
    ("wall", r"\bgreat wall|\bcity wall|\bdefen[cs]e wall|^\s*(a |the )?(big |long |stone |tall )*wall\s*$"),
    ("statue", r"\bdragon|\blion\b|\bcat\b|\bdog\b|\bhorse\b|\bbear\b|\beagle|\bwolf\b|\bunicorn|\brobot|\bmecha\b|\bgolem|\bknight|\bking\b|\bqueen\b|\bdinosaur|\bt ?rex|\belephant|\bowl\b|\bwhale|\bshark|\bsnake|\bfrog|\bduck|\bpig\b|\bcow\b|\bmonkey|\bgorilla|\bhero|\bangel|\bwarrior|\bgiant\b|\btitan|\bgod\b|\bgoddess|\bman\b|\bwoman\b|\bperson|\bskull"),
]
# generic building words: when nothing else matches these give the custom builder a hint for its shape
GENERIC_HINTS = [
    (r"museum|bank|court|library|town hall|city hall|parliament|capitol|senate|university|college|academy|opera|theat(er|re)|gallery|embassy", dict(columns=True, roof_style="flat")),
    (r"factory|warehouse|forge|power ?plant|mill works|refinery|workshop|smithy|blacksmith|brewery|lab\b|laborator", dict(factory=True, roof_style="flat")),
    (r"school|hospital|station|police|garage|mall|block|hall|gym|cinema|airport|hangar|prison|jail|bunker|base\b|barracks|fire station|clinic|hq", dict(roof_style="flat")),
    (r"guild|headquarters|lair|hideout|den\b|keep|manor|estate", dict(towers=2)),
]
STYLES = [  # name, regex, palette, default roof for the custom builder, extra effects
    ("floating", r"floating|flying|sky ?island|in the sky|in the clouds|levitat|hover|cloud", dict(), None, {"floating"}),
    ("cyberpunk", r"cyber|neon|synthwave|vaporwave|blade ?runner|sci ?fi|scifi|futur|hologram|tron\b",
     dict(wall=bl.BLACK_WOOL, trim=bl.PINK_WOOL, pillar=bl.BLUE_WOOL, roof=bl.CONCRETE, floor=bl.CONCRETE, accent=bl.PINK_WOOL), "flat", {"neon"}),
    ("underwater", r"under ?water|under the sea|undersea|ocean|sea ?bed|seafloor|atlantis|mermaid|aquatic|coral|deep sea|submerged",
     dict(wall=bl.BLUE_WOOL, trim=bl.WHITE_STONE, pillar=bl.WHITE_STONE, roof=bl.GLASS, accent=bl.GOLD_BLOCK, floor=bl.SAND), "dome", {"bubble"}),
    ("spooky", r"haunted|spooky|creepy|ghost|horror|gothic|vampire|dracula|halloween|witch|zombie|scary|dark lord|\bevil|necro|cursed|abandoned",
     dict(wall=bl.DARK_WOOD, trim=bl.BLACK_WOOL, pillar=bl.BLACK_WOOL, roof=bl.BLACK_WOOL, floor=bl.DARK_WOOD, base=bl.MOSSY, accent=bl.LANTERN), "spire", {"ruined_light"}),
    ("ice", r"\bice\b|icy|frozen|frost|snow|winter|arctic|polar|glacier|crystal",
     dict(wall=bl.SNOW, trim=bl.WHITE_STONE, pillar=bl.GLASS, roof=bl.GLASS, floor=bl.SNOW, base=bl.SNOW, accent=bl.BLUE_WOOL), "spire", {"snowcap"}),
    ("candy", r"candy|sweet|gingerbread|chocolate|cake|cupcake|lollipop|dessert|sugar|donut|ice cream",
     dict(wall=bl.PINK_WOOL, trim=bl.WHITE_STONE, pillar=bl.RED_WOOL, roof=bl.DARK_WOOD, accent=bl.YELLOW_WOOL), "gable", {"stripes"}),
    ("egyptian", r"egypt|pharaoh|desert|sahara|nile|cleopatra",
     dict(wall=bl.SANDSTONE, trim=bl.GOLD_BLOCK, pillar=bl.SANDSTONE, roof=bl.SANDSTONE, accent=bl.GOLD_BLOCK, base=bl.SANDSTONE), "flat", set()),
    ("arabian", r"arab|persian|sultan|morocc|aladdin|middle east|mughal|indian|taj|bollywood|maharaja",
     dict(wall=bl.WHITE_STONE, trim=bl.SANDSTONE, roof=bl.GOLD_BLOCK, accent=bl.GOLD_BLOCK), "onion", set()),
    ("russian", r"russia|kremlin|st basil|soviet|slavic|onion",
     dict(wall=bl.RED_WOOL, trim=bl.WHITE_STONE, roof=bl.GREEN_WOOL, accent=bl.GOLD_BLOCK), "onion", set()),
    ("viking", r"viking|norse|nordic|scandinav|longhouse|mead hall|valhalla",
     dict(wall=bl.LOG, trim=bl.DARK_WOOD, pillar=bl.DARK_WOOD, roof=bl.THATCH, accent=bl.RED_WOOL), "gable", set()),
    ("elven", r"\belf|elven|fairy|faerie|enchanted|magic|mystic|forest|jungle|druid|nature|treetop|overgrown|garden house",
     dict(wall=bl.LOG, trim=bl.VINE_BLOCK, pillar=bl.LOG, roof=bl.LEAVES, accent=bl.CHERRY_LEAVES), "cone", {"vines"}),
    ("steampunk", r"steam ?punk|victorian|industrial|clockwork|brass|copper",
     dict(wall=bl.BRICKS, trim=bl.DARK_WOOD, pillar=bl.DARK_WOOD, roof=bl.CONCRETE, accent=bl.GOLD_BLOCK), "hip", {"chimneys"}),
    ("tropical", r"tropical|beach|hawai|tiki|caribbean|surf|bamboo|polynes|jungle hut",
     dict(wall=bl.PLANKS, trim=bl.LOG, pillar=bl.LOG, roof=bl.THATCH, floor=bl.PLANKS, accent=bl.YELLOW_WOOL), "hip", set()),
    ("lava", r"lava|hell|inferno|nether|demon|fire|volcan|magma|dragon ?lair",
     dict(wall=bl.BLACK_WOOL, trim=bl.RED_WOOL, pillar=bl.BRICKS, roof=bl.BRICKS, accent=bl.YELLOW_WOOL, base=bl.BLACK_WOOL), "spire", set()),
    ("royal", r"royal|golden|luxur|king'?s|queen'?s|imperial|majestic|fancy|rich|billionaire",
     dict(wall=bl.WHITE_STONE, trim=bl.GOLD_BLOCK, pillar=bl.WHITE_STONE, roof=bl.BLUE_WOOL, accent=bl.GOLD_BLOCK), "dome", set()),
    ("space", r"\bspace\b|alien|martian|mars|moon|lunar|galac|cosmic|star ?wars|astronaut",
     dict(wall=bl.CONCRETE, trim=bl.WHITE_STONE, pillar=bl.CONCRETE, roof=bl.GLASS, accent=bl.GREEN_WOOL), "dome", set()),
    ("medieval", r"mediev|middle ages|feudal|tudor|knight|rustic|old town|village",
     dict(wall=bl.WHITE_STONE, trim=bl.DARK_WOOD, pillar=bl.DARK_WOOD, roof=bl.THATCH, base=bl.COBBLE), "gable", set()),
    ("rainbow", r"rainbow|colou?rful|pride|unicorn|lgbt|multicolou?r|party", dict(), "gable", {"rainbow"}),
    ("ruined", r"ruin|destroyed|broken|crumbl|ancient|lost city|decay|wrecked|post apocalyp",
     dict(wall=bl.MOSSY, trim=bl.STONE_BRICKS, pillar=bl.STONE_BRICKS, roof=bl.MOSSY), "flat", {"ruined"}),
]
SHAPES = [("round", r"\bround|circular|cylind|spheric|\bdome shaped"), ("L", r"\bl ?shaped"), ("cross", r"\bcross ?shaped|\bplus shaped"),
          ("rect", r"\bsquare|\bboxy|\bcube|\brectang")]
SIZE_WORDS = [(r"\btiny|\bminiature|\bmini\b|\bteeny|\bitty|\bbaby\b|\bmicro|\bdoll ?house|\bbird ?house|\bdog ?house", 0.55),
              (r"\bsmall|\blittle|\bcompact|\bcosy|\bcozy|\bmodest", 0.75), (r"\bmedium|\bnormal|\baverage", 1.0),
              (r"\bbig\b|\blarge|\bbigger", 1.3), (r"\bhuge|\bmassive|\bgrand\b|\bmonumental|\bmega\b|\bvast|\bimmense", 1.65),
              (r"\bgiant|\benormous|\bcolossal|\bgigantic|\bepic\b|\btitanic|\bhumongous|\bginormous|\bbiggest|\bultimate", 2.0)]
NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
             "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "a pair of": 2,
             "double": 2, "twin": 2, "triple": 3, "a couple of": 2, "several": 3, "many": 4}
MATERIALS = [(r"red brick", bl.BRICKS), (r"dark ?(wood|oak)|spruce|ebony|chocolate|mahogany|walnut", bl.DARK_WOOD),
             (r"red ?wood|lacquer|cherry ?wood", bl.RED_WOOD),
             (r"stone ?brick", bl.STONE_BRICKS), (r"white ?stone|marble|quartz|limestone|ivory|pearl|porcelain|paper|birch", bl.WHITE_STONE),
             (r"sand ?stone|adobe|clay|terracotta|\bmud\b", bl.SANDSTONE), (r"cobble", bl.COBBLE), (r"moss|overgrown", bl.MOSSY),
             (r"brick", bl.BRICKS), (r"stone|rock|granite|basalt", bl.STONE_BRICKS),
             (r"concrete|cement|steel|metal|\biron\b|chrome|titanium|aluminium|aluminum", bl.CONCRETE),
             (r"glass|crystal|diamond", bl.GLASS), (r"\bgold|golden", bl.GOLD_BLOCK), (r"snow|\bice\b", bl.SNOW),
             (r"thatch|straw|\bhay\b|bamboo", bl.THATCH), (r"\blogs?\b", bl.LOG), (r"wood|oak|plank|timber|wooden", bl.PLANKS),
             (r"\btiles?\b|slate", bl.ROOF_TILE), (r"\bvines?\b|\bivy\b", bl.VINE_BLOCK), (r"wool|cloth|fabric|cotton|cloud", bl.WOOL),
             (r"\bsand\b", bl.SANDSTONE), (r"obsidian|coal", bl.BLACK_WOOL), (r"emerald|jade", bl.GREEN_WOOL),
             (r"ruby", bl.RED_WOOL), (r"sapphire|lapis", bl.BLUE_WOOL), (r"lava|magma", bl.RED_WOOL)]
COLOURS = [(r"\bred\b|crimson|scarlet|maroon", bl.RED_WOOL), (r"\bwhite\b", bl.WHITE_STONE), (r"\bblack\b|\bdark\b", bl.BLACK_WOOL),
           (r"\bblue\b|navy|cyan|teal|aqua|turquoise|azure|\bsky blue", bl.BLUE_WOOL), (r"\byellow\b|lemon", bl.YELLOW_WOOL),
           (r"\bgreen\b|\blime\b|olive", bl.GREEN_WOOL), (r"\bpink\b|magenta|rose\b|fuchsia", bl.PINK_WOOL),
           (r"\bgr[ae]y\b|silver", bl.CONCRETE), (r"\bbrown\b|\btan\b", bl.DARK_WOOD), (r"\borange\b|\bbeige\b|\bbronze\b", bl.SANDSTONE),
           (r"\bpurple\b|violet|lilac|lavender", bl.BLUE_WOOL)]
FEATURES = [("garden", r"garden|flowers|hedge|yard|lawn"), ("moat", r"\bmoat"), ("pond", r"\bpond|\blake\b|koi"),
            ("cherry", r"cherry|sakura|blossom"), ("lanterns", r"lantern|lamps?\b|torch|lights\b"), ("stairs", r"stair|steps"),
            ("chimney", r"chimney|smokestack"), ("path", r"\bpath|walkway|driveway|\broad\b"), ("fence", r"fence|picket"),
            ("flag", r"\bflags?\b|banner"), ("pool", r"\bpool|swimming"), ("trees", r"(?<!cherry )(?<!blossom )\btrees\b|forest|woods\b"),
            ("torii", r"torii")]
FEATURE_NAMES = {"garden": "a garden", "moat": "a moat", "pond": "a pond", "cherry": "cherry trees", "lanterns": "lanterns",
                 "stairs": "stairs", "chimney": "a chimney", "path": "a path", "fence": "a fence", "flag": "a flag",
                 "pool": "a pool", "trees": "trees", "torii": "a torii gate"}
FRIENDLY = {bl.STONE: "rough stone", bl.STONE_BRICKS: "stone", bl.COBBLE: "cobblestone", bl.PLANKS: "wood", bl.LOG: "logs", bl.DARK_WOOD: "dark wood",
            bl.RED_WOOD: "red wood", bl.ROOF_TILE: "dark roof tiles", bl.WHITE_STONE: "white stone", bl.GOLD_BLOCK: "gold",
            bl.GLASS: "glass", bl.BRICKS: "bricks", bl.SANDSTONE: "sandstone", bl.CONCRETE: "concrete", bl.SNOW: "snow",
            bl.THATCH: "thatch", bl.MOSSY: "mossy stone", bl.WOOL: "white wool", bl.LEAVES: "leaves",
            bl.CHERRY_LEAVES: "cherry blossom", bl.AUTUMN_ORANGE: "orange autumn leaves",
            bl.AUTUMN_RED: "red autumn leaves", bl.AUTUMN_GOLD: "golden autumn leaves", bl.AUTUMN_BROWN: "brown autumn leaves", bl.LANTERN: "lanterns", bl.VINE_BLOCK: "vine blocks"}
LABEL_OVERRIDE = [(r"\bdojo", "dojo"), (r"\btaj|\bmosque", "domed mosque"), (r"\bkremlin|\bst basil", "onion-domed palace"),
                  (r"\beiffel", "Eiffel-style tower"), (r"\bbig ben|\bclock tower", "clock tower"), (r"\bwizard|\bmage\b", "wizard tower"),
                  (r"\bstonehenge", "Stonehenge"), (r"\bpumpkin", "pumpkin house"), (r"\bigloo", "igloo"),
                  (r"\bsubmarine", "submarine-ish boat"), (r"\bdog ?house|\bkennel", "dog house"), (r"\bbird ?house", "bird house")]

# ------------------------------------------------------------------ typo tolerance (offline, difflib)
_COMMON = set("""a an the of with and or to in on at by for from my me i we you it its is be make build create please can could
would want need some any big small large huge tiny giant tall short long wide high low old new very really super nice cool
cute pretty awesome beautiful ugly simple basic little one two three four five six seven eight nine ten blocks block floors
floor storey storeys story stories tier tiers level levels roof roofs walls wall door doors window windows made out like that
this has have having near next top side front back inside outside around shaped style themed theme kind sort type looks
horse mouse hose host moss boss most post toast tower towers castle house temple place places plane books book read
reading space spaces where there their thing things stuff something anything everything somewhere live living play
playing hide hiding secret party friends family people person cats dogs world city town land lands water fire earth
medieval egyptian japanese chinese futuristic cyberpunk underwater haunted palace mansion modern ancient spooky
pointy tall wide round square shape shaped colour color colours colors cool epic awesome""".split())


def _vocab():
    v = set(_COMMON)
    srcs = [rx for _, rx in KIND_RULES] + [rx for _, rx, *_ in STYLES] + [rx for rx, _ in MATERIALS + COLOURS + SIZE_WORDS] + \
           [rx for _, rx in FEATURES] + [rx for rx, _ in GENERIC_HINTS] + [AUTUMN_RX.pattern]
    for rx in srcs:
        r2 = rx.replace("\\b", " ").replace(" ?", "")
        v.update(re.findall(r"[a-z]{4,}", r2))
    return v


_VOCAB = None


def correct_typos(t):
    """Fix misspelt words against Vine AI's vocabulary ('castel' -> 'castle', 'pyrimid' -> 'pyramid')."""
    global _VOCAB
    import difflib
    if _VOCAB is None:
        _VOCAB = sorted(_vocab())
    vs = set(_VOCAB)
    out = []
    for w in t.split():
        if len(w) < 4 or w.isdigit() or w in vs or any(w.startswith(k) for k in vs if len(k) >= 4 and len(w) - len(k) <= 3):
            out.append(w); continue
        m = difflib.get_close_matches(w, _VOCAB, n=1, cutoff=0.85 if len(w) <= 5 else 0.78)
        out.append(m[0] if m else w)
    return " ".join(out)


class Plan:
    def __init__(self, text):
        self.text = text or ""
        self.kind = "generic"
        self.scale = 1.0
        self.height = self.width = self.tiers = self.floors = self.towers = None
        self.mats, self.features = {}, set()
        self.castle = self.fairy = self.small_house = self.circus = self.boat = self.columns = self.factory = False
        self.mosque = self.tall = self.spire = False
        self.roof_style = self.shape = self.style = None
        self.style_pal, self.effects = {}, set()
        self.label = None
        self.unknown = False
        self.norm = ""


def _num(tok):
    return int(tok) if tok.isdigit() else NUM_WORDS.get(tok)


def _block_for(word):
    for rx, b in MATERIALS + COLOURS:
        if re.search(rx, " " + word + " "):
            return b
    return None


def _normalize(text):
    t = (text or "").lower()
    t = re.sub(r"[^a-z0-9' ]+", " ", t.replace("-", " ").replace("_", " "))
    t = re.sub(r"^\s*(/?build|please|can you|could you|i want|i'd like|make me|make|build me|create|generate|construct|give me)\b\s*", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return " " + correct_typos(t) + " "


def interpret(text):
    """Free text -> Plan. Rule based + typo tolerant; never fails (unknown requests become an invented custom building)."""
    t = _normalize(text)
    p = Plan(text)
    p.norm = t.strip()
    main = re.split(r"\b(with|and|plus|surrounded by|next to|beside|near|having|that has|featuring|including|on top of|in front of|behind)\b", t)[0]
    scopes = (main,) if (main != t and any(re.search(rx, main) for rx, _ in GENERIC_HINTS)) else (main, t)
    for scope in scopes:
        for kind, rx in KIND_RULES:
            if re.search(rx, scope):
                p.kind = kind
                break
        if p.kind != "generic":
            break
    else:
        p.unknown = bool(t.strip())
    for name, rx, pal, roof, eff in STYLES:
        if re.search(rx, t):
            if p.style is None:
                p.style, p.roof_style = name, roof
            for k, v in pal.items():
                p.style_pal.setdefault(k, v)
            p.effects |= eff
    # disambiguation between kinds and styles
    if p.kind == "round_tower" and p.style in ("cyberpunk", "space") and not re.search(r"wizard|clock|castle|mage", t): p.kind = "skyscraper"
    if p.kind == "palace" and re.search(r"\btaj|mosque|minaret", t): p.mosque = True
    if p.kind == "japanese" and re.search(r"castle|fort|palace", t): p.castle = True
    if p.kind == "japanese" and re.search(r"\bhouse|\bhome|\btea ?house|\bdojo|\bninja|\bonsen|\bryokan", t): p.small_house = True
    if p.kind == "castle" and re.search(r"fairy|disney|princess|magic|fantasy|cinderella|elsa|sleeping beauty", t): p.fairy = True
    if p.kind == "tent" and "circus" in t: p.circus = True
    if p.kind == "ship" and re.search(r"boat|canoe|yacht", t) and not re.search(r"pirate|galleon|ship", t): p.boat = True
    if p.kind == "skyscraper" and p.style == "cyberpunk": p.effects.add("neon")
    if p.style == "medieval" and p.kind not in ("generic", "house", "cottage", "shop", "barn"): p.style_pal = {}
    if p.kind == "mansion" and re.search(r"haunted", t) and p.style is None: p.style = "spooky"
    if p.kind in ("generic", "house", "mansion") and p.style == "underwater" and re.search(r"palace|castle|city|kingdom", t): p.kind, p.unknown = "palace", False
    for rx, kw in GENERIC_HINTS:
        if p.kind == "generic" and re.search(rx, t):
            for k, v in kw.items():
                if k == "roof_style" and p.roof_style and p.style: continue
                setattr(p, k, v)
            p.unknown = False
    for name, rx in SHAPES:
        if re.search(rx, t): p.shape = name; break
    if "flat roof" in t: p.roof_style = "flat"
    if re.search(r"\bdome", t) and p.kind == "generic": p.roof_style = "dome"
    if re.search(r"hip(ped)? roof", t): p.roof_style = "hip"
    if re.search(r"pointy|pointed|spire|steeple|needle|antenna", t): p.spire = True
    if re.search(r"onion", t): p.roof_style = "onion"
    if re.search(r"curved roof|pagoda roof|asian roof", t): p.roof_style = "eave"
    if re.search(r"\btall\b|\btowering|\bskinny|\bslim", t): p.tall = True
    for rx, s in SIZE_WORDS:
        if re.search(rx, t): p.scale = s
    N = r"(\d+|" + "|".join(NUM_WORDS) + r")"
    m = re.search(N + r"\s*(blocks?\s*|meters?\s*|metres?\s*|m\s+)?(tall|high)", t)
    if m: p.height = max(4, min(MAX_DIM - 6, _num(m.group(1))))
    m = re.search(N + r"\s*(blocks?\s*|meters?\s*|metres?\s*)?(wide|across|long)", t) or re.search(r"(\d+)\s*(x|by)\s*\d+", t)
    if m: p.width = max(5, min(MAX_DIM - 6, _num(m.group(1))))
    m = re.search(N + r"\s*(tiers?|tiered|roofs|storeys?|stories|story|levels?)", t)
    if m: p.tiers = max(1, min(9, _num(m.group(1))))
    m = re.search(N + r"\s*(floors?|storeys?|stories|story|levels?)", t)
    if m: p.floors = max(1, min(13, _num(m.group(1))))
    m = re.search(N + r"\s*(towers?|turrets?|spires?|minarets?)", t)
    if m: p.towers = max(0, min(6, _num(m.group(1))))
    elif re.search(r"\b(towers|turrets)\b", t): p.towers = 4
    elif re.search(r"\b(tower|turret)\b", t) and p.kind == "generic": p.towers = 1
    if p.kind == "skyscraper" and p.floors and not p.height: p.height = max(12, min(56, p.floors * 4))
    if p.tall and p.kind in ("skyscraper", "round_tower", "lighthouse", "watchtower", "obelisk", "rocket", "eiffel") and not p.height:
        p.height = int(GEN[p.kind][2] * 1.4)
    if re.search(r"\b(dog|bird) ?house|\bkennel", t): p.scale = min(p.scale, 0.55)
    for rx, lab in LABEL_OVERRIDE:
        if re.search(rx, t): p.label = lab; break
    rest = t
    for target, rx in (("roof", r"roofs?"), ("wall", r"walls?"), ("pillar", r"(pillars?|columns?|posts?)"),
                       ("floor", r"floors?"), ("base", r"(base|foundation|platform)"), ("trim", r"(trim|edges?|details?)"),
                       ("glass", r"windows?")):
        for m in re.finditer(r"([a-z]+(?: [a-z]+)?)\s+" + rx + r"\b", t):
            words = m.group(1).split()
            for cand in (" ".join(words), words[-1]):
                b = _block_for(cand)
                if b is not None:
                    p.mats[target] = b
                    rest = rest[:m.start()] + " " * (m.end() - m.start()) + rest[m.end():]
                    break
    rest = re.sub(r"cherry|sakura|blossom|lanterns?|gold(en)? (tip|spire)|red brick", lambda mm: "brick" if mm.group(0) == "red brick" else " ", rest)
    if p.style:                                          # style words already pick colours; don't double count them
        for name, rx, *_ in STYLES:
            if name == p.style: rest = re.sub(rx, " ", rest)
    found = []
    for rx, b in MATERIALS + COLOURS:
        for m in re.finditer(rx, rest):
            found.append((m.start(), b))
            rest = rest[:m.start()] + " " * (m.end() - m.start()) + rest[m.end():]
    found.sort()
    order = {"japanese": ["pillar", "wall", "roof"], "pagoda": ["pillar", "wall", "roof"], "pagoda_cn": ["pillar", "wall", "roof"],
             "greek": ["pillar", "wall", "roof"], "mushroom": ["roof", "wall", "trim"], "orb": ["wall", "trim", "roof"],
             "palace": ["wall", "roof", "trim"], "rocket": ["wall", "roof", "trim"]}.get(p.kind, ["wall", "trim", "roof"])
    for (_, b), slot in zip(found, [s for s in order if s not in p.mats]):
        p.mats[slot] = b
    if p.kind == "orb" and "wall" not in p.mats:
        for rx, b in ((r"pumpkin|orange", bl.YELLOW_WOOL), (r"apple|ball", bl.RED_WOOL), (r"watermelon", bl.GREEN_WOOL),
                      (r"globe|planet", bl.BLUE_WOOL), (r"snow ?globe|bubble", bl.GLASS)):
            if re.search(rx, t): p.mats["wall"] = b
    for name, rx in FEATURES:
        if re.search(rx, t): p.features.add(name)
    if p.kind == "japanese" and "shrine" in t: p.features.add("torii")
    if p.kind == "torii": p.features.discard("torii")
    if p.columns or p.factory or (p.roof_style and p.kind == "generic" and not p.style): p.unknown = False
    return p


# ------------------------------------------------------------------ style effects (applied after the building is drawn)
NEON = [bl.PINK_WOOL, bl.BLUE_WOOL, bl.LANTERN, bl.YELLOW_WOOL]
RAINBOW = [bl.RED_WOOL, bl.SANDSTONE, bl.YELLOW_WOOL, bl.GREEN_WOOL, bl.BLUE_WOOL, bl.PINK_WOOL]
STRUCT_KEEP = (AIR, bl.WATER, bl.GLASS, bl.LANTERN, bl.GRASS, bl.GRAVEL, bl.DIRT, bl.SAND, bl.LEAVES, bl.CHERRY_LEAVES) + bl.AUTUMN_LEAVES


def _outer(c, k):
    x, y, z = k
    return any((x + dx, y + dy, z) not in c.b for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))


def apply_effects(c, p, P):
    eff = p.effects
    if not eff:
        return c
    rng = random.Random(zlib.crc32(p.text.encode("utf-8", "ignore")) ^ 0x5EED)
    if "neon" in eff:
        for k, v in list(c.b.items()):
            if v not in STRUCT_KEEP and k[2] >= 1 and _outer(c, k) and (k[2] % 4 == 0):
                c.b[k] = NEON[(k[2] // 4) % len(NEON)]
    if "rainbow" in eff:
        for k, v in list(c.b.items()):
            if v not in STRUCT_KEEP and k[2] >= 0:
                c.b[k] = RAINBOW[(k[2] // 2) % len(RAINBOW)]
    if "stripes" in eff:
        for k, v in list(c.b.items()):
            if v == P.wall and (k[0] + k[1] + k[2]) % 4 == 0:
                c.b[k] = P.trim
    if "vines" in eff:
        for k, v in list(c.b.items()):
            if v not in STRUCT_KEEP and k[2] >= 1 and _outer(c, k) and rng.random() < 0.12:
                c.b[k] = bl.VINE_BLOCK
    if "chimneys" in eff:
        x0, x1, y0, y1 = c.footprint(); z1 = c.bounds(True)[5]
        for x in (x0 + 1, x1 - 1):
            for z in range(1, min(z1 + 3, MAX_DIM - 2)):
                c.put(x, y1 - 1, z, bl.BRICKS)
    if "snowcap" in eff:
        tops = {}
        for (x, y, z), v in c.b.items():
            if v not in (AIR, bl.WATER) and z >= 0:
                tops[(x, y)] = max(tops.get((x, y), -9), z)
        for (x, y), z in tops.items():
            c.soft(x, y, z + 1, bl.SNOW)
    if "ruined" in eff or "ruined_light" in eff:
        frac = 0.18 if "ruined" in eff else 0.05
        z1 = c.bounds(True)[5]
        for k, v in list(c.b.items()):
            if v not in (AIR, bl.WATER) and k[2] > 2 and rng.random() < frac * (k[2] / max(1.0, z1)) * 2:
                c.b[k] = AIR
            elif v not in STRUCT_KEEP and k[2] >= 0 and "ruined" in eff and rng.random() < 0.15:
                c.b[k] = bl.MOSSY
    if "bubble" in eff:
        x0, x1, y0, y1, z0, z1 = c.bounds(True)
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        R = max(x1 - x0, y1 - y0) / 2.0 + 3
        Hh = z1 + 3
        for x in range(int(cx - R) - 1, int(cx + R) + 2):
            for y in range(int(cy - R) - 1, int(cy + R) + 2):
                d2 = ((x - cx) / R) ** 2 + ((y - cy) / R) ** 2
                if d2 <= 1.0:
                    c.soft(x, y, -1, bl.SAND)
                    zz = int(Hh * math.sqrt(max(0.0, 1 - d2)))
                    zin = int(Hh * math.sqrt(max(0.0, 1 - ((x - cx) / (R - 1)) ** 2 - ((y - cy) / (R - 1)) ** 2))) if R > 1 else 0
                    for z in range(max(0, zin), zz + 1):
                        if d2 > 0.0:
                            c.soft(x, y, z, bl.GLASS)
                    if d2 > 0.55 and rng.random() < 0.06:
                        col = rng.choice([bl.PINK_WOOL, bl.YELLOW_WOOL, bl.RED_WOOL, bl.GREEN_WOOL])
                        for z in range(0, rng.randint(1, 3)):
                            c.soft(x, y, z, col)
        for k in [k for k in c.b if c.b[k] == bl.GLASS and abs(k[0] - cx) <= 1 and k[1] < cy - R + 3 and k[2] <= 2]:
            c.b[k] = AIR                                 # entrance through the bubble
    if "floating" in eff:
        lift = 7
        nb = {(x, y, z + lift): v for (x, y, z), v in c.b.items()}
        cols = {}
        for (x, y, z), v in c.b.items():
            if v != AIR and z <= 0:
                cols[(x, y)] = 1
        x0, x1, y0, y1 = c.footprint()
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        R = max(2.0, max(x1 - x0, y1 - y0) / 2.0 + 1)
        for x in range(int(cx - R) - 1, int(cx + R) + 2):
            for y in range(int(cy - R) - 1, int(cy + R) + 2):
                d = math.hypot(x - cx, y - cy) / R
                if d <= 1.0:
                    depth = int((1 - d) * (lift - 1)) + 1
                    for i in range(depth):
                        k = (x, y, lift - 1 - i)
                        if k not in nb:
                            nb[k] = bl.GRASS if i == 0 else (bl.DIRT if i < 3 else bl.STONE)
        c.b = nb
    return c

def add_features(c, p, feats, P):
    if not feats:
        return
    x0, x1, y0, y1 = c.footprint()
    cx = (x0 + x1) // 2
    rng = random.Random(zlib.crc32(p.text.encode("utf-8", "ignore")))
    if "moat" in feats:
        m0, m1, n0, n1 = x0 - 4, x1 + 4, y0 - 4, y1 + 4
        for x in range(m0 - 1, m1 + 2):
            for y in range(n0 - 1, n1 + 2):
                if not (m0 + 1 < x < m1 - 1 and n0 + 1 < y < n1 - 1):
                    c.put(x, y, -1, bl.WATER); c.put(x, y, -2, bl.WATER)
                    for z in (0, 1, 2): c.put(x, y, z, AIR)
        for x in (cx - 1, cx, cx + 1):
            for y in range(n0 - 1, n0 + 3): c.put(x, y, -1, bl.PLANKS)
        x0, x1, y0, y1 = m0 - 1, m1 + 1, n0 - 1, n1 + 1
    if "garden" in feats:
        for x in range(x0 - 3, x1 + 4):
            for y in range(y0 - 3, y1 + 4):
                if x0 <= x <= x1 and y0 <= y <= y1 or c.get(x, y, 0) not in (None, AIR):
                    continue
                c.soft(x, y, -1, bl.GRASS)
                if abs(x - cx) > 1:
                    if x in (x0 - 3, x1 + 3) or y in (y0 - 3, y1 + 3):
                        c.soft(x, y, 0, bl.LEAVES)
                    elif rng.random() < 0.12:
                        c.soft(x, y, 0, rng.choice([bl.RED_WOOL, bl.YELLOW_WOOL, bl.PINK_WOOL, bl.BLUE_WOOL]))
    if feats & {"path", "lanterns", "torii"}:
        for y in range(y0 - 9, y0):
            for x in (cx - 1, cx, cx + 1):
                c.put(x, y, -1, bl.GRAVEL)
                if c.get(x, y, 0) in (bl.LEAVES, bl.RED_WOOL, bl.YELLOW_WOOL, bl.PINK_WOOL, bl.BLUE_WOOL): c.put(x, y, 0, AIR)
    if "lanterns" in feats:
        for y in range(y0 - 8, y0 - 1, 3):
            for x in (cx - 3, cx + 3):
                c.put(x, y, 0, bl.STONE_BRICKS); c.put(x, y, 1, bl.LANTERN); c.put(x, y, 2, bl.ROOF_TILE)
    if "torii" in feats and p.kind != "torii":
        ty, w, h = y0 - 6, 3, 7
        for x in (cx - w, cx + w): c.box(x, x, ty, ty, 0, h - 1, bl.RED_WOOD)
        c.box(cx - w - 1, cx + w + 1, ty, ty, h - 2, h - 2, bl.RED_WOOD)
        c.box(cx - w - 2, cx + w + 2, ty, ty, h, h, bl.BLACK_WOOL)
        c.put(cx - w - 2, ty, h + 1, bl.BLACK_WOOL); c.put(cx + w + 2, ty, h + 1, bl.BLACK_WOOL)
    for name, leaves in (("cherry", bl.CHERRY_LEAVES), ("trees", bl.LEAVES)):
        if name in feats:
            for tx, ty in ((x0 - 4, y0 + 1), (x1 + 4, y0 + 1), (x0 - 4, y1 - 1), (x1 + 4, y1 - 1)):
                tree(c, tx, ty, leaves, h=S(p, 4, 3), r=2.6)
    if "pond" in feats:
        px, py = x1 + 8, (y0 + y1) // 2
        for x in range(px - 5, px + 6):
            for y in range(py - 6, py + 7):
                d = ((x - px) / 4.2) ** 2 + ((y - py) / 5.2) ** 2
                if d <= 1:
                    c.put(x, y, -1, bl.WATER); c.put(x, y, 0, AIR)
                    if d < 0.5: c.put(x, y, -2, bl.WATER)
                elif d <= 1.45:
                    c.soft(x, y, -1, bl.SAND)
    if "pool" in feats:
        for x in range(x0 - 8, x0 - 1):
            for y in range(y0 + 1, y1):
                edge = x in (x0 - 8, x0 - 2) or y in (y0 + 1, y1 - 1)
                c.put(x, y, -1, bl.WHITE_STONE if edge else bl.WATER)
    if "fence" in feats:
        f0, f1, g0, g1 = x0 - 5, x1 + 5, y0 - 5, y1 + 5
        for x in range(f0, f1 + 1):
            if abs(x - cx) > 1: c.soft(x, g0, 0, bl.DARK_WOOD)
            c.soft(x, g1, 0, bl.DARK_WOOD)
        for y in range(g0, g1 + 1):
            c.soft(f0, y, 0, bl.DARK_WOOD); c.soft(f1, y, 0, bl.DARK_WOOD)
    bz1 = c.bounds(True)[5]
    if "chimney" in feats and p.kind not in ("house", "cottage", "cabin"):
        x, y = x1 - 1, y1 - 1
        top = max([z for (a, b, z), v in c.b.items() if a == x and b == y and v != AIR] or [3])
        for z in range(1, min(top + 3, MAX_DIM - 1)): c.put(x, y, z, bl.BRICKS)
    if "flag" in feats:
        tops = [(a, b) for (a, b, z), v in c.b.items() if z == bz1 and v != AIR]
        fx, fy = tops[0] if tops else (0, 0)
        for z in range(bz1 + 1, min(bz1 + 6, MAX_DIM - 2)): c.put(fx, fy, z, bl.LOG)
        c.box(fx + 1, fx + 3, fy, fy, min(bz1 + 4, MAX_DIM - 3), min(bz1 + 5, MAX_DIM - 2), bl.RED_WOOL)
    if "stairs" in feats:                                  # external staircase up the right side
        h = 0
        for z in range(1, bz1 + 1):
            if c.get(x1, (y0 + y1) // 2, z) in (None, AIR): break
            h = z
        for i in range(max(2, h)):
            if y0 + i > y1 + 6: break
            c.put(x1 + 1, y0 + i, i, P.base); c.put(x1 + 2, y0 + i, i, P.base)



AUTUMN_RX = re.compile(r"\bautumn|\bfall\b|\bfall colou?rs?|\bmaple|\bharvest season|\bseptember|\boctober|\bnovember|\bthanksgiving")


def autumnize(c):
    """1.4.0: autumn/fall prompts turn green leaves into a mix of orange, red, golden and brown autumn leaves."""
    for k, v in list(c.b.items()):
        if v == bl.LEAVES:
            x, y, z = k
            mix = (bl.AUTUMN_ORANGE, bl.AUTUMN_GOLD, bl.AUTUMN_RED, bl.AUTUMN_ORANGE, bl.AUTUMN_GOLD, bl.AUTUMN_BROWN)
            g = mix[((x // 4) * 7 + (y // 4) * 13) % 6]
            u = (x * 73856093 ^ y * 19349663 ^ z * 83492791) & 0xFFFF
            c.b[k] = g if u % 100 < 70 else mix[(u >> 7) % 6]
        elif v == bl.GRASS and ((k[0] * 31 + k[1] * 17) & 7) < 3:
            c.b[k] = bl.LEAF_LITTER


def generate(p):
    """Plan -> (Canvas, summary). Oversized builds are shrunk to fit MAX_DIM^3."""
    f, label, nominal, default_feats, uses_height = GEN.get(p.kind, GEN["generic"])
    req = p.scale
    scale = p.scale
    if p.height and not uses_height and p.kind != "generic":
        scale = max(0.4, min(3.0, p.height / float(nominal)))
    if p.width and p.kind != "generic":
        scale = max(0.4, min(3.0, p.width / 14.0))
    pal = Pal(BASE_PAL); pal.update(KIND_PAL.get(p.kind, {})); pal.update(p.style_pal); pal.update(p.mats)
    feats = set(p.features) | default_feats
    for _ in range(14):
        p.scale = scale
        c = Canvas()
        f(c, pal, p)
        add_features(c, p, feats, pal)
        if AUTUMN_RX.search(" " + (p.text or "").lower() + " ") or AUTUMN_RX.search(" " + p.norm + " "):
            autumnize(c)
        c = apply_effects(c, p, pal)
        x0, x1, y0, y1, z0, z1 = c.bounds()
        if max(x1 - x0 + 1, y1 - y0 + 1, z1 - min(z0, 0) + 1) <= MAX_DIM:
            break
        scale *= 0.85
        if p.height: p.height = int(p.height * 0.85)
        if p.floors: p.floors = max(1, int(p.floors * 0.85))
        if p.width: p.width = max(5, int(p.width * 0.85))
    x0, x1, y0, y1, z0, z1 = c.bounds(True)
    W, D, H = x1 - x0 + 1, y1 - y0 + 1, z1 + 1
    lab = p.label or label
    if p.kind in ("japanese", "pagoda", "pagoda_cn"):
        lab = "%d-tier %s" % (max(1, min(9, p.tiers or default_tiers(p))),
                              "Japanese castle" if p.castle else ("Japanese " + (p.label or "house")) if p.small_house else label)
    elif p.fairy: lab = "fairy-tale castle"
    elif p.circus: lab = "circus tent"
    elif p.boat: lab = "boat"
    elif p.kind == "statue" and not re.search(r"statue|sculpture", p.norm):
        noun = re.search(KIND_RULES[-1][1], " " + p.norm + " ")
        lab = "%s statue" % (noun.group(0).strip() if noun else "giant")
    elif p.kind == "generic" and p.norm:
        lab = "custom design for \"%s\"" % (p.text.strip()[:40])
    if p.style and p.kind != "generic" and p.style not in lab.lower():
        lab = p.style + " " + lab
    if p.floors and p.kind in ("house", "mansion", "generic"): lab = "%d-floor %s" % (p.floors, lab)
    if req >= 1.6: lab = "huge " + lab
    elif req <= 0.6: lab = "tiny " + lab
    elif req <= 0.8: lab = "small " + lab
    counts = {}
    for v in c.b.values():
        if v not in (AIR, bl.WATER, bl.GRASS, bl.GRAVEL, bl.DIRT, bl.SAND):
            counts[v] = counts.get(v, 0) + 1
    mats = [FRIENDLY.get(b, bl.name_of(b).lower()) for b, _ in sorted(counts.items(), key=lambda kv: -kv[1])][:3]
    mtxt = (", ".join(mats[:-1]) + " and " + mats[-1]) if len(mats) > 1 else (mats[0] if mats else "blocks")
    fl = [FEATURE_NAMES[k] for k in sorted(feats) if k in FEATURE_NAMES]
    ftxt = (", plus " + (", ".join(fl[:-1]) + " and " if len(fl) > 1 else "") + fl[-1]) if fl else ""
    art = "an" if lab[0].lower() in "aeiou" or lab.startswith(("8-", "11-", "18-")) else "a"
    summary = "Vine AI: building %s %s, about %dx%dx%d, with %s%s." % (art, lab, W, D, H, mtxt, ftxt)
    if p.unknown:
        summary += " (New idea! I invented a design from your words.)"
    return c, summary


def _safe_house(text):
    p = Plan(text); p.kind = "house"
    c = Canvas(); house(c, Pal(BASE_PAL, **KIND_PAL["house"]), p)
    return c, "Vine AI: building a house (I kept it simple for \"%s\")." % (text or "").strip()[:40]


_CACHE = {}


def plan_and_generate(text):
    """Text -> (Canvas, summary). Never raises: any failure falls back to a simple house so a build always happens."""
    key = (text or "").strip()
    if key in _CACHE:
        return _CACHE[key]
    try:
        res = generate(interpret(text))
        if not any(v != AIR for v in res[0].b.values()):
            raise ValueError("empty build")
    except Exception as e:                               # pragma: no cover - safety net
        print("Vine AI fallback for %r: %r" % (text, e))
        res = _safe_house(text)
    if len(_CACHE) > 24:
        _CACHE.clear()
    _CACHE[key] = res
    return res


EXAMPLES = ["Japanese temple", "Medieval castle", "Modern house", "Mushroom house", "Underwater palace", "Cyberpunk neon tower"]
BUILDING_TYPES = ["Japanese temple", "Japanese pagoda (N tiers)", "Japanese castle", "dojo", "torii gate", "Chinese pagoda",
                  "medieval castle", "fairy-tale castle", "house", "cottage", "log cabin", "modern house", "mansion", "palace",
                  "mosque / Taj Mahal", "skyscraper", "lighthouse", "windmill", "pyramid", "step pyramid", "sphinx", "Greek/Roman temple",
                  "church", "cathedral", "barn", "farm", "igloo", "treehouse", "giant tree", "mushroom house", "hobbit hole",
                  "bridge", "great wall", "watchtower", "round/wizard tower", "Eiffel-style tower", "fountain", "well", "obelisk",
                  "statue (any creature)", "stadium/arena", "shop/cafe", "tent", "circus tent", "hut", "gazebo", "arch",
                  "Stonehenge", "observatory/dome", "ship", "boat", "rocket", "UFO", "volcano", "greenhouse", "pumpkin/round house",
                  "styles: cyberpunk, underwater, haunted, ice, candy, egyptian, arabian, russian, viking, elven, steampunk, "
                  "tropical, lava, royal, space, medieval, rainbow, ruined, floating",
                  "custom building (anything else - Vine AI invents one)"]

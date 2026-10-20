"""DREAM VINE - procedural art: logo, icon, sky textures. All original. (c)2026 EX Inc."""
import numpy as np

FONT = {
    "D": ["1110 ", "1001 ", "1001 ", "1001 ", "1001 ", "1001 ", "1110 "],
    "R": ["1110", "1001", "1001", "1110", "1010", "1001", "1001"],
    "E": ["1111", "1000", "1000", "1110", "1000", "1000", "1111"],
    "A": ["0110", "1001", "1001", "1111", "1001", "1001", "1001"],
    "M": ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    "V": ["10001", "10001", "10001", "01010", "01010", "00100", "00100"],
    "I": ["111", "010", "010", "010", "010", "010", "111"],
    "N": ["1001", "1101", "1101", "1011", "1011", "1001", "1001"],
    " ": ["00", "00", "00", "00", "00", "00", "00"],
}


def text_mask(text):
    cols = []
    for ch in text:
        g = FONT[ch]
        w = max(len(r) for r in g)
        m = np.array([[c == "1" for c in r.ljust(w, "0")] for r in g], bool)
        cols.append(m); cols.append(np.zeros((7, 1), bool))
    return np.concatenate(cols[:-1], axis=1)


def logo(px=10):
    """DREAM VINE logo: chunky pixel letters, green->teal gradient, 3D extrusion, vine with leaves. RGBA, row 0 top."""
    m = text_mask("DREAM VINE")
    h, w = m.shape
    pad = 3
    W, H = (w + pad * 2) * px, (h + pad * 2 + 2) * px
    img = np.zeros((H, W, 4), np.uint8)
    rng = np.random.RandomState(7)
    def cell(x, y, c):
        y0, x0 = (y + pad) * px, (x + pad) * px
        img[y0:y0 + px, x0:x0 + px] = c
    # vine: sine curve weaving across the letters
    xs = np.arange(0, W)
    vy = (H * 0.5 + np.sin(xs / W * np.pi * 5) * H * 0.33).astype(int)
    for x, y in zip(xs, vy):
        if x % 2 == 0:
            img[max(0, y - 2):y + 2, x] = (40, 110, 36, 255)
    for i, x in enumerate(range(px * 3, W - px * 2, px * 4)):
        y = vy[x]
        s = px // 2 + 2
        oy = -s if i % 2 else s // 2
        leaf = np.array([[0, 1, 1, 0], [1, 1, 1, 1], [1, 1, 1, 1], [0, 1, 1, 0]], bool)
        lk = np.kron(leaf, np.ones((max(1, s // 4), max(1, s // 4)), bool))
        y0, x0 = max(0, y + oy), max(0, x - lk.shape[1] // 2)
        reg = img[y0:y0 + lk.shape[0], x0:x0 + lk.shape[1]]
        lm = lk[:reg.shape[0], :reg.shape[1]]
        reg[lm] = (88, 196, 64, 255) if i % 3 else (220, 120, 200, 255)     # leaves + dream flowers
    # extrusion
    for d in range(3, 0, -1):
        for y, x in zip(*np.nonzero(m)):
            y0, x0 = (y + pad) * px + d * px // 3, (x + pad) * px + d * px // 3
            img[y0:y0 + px, x0:x0 + px] = (22 + d * 6, 52 + d * 6, 30, 255)
    for y, x in zip(*np.nonzero(m)):
        t = y / (h - 1)
        top = np.array([150, 236, 96]); bot = np.array([34, 160, 120])
        c = top * (1 - t) + bot * t
        y0, x0 = (y + pad) * px, (x + pad) * px
        blk = np.clip(c + rng.randint(-14, 14, (px, px, 1)), 0, 255)
        img[y0:y0 + px, x0:x0 + px, :3] = blk
        img[y0:y0 + px, x0:x0 + px, 3] = 255
        img[y0:y0 + 2, x0:x0 + px, :3] = np.clip(c + 40, 0, 255)          # bevel highlight
    # outline
    a = img[..., 3] > 0
    o = np.zeros_like(a)
    for dy in (-2, -1, 0, 1, 2):
        for dx in (-2, -1, 0, 1, 2):
            o |= np.roll(np.roll(a, dy, 0), dx, 1)
    edge = o & ~a
    img[edge] = (10, 24, 14, 255)
    return img


def icon(size=256):
    """Analytic isometric cube rasteriser."""
    import dv_blocks as bl
    N = 32
    img = np.zeros((N, N, 4), np.float64)
    top = bl.tex("grass_top").astype(float); side = bl.tex("grass_side").astype(float)
    c, s = N / 2.0, 13.0          # centre x, half width
    hh = s * 0.5                  # half height of top rhombus
    z0 = 3.5                      # top vertex y
    edge = s                      # cube side height
    for py in range(N):
        for px in range(N):
            x, y = px + 0.5 - c, py + 0.5 - (z0 + hh)
            # top face: rhombus centred at (0,0) with radii (s, hh)
            if abs(x) / s + abs(y) / hh <= 1:
                a = (x / s + y / hh + 1) / 2; b = (-x / s + y / hh + 1) / 2
                col = top[min(15, int(b * 16)), min(15, int(a * 16)), :3]
                img[py, px] = (*col, 255); continue
            # side faces
            for sign, shade in ((-1, 0.82), (1, 0.62)):
                if sign * x < 0 or abs(x) > s:
                    continue
                f = abs(x) / s                       # 0 at centre, 1 at outer edge
                yt = hh * (1 - f)                    # top edge of this face (relative)
                if yt <= y <= yt + edge:
                    u = f if sign > 0 else 1 - f
                    v = (y - yt) / edge
                    col = side[min(15, int(v * 16)), min(15, int(u * 16)), :3] * shade
                    img[py, px] = (*col, 255)
    # vine wrapping around the block (spiral strip + leaves)
    vine = (34, 140, 46); leaf = (96, 214, 74); flower = (232, 120, 210)
    pts = []
    for i in range(140):
        t = i / 139.0
        ang = t * np.pi * 2.6 - 0.6
        x = np.sin(ang) * (s + 0.8)
        y = (z0 + hh) + hh * 0.4 + t * (edge - 1) + np.cos(ang) * hh * 0.35
        front = np.cos(ang) > -0.2
        pts.append((x + c, y, front))
    for x, y, front in pts:
        if front:
            xi, yi = int(x), int(y)
            if 0 <= xi < N and 0 <= yi < N:
                img[yi, xi] = (*vine, 255)
    for j, (x, y, front) in enumerate(pts[6::14]):
        if not front:
            continue
        xi, yi = int(x), int(y)
        col = flower if j % 3 == 2 else leaf
        for dx, dy in ((0, -1), (1, -1), (1, 0), (0, 0)):
            if 0 <= xi + dx < N and 0 <= yi + dy < N:
                img[yi + dy, xi + dx] = (*col, 255)
    # dark outline
    a = img[..., 3] > 0
    o = a.copy()
    for d in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        o |= np.roll(a, d, (0, 1))
    img[o & ~a] = (16, 30, 18, 255)
    img = img.astype(np.uint8)
    k = max(1, size // N)
    return np.kron(img, np.ones((k, k, 1), np.uint8))


def sun():
    n = 32; img = np.zeros((n, n, 4), np.uint8)
    yy, xx = np.mgrid[0:n, 0:n]
    d = np.maximum(abs(xx - 15.5), abs(yy - 15.5))
    img[d < 16] = (255, 240, 170, 60)
    img[d < 12] = (255, 236, 150, 120)
    img[d < 8] = (255, 250, 210, 255)
    return img


def moon():
    n = 32; img = np.zeros((n, n, 4), np.uint8)
    yy, xx = np.mgrid[0:n, 0:n]
    d = np.maximum(abs(xx - 15.5), abs(yy - 15.5))
    img[d < 14] = (200, 210, 240, 40)
    img[d < 8] = (226, 230, 240, 255)
    for cx, cy in ((12, 12), (18, 17), (14, 19)):
        img[cy:cy + 2, cx:cx + 2] = (176, 182, 204, 255)
    return img


def clouds_tex(seed=3):
    rng = np.random.RandomState(seed)
    n = 64
    a = rng.rand(n, n)
    for _ in range(3):
        a = (a + np.roll(a, 1, 0) + np.roll(a, -1, 0) + np.roll(a, 1, 1) + np.roll(a, -1, 1)) / 5
    m = a > np.percentile(a, 72)
    img = np.zeros((n, n, 4), np.uint8)
    img[m] = (255, 255, 255, 215)
    return img

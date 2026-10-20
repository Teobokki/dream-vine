"""DREAM VINE - seeded gradient (Perlin-style) noise, vectorised with numpy. (c)2026 EX Inc."""
import numpy as np


class Noise:
    def __init__(self, seed):
        rng = np.random.RandomState(seed & 0x7FFFFFFF)
        p = np.arange(256, dtype=np.int64)
        rng.shuffle(p)
        self.perm = np.concatenate([p, p])
        ang = rng.uniform(0, 2 * np.pi, 256)
        self.g2 = np.stack([np.cos(ang), np.sin(ang)], 1)
        v = rng.normal(size=(256, 3))
        self.g3 = v / np.linalg.norm(v, axis=1, keepdims=True)

    @staticmethod
    def _fade(t):
        return t * t * t * (t * (t * 6 - 15) + 10)

    def noise2(self, x, y):
        x = np.asarray(x, np.float64); y = np.asarray(y, np.float64)
        xi = np.floor(x).astype(np.int64); yi = np.floor(y).astype(np.int64)
        xf = x - xi; yf = y - yi
        xi &= 255; yi &= 255
        P, G = self.perm, self.g2
        def grad(ix, iy, dx, dy):
            g = G[P[P[ix] + iy] & 255]
            return g[..., 0] * dx + g[..., 1] * dy
        n00 = grad(xi, yi, xf, yf); n10 = grad((xi + 1) & 255, yi, xf - 1, yf)
        n01 = grad(xi, (yi + 1) & 255, xf, yf - 1); n11 = grad((xi + 1) & 255, (yi + 1) & 255, xf - 1, yf - 1)
        u, v = self._fade(xf), self._fade(yf)
        a = n00 + u * (n10 - n00); b = n01 + u * (n11 - n01)
        return (a + v * (b - a)) * 1.414

    def noise3(self, x, y, z):
        x = np.asarray(x, np.float64); y = np.asarray(y, np.float64); z = np.asarray(z, np.float64)
        xi = np.floor(x).astype(np.int64); yi = np.floor(y).astype(np.int64); zi = np.floor(z).astype(np.int64)
        xf, yf, zf = x - xi, y - yi, z - zi
        xi &= 255; yi &= 255; zi &= 255
        P, G = self.perm, self.g3
        def grad(ix, iy, iz, dx, dy, dz):
            g = G[P[P[P[ix] + iy] + iz] & 255]
            return g[..., 0] * dx + g[..., 1] * dy + g[..., 2] * dz
        u, v, w = self._fade(xf), self._fade(yf), self._fade(zf)
        x1, y1, z1 = (xi + 1) & 255, (yi + 1) & 255, (zi + 1) & 255
        c000 = grad(xi, yi, zi, xf, yf, zf); c100 = grad(x1, yi, zi, xf - 1, yf, zf)
        c010 = grad(xi, y1, zi, xf, yf - 1, zf); c110 = grad(x1, y1, zi, xf - 1, yf - 1, zf)
        c001 = grad(xi, yi, z1, xf, yf, zf - 1); c101 = grad(x1, yi, z1, xf - 1, yf, zf - 1)
        c011 = grad(xi, y1, z1, xf, yf - 1, zf - 1); c111 = grad(x1, y1, z1, xf - 1, yf - 1, zf - 1)
        a = c000 + u * (c100 - c000); b = c010 + u * (c110 - c010)
        c = c001 + u * (c101 - c001); d = c011 + u * (c111 - c011)
        e = a + v * (b - a); f = c + v * (d - c)
        return e + w * (f - e)

    def fbm2(self, x, y, octaves=4, lac=2.0, gain=0.5):
        s, amp, f, norm = 0.0, 1.0, 1.0, 0.0
        for i in range(octaves):
            s = s + amp * self.noise2(x * f + i * 17.3, y * f - i * 9.1)
            norm += amp; amp *= gain; f *= lac
        return s / norm

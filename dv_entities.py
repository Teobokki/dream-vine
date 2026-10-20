"""DREAM VINE - physics (AABB vs voxel grid), voxel raycast and mobs. (c)2026 EX Inc."""
import math, random
import numpy as np
import dv_blocks as bl
from dv_render import box_geom

EPS = 1e-4


def _solid(world, x, y, z):
    return bl.SOLID[world.get(x, y, z, missing=bl.STONE)]


def box_hits(world, x0, y0, z0, x1, y1, z1):
    for x in range(math.floor(x0), math.floor(x1 - 1e-9) + 1):
        for y in range(math.floor(y0), math.floor(y1 - 1e-9) + 1):
            for z in range(math.floor(z0), math.floor(z1 - 1e-9) + 1):
                if _solid(world, x, y, z):
                    yield x, y, z


def move(world, pos, vel, dt, hw, hh, guard_edges=False):
    """Moves an AABB (feet centre pos, half width hw, height hh). Returns (on_ground, hit_wall)."""
    on_ground = hit_wall = False
    dist = max(abs(vel[0]), abs(vel[1]), abs(vel[2])) * dt
    steps = max(1, int(math.ceil(dist / 0.4)))
    sdt = dt / steps
    for _ in range(steps):
        for ax in (2, 0, 1):
            d = vel[ax] * sdt
            if d == 0:
                continue
            old = pos[ax]
            pos[ax] += d
            x, y, z = pos
            hits = list(box_hits(world, x - hw, y - hw, z, x + hw, y + hw, z + hh))
            if hits:
                cells = [h[ax] for h in hits]
                if ax == 2:
                    if d > 0:
                        pos[2] = min(cells) - hh - EPS
                    else:
                        pos[2] = max(cells) + 1 + EPS; on_ground = True
                else:
                    pos[ax] = (min(cells) - hw - EPS) if d > 0 else (max(cells) + 1 + hw + EPS)
                    hit_wall = True
                vel[ax] = 0
            elif guard_edges and ax != 2:
                x, y, z = pos
                if not any(True for _ in box_hits(world, x - hw + 0.02, y - hw + 0.02, z - 0.2, x + hw - 0.02, y + hw - 0.02, z - 0.01)):
                    pos[ax] = old; vel[ax] = 0
    return on_ground, hit_wall


def raycast(world, origin, direction, reach):
    """Voxel DDA. Returns (hit_cell, prev_cell, dist) or None. Water/air are skipped."""
    ox, oy, oz = origin
    dx, dy, dz = direction
    x, y, z = math.floor(ox), math.floor(oy), math.floor(oz)
    step = [1 if d > 0 else -1 for d in direction]
    tmax, tdelta = [], []
    for o, d, c in ((ox, dx, x), (oy, dy, y), (oz, dz, z)):
        if abs(d) < 1e-9:
            tmax.append(1e9); tdelta.append(1e9)
        else:
            nb = c + (1 if d > 0 else 0)
            tmax.append((nb - o) / d); tdelta.append(abs(1 / d))
    prev = (x, y, z); t = 0.0
    cell = [x, y, z]
    while t <= reach:
        b = world.get(cell[0], cell[1], cell[2])
        if b not in (bl.AIR, bl.WATER):
            return tuple(cell), prev, t
        prev = tuple(cell)
        i = int(np.argmin(tmax))
        cell[i] += step[i]; t = tmax[i]; tmax[i] += tdelta[i]
    return None


def ray_aabb(o, d, bmin, bmax):
    tmin, tmax = -1e9, 1e9
    for i in range(3):
        if abs(d[i]) < 1e-9:
            if o[i] < bmin[i] or o[i] > bmax[i]:
                return None
        else:
            t1, t2 = (bmin[i] - o[i]) / d[i], (bmax[i] - o[i]) / d[i]
            tmin, tmax = max(tmin, min(t1, t2)), min(tmax, max(t1, t2))
    return tmin if tmax >= max(tmin, 0) else None


# ----------------------------------------------------------------------------- mobs
class Mob:
    hw, hh, speed, max_hp, hostile = 0.45, 1.0, 1.4, 10, False

    def __init__(self, game, pos):
        self.g = game
        self.pos = np.array(pos, np.float64)
        self.vel = np.zeros(3)
        self.yaw = random.uniform(0, 360)
        self.hp = self.max_hp
        self.on_ground = False
        self.timer = random.uniform(1, 4); self.walking = False; self.panic = 0.0
        self.hurt_t = 0.0; self.dead = False; self.anim = 0.0; self.attack_cd = 0.0
        self.np = game.mob_root.attach_new_node(type(self).__name__)
        self.legs = []
        self.build()

    def leg(self, x, y, h, w, color):
        pivot = self.np.attach_new_node("leg"); pivot.set_pos(x, y, h)
        box_geom(pivot, (w, w, h), color, (0.5, 0.5, 1.0))
        self.legs.append(pivot)

    def remove(self):
        self.dead = True
        self.np.remove_node()

    def damage(self, n, src_dir):
        self.hp -= n
        self.hurt_t = 0.35
        self.vel[0] += src_dir[0] * 7; self.vel[1] += src_dir[1] * 7; self.vel[2] = 5
        self.panic = 4.0
        if self.hp <= 0:
            self.on_death(); self.remove()

    def on_death(self):
        pass

    def think(self, dt):
        self.timer -= dt
        if self.timer <= 0:
            self.timer = random.uniform(2, 6)
            self.walking = random.random() < 0.6
            self.yaw = random.uniform(0, 360)

    def update(self, dt):
        if self.dead:
            return
        self.think(dt)
        if self.dead:
            return
        sp = self.speed * (2.4 if self.panic > 0 else 1.0)
        self.panic = max(0, self.panic - dt)
        if self.panic > 0 and random.random() < dt * 1.5:
            self.yaw += random.uniform(-90, 90)
        wv = np.zeros(2)
        if self.walking or self.panic > 0:
            r = math.radians(self.yaw)
            wv = np.array([-math.sin(r), math.cos(r)]) * sp
        k = min(1.0, dt * (10 if self.on_ground else 2))
        self.vel[0] += (wv[0] - self.vel[0]) * k; self.vel[1] += (wv[1] - self.vel[1]) * k
        inw = self.g.world.get(int(math.floor(self.pos[0])), int(math.floor(self.pos[1])), int(math.floor(self.pos[2] + 0.3))) == bl.WATER
        self.vel[2] = max(-50, self.vel[2] - (8 if inw else 30) * dt)
        if inw:
            self.vel[2] = max(self.vel[2], 1.5)
        self.on_ground, wall = move(self.g.world, self.pos, self.vel, dt, self.hw, self.hh)
        if wall and self.on_ground:
            self.vel[2] = 8.6
        moving = float(np.hypot(self.vel[0], self.vel[1]))
        self.anim += dt * moving * 4
        sw = math.sin(self.anim) * 35 * min(1, moving)
        for i, lg in enumerate(self.legs):
            lg.set_p(sw if i % 2 == 0 else -sw)
        self.np.set_pos(*self.pos)
        self.np.set_h(self.yaw)
        if self.hurt_t > 0:
            self.hurt_t -= dt
            self.np.set_color_scale(1, 0.45, 0.45, 1)
        else:
            self.np.clear_color_scale()


class Mossbuck(Mob):
    """Passive grazing animal (original design): mossy back, stubby horns."""
    hw, hh, speed, max_hp = 0.45, 1.1, 1.3, 10

    def build(self):
        fur, moss, dark = (0.55, 0.42, 0.30), (0.36, 0.62, 0.30), (0.25, 0.18, 0.12)
        for x in (-0.25, 0.25):
            for y in (-0.38, 0.38):
                self.leg(x, y, 0.45, 0.22, dark)
        box_geom(self.np, (0.7, 1.15, 0.5), fur, (0.5, 0.5, 0.0)).set_pos(0, 0, 0.42)
        box_geom(self.np, (0.74, 1.0, 0.14), moss, (0.5, 0.5, 0.0)).set_pos(0, -0.02, 0.9)
        head = self.np.attach_new_node("head"); head.set_pos(0, 0.66, 0.78)
        box_geom(head, (0.5, 0.45, 0.45), fur, (0.5, 0.5, 0.5))
        box_geom(head, (0.3, 0.12, 0.2), (0.85, 0.66, 0.55), (0.5, 0.5, 0.5)).set_pos(0, 0.26, -0.08)
        for x in (-0.17, 0.17):
            box_geom(head, (0.08, 0.08, 0.2), (0.9, 0.88, 0.8), (0.5, 0.5, 0.0)).set_pos(x, 0.02, 0.2)
            box_geom(head, (0.07, 0.03, 0.07), (0.05, 0.05, 0.05), (0.5, 0.5, 0.5)).set_pos(x * 0.9, 0.23, 0.08)

    def on_death(self):
        self.g.give(bl.RAW_MEAT, random.randint(1, 2))


class Gloomer(Mob):
    """Hostile night creature (original design): tall shadowy body, glowing teal eyes."""
    hw, hh, speed, max_hp, hostile = 0.3, 1.9, 2.5, 20, True

    def build(self):
        body, dark = (0.22, 0.16, 0.30), (0.12, 0.09, 0.17)
        for x in (-0.13, 0.13):
            self.leg(x, 0, 0.8, 0.22, dark)
        box_geom(self.np, (0.5, 0.3, 0.65), body, (0.5, 0.5, 0.0)).set_pos(0, 0, 0.8)
        for x in (-0.33, 0.33):
            arm = self.np.attach_new_node("arm"); arm.set_pos(x, 0, 1.42); arm.set_p(80)
            box_geom(arm, (0.16, 0.16, 0.75), dark, (0.5, 0.5, 1.0))
        head = self.np.attach_new_node("head"); head.set_pos(0, 0, 1.67)
        box_geom(head, (0.46, 0.46, 0.46), (0.10, 0.08, 0.14), (0.5, 0.5, 0.5))
        for x in (-0.11, 0.11):
            e = box_geom(head, (0.1, 0.03, 0.06), (0.35, 1.0, 0.92), (0.5, 0.5, 0.5))
            e.set_pos(x, 0.235, 0.03); e.set_light_off(1); e.set_color_scale_off(2); e.set_fog_off(2)

    def think(self, dt):
        g = self.g
        p = g.player_pos
        d = p - self.pos
        dist = float(np.hypot(d[0], d[1]))
        self.attack_cd = max(0, self.attack_cd - dt)
        if g.can_be_attacked() and dist < 22:
            self.walking = dist > 1.0
            self.yaw = math.degrees(math.atan2(-d[0], d[1]))
            if dist < 1.5 and abs(d[2]) < 1.8 and self.attack_cd <= 0:
                self.attack_cd = 1.0
                g.hurt_player(3, (d[0] / max(dist, 0.1), d[1] / max(dist, 0.1)))
        else:
            Mob.think(self, dt)

    def on_death(self):
        self.g.give(bl.COAL, random.randint(1, 2))

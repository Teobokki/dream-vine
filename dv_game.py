"""DREAM VINE - the in-game session: chunks, player, interaction, HUD, inventory, crafting, mobs, sky. (c)2026 EX Inc."""
import json, math, os, random, time
import numpy as np
from direct.showbase.DirectObject import DirectObject
from direct.gui.DirectGui import DirectFrame, DirectButton, DGG
from direct.gui.OnscreenText import OnscreenText
from direct.gui.OnscreenImage import OnscreenImage
from panda3d.core import (KeyboardButton, MouseButton, TransparencyAttrib, Fog, CardMaker, TextNode, Filename,
                          WindowProperties, Vec3, SamplerState, Texture, TextureStage)
import dv_blocks as bl
import dv_world as dw
import dv_render as rd
import dv_entities as en
import dv_chat
import dv_vinebuild as vb

CYCLE = 1200.0           # seconds per day/night
PLAYER_HW, PLAYER_H = 0.3, 1.8
SLOT = 0.135


def kb(c):
    return KeyboardButton.ascii_key(c)


def heart_img(kind):
    m = ["  xx   xx  ", " xrrx xrrx ", "xrhrrxrrrrx", "xrrrrrrrrrx", "xrrrrrrrrrx", " xrrrrrrrx ", "  xrrrrrx  ",
         "   xrrrx   ", "    xrx    ", "     x     "]
    return _icon(m, kind, {"x": (20, 8, 8), "r": (218, 34, 40), "h": (255, 170, 170)})


def food_img(kind):
    m = ["      xxxx ", "     xbbbbx", "    xbbbbbx", "   xbbbbbbx", "  xbbbbbbx ", " xwxbbbbx  ", "xwwxxxxx   ",
         "xwwx       ", " xx        ", "           "]
    return _icon(m, kind, {"x": (40, 20, 8), "b": (176, 96, 46), "w": (238, 230, 214)})


def _icon(mask, kind, cols):
    h, w = len(mask), max(len(r) for r in mask)
    img = np.zeros((h, w, 4), np.uint8)
    for y, row in enumerate(mask):
        for x, ch in enumerate(row):
            if ch in cols:
                c = cols[ch]
                if kind == "empty" and ch != "x":
                    c = (40, 40, 44)
                if kind == "half" and ch != "x" and x > w // 2:
                    c = (40, 40, 44)
                img[y, x] = c + (255,)
    return img


class Game(DirectObject):
    def __init__(self, app, save_dir, meta):
        DirectObject.__init__(self)
        self.app, self.base = app, app
        self.save_dir, self.meta = save_dir, meta
        self.world = dw.World(meta["seed"], save_dir)
        self.creative = meta.get("mode") == "creative"
        self.root = app.render.attach_new_node("game")
        self.terrain = self.root.attach_new_node("terrain")
        self.terrain.set_texture(app.atlas)
        self.terrain.set_transparency(TransparencyAttrib.M_binary)
        self.water_root = self.root.attach_new_node("water")
        self.water_root.set_texture(app.atlas)
        self.water_root.set_transparency(TransparencyAttrib.M_alpha)
        self.water_root.set_depth_write(False); self.water_root.set_bin("transparent", 10); self.water_root.set_two_sided(True)
        self.mob_root = self.root.attach_new_node("mobs")
        self.chunk_np = {}; self.dirty = set(); self.dirty_slow = set(); self._want = None; self._center = None; self._unload_t = 0
        # player
        p = meta.get("player", {})
        self.pos = np.array(p.get("pos", [0.5, 0.5, 80.0]), np.float64)
        self.vel = np.zeros(3)
        self.yaw, self.pitch = p.get("yaw", 0.0), p.get("pitch", 0.0)
        self.health, self.food = p.get("health", 20.0), p.get("food", 20.0)
        self.exhaust = 0.0; self.regen_t = 0.0; self.starve_t = 0.0
        self.flying = bool(p.get("flying", False)) and self.creative
        self.on_ground = False; self.fall = 0.0; self.sprint = False; self.in_water = False
        self.inv = [tuple(s) if s else None for s in p.get("inv", [None] * 36)]
        self.inv += [None] * (36 - len(self.inv))
        self.sel = p.get("sel", 0)
        self.spawn = meta.get("spawn")
        self.time = meta.get("time", 0.03)
        self.mobs = []
        self.state = "play"   # play | inventory | paused | dead
        self.hurt_t = 0.0; self.inv_t = 0.0
        self.last_w = self.last_space = -1.0
        self.break_cell = None; self.break_prog = 0.0; self.break_cd = 0.0; self.place_cd = 0.0; self.attack_cd = 0.0
        self.swing = 0.0; self.target = None
        self.cursor_stack = None; self.inv_ui = None; self.pause_ui = None; self.dead_ui = None
        self.show_debug = False; self.hud_hidden = False
        self.save_t = 0.0; self.spawn_t = 0.0; self.fps_t = 0.0; self.fps = 0.0; self.frames = 0
        self._build_sky()
        self._build_hand()
        self._build_hud()
        self.highlight = rd.wire_cube(self.root); self.highlight.hide()
        self.crack = rd.box_geom(self.root, (1.004, 1.004, 1.004), (1, 1, 1), (0, 0, 0), "crack",
                                 tex_uv=bl.tile_uv(bl.CRACK_TILE0))
        self.crack.set_texture(app.atlas); self.crack.set_transparency(TransparencyAttrib.M_alpha)
        self.crack.set_depth_offset(1); self.crack.hide()
        self.captured = False; self.sneaking = False; self._light = 1.0; self._m1 = self._m3 = False
        self.loading = True
        self.new_world = not meta.get("player")
        if self.new_world:
            self._find_spawn()
        self.apply_settings()
        self.accept("escape", self.on_escape)
        self.accept("wheel_up", lambda: self.scroll(-1)); self.accept("wheel_down", lambda: self.scroll(1))
        self.accept("page_up", lambda: self.chat.scroll(3)); self.accept("page_down", lambda: self.chat.scroll(-3))
        for k, f in (("e", self.toggle_inventory), ("f3", self.toggle_debug),
                     ("f2", self.screenshot), ("f1", self.toggle_hud), ("f9", self.toggle_recording),
                     ("space", self.on_space), ("w", self.on_w),
                     ("t", self.open_chat), ("enter", self.open_chat), ("/", lambda: self.open_chat("/")),
                     ("b", self.open_vinebuild), ("z", self.on_z),
                     ("mouse1", lambda: setattr(self, "_m1", True)), ("mouse3", lambda: setattr(self, "_m3", True))):
            self.accept(k, self._k(f))
        for i in range(9):
            self.accept(str(i + 1), self._k(self.select), [i])
        # text chat + VINE BUILD
        self.chat = dv_chat.Chat(self, meta.get("chat"))
        self.vb_ui = None; self.build_job = None; self.build_undo = []; self._ui_closed_t = 0.0; self.build_wire = None
        self._init_leaves()
        self.app.task_mgr.add(self.update, "dv-game-update")

    # ------------------------------------------------------------------ setup
    def apply_settings(self):
        s = self.app.settings
        self.rd = int(s["render_distance"])
        far = max(420.0, self.rd * 16 * 1.6)
        self.app.camLens.set_near_far(0.05, far)
        self.base_fov = float(s["fov"])
        self.fog = Fog("fog")
        self.fog.set_linear_range(self.rd * 16 * 0.55, self.rd * 16 * 0.95)
        self.root.set_fog(self.fog)
        self._want = None

    def _build_sky(self):
        a = self.app
        self.sky = a.render.attach_new_node("sky")
        self.sky.set_bin("background", 0); self.sky.set_depth_write(False); self.sky.set_depth_test(False)
        self.sky.set_light_off(1); self.sky.set_fog_off(1)
        cm = CardMaker("sun"); cm.set_frame(-1, 1, -1, 1)
        self.sun = self.sky.attach_new_node(cm.generate()); self.moon = self.sky.attach_new_node(cm.generate())
        self.sun.set_texture(a.tex_sun); self.moon.set_texture(a.tex_moon)
        for n, s in ((self.sun, 26), (self.moon, 20)):
            n.set_scale(s); n.set_billboard_point_eye(); n.set_transparency(True); n.set_two_sided(True)
        cm = CardMaker("clouds"); cm.set_frame(-512, 512, -512, 512)
        self.clouds = self.root.attach_new_node(cm.generate())
        self.clouds.set_p(-90); self.clouds.set_texture(a.tex_clouds); self.clouds.set_tex_scale(TextureStage.get_default(), 16, 16)
        self.clouds.set_transparency(TransparencyAttrib.M_alpha); self.clouds.set_two_sided(True); self.clouds.set_depth_write(False)
        self.clouds.set_bin("transparent", 20); self.clouds.set_color_scale(1, 1, 1, 0.85)

    def _build_hud(self):
        a = self.app
        self.hud = a.aspect2d.attach_new_node("hud")
        for w, h in ((0.035, 0.004), (0.004, 0.035)):
            DirectFrame(parent=self.hud, frameColor=(1, 1, 1, 0.85), frameSize=(-w, w, -h, h))
        self.hot = self.hud.attach_new_node("hotbar"); self.hot.set_z(-0.9)
        self.slot_frames, self.slot_icons, self.slot_text = [], [None] * 9, []
        for i in range(9):
            x = (i - 4) * SLOT
            DirectFrame(parent=self.hot, frameColor=(0.35, 0.35, 0.38, 0.85), frameSize=(-SLOT / 2, SLOT / 2, -SLOT / 2, SLOT / 2), pos=(x, 0, 0))
            DirectFrame(parent=self.hot, frameColor=(0.10, 0.10, 0.11, 0.72), frameSize=(-SLOT / 2 + 0.008, SLOT / 2 - 0.008, -SLOT / 2 + 0.008, SLOT / 2 - 0.008), pos=(x, 0, 0))
            t = OnscreenText(parent=self.hot, text="", pos=(x + SLOT * 0.38, -SLOT * 0.4), scale=0.042, fg=(1, 1, 1, 1),
                             shadow=(0, 0, 0, 1), align=TextNode.A_right)
            t.set_bin("gui-popup", 5); self.slot_text.append(t)
        self.sel_frame = self.hot.attach_new_node("sel")
        e, t = SLOT / 2 + 0.004, 0.011
        for fs in ((-e, e, e - t, e), (-e, e, -e, -e + t), (-e, -e + t, -e, e), (e - t, e, -e, e)):
            DirectFrame(parent=self.sel_frame, frameColor=(0.97, 0.97, 0.97, 1), frameSize=fs)
        self.hearts, self.foods = [], []
        for i in range(10):
            self.hearts.append(OnscreenImage(parent=self.hot, image=a.tex_heart["full"], scale=(0.026, 1, 0.024),
                                             pos=(-4.5 * SLOT + 0.03 + i * 0.056, 0, SLOT * 0.5 + 0.045)))
            self.foods.append(OnscreenImage(parent=self.hot, image=a.tex_food["full"], scale=(0.026, 1, 0.024),
                                            pos=(4.5 * SLOT - 0.03 - i * 0.056, 0, SLOT * 0.5 + 0.045)))
        for im in self.hearts + self.foods:
            im.set_transparency(True)
        self.item_label = OnscreenText(parent=self.hud, text="", pos=(0, -0.72), scale=0.05, fg=(1, 1, 1, 1), shadow=(0, 0, 0, 1))
        self.label_t = 0.0
        self.debug = OnscreenText(parent=self.app.a2dTopLeft, text="", pos=(0.03, -0.06), scale=0.042, fg=(1, 1, 1, 1),
                                  shadow=(0, 0, 0, 1), align=TextNode.A_left, mayChange=True)
        self.toast = OnscreenText(parent=self.app.a2dTopRight, text="", pos=(-0.04, -0.08), scale=0.045, fg=(1, 1, 0.6, 1),
                                  shadow=(0, 0, 0, 1), align=TextNode.A_right, mayChange=True)
        self.toast_t = 0.0
        # EX CREATOR SCREEN RECORDER 2026 indicator (top-right)
        self.rec_ui = self.app.a2dTopRight.attach_new_node("rec")
        DirectFrame(parent=self.rec_ui, frameColor=(0, 0, 0, 0.55), frameSize=(-0.66, 0.0, -0.115, 0.0), pos=(-0.02, 0, -0.02))
        self.rec_dot = OnscreenImage(parent=self.rec_ui, image=self.app.tex_recdot, scale=0.022, pos=(-0.47, 0, -0.06))
        self.rec_dot.set_transparency(True); self.rec_dot.reparent_to(self.rec_ui, 10)
        self.rec_text = OnscreenText(parent=self.rec_ui, text="REC 00:00", pos=(-0.435, -0.074), scale=0.05, fg=(1, 0.2, 0.2, 1),
                                     shadow=(0, 0, 0, 1), align=TextNode.A_left, mayChange=True)
        OnscreenText(parent=self.rec_ui, text="EX CREATOR SCREEN RECORDER 2026", pos=(-0.05, -0.115 + 0.012), scale=0.03,
                     fg=(1, 1, 1, 0.9), shadow=(0, 0, 0, 1), align=TextNode.A_right)
        self.rec_ui.hide()
        self.hurt_overlay = DirectFrame(parent=a.render2d, frameColor=(0.8, 0, 0, 0), frameSize=(-1, 1, -1, 1))
        self.water_overlay = DirectFrame(parent=a.render2d, frameColor=(0.1, 0.25, 0.7, 0.35), frameSize=(-1, 1, -1, 1))
        self.water_overlay.hide()
        self._hud_cache = None
        self.refresh_hotbar()

    def _build_hand(self):
        self.hand = self.app.camera.attach_new_node("hand")
        self.hand.set_bin("fixed", 100); self.hand.set_depth_test(False); self.hand.set_depth_write(False)
        self.hand.set_fog_off(1)
        self.hand_item = -1
        self.hand_model = None

    # ------------------------------------------------------------------ inventory helpers
    def held(self):
        s = self.inv[self.sel]
        return s[0] if s else None

    def give(self, item, n=1):
        if not item:
            return
        ms = bl.max_stack(item)
        for i, s in enumerate(self.inv):
            if s and s[0] == item and s[1] < ms:
                add = min(n, ms - s[1]); self.inv[i] = (item, s[1] + add); n -= add
                if n <= 0:
                    break
        while n > 0:
            try:
                i = self.inv.index(None)
            except ValueError:
                break
            add = min(n, ms); self.inv[i] = (item, add); n -= add
        self.refresh_hotbar()

    def count(self, item):
        return sum(s[1] for s in self.inv if s and s[0] == item)

    def take(self, item, n):
        for i, s in enumerate(self.inv):
            if s and s[0] == item and n > 0:
                t = min(n, s[1]); n -= t
                self.inv[i] = (item, s[1] - t) if s[1] - t > 0 else None
        self.refresh_hotbar()

    def consume_held(self):
        if self.creative:
            return
        s = self.inv[self.sel]
        self.inv[self.sel] = (s[0], s[1] - 1) if s and s[1] > 1 else None
        self.refresh_hotbar()

    def select(self, i):
        self.sel = i % 9
        self.refresh_hotbar(label=True)

    def scroll(self, d):
        if self.state == "chat":
            self.chat.scroll(-d)
        elif self.state == "play":
            self.select(self.sel + d)

    def refresh_hotbar(self, label=False):
        for i in range(9):
            s = self.inv[i]
            key = s[0] if s else None
            ic = self.slot_icons[i]
            if ic is None or ic[0] != key:
                if ic and ic[1]:
                    ic[1].remove_node()
                node = rd.icon_node(self.hot, key, self.app.atlas, SLOT * 0.62) if key else None
                if node:
                    node.set_pos((i - 4) * SLOT, 0, 0)
                self.slot_icons[i] = (key, node)
            self.slot_text[i].setText(str(s[1]) if s and s[1] > 1 else "")
        self.sel_frame.set_pos((self.sel - 4) * SLOT, 0, 0)
        if label:
            h = self.held()
            self.item_label.setText(bl.name_of(h) if h else ""); self.label_t = 2.0
        self._update_hand()

    def _update_hand(self):
        h = self.held()
        if h == self.hand_item:
            return
        self.hand_item = h
        if self.hand_model:
            self.hand_model.remove_node(); self.hand_model = None
        if h is None:
            self.hand_model = rd.box_geom(self.hand, (0.1, 0.42, 0.1), (0.86, 0.68, 0.55), (0.5, 0.0, 0.5))
            self.hand_model.set_pos(0.34, 0.42, -0.34); self.hand_model.set_hpr(-12, 26, 0)
        elif h in bl.BLOCKS:
            self.hand_model = rd.box_geom(self.hand, (1, 1, 1), (1, 1, 1), (0.5, 0.5, 0.5), tex_uv=rd.block_uvs(h))
            self.hand_model.set_texture(self.app.atlas); self.hand_model.set_transparency(TransparencyAttrib.M_binary)
            self.hand_model.set_scale(0.16); self.hand_model.set_pos(0.36, 0.6, -0.3); self.hand_model.set_hpr(40, 10, 0)
        else:
            cm = CardMaker("held"); cm.set_frame(-0.5, 0.5, -0.5, 0.5)
            u0, v0, u1, v1 = bl.tile_uv(bl.icon_tile(h)); cm.set_uv_range((u0, v0), (u1, v1))
            self.hand_model = self.hand.attach_new_node(cm.generate())
            self.hand_model.set_texture(self.app.atlas); self.hand_model.set_transparency(TransparencyAttrib.M_binary)
            self.hand_model.set_two_sided(True); self.hand_model.set_scale(0.24)
            self.hand_model.set_pos(0.36, 0.7, -0.26); self.hand_model.set_hpr(-60, 0, 10)
        self.hand_base = self.hand_model.get_pos(), self.hand_model.get_hpr()

    # ------------------------------------------------------------------ chunks
    def update_chunks(self, budget=0.006):
        t0 = time.perf_counter()
        pc = (int(math.floor(self.pos[0] / dw.CS)), int(math.floor(self.pos[1] / dw.CS)))
        R = self.rd
        if self._want is None or pc != self._center:
            self._center = pc
            ring = [(pc[0] + dx, pc[1] + dy) for dx in range(-R - 1, R + 2) for dy in range(-R - 1, R + 2)
                    if dx * dx + dy * dy <= (R + 1.5) ** 2]
            ring.sort(key=lambda k: (k[0] - pc[0]) ** 2 + (k[1] - pc[1]) ** 2)
            self._want = ring
        for k in list(self.dirty):
            self.dirty.discard(k)
            if k in self.chunk_np or k in self.world.chunks:
                self.mesh(k)
        t1 = time.perf_counter()
        for k in list(self.dirty_slow):                 # VINE BUILD remeshes, spread over frames
            if time.perf_counter() - t1 > 0.012:
                break
            self.dirty_slow.discard(k)
            if k in self.chunk_np or k in self.world.chunks:
                self.mesh(k)
        for k in self._want:
            if time.perf_counter() - t0 > budget:
                break
            if k not in self.world.chunks:
                self.world.ensure(*k)
        for k in self._want:
            if time.perf_counter() - t0 > budget:
                break
            d2 = (k[0] - pc[0]) ** 2 + (k[1] - pc[1]) ** 2
            if k not in self.chunk_np and d2 <= (R + 0.5) ** 2 and all(
                    (k[0] + a, k[1] + b) in self.world.chunks for a, b in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                self.mesh(k)
        now = time.time()
        if now - self._unload_t > 1.0:
            self._unload_t = now
            for k in list(self.chunk_np):
                if (k[0] - pc[0]) ** 2 + (k[1] - pc[1]) ** 2 > (R + 1.5) ** 2:
                    for n in self.chunk_np.pop(k):
                        if n: n.remove_node()
                    self.leaf_cols.pop(k, None)
            for k in list(self.world.chunks):
                if (k[0] - pc[0]) ** 2 + (k[1] - pc[1]) ** 2 > (R + 3) ** 2:
                    self.world.unload(k)

    def _find_spawn(self):
        for r in range(0, 400, 8):
            for i in range(max(1, r // 2)):
                a = i / max(1, r // 2) * 2 * math.pi
                x, y = int(r * math.cos(a)), int(r * math.sin(a))
                h = float(self.world.height(np.array([x]), np.array([y]))[0])
                if h > dw.SEA + 2:
                    self.pos[:] = (x + 0.5, y + 0.5, h + 3)
                    return
        self.pos[:] = (0.5, 0.5, 90)

    def finish_loading(self):
        self.loading = False
        x, y = int(math.floor(self.pos[0])), int(math.floor(self.pos[1]))
        if self.new_world:
            self.pos[2] = self.world.surface_z(x, y) + 0.01
            self.spawn = [float(self.pos[0]), float(self.pos[1]), float(self.pos[2])]
            if not self.creative:
                pass
            self.save()
        elif self.spawn is None:
            self.spawn = [float(v) for v in self.pos]
        self.app.loading_done()
        self.set_capture(True)
        self.show_toast("Press E for inventory - Esc for menu - F3 debug", 4.0)

    def mesh(self, k):
        old = self.chunk_np.pop(k, None)
        if old:
            for n in old:
                if n: n.remove_node()
        s, w = dw.build_mesh(self.world, *k)
        ns = self.terrain.attach_new_node(rd.mesh_node("c", *s)) if s else None
        nw = self.water_root.attach_new_node(rd.mesh_node("w", *w)) if w else None
        for n in (ns, nw):
            if n: n.set_pos(k[0] * dw.CS, k[1] * dw.CS, 0)
        self.chunk_np[k] = (ns, nw)
        c = self.world.chunks.get(k)
        if c is not None:                               # columns with autumn leaves (falling-leaf emitters)
            m = np.isin(c, bl.AUTUMN_LEAVES)
            has = m.any(2)
            if has.any():
                xs, ys = np.nonzero(has)
                zs = np.argmax(m[xs, ys], axis=1)
                self.leaf_cols[k] = np.stack([xs + k[0] * dw.CS, ys + k[1] * dw.CS, zs], 1)
            else:
                self.leaf_cols.pop(k, None)

    def mark_dirty(self, x, y):
        cx, cy = x // dw.CS, y // dw.CS
        self.dirty.add((cx, cy))
        lx, ly = x % dw.CS, y % dw.CS
        if lx == 0: self.dirty.add((cx - 1, cy))
        if lx == dw.CS - 1: self.dirty.add((cx + 1, cy))
        if ly == 0: self.dirty.add((cx, cy - 1))
        if ly == dw.CS - 1: self.dirty.add((cx, cy + 1))

    def loaded_ratio(self, radius):
        pc = (int(math.floor(self.pos[0] / dw.CS)), int(math.floor(self.pos[1] / dw.CS)))
        ks = [(pc[0] + dx, pc[1] + dy) for dx in range(-radius, radius + 1) for dy in range(-radius, radius + 1)]
        return sum(1 for k in ks if k in self.chunk_np) / float(len(ks))

    # ------------------------------------------------------------------ events
    def on_space(self):
        now = time.time()
        if self.state == "play" and self.creative and now - self.last_space < 0.3:
            self.flying = not self.flying; self.vel[2] = 0
            self.show_toast("Flying ON" if self.flying else "Flying OFF")
            now = -1
        self.last_space = now

    def on_w(self):
        now = time.time()
        if now - self.last_w < 0.3:
            self.sprint = True
        self.last_w = now

    def toggle_debug(self):
        self.show_debug = not self.show_debug
        if not self.show_debug: self.debug.setText("")

    def toggle_hud(self):
        self.hud_hidden = not self.hud_hidden
        (self.hud.hide if self.hud_hidden else self.hud.show)()
        (self.hand.hide if self.hud_hidden else self.hand.show)()

    def show_toast(self, t, secs=2.5):
        self.toast.setText(t); self.toast_t = secs

    def screenshot(self):
        d = self.app.downloads_dir()
        p = os.path.join(d, "DREAM VINE %s.png" % time.strftime("%Y-%m-%d %H-%M-%S"))
        ok = self.app.win.save_screenshot(Filename.from_os_specific(p))
        self.show_toast(("Screenshot saved to Downloads: " + os.path.basename(p)) if ok else "Screenshot failed")

    def on_escape(self):
        if self.state == "chat":
            if self.chat.open:
                self.chat.close_input()
            else:
                self.chat_closed()
        elif self.state == "build":
            self.close_vinebuild()
        elif self.state == "inventory":
            self.toggle_inventory()
        elif self.state == "play":
            self.open_pause()
        elif self.state == "paused":
            self.close_pause()

    def set_capture(self, on):
        self.captured = on
        wp = WindowProperties(); wp.set_cursor_hidden(on)
        wp.set_mouse_mode(WindowProperties.M_confined if on else WindowProperties.M_absolute)
        self.app.win.request_properties(wp)
        if on:
            self._center_mouse()
            self._m1 = self._m3 = False

    def _center_mouse(self):
        w = self.app.win
        w.move_pointer(0, w.get_x_size() // 2, w.get_y_size() // 2)

    # ------------------------------------------------------------------ menus inside the game
    def open_pause(self):
        self.state = "paused"; self.set_capture(False)
        a = self.app
        self.pause_ui = DirectFrame(parent=a.aspect2d, frameColor=(0, 0, 0, 0.55), frameSize=(-3, 3, -2, 2))
        OnscreenText(parent=self.pause_ui, text="Game Menu", pos=(0, 0.45), scale=0.09, fg=(1, 1, 1, 1), shadow=(0, 0, 0, 1))
        a.button(self.pause_ui, "Back to Game", (0, 0.22), self.close_pause)
        a.button(self.pause_ui, "Settings", (0, 0.06), lambda: a.open_settings(back=self._reopen_pause_after_settings))
        a.button(self.pause_ui, "Save & Quit to Title", (0, -0.10), self.quit_to_title)
        # EX CREATOR SCREEN RECORDER 2026 section
        DirectFrame(parent=self.pause_ui, frameColor=(0.08, 0.08, 0.1, 0.8), frameSize=(-0.66, 0.66, -0.2, 0.09), pos=(0, 0, -0.36),
                    relief=DGG.FLAT)
        OnscreenText(parent=self.pause_ui, text="EX CREATOR SCREEN RECORDER 2026", pos=(0, -0.31), scale=0.05, fg=(1, 0.35, 0.35, 1),
                     shadow=(0, 0, 0, 1))
        rec = self.app.screen_rec
        if rec.active:
            self._rec_btn = a.button(self.pause_ui, "Stop recording  (%s)" % self._fmt_t(rec.elapsed()), (0, -0.45), self.stop_recording, width=0.6)
        else:
            self._rec_btn = a.button(self.pause_ui, "Start recording", (0, -0.45), self.start_recording, width=0.6)
        OnscreenText(parent=self.pause_ui, text="Saves an MP4 to your Downloads folder  -  F9 starts / stops", pos=(0, -0.53),
                     scale=0.032, fg=(0.8, 0.8, 0.8, 1), shadow=(0, 0, 0, 1))

    # ------------------------------------------------------------------ EX CREATOR SCREEN RECORDER 2026
    @staticmethod
    def _fmt_t(s):
        s = int(s); return "%02d:%02d" % (s // 60, s % 60) if s < 3600 else "%d:%02d:%02d" % (s // 3600, s // 60 % 60, s % 60)

    def toggle_recording(self):
        if self.app.screen_rec.active:
            self.stop_recording()
        elif self.state in ("play", "paused"):
            self.start_recording()

    def start_recording(self):
        if self.state == "paused":
            self.close_pause()
        rec = self.app.screen_rec
        if rec.start(self.app.downloads_dir()):
            self.rec_ui.show(); self.show_toast("Recording started  (F9 or Esc menu to stop)", 2.5)
        else:
            self.show_toast("Could not start recording: %s" % rec.error, 4)

    def stop_recording(self):
        rec = self.app.screen_rec
        self.rec_ui.hide()
        if self.pause_ui:
            self._rec_btn["text"] = "Saving recording..."; self._rec_btn["state"] = DGG.DISABLED
        self.show_toast("Saving recording...", 30)
        def done(path):
            if self.toast.is_empty():
                return
            self.show_toast(("Saved to Downloads: " + os.path.basename(path)) if path else "Recording failed: %s" % rec.error, 5)
            if self.pause_ui:
                self._rec_btn["text"] = "Start recording"; self._rec_btn["state"] = DGG.NORMAL
                self._rec_btn["command"] = self.start_recording
        if not rec.stop_async(done):
            self.show_toast("Not recording", 2)

    def _reopen_pause_after_settings(self):
        self.apply_settings()
        if self.pause_ui:
            self.pause_ui.show()

    def close_pause(self):
        if self.pause_ui:
            self.pause_ui.destroy(); self.pause_ui = None
        self.state = "play"; self.set_capture(True)

    def quit_to_title(self):
        if self.app.screen_rec.active:
            self.app.screen_rec.stop()
        self.save()
        self.destroy()
        self.app.game = None
        self.app.show_title()

    # ------------------------------------------------------------------ inventory UI
    def toggle_inventory(self, table=False):
        if self.state == "inventory":
            if self.cursor_stack:
                self.give(*self.cursor_stack); self.cursor_stack = None
            if self.inv_ui:
                self.inv_ui.destroy(); self.inv_ui = None
            self.state = "play"; self.set_capture(True); self.refresh_hotbar()
            return
        if self.state != "play":
            return
        self.state = "inventory"; self.set_capture(False)
        self.table_near = table or self._table_near()
        self._build_inventory()

    def _table_near(self):
        x0, y0, z0 = (int(math.floor(v)) for v in self.pos)
        for x in range(x0 - 3, x0 + 4):
            for y in range(y0 - 3, y0 + 4):
                for z in range(z0 - 2, z0 + 4):
                    if self.world.get(x, y, z) == bl.TABLE:
                        return True
        return False

    def _build_inventory(self):
        a = self.app
        if self.inv_ui:
            self.inv_ui.destroy()
        ui = self.inv_ui = DirectFrame(parent=a.aspect2d, frameColor=(0, 0, 0, 0.5), frameSize=(-3, 3, -2, 2))
        DirectFrame(parent=ui, frameColor=(0.76, 0.76, 0.78, 0.97), frameSize=(-1.32, 1.32, -0.8, 0.8), relief=DGG.RAISED,
                    borderWidth=(0.012, 0.012))
        S = 0.115
        OnscreenText(parent=ui, text="Inventory", pos=(-1.25, 0.70), scale=0.05, fg=(0.2, 0.2, 0.22, 1), align=TextNode.A_left)
        self.inv_buttons = []
        def slot_pos(i):
            if i < 9:
                return -1.25 + S / 2 + i * S, -0.68
            r, c = divmod(i - 9, 9)
            return -1.25 + S / 2 + c * S, -0.12 - r * S - 0.04
        for i in range(36):
            x, z = slot_pos(i)
            b = DirectButton(parent=ui, frameColor=(0.55, 0.55, 0.58, 1), frameSize=(-S / 2 + 0.006, S / 2 - 0.006, -S / 2 + 0.006, S / 2 - 0.006),
                             relief=DGG.SUNKEN, borderWidth=(0.006, 0.006), pos=(x, 0, z), pressEffect=0)
            b.bind(DGG.B1PRESS, lambda e, i=i: self.click_slot(i, 0))
            b.bind(DGG.B3PRESS, lambda e, i=i: self.click_slot(i, 1))
            b.bind(DGG.WITHIN, lambda e, i=i: self._tip_slot(i))
            self.inv_buttons.append(b)
        self.inv_icons = [None] * 36
        OnscreenText(parent=ui, text="Left click: pick up / put down / swap\nRight click: take half / place one\n"
                     + ("Click an item on the right to take a stack" if self.creative else "Click a green recipe to craft it\n(hover to see ingredients)"),
                     pos=(-1.25, 0.55), scale=0.042, fg=(0.3, 0.3, 0.32, 1), align=TextNode.A_left)
        self.tip = OnscreenText(parent=ui, text="", pos=(0, -0.77), scale=0.042, fg=(0.15, 0.15, 0.15, 1))
        right = 0.02
        if self.creative:
            OnscreenText(parent=ui, text="Creative: all blocks & items (click to take a stack)", pos=(right + 0.0, 0.70), scale=0.042,
                         fg=(0.2, 0.2, 0.22, 1), align=TextNode.A_left)
            items = bl.CREATIVE_ITEMS
            for n, it in enumerate(items):
                r, c = divmod(n, 11)
                x, z = right + S / 2 + c * S, 0.58 - r * S
                b = DirectButton(parent=ui, frameColor=(0.62, 0.62, 0.65, 1), frameSize=(-S / 2 + 0.006, S / 2 - 0.006, -S / 2 + 0.006, S / 2 - 0.006),
                                 relief=DGG.RAISED, borderWidth=(0.005, 0.005), pos=(x, 0, z), pressEffect=0)
                b.bind(DGG.B1PRESS, lambda e, it=it: self._take_creative(it))
                b.bind(DGG.WITHIN, lambda e, it=it: self.tip.setText(bl.name_of(it)))
                rd.icon_node(b, it, a.atlas, S * 0.6)
            a.button(ui, "VINE BUILD  (B)", (0.95, -0.68), lambda: (self.toggle_inventory(), self.open_vinebuild()), width=0.3, scale=0.8)
        else:
            OnscreenText(parent=ui, text="Crafting" + ("  (crafting table nearby)" if self.table_near else "  (stand near a Crafting Table for tools)"),
                         pos=(right, 0.70), scale=0.042, fg=(0.2, 0.2, 0.22, 1), align=TextNode.A_left)
            for n, (res, cnt, ing, table) in enumerate(bl.RECIPES):
                r, c = divmod(n, 11)
                x, z = right + S / 2 + c * S, 0.58 - r * S
                ok = all(self.count(k) >= v for k, v in ing.items()) and (self.table_near or not table)
                b = DirectButton(parent=ui, frameColor=(0.45, 0.75, 0.45, 1) if ok else (0.5, 0.5, 0.52, 1),
                                 frameSize=(-S / 2 + 0.006, S / 2 - 0.006, -S / 2 + 0.006, S / 2 - 0.006),
                                 relief=DGG.RAISED, borderWidth=(0.005, 0.005), pos=(x, 0, z), pressEffect=0)
                b.bind(DGG.B1PRESS, lambda e, n=n: self.craft(n))
                need = ", ".join("%d %s" % (v, bl.name_of(k)) for k, v in ing.items())
                b.bind(DGG.WITHIN, lambda e, res=res, cnt=cnt, need=need, table=table:
                       self.tip.setText("%s x%d  <-  %s%s" % (bl.name_of(res), cnt, need, "  [table]" if table else "")))
                ic = rd.icon_node(b, res, a.atlas, S * 0.6)
                if not ok:
                    ic.set_color_scale(0.55, 0.55, 0.55, 1)
        self.cursor_np = None
        self._refresh_inv()

    def _tip_slot(self, i):
        s = self.inv[i]
        self.tip.setText(bl.name_of(s[0]) if s else "")

    def _refresh_inv(self):
        if not self.inv_ui:
            return
        for i in range(36):
            s = self.inv[i]
            b = self.inv_buttons[i]
            for ch in b.get_children():
                if ch.get_name() in ("icon", "cnt"):
                    ch.remove_node()
            if s:
                rd.icon_node(b, s[0], self.app.atlas, 0.07)
                if s[1] > 1:
                    t = OnscreenText(parent=b, text=str(s[1]), pos=(0.045, -0.045), scale=0.036, fg=(1, 1, 1, 1),
                                     shadow=(0, 0, 0, 1), align=TextNode.A_right)
                    t.set_name("cnt")
        if self.cursor_np:
            self.cursor_np.remove_node(); self.cursor_np = None
        if self.cursor_stack:
            self.cursor_np = self.inv_ui.attach_new_node("cursor")
            rd.icon_node(self.cursor_np, self.cursor_stack[0], self.app.atlas, 0.08)
            if self.cursor_stack[1] > 1:
                OnscreenText(parent=self.cursor_np, text=str(self.cursor_stack[1]), pos=(0.05, -0.05), scale=0.036,
                             fg=(1, 1, 1, 1), shadow=(0, 0, 0, 1), align=TextNode.A_right)
            self.cursor_np.set_bin("gui-popup", 50)
        self.refresh_hotbar()

    def click_slot(self, i, button):
        s, c = self.inv[i], self.cursor_stack
        if button == 0:
            if c is None:
                self.inv[i], self.cursor_stack = None, s
            elif s is None:
                self.inv[i], self.cursor_stack = c, None
            elif s[0] == c[0]:
                ms = bl.max_stack(s[0]); t = min(ms - s[1], c[1])
                self.inv[i] = (s[0], s[1] + t)
                self.cursor_stack = (c[0], c[1] - t) if c[1] - t > 0 else None
            else:
                self.inv[i], self.cursor_stack = c, s
        else:
            if c is None and s:
                half = (s[1] + 1) // 2
                self.cursor_stack = (s[0], half); self.inv[i] = (s[0], s[1] - half) if s[1] - half > 0 else None
            elif c and (s is None or (s[0] == c[0] and s[1] < bl.max_stack(s[0]))):
                self.inv[i] = (c[0], (s[1] if s else 0) + 1)
                self.cursor_stack = (c[0], c[1] - 1) if c[1] > 1 else None
        self._refresh_inv()

    def _take_creative(self, it):
        self.cursor_stack = (it, bl.max_stack(it))
        self._refresh_inv()

    def craft(self, n):
        res, cnt, ing, table = bl.RECIPES[n]
        if table and not self.table_near:
            self.tip.setText("Needs a Crafting Table nearby"); return
        if not all(self.count(k) >= v for k, v in ing.items()):
            self.tip.setText("Missing ingredients"); return
        for k, v in ing.items():
            self.take(k, v)
        self.give(res, cnt)
        self._build_inventory()
        self.tip.setText("Crafted %s x%d" % (bl.name_of(res), cnt))

    # ------------------------------------------------------------------ survival
    def can_be_attacked(self):
        return not self.creative and self.state != "dead"

    def hurt_player(self, n, push=(0, 0)):
        if self.creative or self.state == "dead" or self.hurt_t > 0:
            return
        self.health -= n; self.hurt_t = 0.5
        self.vel[0] += push[0] * 6; self.vel[1] += push[1] * 6; self.vel[2] = max(self.vel[2], 5)
        self.exhaust += 0.1
        if self.health <= 0:
            self.health = 0; self.die()

    def die(self):
        self.state = "dead"; self.set_capture(False)
        if self.inv_ui:
            self.inv_ui.destroy(); self.inv_ui = None
        a = self.app
        self.dead_ui = DirectFrame(parent=a.aspect2d, frameColor=(0.5, 0, 0, 0.45), frameSize=(-3, 3, -2, 2))
        OnscreenText(parent=self.dead_ui, text="You died!", pos=(0, 0.3), scale=0.13, fg=(1, 1, 1, 1), shadow=(0, 0, 0, 1))
        a.button(self.dead_ui, "Respawn", (0, 0.0), self.respawn)
        a.button(self.dead_ui, "Title Screen", (0, -0.16), self.quit_to_title)

    def respawn(self):
        if self.dead_ui:
            self.dead_ui.destroy(); self.dead_ui = None
        self.health, self.food, self.exhaust = 20.0, 20.0, 0.0
        sx, sy, sz = self.spawn
        self.pos[:] = (sx, sy, sz); self.vel[:] = 0; self.fall = 0
        self.state = "play"; self.set_capture(True)

    def survival_tick(self, dt, moved):
        if self.creative:
            return
        self.exhaust += moved * (0.1 if self.sprint else 0.01)
        while self.exhaust >= 4.0:
            self.exhaust -= 4.0; self.food = max(0.0, self.food - 1)
        if self.food >= 18 and self.health < 20:
            self.regen_t += dt
            if self.regen_t >= 3.5:
                self.regen_t = 0; self.health = min(20.0, self.health + 1); self.exhaust += 3.0
        if self.food <= 0:
            self.starve_t += dt
            if self.starve_t >= 4.0:
                self.starve_t = 0
                if self.health > 1:
                    self.health -= 1; self.hurt_t = 0.3

    # ------------------------------------------------------------------ main update
    def update(self, task):
        dt = min(globalClock.get_dt(), 0.05)
        self.frames += 1; self.fps_t += dt
        if self.fps_t >= 0.5:
            self.fps = self.frames / max(1e-6, self.fps_t); self.frames = 0; self.fps_t = 0
        if self.loading:
            self.update_chunks(0.035)
            r = self.loaded_ratio(min(self.rd, 3))
            self.app.loading_progress(r)
            if r >= 1.0:
                self.finish_loading()
            self.update_camera(dt); self.update_sky()
            return task.cont
        self.update_chunks()
        if self.state != "paused":
            self.time = (self.time + dt / CYCLE) % 1.0
        self.chat.update()
        if self.build_job:
            self._build_tick(dt)
        if self.state in ("play", "inventory", "dead", "chat", "build"):
            if self.state == "play" and self.captured:
                self.mouse_look()
            self.physics(dt)
            if self.state == "play":
                self.interact(dt)
            else:
                self.crack.hide()
            self.update_mobs(dt)
        self.update_leaves(dt)
        if self.state == "inventory" and self.cursor_np and self.app.mouseWatcherNode.has_mouse():
            m = self.app.mouseWatcherNode.get_mouse()
            self.cursor_np.set_pos(m.x * self.app.getAspectRatio(), 0, m.y)
        self.update_camera(dt)
        self.update_sky()
        self.update_hud(dt)
        self.save_t += dt
        if self.save_t > 60:
            self.save_t = 0; self.save(); self.show_toast("World saved", 1.2)
        return task.cont

    def mouse_look(self):
        w = self.app.win
        md = w.get_pointer(0)
        cx, cy = w.get_x_size() // 2, w.get_y_size() // 2
        dx, dy = md.get_x() - cx, md.get_y() - cy
        if md.get_in_window() and (dx or dy):
            s = 0.12 * float(self.app.settings["sensitivity"])
            self.yaw -= dx * s
            self.pitch = max(-89.5, min(89.5, self.pitch - dy * s))
            self._center_mouse()

    def key(self, c):
        return self.app.mouseWatcherNode.is_button_down(kb(c))

    def physics(self, dt):
        mw = self.app.mouseWatcherNode
        if (int(self.pos[0] // dw.CS), int(self.pos[1] // dw.CS)) not in self.chunk_np:
            return
        play = self.state == "play"
        fwd = (self.key("w") - self.key("s")) if play else 0
        side = (self.key("d") - self.key("a")) if play else 0
        jump = play and mw.is_button_down(KeyboardButton.space())
        sneak = play and mw.is_button_down(KeyboardButton.shift())
        if play and mw.is_button_down(KeyboardButton.control()) and fwd > 0:
            self.sprint = True
        if fwd <= 0 or sneak or (not self.creative and self.food <= 6):
            self.sprint = False
        r = math.radians(self.yaw)
        f = np.array([-math.sin(r), math.cos(r)]); rt = np.array([math.cos(r), math.sin(r)])
        wish = f * fwd + rt * side
        n = np.linalg.norm(wish)
        if n > 0:
            wish /= n
        eye_cell = self.world.get(int(math.floor(self.pos[0])), int(math.floor(self.pos[1])), int(math.floor(self.pos[2] + 0.6)))
        self.in_water = eye_cell == bl.WATER
        if self.flying:
            sp = 21.0 if self.sprint else 10.9
            target = wish * sp
            k = min(1, dt * 8)
            self.vel[0] += (target[0] - self.vel[0]) * k; self.vel[1] += (target[1] - self.vel[1]) * k
            self.vel[2] += ((jump - sneak) * 8.0 - self.vel[2]) * min(1, dt * 10)
        else:
            sp = 1.3 if sneak else (5.6 if self.sprint else 4.3)
            if self.in_water:
                sp *= 0.55
            target = wish * sp
            k = min(1, dt * (12 if self.on_ground else 2.5))
            self.vel[0] += (target[0] - self.vel[0]) * k; self.vel[1] += (target[1] - self.vel[1]) * k
            if self.in_water:
                self.vel[2] = max(-3.0, self.vel[2] - 9 * dt)
                if jump:
                    self.vel[2] = min(4.0, self.vel[2] + 30 * dt)
            else:
                self.vel[2] = max(-60.0, self.vel[2] - 32.0 * dt)
                if jump and self.on_ground:
                    self.vel[2] = 8.9
                    self.exhaust += 0.2 if self.sprint else 0.05
        old = self.pos.copy()
        z_before = self.pos[2]
        was_ground = self.on_ground
        self.on_ground, _ = en.move(self.world, self.pos, self.vel, dt, PLAYER_HW, PLAYER_H - (0.3 if sneak else 0),
                                    guard_edges=sneak and was_ground and not self.flying)
        if self.flying and self.on_ground and not jump:
            pass
        if not self.on_ground and self.pos[2] < z_before and not self.flying and not self.in_water:
            self.fall += z_before - self.pos[2]
        if self.on_ground or self.in_water or self.flying:
            if self.on_ground and self.fall > 3.0 and not self.in_water:
                self.hurt_player(int(math.ceil(self.fall - 3.0)))
            self.fall = 0.0
        if self.creative and self.flying and self.on_ground and self.vel[2] <= 0 and sneak:
            self.flying = False
        if self.pos[2] < -20:
            if self.creative:
                self.pos[2] = 140; self.vel[:] = 0
            else:
                self.hurt_player(100)
        self.survival_tick(dt, float(np.hypot(*(self.pos[:2] - old[:2]))))
        self.sneaking = sneak

    @property
    def player_pos(self):
        return self.pos

    def eye(self):
        return self.pos + np.array([0, 0, 1.62 - (0.25 if getattr(self, "sneaking", False) else 0)])

    def look_dir(self):
        h, p = math.radians(self.yaw), math.radians(self.pitch)
        return np.array([-math.sin(h) * math.cos(p), math.cos(h) * math.cos(p), math.sin(p)])

    def update_camera(self, dt):
        e = self.eye()
        cam = self.app.camera
        cam.set_pos(*e); cam.set_hpr(self.yaw, self.pitch, 0)
        fov = self.base_fov + (8 if self.sprint else 0) + (6 if self.flying and self.sprint else 0)
        cur = self.app.camLens.get_min_fov()
        self.app.camLens.set_min_fov(cur + (fov - cur) * min(1, dt * 10))
        # hand bob + swing
        if self.hand_model is not None:
            p0, h0 = self.hand_base
            sp = float(np.hypot(self.vel[0], self.vel[1])) if self.on_ground else 0
            t = time.time()
            bob = math.sin(t * 9) * 0.012 * min(1, sp / 4)
            self.swing = max(0, self.swing - dt * 4)
            sw = math.sin(self.swing * math.pi)
            self.hand_model.set_pos(p0[0] - sw * 0.12, p0[1] + sw * 0.1, p0[2] + bob - sw * 0.06)
            self.hand_model.set_hpr(h0[0], h0[1] - sw * 40, h0[2])

    def reach(self):
        return 6.0 if self.creative else 5.0

    def interact(self, dt):
        mw = self.app.mouseWatcherNode
        e, d = self.eye(), self.look_dir()
        hit = en.raycast(self.world, e, d, self.reach())
        mob_hit, mob_t = None, 1e9
        for m in self.mobs:
            t = en.ray_aabb(e, d, m.pos - [m.hw, m.hw, 0], m.pos + [m.hw, m.hw, m.hh])
            if t is not None and 0 <= t < mob_t and t <= self.reach():
                mob_hit, mob_t = m, t
        if hit and mob_hit and hit[2] < mob_t:
            mob_hit = None
        self.target = hit
        if hit and not mob_hit:
            self.highlight.show(); self.highlight.set_pos(*hit[0])
        else:
            self.highlight.hide()
        self.break_cd = max(0, self.break_cd - dt); self.place_cd = max(0, self.place_cd - dt)
        self.attack_cd = max(0, self.attack_cd - dt)
        left = mw.is_button_down(MouseButton.one()) or self._m1
        right = mw.is_button_down(MouseButton.three()) or self._m3
        self._m1 = self._m3 = False
        if left and mob_hit and self.attack_cd <= 0:
            kind, tier = bl.tool_info(self.held() or 0)
            dmg = (4 + tier) if kind == "sword" else (2 if kind else 1)
            push = d[:2] / max(1e-6, np.linalg.norm(d[:2]))
            mob_hit.damage(dmg, push)
            if mob_hit.dead:
                self.mobs.remove(mob_hit)
            self.attack_cd = 0.45; self.swing = 1.0; self.exhaust += 0.1
            self.break_cell = None; self.crack.hide()
        elif left and hit and not mob_hit:
            cell = hit[0]
            b = self.world.get(*cell)
            if self.creative:
                if self.break_cd <= 0:
                    self.break_block(cell, b, drop=False); self.break_cd = 0.22; self.swing = 1.0
            else:
                bt = self.break_time(b)
                if bt is None:
                    self.crack.hide()
                else:
                    if self.break_cell != cell:
                        self.break_cell, self.break_prog = cell, 0.0
                    self.break_prog += dt / max(bt, 0.05)
                    if self.swing <= 0.05:
                        self.swing = 1.0
                    stage = min(9, int(self.break_prog * 10))
                    self.crack.show(); self.crack.set_pos(cell[0] - 0.002, cell[1] - 0.002, cell[2] - 0.002)
                    self.crack.set_tex_offset(TextureStage.get_default(), stage / float(bl.ATLAS_N), 0)
                    if self.break_prog >= 1.0:
                        self.break_block(cell, b, drop=True)
                        self.break_cell = None; self.crack.hide()
        else:
            self.break_cell = None; self.break_prog = 0.0; self.crack.hide()
        if right and self.place_cd <= 0:
            h = self.held()
            if hit and self.world.get(*hit[0]) == bl.TABLE and not mw.is_button_down(KeyboardButton.shift()):
                self.place_cd = 0.3
                self.toggle_inventory(table=True); return
            if h in bl.FOOD and not self.creative and self.food < 20:
                self.food = min(20.0, self.food + bl.FOOD[h]); self.consume_held(); self.place_cd = 0.6; self.swing = 1.0
                self.show_toast("Yum!", 1.0)
            elif h in bl.BLOCKS and hit:
                c = hit[1]
                if self.world.get(*c) in (bl.AIR, bl.WATER) and not self._blocks_entity(c, h):
                    if self.world.set(*c, h):
                        self.mark_dirty(c[0], c[1]); self.consume_held(); self.swing = 1.0
                        self.place_cd = 0.22

    def _blocks_entity(self, c, h):
        if not bl.SOLID[h]:
            return False
        x, y, z = c
        boxes = [(self.pos, PLAYER_HW, PLAYER_H)] + [(m.pos, m.hw, m.hh) for m in self.mobs]
        for p, hw, hh in boxes:
            if x < p[0] + hw and x + 1 > p[0] - hw and y < p[1] + hw and y + 1 > p[1] - hw and z < p[2] + hh and z + 1 > p[2]:
                return True
        return False

    def break_time(self, b):
        B = bl.BLOCKS.get(b)
        if B is None or B.hard < 0:
            return None
        kind, tier = bl.tool_info(self.held() or 0)
        ok = B.tier < 0 or (kind == B.tool and tier >= B.tier)
        speed = bl.TIER_SPEED[tier] if (kind is not None and kind == B.tool) else 1.0
        return B.hard * (1.5 if ok else 5.0) / speed

    def break_block(self, cell, b, drop):
        if b == bl.BEDROCK and not self.creative:
            return
        self.world.set(*cell, bl.AIR)
        self.mark_dirty(cell[0], cell[1])
        self.exhaust += 0.005
        if drop:
            B = bl.BLOCKS[b]
            kind, tier = bl.tool_info(self.held() or 0)
            if B.tier < 0 or (kind == B.tool and tier >= B.tier):
                it = B.drop if B.drop is not None else b
                if b == bl.LEAVES or b in bl.AUTUMN_LEAVES:
                    it = bl.APPLE if random.random() < 0.06 else (b if random.random() < 0.25 else 0)
                if it:
                    self.give(it, 1)

    # ------------------------------------------------------------------ mobs
    def update_mobs(self, dt):
        self.spawn_t += dt
        day = self.daylight()
        if self.spawn_t > 2.0:
            self.spawn_t = 0
            passive = sum(1 for m in self.mobs if not m.hostile)
            hostile = len(self.mobs) - passive
            if passive < 7:
                self._try_spawn(en.Mossbuck, want_grass=True)
            if day < 0.38 and hostile < 6:
                self._try_spawn(en.Gloomer, want_grass=False)
        for m in list(self.mobs):
            if m.dead:
                self.mobs.remove(m); continue
            k = (int(m.pos[0] // dw.CS), int(m.pos[1] // dw.CS))
            far = np.hypot(*(m.pos[:2] - self.pos[:2])) > 80
            if far or k not in self.chunk_np or (m.hostile and day > 0.6 and random.random() < dt * 0.25):
                m.remove(); self.mobs.remove(m); continue
            m.update(dt)
            if m.dead and m in self.mobs:
                self.mobs.remove(m)
        self.mob_root.set_color_scale(self._light, self._light, self._light, 1)

    def _try_spawn(self, cls, want_grass):
        a = random.uniform(0, 2 * math.pi); r = random.uniform(18, 40)
        x = int(math.floor(self.pos[0] + math.cos(a) * r)); y = int(math.floor(self.pos[1] + math.sin(a) * r))
        if (x // dw.CS, y // dw.CS) not in self.chunk_np:
            return
        z = self.world.surface_z(x, y)
        ground = self.world.get(x, y, z - 1)
        if ground == bl.WATER or ground in bl.LEAF_BLOCKS or (want_grass and ground not in (bl.GRASS, bl.LEAF_LITTER)):
            return
        if self.world.get(x, y, z) != bl.AIR or self.world.get(x, y, z + 1) != bl.AIR:
            return
        self.mobs.append(cls(self, (x + 0.5, y + 0.5, z + 0.01)))

    # ------------------------------------------------------------------ falling autumn leaves (1.4.0)
    MAX_LEAVES = 48

    def _init_leaves(self):
        self.leaf_cols = {}
        self.leaf_root = self.root.attach_new_node("falling-leaves")
        self.leaf_root.set_texture(self.app.atlas); self.leaf_root.set_transparency(TransparencyAttrib.M_binary)
        self.leaf_root.set_two_sided(True); self.leaf_root.set_light_off(1)
        cm = CardMaker("leaf"); cm.set_frame(-0.5, 0.5, -0.5, 0.5)
        u0, v0, u1, v1 = bl.tile_uv(bl.TILE["falling_leaf"]); cm.set_uv_range((u0, v0), (u1, v1))
        cols = [bl.AUTUMN_RGB[b] for b in bl.AUTUMN_LEAVES]
        self.leaf_pool = []
        for i in range(self.MAX_LEAVES):
            n = self.leaf_root.attach_new_node(cm.generate())
            n.set_scale(0.22); n.hide()
            r, g, b = cols[i % 4]; n.set_color(r / 255.0, g / 255.0, b / 255.0, 1)
            self.leaf_pool.append([n, False, 0.0, 0.0, 0.0, 0.0, 0.0])   # node, alive, x, y, z, phase, life
        self.leaf_spawn_t = 0.0

    def update_leaves(self, dt):
        self.leaf_root.set_color_scale(self._light, self._light, self._light, 1)
        if self.state == "paused":
            return
        px, py = self.pos[0], self.pos[1]
        self.leaf_spawn_t += dt
        if self.leaf_spawn_t > 0.12:
            self.leaf_spawn_t = 0.0
            pc = (int(px // dw.CS), int(py // dw.CS))
            near = [self.leaf_cols[(pc[0] + a, pc[1] + b)] for a in (-1, 0, 1) for b in (-1, 0, 1)
                    if (pc[0] + a, pc[1] + b) in self.leaf_cols]
            free = [L for L in self.leaf_pool if not L[1]]
            if near and free:
                for _ in range(min(2, len(free))):
                    arr = near[random.randrange(len(near))]
                    x, y, z = arr[random.randrange(len(arr))]
                    if (x + 0.5 - px) ** 2 + (y + 0.5 - py) ** 2 > 24 ** 2:
                        continue
                    L = free.pop()
                    L[1:] = [True, x + random.random(), y + random.random(), z - 0.05, random.uniform(0, 6.28), 0.0]
                    L[0].show()
        t = globalClock.get_frame_time()
        for L in self.leaf_pool:
            if not L[1]:
                continue
            L[6] += dt
            ph = L[5]
            L[2] += (0.35 * math.sin(t * 1.3 + ph) + 0.25) * dt
            L[3] += 0.35 * math.cos(t * 1.1 + ph * 1.7) * dt
            L[4] -= (0.55 + 0.25 * math.sin(t * 2.0 + ph)) * dt
            b = self.world.get(int(math.floor(L[2])), int(math.floor(L[3])), int(math.floor(L[4])), bl.STONE)
            if L[6] > 14.0 or (bl.SOLID[b] and b not in bl.LEAF_BLOCKS) or b == bl.WATER:
                L[1] = False; L[0].hide(); continue
            L[0].set_pos(L[2], L[3], L[4])
            L[0].set_hpr(t * 60 + ph * 57, 50 * math.sin(t * 2.2 + ph), 35 * math.cos(t * 1.7 + ph))

    # ------------------------------------------------------------------ sky
    def daylight(self):
        s = math.sin(2 * math.pi * self.time)
        return max(0.0, min(1.0, s * 2.5 + 0.45))

    def update_sky(self):
        th = 2 * math.pi * self.time
        s = math.sin(th)
        day = self.daylight()
        night, dayc = np.array([0.02, 0.03, 0.08]), np.array([0.50, 0.72, 1.0])
        sky = night + (dayc - night) * day
        if abs(s) < 0.25 and math.cos(th) < 0 or (abs(s) < 0.25 and math.cos(th) > 0):
            k = (1 - abs(s) / 0.25) * 0.55
            sky = sky * (1 - k) + np.array([1.0, 0.56, 0.30]) * k * max(0.6, day)
        if self.in_water:
            sky = np.array([0.08, 0.18, 0.45]) * (0.4 + 0.6 * day)
            self.fog.set_linear_range(1.0, 22.0); self.water_overlay.show()
        else:
            self.fog.set_linear_range(self.rd * 16 * 0.55, self.rd * 16 * 0.95); self.water_overlay.hide()
        self.app.set_background_color(*sky, 1)
        self.fog.set_color(*sky)
        self._light = 0.22 + 0.78 * day
        self.terrain.set_color_scale(self._light, self._light, self._light, 1)
        self.water_root.set_color_scale(self._light, self._light, self._light, 1)
        self.hand.set_color_scale(max(0.4, self._light), max(0.4, self._light), max(0.4, self._light), 1)
        cp = self.app.camera.get_pos()
        self.sky.set_pos(cp)
        dvec = Vec3(math.cos(th), 0.25, math.sin(th)) * 300
        self.sun.set_pos(dvec); self.moon.set_pos(-dvec)
        cx, cy = math.floor(self.pos[0] / 64) * 64, math.floor(self.pos[1] / 64) * 64
        self.clouds.set_pos(cx, cy, 108)
        ts = TextureStage.get_default()
        self.clouds.set_tex_offset(ts, (cx / 1024.0 * 16 + time.time() * 0.004) % 1, (cy / 1024.0 * 16) % 1)
        cl = 0.35 + 0.65 * day
        self.clouds.set_color_scale(cl, cl, cl * 1.02, 0.85)

    # ------------------------------------------------------------------ HUD
    def update_hud(self, dt):
        self.hurt_t = max(0, self.hurt_t - dt)
        self.hurt_overlay["frameColor"] = (0.8, 0, 0, min(0.35, self.hurt_t * 0.7))
        key = (int(self.health), int(self.food), self.creative)
        if key != self._hud_cache:
            self._hud_cache = key
            for i in range(10):
                for arr, val, tex in ((self.hearts, self.health, self.app.tex_heart), (self.foods, self.food, self.app.tex_food)):
                    v = val - i * 2
                    arr[i].set_texture(tex["full"] if v >= 2 else (tex["half"] if v >= 1 else tex["empty"]), 1)
                    (arr[i].hide if self.creative else arr[i].show)()
        if self.label_t > 0:
            self.label_t -= dt
            if self.label_t <= 0:
                self.item_label.setText("")
        rec = self.app.screen_rec
        self.toast.setPos(-0.04, -0.2 if rec.active else -0.08)
        if rec.active:
            e = rec.elapsed()
            self.rec_text.setText("REC " + self._fmt_t(e))
            (self.rec_dot.show if int(e * 2) % 2 == 0 else self.rec_dot.hide)()
            if self.pause_ui and getattr(self, "_rec_btn", None):
                self._rec_btn["text"] = "Stop recording  (%s)" % self._fmt_t(e)
        if self.toast_t > 0:
            self.toast_t -= dt
            if self.toast_t <= 0:
                self.toast.setText("")
        if self.show_debug:
            x, y, z = self.pos
            facing = ["south", "west", "north", "east"][int(((self.yaw % 360) + 45) // 90) % 4] if False else \
                ["north (+Y)", "west (-X)", "south (-Y)", "east (+X)"][int(((self.yaw % 360) + 45) // 90) % 4]
            tgt = ("%d %d %d %s" % (self.target[0] + (bl.name_of(self.world.get(*self.target[0])),))) if self.target else "-"
            self.debug.setText("DREAM VINE %s  (%d fps)\nXYZ: %.2f / %.2f / %.2f\nChunk: %d %d   loaded %d (meshes %d)\n"
                               "Facing: %s  yaw %.0f pitch %.0f\nTime: %.0f%%  daylight %.2f\nSeed: %d   Mode: %s%s\nMobs: %d\nTarget: %s"
                               % (self.app.VERSION, self.fps, x, y, z, x // 16, y // 16, len(self.world.chunks), len(self.chunk_np),
                                  facing, self.yaw % 360, self.pitch, self.time * 100, self.daylight(), self.world.seed,
                                  "Creative" if self.creative else "Survival", "  (flying)" if self.flying else "",
                                  len(self.mobs), tgt))

    # ------------------------------------------------------------------ persistence
    # ------------------------------------------------------------------ text chat
    def _k(self, f):
        """Key handler wrapper: hotkeys are disabled while chat or VINE BUILD is open."""
        def h(*a):
            if self.state in ("chat", "build"):
                return
            return f(*a)
        return h

    def player_name(self):
        return str(self.app.settings.get("player_name") or "Player")[:16]

    def open_chat(self, prefill=""):
        if self.state != "play" or self.loading or time.time() - self._ui_closed_t < 0.3 or time.time() - self.chat.closed_t < 0.3:
            return
        self.state = "chat"; self.set_capture(False)
        # open on the next frame so the key that opened chat isn't typed into it
        self.app.do_method_later(0.05, lambda t: (self.chat.open_input(prefill) if self.state == "chat" else None, t.done)[1], "chat-open")

    def chat_closed(self):
        if self.state == "chat":
            self.state = "play"; self.set_capture(True)

    def on_chat(self, text):
        if text.startswith("/"):
            self.chat.add(text, (0.7, 0.7, 0.7, 1))
            try:
                self.run_command(text[1:])
            except Exception as e:
                self.chat.system("Command error: %s" % e)
        else:
            self.chat.add("<%s> %s" % (self.player_name(), text))

    def run_command(self, line):
        parts = line.split()
        if not parts:
            return
        cmd, args = parts[0].lower(), parts[1:]
        say = self.chat.system
        if cmd in ("help", "?"):
            for l in ("Commands:", "/gamemode survival|creative  - switch game mode", "/time day|night|noon|midnight|<number>",
                      "/tp <x> <y> <z>  - teleport (~ = current)", "/seed  - show the world seed", "/clear  - clear chat",
                      "/build <description>  - VINE BUILD (creative)", "/undo  - undo the last VINE BUILD",
                      "/name <name>  - set your player name"):
                say(l)
        elif cmd == "gamemode":
            m = (args[0].lower() if args else "")
            if m in ("creative", "c", "1"):
                self.creative = True
            elif m in ("survival", "s", "0"):
                self.creative = False; self.flying = False
            else:
                say("Usage: /gamemode survival|creative"); return
            self.meta["mode"] = "creative" if self.creative else "survival"
            self.refresh_hotbar()
            say("Game mode set to %s" % ("Creative" if self.creative else "Survival"))
        elif cmd == "time":
            a = [x.lower() for x in args if x.lower() not in ("set",)]
            names = {"day": 0.12, "morning": 0.05, "noon": 0.25, "midday": 0.25, "sunset": 0.47, "evening": 0.47,
                     "night": 0.65, "midnight": 0.75, "sunrise": 0.98, "dawn": 0.98}
            if not a:
                say("Time is %d (0-24000)" % int(self.time * 24000)); return
            if a[0] in names:
                self.time = names[a[0]]
            else:
                v = float(a[0])
                self.time = (v % 24000) / 24000.0 if v > 1 else v % 1.0
            say("Time set to %s" % a[0])
        elif cmd in ("tp", "teleport"):
            if len(args) < 3:
                say("Usage: /tp <x> <y> <z>"); return
            cur = [self.pos[0], self.pos[1], self.pos[2]]
            v = []
            for i, s in enumerate(args[:3]):
                if s.startswith("~"):
                    v.append(cur[i] + (float(s[1:]) if len(s) > 1 else 0.0))
                else:
                    v.append(float(s))
            v[2] = max(1.0, min(dw.H - 2.0, v[2]))
            self.world.ensure(int(v[0]) // dw.CS, int(v[1]) // dw.CS)
            self.pos[:] = v; self.vel[:] = 0
            say("Teleported to %.1f %.1f %.1f" % tuple(v))
        elif cmd == "seed":
            say("Seed: %s" % self.meta.get("seed"))
        elif cmd == "clear":
            self.chat.clear()
        elif cmd == "build":
            if not args:
                say("Usage: /build <description>, e.g. /build japanese temple"); return
            self.vine_build(" ".join(args))
        elif cmd == "undo":
            self.undo_build()
        elif cmd == "name":
            if not args:
                say("Your name is %s" % self.player_name()); return
            self.app.settings["player_name"] = " ".join(args)[:16]
            self.app.save_settings()
            say("Your name is now %s" % self.player_name())
        else:
            say("Unknown command /%s - type /help" % cmd)

    # ------------------------------------------------------------------ VINE BUILD (Vine AI, offline)
    def open_vinebuild(self):
        if self.state != "play" or self.loading:
            return
        if not self.creative:
            msg = "VINE BUILD is Creative-only. Use /gamemode creative to try it."
            self.show_toast(msg, 3.5); self.chat.system(msg); return
        self.state = "build"; self.set_capture(False)
        self.vb_ui = dv_chat.VineBuildUI(self, vb.EXAMPLES, vb.plan_and_generate)

    def close_vinebuild(self):
        if self.vb_ui:
            self.vb_ui.destroy(); self.vb_ui = None
        self._ui_closed_t = time.time()
        if self.state == "build":
            self.state = "play"; self.set_capture(True)

    def on_z(self):
        mw = self.app.mouseWatcherNode
        if mw.is_button_down(KeyboardButton.control()):
            self.undo_build()

    def _ground(self, x, y):
        c = self.world.chunks.get((x // dw.CS, y // dw.CS))
        if c is None:
            return None
        col = c[x % dw.CS, y % dw.CS]
        ok = bl.SOLID[col] & ~np.isin(col, (bl.LOG,) + bl.LEAF_BLOCKS) | (col == bl.WATER)
        nz = np.nonzero(ok)[0]
        return int(nz.max()) + 1 if len(nz) else None

    def vine_build(self, text):
        say = self.chat.system
        if not self.creative:
            msg = "VINE BUILD is Creative-only. Use /gamemode creative to try it."
            self.show_toast(msg, 3.5); say(msg); return
        if self.build_job:
            say("Vine AI is still building - wait a moment."); return
        canvas, summary = vb.plan_and_generate(text)
        say(summary)
        x0, x1, y0, y1, z0, z1 = canvas.bounds(True)
        fx, fy = -math.sin(math.radians(self.yaw)), math.cos(math.radians(self.yaw))
        f = (1 if fx > 0 else -1, 0) if abs(fx) > abs(fy) else (0, 1 if fy > 0 else -1)
        r = (f[1], -f[0])
        px, py = int(math.floor(self.pos[0])), int(math.floor(self.pos[1]))
        gap = 3
        def to_w(lx, ly):
            d = ly - y0 + gap
            return px + r[0] * lx + f[0] * d, py + r[1] * lx + f[1] * d
        corners = [to_w(a, b) for a in (x0, x1) for b in (y0, y1)]
        for cx in range(min(c[0] for c in corners) // dw.CS - 1, max(c[0] for c in corners) // dw.CS + 2):
            for cy in range(min(c[1] for c in corners) // dw.CS - 1, max(c[1] for c in corners) // dw.CS + 2):
                self.world.ensure(cx, cy)
        hs = []
        for a in np.linspace(x0, x1, 5):
            for b in np.linspace(y0, y1, 5):
                g = self._ground(*to_w(int(a), int(b)))
                if g is not None:
                    hs.append(g)
        base = int(np.median(hs)) if hs else int(self.pos[2])
        base = max(2, min(dw.H - 3 - (z1 + 1), base))
        cells = {}
        cols = {}
        for (lx, ly, lz), b in canvas.b.items():
            wx, wy = to_w(lx, ly)
            wz = base + lz
            if 1 <= wz < dw.H - 1:
                cells[(wx, wy, wz)] = b
            if b != bl.AIR and lz >= 0:
                cols[(lx, ly)] = max(cols.get((lx, ly), -1), lz)
        clear_top = z1 + 2
        for (lx, ly), top in cols.items():
            wx, wy = to_w(lx, ly)
            for lz in range(0, clear_top):                  # clear terrain/trees inside the building volume
                k = (wx, wy, base + lz)
                if k not in cells and base + lz < dw.H - 1 and self.world.get(*k) != bl.AIR:
                    cells[k] = bl.AIR
            b0 = canvas.b.get((lx, ly, 0), bl.AIR)
            if b0 != bl.AIR:                                 # foundations down to the ground
                fb = b0 if (bl.OPAQUE[b0] and bl.SOLID[b0] and b0 not in (bl.LANTERN,)) else bl.COBBLE
                for d in range(1, 16):
                    k = (wx, wy, base - d)
                    if k in cells or base - d < 1 or self.world.get(*k) not in (bl.AIR, bl.WATER, bl.LOG) + bl.LEAF_BLOCKS:
                        break
                    cells[k] = fb
        cxw, cyw = to_w((x0 + x1) // 2, (y0 + y1) // 2)
        todo = [(k, b) for k, b in cells.items() if self.world.get(*k) != b]
        todo.sort(key=lambda kb: (kb[1] != bl.AIR, kb[0][2], (kb[0][0] - cxw) ** 2 + (kb[0][1] - cyw) ** 2))
        if not todo:
            say("Nothing to build here."); return
        self.build_job = {"todo": todo, "i": 0, "t": 0.0, "dur": max(1.0, min(3.0, len(todo) / 2500.0)), "undo": [],
                          "summary": summary, "text": text}
        wxs = [k[0] for k, _ in todo]; wys = [k[1] for k, _ in todo]; wzs = [k[2] for k, _ in todo]
        self.build_wire = rd.wire_cube(self.root, (0.4, 1.0, 0.4, 1.0), 2.5)
        self.build_wire.set_pos(min(wxs), min(wys), min(wzs))
        self.build_wire.set_scale(max(wxs) - min(wxs) + 1, max(wys) - min(wys) + 1, max(wzs) - min(wzs) + 1)
        self.build_wire.set_light_off(1); self.build_wire.set_fog_off(1)
        self.show_toast("Vine AI is building...", 3.0)

    def _build_tick(self, dt):
        j = self.build_job
        j["t"] += dt
        n = len(j["todo"])
        target = n if j["t"] >= j["dur"] else int(n * (j["t"] / j["dur"]) ** 1.15)
        w = self.world
        while j["i"] < target:
            (x, y, z), b = j["todo"][j["i"]]
            old = w.get(x, y, z)
            if w.set(x, y, z, b):
                j["undo"].append((x, y, z, old))
                cx, cy = x // dw.CS, y // dw.CS
                self.dirty_slow.add((cx, cy))
                lx, ly = x % dw.CS, y % dw.CS
                if lx == 0: self.dirty_slow.add((cx - 1, cy))
                if lx == dw.CS - 1: self.dirty_slow.add((cx + 1, cy))
                if ly == 0: self.dirty_slow.add((cx, cy - 1))
                if ly == dw.CS - 1: self.dirty_slow.add((cx, cy + 1))
            j["i"] += 1
        if self.build_wire:
            a = 0.5 + 0.5 * math.sin(j["t"] * 10)
            self.build_wire.set_color_scale(0.5 + 0.5 * a, 1, 0.5 + 0.5 * a, 1)
        self.show_toast("Vine AI is building... %d%%" % int(100 * j["i"] / max(1, n)), 1.0)
        if j["i"] >= n:
            self.build_undo.append(j["undo"]); self.build_undo = self.build_undo[-10:]
            self.build_job = None
            if self.build_wire:
                self.build_wire.remove_node(); self.build_wire = None
            self.show_toast("VINE BUILD done! %d blocks - Ctrl+Z to undo" % len(j["undo"]), 4.0)
            self.chat.system("Vine AI: done! Placed %d blocks. Press Ctrl+Z or type /undo to undo." % len(j["undo"]))

    def undo_build(self):
        if self.build_job:
            self.chat.system("Wait for the current build to finish."); return
        if not self.build_undo:
            self.show_toast("Nothing to undo"); self.chat.system("Nothing to undo."); return
        rec = self.build_undo.pop()
        for x, y, z, old in reversed(rec):
            self.world.ensure(x // dw.CS, y // dw.CS)
            self.world.set(x, y, z, old)
            self.dirty_slow.add((x // dw.CS, y // dw.CS))
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                self.dirty_slow.add(((x + dx) // dw.CS, (y + dy) // dw.CS))
        if self.vb_ui:
            self.close_vinebuild()
        self.show_toast("Undid last VINE BUILD (%d blocks restored)" % len(rec), 3.0)
        self.chat.system("Undid the last VINE BUILD (%d blocks restored)." % len(rec))

    def save(self):
        self.world.save_all()
        self.meta["chat"] = self.chat.history()[-dv_chat.HISTORY:]
        self.meta.update({"time": self.time, "spawn": self.spawn, "last_played": time.time(),
                          "player": {"pos": [float(v) for v in self.pos], "yaw": self.yaw, "pitch": self.pitch,
                                     "health": self.health, "food": self.food, "inv": [list(s) if s else None for s in self.inv],
                                     "sel": self.sel, "flying": self.flying}})
        tmp = os.path.join(self.save_dir, "level.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.meta, f, indent=1)
        os.replace(tmp, os.path.join(self.save_dir, "level.json"))

    def destroy(self):
        self.ignore_all()
        self.app.task_mgr.remove("dv-game-update")
        if self.vb_ui:
            self.vb_ui.destroy(); self.vb_ui = None
        if self.build_wire:
            self.build_wire.remove_node()
        self.chat.destroy()
        for m in self.mobs:
            m.remove()
        for ui in (self.inv_ui, self.pause_ui, self.dead_ui):
            if ui: ui.destroy()
        self.hurt_overlay.destroy(); self.water_overlay.destroy()
        self.debug.destroy(); self.toast.destroy(); self.rec_ui.remove_node()
        self.hud.remove_node(); self.hand.remove_node(); self.sky.remove_node(); self.root.remove_node()
        self.set_capture(False)
        self.app.set_background_color(0, 0, 0, 1)

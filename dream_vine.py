"""DREAM VINE - an original voxel sandbox game by EX Inc. (c)2026 EX Inc.
All code, textures, names and art are original and generated procedurally."""
import os, sys, json, time, math, random, threading, tempfile, urllib.request, shutil, traceback

APP_NAME = "DREAM VINE"
APP_VERSION = "1.3.2"
REPO = "Teobokki/dream-vine"
UPDATE_URL = "https://raw.githubusercontent.com/%s/main/latest.json" % REPO
RELEASES_URL = "https://github.com/%s/releases/latest" % REPO

BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
if os.name == "nt":
    DATA = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), APP_NAME)
else:
    DATA = os.path.join(os.path.expanduser("~"), ".dream-vine")
SAVES = os.path.join(DATA, "saves")
os.makedirs(SAVES, exist_ok=True)


def log_error(msg):
    try:
        with open(os.path.join(DATA, "error.log"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except Exception:
        pass


from panda3d.core import loadPrcFileData, Filename
_icon = os.path.join(BASE, "assets", "icon.ico")
loadPrcFileData("", """
window-title DREAM VINE
win-size 1280 720
sync-video true
audio-library-name p3openal_audio
audio-sfx-active #f
audio-preload-threshold 50000000
audio-cache-limit 4
textures-power-2 none
framebuffer-multisample 0
notify-level warning
default-directnotify-level warning
load-display pandagl
aux-display p3tinydisplay
want-pstats false
""")
if os.path.exists(_icon):
    loadPrcFileData("", "icon-filename " + Filename.from_os_specific(_icon).get_fullpath())

import numpy as np
from direct.showbase.ShowBase import ShowBase
from direct.gui.DirectGui import DirectFrame, DirectButton, DirectSlider, DirectEntry, DGG
from direct.gui.OnscreenText import OnscreenText
from direct.gui.OnscreenImage import OnscreenImage
from panda3d.core import TextNode, TransparencyAttrib, WindowProperties, Fog, TextureStage
import dv_blocks as bl
import dv_world as dw
import dv_render as rd
import dv_art
from dv_game import Game, heart_img, food_img
from direct.gui import DirectGuiGlobals
from dv_recorder import Recorder

DEFAULT_SETTINGS = {"render_distance": 6, "sensitivity": 1.0, "fov": 75, "fullscreen": False, "player_name": "Player"}
MUSIC_VOLUME = 0.7          # menu music volume is fixed (not user-adjustable)
SPLASHES = ["Grown, not built!", "100% original pixels!", "Now with Gloomers!", "Mind the vines!", "Made by EX Inc.!",
            "Dream big, dig deep!", "Mossbucks approve!", "Infinite-ish worlds!", "Punch a log!"]


def vtuple(v):
    out = []
    for p in str(v).strip().lstrip("vV").split("."):
        n = "".join(ch for ch in p if ch.isdigit())
        out.append(int(n) if n else 0)
    return tuple(out + [0] * (3 - len(out)))


def is_portable():
    """True for the single-file portable build (DREAM.VINE.Portable.exe), False for the installed/onedir copy or source."""
    if not getattr(sys, "frozen", False) or not hasattr(sys, "_MEIPASS"):
        return False
    exe = os.path.normcase(os.path.abspath(sys.executable))
    meipass = os.path.normcase(os.path.abspath(sys._MEIPASS))
    if meipass.startswith(os.path.dirname(exe) + os.sep):   # onedir build: _internal next to the exe
        return False
    la = os.environ.get("LOCALAPPDATA")
    if la and exe.startswith(os.path.normcase(os.path.join(la, "Programs", APP_NAME)) + os.sep):
        return False
    return True


def check_update():
    req = urllib.request.Request(UPDATE_URL + "?t=%d" % time.time(), headers={"User-Agent": "DREAM-VINE/" + APP_VERSION})
    m = json.loads(urllib.request.urlopen(req, timeout=10).read(65536).decode("utf-8"))
    ver = str(m["version"])
    if vtuple(ver) > vtuple(APP_VERSION):
        if is_portable() and m.get("portable_url"):
            return "newer", {"version": ver, "notes": m.get("notes", ""), "link": m["portable_url"], "portable": True}
        return "newer", {"version": ver, "notes": m.get("notes", ""), "link": m.get("installer_url") or m.get("url") or RELEASES_URL}
    return "latest", "You have the latest version (%s)." % APP_VERSION


def seed_from_text(t):
    t = t.strip()
    if not t:
        return random.randint(-2 ** 31, 2 ** 31 - 1)
    try:
        return int(t)
    except ValueError:
        h = 0
        for ch in t:
            h = (31 * h + ord(ch)) & 0xFFFFFFFF
        return h - (1 << 32) if h >= (1 << 31) else h


class TitleScene:
    """Slowly rotating panorama over a demo world shown behind the menus."""
    def __init__(self, app):
        self.app = app
        self.root = app.render.attach_new_node("title-scene")
        w = dw.World(2026)
        self.root.set_texture(app.atlas)
        R = 3
        x0 = 40
        for cx in range(-R - 1, R + 2):
            for cy in range(-R - 1, R + 2):
                w.ensure(cx, cy)
        tr = self.root.attach_new_node("t"); tr.set_transparency(TransparencyAttrib.M_binary)
        wa = self.root.attach_new_node("w"); wa.set_transparency(TransparencyAttrib.M_alpha); wa.set_depth_write(False)
        wa.set_bin("transparent", 10)
        for cx in range(-R, R + 1):
            for cy in range(-R, R + 1):
                s, wt = dw.build_mesh(w, cx, cy)
                for data, parent in ((s, tr), (wt, wa)):
                    if data:
                        n = parent.attach_new_node(rd.mesh_node("c", *data)); n.set_pos(cx * 16, cy * 16, 0)
        self.h = float(w.surface_z(8, 8))
        f = Fog("tf"); f.set_color(0.62, 0.80, 1.0); f.set_linear_range(30, 60)
        self.root.set_fog(f)
        self.t = 0.0
        app.task_mgr.add(self.spin, "title-spin")

    def spin(self, task):
        self.t += globalClock.get_dt()
        a = self.t * 4.0
        self.app.camera.set_pos(8, 8, max(self.h, dw.SEA) + 14)
        self.app.camera.set_hpr(a, -14, 0)
        self.app.set_background_color(0.62, 0.80, 1.0, 1)
        return task.cont

    def destroy(self):
        self.app.task_mgr.remove("title-spin")
        self.root.remove_node()


class App(ShowBase):
    VERSION = APP_VERSION

    def __init__(self):
        ShowBase.__init__(self)
        self.disable_mouse()
        self.settings = dict(DEFAULT_SETTINGS)
        try:
            self.settings.update(json.load(open(os.path.join(DATA, "settings.json"), encoding="utf-8")))
        except Exception:
            pass
        self.settings.pop("music_volume", None)      # ignored: music volume is locked at 70%
        self.atlas = rd.np_texture(bl.build_atlas(), "atlas")
        self.tex_sun = rd.np_texture(dv_art.sun(), "sun"); self.tex_moon = rd.np_texture(dv_art.moon(), "moon")
        self.tex_clouds = rd.np_texture(dv_art.clouds_tex(), "clouds")
        from panda3d.core import SamplerState
        self.tex_clouds.set_wrap_u(SamplerState.WM_repeat); self.tex_clouds.set_wrap_v(SamplerState.WM_repeat)
        self.tex_heart = {k: rd.np_texture(heart_img(k), "h" + k) for k in ("full", "half", "empty")}
        self.tex_food = {k: rd.np_texture(food_img(k), "f" + k) for k in ("full", "half", "empty")}
        self.tex_logo = rd.np_texture(dv_art.logo(12), "logo")
        _yy, _xx = np.mgrid[0:32, 0:32]; _dot = np.zeros((32, 32, 4), np.uint8)
        _dot[(_xx - 15.5) ** 2 + (_yy - 15.5) ** 2 < 15 ** 2] = (235, 30, 30, 255)
        self.tex_recdot = rd.np_texture(_dot, "recdot")
        self.camLens.set_min_fov(float(self.settings["fov"]))
        self.game = None; self.scene = None; self.screen = None; self.overlay = None
        self._upd_result = None
        self.apply_fullscreen()
        self.exitFunc = self.on_exit
        self.accept("window-event", self._on_window_event)
        DirectGuiGlobals.setDefaultClickSound(None); DirectGuiGlobals.setDefaultRolloverSound(None)
        self._init_music()
        self.screen_rec = Recorder(self)
        self.show_title()
        auto = os.environ.get("DV_AUTOPLAY")      # developer/testing shortcut: DV_AUTOPLAY=name:seed:mode
        if auto:
            name, seed, mode = (auto.split(":") + ["", "", "survival"])[:3]
            if not os.path.exists(os.path.join(SAVES, name, "level.json")):
                os.makedirs(os.path.join(SAVES, name), exist_ok=True)
                json.dump({"name": name, "seed": seed_from_text(seed), "mode": mode, "last_played": time.time(), "time": 0.03},
                          open(os.path.join(SAVES, name, "level.json"), "w"))
            self.start_game(name)
        ts = os.environ.get("DV_TESTSCRIPT")      # developer/testing hook (not used by players)
        if ts and not getattr(sys, "frozen", False):
            self.do_method_later(float(os.environ.get("DV_TESTDELAY", "12")),
                                 lambda t: exec(open(ts).read(), {"app": self, "__name__": "dvtest"}) or t.done, "dv-test")

    # ---------------------------------------------------------------- helpers
    def downloads_dir(self):
        d = os.path.join(os.path.expanduser("~"), "Downloads")
        os.makedirs(d, exist_ok=True)
        return d

    def save_settings(self):
        try:
            json.dump(self.settings, open(os.path.join(DATA, "settings.json"), "w", encoding="utf-8"), indent=1)
        except Exception as e:
            log_error("settings: %r" % e)

    def apply_fullscreen(self):
        wp = WindowProperties()
        if self.settings.get("fullscreen"):
            wp.set_fullscreen(True)
            wp.set_size(self.pipe.get_display_width(), self.pipe.get_display_height())
        else:
            wp.set_fullscreen(False)
            wp.set_size(1280, 720)
        if self.win:
            self.win.request_properties(wp)

    def _on_window_event(self, win):
        if win and win.is_closed():
            self.userExit()

    def on_exit(self):
        if self.screen_rec.active:
            try:
                self.screen_rec.stop()
            except Exception as e:
                log_error("recorder on exit: %r" % e)
        if self.game:
            try:
                self.game.save()
            except Exception as e:
                log_error("save on exit: %r" % e)

    def button(self, parent, text, pos, cmd, width=0.62, scale=1.0, enabled=True):
        w = width
        b = DirectButton(parent=parent, text=text, text_scale=0.056 * scale, text_fg=(1, 1, 1, 1) if enabled else (0.6, 0.6, 0.6, 1),
                         text_shadow=(0.15, 0.15, 0.15, 1), text_pos=(0, -0.018),
                         frameSize=(-w, w, -0.058, 0.058), frameColor=((0.42, 0.44, 0.46, 0.96), (0.30, 0.36, 0.30, 1),
                                                                         (0.42, 0.62, 0.40, 1), (0.28, 0.28, 0.30, 0.9)),
                         relief=DGG.RAISED, borderWidth=(0.012, 0.012), pos=(pos[0], 0, pos[1]), command=cmd, pressEffect=1)
        if not enabled:
            b["state"] = DGG.DISABLED
        return b

    def text(self, parent, t, pos, scale=0.05, fg=(1, 1, 1, 1), align=TextNode.A_center):
        return OnscreenText(parent=parent, text=t, pos=pos, scale=scale, fg=fg, shadow=(0, 0, 0, 1), align=align, mayChange=True)

    def clear_screen(self):
        if self.screen:
            self.screen.destroy(); self.screen = None

    def new_screen(self, dim=0.0):
        self.clear_screen()
        self.screen = DirectFrame(parent=self.aspect2d, frameColor=(0, 0, 0, dim), frameSize=(-4, 4, -2, 2))
        return self.screen

    # ---------------------------------------------------------------- menu music
    def _init_music(self):
        self.music = None; self._mfade = 1.0; self._mtarget = 1.0
        try:
            m = self.loader.load_music(Filename.from_os_specific(os.path.join(BASE, "assets", "menu_music.wav")))
            if m and m.length() > 0:
                m.set_loop(True); m.set_loop_count(0)     # 0 = loop forever (gapless, fully preloaded PCM)
                self.music = m
        except Exception as e:
            log_error("music: %r" % e)
        self._mfade = 0.0
        self.task_mgr.add(self._music_task, "music-fade")

    def music_volume(self):
        return MUSIC_VOLUME

    def music_in(self):
        self._mtarget = 1.0
        if self.music and self.music.status() != self.music.PLAYING:
            self.music.set_volume(0.0); self.music.play()

    def music_out(self):
        self._mtarget = 0.0

    def _music_task(self, task):
        m = self.music
        if m:
            dt = globalClock.get_dt()
            step = dt / 1.5
            self._mfade = min(self._mtarget, self._mfade + step) if self._mtarget > self._mfade else max(self._mtarget, self._mfade - step)
            m.set_volume(self._mfade * self.music_volume())
            if self._mfade <= 0.0 and self._mtarget <= 0.0 and m.status() == m.PLAYING:
                m.stop()
        return task.cont

    # ---------------------------------------------------------------- title
    def show_title(self):
        self.music_in()
        if self.scene is None:
            self.scene = TitleScene(self)
        self.camLens.set_min_fov(float(self.settings["fov"]))
        self.camLens.set_near_far(0.1, 400)
        s = self.new_screen(0.12)
        logo = OnscreenImage(parent=s, image=self.tex_logo, pos=(0, 0, 0.55), scale=(0.95, 1, 0.95 * 180 / 660))
        logo.set_transparency(TransparencyAttrib.M_alpha)
        sp = self.text(s, random.choice(SPLASHES), (0.78, 0.34), 0.055, (1, 1, 0.25, 1))
        sp.set_r(-14)
        self._splash = sp
        self.task_mgr.add(self._pulse, "splash-pulse")
        self.button(s, "Singleplayer", (0, 0.12), self.show_worlds)
        self.button(s, "Settings", (0, -0.03), lambda: self.open_settings(back=self.show_title))
        self.button(s, "Check for updates", (0, -0.18), self.start_update_check)
        self.button(s, "Quit Game", (0, -0.33), self.userExit)
        self.text(self.screen, "DREAM VINE " + APP_VERSION, (-1.0 * self.getAspectRatio() + 0.03, -0.96), 0.045, align=TextNode.A_left)
        self.text(self.screen, "\u00a92026 EX Inc./HYPERION DIGITAL \u00a92026", (1.0 * self.getAspectRatio() - 0.03, -0.96), 0.045, align=TextNode.A_right)

    def _pulse(self, task):
        if self.screen is None or self._splash is None or self._splash.is_empty():
            return task.done
        k = 1 + 0.06 * math.sin(task.time * 6)
        self._splash.set_scale(k)
        return task.cont

    # ---------------------------------------------------------------- worlds
    def list_worlds(self):
        out = []
        for d in os.listdir(SAVES):
            p = os.path.join(SAVES, d, "level.json")
            if os.path.exists(p):
                try:
                    m = json.load(open(p, encoding="utf-8")); out.append((d, m))
                except Exception:
                    pass
        out.sort(key=lambda t: -float(t[1].get("last_played", 0)))
        return out

    def show_worlds(self, selected=None):
        s = self.new_screen(0.55)
        self.text(s, "Select World", (0, 0.8), 0.075)
        worlds = self.list_worlds()
        self._sel_world = selected if selected in [w[0] for w in worlds] else (worlds[0][0] if worlds else None)
        if not worlds:
            self.text(s, "No worlds yet - create one!", (0, 0.4), 0.055, (0.85, 0.85, 0.85, 1))
        for i, (d, m) in enumerate(worlds[:7]):
            sel = d == self._sel_world
            lp = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(m.get("last_played", 0)))) if m.get("last_played") else ""
            label = "%s   [%s]   seed %s   %s" % (m.get("name", d), m.get("mode", "survival").title(), m.get("seed"), lp)
            b = DirectButton(parent=s, text=label, text_scale=0.045, text_fg=(1, 1, 1, 1), text_shadow=(0, 0, 0, 1), text_pos=(0, -0.015),
                             frameSize=(-1.0, 1.0, -0.055, 0.055),
                             frameColor=(0.25, 0.45, 0.25, 0.95) if sel else (0.18, 0.18, 0.2, 0.85),
                             relief=DGG.FLAT, pos=(0, 0, 0.62 - i * 0.125), command=self.show_worlds, extraArgs=[d])
        self.button(s, "Play Selected World", (-0.33, -0.55), self.play_selected, width=0.31, scale=0.85, enabled=bool(worlds))
        self.button(s, "Create New World", (0.33, -0.55), self.show_create, width=0.31, scale=0.85)
        self.button(s, "Delete", (-0.33, -0.70), self.confirm_delete, width=0.31, scale=0.85, enabled=bool(worlds))
        self.button(s, "Back", (0.33, -0.70), self.show_title, width=0.31, scale=0.85)

    def confirm_delete(self):
        d = self._sel_world
        if not d:
            return
        s = self.new_screen(0.7)
        self.text(s, "Delete world '%s'?" % d, (0, 0.2), 0.07)
        self.text(s, "This cannot be undone.", (0, 0.08), 0.05, (1, 0.6, 0.6, 1))
        def do():
            shutil.rmtree(os.path.join(SAVES, d), ignore_errors=True); self.show_worlds()
        self.button(s, "Delete", (-0.33, -0.15), do, width=0.31)
        self.button(s, "Cancel", (0.33, -0.15), self.show_worlds, width=0.31)

    def show_create(self):
        s = self.new_screen(0.55)
        self.text(s, "Create New World", (0, 0.75), 0.075)
        self.text(s, "World Name", (-0.6, 0.5), 0.05, align=TextNode.A_left)
        self._e_name = DirectEntry(parent=s, initialText="New World", scale=0.06, width=20, pos=(-0.6, 0, 0.39),
                                   frameColor=(0.05, 0.05, 0.05, 1), text_fg=(1, 1, 1, 1), focus=1)
        self.text(s, "Seed for the world generator (leave blank for random)", (-0.6, 0.22), 0.042, (0.8, 0.8, 0.8, 1), TextNode.A_left)
        self._e_seed = DirectEntry(parent=s, initialText="", scale=0.06, width=20, pos=(-0.6, 0, 0.11),
                                   frameColor=(0.05, 0.05, 0.05, 1), text_fg=(1, 1, 1, 1))
        self._mode = "survival"
        self._mode_btn = self.button(s, "Game Mode: Survival", (0, -0.1), self._toggle_mode)
        self._mode_desc = self.text(s, "Gather resources, craft tools, keep your health and hunger up.", (0, -0.22), 0.042, (0.8, 0.8, 0.8, 1))
        self.button(s, "Create New World", (-0.33, -0.55), self.create_world, width=0.31, scale=0.85)
        self.button(s, "Cancel", (0.33, -0.55), self.show_worlds, width=0.31, scale=0.85)

    def _toggle_mode(self):
        self._mode = "creative" if self._mode == "survival" else "survival"
        self._mode_btn["text"] = "Game Mode: " + self._mode.title()
        self._mode_desc.setText("Unlimited blocks, instant breaking, double-tap Space to fly." if self._mode == "creative"
                                else "Gather resources, craft tools, keep your health and hunger up.")

    def create_world(self):
        name = (self._e_name.get().strip() or "New World")[:40]
        seed = seed_from_text(self._e_seed.get())
        safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in name).strip() or "World"
        d, i = safe, 2
        while os.path.exists(os.path.join(SAVES, d)):
            d = "%s (%d)" % (safe, i); i += 1
        os.makedirs(os.path.join(SAVES, d), exist_ok=True)
        meta = {"name": name, "seed": seed, "mode": self._mode, "created": time.time(), "last_played": time.time(),
                "version": APP_VERSION, "time": 0.03}
        json.dump(meta, open(os.path.join(SAVES, d, "level.json"), "w", encoding="utf-8"), indent=1)
        self.start_game(d)

    def play_selected(self):
        if self._sel_world:
            self.start_game(self._sel_world)

    # ---------------------------------------------------------------- game
    def start_game(self, d):
        path = os.path.join(SAVES, d)
        meta = json.load(open(os.path.join(path, "level.json"), encoding="utf-8"))
        self.clear_screen()
        if self.scene:
            self.scene.destroy(); self.scene = None
        s = self.new_screen(1.0)
        s["frameColor"] = (0.10, 0.08, 0.06, 1)
        self.text(s, "Loading world...", (0, 0.12), 0.07)
        self._lt = self.text(s, "Generating terrain", (0, 0.0), 0.05, (0.8, 0.8, 0.8, 1))
        DirectFrame(parent=s, frameColor=(0.25, 0.25, 0.25, 1), frameSize=(-0.6, 0.6, -0.025, 0.025), pos=(0, 0, -0.12))
        self._lbar = DirectFrame(parent=s, frameColor=(0.35, 0.85, 0.35, 1), frameSize=(0, 1.2, -0.025, 0.025), pos=(-0.6, 0, -0.12))
        self._lbar.set_sx(0.001)
        self.music_out()
        self.game = Game(self, path, meta)

    def loading_progress(self, r):
        if self.screen and getattr(self, "_lbar", None) and not self._lbar.is_empty():
            self._lbar.set_sx(max(0.001, r))
            self._lt.setText("Generating terrain  %d%%" % int(r * 100))

    def loading_done(self):
        self.clear_screen()

    # ---------------------------------------------------------------- settings
    def open_settings(self, back):
        prev = self.screen
        if self.game and self.game.pause_ui:
            self.game.pause_ui.hide(); prev = None
        if prev and back != self.show_title:
            prev.hide()
        s = self.new_screen(0.65) if not self.game else DirectFrame(parent=self.aspect2d, frameColor=(0, 0, 0, 0.7), frameSize=(-4, 4, -2, 2))
        if self.game:
            self._settings_frame = s
        self.text(s, "Settings", (0, 0.75), 0.075)
        st = self.settings
        def slider(label, key, rng, z, fmt, step):
            t = self.text(s, "", (0, z + 0.06), 0.05)
            def upd():
                v = sl["value"]
                v = round(v / step) * step
                st[key] = int(v) if step >= 1 else round(v, 2)
                t.setText(label + ": " + fmt(st[key]))
            sl = DirectSlider(parent=s, range=rng, value=st[key], pageSize=step, scale=0.6, pos=(0, 0, z - 0.02),
                              frameColor=(0.3, 0.3, 0.32, 1), thumb_frameColor=(0.75, 0.75, 0.78, 1), command=upd)
            upd()
            return sl
        slider("Render Distance", "render_distance", (2, 12), 0.48, lambda v: "%d chunks" % v, 1)
        slider("Mouse Sensitivity", "sensitivity", (0.2, 3.0), 0.24, lambda v: "%d%%" % round(v * 100), 0.05)
        slider("Field of View", "fov", (50, 110), 0.0, lambda v: "%d" % v, 1)
        fb = self.button(s, "", (0, -0.24), None)
        def setfs():
            fb["text"] = "Fullscreen: " + ("ON" if st["fullscreen"] else "OFF")
        def togfs():
            st["fullscreen"] = not st["fullscreen"]; setfs(); self.apply_fullscreen()
        fb["command"] = togfs; setfs()
        self.text(s, "Controls: WASD move, Mouse look, Space jump (double-tap to fly in Creative), Shift sneak,\n"
                     "Ctrl / double-tap W sprint, Left click break / attack, Right click place / use / eat,\n"
                     "1-9 / wheel hotbar, E inventory, Esc menu, F2 screenshot, F3 debug, F1 hide HUD",
                  (0, -0.42), 0.038, (0.85, 0.85, 0.85, 1))
        def done():
            self.save_settings()
            self.camLens.set_min_fov(float(st["fov"]))
            if self.game:
                s.destroy(); self._settings_frame = None
                back()
            else:
                back()
        self.button(s, "Done", (0, -0.72), done)

    # ---------------------------------------------------------------- updates
    def start_update_check(self):
        self._dialog("Checking for updates...", [])
        def work():
            try:
                self._upd_result = check_update()
            except Exception as e:
                self._upd_result = ("error", "Could not check for updates.\n(%s)" % (str(e)[:90]))
        threading.Thread(target=work, daemon=True).start()
        self.task_mgr.add(self._poll_update, "poll-update")

    def _poll_update(self, task):
        r = self._upd_result
        if r is None:
            return task.cont
        self._upd_result = None
        kind, data = r
        if kind == "newer":
            self._dialog("DREAM VINE %s is available!\n%s\n\nDownload and install it now?" % (data["version"], data["notes"][:160]),
                         [("Download & Install", lambda: (self.download_portable(data["link"]) if data.get("portable") else self.download_install(data["link"]))),
                          ("Not now", self._close_dialog)])
        else:
            self._dialog(data, [("OK", self._close_dialog)])
        return task.done

    def _dialog(self, msg, buttons):
        self._close_dialog()
        o = self.overlay = DirectFrame(parent=self.aspect2d, frameColor=(0, 0, 0, 0.6), frameSize=(-4, 4, -2, 2))
        DirectFrame(parent=o, frameColor=(0.2, 0.22, 0.24, 0.97), frameSize=(-0.9, 0.9, -0.38, 0.38), relief=DGG.RAISED, borderWidth=(0.01, 0.01))
        self.text(o, msg, (0, 0.2), 0.05)
        n = len(buttons)
        for i, (t, c) in enumerate(buttons):
            self.button(o, t, ((i - (n - 1) / 2) * 0.62, -0.25), c, width=0.29, scale=0.8)

    def _close_dialog(self):
        if self.overlay:
            self.overlay.destroy(); self.overlay = None

    def download_install(self, link):
        if not link.lower().endswith(".exe"):
            self._open_browser(link); return
        self._dialog("Downloading update...", [])
        def work():
            try:
                dst = os.path.join(tempfile.gettempdir(), os.path.basename(link.split("?")[0]) or "DREAM.VINE.Setup.exe")
                req = urllib.request.Request(link, headers={"User-Agent": "DREAM-VINE/" + APP_VERSION})
                with urllib.request.urlopen(req, timeout=60) as r, open(dst, "wb") as f:
                    shutil.copyfileobj(r, f)
                self._upd_result = ("install", dst)
            except Exception as e:
                self._upd_result = ("dlerror", (link, str(e)[:90]))
        threading.Thread(target=work, daemon=True).start()
        self.task_mgr.add(self._poll_download, "poll-dl")

    def _poll_download(self, task):
        r = self._upd_result
        if r is None:
            return task.cont
        self._upd_result = None
        if r[0] == "install":
            try:
                os.startfile(r[1])
                self.userExit()
            except Exception as e:
                self._dialog("Could not start the installer:\n%s" % e, [("Open download page", lambda: self._open_browser(RELEASES_URL)), ("Close", self._close_dialog)])
        else:
            self._dialog("Download failed.\n%s" % r[1][1], [("Open download page", lambda: self._open_browser(RELEASES_URL)), ("Close", self._close_dialog)])
        return task.done

    # ---- portable self-update: download <exe>.new next to the exe, swap it in with a helper script after we exit
    def download_portable(self, link):
        exe = os.path.abspath(sys.executable)
        new = exe + ".new"
        self._dialog("Downloading portable update...", [])
        def work():
            try:
                req = urllib.request.Request(link, headers={"User-Agent": "DREAM-VINE/" + APP_VERSION})
                with urllib.request.urlopen(req, timeout=60) as r, open(new, "wb") as f:
                    shutil.copyfileobj(r, f)
                with open(new, "rb") as f:
                    ok = f.read(2) == b"MZ"
                if not ok or os.path.getsize(new) < 5_000_000:
                    os.remove(new)
                    raise IOError("downloaded file is not a valid DREAM VINE executable")
                self._upd_result = ("swap", new)
            except Exception as e:
                try:
                    if os.path.exists(new): os.remove(new)
                except OSError:
                    pass
                self._upd_result = ("dlerror", (link, str(e)[:90]))
        threading.Thread(target=work, daemon=True).start()
        self.task_mgr.add(self._poll_portable, "poll-dl")

    def _poll_portable(self, task):
        r = self._upd_result
        if r is None:
            return task.cont
        self._upd_result = None
        if r[0] == "swap":
            try:
                self._launch_swap_helper(os.path.abspath(sys.executable), r[1])
                self.userExit()
            except Exception as e:
                log_error("portable update: %r" % e)
                self._dialog("Could not apply the update:\n%s" % str(e)[:90], [("Open download page", lambda: self._open_browser(RELEASES_URL)), ("Close", self._close_dialog)])
        else:
            self._dialog("Download failed.\n%s" % r[1][1], [("Open download page", lambda: self._open_browser(RELEASES_URL)), ("Close", self._close_dialog)])
        return task.done

    def _launch_swap_helper(self, exe, new):
        """Write a small .bat that waits for this game to close, replaces the exe (same name/path), relaunches it and deletes itself."""
        import subprocess
        pids = [os.getpid()]
        try:
            pids.append(os.getppid())        # onefile bootloader process that holds the exe open
        except Exception:
            pass
        bat = os.path.join(tempfile.gettempdir(), "dream_vine_update_%d.bat" % os.getpid())
        lines = ["@echo off", "setlocal", "set N=0"]
        for p in pids:
            lines += [":w%d" % p,
                      'tasklist /FI "PID eq %d" 2>NUL | find " %d " >NUL' % (p, p),
                      "if not errorlevel 1 (ping -n 2 127.0.0.1 >NUL & set /a N+=1 & if !N! LSS 120 goto w%d)" % p]
        lines = ["@echo off", "setlocal EnableDelayedExpansion", "set N=0"] + lines[3:]
        lines += ["set T=0",
                  ":swap",
                  'move /Y "%s" "%s" >NUL 2>&1' % (new, exe),
                  "if errorlevel 1 (ping -n 2 127.0.0.1 >NUL & set /a T+=1 & if !T! LSS 60 goto swap)",
                  'start "" "%s"' % exe,
                  '(goto) 2>NUL & del "%~f0"']
        with open(bat, "w", encoding="mbcs" if os.name == "nt" else "utf-8") as f:
            f.write("\r\n".join(lines) + "\r\n")
        flags = 0x00000008 | 0x00000200          # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(["cmd.exe", "/c", bat], creationflags=flags, close_fds=True, cwd=os.path.dirname(exe),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _open_browser(self, url):
        import webbrowser
        webbrowser.open(url); self._close_dialog()


def main():
    try:
        App().run()
    except SystemExit:
        raise
    except Exception:
        log_error(traceback.format_exc())
        raise


if __name__ == "__main__":
    main()

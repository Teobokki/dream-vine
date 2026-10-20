"""DREAM VINE text chat (log + input line) and the VINE BUILD overlay. (c)2026 EX Inc./HYPERION DIGITAL (c)2026"""
import time
from direct.gui.DirectGui import DirectFrame, DirectButton, DirectEntry, DGG
from direct.gui.OnscreenText import OnscreenText
from panda3d.core import TextNode

VISIBLE = 10          # lines shown
HISTORY = 100         # lines kept
FADE_AFTER, FADE_TIME = 10.0, 1.5
WRAP = 52


class Chat:
    def __init__(self, game, history=None):
        self.g, self.app = game, game.app
        self.lines = []                       # [text, colour, time]
        for t in (history or [])[-HISTORY:]:
            self.lines.append([t, (0.8, 0.8, 0.8, 1), 0.0])
        self.open = False
        self.scroll_off = 0
        self.closed_t = 0.0
        self.root = self.app.a2dBottomLeft.attach_new_node("chat")
        self.bg = []
        self.nodes = []
        for i in range(VISIBLE):
            z = 0.36 + i * 0.052
            bg = DirectFrame(parent=self.root, frameColor=(0, 0, 0, 0.4), frameSize=(0.02, 1.12, z - 0.016, z + 0.036), relief=DGG.FLAT)
            t = OnscreenText(parent=self.root, text="", pos=(0.04, z), scale=0.038, fg=(1, 1, 1, 1), shadow=(0, 0, 0, 1),
                             align=TextNode.A_left, mayChange=True)
            self.bg.append(bg); self.nodes.append(t)
        self.entry = None
        self.hint = None
        self.refresh()

    # ------------------------------------------------------------------ log
    def add(self, text, colour=(1, 1, 1, 1)):
        while text:
            cut = text[:WRAP]
            if len(text) > WRAP and " " in cut:
                cut = cut[:cut.rfind(" ")]
            self.lines.append([cut, colour, time.time()])
            text = text[len(cut):].lstrip()
        self.lines = self.lines[-HISTORY:]
        self.scroll_off = 0
        self.refresh()

    def system(self, text):
        self.add(text, (1, 0.95, 0.45, 1))

    def clear(self):
        self.lines = []; self.scroll_off = 0; self.refresh()

    def history(self):
        return [l[0] for l in self.lines]

    def scroll(self, n):
        if self.open:
            self.scroll_off = max(0, min(max(0, len(self.lines) - VISIBLE), self.scroll_off + n))
            self.refresh()

    def refresh(self):
        now = time.time()
        end = len(self.lines) - self.scroll_off
        shown = self.lines[max(0, end - VISIBLE):end]
        for i in range(VISIBLE):
            t, bg = self.nodes[i], self.bg[i]
            j = len(shown) - 1 - i
            if j < 0:
                t.setText(""); bg.hide(); continue
            text, col, ts = shown[j]
            a = 1.0 if self.open else max(0.0, min(1.0, (FADE_AFTER + FADE_TIME - (now - ts)) / FADE_TIME))
            if a <= 0:
                t.setText(""); bg.hide(); continue
            t.setText(text); t["fg"] = (col[0], col[1], col[2], a)
            bg.show(); bg["frameColor"] = (0, 0, 0, 0.4 * a)

    def update(self):
        self.refresh()

    # ------------------------------------------------------------------ input
    def open_input(self, prefill=""):
        if self.open or time.time() - self.closed_t < 0.25:
            return
        self.open = True
        self.entry = DirectEntry(parent=self.root, scale=0.042, width=25, pos=(0.04, 0, 0.27), initialText=prefill, focus=1,
                                 numLines=1, frameColor=(0, 0, 0, 0.6), text_fg=(1, 1, 1, 1), command=self._submit,
                                 relief=DGG.FLAT, cursorKeys=1, suppressKeys=0)
        if prefill:
            self.entry.setCursorPosition(len(prefill))
        self.hint = OnscreenText(parent=self.root, text="Enter = send   Esc = close   Wheel = scroll   /help = commands",
                                 pos=(0.04, 0.22), scale=0.03, fg=(0.85, 0.85, 0.85, 1), shadow=(0, 0, 0, 1), align=TextNode.A_left)
        self.refresh()

    def _submit(self, text):
        self.close_input()
        text = text.strip()
        if text:
            self.g.on_chat(text)

    def close_input(self):
        if self.entry:
            self.entry.destroy(); self.entry = None
        if self.hint:
            self.hint.destroy(); self.hint = None
        self.open = False
        self.scroll_off = 0
        self.closed_t = time.time()
        self.refresh()
        self.g.chat_closed()

    def destroy(self):
        if self.entry:
            self.entry.destroy()
        self.root.remove_node()


class VineBuildUI:
    """Overlay: VINE BUILD by Vine AI - describe a building, see the interpretation, Build / Undo."""
    def __init__(self, game, examples, interpret):
        self.g, a = game, game.app
        self.interpret = interpret
        self.last = None
        self.ui = DirectFrame(parent=a.aspect2d, frameColor=(0, 0, 0, 0.55), frameSize=(-3, 3, -2, 2))
        DirectFrame(parent=self.ui, frameColor=(0.07, 0.12, 0.08, 0.96), frameSize=(-1.05, 1.05, -0.62, 0.62), relief=DGG.RAISED,
                    borderWidth=(0.012, 0.012))
        OnscreenText(parent=self.ui, text="VINE BUILD", pos=(0, 0.47), scale=0.11, fg=(0.45, 1, 0.4, 1), shadow=(0, 0, 0, 1))
        OnscreenText(parent=self.ui, text="powered by  Vine AI  - describe any building and I'll build it in front of you",
                     pos=(0, 0.39), scale=0.04, fg=(0.75, 0.95, 0.7, 1), shadow=(0, 0, 0, 1))
        self.entry = DirectEntry(parent=self.ui, scale=0.05, width=36, pos=(-0.9, 0, 0.24), initialText="", focus=1, numLines=1,
                                 frameColor=(0.95, 0.97, 0.93, 1), text_fg=(0.05, 0.1, 0.05, 1), command=lambda t: self.build(),
                                 relief=DGG.SUNKEN, borderWidth=(0.01, 0.01), cursorKeys=1)
        self.ph = OnscreenText(parent=self.ui, text="Describe a building...", pos=(-0.88, 0.24), scale=0.05, fg=(0.5, 0.55, 0.5, 1),
                               align=TextNode.A_left, mayChange=True)
        OnscreenText(parent=self.ui, text="Try:", pos=(-0.9, 0.1), scale=0.042, fg=(0.85, 0.85, 0.85, 1), align=TextNode.A_left)
        for i, ex in enumerate(examples):
            r, cidx = divmod(i, 3)
            a.button(self.ui, ex, (-0.58 + cidx * 0.6, 0.1 - r * 0.11), lambda ex=ex: self.set_text(ex), width=0.27, scale=0.75)
        self.info = OnscreenText(parent=self.ui, text="", pos=(0, -0.2), scale=0.04, fg=(1, 0.95, 0.6, 1), shadow=(0, 0, 0, 1),
                                 wordwrap=48, mayChange=True)
        a.button(self.ui, "Build", (-0.6, -0.47), self.build, width=0.25)
        a.button(self.ui, "Undo last build", (0, -0.47), self.g.undo_build, width=0.29, enabled=bool(self.g.build_undo))
        a.button(self.ui, "Close", (0.6, -0.47), self.g.close_vinebuild, width=0.25)
        a.task_mgr.add(self._poll, "vb-poll")

    def set_text(self, t):
        self.entry.enterText(t); self.entry.setCursorPosition(len(t)); self.entry["focus"] = 1

    def _poll(self, task):
        if self.ui.is_empty():
            return task.done
        t = self.entry.get()
        self.ph.setText("" if t else "Describe a building...")
        if t != self.last and task.time - getattr(self, "_lt", -1) > 0.25:
            self.last = t; self._lt = task.time
            self.info.setText(self.interpret(t)[1] if t.strip() else "Vine AI works offline: type ANYTHING (typos ok) - building types, styles (cyberpunk, underwater, haunted...), "
                              "sizes (tiny, huge, '20 blocks tall', '5 tiers'), materials & colours and extras "
                              "(garden, moat, pond, cherry trees, lanterns, chimney...).")
        return task.cont

    def build(self):
        t = self.entry.get().strip()
        if not t:
            self.info.setText("Type what you want Vine AI to build first."); return
        self.g.close_vinebuild()
        self.g.vine_build(t)

    def destroy(self):
        self.g.app.task_mgr.remove("vb-poll")
        self.ui.destroy()

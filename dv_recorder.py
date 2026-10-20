"""EX CREATOR SCREEN RECORDER 2026 - records DREAM VINE's own rendered frames to an H.264 MP4. (c)2026 EX Inc./HYPERION DIGITAL"""
import os, sys, time, threading, subprocess, shutil, collections
from panda3d.core import Texture, GraphicsOutput

BRAND = "EX CREATOR SCREEN RECORDER 2026"
FPS = 30
MAX_QUEUE = 24          # frames buffered for the encoder; beyond this the last frame is repeated (keeps timing, no stutter)


def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        p = imageio_ffmpeg.get_ffmpeg_exe()
        if p and os.path.exists(p):
            return p
    except Exception:
        pass
    return shutil.which("ffmpeg")


class Recorder:
    def __init__(self, app):
        self.app = app
        self.active = False
        self.proc = None; self.thread = None; self.path = None; self.error = None
        self.tex = None; self.start_t = 0.0; self.written = 0; self.size = None; self.fmt = None
        self.q = collections.deque(); self.cv = threading.Condition(); self.closing = False

    def elapsed(self):
        return time.time() - self.start_t if self.active else 0.0

    def start(self, out_dir):
        if self.active:
            return True
        exe = ffmpeg_exe()
        if not exe:
            self.error = "ffmpeg not found"; return False
        win = self.app.win
        self.tex = Texture("ex-recorder")
        try:
            win.add_render_texture(self.tex, GraphicsOutput.RTM_copy_ram, GraphicsOutput.RTP_color)
        except Exception as e:
            self.error = "could not capture the game window (%s)" % e; self.tex = None; return False
        self.exe = exe
        self.path = os.path.join(out_dir, "DREAM VINE Recording %s.mp4" % time.strftime("%Y-%m-%d %H-%M-%S"))
        self.proc = None; self.size = None; self.fmt = None; self.written = 0; self.error = None
        self.q.clear(); self.closing = False
        self.start_t = time.time()
        self.active = True
        self.app.task_mgr.add(self._grab, "ex-recorder-grab", sort=60)
        return True

    def _open_ffmpeg(self, w, h, pix):
        cmd = [self.exe, "-hide_banner", "-loglevel", "error", "-y",
               "-f", "rawvideo", "-pix_fmt", pix, "-s", "%dx%d" % (w, h), "-r", str(FPS), "-i", "-",
               "-vf", "vflip,scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
               "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-metadata", "comment=" + BRAND,
               "-metadata", "title=DREAM VINE Recording", self.path]
        flags = 0x08000000 if os.name == "nt" else 0          # CREATE_NO_WINDOW
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                     creationflags=flags)
        self.thread = threading.Thread(target=self._writer, daemon=True)
        self.thread.start()

    def _grab(self, task):
        if not self.active:
            return task.done
        t = self.tex
        if not t.has_ram_image():
            return task.cont
        w, h = t.get_x_size(), t.get_y_size()
        if self.size is None:
            comps = t.get_num_components()
            if t.get_component_width() != 1 or comps not in (3, 4):
                self.error = "unsupported frame format"; self.stop(); return task.done
            self.size, self.fmt = (w, h), ("bgra" if comps == 4 else "bgr24")
            self._open_ffmpeg(w, h, self.fmt)
        if (w, h) != self.size:                      # window resized: keep repeating the last good frame
            data = None
        else:
            data = bytes(memoryview(t.get_ram_image()))
        due = int((time.time() - self.start_t) * FPS) + 1 - self.written
        if due <= 0:
            return task.cont
        with self.cv:
            if data is not None and len(self.q) < MAX_QUEUE:
                self.q.append([data, due])
            elif self.q:
                self.q[-1][1] += due
            elif data is not None:
                self.q.append([data, due])
            else:
                self.q.append([None, due])
            self.written += due
            self.cv.notify()
        return task.cont

    def _writer(self):
        last = None
        try:
            while True:
                with self.cv:
                    while not self.q and not self.closing:
                        self.cv.wait(0.5)
                    if not self.q and self.closing:
                        break
                    data, n = self.q.popleft()
                if data is None:
                    data = last
                if data is None:
                    continue
                last = data
                for _ in range(n):
                    self.proc.stdin.write(data)
        except Exception as e:
            self.error = "encoder: %s" % e
        finally:
            try:
                self.proc.stdin.close()
            except Exception:
                pass

    def stop_async(self, done):
        """Stops without blocking the game; done(path_or_None) is called on the main thread when the MP4 is final."""
        if not self.active:
            return False
        self.active = False
        self.app.task_mgr.remove("ex-recorder-grab")
        res = {}
        def work():
            res["path"] = self._finalise()
        self._detach()
        th = threading.Thread(target=work, daemon=True); th.start()
        def poll(task):
            if th.is_alive():
                return task.cont
            done(res.get("path"))
            return task.done
        self.app.task_mgr.add(poll, "ex-recorder-finalise")
        return True

    def _detach(self):
        try:
            self.app.win.clear_render_textures()
        except Exception:
            pass
        self.tex = None

    def stop(self, timeout=30):
        """Stops recording and finalises the MP4. Returns the saved path or None."""
        if not self.active:
            return None
        self.active = False
        self.app.task_mgr.remove("ex-recorder-grab")
        self._detach()
        return self._finalise(timeout)

    def _finalise(self, timeout=30):
        self.active = False
        if self.proc is None:                # nothing captured yet
            return None
        with self.cv:
            self.closing = True; self.cv.notify()
        self.thread.join(timeout)
        try:
            self.proc.wait(timeout)
        except Exception:
            self.proc.kill(); self.error = "encoder timed out"
        ok = self.proc.returncode == 0 and os.path.exists(self.path) and os.path.getsize(self.path) > 0
        if not ok and not self.error:
            self.error = (self.proc.stderr.read() or b"").decode("utf-8", "ignore")[-200:] or "encoder failed"
        self.proc = None
        return self.path if ok else None

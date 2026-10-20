# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_data_files, collect_all
fd, fb, fh = collect_all('imageio_ffmpeg')
import os
DROP = ('avcodec', 'avformat', 'avutil', 'swresample', 'swscale', 'libp3ffmpeg', 'fmod', 'assimp', 'ptloader',
        'bullet', 'pandaode', 'pandaai', 'vrpn', 'p3vision', 'pandadx9', 'd3dx9', 'cgd3d9', 'pandaphysics', 'pandafx')
b = [x for x in collect_dynamic_libs('panda3d') if not any(k in os.path.basename(x[0]).lower() for k in DROP)]
d = collect_data_files('panda3d', includes=['etc/*', 'models/**/*'])
a = Analysis(['dream_vine.py'], datas=[('assets', 'assets')] + d + fd, binaries=b + fb,
             hiddenimports=['panda3d.core', 'panda3d.direct', 'direct.showbase.ShowBase', 'direct.gui.DirectGui',
                            'dv_game', 'dv_world', 'dv_blocks', 'dv_render', 'dv_entities', 'dv_noise', 'dv_art', 'dv_recorder', 'dv_vinebuild', 'dv_chat', 'imageio_ffmpeg'] + fh,
             excludes=['matplotlib', 'scipy', 'pandas', 'IPython', 'pytest', 'tkinter', 'PIL', 'cv2', 'wx', 'PyQt5'],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='DREAM VINE', console=False, upx=False, runtime_tmpdir=None,
          version='version.txt', icon=['assets/icon.ico'])

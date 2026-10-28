"""参数速扫: 抓一帧真实桌面, 用 win/glass_overlay.py 里的着色器在离屏 FBO 上
渲染指定参数组合, 直接出 PNG —— 不用全屏闪一下就能选参数。

用法 (在仓库根目录):
    .venv\\Scripts\\python.exe WindowsDuo\\win\\lookdev.py g=0.6
    .venv\\Scripts\\python.exe WindowsDuo\\win\\lookdev.py g=1.0 spread=0.30 dark=0.0003 eye=1.9 maxtilt=66
    .venv\\Scripts\\python.exe WindowsDuo\\win\\lookdev.py g=0.5 tag=my_look

可调键: g(浓度 0~1) spread dark eye maxtilt tag
不给的键用 win/config.json 里的当前值。
输出: win/look_<tag>.png
"""
import sys
from pathlib import Path

import mss
from PIL import Image
from PyQt6.QtGui import QSurfaceFormat, QOffscreenSurface, QOpenGLContext
from PyQt6.QtOpenGL import QOpenGLShader, QOpenGLShaderProgram
from PyQt6.QtWidgets import QApplication
from OpenGL import GL

import glass_overlay as go

W, H = 960, 600
OUT_DIR = Path(__file__).with_name("looks")


def parse_args():
    p = {"g": 0.6, "tag": None}
    for a in sys.argv[1:]:
        if "=" not in a:
            continue
        k, v = a.split("=", 1)
        p[k] = v if k == "tag" else float(v)
    cfg = go.CFG
    p.setdefault("spread", float(cfg["blur_spread"]))
    p.setdefault("dark", float(cfg["darkening"]))
    p.setdefault("eye", float(cfg["eye_dist_h"]))
    p.setdefault("maxtilt", float(cfg["max_tilt_deg"]))
    return p


def main():
    p = parse_args()
    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[1])
        img = Image.frombytes("RGB", shot.size, shot.rgb)
    if img.width > 1920:
        img = img.resize((1920, int(1920 * img.height / img.width)), Image.LANCZOS)

    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CompatibilityProfile)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication(sys.argv)   # 必须保留引用, 否则会被回收导致离屏上下文崩溃
    surf = QOffscreenSurface()
    surf.create()
    ctx = QOpenGLContext()
    ctx.setFormat(fmt)
    assert ctx.create() and ctx.makeCurrent(surf)

    prog = QOpenGLShaderProgram()
    assert prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, go.VS), prog.log()
    assert prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, go.FS_DUO), prog.log()
    assert prog.link(), prog.log()
    prog.bind()

    tex = GL.glGenTextures(1)
    GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
    GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, img.width, img.height, 0,
                    GL.GL_RGB, GL.GL_UNSIGNED_BYTE, img.tobytes())
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR_MIPMAP_LINEAR)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
    GL.glGenerateMipmap(GL.GL_TEXTURE_2D)

    GL.glBindVertexArray(GL.glGenVertexArrays(1))

    fbo = GL.glGenFramebuffers(1)
    GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, fbo)
    out_tex = GL.glGenTextures(1)
    GL.glBindTexture(GL.GL_TEXTURE_2D, out_tex)
    GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, W, H, 0, GL.GL_RGBA,
                    GL.GL_UNSIGNED_BYTE, None)
    GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0,
                              GL.GL_TEXTURE_2D, out_tex, 0)
    assert GL.glCheckFramebufferStatus(GL.GL_FRAMEBUFFER) == GL.GL_FRAMEBUFFER_COMPLETE

    GL.glViewport(0, 0, W, H)
    GL.glActiveTexture(GL.GL_TEXTURE0)
    GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
    GL.glUniform1i(prog.uniformLocation("uTex"), 0)
    GL.glUniform2f(prog.uniformLocation("uRes"), float(img.width), float(img.height))
    GL.glUniform1f(prog.uniformLocation("uTilt"),
                   p["g"] * p["maxtilt"] * 3.14159265358979 / 180.0)
    GL.glUniform1f(prog.uniformLocation("uEyeZ"), p["eye"] * img.height)
    GL.glUniform1f(prog.uniformLocation("uSpread"), p["spread"])
    GL.glUniform1f(prog.uniformLocation("uDark"), p["dark"])
    GL.glUniform1i(prog.uniformLocation("uMaxTaps"), int(go.CFG.get("max_taps", 32)))
    GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
    GL.glFinish()

    data = GL.glReadPixels(0, 0, W, H, GL.GL_RGB, GL.GL_UNSIGNED_BYTE)
    out = Image.frombytes("RGB", (W, H), data).transpose(Image.FLIP_TOP_BOTTOM)
    tag = p.get("tag") or (f"g{p['g']:.2f}_s{p['spread']:.2f}_d{p['dark']:.5f}"
                           f"_e{p['eye']:.1f}_t{p['maxtilt']:.0f}")
    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / f"look_{tag}.png"
    out.save(path)
    print(f"{path}  (g={p['g']:.2f} tilt={p['g']*p['maxtilt']:.1f}deg "
          f"spread={p['spread']:.2f} dark={p['dark']:.5f} eye={p['eye']:.1f})")


if __name__ == "__main__":
    main()
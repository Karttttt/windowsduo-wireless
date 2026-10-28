"""生成效果对比图：用合成测试图（不含任何个人桌面内容）在 5 个浓度下渲染，拼成一张图。

用法（仓库根目录）：
    .venv\\Scripts\\python.exe WindowsDuo\\win\\looksheet.py
输出：
    docs/effect-stages.png
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from PyQt6.QtGui import QSurfaceFormat, QOffscreenSurface, QOpenGLContext
from PyQt6.QtOpenGL import QOpenGLShader, QOpenGLShaderProgram
from PyQt6.QtWidgets import QApplication
from OpenGL import GL

import glass_overlay as go

W, H = 960, 600
TEX_W, TEX_H = 1920, 1200
STAGES = [0.0, 0.25, 0.5, 0.75, 1.0]
OUT = Path(__file__).resolve().parent.parent / "docs" / "effect-stages.png"


def make_test_card():
    """合成测试图：渐变底 + 网格 + 色块（和 offscreen_test.py 同款，便于对照）"""
    img = Image.new("RGB", (TEX_W, TEX_H))
    dr = ImageDraw.Draw(img)
    for x in range(0, TEX_W, 4):
        dr.line([(x, 0), (x, TEX_H)],
                fill=(int(255 * x / TEX_W), 46, int(255 - 255 * x / TEX_W)))
    for gx in range(0, TEX_W, 120):
        dr.line([(gx, 0), (gx, TEX_H)], fill=(235, 235, 235), width=3)
    for gy in range(0, TEX_H, 120):
        dr.line([(0, gy), (TEX_W, gy)], fill=(235, 235, 235), width=3)
    dr.rectangle([100, 100, 340, 280], fill=(0, 200, 90))
    dr.rectangle([1560, 880, 1820, 1100], fill=(255, 210, 0))
    dr.rectangle([760, 470, 1160, 730], fill=(30, 90, 210))
    return img


def render(app, prog, tex, g):
    GL.glClearColor(0, 0, 0, 1)
    GL.glClear(GL.GL_COLOR_BUFFER_BIT)
    GL.glViewport(0, 0, W, H)
    GL.glActiveTexture(GL.GL_TEXTURE0)
    GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
    GL.glUniform1i(prog.uniformLocation("uTex"), 0)
    GL.glUniform2f(prog.uniformLocation("uRes"), float(TEX_W), float(TEX_H))
    GL.glUniform1f(prog.uniformLocation("uTilt"),
                   g * float(go.CFG["max_tilt_deg"]) * 3.14159265358979 / 180.0)
    GL.glUniform1f(prog.uniformLocation("uEyeZ"),
                   float(go.CFG["eye_dist_h"]) * TEX_H)
    GL.glUniform1f(prog.uniformLocation("uSpread"), float(go.CFG["blur_spread"]))
    GL.glUniform1f(prog.uniformLocation("uDark"), float(go.CFG["darkening"]))
    GL.glUniform1i(prog.uniformLocation("uMaxTaps"), int(go.CFG.get("max_taps", 32)))
    GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
    GL.glFinish()
    data = GL.glReadPixels(0, 0, W, H, GL.GL_RGB, GL.GL_UNSIGNED_BYTE)
    return Image.frombytes("RGB", (W, H), data).transpose(Image.FLIP_TOP_BOTTOM)


def main():
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CompatibilityProfile)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication(sys.argv)          # 必须保留引用
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

    card = make_test_card()
    tex = GL.glGenTextures(1)
    GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
    GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, TEX_W, TEX_H, 0,
                    GL.GL_RGB, GL.GL_UNSIGNED_BYTE, card.tobytes())
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR_MIPMAP_LINEAR)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
    GL.glGenerateMipmap(GL.GL_TEXTURE_2D)
    GL.glBindVertexArray(GL.glGenVertexArrays(1))

    # 每档先渲到一个 FBO，再读回
    fbo = GL.glGenFramebuffers(1)
    GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, fbo)
    out_tex = GL.glGenTextures(1)
    GL.glBindTexture(GL.GL_TEXTURE_2D, out_tex)
    GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, W, H, 0, GL.GL_RGBA,
                    GL.GL_UNSIGNED_BYTE, None)
    GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0,
                              GL.GL_TEXTURE_2D, out_tex, 0)
    assert GL.glCheckFramebufferStatus(GL.GL_FRAMEBUFFER) == GL.GL_FRAMEBUFFER_COMPLETE

    frames = [render(app, prog, tex, g) for g in STAGES]

    # ---- 拼图 ----
    tw, th, gap = 520, 325, 0
    cols = len(frames)
    head = 54
    foot = 64
    sheet = Image.new("RGB", (tw * cols, head + th + foot), (14, 14, 16))
    dr = ImageDraw.Draw(sheet)
    try:
        f_big = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 20)
        f_small = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 15)
    except OSError:
        f_big = f_small = ImageFont.load_default()

    maxtilt = float(go.CFG["max_tilt_deg"])
    dr.text((16, 14), "WindowsDuo - glass concentration across the fold angle",
            fill=(238, 238, 240), font=f_big)

    for i, (g, im) in enumerate(zip(STAGES, frames)):
        x = i * tw
        sheet.paste(im.resize((tw, th), Image.LANCZOS), (x, head))
        label = f"{int(round(g*100))}%   tilt {g*maxtilt:.0f} deg"
        dr.text((x + 14, head + th + 9), label, fill=(232, 232, 236), font=f_small)
        if i:
            dr.line([(x, head), (x, head + th)], fill=(64, 64, 70))

    note = (f"offscreen render with the repo shader  |  "
            f"blur_spread {go.CFG['blur_spread']}  darkening {go.CFG['darkening']}  "
            f"max_tilt {go.CFG['max_tilt_deg']} deg  eye {go.CFG['eye_dist_h']}x screen height")
    dr.text((16, head + th + 36), note, fill=(126, 126, 134), font=f_small)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(OUT)
    print(f"{OUT}  ({sheet.width}x{sheet.height})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
"""
iPhone Duo「悬浮玻璃」· Windows 端 v3 (复刻着色器版)
================================================================
融合四个开源复刻的精华 (均为 MIT / 可移植):
  - elijah-semyonov/DuoLikeAnimation : 逆投影模型 + Vogel 盘模糊 (主体公式)
  - chuspeeism/iphone-duo            : mip LOD 分级采样 + 边缘覆盖率平滑
  - DhananjayBhosale/MacDuo          : 笔记本场景 (铰链 = 屏幕底边, 盖角度驱动)
  - askmaddyy/FrostFold              : 磨砂玻璃观感参数

模型: 界面固定在世界空间的平面上不动; 屏幕是一块玻璃, 绕"铰链"(屏幕底边)
向观察者方向转开。每个像素: 眼睛 → 玻璃像素 → 延长交到界面平面 = 采样点。
间隙越大 → 模糊半径越大、越暗; 视线完全出界 → 纯黑。这是空间效果:
靠近铰链处始终清晰, 远离铰链处(屏幕上部)先模糊、先消失。

线程:
  - AngleReader   : 串口 100Hz 读 {"a":..,"b":..}   (--manual 可脱离串口)
  - CaptureWorker : mss 截屏原始帧
  - GL 主线程     : 上传纹理(带 mipmap) → 单 pass Duo 折叠着色器
用法:
  run_overlay.bat   串口驱动 | run_manual.bat   键盘手动 (↑↓←→)
  --selftest 无窗口自检 | --smoke 4s 全屏演示自退
"""
import json
import sys
import threading
import time
from pathlib import Path

import mss
import serial
from OpenGL import GL
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QSurfaceFormat
from PyQt6.QtOpenGL import QOpenGLShader, QOpenGLShaderProgram, QOpenGLWindow
from PyQt6.QtWidgets import QApplication

CFG_PATH = Path(__file__).with_name("config.json")
CFG = json.loads(CFG_PATH.read_text("utf-8"))

# 注意 (Intel Iris Xe 等 Windows 驱动): 只要显式写 #version, 驱动就把上下文当
# "forward compatible", varying / gl_Vertex / gl_FragColor 全部被移除, 立即模式
# (glBegin) 也会报 GL_INVALID_ENUM。所以这里统一用 **GLSL 330 core** 写法:
# 四边形由 gl_VertexID 生成 (不依赖任何顶点属性), 输出走 out 变量。
# 这样在 forward-compatible 上下文和真兼容上下文下都能跑。
VS = """#version 330 core
out vec2 vUV;
void main() {
    // 全屏四边形 (GL_TRIANGLE_STRIP, 4 顶点): 顶点 ID -> NDC 角点, 无需 VBO
    vec2 p = vec2((gl_VertexID & 1) == 0 ? -1.0 : 1.0,
                  (gl_VertexID & 2) == 0 ? -1.0 : 1.0);
    vUV = p * 0.5 + 0.5;
    gl_Position = vec4(p, 0.0, 1.0);
}
"""

# Duo 折叠着色器: 逆投影 + Vogel 盘模糊 + mip LOD + 边缘覆盖率
FS_DUO = """#version 330 core
uniform sampler2D uTex;
uniform vec2  uRes;      // 截图尺寸 px
uniform float uTilt;     // 玻璃转角 (弧度), 0 = 贴合界面
uniform float uEyeZ;     // 眼睛到界面平面距离 px
uniform float uSpread;   // 单位间隙 → 模糊半径 (散射半角正切)
uniform float uDark;     // 单位模糊半径损失的光量
uniform int   uMaxTaps;
in vec2 vUV;
out vec4 fragColor;

const float GOLDEN = 2.39996322972865332;
const float TWO_PI = 6.28318530717958648;

float hash21(vec2 p) {
    return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453);
}

void main() {
    // vUV: (0,0)=左下 (GL 约定)。铰链 = 屏幕底边。
    vec2 p = vUV * uRes;                 // y 自底向上, y=0 在铰链
    float tilt = uTilt;
    vec2 uvFlat = vec2(vUV.x, 1.0 - vUV.y);   // 平视采样 (截图行序 top-first)

    if (tilt < 1e-5) {
        fragColor = vec4(texture(uTex, uvFlat).rgb, 1.0);
        return;
    }

    // 玻璃像素放到 3D: 绕底边铰链旋转 tilt, 上部向观察者抬升
    float d = p.y;                                    // 该像素到铰链的距离
    vec3 glass = vec3(p.x, d * cos(tilt), d * sin(tilt));
    vec3 eye   = vec3(uRes * 0.5, uEyeZ);             // 眼睛: 屏幕中心正前上方

    // 光线 eye -> glass 像素, 延长交到界面平面 z=0
    float depth = eye.z - glass.z;
    if (depth <= 1e-3) { fragColor = vec4(0.0, 0.0, 0.0, 1.0); return; }
    float t   = eye.z / depth;
    vec2 hit  = eye.xy + (glass.xy - eye.xy) * t;     // 界面平面上的落点 (px, y 向上)

    // 玻璃与界面的间隙 → 模糊半径
    float gap    = glass.z;
    float radius = uSpread * gap;

    // 整个模糊核都在界面之外 → 黑
    if (hit.x < -radius || hit.x > uRes.x + radius ||
        hit.y < -radius || hit.y > uRes.y + radius) {
        fragColor = vec4(0.0, 0.0, 0.0, 1.0); return;
    }

    // 磨砂玻璃吸光: 与散射成正比地变暗 (iphone-duo / DuoLike 同款)
    float att = max(1.0 - uDark * radius, 0.0);

    vec2 uvHit = vec2(hit.x / uRes.x, 1.0 - hit.y / uRes.y);

    if (radius < 0.5) {
        fragColor = vec4(textureLod(uTex, uvHit, 0.0).rgb * att, 1.0);
        return;
    }

    // mip LOD (iphone-duo): 大半径先降到低分辨率 mip 再盘式采样
    float lod  = clamp(log2(max(radius, 1.0) / 16.0), 0.0, 6.0);
    float effR = radius / exp2(lod);

    // Vogel 盘 (DuoLike): sqrt 均匀面密度 + 黄金角 + 每像素随机旋转 → 磨砂颗粒
    int taps = int(clamp(effR * 2.0, 6.0, float(uMaxTaps)));
    float rot = hash21(gl_FragCoord.xy) * TWO_PI;

    // 边缘覆盖率 (iphone-duo): 采样核出界部分按比例衰减, 不出现硬边
    float footX = (radius + 1.0) / uRes.x;
    float footY = (radius + 1.0) / uRes.y;

    vec3 sum = vec3(0.0);
    for (int i = 0; i < taps; ++i) {
        float r = effR * sqrt((float(i) + 0.5) / float(taps));
        float a = float(i) * GOLDEN + rot;
        vec2 off = r * vec2(cos(a), sin(a));          // px, 界面平面坐标
        vec2 uv  = uvHit + vec2(off.x / uRes.x, -off.y / uRes.y);
        float cx = smoothstep(0.0, footX, uv.x) * (1.0 - smoothstep(1.0 - footX, 1.0, uv.x));
        float cy = smoothstep(0.0, footY, 1.0 - uv.y) * (1.0 - smoothstep(1.0 - footY, 1.0, 1.0 - uv.y));
        sum += textureLod(uTex, uv, lod).rgb * cx * cy;
    }
    vec3 c = sum / float(taps) * att;
    fragColor = vec4(c, 1.0);
}
"""


# ---------------------------------------------------------------- 串口线程
class AngleReader(threading.Thread):
    def __init__(self, port, baud):
        super().__init__(daemon=True)
        self.port, self.baud = port, baud
        self.lock = threading.Lock()
        self.angle = None
        self.other = None
        self.fps = 0.0
        self.status = "connecting"
        self._stop = False

    def get(self):
        with self.lock:
            return self.angle, self.other, self.fps, self.status

    def run(self):
        import re
        pat = re.compile(r"\{[^}]*\}")
        n, t0 = 0, time.time()
        while not self._stop:
            try:
                with serial.Serial(self.port, self.baud, timeout=1) as ser:
                    self._set("connected")
                    buf = b""
                    while not self._stop:
                        buf += ser.readline()
                        if b"}" not in buf:
                            buf = buf[-64:] if len(buf) > 256 else buf
                            continue
                        line, buf = buf.rsplit(b"}", 1)
                        line = (line + b"}").decode("ascii", "ignore")
                        m = pat.search(line)
                        if not m:
                            continue
                        try:
                            d = json.loads(m.group(0))
                        except ValueError:
                            continue
                        with self.lock:
                            self.angle = float(d[CFG.get("axis", "a")])
                            self.other = float(d.get("b", 0.0))
                        n += 1
                        now = time.time()
                        if now - t0 >= 1:
                            with self.lock:
                                self.fps = n / (now - t0)
                            n, t0 = 0, now
            except (serial.SerialException, OSError):
                self._set("waiting " + self.port)
                time.sleep(2)

    def _set(self, s):
        with self.lock:
            self.status = s


# ---------------------------------------------------------------- TCP 线程 (ESP8266 WiFi 透传)
def _local_prefix():
    """本机在哪个 /24 网段里 (不真正发包)。"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()
    return ip.rsplit(".", 1)[0]


def scan_for_bridge(port=8266, workers=96, timeout=0.35):
    """在当前 /24 里找开放 <port> 且会吐 JSON 的主机 —— 手机热点的 IP 会变,
    与其每次去后台查, 不如启动时扫一遍 (1~2 秒)。"""
    import concurrent.futures
    import socket
    prefix = _local_prefix()
    if not prefix:
        return None

    def probe(i):
        ip = f"{prefix}.{i}"
        s = None
        try:
            s = socket.create_connection((ip, port), timeout=timeout)
            s.settimeout(0.8)
            try:
                s.recv(256)          # 顺手读掉首包(可能是日志, 也可能是 JSON)
            except socket.timeout:
                pass
            return ip                # 端口开着就算命中
        except OSError:
            return None
        finally:
            if s:
                try:
                    s.close()
                except OSError:
                    pass

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for hit in ex.map(probe, range(1, 255)):
            if hit:
                return hit
    return None


class TcpAngleReader(threading.Thread):
    """从 ESP8266 串口 WiFi 模块透传出来的 TCP 流里读同样的 JSON 行。

    与 AngleReader 接口完全一致（get() 返回 angle, other, fps, status），
    所以主循环、标定脚本都不需要区分数据来自串口还是网络。断线自动重连。
    host 传 "auto" 时每次重连都会扫描当前网段找 8266 端口。
    """

    def __init__(self, host, port):
        super().__init__(daemon=True)
        self.host, self.port = host, int(port)
        self.lock = threading.Lock()
        self.angle = None
        self.other = None
        self.fps = 0.0
        self.status = f"tcp {host}:{port}"
        self._stop = False

    def get(self):
        with self.lock:
            return self.angle, self.other, self.fps, self.status

    def _set(self, s):
        with self.lock:
            self.status = s

    def run(self):
        import re
        import socket
        pat = re.compile(r"\{[^}]*\}")
        while not self._stop:
            sock = None
            host = self.host
            if host == "auto":
                self._set("scanning ...")
                host = scan_for_bridge(self.port)
                if not host:
                    self._set("bridge not found")
                    time.sleep(3)
                    continue
                self._set(f"tcp {host}:{self.port}")
            try:
                sock = socket.create_connection((host, self.port), timeout=3)
                sock.settimeout(1.0)
                try:
                    # 小包 100Hz, 关掉 Nagle 才能把延迟压到最低
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                except OSError:
                    pass
                self._set(f"tcp {host}:{self.port}")
                buf = b""
                n, t0 = 0, time.time()
                while not self._stop:
                    try:
                        chunk = sock.recv(4096)
                    except socket.timeout:
                        continue
                    if not chunk:
                        break                     # 对端断开
                    buf += chunk
                    while b"}" in buf:
                        line, buf = buf.split(b"}", 1)
                        m = pat.search((line + b"}").decode("ascii", "ignore"))
                        if not m:
                            continue
                        try:
                            d = json.loads(m.group(0))
                        except ValueError:
                            continue
                        with self.lock:
                            self.angle = float(d[CFG.get("axis", "a")])
                            self.other = float(d.get("b", 0.0))
                        n += 1
                        now = time.time()
                        if now - t0 >= 1:
                            with self.lock:
                                self.fps = n / (now - t0)
                            n, t0 = 0, now
                    if len(buf) > 512:            # 脏数据兜底
                        buf = buf[-256:]
                time.sleep(1.0)                   # 断开后别空转
            except OSError:
                self._set(f"waiting {self.host}:{self.port}")
                time.sleep(2)
            finally:
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass


# ---------------------------------------------------------------- 键盘控制
class ManualControl(threading.Thread):
    """键盘控制玻璃浓度: ↑/w +3%  ↓/s -3%  →/d 100%  ←/a 0%  r=角度自动  Esc 退出
    默认为手动覆盖模式 (target=0 即正常显示); 按 r 切换到跟随角度。

    两个输入来源共用 apply():
      - run(): 控制台 msvcrt.getwch()（控制台有焦点时）
      - GlassGLWindow.keyPressEvent(): 覆盖层窗口自己收键（窗口有焦点时）
    """

    def __init__(self):
        super().__init__(daemon=True)
        self.lock = threading.Lock()
        self.target = 0.0
        self.last_key = ""
        self.quit_flag = False
        self.auto = False          # False=键盘手动覆盖(默认) True=跟随角度

    def get(self):
        with self.lock:
            return self.target, self.last_key, self.auto

    def apply(self, kind):
        """kind: up/down/full/zero/toggle/quit"""
        with self.lock:
            if kind == "toggle":
                self.auto = not self.auto
                self.last_key = "角度自动" if self.auto else "手动"
                return
            if kind == "quit":
                self.quit_flag = True
                return
            delta = {"up": 0.03, "down": -0.03, "full": 1.0, "zero": 0.0}.get(kind)
            if delta is None:
                return
            self.auto = False       # 任何调节键都切回手动覆盖
            self.target = max(0.0, min(1.0,
                                       self.target + delta if abs(delta) < 0.5 else delta))
            self.last_key = {"up": "↑", "down": "↓", "full": "→", "zero": "←"}[kind]

    def run(self):
        import msvcrt
        while not self.quit_flag:
            ch = msvcrt.getwch()
            if ch in ("\xe0", "\x00"):
                k = msvcrt.getwch()
                self.apply({"H": "up", "P": "down", "M": "full", "K": "zero"}.get(k))
            else:
                if ch == "\x1b":
                    self.apply("quit")
                    break
                if ch.lower() == "r":
                    self.apply("toggle")
                    continue
                self.apply({"w": "up", "s": "down", "d": "full", "a": "zero"}.get(ch.lower()))


# ---------------------------------------------------------------- 截图线程
class CaptureWorker(threading.Thread):
    def __init__(self, region):
        super().__init__(daemon=True)
        self.region = region
        self.request = threading.Event()
        self.done = threading.Event()
        self.lock = threading.Lock()
        self.frame = None          # (bytes, w, h, seq)
        self.busy = False

    def latest(self):
        with self.lock:
            return self.frame

    def kick(self):
        if not self.busy:
            self.request.set()

    def run(self):
        seq = 0
        with mss.mss() as sct:
            while True:
                self.request.wait()
                self.request.clear()
                self.done.clear()
                self.busy = True
                try:
                    shot = sct.grab(self.region)
                    raw = shot.raw                     # BGRA
                    seq += 1
                    with self.lock:
                        self.frame = (raw, shot.width, shot.height, seq)
                except Exception as e:  # noqa
                    print("[capture] error:", e)
                finally:
                    self.busy = False
                    self.done.set()


# ---------------------------------------------------------------- GL 窗口
class GlassGLWindow(QOpenGLWindow):
    """全屏置顶玻璃覆盖层。

    为什么不用 QOpenGLWidget: 本机 (Intel Iris Xe / Win11 26300) 上 QOpenGLWidget
    把内部 FBO 合成到窗口那一步是坏的 —— grabFramebuffer() 抓到的内容完全正常,
    屏幕上却永远是一片纯黑。QOpenGLWindow 直接渲染到窗口表面, 显示正常。
    """
    def __init__(self, screen, reader, capturer, manual=None):
        super().__init__()
        self.reader = reader
        self.capturer = capturer
        self.manual = manual
        self.g = 0.0
        self.shown = False
        self._uploaded_seq = -1
        self._last_kick = 0.0
        self._last_print = 0.0
        self._locked = False
        self.angle_closed = float(CFG["angle_closed"])
        self.angle_open = float(CFG["angle_open"])
        self.glass_start = float(CFG.get("glass_start", 0.05))
        self.refresh_hz = float(CFG.get("refresh_hz", 3))
        self.max_tilt = float(CFG.get("max_tilt_deg", 88.0)) * 3.14159265 / 180.0
        self.eye_h = float(CFG.get("eye_dist_h", 2.0))       # 眼距 = 屏高倍数
        self.spread = float(CFG.get("blur_spread", 0.55))
        self.dark = float(CFG.get("darkening", 0.001))
        self.max_taps = int(CFG.get("max_taps", 32))

        self.setFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.Tool
        )
        self.setGeometry(screen.geometry())
        self.setTitle("duo-glass")

    def keyPressEvent(self, ev):
        """覆盖层自己收键: 它全屏置顶、控制台又看不见, 让用户"点控制台"根本不现实。
        所以窗口激活后 ↑↓←→ / r / Esc 直接在这里处理。"""
        k = ev.key()
        if k == Qt.Key.Key_Escape:
            QApplication.quit()
            return
        if k == Qt.Key.Key_R:
            if self.manual is not None:
                self.manual.apply("toggle")
            return
        kind = {
            Qt.Key.Key_Up: "up", Qt.Key.Key_W: "up",
            Qt.Key.Key_Down: "down", Qt.Key.Key_S: "down",
            Qt.Key.Key_Right: "full", Qt.Key.Key_D: "full",
            Qt.Key.Key_Left: "zero", Qt.Key.Key_A: "zero",
        }.get(k)
        if kind and self.manual is not None:
            self.manual.apply(kind)

    def _exclude_from_capture(self):
        # 关键: 把自己从屏幕捕获中排除, 否则截图会抓到上一次的渲染结果,
        # 反馈几帧后收敛成一片纯色 ("白屏" 的根因之一)
        # --smoke 调试时设 _no_exclude=True, 便于抓屏验证渲染效果
        if getattr(self, "_no_exclude", False):
            return
        try:
            import ctypes
            WDA_EXCLUDEFROMCAPTURE = 0x11
            r = ctypes.windll.user32.SetWindowDisplayAffinity(int(self.winId()),
                                                              WDA_EXCLUDEFROMCAPTURE)
            if not r:
                print("[警告] SetWindowDisplayAffinity 失败, 截图可能包含自身")
        except Exception as e:  # noqa
            print("[警告] 显示排除设置异常:", e)

    # ---------- GL ----------
    def initializeGL(self):
        print("[GL] initializeGL, context =", self.context().isValid(),
              self.context().format().majorVersion(), self.context().format().minorVersion())
        # 只在第一次暴露时启动 (上下文丢失后 initializeGL 会再次进入)
        if not getattr(self, "_excluded", False):
            self._excluded = True
            self._exclude_from_capture()
        if not hasattr(self, "timer"):
            self.timer = QTimer()
            self.timer.timeout.connect(self.tick)
            self.timer.start(16)
        self.prog = QOpenGLShaderProgram(self)
        ok_v = self.prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, VS)
        ok_f = self.prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, FS_DUO)
        if not (ok_v and ok_f and self.prog.link()):
            print("[GL] 着色器编译失败:\n", self.prog.log())
        self.prog.bind()

        self.cap_tex = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.cap_tex)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER,
                           GL.GL_LINEAR_MIPMAP_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
        # 空 VAO: core/forward-compatible 上下文里 draw 前必须绑定 VAO
        self.vao = GL.glGenVertexArrays(1)
        GL.glBindVertexArray(0)
        self._gl_ready = True

    def paintGL(self):
        if not getattr(self, "_gl_ready", False):
            if not hasattr(self, "_warned_gl"):
                self._warned_gl = True
                print("[GL] paintGL 时 _gl_ready=False (initializeGL 未完成?)")
            return
        dpr = self.devicePixelRatio()
        w = max(1, int(self.width() * dpr))
        h = max(1, int(self.height() * dpr))
        if not hasattr(self, "_painted_once"):
            self._painted_once = True
            frame0 = self.capturer.latest()
            print(f"[GL] paintGL 首帧: w={w} h={h} 截图帧={'有' if frame0 else '无'}")

        frame = self.capturer.latest()
        if frame and frame[3] != self._uploaded_seq:
            raw, fw, fh, seq = frame
            GL.glBindTexture(GL.GL_TEXTURE_2D, self.cap_tex)
            GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, fw, fh, 0,
                            GL.GL_BGRA, GL.GL_UNSIGNED_BYTE, raw)
            GL.glGenerateMipmap(GL.GL_TEXTURE_2D)
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
            self._uploaded_seq = seq

        if self._uploaded_seq == -1:
            GL.glClearColor(0, 0, 0, 1)
            GL.glClear(GL.GL_COLOR_BUFFER_BIT)
            return

        self.prog.bind()
        GL.glViewport(0, 0, w, h)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.cap_tex)
        GL.glUniform1i(self.prog.uniformLocation("uTex"), 0)
        GL.glUniform2f(self.prog.uniformLocation("uRes"), float(frame[1]), float(frame[2]))
        GL.glUniform1f(self.prog.uniformLocation("uTilt"), self.g * self.max_tilt)
        GL.glUniform1f(self.prog.uniformLocation("uEyeZ"), self.eye_h * frame[2])
        GL.glUniform1f(self.prog.uniformLocation("uSpread"), self.spread)
        GL.glUniform1f(self.prog.uniformLocation("uDark"), self.dark)
        GL.glUniform1i(self.prog.uniformLocation("uMaxTaps"), self.max_taps)
        self._draw_quad()

    def _draw_quad(self):
        # 顶点由 VS 里的 gl_VertexID 生成, 这里只负责画 4 个顶点的 triangle strip
        GL.glBindVertexArray(self.vao)
        GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
        GL.glBindVertexArray(0)

    # ---------- 主循环 ----------
    def tick(self):
        if self.manual is not None:
            target_m, key, auto = self.manual.get()
            if self.manual.quit_flag:
                QApplication.quit()
        else:
            target_m, key, auto = 0.0, "", False

        angle = other = None
        fps, status = 0.0, "manual"
        if self.reader is not None:
            angle, other, fps, status = self.reader.get()

        if auto and angle is not None:
            lo, hi = self.angle_open, self.angle_closed
            ratio = (angle - lo) / (hi - lo) if hi != lo else 0.0
            target = 0.0 if ratio < self.glass_start else min(1.0, ratio)
            mode = "自动"
        else:
            target = target_m
            mode = "手动"
        # --smoke 时冻结浓度: 否则 0.22/帧 的平滑会在 2 秒内把 g 衰减到 0,
        # 抓到的其实是平视画面, 起不到验证折叠效果的作用
        if getattr(self, "_freeze_g", False):
            self.g = self._freeze_g_value
        else:
            self.g += (target - self.g) * 0.22

        # Overlay 常驻显示: 不再按浓度隐藏 (透明逻辑已按需求移除)
        if not self.shown:
            self.capturer.kick()
        else:
            now = time.time()
            if self.refresh_hz > 0 and now - self._last_kick >= 1.0 / self.refresh_hz:
                self._last_kick = now
                self.capturer.kick()
            self.update()
            if CFG.get("lock_at_close") and self.g > 0.985 and not self._locked:
                self._locked = True
                import ctypes
                ctypes.windll.user32.LockWorkStation()
            if self.g < 0.9:
                self._locked = False

        # 控制台实时单行重绘
        if time.time() - self._last_print > 0.1:
            self._last_print = time.time()
            if self.reader is not None:
                a = angle if angle is not None else float("nan")
                print(f"\r[{mode}] a={a:7.2f}° b={(other if other is not None else 0):7.2f}° "
                      f"浓度={self.g*100:5.1f}%  [{status} {fps:3.0f}Hz] "
                      f"↑↓调节 r=切自动 Esc退出 ", end="", flush=True)
            else:
                print(f"\r[{mode}] 玻璃={self.g*100:5.1f}%  "
                      f"[↑↓调节 ←清空 →拉满 r=切自动 Esc退出] ", end="", flush=True)


# ---------------------------------------------------------------- 入口
def disable_quick_edit():
    """关掉控制台的 QuickEdit: 一旦有人点进控制台选中文字, 控制台会暂停输出、
    按键也没反应 —— 表面看就是"程序卡住了"。"""
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.GetStdHandle(-10)                      # STD_INPUT_HANDLE
        mode = ctypes.c_uint32()
        if h and k32.GetConsoleMode(h, ctypes.byref(mode)):
            ENABLE_EXTENDED_FLAGS = 0x0080
            ENABLE_QUICK_EDIT = 0x0040
            new = (mode.value | ENABLE_EXTENDED_FLAGS) & ~ENABLE_QUICK_EDIT
            k32.SetConsoleMode(h, new)
    except Exception:
        pass


def pick_port():
    """config.json 里的串口不在线时, 自动找 CH340/CP210x (换 USB 口会改 COM 号)。
    优先级: 命令行 --port=COMx > config.json > 自动探测"""
    for a in sys.argv:
        if a.startswith("--port="):
            return a.split("=", 1)[1]
    want = str(CFG.get("port", "COM3"))
    try:
        from serial.tools import list_ports
        ports = list(list_ports.comports())
    except Exception:
        return want
    if any(p.device.upper() == want.upper() for p in ports):
        return want
    for p in ports:
        hwid = (p.hwid or "").upper()
        if any(k in hwid for k in ("1A86", "10C4", "CH340", "CP210")):
            print(f"[串口] {want} 不在线, 自动改用 {p.device} ({p.description})")
            return p.device
    # 一个 CH340 都没枚举到: 常见于设备管理器里带黄色感叹号(代码 31, COM 号撞蓝牙串口)
    print(f"[串口] 没找到 {want}, 也没探测到 CH340/CP210x。")
    print("       若设备管理器里 CH340 带黄色感叹号(代码 31): 双击 win\\fix_ch340.bat 修复后重试。")
    return want


def main():
    smoke = "--smoke" in sys.argv
    selftest = "--selftest" in sys.argv
    manual = "--manual" in sys.argv
    auto_start = "--auto" in sys.argv      # 启动即跟随角度 (默认手动, 按 r 切换)
    duration = 0.0                          # --duration=秒: 到点自动退出, 便于演示
    tcp = None                              # --tcp[=host:port]: 走 ESP8266 WiFi 而不是串口
    smoke_g = 0.85
    for a in sys.argv:
        if a.startswith("--smoke-g="):
            smoke_g = max(0.0, min(1.0, float(a.split("=", 1)[1])))
        elif a.startswith("--duration="):
            duration = max(0.0, float(a.split("=", 1)[1]))
        elif a == "--tcp":
            tcp = str(CFG.get("tcp", "192.168.1.50:8266"))
        elif a.startswith("--tcp="):
            tcp = a.split("=", 1)[1]

    disable_quick_edit()      # 控制台被点选就会"卡住", 提前关掉

    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CompatibilityProfile)
    fmt.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(fmt)

    app = QApplication(sys.argv)
    screen = app.primaryScreen()
    dpr = screen.devicePixelRatio()
    geom = screen.geometry()
    region = {"left": geom.x(), "top": geom.y(),
              "width": int(geom.width() * dpr), "height": int(geom.height() * dpr)}

    kb = ManualControl()
    kb.start()
    if auto_start:
        with kb.lock:
            kb.auto = True
    if manual:
        reader = None
        print("[手动模式] 不连接传感器")
    elif tcp:
        if tcp == "auto":
            print("[网络] 自动扫描局域网里的 ESP8266 透传桥 (端口 8266) ...")
            reader = TcpAngleReader("auto", 8266)
        else:
            host, _, pstr = tcp.rpartition(":")
            print(f"[网络] 连接 {host}:{pstr} (ESP8266 透传)")
            reader = TcpAngleReader(host, int(pstr))
        reader.start()
    else:
        port = pick_port()
        print(f"[串口] 使用 {port}")
        reader = AngleReader(port, int(CFG.get("baud", 115200)))
        reader.start()
    capturer = CaptureWorker(region)
    capturer.start()

    print("=" * 60)
    print("iPhone Duo 悬浮玻璃 · Windows 端 v3 (复刻着色器)")
    print(f"  铰链=屏幕底边  最大转角 {CFG.get('max_tilt_deg')}°  眼距 {CFG.get('eye_dist_h')}x屏高")
    print(f"  blur_spread={CFG.get('blur_spread')}  darkening={CFG.get('darkening')}  "
          f"taps<={CFG.get('max_taps')}")
    print("-" * 60)
    print("  覆盖层会自动抢到键盘焦点，直接按键即可（不用去点控制台）")
    print("  ↑/↓ 调浓度   ← 清空   → 拉满   r 切换角度自动跟随   Esc 退出")
    print("=" * 60)

    if selftest:
        time.sleep(4)
        angle, other, fps, st = reader.get() if reader else (None, None, 0.0, "manual")
        capturer.kick()
        capturer.done.wait(timeout=3)
        frame = capturer.latest()
        ok = (frame is not None) and (manual or angle is not None)
        print(f"[自检] 串口: {st} angle={angle} fps={fps:.0f} | "
              f"截屏: {'OK %dx%d' % (frame[1], frame[2]) if frame else 'FAIL'}"
              f"  => {'PASS ✔' if ok else 'FAIL ✘'}")
        return 0 if ok else 1

    widget = GlassGLWindow(screen, reader, capturer, manual=kb)

    print("[运行] Overlay 常驻显示。Ctrl+C 退出。")
    if duration > 0:
        print(f"[运行] {duration:.0f}s 后自动退出")

    if smoke:
        def dump_and_quit():
            # 0) 重截一帧: 启动时那次 kick 早于窗口出现, 可能抓到 Overlay 自己(纯黑)
            capturer.kick()
            capturer.done.wait(timeout=2.0)
            widget.update()
            app.processEvents()
            # 1) 直接抓 Overlay 自己的渲染内容 (不经过屏幕捕获, 无反馈污染)
            try:
                img = widget.grabFramebuffer()
                out1 = str(Path(__file__).with_name("smoke_widget.png"))
                img.save(out1)
                print(f"[smoke] grabFramebuffer: {out1} ({img.width()}x{img.height()})")
            except Exception as e:
                print("[smoke] grabFramebuffer fail:", e)
            # 2) 整屏参考帧
            try:
                import mss as _mss
                from PIL import Image as _Image
                with _mss.MSS() as sct2:
                    shot = sct2.grab(region)
                    out2 = str(Path(__file__).with_name("smoke_frame.png"))
                    _Image.frombytes("RGB", shot.size, shot.rgb).save(out2)
                print(f"[smoke] 整屏帧: {out2}")
            except Exception as e:
                print("[smoke] dump fail:", e)
            app.quit()

        # 调试: 关闭后台重截(截图里会包含 Overlay 自身, 多次重截会反馈污染成纯色)
        widget.refresh_hz = 0.0
        widget.g = smoke_g
        widget._freeze_g = True
        widget._freeze_g_value = smoke_g
        QTimer.singleShot(2000, dump_and_quit)
        widget.show()
        widget.shown = True
        capturer.kick()
    else:
        widget.show()
        widget.shown = True
        capturer.kick()
    # 抢键盘焦点: 全屏覆盖层期间控制台被挡住, 用户点不到它, 按键必须由窗口自己收
    try:
        widget.requestActivate()
    except Exception as e:  # noqa
        print("[警告] 覆盖层获取焦点失败:", e)
    if duration > 0:
        QTimer.singleShot(int(duration * 1000), app.quit)
    app.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main())

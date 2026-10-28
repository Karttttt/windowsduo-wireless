# AGENTS.md — AI 协作指南

面向在本仓库工作的 AI 编码代理（与人类贡献者）。改动前请先读完本文件，避免踩已知的坑。

## 项目是什么

复刻 iPhone Duo 折叠屏的「悬浮玻璃」效果，运行在 Windows 笔记本上：

- **硬件侧**（`esp32/`）：ESP32 + MPU6050 测屏幕开合角度，100Hz 通过串口输出 `{"a":主轴角,"b":副轴角}` JSON。主轴 a 的约定：+10° ≈ 合盖，-90° ≈ 屏幕垂直于桌面。
- **Windows 侧**（`win/`）：PyQt6 QOpenGLWindow 全屏置顶悬浮层，GLSL 着色器实现逆投影 Duo 折叠效果（铰链=屏幕底边，间隙越大越模糊越暗，视线出界纯黑）。

## 目录结构

```
esp32/
  mpu6050_angle/          ESP-IDF v5.x 固件工程 (main/mpu6050_angle_main.c)
  debug_view.py|.bat      串口实时单行重绘调试查看器
stm32/
  bluepill_mpu6050/       STM32F103C8T6 移植版固件 (PlatformIO) + build.bat/flash.bat
  esp8266_bridge/         可选: ESP-01 串口 WiFi 透传桥 (UART -> TCP), STM32 固件不用改
win/
  glass_overlay.py        主程序: AngleReader + CaptureWorker + GlassGLWindow
  config.json             全部运行参数 (串口/角度映射/模糊/变暗等)
  offscreen_test.py       离屏渲染验证着色器(不出窗口, 出 PNG)
  lookdev.py              用真实桌面离屏快速试参数, 出 win/looks/*.png
  calibrate.py            两点标定: 合盖/全开角度写回 config.json
  run_overlay.bat         串口驱动启动  /  run_manual.bat  纯键盘启动
```

## 构建与运行

### ESP32 固件
- 本机用 ESP-IDF v5.4.4（`D:\Espressif`）。**不要**直接在 shell 里 `idf.py`（本机 PowerShell 不透传 `$env:PATH`），必须走包装器：
  ```
  python esp32/mpu6050_angle/run_build.py -p COM3 flash
  ```
- ESP32 = COM3 (CH9102)。烧录前确认串口没被 debug_view 等程序占用，否则报 PermissionError。
- I2C 引脚是掌控板（盛思乐动）专用口：P19=SCL→GPIO22，P20=SDA→GPIO23（**不是** 21/22）。

### STM32 固件（本机实际硬件：Blue Pill + GY-521 + ST-Link + CH340）
- 工程在 `stm32/bluepill_mpu6050/`（PlatformIO + Arduino core），输出协议与 ESP32 版一致：`{"a":..,"b":..}` @115200。
- **必须用 `build.bat` / `flash.bat`**，不要直接 `pio run`：工具链打不开中文路径下的 `ldscript.ld`（链接期报 `cannot open linker script ... Invalid argument`），且 `TMP` 指向 `C:\Temp` 会 `Permission denied`。bat 里已建 `C:\duo` 目录联接并把 `TMP/TEMP` 指到 `C:\duo\Temp`。
- 串口 ISP 兜底：BOOT0=1 复位后 `stm32flash -w firmware.bin -v -g 0x0 COMx`。

### Windows 端
- Python venv: `C:\Users\王家特\Desktop\duo\.venv\Scripts\python.exe`（PyQt6 / PyOpenGL / pyserial / mss / Pillow 已装）。
- 直接跑 `win/run_overlay.bat`（串口驱动，自动探测 CH340 的 COM 口）或 `win/run_manual.bat`（纯键盘）；标定用 `win/run_calibrate.bat`。
- 串口查看器 `esp32/debug_view.bat`，换 USB 口后 COM 号会变，可加 `--port COMx`。
- **无线模式**：`--tcp[=host:port]` 改用 `TcpAngleReader`（`run_wifi.bat`），与 `AngleReader` 接口一致，断线自愈。`--tcp` 不带值时读 `config.json` 的 `tcp`，`"auto"` 表示扫描当前 /24 的 8266 端口自动找桥（`scan_for_bridge()`）。数据源是 `stm32/esp8266_bridge`；STM32 只需把 PA9 接 ESP 的 RX。校园网有客户端隔离，用手机热点。
- **CH340 报代码 31（`STATUS_OBJECT_NAME_COLLISION`）时根本没有 COM 口**：Windows 把它分到了蓝牙串口已占用的号码，设备管理器带黄色感叹号。双击 `win/fix_ch340.bat` 修复（提权 → 改 PortName 到 ≥COM20 → 重启设备）。`pick_port()` 会自动找 CH340，号码变了不用改配置。
- 键盘（**覆盖层窗口自己收键**，见 `GlassGLWindow.keyPressEvent`；`ManualControl.apply()` 是唯一入口，控制台的 `msvcrt` 线程也复用它）：↑/↓ 浓度 ±3%，← 清零，→ 拉满，`r` 在 手动/角度自动 间切换，Esc 退出。`run_overlay.bat` 默认带 `--auto`（启动即跟随角度）。
- 控制台启动时会关掉 QuickEdit（`disable_quick_edit()`）：否则点一下控制台进入选择模式，输出会冻结、按键无响应，看起来像卡死。

## 已知坑（改代码前必读）

1. **GL 窗口用 `QOpenGLWindow`，不是 `QOpenGLWidget`（本机改过，别退回）**：本机（Intel Iris Xe / Win11 26300）上 `QOpenGLWidget` 把内部 FBO 合成到窗口那一步是坏的——`grabFramebuffer()` 抓到的内容完全正常，**屏幕上却永远纯黑**。已改为 `PyQt6.QtOpenGL.QOpenGLWindow`（直接渲染到窗口表面），显示正常。判断方法：`--smoke` 出的 `smoke_widget.png` 好看但屏幕全黑 = 这个坑。注：`QOpenGLWindow` 没有 `showEvent`/`setWindowTitle`/`grab()`，排除捕获与定时器放在 `initializeGL()` 里做。
2. PyQt6 6.11 枚举名：`QOpenGLShader.ShaderTypeBit.Vertex`（不是 `ShaderType.Vertex`）；`QSurfaceFormat.OpenGLContextProfile.CompatibilityProfile`。
3. **截图反馈污染**：Overlay 是不透明置顶窗口，mss 截屏会抓到自己上一帧，几帧后收敛成纯色。靠 `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE=0x11)` 把自己排除出捕获（见 `_exclude_from_capture`）。改截图逻辑时别动它。
4. **`.bat` 文件里禁止中文**：cmd 按 GBK 解码会乱码并把乱码当命令执行。bat 只写 ASCII。
5. **GLSL 版本（已在 Intel 机器上改过，别退回）**：原版用 `#version 330 compatibility` + 立即模式。Intel Iris Xe 的 Windows 驱动只要看到显式 `#version`，就把上下文当 **forward-compatible**——`varying` / `gl_Vertex` / `gl_FragColor` 全部报“removed”，`glBegin` 直接 GL_INVALID_ENUM。现已统一改为 `#version 330 core`：四边形由 `gl_VertexID` 生成（不需要 VBO/顶点属性），输出走 `out vec4 fragColor`。改着色器时保持 core 写法，不要再用 compatibility。
6. 调着色器先用 `offscreen_test.py` 离屏出图验证，再上真窗口；`--smoke` 用 `grabFramebuffer()` 抓帧（不要用整屏截图验证 GL 内容）。
7. config.json 是唯一参数入口（`blur_spread` 模糊、`darkening` 变暗、`angle_closed/angle_open` 角度映射等），不要在代码里硬编码覆盖它。

## 提交约定

- 主分支 `main`，远端 `origin` = github.com/KaedeharaKazuha1029/WindowsDuo。
- `.gitignore` 排除 `esp32/mpu6050_angle/build/`（120MB）、`*.log`、`dbg*.txt`、`*_log.txt`、`*_exit.txt`、`win/smoke_frame.png`、`win/smoke_grab.png`、`.workbuddy/`。不要把这些加回来。
- 提交信息用中文、说明改动动机即可。

## 许可

MIT (见 LICENSE)。

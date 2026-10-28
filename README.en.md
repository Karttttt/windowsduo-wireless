# WindowsDuo — Wireless Replica

**[中文](README.md) | English**

A replica of [iPhone Duo's "floating glass" effect](https://github.com/KaedeharaKazuha1029/WindowsDuo)
for laptop screens: as you open or close the lid, the desktop content behaves as if it sits
behind a pane of glass hinged at the screen's bottom edge — the wider the gap, the blurrier and
darker it gets, fading to black where your line of sight leaves the content plane.

> **This repository is a replica**, based on
> [KaedeharaKazuha1029/WindowsDuo](https://github.com/KaedeharaKazuha1029/WindowsDuo) (MIT).
>
> Original hardware was an ESP32 talking over **USB serial**. This replica swaps the MCU for an
> **STM32F103C8T6 (Blue Pill)** and adds an **ESP8266 serial-to-WiFi bridge**, so the hinge can be
> completely cable-free with a 100 Hz wireless feed. The inverse-projection shader and the
> complementary filter are unchanged from upstream — see
> [What we changed](#what-we-changed-vs-upstream).

![demo](win/smoke_widget.png)

## How it works

This is not a full-screen Gaussian blur — it is a **spatial inverse projection**:

- The desktop content is fixed on a plane in world space; the screen is a pane of glass that
  rotates about its bottom edge towards the viewer.
- For every glass pixel, a ray is cast from the eye through that pixel and extended until it hits
  the content plane. That intersection is the sample point.
- Larger gap → larger sampling radius (stronger blur) and more absorption (darker). Near the hinge
  the content stays sharp.
- Sampling uses a Vogel spiral disc with mip-level LOD selection and edge-coverage smoothing,
  all in a single-pass GLSL shader.

The model is derived from several open-source re-creations (DuoLikeAnimation / iphone-duo /
MacDuo / FrostFold) and re-implemented for the laptop case, where the hinge is the bottom edge of
the screen.

## Variants

| Variant | Platform | Lid-angle source | Hardware |
|---|---|---|---|
| Windows + ESP32 | Windows | ESP32 + MPU6050 over USB serial | ESP32 dev board + MPU6050 |
| **Windows + STM32 (this repo)** | Windows | STM32F103C8T6 + MPU6050, optional WiFi | Blue Pill + GY-521 + ST-Link, + NodeMCU/ESP-01 for wireless |
| macOS port | macOS | Built-in lid-angle sensor (HID) | None (2016+ MacBooks) |
| Manual | Windows / macOS | Keyboard | None |

## Repository layout

```
esp32/                    Original ESP-IDF firmware + serial debug viewer
  mpu6050_angle/          Gyro bias calibration + complementary filter, 100 Hz JSON
stm32/
  bluepill_mpu6050/       STM32 port (PlatformIO + Arduino core) + build.bat / flash.bat
  esp8266_bridge/         UART -> TCP transparent bridge (NodeMCU / ESP-01)
                          + find_ip.py to locate it on the LAN
win/                      Windows host
  glass_overlay.py        PyQt6 + OpenGL full-screen overlay (serial or TCP input)
  config.json             All runtime parameters
  offscreen_test.py       Render the shader offscreen to a PNG
  lookdev.py              Render the real desktop at arbitrary parameters (no full-screen flash)
  calibrate.py            Two-pose calibration -> angle_closed / angle_open
  fix_ch340.bat           Repair a CH340 COM-port collision (device problem code 31)
  run_overlay.bat         Serial mode   /  run_wifi.bat   Wireless mode
  run_manual.bat          Keyboard only /  run_calibrate.bat  Calibration
mac/                      macOS port (see mac/README.md)
```

## Quick start

### 1. Flash the STM32

Open `stm32/bluepill_mpu6050/` and run `build.bat`, then `flash.bat` (ST-Link, SWD).
Wiring: GY-521 `VCC→5V, GND→GND, SCL→PB6, SDA→PB7, AD0→GND`; USART1 is `PA9 (TX) / PA10 (RX)`
at 115200, output format `{"a":<pitch>,"b":<secondary>}` at 100 Hz.

> On Windows with a non-ASCII user name, the ARM toolchain cannot open the linker script and
> requires a temp directory inside the project tree. Both bat files create an ASCII junction
> `C:\duo` and point `TMP` at `C:\duo\Temp` to work around this.

### 2. Optional: go wireless

```
Blue Pill PA9 (TX) ──► ESP8266 RX          ── WiFi/TCP ──► PC
5 V module        ──► ESP VIN, common GND
```

Flash `stm32/esp8266_bridge/` once (copy `src/secrets.example.h` to `src/secrets.h` and fill in
your 2.4 GHz SSID/password), then power-cycle with **IO0 released**. The bridge opens a TCP server
on port 8266 and forwards every byte it receives on UART. Measured: 100 Hz, zero dropped frames.

### 3. Run the overlay

```bat
WindowsDuo\win\run_overlay.bat          :: serial (CH340 auto-detected)
WindowsDuo\win\run_wifi.bat             :: wireless (auto-discovers the bridge on the LAN)
WindowsDuo\win\run_manual.bat           :: no hardware, keyboard only
```

Keys (the overlay window takes keyboard focus itself): `↑/↓` glass concentration,
`←/→` clear/full, `r` toggle between manual override and angle-following, `Esc` quit.

## Configuration

All runtime parameters live in `win/config.json`:

| Key | Meaning | Value here |
|---|---|---|
| `angle_closed` / `angle_open` | Raw sensor angles for lid closed / fully open | 88 / 30 (overwritten by `run_calibrate.bat`) |
| `blur_spread` | Blur radius per unit gap (smaller = clearer) | 0.30 |
| `darkening` | Light absorbed per unit blur radius | 0.0003 |
| `eye_dist_h` | Eye distance in screen heights | 1.9 |
| `max_tilt_deg` | Glass angle at full concentration | 66 |
| `refresh_hz` | Desktop capture rate | 3 |
| `port` / `tcp` | Serial port / wireless endpoint (`"auto"` = scan the LAN) | COM3 / auto |
| `lock_at_close` | Lock the workstation when fully closed | false |

Upstream ships `blur 0.42 / darkening 0.001 / tilt 88 / eye 2.0`. On a dark-themed desktop that
reads as almost pure black at high concentration, so this replica dials it a notch softer —
`win/lookdev.py` was used to compare the frames side by side.

To recalibrate the angle mapping:

```bat
WindowsDuo\win\run_calibrate.bat
```

Close the lid, press Enter; open it fully, press Enter; the script writes `angle_closed` /
`angle_open` back into `config.json`. If `a` barely moves while `b` does, set `"axis": "b"` instead
of reflashing.

## Known pitfalls

All of them are written up in [AGENTS.md](AGENTS.md); the short version:

1. **Use `QOpenGLWindow`, not `QOpenGLWidget`.** On this machine (Intel Iris Xe / Windows 11) the
   widget's FBO-to-window composition silently produces a **black screen** even though
   `grabFramebuffer()` returns a perfectly correct image.
2. **Use `#version 330 core`.** Intel's Windows driver treats any context with an explicit
   `#version` as forward-compatible, which removes `varying`, `gl_Vertex`, `gl_FragColor` — and
   immediate mode. The full-screen quad is generated from `gl_VertexID` instead.
3. **Capture feedback loop.** An opaque always-on-top overlay captures itself unless it is excluded
   with `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)`; without that the image converges to a
   flat colour within a few frames.
4. **CH340 COM-port collision.** Windows sometimes assigns the USB-serial adapter a COM number that
   a Bluetooth serial port already owns (`STATUS_OBJECT_NAME_COLLISION`, device code 31, no port
   exists at all). `win/fix_ch340.bat` reassigns it to a free number ≥ COM20.
5. **Batch files must stay ASCII.** `cmd` decodes them as GBK and will execute the mojibake.

## What we changed vs upstream

- **MCU port**: ESP-IDF firmware → PlatformIO + Arduino core on STM32F103C8T6. Same algorithm
  (complementary filter 0.98/0.02, 3 s gyro bias calibration, 0.3 output EMA), same JSON protocol,
  same 100 Hz rate. I2C moved to PB6/PB7, USART1 to PA9/PA10.
- **Wireless**: new `stm32/esp8266_bridge` firmware plus a `TcpAngleReader` in the host app, with
  LAN auto-discovery. Credentials live in a gitignored `secrets.h`.
- **Render path**: GLSL 330 core + `gl_VertexID` quad; `QOpenGLWidget` → `QOpenGLWindow`.
- **Host app**: `--tcp`, `--auto`, `--duration`, `--port` flags, CH340 auto-detection, QuickEdit
  disabled on the console, and the overlay window handles its own keys.
- **Tooling**: `calibrate.py`, `lookdev.py`, `find_ip.py`, `fix_ch340.bat`, portable launchers.

## License

[MIT](LICENSE). The original copyright notice is preserved; the shader model and filter design come
from upstream.

## Credits

- elijah-semyonov/DuoLikeAnimation — inverse-projection model and Vogel disc blur
- chuspeeism/iphone-duo — mip LOD sampling and edge coverage smoothing
- DhananjayBhosale/MacDuo — laptop scenario (hinge = screen bottom edge)
- askmaddyy/FrostFold — frosted-glass look parameters
- macOS sensor protocol reference: [Mac-Duo by sumimakito](https://github.com/sumimakito/MacDuo) (Apache-2.0)
"""
角度自动标定: 把「合盖」和「全开」两个姿态的真实角度读出来, 直接生成 config.json 的
angle_closed / angle_open。

用法:
    .venv\\Scripts\\python.exe WindowsDuo\\win\\calibrate.py [--port COM9]
    (不传 --port 时读 win/config.json 的 port, 并自动找 CH340/CP210x)

流程:
    1. 合上笔记本屏幕, 回车 -> 采样 3 秒
    2. 把屏幕开到最大, 回车 -> 采样 3 秒
    3. 屏幕输出建议参数, 并询问是否直接写回 config.json
"""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import serial

CFG_PATH = Path(__file__).with_name("config.json")


def find_port(cfg_port):
    try:
        from serial.tools import list_ports
        ports = list(list_ports.comports())
    except Exception:
        return cfg_port
    for p in ports:
        if p.device.upper() == str(cfg_port).upper():
            return cfg_port
    for p in ports:
        h = (p.hwid or "").upper()
        if any(k in h for k in ("1A86", "10C4", "CH340", "CP210")):
            print(f"[端口] {cfg_port} 不存在, 自动改用 {p.device} ({p.description})")
            return p.device
    return cfg_port


def sample(ser, axis, seconds=3.0):
    """采样 seconds 秒, 返回该轴的中位数 (抗单帧毛刺)"""
    t0 = time.time()
    vals = []
    while time.time() - t0 < seconds:
        line = ser.readline()
        if not line:
            continue
        try:
            text = line.decode("ascii", "ignore")
            start, end = text.find("{"), text.rfind("}")
            if start < 0 or end < 0:
                continue
            d = json.loads(text[start:end + 1])
            vals.append(float(d[axis]))
        except (ValueError, KeyError):
            continue
    if not vals:
        raise RuntimeError("3 秒内没有收到任何角度数据, 检查串口和固件")
    return statistics.median(vals), len(vals)


def main():
    cfg = json.loads(CFG_PATH.read_text("utf-8"))
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default=cfg.get("port", "COM3"))
    ap.add_argument("--axis", default=cfg.get("axis", "a"))
    ap.add_argument("--baud", type=int, default=int(cfg.get("baud", 115200)))
    args = ap.parse_args()

    port = find_port(args.port)
    print(f"连接 {port} @ {args.baud}, 轴 = {args.axis}")
    ser = serial.Serial(port, args.baud, timeout=1)
    ser.reset_input_buffer()

    print("\n[1/2] 请把笔记本屏幕完全合上, 然后按回车...")
    input()
    ser.reset_input_buffer()
    closed, n1 = sample(ser, args.axis)
    print(f"      合盖角度 = {closed:.2f}°  ({n1} 帧)")

    print("\n[2/2] 请把屏幕开到最大, 然后按回车...")
    input()
    ser.reset_input_buffer()
    opened, n2 = sample(ser, args.axis)
    print(f"      全开角度 = {opened:.2f}°  ({n2} 帧)")

    ser.close()

    span = abs(opened - closed)
    print("\n" + "=" * 56)
    print(f"  角度跨度 {span:.1f}°  合盖 {closed:.2f}° -> 全开 {opened:.2f}°")
    if span < 20:
        print("  [!] 跨度太小 (应 > 60°)。检查: 模块是否随屏幕一起转动?")
        print("      a 不变而 b 变 -> 用 --axis b 重跑, 或改 config.json 的 axis")
    print(f'  "angle_closed": {closed:.1f},')
    print(f'  "angle_open":   {opened:.1f},')
    print("=" * 56)

    ans = input("\n直接写回 win/config.json? [y/N] ").strip().lower()
    if ans == "y":
        cfg["angle_closed"] = round(closed, 1)
        cfg["angle_open"] = round(opened, 1)
        cfg["axis"] = args.axis
        cfg["port"] = port
        CFG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", "utf-8")
        print(f"已写入 {CFG_PATH}")
        return 0
    print("未写入。手动把上面两行抄进 win/config.json 即可。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
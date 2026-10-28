"""扫描当前网段, 找出 ESP8266 透传桥的 IP（开放 8266/tcp, 且能读到角度 JSON）。

用法:
    .venv\\Scripts\\python.exe WindowsDuo\\stm32\\esp8266_bridge\\find_ip.py
    ... find_ip.py 192.168.43        # 指定网段前缀

先连上 ESP 所在的 WiFi/热点再跑。
"""
import concurrent.futures
import json
import socket
import sys
import time

PORT = 8266


def local_prefixes():
    """返回本机所在网段的前三段, 例如 ['192.168.43']"""
    out = []
    try:
        import subprocess
        txt = subprocess.run(["ipconfig"], capture_output=True, text=True,
                             encoding="gbk", errors="ignore").stdout
        import re
        for m in re.finditer(r"IPv4.*?:\s*(\d+\.\d+\.\d+)\.\d+", txt):
            p = m.group(1)
            if not p.startswith("127."):
                out.append(p)
    except Exception:
        pass
    return list(dict.fromkeys(out))


def probe(ip):
    s = None
    try:
        s = socket.create_connection((ip, PORT), timeout=0.35)
        s.settimeout(1.2)
        data = s.recv(512)
        if b"{" in data:
            return ip, data.decode("ascii", "ignore")[:60]
        return ip, "<端口开着，但没读到 JSON>"
    except OSError:
        return None
    finally:
        if s:
            try:
                s.close()
            except OSError:
                pass


def main():
    prefixes = [sys.argv[1]] if len(sys.argv) > 1 else local_prefixes()
    if not prefixes:
        print("拿不到本机网段，请手动传参，例如: find_ip.py 192.168.43")
        return 1
    print(f"扫描网段: {', '.join(p + '.0/24' for p in prefixes)}  (端口 {PORT})")
    ips = [f"{p}.{i}" for p in prefixes for i in range(1, 255)]
    t0 = time.time()
    hits = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=96) as ex:
        for r in ex.map(probe, ips):
            if r:
                hits.append(r)
                print(f"  >>> {r[0]}  {r[1]}")
    print(f"完成, 用时 {time.time()-t0:.1f}s, 命中 {len(hits)} 个")
    if not hits:
        print("没找到。检查: ESP 是否上电 / 是否和电脑连同一个热点 / 是否烧的是连该热点的固件")
        return 1
    if len(hits) == 1:
        print(f"\n用这条命令启动:\n  WindowsDuo\\win\\run_wifi.bat {hits[0][0]}:{PORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
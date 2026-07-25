#!/usr/bin/env python3
"""Full TCP port sweep of the robot + probe of likely UDP ports.

Purpose: find any service other than the Tuya DP channel (6668) — in particular
a P2P / media / map channel the vendor app might use to pull the map raster
directly from the robot. If such a port exists, a fully cloud-free map is on.

    ./homerun ports
"""
import socket, sys, concurrent.futures, time

IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.3.241"
KNOWN = {6668: "Tuya DP channel (AES)", 6667: "Tuya discovery",
         6666: "Tuya discovery", 7000: "Tuya discovery/pair",
         80: "http", 443: "https", 554: "rtsp", 1883: "mqtt",
         8883: "mqtt-tls", 22: "ssh", 23: "telnet", 5000: "upnp?",
         8000: "http-alt", 8080: "http-alt", 9999: "?", 32768: "p2p?"}


def tcp(port, timeout=0.55):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        return port if s.connect_ex((IP, port)) == 0 else None
    except Exception:
        return None
    finally:
        s.close()


def banner(port):
    """Try to coax a banner so we can tell what the service is."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2.0)
        s.connect((IP, port))
        try:
            s.settimeout(1.2)
            data = s.recv(256)
            if data:
                return data[:80]
        except Exception:
            pass
        # nudge it
        try:
            s.sendall(b"\r\n")
            s.settimeout(1.2)
            data = s.recv(256)
            if data:
                return data[:80]
        except Exception:
            pass
        return b""
    except Exception:
        return b""
    finally:
        try: s.close()
        except Exception: pass


def udp(port, payload=b"\x00", timeout=1.0):
    """UDP is unreliable to probe; we only report ports that actually answer."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        s.sendto(payload, (IP, port))
        data, _ = s.recvfrom(2048)
        return (port, data[:60]) if data else None
    except Exception:
        return None
    finally:
        s.close()


print(f"full TCP sweep of {IP} (1-65535)…", flush=True)
t0 = time.time()
open_tcp = []
with concurrent.futures.ThreadPoolExecutor(max_workers=600) as ex:
    for r in ex.map(tcp, range(1, 65536)):
        if r:
            open_tcp.append(r)
            print(f"  OPEN tcp/{r}  {KNOWN.get(r,'')}", flush=True)
print(f"TCP sweep done in {time.time()-t0:.0f}s — {len(open_tcp)} open\n", flush=True)

for p in sorted(open_tcp):
    b = banner(p)
    desc = KNOWN.get(p, "unknown")
    print(f"  tcp/{p:<6} {desc:<26} banner={b!r}", flush=True)

print("\nprobing UDP ports that commonly carry P2P/media…", flush=True)
UDP_PORTS = [6666, 6667, 6668, 6669, 7000, 1900, 5353, 3478, 5683,
             32100, 32108, 10000, 20000, 8800, 8888, 9999, 50000]
with concurrent.futures.ThreadPoolExecutor(max_workers=32) as ex:
    for r in ex.map(udp, UDP_PORTS):
        if r:
            print(f"  UDP {r[0]} replied: {r[1]!r}", flush=True)
print("\nnote: 32100/32108 are Tuya/CS2 P2P ports — if either answers, "
      "a direct device<->app channel exists.", flush=True)

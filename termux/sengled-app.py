#!/usr/bin/env python3
"""Sengled bulb control for Termux (standalone, stdlib only).

Controls Sengled WiFi bulbs over UDP (port 9080) directly from the phone,
with no PC and no cloud involved. The phone must be on the same WiFi
network as the bulbs.

Usage:
    python sengled-app.py                    # interactive menu
    python sengled-app.py status [bulb]      # query brightness/power
    python sengled-app.py on [bulb]          # turn on
    python sengled-app.py off [bulb]         # turn off
    python sengled-app.py b 50 [bulb]        # set brightness 1-100

bulb: "all" (default), a name, an IP, or an index (1-based).
"""

import json
import socket
import sys
import time

BULB_PORT = 9080
TIMEOUT = 3
RETRIES = 3

# Bulb registry. Edit names/IPs here to match your setup.
BULBS = [
    {"name": "lampara de sala", "ip": "192.168.68.150"},
    {"name": "luz blanca", "ip": "192.168.68.118"},
]


def send_udp(bulb_ip, payload, timeout=TIMEOUT):
    """Send one JSON command to a bulb; return the parsed response dict or None."""
    data = json.dumps(payload).encode("utf-8")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(timeout)
            s.sendto(data, (bulb_ip, BULB_PORT))
            raw, _ = s.recvfrom(4096)
            return json.loads(raw.decode("utf-8"))
    except (OSError, ValueError):
        return None


def exec_command(bulb_ip, payload):
    """Run a command with retries. True when the bulb confirms ret=0."""
    for _ in range(RETRIES):
        resp = send_udp(bulb_ip, payload)
        if isinstance(resp, dict):
            result = resp.get("result")
            if isinstance(result, dict) and result.get("ret") == 0:
                return True
        time.sleep(0.5)
    return False


def switch(bulb_ip, on):
    return exec_command(bulb_ip, {"func": "set_device_switch",
                                  "param": {"switch": 1 if on else 0}})


def set_brightness(bulb_ip, value):
    value = max(1, min(100, int(value)))
    return exec_command(bulb_ip, {"func": "set_device_brightness",
                                  "param": {"brightness": value}})


def get_brightness(bulb_ip):
    resp = send_udp(bulb_ip, {"func": "get_device_brightness", "param": {}})
    if isinstance(resp, dict):
        result = resp.get("result")
        if isinstance(result, dict) and "brightness" in result:
            return result["brightness"]
    return None


def resolve_bulbs(spec):
    """Map a user spec ('all', name, ip, index) to a list of bulb dicts."""
    if not spec or spec.strip().lower() == "all":
        return BULBS
    spec = spec.strip()
    for b in BULBS:
        if b["name"].lower() == spec.lower() or b["ip"] == spec:
            return [b]
    try:
        idx = int(spec)
        if 1 <= idx <= len(BULBS):
            return [BULBS[idx - 1]]
    except ValueError:
        pass
    print(f"Unknown bulb: {spec}")
    print("Known bulbs: " + ", ".join(f"{i+1}={b['name']}" for i, b in enumerate(BULBS)))
    sys.exit(2)


def main():
    args = sys.argv[1:]
    if not args:
        interactive_menu()
        return

    action = args[0].lower()
    bulbs = resolve_bulbs(args[1] if len(args) > 1 else "all")

    if action in ("on", "off"):
        for b in bulbs:
            ok = switch(b["ip"], action == "on")
            print(f"{'ON' if action == 'on' else 'OFF'} {b['name']} ({b['ip']}): "
                  f"{'OK' if ok else 'FAILED'}")
    elif action in ("b", "brightness", "brillo"):
        if len(args) < 2:
            print("Usage: sengled-app.py brightness <1-100> [bulb]")
            sys.exit(2)
        value = max(1, min(100, int(args[1])))
        target = resolve_bulbs(args[2] if len(args) > 2 else "all")
        for b in target:
            ok = set_brightness(b["ip"], value)
            print(f"BRIGHTNESS {value}% {b['name']} ({b['ip']}): "
                  f"{'OK' if ok else 'FAILED'}")
    elif action in ("status", "estado"):
        for b in bulbs:
            value = get_brightness(b["ip"])
            print(f"{b['name']} ({b['ip']}): "
                  f"{'brightness ' + str(value) + '%' if value is not None else 'no response'}")
    elif action in ("help", "--help", "-h"):
        print(__doc__)
    else:
        print(f"Unknown action: {action}")
        print(__doc__)
        sys.exit(2)


def interactive_menu():
    print("=== Sengled bulbs ===")
    print("Bulbs:")
    for i, b in enumerate(BULBS, 1):
        value = get_brightness(b["ip"])
        state = f"brightness {value}%" if value is not None else "no response"
        print(f"  {i}. {b['name']} ({b['ip']}) — {state}")
    print()
    print("Actions: 1=ON all  2=OFF all  3=brightness  4=ON one  5=OFF one  0=exit")
    while True:
        try:
            choice = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if choice == "0":
            return
        elif choice == "1":
            for b in BULBS:
                print(f"ON {b['name']}: {'OK' if switch(b['ip'], True) else 'FAILED'}")
        elif choice == "2":
            for b in BULBS:
                print(f"OFF {b['name']}: {'OK' if switch(b['ip'], False) else 'FAILED'}")
        elif choice == "3":
            try:
                value = int(input("Brightness (1-100): "))
            except (ValueError, EOFError):
                continue
            for b in BULBS:
                print(f"BRIGHTNESS {value}% {b['name']}: "
                      f"{'OK' if set_brightness(b['ip'], value) else 'FAILED'}")
        elif choice in ("4", "5"):
            try:
                idx = int(input("Bulb number: "))
            except (ValueError, EOFError):
                continue
            if 1 <= idx <= len(BULBS):
                b = BULBS[idx - 1]
                print(f"{'ON' if choice == '4' else 'OFF'} {b['name']}: "
                      f"{'OK' if switch(b['ip'], choice == '4') else 'FAILED'}")
        else:
            print("Unknown option")


if __name__ == "__main__":
    main()

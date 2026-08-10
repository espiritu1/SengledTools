"""Sengled UDP web control panel (multi-bulb).

Local web UI to control Sengled WiFi bulbs via UDP.
No cloud, no dependencies beyond the SengledTools package.

Usage:
    python sengled-web.py [--port 8000]
    python sengled-web.py --bulb "Foco 1=192.168.68.110" --bulb "Foco 2=192.168.68.118"
    python sengled-web.py --ip 192.168.68.110   # single-bulb mode (backward compatible)

Bulb names are editable from the UI and persist in ~/.sengled/web-panel.json.

Open http://<this-pc-ip>:8000 from any device on the same LAN.
"""

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sengled.udp import send_udp_command

# ---------------------------------------------------------------------------
# Bulb registry: name -> IP
# ---------------------------------------------------------------------------

DEFAULT_BULBS = [
    {"name": "Foco 1 (viejo)", "ip": "192.168.68.150"},
    {"name": "Foco 2 (nuevo)", "ip": "192.168.68.118"},
]

BULBS = list(DEFAULT_BULBS)  # populated/replaced by main()

# Persistence for editable bulb names
CONFIG_DIR = os.path.expanduser("~/.sengled")
CONFIG_FILE = os.path.join(CONFIG_DIR, "web-panel.json")


def load_panel_config():
    """Load saved names from ~/.sengled/web-panel.json, if present."""
    saved = {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        for b in data.get("bulbs", []):
            ip = str(b.get("ip", "")).strip()
            name = str(b.get("name", "")).strip()
            if ip and name:
                saved[ip] = name
    except (OSError, ValueError):
        pass  # no config yet or corrupted: fall back to defaults
    return saved


def save_panel_config():
    """Persist current bulb names to ~/.sengled/web-panel.json (atomic)."""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp = CONFIG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"bulbs": BULBS}, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_FILE)
    except OSError:
        pass  # non-fatal: names just won't persist


def get_bulb_ip(bulb_id: str) -> str:
    """Resolve a bulb id (ip, name, or index) to its IP. Returns None if unknown."""
    bulb_id = bulb_id.strip()
    for b in BULBS:
        if b["ip"] == bulb_id or b["name"] == bulb_id:
            return b["ip"]
    try:
        idx = int(bulb_id)
        if 0 <= idx < len(BULBS):
            return BULBS[idx]["ip"]
    except (TypeError, ValueError):
        pass
    return None


# ---------------------------------------------------------------------------
# Bulb commands (same payloads as sengled_tool.py)
# ---------------------------------------------------------------------------

def cmd_switch(bulb_ip: str, on: bool):
    return send_udp_command(
        bulb_ip,
        {"func": "set_device_switch", "param": {"switch": 1 if on else 0}},
    )


def cmd_brightness(bulb_ip: str, value: int):
    value = max(0, min(100, int(value)))
    return send_udp_command(
        bulb_ip,
        {"func": "set_device_brightness", "param": {"brightness": value}},
    )


def cmd_get_brightness(bulb_ip: str):
    return send_udp_command(bulb_ip, {"func": "get_device_brightness", "param": {}})


# Server-side state (best effort; bulbs report state on demand)
state = {}  # ip -> {"power": "unknown", "brightness": None}


def ensure_state(bulb_ip: str):
    if bulb_ip not in state:
        state[bulb_ip] = {"power": "unknown", "brightness": None}
    return state[bulb_ip]


def refresh_state(bulb_ip: str):
    st = ensure_state(bulb_ip)
    resp = cmd_get_brightness(bulb_ip)
    if resp and "result" in resp:
        params = resp.get("result", {})
        if "brightness" in params:
            st["brightness"] = params["brightness"]
            return True
    return False


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#14161c">
<title>Sengled Bulbs</title>
<style>
  :root { --bg:#14161c; --card:#1e222b; --fg:#e8eaf0; --muted:#9aa3b2;
          --accent:#ffb84d; --ok:#3ddc84; --err:#ff5c5c; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:system-ui, -apple-system, "Segoe UI", sans-serif;
         background:var(--bg); color:var(--fg); padding:24px 16px; }
  .wrap { max-width:880px; margin:0 auto; }
  .head { display:flex; align-items:baseline; justify-content:space-between;
          margin-bottom:18px; gap:12px; flex-wrap:wrap; }
  h1 { font-size:20px; margin:0; font-weight:600; }
  .sub { color:var(--muted); font-size:12.5px; }
  .grid { display:grid; grid-template-columns:repeat(2, 1fr); gap:16px; }
  @media (max-width:720px) { .grid { grid-template-columns:1fr; } }
  .card { background:var(--card); border-radius:20px; padding:20px;
          box-shadow:0 10px 40px rgba(0,0,0,.45); }
  .card-head { display:flex; align-items:center; gap:8px; margin-bottom:2px; }
  .name { font-size:16px; font-weight:600; overflow:hidden; text-overflow:ellipsis;
          white-space:nowrap; flex:1; min-width:0; }
  .pencil { flex:none; width:34px; height:34px; border-radius:10px; border:0;
            background:#3a4150; color:var(--fg); cursor:pointer;
            display:flex; align-items:center; justify-content:center; padding:0; }
  .pencil:hover { background:#4a5265; }
  .pencil svg { width:16px; height:16px; }
  .name-input { flex:1; font-size:16px; font-weight:600; min-width:0;
                background:#2a2f3a; color:var(--fg); border:1px solid var(--accent);
                border-radius:8px; padding:3px 8px; outline:none; }
  .card-sub { color:var(--muted); font-size:11.5px; margin-bottom:12px; }
  .status { font-size:12.5px; color:var(--muted); margin-bottom:14px;
            min-height:18px; }
  .status.ok { color:var(--ok); } .status.err { color:var(--err); }
  .btnrow { display:flex; gap:10px; margin-bottom:20px; }
  button.btn { flex:1; border:0; border-radius:14px; padding:14px 0; font-size:15px;
               font-weight:600; cursor:pointer; color:#14161c;
               transition:filter .15s; }
  button.btn:hover { filter:brightness(1.1); }
  button.btn:active { transform:scale(.97); }
  .btn.on { background:var(--accent); }
  .btn.off { background:#3a4150; color:var(--fg); }
  .sliderlabel { display:flex; justify-content:space-between; font-size:13px;
                 color:var(--muted); margin-bottom:8px; }
  input[type=range] { -webkit-appearance:none; appearance:none; width:100%;
                      height:40px; background:transparent; touch-action:none; }
  input[type=range]::-webkit-slider-runnable-track { height:8px; border-radius:4px;
                      background:#3a4150; }
  input[type=range]::-webkit-slider-thumb { -webkit-appearance:none; appearance:none;
                      width:26px; height:26px; border-radius:50%; background:var(--accent);
                      margin-top:-9px; border:0; }
  input[type=range]::-moz-range-track { height:8px; border-radius:4px; background:#3a4150; }
  input[type=range]::-moz-range-thumb { width:26px; height:26px; border-radius:50%;
                      background:var(--accent); border:0; }
  .hint { margin-top:18px; font-size:11.5px; color:var(--muted);
          text-align:center; }
</style>
</head>
<body>
  <div class="wrap">
    <div class="head">
      <h1>Sengled Bulbs</h1>
      <div class="sub">local UDP &middot; <span id="pcs">-</span></div>
    </div>
    <div class="grid" id="grid"></div>
    <div class="hint">Add to home screen to use as an app</div>
  </div>
<script>
  const $ = (id) => document.getElementById(id);
  let bulbs = [];
  const byIp = new Map();

  async function api(path, body) {
    const opt = { method: "POST" };
    if (body !== undefined) {
      opt.headers = { "Content-Type": "application/json" };
      opt.body = JSON.stringify(body);
    }
    const r = await fetch(path, opt);
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || ("HTTP " + r.status));
    return data;
  }

  async function apiGet(path) {
    const r = await fetch(path);
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || ("HTTP " + r.status));
    return data;
  }

  function setStatus(ip, text, cls) {
    const e = byIp.get(ip);
    if (!e) return;
    e.status.textContent = text;
    e.status.className = "status" + (cls ? " " + cls : "");
  }

  function renderCards() {
    const grid = $("grid");
    grid.innerHTML = "";
    bulbs.forEach((b) => {
      const card = document.createElement("div");
      card.className = "card";
      card.dataset.ip = b.ip;

      const head = document.createElement("div");
      head.className = "card-head";

      const name = document.createElement("span");
      name.className = "name";
      name.textContent = b.name;
      name.title = b.name;

      const pencil = document.createElement("button");
      pencil.className = "pencil";
      pencil.title = "Rename bulb";
      pencil.setAttribute("aria-label", "Rename bulb");
      pencil.innerHTML =
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
        '<path d="M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>';

      head.appendChild(name);
      head.appendChild(pencil);

      const sub = document.createElement("div");
      sub.className = "card-sub";
      sub.textContent = b.ip;

      const status = document.createElement("div");
      status.className = "status";
      status.textContent = "Loading\u2026";

      const row = document.createElement("div");
      row.className = "btnrow";
      const onBtn = document.createElement("button");
      onBtn.className = "btn on";
      onBtn.textContent = "ON";
      const offBtn = document.createElement("button");
      offBtn.className = "btn off";
      offBtn.textContent = "OFF";
      row.appendChild(onBtn);
      row.appendChild(offBtn);

      const slabel = document.createElement("div");
      slabel.className = "sliderlabel";
      slabel.innerHTML = "<span>Brightness</span><span class='bval'>-</span>";

      const slider = document.createElement("input");
      slider.type = "range";
      slider.min = 1;
      slider.max = 100;
      slider.value = 100;

      card.appendChild(head);
      card.appendChild(sub);
      card.appendChild(status);
      card.appendChild(row);
      card.appendChild(slabel);
      card.appendChild(slider);
      grid.appendChild(card);

      const entry = {
        b: b, name: name, status: status,
        onBtn: onBtn, offBtn: offBtn, slider: slider,
        bval: slabel.querySelector(".bval"), editing: false,
      };
      byIp.set(b.ip, entry);

      onBtn.addEventListener("click", () => setSwitch(b.ip, true));
      offBtn.addEventListener("click", () => setSwitch(b.ip, false));
      pencil.addEventListener("click", () => startEdit(b.ip));
      slider.addEventListener("input", () => queueBrightness(b.ip));
      slider.addEventListener("change", () => sendBrightness(b.ip));
    });
  }

  function startEdit(ip) {
    const e = byIp.get(ip);
    if (!e || e.editing) return;
    e.editing = true;
    const input = document.createElement("input");
    input.className = "name-input";
    input.value = e.b.name;
    input.maxLength = 40;
    e.name.replaceWith(input);
    input.focus();
    input.select();

    let done = false;
    async function finish(save) {
      if (done) return;
      done = true;
      const value = input.value.trim();
      input.replaceWith(e.name);
      e.editing = false;
      if (save && value && value !== e.b.name) {
        try {
          await api("/api/rename", { ip: ip, name: value });
          e.b.name = value;
          e.name.textContent = value;
          e.name.title = value;
          setStatus(ip, "Name saved", "ok");
        } catch (err) {
          setStatus(ip, "Rename failed: " + err.message, "err");
        }
      }
    }
    input.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") { ev.preventDefault(); finish(true); }
      else if (ev.key === "Escape") { finish(false); }
    });
    input.addEventListener("blur", () => finish(true));
  }

  async function loadState(ip) {
    const e = byIp.get(ip);
    if (!e) return;
    try {
      const data = await apiGet("/api/state?ip=" + encodeURIComponent(ip));
      if (data.brightness !== null && data.brightness !== undefined) {
        e.slider.value = data.brightness;
        e.bval.textContent = data.brightness + "%";
      }
      setStatus(ip, data.power === "off" ? "Bulb OFF" : "Bulb ON", "ok");
    } catch (err) {
      setStatus(ip, "Bulb not reachable: " + err.message, "err");
    }
  }

  async function setSwitch(ip, on) {
    try {
      await api(on ? "/api/on" : "/api/off", { ip: ip });
      setStatus(ip, on ? "Bulb ON" : "Bulb OFF", "ok");
    } catch (e) {
      setStatus(ip, "Error: " + e.message, "err");
    }
  }

  const timers = new Map();
  function queueBrightness(ip) {
    const e = byIp.get(ip);
    if (!e) return;
    e.bval.textContent = e.slider.value + "%";
    clearTimeout(timers.get(ip));
    timers.set(ip, setTimeout(() => sendBrightness(ip), 250));
  }

  async function sendBrightness(ip) {
    const e = byIp.get(ip);
    if (!e) return;
    try {
      const v = Number(e.slider.value);
      await api("/api/brightness", { ip: ip, value: v });
      setStatus(ip, "Brightness " + v + "%", "ok");
    } catch (err) {
      setStatus(ip, "Error: " + err.message, "err");
    }
  }

  // On load: fetch bulb list, render one card per bulb, query real state
  (async () => {
    try {
      const data = await apiGet("/api/bulbs");
      bulbs = data.bulbs;
      if (!bulbs.length) throw new Error("no bulbs configured");
      $("pcs").textContent = bulbs.length + (bulbs.length === 1 ? " bulb" : " bulbs");
      renderCards();
      bulbs.forEach((b) => loadState(b.ip));
    } catch (e) {
      $("grid").innerHTML =
        "<div class='card' style='grid-column:1/-1;color:var(--err)'>" +
        "Failed to load bulbs: " + e.message + "</div>";
    }
  })();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet
        pass

    def _send(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_page(self):
        body = PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def _resolve_ip(self, data=None):
        """Resolve requested bulb ip from body/query; default to first bulb."""
        data = data or {}
        bulb_id = data.get("ip") or data.get("bulb")
        if bulb_id:
            ip = get_bulb_ip(str(bulb_id))
            if ip:
                return ip
            raise ValueError(f"unknown bulb: {bulb_id}")
        if not BULBS:
            raise ValueError("no bulbs configured")
        return BULBS[0]["ip"]

    def do_GET(self):
        try:
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(self.path)
            route = parsed.path
            qs = parse_qs(parsed.query)
            if route == "/" or route == "/index.html":
                self._send_page()
                return
            if route == "/api/bulbs":
                self._send(200, {"bulbs": BULBS})
                return
            if route == "/api/state":
                data = {"ip": qs.get("ip", [None])[0]} if qs.get("ip") else {}
                bulb_ip = self._resolve_ip(data)
                refresh_state(bulb_ip)
                self._send(200, ensure_state(bulb_ip))
                return
            self._send(404, {"error": "not found"})
        except Exception as exc:
            self._send(502, {"error": str(exc)})

    def do_POST(self):
        try:
            data = self._read_body()
            if self.path == "/api/on":
                bulb_ip = self._resolve_ip(data)
                resp = cmd_switch(bulb_ip, True)
                if not resp:
                    raise RuntimeError("no response from bulb")
                ensure_state(bulb_ip)["power"] = "on"
                self._send(200, {"ok": True, "ip": bulb_ip})
            elif self.path == "/api/off":
                bulb_ip = self._resolve_ip(data)
                resp = cmd_switch(bulb_ip, False)
                if not resp:
                    raise RuntimeError("no response from bulb")
                ensure_state(bulb_ip)["power"] = "off"
                self._send(200, {"ok": True, "ip": bulb_ip})
            elif self.path == "/api/brightness":
                bulb_ip = self._resolve_ip(data)
                value = int(data.get("value", 100))
                resp = cmd_brightness(bulb_ip, value)
                if not resp:
                    raise RuntimeError("no response from bulb")
                st = ensure_state(bulb_ip)
                st["brightness"] = value
                st["power"] = "on" if value > 0 else st.get("power", "on")
                self._send(200, {"ok": True, "brightness": value, "ip": bulb_ip})
            elif self.path == "/api/rename":
                bulb_ip = self._resolve_ip(data)
                name = str(data.get("name", "")).strip()
                if not name:
                    raise ValueError("name is required")
                if len(name) > 40:
                    raise ValueError("name too long (max 40)")
                for b in BULBS:
                    if b["ip"] == bulb_ip:
                        b["name"] = name
                        break
                save_panel_config()
                self._send(200, {"ok": True, "name": name, "ip": bulb_ip})
            else:
                self._send(404, {"error": "not found"})
        except Exception as exc:
            self._send(502, {"error": str(exc)})


# ---------------------------------------------------------------------------

def main():
    global BULBS
    parser = argparse.ArgumentParser(description="Sengled UDP web control panel (multi-bulb)")
    parser.add_argument("--ip", default=None,
                        help="Single bulb IP (backward compatible; overrides defaults)")
    parser.add_argument("--bulb", action="append", default=None, metavar="NAME=IP",
                        help="Add a bulb as NAME=IP (repeatable). "
                             "Defaults to the known bulbs if neither --ip nor --bulb given.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("SENGLED_WEB_PORT", "8000")),
                        help="HTTP port (default: 8000)")
    args = parser.parse_args()

    if args.ip:
        BULBS = [{"name": args.ip, "ip": args.ip}]
    elif args.bulb:
        BULBS = []
        for item in args.bulb:
            if "=" in item:
                name, ip = item.split("=", 1)
            else:
                name, ip = item, item
            BULBS.append({"name": name.strip(), "ip": ip.strip()})
    else:
        BULBS = [dict(b) for b in DEFAULT_BULBS]

    # Apply persisted names (by IP) and create the config file on first run.
    saved = load_panel_config()
    for b in BULBS:
        if b["ip"] in saved:
            b["name"] = saved[b["ip"]]
    save_panel_config()

    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"Sengled web panel on http://0.0.0.0:{args.port}  (bulbs: {len(BULBS)})")
    for b in BULBS:
        print(f"  - {b['name']} @ {b['ip']}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

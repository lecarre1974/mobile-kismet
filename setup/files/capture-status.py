#!/usr/bin/env python3
"""Status page, survey tables, downloads and capture controls.

Runs only during a check-in (started by checkin-toggle.sh). No external assets:
the check-in network has no internet.
"""
import json
import os
import shutil
import socket
import subprocess
import tarfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = "/var/lib/capture"
RUN = "/run/capture"
CHECKIN = "/run/checkin"
PORTS = (80, 8080)
ALLOWED_EXT = (".pcap", ".csv")
SUDO = "/usr/bin/sudo"
ACTIONS = {
    "capture/start": [SUDO, "-n", "/usr/bin/systemctl", "start", "wifi-capture.service"],
    "capture/stop": [SUDO, "-n", "/usr/bin/systemctl", "stop", "wifi-capture.service"],
    "checkin/off": [SUDO, "-n", "/usr/local/bin/checkin-toggle.sh", "off-async"],
    "checkin/extend": [SUDO, "-n", "/usr/local/bin/checkin-toggle.sh", "extend"],
    "focus/clear": [SUDO, "-n", "/usr/local/bin/focus-control.sh", "clear"],
}
MAC_RE = __import__("re").compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
ACTIVE_SECS = 300


def read(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def run(cmd, timeout=5):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)


def run_input(cmd, text, timeout=25):
    try:
        p = subprocess.run(cmd, input=text, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)


def pisugar(cmd):
    try:
        with socket.create_connection(("127.0.0.1", 8423), timeout=1.5) as s:
            s.sendall((cmd + "\n").encode())
            data = s.recv(200).decode(errors="replace")
        return data.strip().split(": ", 1)[-1]
    except OSError:
        return None


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def to_int(v, default=0):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


def current_freq(iface):
    if not iface:
        return None
    _, out = run(["/usr/sbin/iw", "dev", iface, "info"], timeout=3)
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("channel "):
            try:
                ch = int(line.split()[1])
                mhz = int(line.split("(")[1].split()[0])
                return {"channel": ch, "mhz": mhz}
            except (IndexError, ValueError):
                return None
    return None


def meminfo():
    vals = {}
    for line in read("/proc/meminfo").splitlines():
        k, _, rest = line.partition(":")
        vals[k] = to_int(rest.split()[0]) if rest.split() else 0
    return vals.get("MemTotal", 0) * 1024, vals.get("MemAvailable", 0) * 1024


def dir_stats(path):
    count, size = 0, 0
    try:
        with os.scandir(path) as it:
            for e in it:
                if e.is_file() and e.name.endswith(".pcap"):
                    count += 1
                    size += e.stat().st_size
    except OSError:
        pass
    return count, size


def status():
    iface = read(f"{RUN}/iface")
    session = read(f"{RUN}/session")
    pcaps, pcap_bytes = dir_stats(session) if session else (0, 0)
    disk = shutil.disk_usage(BASE)
    total_bytes = 0
    for root, _, files in os.walk(BASE):
        for f in files:
            try:
                total_bytes += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    expires = read(f"{CHECKIN}/expires")
    mem_total, mem_avail = meminfo()
    _, active = run(["/usr/bin/systemctl", "is-active", "wifi-capture.service"], timeout=3)
    _, throttled = run(["/usr/bin/vcgencmd", "get_throttled"], timeout=3)
    session_started = None
    if session:
        try:
            session_started = int(time.mktime(time.strptime(os.path.basename(session), "%Y%m%d-%H%M%S")))
        except ValueError:
            pass
    return {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "now": int(time.time()),
        "service": active,
        "state": read(f"{RUN}/state", "unknown"),
        "warning": read(f"{RUN}/warning"),
        "focus": read(f"{RUN}/focus"),
        "focus_targets": [l.split(" ", 1) for l in read(f"{RUN}/focus-targets").splitlines() if " " in l],
        "session": os.path.basename(session),
        "session_started": session_started,
        "iface": iface,
        "freq": current_freq(iface),
        "hop": read(f"{RUN}/hop"),
        "rx_packets": to_int(read(f"/sys/class/net/{iface}/statistics/rx_packets", "0")) if iface else 0,
        "rx_bytes": to_int(read(f"/sys/class/net/{iface}/statistics/rx_bytes", "0")) if iface else 0,
        "pcaps": pcaps,
        "pcap_bytes": pcap_bytes,
        "stored_bytes": total_bytes,
        "disk_free": disk.free,
        "disk_total": disk.total,
        "battery": to_float(pisugar("get battery")),
        "battery_v": to_float(pisugar("get battery_v")),
        "charging": pisugar("get battery_charging"),
        "plugged": pisugar("get battery_power_plugged"),
        "cpu_temp": to_int(read("/sys/class/thermal/thermal_zone0/temp", "0")) / 1000,
        "load": read("/proc/loadavg").split()[:3],
        "mem_total": mem_total,
        "mem_avail": mem_avail,
        "throttled": throttled.split("=")[-1] if "=" in throttled else None,
        "uptime": int(float(read("/proc/uptime", "0 0").split()[0])),
        "auto_off_at": int(expires) if expires.isdigit() else None,
    }


_survey_lock = threading.Lock()
_survey_cache = {"key": None, "data": None}


def parse_time(s):
    try:
        return int(time.mktime(time.strptime(s.strip(), "%Y-%m-%d %H:%M:%S")))
    except ValueError:
        return None


def parse_survey(path):
    aps, stations, section = [], [], None
    with open(path, errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("BSSID,"):
                section = "ap"
                continue
            if line.startswith("Station MAC,"):
                section = "sta"
                continue
            parts = [p.strip() for p in line.split(",")]
            if section == "ap" and len(parts) >= 14:
                essid = ",".join(parts[13:-1]).strip() if len(parts) >= 15 else parts[13]
                essid = essid.replace("\x00", "")
                aps.append({
                    "bssid": parts[0], "first": parse_time(parts[1]), "last": parse_time(parts[2]),
                    "channel": to_int(parts[3], -1), "speed": to_int(parts[4], -1),
                    "privacy": parts[5] or "?", "cipher": parts[6], "auth": parts[7],
                    "power": to_int(parts[8], -1), "beacons": to_int(parts[9]), "data": to_int(parts[10]),
                    "essid": essid, "hidden": not essid,
                })
            elif section == "sta" and len(parts) >= 6:
                probes = [p for p in (",".join(parts[6:]).split(",") if len(parts) > 6 else []) if p.strip()]
                bssid = parts[5]
                stations.append({
                    "mac": parts[0], "first": parse_time(parts[1]), "last": parse_time(parts[2]),
                    "power": to_int(parts[3], -1), "packets": to_int(parts[4]),
                    "bssid": None if bssid.startswith("(not") else bssid,
                    "probes": [p.strip() for p in probes],
                })
    return aps, stations


def survey():
    session = read(f"{RUN}/session")
    path = os.path.join(session, "summary-01.csv") if session else ""
    try:
        key = (path, os.path.getmtime(path), os.path.getsize(path))
    except OSError:
        return {"available": False}
    with _survey_lock:
        if _survey_cache["key"] == key:
            return _survey_cache["data"]
        aps, stations = parse_survey(path)
        now = int(time.time())
        names = {a["bssid"]: a["essid"] for a in aps}
        clients = {}
        for s in stations:
            if s["bssid"]:
                clients[s["bssid"]] = clients.get(s["bssid"], 0) + 1
            s["network"] = names.get(s["bssid"]) if s["bssid"] else None
        channels, privacy = {}, {}
        for a in aps:
            a["clients"] = clients.get(a["bssid"], 0)
            if a["channel"] > 0:
                channels[a["channel"]] = channels.get(a["channel"], 0) + 1
            privacy[a["privacy"]] = privacy.get(a["privacy"], 0) + 1
        active = lambda x: x["last"] is not None and now - x["last"] <= ACTIVE_SECS
        aps.sort(key=lambda a: (a["power"] in (-1, 0), -a["power"] if a["power"] not in (-1, 0) else 0))
        stations.sort(key=lambda s: -(s["last"] or 0))
        data = {
            "available": True,
            "updated": int(key[1]),
            "ap_total": len(aps),
            "ap_active": sum(1 for a in aps if active(a)),
            "sta_total": len(stations),
            "sta_active": sum(1 for s in stations if active(s)),
            "sta_associated": sum(1 for s in stations if s["bssid"]),
            "hidden": sum(1 for a in aps if a["hidden"]),
            "channels": channels,
            "privacy": privacy,
            "aps": aps[:300],
            "stations": stations[:300],
        }
        _survey_cache.update(key=key, data=data)
        return data


def file_list():
    sessions = []
    try:
        names = sorted(os.listdir(BASE), reverse=True)
    except OSError:
        return sessions
    current = os.path.basename(read(f"{RUN}/session"))
    for name in names:
        path = os.path.join(BASE, name)
        if not os.path.isdir(path):
            continue
        files, total = [], 0
        for f in sorted(os.listdir(path), reverse=True):
            full = os.path.join(path, f)
            if f.endswith(ALLOWED_EXT) and os.path.isfile(full):
                size = os.path.getsize(full)
                total += size
                files.append({"name": f, "size": size})
        sessions.append({"session": name, "files": files, "size": total, "current": name == current})
    return sessions


def safe_name(s):
    return bool(s) and "/" not in s and "\\" not in s and not s.startswith(".")


PAGE = r"""<!doctype html><html lang=en><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Capture Status</title>
<style>
:root{--bg:#0e1114;--card:#171b20;--card2:#1e242b;--line:#2a323b;--text:#e8ecf1;--dim:#8f9cab;
--ok:#3fcf8e;--bad:#ff6b6b;--warn:#f2c14e;--accent:#6aa9ff;--bar:#3b82f6}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.4 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;padding:16px}
main{max-width:980px;margin:auto}header{display:flex;justify-content:space-between;align-items:baseline;gap:8px;flex-wrap:wrap}
h1{font-size:20px;margin:0}h2{font-size:15px;margin:0 0 10px;color:var(--dim);font-weight:600;text-transform:uppercase;letter-spacing:.04em}
.clock{color:var(--dim);font-size:13px}.card{background:var(--card);border-radius:12px;padding:14px;margin-top:12px}
.banner{display:flex;gap:12px;align-items:center;flex-wrap:wrap;border-left:6px solid var(--dim)}
.banner.ok{border-color:var(--ok)}.banner.bad{border-color:var(--bad)}.banner.warn{border-color:var(--warn)}
.dot{width:12px;height:12px;border-radius:50%;background:var(--dim);flex:none}.ok .dot{background:var(--ok);box-shadow:0 0 0 4px #3fcf8e33}
.bad .dot{background:var(--bad)}.warn .dot{background:var(--warn)}
.state{font-size:20px;font-weight:700}.sub{color:var(--dim);font-size:13px}.grow{flex:1;min-width:160px}
.btns{display:flex;gap:8px;flex-wrap:wrap}button{font:inherit;font-weight:600;border:0;border-radius:9px;padding:10px 14px;background:var(--card2);color:var(--text);cursor:pointer}
button.go{background:#1f6f4a}button.stop{background:#7a2a2a}button:disabled{opacity:.5}
.note{border-left:6px solid var(--warn);display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.kpis{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin-top:12px}
.kpi{background:var(--card);border-radius:12px;padding:12px}.kpi b{display:block;font-size:22px;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.kpi span{font-size:12px;color:var(--dim)}.two{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
.two .card{margin-top:12px}svg{display:block;width:100%}.bars{display:flex;align-items:flex-end;gap:2px;height:90px;border-bottom:1px solid var(--line)}
.bars div{flex:1;background:var(--bar);border-radius:2px 2px 0 0;min-height:1px}.axis{display:flex;justify-content:space-between;font-size:11px;color:var(--dim);margin-top:4px}
.mix div{display:flex;align-items:center;gap:8px;font-size:13px;margin:4px 0}.mix i{display:block;height:10px;background:var(--bar);border-radius:3px}
.mix span{width:110px;flex:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.mix em{color:var(--dim);font-style:normal;margin-left:auto}
input[type=search]{width:100%;font:inherit;padding:9px 11px;border-radius:9px;border:1px solid var(--line);background:var(--card2);color:var(--text);margin-bottom:8px}
.tbl{overflow-x:auto;max-height:420px;overflow-y:auto;border-radius:8px}table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);white-space:nowrap}th{position:sticky;top:0;background:var(--card);color:var(--dim);font-weight:600;cursor:pointer}
td.wrap{white-space:normal;min-width:140px}.mono{font-family:ui-monospace,Menlo,monospace;font-size:12px}.dimtxt{color:var(--dim)}
.sig{display:inline-block;width:38px;height:6px;background:var(--line);border-radius:3px;vertical-align:middle;margin-right:6px;overflow:hidden}.sig i{display:block;height:100%;background:var(--ok)}
.tag{display:inline-block;padding:1px 6px;border-radius:5px;background:var(--card2);font-size:12px}.tag.open{background:#5a2323}.tag.wep{background:#5a4423}
details{border-top:1px solid var(--line);padding:8px 0}details:first-of-type{border-top:0}summary{cursor:pointer;display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap}
ul{list-style:none;margin:8px 0 0;padding:0}li{display:flex;justify-content:space-between;gap:10px;padding:5px 0;font-size:13px}
a{color:var(--accent);overflow-wrap:anywhere}.sys{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px;font-size:13px}
.sys div span{display:block;color:var(--dim);font-size:12px}.err{color:var(--bad)}
</style>
<main>
<header><h1>Capture Status</h1><div class=clock id=clock></div></header>
<section class="card banner" id=banner><div class=dot></div><div class=grow><div class=state id=state>Loading&hellip;</div><div class=sub id=statesub></div></div>
<div class=btns><button id=btnStart class=go hidden>Start capture</button><button id=btnStop class=stop hidden>Stop capture</button></div></section>
<section class="card note" id=note hidden><div class=grow><b>This unit is transmitting.</b> <span id=notetxt></span></div>
<div class=btns><button id=btnExtend>Extend 10 min</button><button id=btnEnd class=stop>End check-in now</button></div></section>
<div class=kpis id=kpis></div>
<div class=two>
<section class=card><h2>Packets per second</h2><svg id=spark viewBox="0 0 300 90" preserveAspectRatio=none height=90></svg><div class=axis><span>5 min ago</span><span id=sparkmax></span><span>now</span></div></section>
<section class=card><h2>Networks per channel</h2><div class=bars id=chbars></div><div class=axis id=chaxis></div></section>
</div>
<div class=two>
<section class=card><h2>Encryption</h2><div class=mix id=mix></div></section>
<section class=card><h2>System</h2><div class=sys id=sys></div></section>
</div>
<section class=card><h2>Focus</h2>
<div id=focusnow class=sub style="margin-bottom:8px">Capturing all channels.</div>
<div class=btns style="margin-bottom:8px"><button id=btnFocusSel class=go>Focus on selected</button><button id=btnFocusAll hidden>Back to all channels</button></div>
<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center"><select id=addkind style="font:inherit;padding:9px;border-radius:9px;border:1px solid var(--line);background:var(--card2);color:var(--text)"><option value=ssid>SSID name</option><option value=bssid>BSSID (MAC)</option></select>
<input id=addval style="flex:1;min-width:160px;font:inherit;padding:9px 11px;border-radius:9px;border:1px solid var(--line);background:var(--card2);color:var(--text)" placeholder="Type a name or AA:BB:CC:DD:EE:FF, press Add">
<button id=btnAdd>Add to focus</button></div>
<div id=pending class=sub style="margin-top:8px"></div></section>
<section class=card><h2>Networks <span id=apcount class=dimtxt></span></h2><input type=search id=apq placeholder="Filter by name, address, channel, encryption">
<div class=tbl><table><thead><tr><th style="width:28px"><input type=checkbox id=apall title="Select all shown"></th><th data-k=essid>Name</th><th data-k=power>Signal</th><th data-k=channel>Ch</th><th data-k=privacy>Security</th><th data-k=clients>Devices</th><th data-k=data>Data</th><th data-k=bssid>Address</th><th data-k=last>Last seen</th></tr></thead><tbody id=aps></tbody></table></div></section>
<section class=card><h2>Devices <span id=stacount class=dimtxt></span></h2><input type=search id=staq placeholder="Filter by address, network, searched-for name">
<div class=tbl><table><thead><tr><th data-k=mac>Address</th><th data-k=power>Signal</th><th data-k=packets>Packets</th><th data-k=network>Connected to</th><th data-k=probes>Searching for</th><th data-k=last>Last seen</th></tr></thead><tbody id=stas></tbody></table></div></section>
<section class=card><h2>Sessions &amp; files</h2><div id=files class=dimtxt>Loading&hellip;</div></section>
</main>
<script>
const $=id=>document.getElementById(id);
function el(t,p,...k){const e=document.createElement(t);if(p)for(const[a,v]of Object.entries(p)){if(a==="text")e.textContent=v;else if(a==="cls")e.className=v;else if(a==="style")e.style.cssText=v;else e.setAttribute(a,v)}for(const c of k)if(c!=null)e.append(c);return e}
const size=b=>{if(b==null)return"-";const u=["B","KB","MB","GB","TB"];let i=0;while(b>=1024&&i<4){b/=1024;i++}return b.toFixed(i?1:0)+" "+u[i]};
const dur=s=>{if(s==null||s<0)return"-";const d=Math.floor(s/86400),h=Math.floor(s%86400/3600),m=Math.floor(s%3600/60);return d?d+"d "+h+"h":h?h+"h "+m+"m":m+"m "+Math.floor(s%60)+"s"};
const ago=(t,now)=>t?dur(now-t)+" ago":"-";
const band=f=>!f?"-":f.mhz<3000?"2.4 GHz":f.mhz<5900?"5 GHz":"6 GHz";
const LABEL={capturing:"Capturing","waiting-for-adapter":"Waiting for adapter","no-adapter":"Adapter not found","adapter-error":"Adapter error","disk-full":"SD card full",restarting:"Restarting capture",stopped:"Capture stopped"};
let hist=[],last=null,S=null,V=null,now=0,sel=new Set(),curTargets=[];
async function postJSON(a,obj,q){if(q&&!confirm(q))return;try{const r=await fetch("/api/"+a,{method:"POST",headers:{"X-Requested-With":"capture-ui","Content-Type":"application/json"},body:JSON.stringify(obj)});const j=await r.json();if(!j.ok)alert("Failed: "+j.output);}catch(e){}setTimeout(tick,1500)}
$("btnFocusSel").onclick=()=>{if(!sel.size)return alert("Tick one or more networks first.");postJSON("focus/set",{targets:[...sel].map(v=>({type:"bssid",value:v}))},"Focus the radio on "+sel.size+" selected network(s)? It will dwell on their channels only. Power-cycle returns to all channels.")};
$("btnFocusAll").onclick=()=>postJSON("focus/clear",{},"Go back to scanning all channels?");
$("btnAdd").onclick=()=>{const k=$("addkind").value,v=$("addval").value.trim();if(!v)return;if(k==="bssid"&&!/^([0-9a-f]{2}:){5}[0-9a-f]{2}$/i.test(v))return alert("Enter a MAC like AA:BB:CC:DD:EE:FF");const t=curTargets.map(([kind,val])=>({type:kind,value:val}));t.push({type:k,value:v});$("addval").value="";postJSON("focus/set",{targets:t})};
$("addval").addEventListener("keydown",e=>{if(e.key==="Enter")$("btnAdd").click()});
$("apall").onchange=e=>{const rows=V?V.aps:[];const aq=$("apq").value.toLowerCase();rows.filter(a=>!aq||[a.essid,a.bssid,a.privacy,String(a.channel)].join(" ").toLowerCase().includes(aq)).forEach(a=>{if(e.target.checked)sel.add(a.bssid);else sel.delete(a.bssid)});render()};
async function post(a,q){if(q&&!confirm(q))return;try{const r=await fetch("/api/"+a,{method:"POST",headers:{"X-Requested-With":"capture-ui"}});const j=await r.json();if(!j.ok)alert("Failed: "+j.output);}catch(e){}setTimeout(tick,1500)}
$("btnStart").onclick=()=>post("capture/start","Start capturing now?");
$("btnStop").onclick=()=>post("capture/stop","Stop capturing? It stays stopped until you press Start or power-cycle the unit.");
$("btnExtend").onclick=()=>post("checkin/extend");
$("btnEnd").onclick=()=>post("checkin/off","End check-in? This page will go offline and the unit goes silent.");
function kpi(v,l){return el("div",{cls:"kpi"},el("b",{text:v}),el("span",{text:l}))}
function spark(){const svg=$("spark");svg.replaceChildren();if(hist.length<2)return;const mx=Math.max(1,...hist);const pts=hist.map((v,i)=>(i/(60-1)*300).toFixed(1)+","+(88-v/mx*84).toFixed(1));const off=60-hist.length;const shift=p=>{const[x,y]=p.split(",");return(+x+off/(60-1)*300).toFixed(1)+","+y};const s=pts.map(shift);
const ns="http://www.w3.org/2000/svg";const a=document.createElementNS(ns,"polygon");a.setAttribute("points",s[0].split(",")[0]+",90 "+s.join(" ")+" 300,90");a.setAttribute("fill","#3b82f633");const l=document.createElementNS(ns,"polyline");l.setAttribute("points",s.join(" "));l.setAttribute("fill","none");l.setAttribute("stroke","#6aa9ff");l.setAttribute("stroke-width","2");l.setAttribute("vector-effect","non-scaling-stroke");svg.append(a,l);$("sparkmax").textContent="peak "+Math.round(mx)+"/s"}
function throttle(h){if(h==null)return"unknown";const v=parseInt(h,16);if(!v)return"OK";const m=[];if(v&1)m.push("low voltage now");if(v&4)m.push("throttled now");if(v&0x10000)m.push("low voltage earlier");if(v&0x40000)m.push("throttled earlier");return m.join(", ")||h}
async function tick(){try{const d=await(await fetch("/api/status")).json();S=d;now=d.now;$("clock").textContent=d.time;
let rate=null;if(last&&d.now>last.now){rate=Math.max(0,(d.rx_packets-last.rx_packets)/(d.now-last.now));hist.push(rate);if(hist.length>60)hist.shift()}
let brate=null;if(last&&d.now>last.now)brate=Math.max(0,(d.pcap_bytes-last.pcap_bytes)/(d.now-last.now));last=d;
const ok=d.state==="capturing"&&d.service==="active";const starting=["waiting-for-adapter","restarting"].includes(d.state)&&d.service==="active";
$("banner").className="card banner "+(ok&&!d.warning?"ok":(ok||starting)?"warn":"bad");$("state").textContent=d.service!=="active"?"Capture stopped":(LABEL[d.state]||d.state)+(ok&&d.warning?" - needs attention: "+d.warning:"");
$("statesub").textContent=d.session?"Session "+d.session+(d.session_started?" - running "+dur(d.now-d.session_started):""):"";
$("btnStart").hidden=d.service==="active";$("btnStop").hidden=d.service!=="active";
if(d.auto_off_at){$("note").hidden=false;$("notetxt").textContent="Check-in switches off in "+dur(d.auto_off_at-d.now)+"."}else $("note").hidden=true;
curTargets=d.focus_targets||[];const foc=curTargets.length>0;$("btnFocusAll").hidden=!foc;
$("focusnow").textContent=foc?(d.focus||"Focusing..."):"Capturing all channels (default). Tick networks below or add one, then Focus.";
$("pending").textContent=foc?"Targets: "+curTargets.map(t=>t[1]).join(", "):"";
const left=brate&&brate>0?dur(d.disk_free/brate):"-";
$("kpis").replaceChildren(kpi(d.freq?band(d.freq)+" ch "+d.freq.channel:"-","Listening on"),kpi(rate==null?"-":rate.toFixed(0),"Packets per second"),kpi(d.rx_packets.toLocaleString(),"Packets received"),kpi(size(d.pcap_bytes),d.pcaps+" pcap files this session"),
kpi(V?V.ap_active+" / "+V.ap_total:"-","Networks (active / total)"),kpi(V?V.sta_active+" / "+V.sta_total:"-","Devices (active / total)"),kpi(size(d.disk_free),"SD free, about "+left+" left"),kpi(d.battery!=null?Math.round(d.battery)+"%":"-",d.plugged==="true"?"Battery, charger connected":"Battery"));
spark();
const memUsed=d.mem_total-d.mem_avail;
$("sys").replaceChildren(...[["Battery",d.battery!=null?Math.round(d.battery)+"% at "+(d.battery_v||0).toFixed(2)+" V":"-"],["Charging",d.charging==="true"?"yes":"no"],["CPU temperature",d.cpu_temp.toFixed(1)+" C"],["Load (1/5/15 min)",d.load.join(" / ")],["Memory used",size(memUsed)+" of "+size(d.mem_total)],["Power warnings",throttle(d.throttled)],["Powered on for",dur(d.uptime)],["Capture adapter",d.iface||"-"],["Channels hopped",d.hop||"-"],["Stored on SD",size(d.stored_bytes)]].map(([k,v])=>el("div",null,el("span",{text:k}),v)));
}catch(e){$("banner").className="card banner bad";$("state").textContent="Lost connection to the unit";$("statesub").textContent="Check you are still on the unit's Wi-Fi."}}
let apSort={k:"power",d:-1},staSort={k:"last",d:-1};
function sorter(s){return(a,b)=>{let x=a[s.k],y=b[s.k];if(Array.isArray(x))x=x.join(",");if(Array.isArray(y))y=y.join(",");if(x==null)x="";if(y==null)y="";if(s.k==="power"){x=x===-1?-999:x;y=y===-1?-999:y}return(x>y?1:x<y?-1:0)*s.d}}
document.querySelectorAll("th[data-k]").forEach(th=>th.onclick=()=>{const t=th.closest("table").querySelector("tbody").id==="aps"?apSort:staSort;if(t.k===th.dataset.k)t.d*=-1;else{t.k=th.dataset.k;t.d=-1}render()});
$("apq").oninput=render;$("staq").oninput=render;
function sig(p){if(p==null||p===-1||p===0)return el("span",{cls:"dimtxt",text:"-"});const pct=Math.max(0,Math.min(100,(p+95)*100/65));return el("span",null,el("span",{cls:"sig"},el("i",{style:"width:"+pct+"%"})),p+" dBm")}
function sec(p){const c=/OPN/.test(p)?"tag open":/WEP/.test(p)?"tag wep":"tag";return el("span",{cls:c,text:p.trim()==="OPN"?"Open":p})}
function render(){if(!V||!V.available){$("aps").replaceChildren(el("tr",null,el("td",{colspan:8,cls:"dimtxt",text:"Waiting for the first survey results (about 30 seconds after capture starts)."})));return}
const aq=$("apq").value.toLowerCase(),sq=$("staq").value.toLowerCase();
const aps=V.aps.filter(a=>!aq||[a.essid,a.bssid,a.privacy,String(a.channel)].join(" ").toLowerCase().includes(aq)).sort(sorter(apSort));
$("apcount").textContent="("+aps.length+(V.ap_total>V.aps.length?" of "+V.ap_total:"")+")";
$("aps").replaceChildren(...aps.map(a=>{const cb=el("input",{type:"checkbox"});cb.checked=sel.has(a.bssid);cb.onchange=()=>{cb.checked?sel.add(a.bssid):sel.delete(a.bssid)};return el("tr",null,el("td",null,cb),el("td",{cls:"wrap"},a.hidden?el("span",{cls:"dimtxt",text:"(hidden)"}):a.essid),el("td",null,sig(a.power)),el("td",{text:a.channel}),el("td",null,sec(a.privacy)),el("td",{text:a.clients}),el("td",{text:a.data.toLocaleString()}),el("td",{cls:"mono",text:a.bssid}),el("td",{cls:"dimtxt",text:ago(a.last,now)}))}));
const st=V.stations.filter(s=>!sq||[s.mac,s.network,s.bssid,s.probes.join(" ")].join(" ").toLowerCase().includes(sq)).sort(sorter(staSort));
$("stacount").textContent="("+st.length+(V.sta_total>V.stations.length?" of "+V.sta_total:"")+")";
$("stas").replaceChildren(...st.map(s=>el("tr",null,el("td",{cls:"mono",text:s.mac}),el("td",null,sig(s.power)),el("td",{text:s.packets.toLocaleString()}),el("td",{cls:"wrap"},s.bssid?(s.network||el("span",{cls:"mono",text:s.bssid})):el("span",{cls:"dimtxt",text:"not connected"})),el("td",{cls:"wrap",text:s.probes.join(", ")}),el("td",{cls:"dimtxt",text:ago(s.last,now)}))));
const ch=V.channels,keys=Object.keys(ch).map(Number).sort((a,b)=>a-b),mx=Math.max(1,...keys.map(k=>ch[k]));
$("chbars").replaceChildren(...keys.map(k=>el("div",{title:"ch "+k+": "+ch[k],style:"height:"+(ch[k]/mx*100)+"%"})));
$("chaxis").replaceChildren(el("span",{text:keys.length?"ch "+keys[0]:"no networks yet"}),el("span",{text:keys.length?keys.length+" channels in use":""}),el("span",{text:keys.length?"ch "+keys[keys.length-1]:""}));
const pv=Object.entries(V.privacy).sort((a,b)=>b[1]-a[1]),pm=Math.max(1,...pv.map(p=>p[1]));
$("mix").replaceChildren(...pv.map(([k,v])=>el("div",null,el("span",{text:k.trim()==="OPN"?"Open":k}),el("i",{style:"width:"+Math.max(4,v/pm*55)+"%"}),el("em",{text:v}))))}
async function survey(){try{V=await(await fetch("/api/survey")).json();render()}catch(e){}}
function delFile(session,name){postJSON("files/delete",{session,name},'Delete "'+name+'"? This cannot be undone.');setTimeout(files,1600)}
function delSession(session){postJSON("files/delete",{session},'Delete the whole session "'+session+'" and all its files? This cannot be undone.');setTimeout(files,1600)}
async function files(){try{const s=await(await fetch("/api/files")).json();const w=$("files");w.className="";w.replaceChildren();if(!s.length){w.className="dimtxt";w.textContent="No captures yet.";return}
s.forEach((x,i)=>{const delBtn=el("button",{cls:"stop",style:"padding:6px 10px"},"Delete session");delBtn.disabled=x.current;delBtn.onclick=()=>delSession(x.session);
const d=el("details",i===0?{open:""}:null,el("summary",null,el("span",{text:x.session+(x.current?" (recording)":"")}),el("span",{cls:"dimtxt",text:x.files.length+" files, "+size(x.size)})),
el("div",{style:"margin:8px 0;display:flex;gap:8px;flex-wrap:wrap"},el("a",{href:"/download/"+encodeURIComponent(x.session)+".tar",text:"Download whole session (.tar)"}),delBtn),
el("ul",null,...x.files.map(f=>{const db=el("button",{style:"padding:3px 8px;font-size:12px"},"Delete");db.onclick=()=>delFile(x.session,f.name);return el("li",null,el("a",{href:"/files/"+encodeURIComponent(x.session)+"/"+encodeURIComponent(f.name),text:f.name}),el("span",{style:"display:flex;gap:10px;align-items:center"},el("span",{cls:"dimtxt",text:size(f.size)}),db))})));w.append(d)})}catch(e){}}
tick();survey();files();setInterval(tick,5000);setInterval(survey,15000);setInterval(files,30000);
</script></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "status"
    sys_version = ""

    def log_message(self, *args):
        pass

    def send_body(self, body, ctype, code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, obj, code=200):
        self.send_body(json.dumps(obj).encode(), "application/json", code)

    def send_file(self, session, name):
        if not (safe_name(session) and safe_name(name) and name.endswith(ALLOWED_EXT)):
            return self.send_error(404)
        base = os.path.realpath(BASE)
        path = os.path.realpath(os.path.join(base, session, name))
        if not path.startswith(base + os.sep) or not os.path.isfile(path):
            return self.send_error(404)
        size = os.path.getsize(path)
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        self.end_headers()
        with open(path, "rb") as f:
            shutil.copyfileobj(f, self.wfile, 65536)

    def send_session_tar(self, session):
        if not safe_name(session):
            return self.send_error(404)
        base = os.path.realpath(BASE)
        path = os.path.realpath(os.path.join(base, session))
        if not path.startswith(base + os.sep) or not os.path.isdir(path):
            return self.send_error(404)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-tar")
        self.send_header("Content-Disposition", f'attachment; filename="{session}.tar"')
        self.send_header("Connection", "close")
        self.end_headers()
        with tarfile.open(fileobj=self.wfile, mode="w|") as tar:
            for f in sorted(os.listdir(path)):
                full = os.path.join(path, f)
                if f.endswith(ALLOWED_EXT) and os.path.isfile(full):
                    tar.add(full, arcname=f"{session}/{f}")

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        try:
            if path == "/":
                self.send_body(PAGE.encode(), "text/html; charset=utf-8")
            elif path in ("/api/status", "/status.json"):
                self.send_json(status())
            elif path == "/api/survey":
                self.send_json(survey())
            elif path in ("/api/files", "/files.json"):
                self.send_json(file_list())
            elif path.startswith("/files/"):
                parts = [urllib.parse.unquote(p) for p in path[len("/files/"):].split("/")]
                if len(parts) == 2:
                    self.send_file(*parts)
                else:
                    self.send_error(404)
            elif path.startswith("/download/") and path.endswith(".tar"):
                self.send_session_tar(urllib.parse.unquote(path[len("/download/"):-len(".tar")]))
            else:
                self.send_error(404)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def read_body(self, limit=65536):
        try:
            n = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return b""
        return self.rfile.read(min(n, limit)) if n > 0 else b""

    def delete_target(self, session, name):
        base = os.path.realpath(BASE)
        if not safe_name(session):
            return False, "bad session"
        if name is not None and not (safe_name(name) and name.endswith(ALLOWED_EXT)):
            return False, "bad file"
        if os.path.basename(read(f"{RUN}/session")) == session and name is None:
            return False, "cannot delete the session that is recording"
        target = os.path.realpath(os.path.join(base, session, name) if name else os.path.join(base, session))
        if not target.startswith(base + os.sep) or not os.path.exists(target):
            return False, "not found"
        try:
            if name:
                os.remove(target)
            else:
                shutil.rmtree(target)
        except OSError as e:
            return False, str(e)
        return True, "deleted"

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        action = path[len("/api/"):] if path.startswith("/api/") else ""
        if self.headers.get("X-Requested-With") != "capture-ui":
            return self.send_json({"ok": False, "output": "not allowed"}, 403)
        if action in ACTIONS:
            code, out = run(ACTIONS[action], timeout=25)
            return self.send_json({"ok": code == 0, "output": out[-300:]})
        if action == "focus/set":
            try:
                body = json.loads(self.read_body() or b"{}")
                targets = body.get("targets", [])
            except (ValueError, AttributeError):
                return self.send_json({"ok": False, "output": "bad request"}, 400)
            lines = []
            for t in targets[:32]:
                kind, val = t.get("type"), (t.get("value") or "").strip()
                if kind == "bssid" and MAC_RE.match(val):
                    lines.append(f"bssid {val.upper()}")
                elif kind == "ssid" and 1 <= len(val) <= 32:
                    lines.append("ssid " + "".join(c for c in val if ord(c) >= 32))
            if not lines:
                return self.send_json({"ok": False, "output": "no valid targets"}, 400)
            code, out = run_input([SUDO, "-n", "/usr/local/bin/focus-control.sh", "set"],
                                  "\n".join(lines) + "\n")
            return self.send_json({"ok": code == 0, "output": out[-300:]})
        if action == "files/delete":
            try:
                body = json.loads(self.read_body() or b"{}")
            except ValueError:
                return self.send_json({"ok": False, "output": "bad request"}, 400)
            ok, msg = self.delete_target(body.get("session", ""), body.get("name"))
            return self.send_json({"ok": ok, "output": msg})
        self.send_json({"ok": False, "output": "unknown action"}, 404)


if __name__ == "__main__":
    # Port 80 lets phones load http://10.42.0.1 directly. Browsers that try
    # HTTPS first find nothing on 443 and fall back to plain HTTP.
    servers = []
    for port in PORTS:
        try:
            servers.append(ThreadingHTTPServer(("0.0.0.0", port), Handler))
        except OSError as e:
            print(f"cannot listen on {port}: {e}", flush=True)
    if not servers:
        raise SystemExit("no listening ports")
    for s in servers[1:]:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    servers[0].serve_forever()

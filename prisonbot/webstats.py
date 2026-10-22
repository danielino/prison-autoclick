"""A small web server (standard library only) with a live page of what the bot is doing and how the fight is going.
The page receives its data over Server-Sent Events (/events); /api/state gives the same data once as JSON.
It only shows data: there is no way to control the bot or the game from it."""
import json, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .config import log
from . import live

DEFAULT_PORT = 8080
MAX_CLIENTS = 20  # live streams at the same time
_server = None
_thread = None
_error = ""
_clients = 0
_lock = threading.Lock()
_stopping = threading.Event()

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AutoPrison live</title>
<style>
:root{--bg:#0f1218;--card:#181d27;--line:#2a3140;--tx:#e6e9ef;--mute:#8b94a7;--ok:#3ddc84;--warn:#ffb020;--bad:#ff5c5c;--acc:#5aa9ff}
@media (prefers-color-scheme: light){:root{--bg:#f3f5f9;--card:#fff;--line:#d9dee8;--tx:#1b2230;--mute:#667089;--acc:#1f6fe0}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font:14px/1.4 system-ui,Segoe UI,sans-serif}
header{display:flex;flex-wrap:wrap;align-items:center;gap:12px;padding:14px 18px;border-bottom:1px solid var(--line)}
h1{font-size:18px;margin:0}.dot{width:10px;height:10px;border-radius:50%;background:var(--bad);display:inline-block}
.dot.on{background:var(--ok)}.badge{padding:2px 10px;border-radius:99px;border:1px solid var(--line);color:var(--mute)}
.badge.run{color:var(--ok);border-color:var(--ok)}.badge.fight{color:var(--bad);border-color:var(--bad)}
#status{color:var(--mute);flex:1;min-width:200px}
main{display:grid;gap:14px;padding:14px 18px;grid-template-columns:repeat(auto-fit,minmax(320px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
.card h2{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--mute);margin:0 0 10px}
.wide{grid-column:1/-1}
.big{font-size:34px;font-weight:700}.row{display:flex;gap:18px;flex-wrap:wrap;align-items:flex-end}
.k{color:var(--mute);font-size:12px}.bar{height:12px;border-radius:6px;background:var(--line);overflow:hidden;margin:4px 0 8px}
.bar>i{display:block;height:100%;background:var(--ok);transition:width .5s}.bar.mid>i{background:var(--warn)}.bar.low>i{background:var(--bad)}
.bot{display:grid;grid-template-columns:90px 1fr 48px;gap:8px;align-items:center;margin:4px 0}
.bot.t{outline:1px solid var(--acc);border-radius:6px;padding:2px 4px}.bot .bar{margin:0}
canvas{width:100%;height:150px;display:block}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:8px 14px}
.stat{display:flex;justify-content:space-between;gap:8px;border-bottom:1px dashed var(--line);padding:3px 0}
.stat b{font-variant-numeric:tabular-nums}.gt{grid-column:1/-1;color:var(--mute);font-size:12px;margin-top:6px}
#ev{max-height:340px;overflow:auto;font:12px/1.5 ui-monospace,Consolas,monospace}
#ev div{padding:1px 0;border-bottom:1px solid var(--line)}#ev .t{color:var(--mute)}
.k-action{color:var(--acc)}.k-fight{color:var(--bad)}.k-warn{color:var(--warn)}.k-loot{color:var(--ok)}.k-heal{color:var(--ok)}
.k-llm{color:#c08bff}.k-stats{color:var(--mute)}
.none{color:var(--mute)}
</style></head><body>
<header><span class="dot" id="dot"></span><h1>AutoPrison live</h1><span class="badge" id="run">stopped</span>
<span class="badge" id="fightb">no fight</span><span id="status"></span><span class="k" id="clock"></span></header>
<main>
<section class="card"><h2>Combat</h2>
 <div class="row"><div><div class="k">Fight</div><div class="big" id="fno">-</div></div>
 <div><div class="k">Time</div><div class="big" id="ftime">-</div></div>
 <div><div class="k">Attacks left</div><div class="big" id="att">-</div></div>
 <div><div class="k">Turn</div><div class="big" id="turn">-</div></div></div>
 <div class="k" style="margin-top:12px">Your health <b id="myp"></b></div><div class="bar" id="mybar"><i style="width:0"></i></div>
 <div class="k">Bots in the fight</div><div id="bots" class="none">none</div>
 <div class="k" style="margin-top:8px">Last action: <span id="last" class="none">-</span></div></section>
<section class="card"><h2>Health in the last minutes</h2><canvas id="chart" width="640" height="150"></canvas>
 <div class="k"><span style="color:var(--acc)">&#9632;</span> you &nbsp; <span style="color:var(--bad)">&#9632;</span> target bot</div></section>
<section class="card wide"><h2>Session <span id="sess" class="k"></span></h2><div class="grid" id="stats"></div></section>
<section class="card wide" id="llmc" style="display:none"><h2>Vision model</h2><div class="grid" id="llm"></div></section>
<section class="card wide"><h2>Events</h2><div id="ev"></div></section>
</main>
<script>
const $=id=>document.getElementById(id);let off=0,last=null;
const fmt=s=>{s=Math.max(0,Math.round(s));const h=Math.floor(s/3600),m=Math.floor(s%3600/60);return(h?h+':':'')+String(m).padStart(h?2:1,'0')+':'+String(s%60).padStart(2,'0')};
const cls=p=>p<.25?'bar low':p<.5?'bar mid':'bar';
function hp(el,p){el.className=cls(p);el.firstElementChild.style.width=Math.round(p*100)+'%'}
function render(s){last=s;off=s.now-Date.now()/1000;const f=s.fight;
 $('run').textContent=s.running?'hunting':'stopped';$('run').className='badge'+(s.running?' run':'');
 $('fightb').textContent=f.in_fight?'in a fight':'no fight';$('fightb').className='badge'+(f.in_fight?' fight':'');
 $('status').textContent=s.status||'';$('fno').textContent=f.number||'-';
 $('att').textContent=f.attacks_left==null?'-':f.attacks_left;
 $('turn').textContent=f.turn==='mine'?'yours':f.turn==='enemy'?'enemy':'-';
 if(f.my_health==null){$('myp').textContent='';hp($('mybar'),0)}else{$('myp').textContent=Math.round(f.my_health*100)+'%';hp($('mybar'),f.my_health)}
 const b=$('bots');b.innerHTML='';
 if(!f.bots.length){b.className='none';b.textContent=f.in_fight?'looking...':'none'}else{b.className='';
  f.bots.forEach((x,i)=>{const d=document.createElement('div');d.className='bot'+(f.target===i?' t':'');
   const p=x.health;d.innerHTML='<span>bot '+(i+1)+(f.target===i?' &#9654;':'')+'</span><div class="'+(p==null?'bar':cls(p))+'"><i style="width:'+(p==null?0:Math.round(p*100))+'%"></i></div><b>'+(p==null?'?':Math.round(p*100)+'%')+'</b>';b.appendChild(d)})}
 $('last').textContent=s.last_action?s.last_action+(s.last_action_age!=null?'  ('+s.last_action_age+' s ago)':''):'-';
 $('last').className=s.last_action?'':'none';
 const st=s.stats;$('sess').textContent='hunting time '+fmt(st.seconds);
 const g=$('stats');g.innerHTML='';st.groups.forEach(gr=>{const t=document.createElement('div');t.className='gt';t.textContent=gr.title;g.appendChild(t);
  gr.items.forEach(i=>{const d=document.createElement('div');d.className='stat';d.innerHTML='<span>'+i.label+'</span><b>'+i.value+(i.rate!=null?' <span class="k">('+i.rate+'/h)</span>':'')+'</b>';g.appendChild(d)})});
 if(s.llm){$('llmc').style.display='';const l=s.llm,a=l.ok?(l.seconds/l.ok).toFixed(1):'-';
  $('llm').innerHTML=[['asked / answered',l.asks+' / '+l.ok],['average answer (s)',a],['weakest bot: agreed / differed',l.agree+' / '+l.differ],['attacks left: same / different',l.attacks_same+' / '+l.attacks_differ]].map(r=>'<div class="stat"><span>'+r[0]+'</span><b>'+r[1]+'</b></div>').join('')}
 const e=$('ev');e.innerHTML=s.events.slice().reverse().map(x=>{const d=new Date(x.t*1000).toTimeString().slice(0,8);return'<div><span class="t">'+d+'</span> <span class="k-'+x.kind+'">'+x.text.replace(/[<>&]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]))+'</span></div>'}).join('');
 chart(s.series,s.now)}
function chart(ser,now){const c=$('chart'),x=c.getContext('2d'),w=c.width=c.clientWidth*devicePixelRatio,h=c.height=150*devicePixelRatio;x.clearRect(0,0,w,h);
 const css=getComputedStyle(document.documentElement),line=css.getPropertyValue('--line'),span=300;x.strokeStyle=line;x.lineWidth=1;
 for(let i=0;i<=4;i++){const y=h*i/4;x.beginPath();x.moveTo(0,y);x.lineTo(w,y);x.stroke()}
 const pts=ser.filter(p=>now-p[0]<=span);
 const draw=(k,col)=>{x.strokeStyle=col;x.lineWidth=2*devicePixelRatio;x.beginPath();let on=false;pts.forEach(p=>{if(p[k]==null)return;const X=w*(1-(now-p[0])/span),Y=h*(1-p[k]);on?x.lineTo(X,Y):x.moveTo(X,Y);on=true});x.stroke()};
 draw(1,css.getPropertyValue('--acc').trim());draw(2,css.getPropertyValue('--bad').trim())}
setInterval(()=>{if(!last)return;const n=Date.now()/1000+off,f=last.fight;$('clock').textContent=new Date().toTimeString().slice(0,8);
 $('ftime').textContent=f.in_fight&&f.seconds!=null?fmt(f.seconds+(n-last.now)):(f.last_seconds!=null?'last '+fmt(f.last_seconds):'-')},500);
function connect(){const es=new EventSource('events');
 es.onopen=()=>$('dot').className='dot on';es.onerror=()=>{$('dot').className='dot'};
 es.addEventListener('state',m=>render(JSON.parse(m.data)))}
connect();
</script></body></html>
"""


def _allowed_host(handler, cfg_lan):
    """Refuse requests whose Host header is not this machine (protects the local-only server from web pages that point
    a hostname at 127.0.0.1)."""
    if cfg_lan:
        return True
    host = (handler.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
    return host in ("localhost", "127.0.0.1", "::1", "")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    lan = False

    def log_message(self, *a):
        pass

    def _send(self, code, ctype, body, extra=()):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not _allowed_host(self, self.lan):
            return self._send(403, "text/plain", "forbidden host")
        path = self.path.split("?", 1)[0]
        try:
            if path in ("/", "/index.html"):
                return self._send(200, "text/html; charset=utf-8", PAGE)
            if path == "/api/state":
                return self._send(200, "application/json", json.dumps(live.snapshot()))
            if path == "/healthz":
                return self._send(200, "text/plain", "ok")
            if path == "/events":
                return self._stream()
            self._send(404, "text/plain", "not found")
        except (BrokenPipeError, ConnectionError, OSError):
            pass

    def _stream(self):
        global _clients
        with _lock:
            if _clients >= MAX_CLIENTS:
                return self._send(503, "text/plain", "too many viewers")
            _clients += 1
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            self.wfile.write(b"retry: 2000\n\n")
            ver = -1
            while not _stopping.is_set():
                data = json.dumps(live.snapshot(events=40))
                self.wfile.write(("event: state\ndata: %s\n\n" % data).encode("utf-8"))
                self.wfile.flush()
                ver = live.wait_change(live.version(), 1.0)  # a change is pushed at once, otherwise once a second
                time.sleep(0.15)  # a burst of changes goes out as one frame
        except (BrokenPipeError, ConnectionError, OSError):
            pass
        finally:
            with _lock:
                _clients -= 1


# ---------------------------------------------------------------- start / stop
def running():
    return _server is not None


def error():
    return _error


def address(cfg):
    """The address to type in a browser."""
    port = int(cfg.get("web_port", DEFAULT_PORT))
    return "http://localhost:%d/" % port


def stop():
    global _server, _thread
    _stopping.set()
    srv, _server = _server, None
    if srv is not None:
        try:
            srv.shutdown()
            srv.server_close()
        except Exception:
            pass
        log("WEB server stopped")
    _thread = None


def start(cfg):
    """Start the server (stopping a running one first). (True, address) or (False, why)."""
    global _server, _thread, _error
    stop()
    _error = ""
    if not cfg.get("web_enabled"):
        return False, "off"
    port = int(cfg.get("web_port", DEFAULT_PORT))
    host = "0.0.0.0" if cfg.get("web_lan") else "127.0.0.1"
    handler = type("H", (Handler,), {"lan": bool(cfg.get("web_lan"))})
    try:
        srv = ThreadingHTTPServer((host, port), handler)
    except OSError as e:
        _error = "Cannot listen on %s:%d (%s). Is another program using the port?" % (host, port, e)
        log("WEB server: " + _error)
        return False, _error
    srv.daemon_threads = True
    _stopping.clear()
    _server = srv
    _thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.3}, daemon=True)
    _thread.start()
    log("WEB server listening on %s:%d (%s)" % (host, srv.server_address[1], "the network can see it" if cfg.get("web_lan") else "this computer only"))
    return True, address(dict(cfg, web_port=srv.server_address[1]))

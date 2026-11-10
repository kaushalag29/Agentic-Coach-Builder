"""Views of the Project graph beyond the Markdown pages (ADR-0025): a JSON Canvas per Goal for Obsidian, and one
self-contained HTML page (`vault build --html`) that works offline.

Both are written from the same graph and layout as the vault pages, so they show exactly what the pages show: a
coach's slice or the person's full build, never more.
"""
from __future__ import annotations

import json
import re
from importlib import resources

from . import graph as G

COL_W = 320                        # one column per week
ROW_H = 120
NODE_W, NODE_H = 280, 90
CANVAS_TYPES = ("serves", "changes_scope_of", "led_to", "blocks", "owned_by", "decided_by", "supersedes",
                "resolved_by")
CYTOSCAPE = "cytoscape-3.30.4.min.js"
HTML_MAX_NODES = 300               # the first view: the active Goals' neighbourhood, at most this many nodes


def _goal_subgraph(g: G.Graph, gid: str) -> set[str]:
    """A Goal, what serves it or changes it, what blocks those, and who owns or decided them."""
    keep = {gid}
    for e in g.into.get(gid, []):
        if e.type in ("serves", "changes_scope_of", "led_to", "blocks", "sub_goal_of"):
            keep.add(e.src)
    for nid in list(keep):
        for e in g.into.get(nid, []):
            if e.type in ("blocks", "led_to", "supersedes"):
                keep.add(e.src)
        for e in g.out.get(nid, []):
            if e.type in ("owned_by", "decided_by"):
                keep.add(e.dst)
    return {n for n in keep if g.nodes[n].kind in ("goal", "thread", "decision", "issue", "person")}


def _weeks_of(g: G.Graph, nid: str) -> list[str]:
    n = g.nodes[nid]
    if n.kind == "thread":
        return [w for w in n.data["weeks"] if w]
    if n.kind == "week":
        return [nid]
    for e in g.out.get(nid, []):
        if e.type in ("decided_in", "reviewed_in"):          # a Check-in sits in the week it reviewed
            return [e.dst]
    from .store import iso_week
    import datetime as dt
    try:
        return [iso_week(dt.date.fromisoformat(n.date[:10]))] if n.date else []
    except ValueError:
        return []


def _span(weeks: list[str]) -> list[str]:
    """Every ISO week from the first of `weeks` to the last, in order (at most two years)."""
    from .store import next_week
    if not weeks:
        return []
    out, w = [], weeks[0]
    while w <= weeks[-1] and len(out) < 104:
        out.append(w)
        w = next_week(w)
    return out


def canvas(g: G.Graph, lay, gid: str, generated: str) -> str:
    """One Goal as a JSON Canvas 1.0 board: a column per week (a group), lanes for Decisions, tasks (each a bar as long
    as it was carried, packed by greedy interval colouring: the fewest rows, O(n log n)), Issues and People."""
    nodes_in = _goal_subgraph(g, gid)
    have = sorted({w for n in nodes_in for w in _weeks_of(g, n)})
    weeks = _span(have)                                  # every week from the first to the last: time stays even
    col = {w: i for i, w in enumerate(weeks)}
    x0 = NODE_W + 80
    out_nodes, placed = [], {}

    def node(nid: str, x: int, y: int, w: int = NODE_W, h: int = NODE_H) -> None:
        try:
            path = lay.path(nid)
        except KeyError:
            return
        out_nodes.append({"id": nid, "type": "file", "file": path, "x": x, "y": y, "width": w, "height": h})
        placed[nid] = True

    node(gid, 0, 0, NODE_W, NODE_H * 2)
    y = 0
    decs = sorted((n for n in nodes_in if g.nodes[n].kind == "decision"), key=lambda n: (g.nodes[n].date, n))
    per_col: dict[int, int] = {}
    for d in decs:
        c = col.get((_weeks_of(g, d) or [weeks[0] if weeks else ""])[0], 0)
        node(d, x0 + c * COL_W, y + per_col.get(c, 0) * ROW_H)
        per_col[c] = per_col.get(c, 0) + 1
    y += max([0, *per_col.values()]) * ROW_H + 60
    threads = sorted((n for n in nodes_in if g.nodes[n].kind == "thread"),
                     key=lambda n: (col.get((_weeks_of(g, n) or [""])[0], 0), n))
    rows_end: list[int] = []
    for t in threads:
        ws = [col[w] for w in _weeks_of(g, t) if w in col] or [0]
        a, b = min(ws), max(ws)
        r = next((i for i, end in enumerate(rows_end) if end < a), None)
        if r is None:
            rows_end.append(b)
            r = len(rows_end) - 1
        else:
            rows_end[r] = b
        node(t, x0 + a * COL_W, y + r * ROW_H, (b - a + 1) * COL_W - 40)
    y += max(1, len(rows_end)) * ROW_H + 60
    for kind in ("issue", "person"):
        items = sorted((n for n in nodes_in if g.nodes[n].kind == kind), key=lambda n: (g.nodes[n].date, n))
        for i, n in enumerate(items):
            c = col.get((_weeks_of(g, n) or [""])[0], 0) if kind == "issue" else 0
            node(n, x0 + c * COL_W + (0 if kind == "issue" else i * COL_W), y + (i * ROW_H if kind == "issue" else 0))
        if items:
            y += (len(items) if kind == "issue" else 1) * ROW_H + 60
    groups = [{"id": f"week-{w}", "type": "group", "label": w, "x": x0 + i * COL_W - 20, "y": -60,
               "width": COL_W - 10, "height": y + 60} for i, w in enumerate(weeks)]
    edges = []
    for nid in placed:
        for e in g.out.get(nid, []):
            if e.type in CANVAS_TYPES and e.dst in placed:
                edges.append({"id": f"{e.src}-{e.type}-{e.dst}", "fromNode": e.src, "toNode": e.dst, "label": e.type,
                              "toEnd": "arrow"})
    return json.dumps({"_generated": generated, "_coach": g.nodes[gid].coach or "founder", "nodes": groups + out_nodes, "edges": edges}, indent=1,
                      ensure_ascii=False) + "\n"


def graph_data(g: G.Graph, lay) -> dict:
    """The HTML viewer's data: every node with a page, and every edge between two of them."""
    nodes, keep = [], set()
    for nid, n in g.nodes.items():
        if n.kind == "source":
            continue
        try:
            if n.kind == "week":                                  # the shared spine first, else a folder's own
                sc = next((sc for sc in ("shared", *sorted(lay.weeks)) if nid in lay.weeks.get(sc, ())), None)
                path = lay.path(nid, sc)
            else:
                path = lay.path(nid)
        except (KeyError, TypeError):
            continue
        keep.add(nid)
        nodes.append({"id": nid, "kind": n.kind, "label": path.rsplit("/", 1)[-1].removesuffix(".md"), "title": n.title, "date": n.date,
                      "status": n.status or "", "coach": n.coach, "path": path,
                      "weeks": n.data.get("weeks") if n.kind == "thread" else _weeks_of(g, nid)})
    edges = [{"source": e.src, "target": e.dst, "type": e.type} for e in g.edges
             if e.src in keep and e.dst in keep]
    return {"nodes": nodes, "edges": edges}


_PAGE = """<!doctype html>
__GENERATED__
<html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#fff;--fg:#1d1d1f;--muted:#6e6e73;--line:#d2d2d7;--panel:#f5f5f7}
@media (prefers-color-scheme:dark){:root{--bg:#1c1c1e;--fg:#f5f5f7;--muted:#a1a1a6;--line:#3a3a3c;--panel:#2c2c2e}}
html,body{margin:0;height:100%;background:var(--bg);color:var(--fg);font:14px/1.4 -apple-system,Segoe UI,sans-serif}
#bar{display:flex;flex-wrap:wrap;gap:12px;align-items:center;padding:8px 12px;border-bottom:1px solid var(--line)}
#bar label{white-space:nowrap}#cy{position:absolute;top:96px;left:0;right:300px;bottom:0}
#side{position:absolute;top:96px;right:0;width:284px;bottom:0;padding:8px;border-left:1px solid var(--line);overflow:auto;background:var(--panel)}
input[type=search]{padding:4px 8px;min-width:200px}.muted{color:var(--muted)}h1{font-size:16px;margin:0 12px 0 0}
#why li{margin:4px 0}
</style></head><body>
<div id="bar"><h1>__TITLE__</h1>
<input id="q" type="search" placeholder="Search titles">
<span id="kinds"></span>
<label>Up to <input id="week" type="range" min="0" value="0"> <span id="weeklabel"></span></label>
<button id="all">Show all</button></div>
<div id="cy"></div>
<div id="side"><p class="muted">Click a node to read it, click a second one for how they connect, double-click to
show what is tied to it. Search highlights a record and everything two steps from it.</p><div id="info"></div>
<ol id="why"></ol></div>
<script type="application/json" id="data">__DATA__</script>
<script>__CYTOSCAPE__</script>
<script>
(function(){
const D=JSON.parse(document.getElementById('data').textContent);
const COLORS=__COLORS__;
const weeks=[...new Set(D.nodes.flatMap(n=>n.weeks||[]))].sort();
const shown=new Set();
const goals=D.nodes.filter(n=>n.kind==='goal'&&n.status==='active').map(n=>n.id);
const adj={};D.edges.forEach(e=>{(adj[e.source]=adj[e.source]||[]).push(e.target);(adj[e.target]=adj[e.target]||[]).push(e.source)});
function grow(ids,hops){let f=ids.slice();ids.forEach(i=>shown.add(i));for(let h=0;h<hops;h++){const n=[];f.forEach(i=>(adj[i]||[]).forEach(j=>{if(!shown.has(j)&&shown.size<__MAX__){shown.add(j);n.push(j)}}));f=n}}
if(D.nodes.length<=__MAX__)D.nodes.forEach(n=>shown.add(n.id));  // a Project this size is shown whole
else grow(goals.length?goals:D.nodes.slice(0,1).map(n=>n.id),2);
const cy=cytoscape({container:document.getElementById('cy'),wheelSensitivity:0.3,
 elements:[...D.nodes.map(n=>({data:{...n,color:COLORS[n.kind]||'#888'}})),...D.edges.map((e,i)=>({data:{id:'e'+i,...e}}))],
 style:[{selector:'node',style:{'background-color':'data(color)','label':'data(label)','font-size':11,'color':'#6e6e73','text-wrap':'wrap','text-max-width':200,'text-valign':'bottom','text-margin-y':3,'width':16,'height':16}},
 {selector:'node[kind="goal"]',style:{'width':32,'height':32,'font-size':12}},
 {selector:'node[kind="week"]',style:{'shape':'round-rectangle','width':70,'height':18,'text-valign':'center','text-margin-y':0,'color':'#fff','font-size':10}},
 {selector:'node[status="superseded"],node[status="merged"],node[status="resolved"]',style:{'opacity':0.5}},
 {selector:'edge',style:{'width':1,'line-color':'#999','target-arrow-color':'#999','target-arrow-shape':'triangle','curve-style':'bezier','label':'','font-size':9,'color':'#999','text-rotation':'autorotate','opacity':0.6}},
 {selector:'edge[type="mentions"],edge[type="reviewed_in"],edge[type="decided_in"]',style:{'line-style':'dotted','label':'','opacity':0.2}},
 {selector:'.hidden',style:{'display':'none'}},{selector:'.faded',style:{'opacity':0.12}},
 {selector:'.hl',style:{'border-width':3,'border-color':'#ff9f0a'}},{selector:'.path',style:{'line-color':'#ff9f0a','target-arrow-color':'#ff9f0a','width':3,'label':'data(type)','opacity':1}},
 {selector:'node:selected',style:{'border-width':3,'border-color':'#0a84ff'}}]});
const kindsOn=new Set(Object.keys(COLORS));
const kbox=document.getElementById('kinds');
Object.keys(COLORS).forEach(k=>{const l=document.createElement('label');const c=document.createElement('input');c.type='checkbox';c.checked=true;
 c.onchange=()=>{c.checked?kindsOn.add(k):kindsOn.delete(k);apply()};l.appendChild(c);l.appendChild(document.createTextNode(' '+k+' '));kbox.appendChild(l)});
const wk=document.getElementById('week');wk.max=Math.max(0,weeks.length-1);wk.value=wk.max;
function upto(){return weeks[+wk.value]||'9999'}
function apply(){const lim=upto();document.getElementById('weeklabel').textContent=weeks.length?lim:'';
 cy.batch(()=>{cy.nodes().forEach(n=>{const d=n.data();const ws=d.weeks||[];const early=!ws.length||ws[0]<=lim;
  n.toggleClass('hidden',!(shown.has(d.id)&&kindsOn.has(d.kind)&&early))})})}
// a timeline: one column per week, left to right; one lane per kind, top to bottom
const LANES=['week','goal','decision','thread','issue','person','note','checkin'],COL=230,ROW=58;
const allWeeks=(()=>{const ws=weeks.slice();return ws})();
function col(d){if(d.kind==='week')return allWeeks.indexOf(d.id);const w=(d.weeks||[])[0];const i=w?allWeeks.indexOf(w):-1;return i}
function layout(){const vis=cy.nodes().filter(n=>!n.hasClass('hidden'));const cells={},pos={};
 vis.forEach(n=>{const d=n.data();const lane=Math.max(0,LANES.indexOf(d.kind));const c=col(d);const k=lane+':'+c;
  (cells[k]=cells[k]||[]).push(n.id());pos[n.id()]={lane,c,i:cells[k].length-1}});
 const depth=LANES.map((_,l)=>Math.max(0,...Object.keys(cells).filter(k=>+k.split(':')[0]===l).map(k=>cells[k].length)));
 const top=[];let y=0;LANES.forEach((_,l)=>{top[l]=y;if(depth[l])y+=depth[l]*ROW+40});   // an empty lane takes no room
 cy.layout({name:'preset',animate:false,fit:true,padding:30,positions:n=>{const p=pos[n.id()];
  return p?{x:(p.c+1)*COL,y:top[p.lane]+p.i*ROW}:{x:0,y:0}}}).run()}
wk.oninput=apply;apply();layout();
document.getElementById('all').onclick=()=>{D.nodes.forEach(n=>shown.add(n.id));apply();layout()};
let first=null;const info=document.getElementById('info'),why=document.getElementById('why');
function show(d){info.textContent='';const h=document.createElement('h3');h.textContent=d.title;info.appendChild(h);
 [['kind',d.kind],['date',d.date],['status',d.status],['coach',d.coach],['page',d.path]].forEach(([k,v])=>{if(v){const p=document.createElement('div');p.textContent=k+': '+v;info.appendChild(p)}})}
cy.on('tap','node',ev=>{const n=ev.target;show(n.data());cy.elements().removeClass('path');why.textContent='';
 if(first&&first.id()!==n.id()){const r=cy.elements(':visible').aStar({root:first,goal:n,directed:false});
  if(r.found){r.path.addClass('path');r.path.edges().forEach(e=>{const li=document.createElement('li');
   li.textContent=e.source().data('label')+' —'+e.data('type')+'→ '+e.target().data('label');why.appendChild(li)})}
  else{const li=document.createElement('li');li.textContent='No connection between these two in this view.';why.appendChild(li)}first=null}
 else first=n});
cy.on('dbltap','node',ev=>{grow([ev.target.id()],1);apply();layout()});
document.getElementById('q').oninput=e=>{const q=e.target.value.trim().toLowerCase();cy.elements().removeClass('faded hl');
 if(!q)return;const m=cy.nodes().filter(n=>(n.data('title')||'').toLowerCase().includes(q));m.forEach(n=>shown.add(n.id()));apply();
 const near=m.closedNeighborhood().closedNeighborhood();cy.elements().not(near).addClass('faded');m.addClass('hl')};
})();
</script></body></html>
"""


def html(g: G.Graph, lay, title: str, colors: dict[str, int], generated: str) -> str:
    """One offline page: the data inline (`</` escaped), Cytoscape inline, and a policy that blocks every network
    request. Labels are drawn on a canvas or set as text, never as HTML."""
    js = resources.files("founder_coach").joinpath("assets", CYTOSCAPE).read_text(encoding="utf-8")
    data = json.dumps(graph_data(g, lay), ensure_ascii=False).replace("</", "<\\/")
    cols = json.dumps({k: f"#{v:06x}" for k, v in colors.items()})
    esc = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    parts = {"GENERATED": generated, "TITLE": esc, "COLORS": cols, "MAX": str(HTML_MAX_NODES), "DATA": data,
             "CYTOSCAPE": js.replace("</script", "<\\/script")}
    # one pass, so text from the store can never be read as a later placeholder
    return re.sub(r"__(GENERATED|TITLE|COLORS|MAX|DATA|CYTOSCAPE)__", lambda m: parts[m.group(1)], _PAGE)

"""
generate_day_view.py — generate a self-contained HTML viewer for one day.

Usage:
    python generate_day_view.py 2024-03-15
    python generate_day_view.py 2024-03-15 --out /tmp/day.html
    python generate_day_view.py 2024-03-15 --segments path/to/semantic_stops.csv
    python generate_day_view.py 2024-03-15 --mongo mongodb://host:27017 --imghost http://myserver

Data sources:
    Segments  — semantic_stops.csv  (local file, filtered by date)
    Images    — MongoDB picam.images (matched by timestamp range)
"""

import argparse
import json
import sys
import csv
from datetime import datetime, timezone, timedelta
import pandas as pd

from pymongo import MongoClient

# ─── Config ───────────────────────────────────────────────────────────────────

MONGO_URI     = "mongodb://localhost:27018"
DB            = "picam"
COL_IMAGES    = "images"
IMG_HOST      = "http://localhost:9000/LifelogPicam/cathal"
SEGMENTS_FILE = "files/nominatim_semantic_stops.csv"


# ─── Data fetching ────────────────────────────────────────────────────────────

def day_bounds_utc(date_str: str):
    d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return d.timestamp(), (d + timedelta(days=1)).timestamp()


def load_segments(csv_path: str, start_ts: float, end_ts: float) -> list:
    segments = []
    df = pd.read_csv(csv_path, sep=";")
    for _, row in df.iterrows():
        s = float(row["start_ts"])
        e = float(row["end_ts"])
        if e < start_ts or s >= end_ts:
            continue
        segments.append({
            "track_id":    int(row["track_id"]),
            "start":       row["start"],
            "end":         row["end"],
            "start_ts":    s,
            "end_ts":      e,
            "label":       "stop" if str(row["label"]) == "1" else "move",
            "lat":         float(row["centroid_lat"]),
            "lon":         float(row["centroid_lon"]),
            "stop_id":     row["stop_id"]  or None,
            "place_id":    row["place_id"] or None,
            "n_points":    int(row["n_points"]),
            # Foursquare / semantic enrichment
            "name":        row.get("name")        or None,
            "categories":  row.get("categories")  or None,
            "parent":      row.get("parent")      or None,
            "location":     row.get("location")     or None,
            "fsq_place_id":      row.get("fsq_place_id")      or None,
        })
    segments.sort(key=lambda x: x["start_ts"])
    return segments


def fetch_images(start_ts: float, end_ts: float, mongo_uri: str) -> list:
    client = MongoClient(mongo_uri)
    db     = client[DB]
    images = list(db[COL_IMAGES].find(
        {"timestamp": {"$gte": start_ts * 1000, "$lt": end_ts * 1000}, "device": "cathal"},
        {"_id": 0, "thumbnail": 1, "timestamp": 1, "time": 1},
        sort=[("timestamp", 1)],
    ))
    client.close()
    return images


# ─── HTML ─────────────────────────────────────────────────────────────────────

HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{date}</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html,body{{height:100%;font-family:system-ui,sans-serif;background:#0f0f0f;color:#e0e0e0}}
#app{{display:flex;flex-direction:column;height:100vh}}

/* ── header ── */
#hdr{{padding:8px 16px;background:#1a1a1a;border-bottom:1px solid #252525;
      display:flex;align-items:center;gap:10px;flex-shrink:0}}
#hdr h1{{font-size:14px;font-weight:500;white-space:nowrap}}
#stats{{font-size:12px;color:#555;margin-left:auto;white-space:nowrap}}

/* ── main ── */
#main{{display:flex;flex:1;overflow:hidden}}
#map{{flex:1;min-width:0}}

/* ── sidebar ── */
#sb{{width:340px;display:flex;flex-direction:column;
     background:#141414;border-left:1px solid #1e1e1e;overflow:hidden;flex-shrink:0}}

/* track pills */
#pills{{display:flex;flex-wrap:wrap;gap:5px;padding:8px 12px;
        border-bottom:1px solid #1e1e1e;background:#161616;flex-shrink:0}}
.pill{{font-size:11px;padding:2px 9px;border-radius:10px;cursor:pointer;
       border:1px solid #333;color:#888;user-select:none;transition:opacity .15s}}
.pill.off{{opacity:.3}}

/* segment list */
#seg-list{{flex:1;overflow-y:auto}}
#seg-list::-webkit-scrollbar{{width:3px}}
#seg-list::-webkit-scrollbar-thumb{{background:#252525;border-radius:2px}}

.seg{{padding:9px 12px 9px 14px;border-bottom:1px solid #1a1a1a;cursor:pointer;
      display:flex;align-items:flex-start;gap:9px;transition:background .1s;
      border-left:3px solid transparent}}
.seg:hover{{background:#1c1c1c}}
.seg.active{{background:#1e231e}}
.seg.stop{{border-left-color:#ff9800}}
.seg.move{{border-left-color:#3a7bd5}}
.seg.active.stop{{background:#261d0d}}
.seg.active.move{{background:#0e1826}}

.dot{{width:9px;height:9px;border-radius:50%;flex-shrink:0;margin-top:3px}}
.dot.stop{{background:#ff9800}}
.dot.move{{background:#3a7bd5}}

.sb{{flex:1;min-width:0}}
.sl{{font-size:12px;font-weight:500;text-transform:uppercase;letter-spacing:.05em;color:#ccc}}
.sl .place-name{{text-transform:none;letter-spacing:0;color:#e8c87a;font-weight:400;margin-left:5px}}
.st{{font-size:11px;color:#666;margin-top:1px}}
.si{{font-size:10px;color:#484848;margin-top:3px;line-height:1.5}}
.sp{{font-size:11px;color:#444;flex-shrink:0;padding-top:1px}}
.cat-tag{{display:inline-block;font-size:10px;padding:1px 6px;border-radius:3px;
          background:#1e2a1e;color:#6a9;border:1px solid #2a3a2a;margin-top:3px}}

/* ── image panel ── */
#panel{{height:230px;border-top:1px solid #1e1e1e;background:#0c0c0c;
        display:flex;flex-direction:column;flex-shrink:0}}
#phdr{{padding:7px 12px;font-size:11px;color:#666;background:#161616;
       border-bottom:1px solid #1a1a1a;flex-shrink:0;
       white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
#strip{{display:flex;gap:5px;padding:6px 8px;overflow-x:auto;flex:1;align-items:center}}
#strip::-webkit-scrollbar{{height:3px}}
#strip::-webkit-scrollbar-thumb{{background:#252525;border-radius:2px}}
.thumb{{height:178px;width:auto;border-radius:3px;cursor:zoom-in;flex-shrink:0;object-fit:cover;
        border:2px solid transparent;transition:border-color .1s}}
.thumb:hover{{border-color:#ff9800}}
#no-img{{color:#2a2a2a;font-size:12px;margin:auto}}

/* ── legend ── */
#leg{{position:absolute;bottom:20px;left:10px;z-index:1000;
      background:rgba(12,12,12,.88);border-radius:5px;padding:7px 11px;
      font-size:11px;color:#888;border:1px solid #222;pointer-events:none;line-height:2}}
.ld{{display:flex;align-items:center;gap:7px}}
.lc{{width:9px;height:9px;border-radius:50%;flex-shrink:0}}

/* ── lightbox ── */
#lb{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.94);
     z-index:9999;align-items:center;justify-content:center;cursor:zoom-out}}
#lb.open{{display:flex}}
#lb img{{max-width:92vw;max-height:92vh;border-radius:4px;object-fit:contain}}
#lbx{{position:fixed;top:14px;right:18px;font-size:22px;color:#666;cursor:pointer;line-height:1}}
</style>
</head>
<body>
<div id="app">
  <div id="hdr">
    <h1>&#128205; {date}</h1>
    <span id="stats"></span>
  </div>
  <div id="main">
    <div id="map"></div>
    <div id="sb">
      <div id="pills"></div>
      <div id="seg-list"></div>
      <div id="panel">
        <div id="phdr">Select a segment to view images</div>
        <div id="strip"><span id="no-img">No segment selected</span></div>
      </div>
    </div>
  </div>
</div>

<div id="leg">
  <div class="ld"><span class="lc" style="background:#ff9800"></span>Stop</div>
  <div class="ld"><span class="lc" style="background:#3a7bd5"></span>Move</div>
  <div class="ld"><span class="lc" style="background:#e8c87a;border-radius:2px"></span>Named place</div>
</div>

<div id="lb"><span id="lbx">&#10005;</span><img id="lbi" src="" alt=""/></div>

<script>
const IMG_HOST = {img_host};
const SEGS     = {segments_json};
const IMAGES   = {images_json};

// ── utils ────────────────────────────────────────────────────────────────────
function fmt(ts) {{
  return new Date(ts * 1000).toTimeString().slice(0,8);
}}
function dur(s) {{
  const m = Math.round((s.end_ts - s.start_ts) / 60);
  return m < 60 ? m + 'm' : (m/60).toFixed(1) + 'h';
}}
const TRACK_COLORS = ['#4fc3f7','#81c784','#ffb74d','#f06292','#ce93d8','#80cbc4','#fff176','#ff8a65'];
function tc(id) {{ return TRACK_COLORS[id % TRACK_COLORS.length]; }}

// ── map ──────────────────────────────────────────────────────────────────────
const map = L.map('map');
L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png',{{
  attribution:'&copy; OpenStreetMap &copy; CARTO', maxZoom:19
}}).addTo(map);

// ── draw segments as polylines + stop markers ────────────────────────────────
// Group consecutive segments by track, draw a line through their centroids.
// Stop segments also get a circle marker.

const trackIds = [...new Set(SEGS.map(s => s.track_id))].sort((a,b)=>a-b);
const trackPolylines = {{}};
const segMarkers = [];

// Build one polyline per track (centroid-to-centroid)
trackIds.forEach(tid => {{
  const pts = SEGS.filter(s => s.track_id === tid).map(s => [s.lat, s.lon]);
  if (pts.length < 2) return;
  trackPolylines[tid] = L.polyline(pts, {{
    color: tc(tid), weight: 2, opacity: 0.55, dashArray: '4 4'
  }}).addTo(map);
}});

// Stop markers
SEGS.forEach((seg, idx) => {{
  if (seg.label !== 'stop') {{ segMarkers.push(null); return; }}
  const hasName = !!seg.name;
  const icon = L.divIcon({{
    className: '',
    html: `<div style="width:${{hasName?16:12}}px;height:${{hasName?16:12}}px;border-radius:50%;
      background:${{hasName?'#e8c87a':'#ff9800'}};border:2px solid rgba(255,255,255,.35);
      box-shadow:0 0 5px rgba(0,0,0,.7)"></div>`,
    iconSize: [hasName?16:12, hasName?16:12],
    iconAnchor: [hasName?8:6, hasName?8:6],
  }});
  const m = L.marker([seg.lat, seg.lon], {{icon}})
    .addTo(map)
    .on('click', () => selectSeg(idx));
  segMarkers.push(m);
}});

// Fit map
const allPts = SEGS.map(s => [s.lat, s.lon]);
if (allPts.length) map.fitBounds(allPts, {{padding:[30,30]}});

// ── track pills ───────────────────────────────────────────────────────────────
const activeTracks = new Set(trackIds);
const pillsEl = document.getElementById('pills');
trackIds.forEach(tid => {{
  const p = document.createElement('div');
  p.className = 'pill on';
  p.textContent = 'Track ' + tid;
  p.style.borderColor = tc(tid);
  p.style.color = tc(tid);
  p.addEventListener('click', () => {{
    if (activeTracks.has(tid)) {{
      activeTracks.delete(tid); p.classList.add('off');
      if (trackPolylines[tid]) map.removeLayer(trackPolylines[tid]);
    }} else {{
      activeTracks.add(tid); p.classList.remove('off');
      if (trackPolylines[tid]) trackPolylines[tid].addTo(map);
    }}
    renderList();
  }});
  pillsEl.appendChild(p);
}});

// ── segment list ──────────────────────────────────────────────────────────────
let activeIdx = null;

function renderList() {{
  const el = document.getElementById('seg-list');
  el.innerHTML = '';
  SEGS.forEach((seg, idx) => {{
    if (!activeTracks.has(seg.track_id)) return;
    const isActive = idx === activeIdx;
    const d = document.createElement('div');
    d.className = `seg ${{seg.label}}${{isActive?' active':''}}`;

    const ids = [
      seg.stop_id  ? `stop: ${{seg.stop_id}}`   : null,
      seg.place_id ? `place: ${{seg.place_id}}` : null,
      seg.fsq_id   ? `fsq: ${{seg.fsq_id}}`     : null,
    ].filter(Boolean).join('  ·  ');

    const catTag = seg.categories
      ? `<span class="cat-tag">${{seg.categories}}</span>` : '';

    d.innerHTML = `
      <div class="dot ${{seg.label}}"></div>
      <div class="sb">
        <div class="sl">
          ${{seg.label}}
          <span style="font-size:11px;color:#555;font-weight:400;text-transform:none;letter-spacing:0">${{dur(seg)}}</span>
          ${{seg.name ? `<span class="place-name">&#9679; ${{seg.name}}</span>` : ''}}
        </div>
        <div class="st">${{fmt(seg.start_ts)}} &rarr; ${{fmt(seg.end_ts)}}</div>
        ${{ids   ? `<div class="si">${{ids}}</div>` : ''}}
        ${{catTag ? `<div>${{catTag}}</div>` : ''}}
        ${{seg.checkin && seg.checkin !== 'HOME' ? `<div class="si" style="color:#5a8">&#10003; ${{seg.checkin}}</div>` : ''}}
        ${{seg.checkin === 'HOME' ? `<div class="si" style="color:#5a8">&#8962; Home</div>` : ''}}
      </div>
      <div class="sp">${{seg.n_points}}</div>`;
    d.addEventListener('click', () => selectSeg(idx));
    el.appendChild(d);
  }});

  // stats
  const stops = SEGS.filter(s=>s.label==='stop').length;
  const named = SEGS.filter(s=>s.name).length;
  document.getElementById('stats').textContent =
    `${{SEGS.length}} segs · ${{stops}} stops · ${{named}} named · ${{IMAGES.length}} images`;
}}

renderList();

// ── select segment ────────────────────────────────────────────────────────────
function selectSeg(idx) {{
  activeIdx = idx;
  renderList();

  const seg = SEGS[idx];
  map.setView([seg.lat, seg.lon], Math.max(map.getZoom(), 16), {{animate: true}});

  const imgs = IMAGES.filter(i => i.timestamp >= seg.start_ts * 1000 && i.timestamp <= seg.end_ts * 1000);
  document.getElementById('phdr').textContent =
    `${{seg.label.toUpperCase()}}  ${{fmt(seg.start_ts)}} – ${{fmt(seg.end_ts)}}  (${{dur(seg)}})` +
    (seg.name ? `  ·  ${{seg.name}}` : '') +
    `  ·  ${{imgs.length}} image${{imgs.length!==1?'s':''}}`;

  const strip = document.getElementById('strip');
  strip.innerHTML = '';
  if (!imgs.length) {{
    strip.innerHTML = '<span id="no-img">No images in this window</span>';
    return;
  }}
  imgs.forEach(img => {{
    const src = `${{IMG_HOST}}/${{img.thumbnail}}`;
    const el  = document.createElement('img');
    el.className = 'thumb';
    el.src   = src;
    el.title = img.formatted_time || '';
    el.addEventListener('click', () => {{ document.getElementById('lbi').src=src; document.getElementById('lb').classList.add('open'); }});
    strip.appendChild(el);
  }});
}}

// ── lightbox ─────────────────────────────────────────────────────────────────
document.getElementById('lb').addEventListener('click', ()=>document.getElementById('lb').classList.remove('open'));
document.getElementById('lbx').addEventListener('click', e=>{{e.stopPropagation();document.getElementById('lb').classList.remove('open');}});
</script>
</body>
</html>
"""


# ─── Render ───────────────────────────────────────────────────────────────────

def render(date_str: str, segments_file: str, mongo_uri: str, img_host: str, out_path: str):
    start_ts, end_ts = day_bounds_utc(date_str)

    print(f"Loading segments from {segments_file}…")
    segments = load_segments(segments_file, start_ts, end_ts)
    print(f"  {len(segments)} segments for {date_str}")
    if not segments:
        print("No segments found for this date.", file=sys.stderr)
        sys.exit(1)

    print("Fetching images from MongoDB…")
    images = fetch_images(start_ts, end_ts, mongo_uri)
    print(f"  {len(images)} images")

    html = HTML.format(
        date          = date_str,
        img_host      = json.dumps(img_host),
        segments_json = json.dumps(segments),
        images_json   = json.dumps(images),
    )

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Saved → {out_path}")

# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a day-view HTML from semantic_stops.csv + MongoDB images.")
    parser.add_argument("date",        help="Date to render (YYYY-MM-DD)")
    parser.add_argument("--out",       default=None,          help="Output path (default: <date>.html)")
    parser.add_argument("--segments",  default=SEGMENTS_FILE, help=f"Segments CSV (default: {SEGMENTS_FILE})")
    parser.add_argument("--mongo",     default=MONGO_URI,     help=f"MongoDB URI (default: {MONGO_URI})")
    parser.add_argument("--imghost",   default=IMG_HOST,      help=f"Image host prefix (default: {IMG_HOST})")
    args = parser.parse_args()

    render(
        date_str      = args.date,
        segments_file = args.segments,
        mongo_uri     = args.mongo,
        img_host      = args.imghost,
        out_path      = args.out or f"{args.date}.html",
    )
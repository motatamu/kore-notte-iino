#!/usr/bin/env python3
"""行先表示オープンデータ（led_front.txt / led_side.txt）→ led.js 変換

  python3 tools/convert_led.py                 # カレントの led_front.txt / led_side.txt → led.js
  python3 tools/convert_led.py --check         # 検証だけ（led.js は書かない）
  python3 tools/convert_led.py --gtfs path.zip # GTFS-JP zip の routes.txt で route_id を補完して CSV を書き戻す

形式の説明は spec/led-opendata.md を参照。
検証：列名・値の語彙・data.js（変換済みダイヤ）に存在する系統名/行先かどうかを確認し、
問題があれば警告を出す（警告は致命ではない＝ダイヤ改正で消えた行先の行はアプリ側で無視されるだけ）。
"""
import csv, io, json, os, re, sys, zipfile

FRONT_COLS = ['route_id','route_short_name','trip_headsign','board_stop_name','route_box','via_mode','via_text',
              'dest_text','dest_romaji','loop_style','note_text','verified','source']
SIDE_COLS  = ['route_id','route_short_name','trip_headsign','origin_stop_name','board_stop_name',
              'stop_name_1','stop_name_2','stop_name_3','stop_name_4','stop_name_5','stop_name_6',
              'header_style','header_loop','header_romaji','source']
ENUM = {
    'route_box':   {'', 'none'},
    'via_mode':    {'', 'none', 'inline', 'top', 'stack'},
    'loop_style':  {'', 'none', 'text', 'badge'},
    'verified':    {'', '0', '1'},
    'header_style':{'', 'route_only'},
    'header_loop': {'', '0', '1'},
}
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

def read_csv(path, cols):
    with open(path, encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return rows
    missing = [c for c in cols if c not in rows[0]]
    extra   = [c for c in rows[0] if c not in cols]
    if missing: raise SystemExit('%s: 列が足りません: %s' % (path, missing))
    if extra:   print('%s: 未知の列（無視します）: %s' % (path, extra))
    for r in rows:
        for c in cols: r[c] = (r.get(c) or '').strip()
    return rows

def load_gd():
    p = os.path.join(ROOT, 'data.js')
    if not os.path.exists(p): return None
    s = open(p, encoding='utf-8').read()
    # data.js = window.GD={...};window.GD.en={...}; の形。最初のオブジェクトだけ読めばよい
    dec = json.JSONDecoder()
    gd, _ = dec.raw_decode(s, s.index('{'))
    return gd

def validate(front, side, gd):
    warn = 0
    def w(msg):
        nonlocal warn; warn += 1; print('警告:', msg)
    ivs = lambda x: re.sub('[\U000E0100-\U000E01EF\uFE00-\uFE0F]', '', x)  # 異体字セレクタ（辻󠄀 等）は無視して照合
    routes = set(gd['routes']) if gd else None
    hs_by_route = {}
    if gd:
        for t in gd['trips']:
            hs_by_route.setdefault(gd['routes'][t[0]], set()).add(ivs(gd['headsigns'][t[3]]))
    for name, rows, cols in (('led_front.txt', front, FRONT_COLS), ('led_side.txt', side, SIDE_COLS)):
        seen = set()
        for i, r in enumerate(rows, 2):
            for c, allowed in ENUM.items():
                if c in cols and r[c] not in allowed:
                    w('%s:%d %s=「%s」は語彙にありません %s' % (name, i, c, r[c], sorted(allowed)))
            if not r['route_short_name'] and not r['route_id']:
                w('%s:%d route_id も route_short_name も空です' % (name, i))
            if not r['trip_headsign']:
                w('%s:%d trip_headsign が空です' % (name, i))
            if name == 'led_front.txt':
                if r['via_mode'] in ('inline','top','stack') and not r['via_text']:
                    w('%s:%d via_mode=%s なのに via_text が空です' % (name, i, r['via_mode']))
                if r['via_mode'] in ('', 'none') and r['via_text']:
                    w('%s:%d via_text があるのに via_mode が %s です' % (name, i, r['via_mode'] or 'auto'))
                if r['via_mode'] == 'stack' and not (1 <= len(r['via_text'].split('/')) <= 4):
                    w('%s:%d stack の行数は1〜4です' % (name, i))
            if name == 'led_side.txt':
                names = [r['stop_name_%d' % n] for n in range(1, 7)]
                filled = [x for x in names if x]
                if names[:len(filled)] != filled:
                    w('%s:%d stop_name_1 から順に詰めてください（途中に空きがあります）' % (name, i))
            key = (r['route_short_name'], r['trip_headsign'], r.get('origin_stop_name',''), r['board_stop_name'])
            if key in seen: w('%s:%d 重複キー %s' % (name, i, key))
            seen.add(key)
            if routes is not None and r['route_short_name'] and r['route_short_name'] not in routes:
                w('%s:%d 系統「%s」は現在のダイヤ（data.js）にありません' % (name, i, r['route_short_name']))
            elif routes is not None and r['trip_headsign'] != '*' and ivs(r['trip_headsign']) not in hs_by_route.get(r['route_short_name'], ()):
                w('%s:%d 「%s|%s」は現在のダイヤにない行先です' % (name, i, r['route_short_name'], r['trip_headsign']))
    return warn

def fill_route_ids(zip_path, front, side):
    with zipfile.ZipFile(zip_path) as z:
        txt = io.TextIOWrapper(z.open('routes.txt'), encoding='utf-8-sig', newline='')
        name_to_id = {}
        for r in csv.DictReader(txt):
            name = (r.get('route_short_name') or r.get('route_long_name') or '').strip()
            name_to_id.setdefault(name, r['route_id'])
    n = 0
    for rows in (front, side):
        for r in rows:
            if not r['route_id'] and r['route_short_name'] in name_to_id:
                r['route_id'] = name_to_id[r['route_short_name']]; n += 1
    return n

def write_csv(path, rows, cols):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        wri = csv.DictWriter(f, fieldnames=cols, lineterminator='\n')
        wri.writeheader()
        for r in rows: wri.writerow({c: r.get(c, '') for c in cols})

def main(argv):
    check = '--check' in argv
    gtfs = argv[argv.index('--gtfs') + 1] if '--gtfs' in argv else None
    fp, sp = os.path.join(ROOT, 'led_front.txt'), os.path.join(ROOT, 'led_side.txt')
    front = read_csv(fp, FRONT_COLS)
    side  = read_csv(sp, SIDE_COLS) if os.path.exists(sp) else []
    if gtfs:
        n = fill_route_ids(gtfs, front, side)
        write_csv(fp, front, FRONT_COLS); write_csv(sp, side, SIDE_COLS)
        print('route_id を %d 行補完して CSV を書き戻しました' % n)
    warn = validate(front, side, load_gd())
    print('front=%d side=%d 警告=%d' % (len(front), len(side), warn))
    if check: return 0
    # source 列はアプリで使わないので led.js には入れない（CSV が正本）
    strip = lambda rows, cols: [{c: r[c] for c in cols if c != 'source' and r[c] != ''} for r in rows]
    out = {'version': '0.1', 'front': strip(front, FRONT_COLS), 'side': strip(side, SIDE_COLS)}
    js = 'window.LED=' + json.dumps(out, ensure_ascii=False, separators=(',', ':')) + ';\n'
    open(os.path.join(ROOT, 'led.js'), 'w', encoding='utf-8').write(js)
    print('led.js を書き出しました (%d bytes)' % len(js.encode('utf-8')))
    return 0

if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

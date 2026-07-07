#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
名古屋市バス GTFS-JP → data.js 変換スクリプト
「これ乗っていいの？」プロジェクト用

使い方: python3 convert_gtfs.py <GTFSを展開したフォルダ> <出力data.jsパス>

※ 2026-03-28改正のGTFSから、公開中の data.js をバイト単位で完全再現できることを検証済み。

data.js の構造 (window.GD):
  stops[i]     = [停留所名, 緯度, 経度, のりば(platform_code), 接近情報URLパラメータ(b_xxxxx)]
  routes[r]    = 系統名 (route_short_name)
  services[s]  = ダイヤ名 (service_id)
  calendar[s]  = [月,火,水,木,金,土,日] の運行フラグ
  calendarDates{YYYYMMDD: {add:[s...], del:[s...]}}  例外日（祝日ダイヤ等）
  headsigns[h] = 行先表示
  patterns[p]  = [停留所index列]
  trips[t]     = [r, p, s, h, [分単位の発時刻列(patternと同じ長さ)]]
  yomi{停留所名: 読みがな}   (translations.txt ja-Hrkt)
  feed         = データ出典表記
  en{停留所名: 英語名}       (translations.txt en / 別文で追記)
"""
import csv, json, sys, os, re

def read_csv(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def hhmm_to_min(t):
    h, m, *_ = t.split(':')
    return int(h) * 60 + int(m)

def build(gtfs_dir):
    # ---- stops ----
    stops = []
    stopid_to_idx = {}
    for row in read_csv(os.path.join(gtfs_dir, 'stops.txt')):
        url = row.get('stop_url', '') or ''
        m = re.search(r'[?&]from=([^&]+)', url)
        param = m.group(1) if m else ''
        stopid_to_idx[row['stop_id']] = len(stops)
        stops.append([row['stop_name'], round(float(row['stop_lat']), 6),
                      round(float(row['stop_lon']), 6),
                      row.get('platform_code', '') or '', param])

    # ---- routes ----
    routes = []
    routeid_to_idx = {}
    for row in read_csv(os.path.join(gtfs_dir, 'routes.txt')):
        routeid_to_idx[row['route_id']] = len(routes)
        routes.append(row['route_short_name'] or row['route_long_name'])

    # ---- calendar ----
    services, calendar = [], []
    svc_to_idx = {}
    days = ['monday','tuesday','wednesday','thursday','friday','saturday','sunday']
    for row in read_csv(os.path.join(gtfs_dir, 'calendar.txt')):
        svc_to_idx[row['service_id']] = len(services)
        services.append(row['service_id'])
        calendar.append([int(row[d]) for d in days])

    # ---- calendar_dates ----
    calendar_dates = {}
    for row in read_csv(os.path.join(gtfs_dir, 'calendar_dates.txt')):
        d = row['date']
        if d not in calendar_dates:
            calendar_dates[d] = {'add': [], 'del': []}
        key = 'add' if row['exception_type'] == '1' else 'del'
        si = svc_to_idx.get(row['service_id'])
        if si is not None:
            calendar_dates[d][key].append(si)

    # ---- stop_times ----
    trip_stops = {}
    with open(os.path.join(gtfs_dir, 'stop_times.txt'), encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            trip_stops.setdefault(row['trip_id'], []).append(
                (int(row['stop_sequence']), stopid_to_idx[row['stop_id']],
                 hhmm_to_min(row['departure_time'])))
    for v in trip_stops.values():
        v.sort()

    # ---- trips / patterns / headsigns ----
    headsigns, patterns, trips = [], [], []
    hs_to_idx, pat_to_idx = {}, {}
    for row in read_csv(os.path.join(gtfs_dir, 'trips.txt')):
        st = trip_stops.get(row['trip_id'])
        if not st:
            continue
        pat = tuple(x[1] for x in st)
        times = [x[2] for x in st]
        if pat not in pat_to_idx:
            pat_to_idx[pat] = len(patterns)
            patterns.append(list(pat))
        hs = row.get('trip_headsign', '') or ''
        if hs not in hs_to_idx:
            hs_to_idx[hs] = len(headsigns)
            headsigns.append(hs)
        trips.append([routeid_to_idx[row['route_id']], pat_to_idx[pat],
                      svc_to_idx[row['service_id']], hs_to_idx[hs], times])

    # ---- translations ----
    yomi, en = {}, {}
    for row in read_csv(os.path.join(gtfs_dir, 'translations.txt')):
        if row['table_name'] == 'stops' and row['field_name'] == 'stop_name':
            key = row.get('field_value') or row.get('record_id') or ''
            if not key:
                continue
            if row['language'] == 'ja-Hrkt':
                yomi[key] = row['translation']
            elif row['language'] == 'en':
                en[key] = row['translation']

    # ---- feed ----
    feed = '名古屋市交通局 GTFS-JP'
    fi_path = os.path.join(gtfs_dir, 'feed_info.txt')
    if os.path.exists(fi_path):
        fi = read_csv(fi_path)
        if fi:
            d = fi[0].get('feed_start_date', '')
            if len(d) == 8:
                feed = '名古屋市交通局 GTFS-JP %s-%s-%s改正 (CC BY 4.0)' % (d[:4], d[4:6], d[6:8])

    GD = {'stops': stops, 'routes': routes, 'services': services, 'calendar': calendar,
          'calendarDates': calendar_dates, 'headsigns': headsigns, 'patterns': patterns,
          'trips': trips, 'yomi': yomi, 'feed': feed}
    return GD, en

def validate(GD, en):
    """変換結果の健全性チェック。おかしければ例外を投げて更新を中止させる。"""
    assert len(GD['stops']) > 3000, '停留所が少なすぎる: %d' % len(GD['stops'])
    assert len(GD['routes']) > 100, '系統が少なすぎる: %d' % len(GD['routes'])
    assert len(GD['trips']) > 20000, '便数が少なすぎる: %d' % len(GD['trips'])
    assert len(GD['patterns']) > 300 and len(GD['headsigns']) > 300
    assert len(GD['yomi']) > 1000 and len(en) > 1000, '読みがな/英語名が少なすぎる'
    ns, np, nsv, nh = len(GD['stops']), len(GD['patterns']), len(GD['services']), len(GD['headsigns'])
    for s in GD['stops']:
        assert isinstance(s[0], str) and s[0] and isinstance(s[1], float) and isinstance(s[2], float)
    for p in GD['patterns']:
        assert all(0 <= i < ns for i in p)
    for t in GD['trips']:
        r, p, sv, h, times = t
        assert 0 <= r < len(GD['routes']) and 0 <= p < np and 0 <= sv < nsv and 0 <= h < nh
        assert len(times) == len(GD['patterns'][p]), '時刻列とパターンの長さ不一致'
        assert all(times[i] <= times[i+1] for i in range(len(times)-1)), '時刻が逆行'
    assert len(GD['calendar']) == nsv

def write_datajs(GD, en, out_path):
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('window.GD=')
        f.write(json.dumps(GD, ensure_ascii=False, separators=(',', ':')))
        f.write(';window.GD.en=')
        f.write(json.dumps(en, ensure_ascii=False, separators=(',', ':')))
        f.write(';')

def main(gtfs_dir, out_path):
    GD, en = build(gtfs_dir)
    validate(GD, en)
    write_datajs(GD, en, out_path)
    print('OK: stops=%d routes=%d services=%d patterns=%d headsigns=%d trips=%d yomi=%d en=%d' %
          (len(GD['stops']), len(GD['routes']), len(GD['services']), len(GD['patterns']),
           len(GD['headsigns']), len(GD['trips']), len(GD['yomi']), len(en)))

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GTFS-JP → data.js 変換スクリプト（複数フィード対応版）
「これ乗っていいの？」プロジェクト用

使い方:
  python3 convert_gtfs.py <市バスGTFSフォルダ> <出力data.jsパス>
  python3 convert_gtfs.py <市バスGTFSフォルダ> <SRT GTFSフォルダ> <出力data.jsパス>
    …フォルダを2つ以上並べると順にマージする。1つ目＝主フィード（名古屋市交通局・市バス）、
      2つ目以降＝追加フィード（名古屋市住宅都市局・SRTなど）。

※ 市バス1フィードだけで変換した場合、v3.97時点の公開data.jsをバイト単位で完全再現できる
   （2026-08-21検証済み＝マージ機構が市バス部分に一切波及しないことの担保）。

data.js の構造 (window.GD):
  stops[i]     = [停留所名, 緯度, 経度, のりば(platform_code), 接近情報URLパラメータ(b_xxxxx)]
  routes[r]    = 系統名 (route_short_name。無ければ route_long_name＝SRTは「名駅－栄ルート」等)
  services[s]  = ダイヤ名 (service_id)
  calendar[s]  = [月,火,水,木,金,土,日] の運行フラグ
  calendarDates{YYYYMMDD: {add:[s...], del:[s...]}}  例外日（祝日ダイヤ等）
  headsigns[h] = 行先表示
  patterns[p]  = [停留所index列]
  trips[t]     = [r, p, s, h, [分単位の発時刻列], hsSeq?]
                 hsSeq＝6番目・省略可＝停留所ごとの行先index列（patternと同じ長さ）。
                 GTFSのstop_headsignがある便（SRTの周回便）だけに付く。末尾の「 行き」は
                 落として登録する（アプリの行先モデル＝地名。市バスは全便省略＝従来と同形）
  yomi{停留所名: 読みがな}   (translations.txt ja-Hrkt)
  feed         = データ出典表記（複数フィードは「＋」でつなぐ）
  feeds        = [{name, s0, r0, sv0, h0, p0, t0}] 各フィードの出典と開始オフセット
                 （s0=stops開始index, r0=routes, sv0=services, h0=headsigns, p0=patterns, t0=trips）
  calPeriod    = {serviceIndex: [開始YYYYMMDD, 終了YYYYMMDD]} 運行期間（追加フィードのみ。
                 SRTは2026-09-11開始＝それより前に便を出さないため。主フィード（市バス）には
                 意図的に付けない＝期限切れでもアプリは古いダイヤで動き続ける安全側運転を維持）
  tripIds      = {tripIndex: GTFSのtrip_id} （追加フィードのみ。GTFS-RTのTripUpdates照合用）
  stopIds      = {stopIndex: GTFSのstop_id} （追加フィードのみ。GTFS-RTのVehiclePosition照合用）
  en{停留所名: 英語名}       (translations.txt en / 別文で追記。追加フィードは系統名の英語も入る)

追加フィード（SRT）の取り込み規約:
  ・IDの衝突回避＝各フィードのID→index対応表はフィードごとに独立（stop_id等が同じ文字列でも別index）
  ・停留所は「名前」で市バスと自然に合流する（栄・名古屋駅など＝同名なら同じ停留所グループ。
    のりば単位では別物として残る＝GPS最寄り判定・地図表示はそのまま働く）
  ・yomi/enの同名キーは主フィード優先（上書きしない）
  ・platform_codeが空の追加フィード停留所には「SRT」を入れる（のりば表示が「のりば?」になるのを防ぐ）
"""
import csv, json, sys, os, re

def read_csv(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def hhmm_to_min(t):
    h, m, *_ = t.split(':')
    return int(h) * 60 + int(m)

def _strip_iki(s):
    """stop_headsignの末尾「 行き」を落とす（SRTの表記規約。アプリの行先モデル＝地名）"""
    return re.sub(r'[ 　]*行き$', '', s)

def _feed_credit(gtfs_dir, default_name):
    fi_path = os.path.join(gtfs_dir, 'feed_info.txt')
    if os.path.exists(fi_path):
        fi = read_csv(fi_path)
        if fi:
            d = fi[0].get('feed_start_date', '')
            if len(d) == 8:
                return '%s %s-%s-%s改正 (CC BY 4.0)' % (default_name, d[:4], d[4:6], d[6:8])
    return default_name

def build_feed(gtfs_dir, GD, en, extra=False, pole_default='', credit_name=''):
    """1フィードをGDへ追記する。extra=True＝追加フィード（SRT）扱い＝
       calPeriod・tripIds・stopIds を出す／platform_code空にpole_defaultを入れる"""
    feed_meta = {'name': credit_name,
                 's0': len(GD['stops']), 'r0': len(GD['routes']), 'sv0': len(GD['services']),
                 'h0': len(GD['headsigns']), 'p0': len(GD['patterns']), 't0': len(GD['trips'])}

    # ---- stops ----
    stops = GD['stops']
    stopid_to_idx = {}
    stopid_to_name = {}
    for row in read_csv(os.path.join(gtfs_dir, 'stops.txt')):
        url = row.get('stop_url', '') or ''
        m = re.search(r'[?&]from=([^&]+)', url)
        param = m.group(1) if m else ''
        pc = row.get('platform_code', '') or ''
        if extra and not pc:
            pc = pole_default
        idx = len(stops)
        stopid_to_idx[row['stop_id']] = idx
        stopid_to_name[row['stop_id']] = row['stop_name']
        if extra:
            GD['stopIds'][idx] = row['stop_id']
        stops.append([row['stop_name'], round(float(row['stop_lat']), 6),
                      round(float(row['stop_lon']), 6), pc, param])

    # ---- routes ----
    routes = GD['routes']
    routeid_to_idx = {}
    routeid_to_name = {}
    for row in read_csv(os.path.join(gtfs_dir, 'routes.txt')):
        routeid_to_idx[row['route_id']] = len(routes)
        name = row['route_short_name'] or row['route_long_name']
        routeid_to_name[row['route_id']] = name
        routes.append(name)

    # ---- calendar ----
    services, calendar = GD['services'], GD['calendar']
    svc_to_idx = {}
    days = ['monday','tuesday','wednesday','thursday','friday','saturday','sunday']
    for row in read_csv(os.path.join(gtfs_dir, 'calendar.txt')):
        si = len(services)
        svc_to_idx[row['service_id']] = si
        services.append(row['service_id'])
        calendar.append([int(row[d]) for d in days])
        if extra:
            st, ed = row.get('start_date', '') or '', row.get('end_date', '') or ''
            if len(st) == 8 and len(ed) == 8:
                GD['calPeriod'][si] = [st, ed]

    # ---- calendar_dates ----
    calendar_dates = GD['calendarDates']
    for row in read_csv(os.path.join(gtfs_dir, 'calendar_dates.txt')):
        d = row['date']
        if d not in calendar_dates:
            calendar_dates[d] = {'add': [], 'del': []}
        key = 'add' if row['exception_type'] == '1' else 'del'
        si = svc_to_idx.get(row['service_id'])
        if si is not None:
            calendar_dates[d][key].append(si)

    # ---- stop_times ----（stop_headsignも拾う＝空文字なら従来どおり無視）
    trip_stops = {}
    with open(os.path.join(gtfs_dir, 'stop_times.txt'), encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            trip_stops.setdefault(row['trip_id'], []).append(
                (int(row['stop_sequence']), stopid_to_idx[row['stop_id']],
                 hhmm_to_min(row['departure_time']),
                 (row.get('stop_headsign', '') or '').strip()))
    for v in trip_stops.values():
        v.sort()

    # ---- trips / patterns / headsigns ----
    headsigns, patterns, trips = GD['headsigns'], GD['patterns'], GD['trips']
    hs_to_idx = {h: i for i, h in enumerate(headsigns)}   # 行先はフィード横断で共有（同名は同index）
    pat_to_idx = {}
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
        trip = [routeid_to_idx[row['route_id']], pat_to_idx[pat],
                svc_to_idx[row['service_id']], hs_to_idx[hs], times]
        # 停留所ごとの行先（stop_headsign）：1つでも入っていればhsSeqを付ける
        if any(x[3] for x in st):
            seq = []
            for x in st:
                s_hs = _strip_iki(x[3]) if x[3] else hs
                if s_hs not in hs_to_idx:
                    hs_to_idx[s_hs] = len(headsigns)
                    headsigns.append(s_hs)
                seq.append(hs_to_idx[s_hs])
            trip.append(seq)
        if extra:
            GD['tripIds'][len(trips)] = row['trip_id']
        trips.append(trip)

    # ---- translations ----（キー＝field_value。無ければrecord_id（stop_id/route_id）から名前を引く。
    #      同名キーは主フィード優先＝上書きしない）
    yomi = GD['yomi']
    for row in read_csv(os.path.join(gtfs_dir, 'translations.txt')):
        tbl, fld = row.get('table_name', ''), row.get('field_name', '')
        if tbl == 'stops' and fld == 'stop_name':
            key = row.get('field_value') or stopid_to_name.get(row.get('record_id') or '', '')
            if not key:
                continue
            if row['language'] == 'ja-Hrkt' and key not in yomi:
                yomi[key] = row['translation']
            elif row['language'] == 'en' and key not in en:
                en[key] = row['translation']
        elif extra and tbl == 'routes' and fld in ('route_long_name', 'route_short_name') and row['language'] == 'en':
            # 系統名の英語（SRT＝Nagoya Sta. - Sakae Route等）。主フィード（市バス）には適用しない＝
            # 従来のen辞書を1キーも変えない（byte一致の担保。市バス系統名の英語は未使用のため不要）
            key = row.get('field_value') or routeid_to_name.get(row.get('record_id') or '', '')
            if key and key not in en:
                en[key] = row['translation']

    GD['feeds'].append(feed_meta)
    return GD, en

def build(gtfs_dirs):
    """gtfs_dirs＝フォルダのリスト（1つ目＝市バス主フィード、2つ目以降＝SRT等の追加フィード）。
       文字列1つでも可（従来互換）"""
    if isinstance(gtfs_dirs, str):
        gtfs_dirs = [gtfs_dirs]
    GD = {'stops': [], 'routes': [], 'services': [], 'calendar': [],
          'calendarDates': {}, 'headsigns': [], 'patterns': [], 'trips': [],
          'yomi': {}, 'feed': '', 'feeds': [], 'calPeriod': {}, 'tripIds': {}, 'stopIds': {}}
    en = {}
    credits = []
    for i, d in enumerate(gtfs_dirs):
        extra = (i > 0)
        name = '名古屋市（住宅都市局）SRT GTFS' if extra else '名古屋市交通局 GTFS-JP'
        credit = _feed_credit(d, name)
        credits.append(credit)
        build_feed(d, GD, en, extra=extra, pole_default='SRT', credit_name=credit)
    GD['feed'] = '＋'.join(credits)
    # 追加フィードが無いときは追加キーを落とす（市バス単独＝従来のdata.jsとバイト一致）
    if len(gtfs_dirs) == 1:
        for k in ('feeds', 'calPeriod', 'tripIds', 'stopIds'):
            del GD[k]
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
        r, p, sv, h, times = t[0], t[1], t[2], t[3], t[4]
        assert 0 <= r < len(GD['routes']) and 0 <= p < np and 0 <= sv < nsv and 0 <= h < nh
        assert len(times) == len(GD['patterns'][p]), '時刻列とパターンの長さ不一致'
        assert all(times[i] <= times[i+1] for i in range(len(times)-1)), '時刻が逆行'
        assert len(t) <= 6
        if len(t) == 6:  # hsSeq＝停留所ごとの行先
            assert len(t[5]) == len(GD['patterns'][p]), 'hsSeqとパターンの長さ不一致'
            assert all(0 <= x < nh for x in t[5])
    assert len(GD['calendar']) == nsv
    # 追加フィード（SRT）が入っているときの追加チェック
    if 'feeds' in GD:
        assert len(GD['feeds']) >= 2
        for si, pr in GD['calPeriod'].items():
            assert len(pr) == 2 and len(pr[0]) == 8 and len(pr[1]) == 8 and pr[0] <= pr[1]
        assert '名駅－栄ルート' in GD['routes'] and '名駅－名城ルート' in GD['routes'], 'SRTの2ルートが無い'
        srt_trips = [t for t in GD['trips'] if len(t) == 6]
        assert len(srt_trips) >= 10, 'SRTのhsSeq付き便が少なすぎる: %d' % len(srt_trips)

def write_datajs(GD, en, out_path):
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('window.GD=')
        f.write(json.dumps(GD, ensure_ascii=False, separators=(',', ':')))
        f.write(';window.GD.en=')
        f.write(json.dumps(en, ensure_ascii=False, separators=(',', ':')))
        f.write(';')

def main(argv):
    # 最後の引数＝出力パス、それ以外＝GTFSフォルダ（1つ以上）
    dirs, out_path = argv[:-1], argv[-1]
    GD, en = build(dirs)
    validate(GD, en)
    write_datajs(GD, en, out_path)
    print('OK: stops=%d routes=%d services=%d patterns=%d headsigns=%d trips=%d yomi=%d en=%d feeds=%d' %
          (len(GD['stops']), len(GD['routes']), len(GD['services']), len(GD['patterns']),
           len(GD['headsigns']), len(GD['trips']), len(GD['yomi']), len(en), len(dirs)))

if __name__ == '__main__':
    main(sys.argv[1:])

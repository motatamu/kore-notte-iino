#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
名古屋市バス ダイヤ自動更新スクリプト（GitHub Actionsから毎週実行される）

やること:
 1. 名古屋市オープンデータカタログ(data.bodik.jp)のAPIでGTFS-JPデータセットを確認
 2. 「改正日（feed_start_date）が今日以前」の最新データを選ぶ
    （改正日前に先行掲載されることがあるため。例: 2026-03-28改正版は3/18掲載）
 3. 今使っているものと同じなら何もしない（exit 0, 標準出力 "no-change"）
 4. 新しければダウンロード→変換→検証→ data.js と tools/data-version.txt を書き換え
    （標準出力 "updated"）
 5. 変換や検証に失敗したら例外で異常終了（→ Actionsが失敗し、GitHubからメール通知が届く。
    data.jsは書き換えないので、アプリは古いダイヤのまま動き続ける＝安全側）

テスト用の環境変数:
  AU_API_URL   … カタログAPIのURLを差し替え（file:// 可）
  AU_ZIP_FILE  … ダウンロードせずローカルのzipを使う
  AU_TODAY     … 「今日」をYYYYMMDDで固定
"""
import json, os, sys, tempfile, zipfile, urllib.request
from datetime import datetime, timedelta, timezone

import convert_gtfs

API_URL = os.environ.get('AU_API_URL',
    'https://data.bodik.jp/api/3/action/package_show?id=231002_7109030000_bus-gtfs-jp')
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # tools/ の一つ上
DATA_JS = os.path.join(REPO_ROOT, 'data.js')
VERSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data-version.txt')

def today_jst():
    if os.environ.get('AU_TODAY'):
        return os.environ['AU_TODAY']
    return datetime.now(timezone(timedelta(hours=9))).strftime('%Y%m%d')

def fetch_json(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read().decode('utf-8'))

def download(url, dest):
    with urllib.request.urlopen(url, timeout=300) as r, open(dest, 'wb') as f:
        f.write(r.read())

def feed_start_date(zip_path):
    """zipの中のfeed_info.txtから改正日(YYYYMMDD)を読む。無ければ '00000000'（=常に有効扱い）"""
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if n.endswith('feed_info.txt')]
        if not names:
            return '00000000'
        text = z.read(names[0]).decode('utf-8-sig')
        lines = [l for l in text.splitlines() if l.strip()]
        header = lines[0].split(',')
        row = lines[1].split(',')
        try:
            return row[header.index('feed_start_date')].strip()
        except (ValueError, IndexError):
            return '00000000'

def main():
    data = fetch_json(API_URL)
    resources = [r for r in data['result']['resources']
                 if (r.get('format') or '').upper() == 'ZIP' and r.get('url')]
    if not resources:
        raise RuntimeError('カタログにZIPリソースが見つからない')
    # 新しい順（登録日時の降順）
    resources.sort(key=lambda r: r.get('created') or '', reverse=True)

    current = ''
    if os.path.exists(VERSION_FILE):
        current = open(VERSION_FILE, encoding='utf-8').readline().strip()  # 1行目がマーカー

    today = today_jst()
    with tempfile.TemporaryDirectory() as tmp:
        for res in resources:
            marker = '%s|%s' % (res['id'], res.get('last_modified') or res.get('created') or '')
            if marker == current:
                print('no-change')  # 今使っているものが最新
                return
            zip_path = os.environ.get('AU_ZIP_FILE')
            if not zip_path:
                zip_path = os.path.join(tmp, 'gtfs.zip')
                download(res['url'], zip_path)
            start = feed_start_date(zip_path)
            if start > today:
                # 改正日がまだ先 → 先行掲載。ひとつ前のリソースを見る
                print('skip (改正日%sはまだ先): %s' % (start, res.get('name', '')), file=sys.stderr)
                continue
            # 採用: 変換→検証→書き込み
            gtfs_dir = os.path.join(tmp, 'gtfs')
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(gtfs_dir)
            GD, en = convert_gtfs.build(gtfs_dir)
            convert_gtfs.validate(GD, en)
            convert_gtfs.write_datajs(GD, en, DATA_JS)
            with open(VERSION_FILE, 'w', encoding='utf-8') as f:
                f.write(marker + '\n')
                f.write('%s (%s改正)\n' % (res.get('name', ''), start))
            print('updated')
            return
    raise RuntimeError('有効な（改正日到来済みの）GTFSリソースが見つからない')

if __name__ == '__main__':
    main()

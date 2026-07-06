# kore-notte-iino
# これ乗っていいの？（Kore Notte Iino?）

名古屋市バス版プロトタイプ  
https://motatamu.github.io/kore-notte-iino/

「目の前に来たこのバス、乗っていいの？」という不安を解消することに特化したWebアプリです。
降りたいバス停を登録すると、いまいるバス停（のりば単位）で乗ってよいバスを、
実車の行先表示（LED）を再現したドット表示で教えます。

## 特徴
- のりば単位の案内（同じ名前のバス停でも、正しいのりばへ地図と目印で誘導）
- いちばん早く目的地に着くバスを推薦（循環バスの遠回りを回避）
- 実車のLED行先表示をドット単位で自動再現
- 7言語対応（日本語・英語・中文・한국어・Tiếng Việt・Bahasa Indonesia・Filipino）
- 最終バス警告・公式バス接近情報へのリンク

## データ・素材のクレジット
- バスデータ：名古屋市交通局「市バスGTFS-JPデータ」（CC BY 4.0）
- 地図：© OpenStreetMap contributors（タイル・目印データ）
- 地図表示：Leaflet / Leaflet.GestureHandling
- ドットフォント：PixelMplus font by itouhiro（M+ FONT LICENSE）
- LED表示レイアウトの参考：LED再現置き場（青石橋さん）

## 注意
時刻表ベースの案内です。遅延・運休には対応していません（プロトタイプ）。

公共交通オープンデータチャレンジ2026 応募作品（予定）

# マニュアル変換ガイド

ビルド方法は [README](../README.md#マニュアル変換ツール) を参照してください。
以下はリポジトリのルートで実行します。Windows の PowerShell では `./manualbook` を
`.\manualbook.exe` に置き換えてください。

## 取得と変換

[manifest.json](../manifest.json) を入力にし、取得 → Markdown 変換 → 索引作成までを行います。
初回は冊子により数分以上かかります。取得済みの資料は再利用するため、通常は `build` だけで足ります。

```console
./manualbook build
./manualbook build -only 8-10/cr
./manualbook build -only 8-10/cr -force
```

取得または変換だけを実行することもできます。

| サブコマンド | 処理 |
| --- | --- |
| `build` | 取得・変換・索引作成 |
| `fetch` | HTML と図を取得キャッシュに保存 |
| `md` | 取得キャッシュから Markdown と索引を作成（ネットワーク取得なし） |

```console
./manualbook fetch -only 8-5/me-ug
./manualbook md -only 8-5/me-ug
./manualbook build -h
```

引数はサブコマンドの後に指定します。

| 引数 | 既定値・用途 |
| --- | --- |
| `-manifest PATH` | `manifest.json`。対象資料とトレインの説明 |
| `-cache PATH` | `cache`。取得キャッシュのルート |
| `-manuals PATH` | `AIR_TOOLKIT_MANUALS` → `~/.air-toolkit/manuals/`。変換結果のルート |
| `-only TRAIN/BOOK` | 未指定なら全資料。例: `8-10/cr` |
| `-force` | `fetch` / `build` で取得済みの資料も取り直す |
| `-delay DURATION` | `1s`。リクエスト間隔。1 秒以上を保つ |

`-manuals` は `<train>/<book>/` の親ディレクトリを指定します。`air-manual` でも同じ資料を読むには
環境変数 `AIR_TOOLKIT_MANUALS` をそのルートに設定してください。

**変換時は対象の `<manuals>/<train>/<book>/` を丸ごと消して書き直します。**
README.md が無い非空ディレクトリは消さずに止めますが、README.md があれば削除対象になります。
資料専用のルートを使い、生成済みの冊子ディレクトリに手書きファイルを置かないでください。
`md` も同じ書き直しを行います。

章の一覧は目次ページの `ul#bookToc` から決め、リンクを辿って対象を広げません。
UA は `manualbook/0.1 (+https://github.com/yuu61/air-toolkit)` とし、Accept / Accept-Language を送ります。
403 の切り分けではブラウザの UA に置き換えず、この 3 つを確認します。
一時的な通信失敗、HTTP 429 / 5xx は最大 3 回試します。
図の取得失敗は警告して続行し、本文には元画像の URL が残ります。

複数冊の処理では 1 冊が失敗しても残りを続け、最後に成功数を表示します。
1 冊でも失敗した場合は終了コード 1、引数の誤りは 2 です。
定期取得は行いません。Cisco の更新情報を見て人が manifest を直し、必要な冊子を取り直します。

## 対象資料

対象一覧の正本は manifest です。ここでのトレインは実機の実行版を断定するものではありません。

| train | book | 冊子 |
| --- | --- | --- |
| `8-5` | `cr` | Cisco Wireless Controller Command Reference, Release 8.5 |
| `8-5` | `cg` | Cisco Wireless Controller Configuration Guide, Release 8.5 |
| `8-5` | `me-ug` | Cisco Mobility Express User Guide, Release 8.5 |
| `8-5` | `me-dg` | Cisco Mobility Express Deployment Guide, Release 8.5 |
| `8-5` | `me-rn` | Release Notes for Cisco Mobility Express, Release 8.5 |
| `8-10` | `cr` | Cisco Wireless Controller Command Reference, Release 8.10 |
| `8-10` | `cg` | Cisco Wireless Controller Configuration Guide, Release 8.10 |
| `8-10` | `ap-cr` | Cisco Aironet Wave 2 and Catalyst Wi-Fi6 Access Point Command Reference, Release 8.10 |
| `8-10` | `me-ug` | Cisco Mobility Express User Guide, Release 8.10 |
| `8-10` | `me-cr` | Cisco Mobility Express Command Reference, Release 8.10 |
| `8-10` | `me-rn` | Release Notes for Cisco Mobility Express, Release 8.10 |

manifest では `8-5` を 2504 / 5508 / 7510 / WiSM2 / 8510 の最終トレイン、
`8-10` を 3504 / 5520 / 8540 / vWLC / Mobility Express の最終トレインとして整理しています。
実機の実行版と対象資料の版を照合し、2504 に 8.10 の仕様を適用しないでください。

Mobility Express 8.5 に独立した `me-cr` はありません。User Guide の Controller CLI Commands は
手順なので `commands.tsv` には載らず、`sections.tsv` の `ctrlr_cli#…` から引きます。
`ap-cr` は AP 自身の CLI で、コントローラーや IOS XE 用の資料とは区別します。

## 出力と索引

```text
<manuals>/8-10/cr/
  README.md                     出典・取得日・トレイン・最終機種・章一覧
  config_commands_a_to_i/       元の 1 ページに対応する章
    README.md                   章タイトル・章直下の本文・トピック一覧
    config_aaa_auth.md          コマンド 1 つ / 機能 1 つの本文
    config_aaa_auth_mgmt.md
  images/                       本文の図
  commands.tsv
  sections.tsv
```

章直下のトピックを 1 ファイルにし、32 KB を超えるトピックは子トピックを再帰的に別ファイルへ
分けます。元のファイルには子への一覧リンクを残します。分ける子が無い本文は 32 KB を超える場合もあります。
先頭見出しは `#`、ファイル名は見出しから作り（`config aaa auth` → `config_aaa_auth.md`）、
同じ章で重複したら `_2`, `_3` …を付けます。図は `../images/`、冊子内のリンクは分割先への相対パスです。

索引はタブ区切りで、先頭行が列名です。

| 索引 | 列 | 用途 |
| --- | --- | --- |
| `commands.tsv` | `command / entry / file / line / source` | 構文を持つコマンド項目 |
| `sections.tsv` | `section / title / file / line / source` | 全 topictitle 見出し |

`file` は冊子ルートからの相対パス、`line` は本文の見出し行（1 始まり）です。
`section` は「章#アンカー」で、ファイルの分け方に依りません。
`source` は元ページの URL とアンカーです。

```console
rg -n -i -F "config wlan" "<manuals>/8-10/cr/commands.tsv"
rg -n -i -F "WLAN" "<manuals>/8-10/cg/sections.tsv"
rg -n -F "ctrlr_cli#" "<manuals>/8-5/me-ug/sections.tsv"
```

`rg -n` の番号は索引内の行番号です。本文の位置には TSV の `line` を使います。
候補の `file` を全文読み、関係する子トピック・脚注・図まで確認してください。
手順中の CLI がすべて `commands.tsv` に載るわけではありません。
設定ガイドの Restrictions など、箇条書きの制約項目はコマンド索引に含めません。

章内目次の全アンカーと見出しの対応を検証してから分割します。変換で止まった場合は
欠けたトピックや見出しを調べ、検証を緩めず変換器を直します。
開発時の確認方法は [開発ガイド](develop.md#マニュアル変換の確認) を参照してください。

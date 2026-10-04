# マニュアル変換ガイド

Cisco 公式の HTML マニュアルを取得し、トピック単位の Markdown と TSV 索引 (`commands.tsv`, `sections.tsv`) に変換する `manualbook` の利用ガイドです。

## 概要とビルド

`manualbook` は [manifest.json](../manifest.json) の定義に基づき、取得・変換・索引作成を一括で行います。

```console
# ビルド
go build -ldflags="-s -w" ./cmd/manualbook

# 実行 (全資料の取得と変換)
./manualbook build
# Windows PowerShell: .\manualbook.exe build
```

> [!NOTE]
> Windows Defender の誤検知を防止するため、ビルド時は `-ldflags="-s -w"` を付与します。

## サブコマンドとオプション

### サブコマンド
| サブコマンド | 処理内容 |
| --- | --- |
| `build` | 資料の取得、Markdown 変換、索引作成（通常はこちらを使用） |
| `fetch` | HTML と画像を取得キャッシュにダウンロード |
| `md` | 取得済みキャッシュから Markdown と索引を生成（通信なし） |

### 主なオプション
サブコマンドの後に指定します（例: `./manualbook build -only 8-10/cr`）。

| オプション | 既定値 | 説明 |
| --- | --- | --- |
| `-only TRAIN/BOOK` | (全冊子) | 処理対象を単一の冊子に限定（例: `8-10/cr`） |
| `-force` | `false` | 取得済みキャッシュを無視して再取得 |
| `-delay DURATION` | `1s` | リクエスト間隔（1 秒以上を推奨） |
| `-manifest PATH` | `manifest.json` | 資料定義ファイルのパス |
| `-cache PATH` | `cache` | HTML / 画像の取得キャッシュディレクトリ |
| `-manuals PATH` | `~/.air-toolkit/manuals/` | 変換先ディレクトリ（環境変数 `AIR_TOOLKIT_MANUALS` も参照） |

> [!WARNING]
> 変換時、対象冊子の出力先ディレクトリ（`<manuals>/<train>/<book>/`）は**完全に削除されてから再生成**されます。

## 対象資料一覧

[manifest.json](../manifest.json) に定義されている資料です。

| train | book | 冊子名・内容 | 主な対象機種 |
| --- | --- | --- | --- |
| `8-5` | `cr` | Controller Command Reference 8.5 | 2504 / 5508 / 7510 / WiSM2 / 8510 |
| `8-5` | `cg` | Controller Configuration Guide 8.5 | 同上 |
| `8-5` | `me-ug` | Mobility Express User Guide 8.5 | Mobility Express (8.5) |
| `8-5` | `me-dg` | Mobility Express Deployment Guide 8.5 | 同上 |
| `8-5` | `me-rn` | Mobility Express Release Notes 8.5 | 同上 |
| `8-10` | `cr` | Controller Command Reference 8.10 | 3504 / 5520 / 8540 / vWLC |
| `8-10` | `cg` | Controller Configuration Guide 8.10 | 同上 |
| `8-10` | `ap-cr` | Wave 2 / Catalyst Wi-Fi 6 AP Command Reference 8.10 | Aironet AP 単体 CLI |
| `8-10` | `me-ug` | Mobility Express User Guide 8.10 | Mobility Express (8.10) |
| `8-10` | `me-cr` | Mobility Express Command Reference 8.10 | 同上 |
| `8-10` | `me-rn` | Mobility Express Release Notes 8.10 | 同上 |

- **Mobility Express 8.5 の CLI**: 独立した `me-cr` がないため、`me-ug` の「Controller CLI Commands」章（`sections.tsv` の `ctrlr_cli#...`）から検索します。
- **AP CLI**: `ap-cr` は AP 自身の CLI であり、WLC / コントローラー CLI とは構文が異なります。

## 出力構造と索引

### ディレクトリ構成
```text
<manuals>/8-10/cr/
  README.md                     出典、取得日、章一覧
  config_commands_a_to_i/       章単位のディレクトリ (元の 1 ページに対応)
    README.md                   章タイトル、概要、トピック一覧
    config_aaa_auth.md          トピック単位の本文 (1 コマンド / 1 機能)
    config_aaa_auth_mgmt.md
  images/                       本文中の画像
  commands.tsv                  コマンド索引
  sections.tsv                  セクション (見出し) 索引
```

- **トピック分割**: 章直下のトピックごとに 1 ファイルに分割されます。32 KB を超えるトピックは子トピックが再帰的に別ファイルへ分割されます。
- **見出しとリンク**: 各ファイルの先頭見出しは `#` に調整され、本文内のリンクは分割先ファイルへの相対パスに解決されます。

### 索引ファイル (TSV)
タブ区切りテキストで、先頭行にヘッダーが含まれます。

| 索引 | 列構成 | 用途 |
| --- | --- | --- |
| `commands.tsv` | `command / entry / file / line / source` | コマンド構文を持つ項目（構文検索） |
| `sections.tsv` | `section / title / file / line / source` | すべての見出し（機能解説・手順・制約の検索） |

- `file`: 冊子ルートからの相対パス
- `line`: 該当見出しの行番号 (1 始まり)
- `source`: Cisco 公式ドキュメントの元 URL

```console
# コマンド構文の検索例
rg -n -i -F "config wlan" "<manuals>/8-10/cr/commands.tsv"

# 機能説明・設定手順の検索例
rg -n -i -F "WLAN" "<manuals>/8-10/cg/sections.tsv"
```

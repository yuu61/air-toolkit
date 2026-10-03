# air-toolkit

Cisco AireOS WLC / Mobility Express と Aironet AP を運用するための SSH CLI、エージェント向け skill、参照マニュアルを作る HTML → Markdown 変換ツールです。
Wave 2 / Catalyst Wi-Fi 6 AP 自身の CLI も扱います。Catalyst 9800 の IOS XE は対象外です。

## 運用ツールと skills

`air-ssh` は Python 3.10 以降で動く SSH CLI です。skill はこの CLI やローカル資料を利用します。

| Skill | 用途 | 機器への接続 |
| --- | --- | --- |
| [air-ssh](skills/air-ssh/SKILL.md) | 状態確認、設定変更、WLAN サイクル、設定保存、AP 自身の CLI 操作 | あり |
| [air-manual](skills/air-manual/SKILL.md) | 構文・手順・制約・対応機種・トレイン間の違いを調べる | なし |

### インストール

```console
git clone https://github.com/yuu61/air-toolkit "$HOME/.agents/skills/air-toolkit"
uv tool install -e "$HOME/.agents/skills/air-toolkit"
```

`air-ssh` が見つからない場合は `uv tool update-shell` を実行し、ターミナルとエージェントを開き直します。

更新は `git -C "$HOME/.agents/skills/air-toolkit" pull` で本体と skill に反映されます。
依存パッケージが変わった場合は `uv tool install --reinstall -e "$HOME/.agents/skills/air-toolkit"`を再実行します。
プラグインを読み込んだセッションは開き直してください。

### 旧名 aironet からの移行

旧版を uv tool で導入済みの場合は、`uv tool uninstall aironet` の後に上の導入手順で
`air-toolkit` をインストールします。既存のクローンを使う場合は、リポジトリのルートで
`git remote set-url origin https://github.com/yuu61/air-toolkit.git` を実行します。
CLI の `air-ssh`、マニュアル変換の `manualbook`、skill の `air-ssh` / `air-manual` は同じ名前で使えます。

| 設定 | 旧名 | 新名 |
| --- | --- | --- |
| 標準クローン先 | `~/.agents/skills/aironet` | `~/.agents/skills/air-toolkit` |
| インベントリ・資料の標準保存先 | `~/.aironet/` | `~/.air-toolkit/` |
| インベントリの指定 | `AIRONET_INVENTORY` | `AIR_TOOLKIT_INVENTORY` |
| 機器の指定 | `AIRONET_DEVICE` | `AIR_TOOLKIT_DEVICE` |
| 資料の指定 | `AIRONET_MANUALS` | `AIR_TOOLKIT_MANUALS` |

既存の `devices.json` と `manuals/` は新しい保存先へ移すか、`AIR_TOOLKIT_INVENTORY` と
`AIR_TOOLKIT_MANUALS` に現在のパスを指定して使います。環境変数を使っている場合は名前も更新してください。

### 接続先と基本操作

`~/.air-toolkit/devices.json` に機器を定義します。以下のアドレスと資格情報は例です。

```json
{
  "devices": {
    "wlc": {
      "host": "192.0.2.1",
      "username": "admin",
      "password": "YOUR_PASSWORD"
    },
    "ap1": {
      "kind": "ap",
      "host": "192.0.2.17",
      "username": "admin",
      "password": "YOUR_PASSWORD",
      "enable_password": "YOUR_ENABLE_SECRET"
    }
  }
}
```

`air-ssh --list` インベントリの場所と機器名・ホスト・ユーザー名・種別を表示します。
対象は `--device NAME`（短縮形 `-d`）または `AIR_TOOLKIT_DEVICE` で明示します。

```console
air-ssh --device wlc "show sysinfo"
air-ssh --device wlc "show ap summary" "show client summary"
air-ssh --device ap1 "show version" "show capwap client rcb"
```

WLAN を止める必要がある変更には、変更コマンドの直前に `--cycle-wlan ID` を置きます。
処理後に元の有効・無効状態へ戻して確認します。設定値の変更を取り消す機能ではありません。

```console
air-ssh --device wlc --cycle-wlan 1 "config wlan max-associated-clients 50 1"
air-ssh --device wlc "show wlan 1"
air-ssh --device wlc --save
```

対応する確認プロンプトには CLI が自動で `y` を返します。実行前に対象と変更内容を確認してください。
`--cycle-wlan` と `--save` はコントローラー専用です。既知のエラーやタイムアウトでは後続処理と保存を止めます。
認証情報の優先順位、複数 WLAN の操作順、復旧とエラーの扱いは [SSH 操作ガイド](docs/air-ssh.md) を参照してください。

## マニュアル変換ツール

`manualbook` は [manifest.json](manifest.json) にある Cisco の HTML 資料を取得し、
トピック単位の Markdown と `commands.tsv` / `sections.tsv` に変換する Go 製のツールです。
Go は [go.mod](go.mod) に対応する版を使い、クローンのルートで実行します。

```console
go build -ldflags="-s -w" ./cmd/manualbook
./manualbook build
```

Windows では `manualbook.exe` ができるので、PowerShell では `.\manualbook.exe build` と実行します。
`-ldflags="-s -w"` は Windows Defender の誤検知を避けるために付けています。

- 取得キャッシュは `cache/`、変換結果は `~/.air-toolkit/manuals/<train>/<book>/` に置きます。
- 2 回目以降は取得済みの資料を再利用します。取り直すときは `-force`、1 冊だけなら `-only 8-10/cr`。
- 変換対象の冊子ディレクトリは消して書き直します。資料専用の出力先を使ってください。

対象資料、引数、出力形式と索引の読み方は [マニュアル変換ガイド](docs/manualbook.md) を参照してください。
変換済み資料があれば、参照時に `manualbook` 自体は不要です。

## 開発

開発環境、`make check` による検証、Python の版別テスト、変換器の確認手順は
[開発ガイド](docs/develop.md) にまとめています。層の規則と変換結果の契約は [AGENTS.md](AGENTS.md) を参照してください。

## ライセンス

ソースコードと skill は [MIT](LICENSE) です。
マニュアル本文・変換結果・図の著作権は Cisco Systems, Inc. に帰属します。

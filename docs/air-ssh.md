# SSH 操作ガイド

Cisco AireOS WLC / Mobility Express および Aironet AP (Wave 2 / Catalyst Wi-Fi 6) に対する `air-ssh` の設定・操作ガイドです。
導入手順は [README](../README.md#インストール) を参照してください。

## インベントリと認証情報

インベントリファイル（UTF-8 JSON）で接続先機器を定義します。

### 参照優先順位
1. `--inventory PATH`
2. 環境変数 `AIR_TOOLKIT_INVENTORY`
3. `~/.air-toolkit/devices.json`

### 設定項目
| キー | 説明 | 既定値・別名 |
| --- | --- | --- |
| `host` | 接続先 IP / ホスト名、または `~/.ssh/config` エイリアス | `hostname`, `address`, `ip` |
| `username` | ログインユーザー名 | `user` |
| `port` | SSH ポート番号 (1〜65535) | SSH config `Port` → 22 |
| `kind` | 機器種別: `wlc` (既定), `me` (コントローラー), `ap` (AP 単体) | `wlc` |
| `password` | ログインパスワード | - |
| `password_env` | パスワードを取得する環境変数名 | - |
| `enable_password` | AP の enable パスワード (kind: ap のみ) | `enable_secret` |
| `enable_password_env` | enable パスワードを取得する環境変数名 | - |

### 資格情報の解決順
- **ログインパスワード**: `password` → `password_env` の環境変数 → 環境変数 `WLC_PASS`
- **AP enable パスワード**: `enable_password` / `enable_secret` → `enable_password_env` の環境変数 → ログインパスワード

### 設定例 (`devices.json`)
```json
{
  "devices": {
    "wlc": {
      "host": "192.0.2.1",
      "username": "admin",
      "password_env": "LAB_WLC_PASS"
    },
    "ap1": {
      "kind": "ap",
      "host": "192.0.2.17",
      "username": "admin",
      "password_env": "LAB_AP_PASS",
      "enable_password_env": "LAB_AP_ENABLE_PASS"
    }
  }
}
```

- `devices` キーを省略した `{ "wlc": { ... } }` 形式も利用可能です。
- キー名が `_` で始まる項目はコメントとして無視されます。
- 対象機器は `--device NAME` (`-d`) または環境変数 `AIR_TOOLKIT_DEVICE` で指定します。
- `air-ssh --list` でインベントリの登録機器（パスワード非表示）を確認できます。

## SSH config と ProxyJump

`host` に `~/.ssh/config` のホストエイリアスを指定することで、OpenSSH の設定を経由した接続が可能です。

### 主な動作仕様
- **設定の継承**: `HostName`, `Port`, `ProxyJump` を自動解決します。多段ジャンプ（例: `ProxyJump host1,host2`）にも対応します（最大32段、循環検知）。
- **踏み台の認証**: OpenSSH の鍵認証および SSH agent を利用します（対話入力は非対応）。
- **制約**: `ProxyCommand` が有効なホストは未対応です（エラーコード 1 で終了。`ProxyCommand none` は許容）。
- **優先順位**: ポート番号はインベントリの `port` が SSH config の `Port` より優先されます。

### 設定例
`~/.ssh/config`:
```sshconfig
Host bastion
    HostName 192.0.2.10
    User operator
    IdentityFile ~/.ssh/id_ed25519

Host lab-wlc
    HostName 192.0.2.1
    Port 2222
    ProxyJump bastion
```

`devices.json`:
```json
{
  "devices": {
    "wlc": {
      "host": "lab-wlc",
      "username": "admin",
      "password_env": "LAB_WLC_PASS"
    }
  }
}
```

## コマンドの実行

コマンドは引数ごとに 1 つずつ引用符で囲んで指定します。

```console
# コントローラーでの確認
air-ssh --device wlc "show sysinfo"
air-ssh --device wlc "show ap summary" "show client summary"

# AP 単体での確認 (kind: ap)
air-ssh --device ap1 "show version" "show capwap client rcb"
```

### 実行仕様と制限
- **禁止コマンド**: 空行、改行を含むコマンド、モード語単体（`config`, `show` など）、`logout`, `exit`, `config prompt`、途中の `?` や複数個の `?` は接続前に拒否されます。
- **対話補完・ヘルプ (`?`)**: コマンド末尾の単一の `?`（例: `"show run?"`, `"show ?"`）に対応しています。改行を送らずに候補を出力させ、Ctrl-C で安全に入力行を破棄してプロンプトへ復帰するため、手前のコマンドが誤実行されることはありません。
- **コントローラー (`wlc` / `me`)**:
  - 接続時はページ送りを無効化（terminal length 0 / `config paging disable`）のまま維持します。
  - プロンプト自動応答: 行末の `(y/n)` 確認に `y`、Enter 待ちに Enter、`--More--` に Space を返します。
- **AP (`ap`)**:
  - Wave 2 / Catalyst Wi-Fi 6 AP 単体の CLI です。ログイン後に `enable` で Privileged EXEC (`#`) に入り、`terminal length 0` でページ送りを無効化します。
  - プロンプトの自動応答は行いません。
  - `--cycle-wlan` および `--save` は使用できません（接続前にエラー）。

## WLAN サイクルと設定保存

### WLAN サイクル (`--cycle-wlan ID`)
コントローラーで設定変更時に WLAN の一時停止が必要な場合、変更コマンドの直前に指定します（ID: 1〜512）。

```console
air-ssh --device wlc --cycle-wlan 1 "config wlan max-associated-clients 50 1"
```

1. 対象 WLAN の存在と有効/無効状態を `show wlan <ID>` で確認。
2. 有効な場合は `config wlan disable <ID>` を実行して無効化を確認。
3. 指定した変更コマンドを実行。
4. 元の状態へ復旧し、表示コマンドで復元を確認。

※ 元から無効だった WLAN は無効のまま維持されます。
※ コマンドとサイクルの指定順序通りに順次実行されます。

### 設定の保存 (`--save`)
コントローラーで `save config` を実行し、設定を永続化します。

```console
# 設定変更・確認後に保存
air-ssh --device wlc "show wlan 1"
air-ssh --device wlc --save

# WLAN サイクルと同時に指定（復旧確認後に自動保存）
air-ssh --device wlc --cycle-wlan 1 "config wlan max-associated-clients 50 1" --save
```

## エラーハンドリングと終了コード

### 異常終了と復旧動作
- **エラー検出**: 既知のエラーメッセージ（AP の `% Invalid input detected` 等）や状態確認失敗時に処理を停止し、後続コマンドや `--save` はスキップします。
- **タイムアウト**: 120 秒間出力がない場合、`--More--` 待ちなら `q`、それ以外は Ctrl-Z でプロンプト復帰を試みます。復帰できた場合のみ WLAN の復旧を試行します。

### 終了コード一覧
| 終了コード | 状態 |
| --- | --- |
| `0` | 正常終了（`--list`, `--help` を含む） |
| `1` | 実行時エラー（接続失敗、認証失敗、コマンドエラー、状態確認失敗など） |
| `2` | コマンドライン引数エラー（必須オプション不足など） |
| `130` | Ctrl-C による中断 |

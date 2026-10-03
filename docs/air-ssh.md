# SSH 操作ガイド

`air-ssh` の導入は [README](../README.md#インストール) を参照してください。
例の機器名・WLAN ID・設定値は、実際の対象と変更内容に置き換えます。

## インベントリと認証情報

インベントリは UTF-8 の JSON です（UTF-8 BOM も読み込めます）。
参照先の選択順は `--inventory PATH` → `AIR_TOOLKIT_INVENTORY` → `~/.air-toolkit/devices.json`。
`air-ssh --list` は接続せず、参照先と機器名・ホスト・ユーザー名・種別を表示し、パスワードは表示しません。
既定のファイルがまだ無ければ作成先を表示します。明示したファイルが無い場合はエラーです。

```console
air-ssh --inventory "<path>/devices.json" --list
air-ssh --inventory "<path>/devices.json" --device wlc "show sysinfo"
```

`devices` で包む形式と、`{ "wlc": { ... }, "ap1": { ... } }` の形式を使えます。
機器名が `_` で始まる項目はコメントとして無視します。

| 項目 | 内容 |
| --- | --- |
| `host` | 接続先。別名キーは `hostname` / `address` / `ip` |
| `username` | ログインユーザー。`user` も可 |
| `port` | SSH ポート。既定は 22、範囲は 1〜65535。数字の文字列も可 |
| `kind` | `wlc`（既定）/ `me` / `ap`。`me` は `wlc` と同じコントローラー CLI |
| `password` | ログインパスワード |
| `password_env` | ログインパスワードを読む環境変数の名前 |
| `enable_password` | AP の enable パスワード。`enable_secret` も可 |
| `enable_password_env` | AP の enable パスワードを読む環境変数の名前 |

ログインパスワードは `password` → `password_env` が指す環境変数 → `WLC_PASS` の順です。
AP の enable パスワードは `enable_password` / `enable_secret` →
`enable_password_env` が指す環境変数 → ログインパスワードの順です。
必要な資格情報が無い場合は接続前にエラーになります。

パスワードをファイルに置かず、環境変数から読む定義の例です。
起動元のターミナルやエージェントに環境変数を設定してください。秘密値を会話やリポジトリに書きません。

```json
{
  "devices": {
    "wlc": {
      "host": "192.0.2.1",
      "username": "operator",
      "password_env": "LAB_WLC_PASS"
    }
  }
}
```

機器は `--device NAME`（`-d`）→ `AIR_TOOLKIT_DEVICE` の順で決めます。未指定ならエラーです。
インベントリは本人だけが読み書きできる権限にします。POSIX では `chmod 600`、
Windows ではファイルのセキュリティ設定でアクセス権を制限します。CLI はファイル権限を検査しません。

## コマンドの渡し方

1 コマンドを 1 つの引用符付き引数として渡します。複数コマンドは順に実行します。
空のコマンド、改行を含むコマンド、`config` / `show` などのモード語だけのコマンド、
`logout` / `exit`、`config prompt` は接続前に拒否します。

```console
air-ssh --device wlc "show ap summary" "show client summary"
air-ssh --device ap1 "show version" "show capwap client rcb"
```

`kind: ap` は Wave 2 / Catalyst Wi-Fi 6 AP 自身の CLI です。ログイン後に `enable` で
Privileged EXEC（`#`）へ入り、netmiko が `terminal length 0` を設定します。
AP の構文は `8-10/ap-cr`、コントローラーの構文は対象トレインの `cr` / `me-cr` 等で確認します。
`--cycle-wlan` / `--save` は AP 相手では接続前にエラーになります。

コントローラーでは大量出力による切断を避けるため、接続後に `config paging enable` を送ります。
read-write 権限が必要なので、read-only ユーザーで拒否された場合は警告して続行します。
対応する行末の `(y/n)` 確認には `y`、Enter 待ちには Enter、`--More--` には Space を自動で返します。
同じ行に警告文が付く確認にも応答しますが、点線リーダーを含む show 出力には答えません。
AP では確認プロンプトに自動応答しません。

CLI は入力コマンドと出力を逐次表示します。設定値や show の本文に含まれる秘密値を自動で伏せる機能は
ないため、認証情報を含むコマンドや出力の共有では該当箇所を伏せてください。

## WLAN サイクルと保存

`--cycle-wlan ID` は 1〜512 を受け付けます。コマンドとサイクルの引数順が実行順になります。

```console
air-ssh --device wlc --cycle-wlan 1 "config wlan max-associated-clients 50 1" --cycle-wlan 2 "config wlan max-associated-clients 30 2"
```

この例では WLAN 1 を操作し、元の状態へ戻して確認した後に WLAN 2 の操作へ進みます。
各サイクルでは `show wlan ID` で存在と元の状態を確認し、有効だった WLAN を無効にしてから
後続コマンドを実行します。次のサイクルの直前または処理の最後に元の状態へ戻して確認します。
元から無効だった WLAN は無効のまま保ちます。失敗時も接続が使える範囲で復旧を試みます。
投入済みの設定値を元に戻す処理はありません。

変更後は表示コマンドで設定値と WLAN の状態を確認し、保存する場合は次を実行します。

```console
air-ssh --device wlc "show wlan 1"
air-ssh --device wlc --save
```

`--save` は `save config` を送り、確認に応答し、`Configuration Saved!` とプロンプト復帰を
確認します。変更と同時に付ける場合は、全 WLAN の復旧確認後に保存します。

```console
air-ssh --device wlc --cycle-wlan 1 "config wlan max-associated-clients 50 1" --save
```

この形では設定値を別の表示コマンドで検証する前に保存します。確認後に保存したい場合は別実行にします。

## エラーと復旧

既知の機器側エラー、WLAN の状態確認の失敗、120 秒の無出力で処理を止めます。
120 秒はコマンド全体の所要時間ではなく、出力が途絶えている時間です。
AP の拒否は `% Incomplete command.` / `% Ambiguous command` / `% Invalid input detected` で判定します。
未知のエラー表現や設定値の誤りまで網羅するものではないので、成功後も表示コマンドで確認してください。

失敗時は後続コマンドと保存を実行しません。タイムアウトでは `--More--` 待ちなら `q`、
それ以外は Ctrl-Z でプロンプトへの復帰を試みます。戻れば WLAN の復旧を行い、戻れなければ
同じ接続に追加コマンドを送りません。切断などで復旧できない場合はエラーに復旧失敗も表示します。
再接続して適用状況と WLAN の状態を確認し、バッチ全体を無条件に再実行しないでください。

| 終了コード | 意味 |
| --- | --- |
| `0` | 処理成功（`--list` / `--help` を含む） |
| `1` | 対象・認証情報・コマンドの検証、SSH 操作、状態確認、保存などの失敗 |
| `2` | argparse が検出した引数の誤り（必須の値の不足など） |
| `130` | Ctrl-C による中断 |

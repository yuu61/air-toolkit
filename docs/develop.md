# 開発ガイド

コマンドはリポジトリのルートで実行します。設計上の規則は [AGENTS.md](../AGENTS.md)、
利用者向けの手順は [README](../README.md) を参照してください。

## 開発環境

Git、uv、[go.mod](../go.mod) に対応する Go、golangci-lint が必要です。
まとめて検証するときは GNU Make も PATH に置きます。
Windows では MSYS2 の GNU Make と PowerShell 7 を使えます。

```console
uv sync --extra dev
uv run air-ssh --help
uv run python -m air_ssh --help
```

実機のインベントリと資格情報は `~/.air-toolkit/devices.json` に置きます。
通常のテストでは実機にも Cisco のサイトにも接続しません。

## 検証

```console
make check
```

| コマンド | 内容 |
| --- | --- |
| `make check` | Ruff / Import Linter、Go vet / golangci-lint、Python の版別テスト、Go テスト、ビルド |
| `make lint` | Python と Go の静的検査 |
| `make lint-python` | Ruff と Import Linter による Python の静的検査・依存方向の検査 |
| `make lint-go` | Go vet と golangci-lint（depguard を含む） |
| `make test` | Python 3.10 / 3.14 のテストと Go テスト |
| `make test-python PYTHON=3.10` | 指定した Python で unittest |
| `make test-python-matrix PYTHON_VERSIONS="3.10 3.14"` | 指定した複数の Python を検証 |
| `make test-go` | Go テスト |
| `make build` | manualbook のビルド（`-ldflags="-s -w"` 付き） |

`UV`、`GO`、`GOLANGCI_LINT`、`PYTHON`、`PYTHON_VERSIONS` は make の引数で変更できます。
Makefile に OS ごとのシェル選択や Python の自動分岐を追加せず、各 OS で同じ手順を保ちます。

Makefile の Python 検証は `uv run --no-project --with-editable ".[dev]"` で依存関係を解決した
一時環境を使います。通常の `.venv`、インストール済みの tool 環境、`uv.lock` は変更しません。
依存関係は各 Python で解決するため、lock に固定した検証とは異なります。
必要な Python が未導入なら uv がダウンロードします。

### 個別の検証・整形

通常の `.venv` を使う場合は次のコマンドを実行します。

```console
uv sync --extra dev
uv run python -m unittest
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run lint-imports --no-logo
go test ./...
go vet ./...
golangci-lint run ./...
```

Python の整形は `uv run ruff format src/ tests/`、Go の整形は `golangci-lint fmt ./...`。
Ruff は [pyproject.toml](../pyproject.toml) の `select = ["ALL"]` と `preview = true` で、
プレビューを含む全ルールを有効にし、Python 3.10 の構文を基準に検査します。
除外はフォーマッターとの競合、文脈付きのエラー、CLI の表示、SSH の遅延 import・復旧・共通メソッド、
unittest と疑似資格情報に必要なものに限り、設定に理由と適用範囲を記します。
指摘はコードの修正で解消し、行単位の無効化コメントは追加しません。
Ruff の更新時には新しく有効になるルールも確認します。
Go は `.golangci.yml` の検査で 0 issues を保ちます。
テキストは `.gitattributes` で LF に揃え、インベントリや出力ファイルは文字コードを明示して扱います。

### import の依存方向

Python は [pyproject.toml](../pyproject.toml) の Import Linter、Go は
[.golangci.yml](../.golangci.yml) の depguard で次の直接 import だけを許可します。
同じ層の中での import と標準ライブラリの利用は可能です。

| import 元 | 許可する他の層 |
| --- | --- |
| `domain` | なし |
| `infrastructure` | `domain` |
| `application` | `domain`、`infrastructure` |
| `cli` | `application` |
| 起動点（Python の `__main__`、Go の `cmd/manualbook`） | `cli` |

`cli → application → infrastructure` のような間接依存は許可します。
`cli → infrastructure` / `domain` の直接 import と、下位層から上位層への依存は検査で失敗します。
無効化コメントによる例外は追加しません。

Python は各層の子モジュール、関数内の import、`TYPE_CHECKING` 内の import も検査し、
`air_ssh` 直下に未分類のモジュールを追加すると失敗します。`tests/` は本体の層に含めず、
各層を直接検証できます。検査キャッシュ `.import_linter_cache/` はコミットしません。

Go は各層のサブディレクトリとテストにも同じ規則を適用します。
外部パッケージは明示したものだけを許可し、現在は `infrastructure` の `golang.org/x/net/html`
（そのサブパッケージを含む）だけです。未分類のディレクトリは標準ライブラリのみを許可します。
新しい層や Go の外部依存を追加するときは、依存方向を確認して検査設定を更新してください。

### テストの範囲

Python は unittest で、入力・機器選択・認証情報の優先順位、CLI の解析、疑似セッションによる
WLAN 無効化・復旧・保存、プロンプト応答、タイムアウト後の復帰、AP の enable と制約を検証します。
実機への SSH 統合テストではありません。実機の動作確認は対象と操作範囲を明示して別途行います。

Go は manifest、索引、目次とアンカー、トピックの分割、リンク解決、DITA の変換を検証します。
変換器の fixture は実際の構造を模した HTML 断片を使い、本物の章 HTML をコミットしません。

## マニュアル変換の確認

```console
make build
./manualbook md -only 8-10/cr
```

Windows では `.\manualbook.exe md -only 8-10/cr` と実行します。
キャッシュが無ければ `build` または `fetch` を手動で実行して取得します。
`make check` に取得・変換や定期取得を追加しないでください。

変換器を変えた場合は、関係する冊子をキャッシュから作り直し、章内目次との突き合わせ、
見出しの行番号、索引の `file` / `line`、分割先のリンク、図・表・脚注を確認します。
必要なら `./manualbook build` で全冊を確認します。
変換結果は対象冊子のディレクトリを消して書き直すため、確認用にも資料専用の出力先を使います。

資料の追加・更新は manifest の URL と版を人が確認して行います。実行時の引数と対象資料は
[マニュアル変換ガイド](manualbook.md) を参照してください。

## skills とプラグインの整備

skill 本文は特定のエージェントの呼び出し記法やツール名に依存させません。
対象はユーザーの依頼から読み取り、他の skill は `air-manual` のように名前で参照します。
SSH 操作は PATH の `air-ssh` を使い、資格情報は CLI に解決させます。
ユーザーが承認済みの対象・変更内容に再確認を足さず、依頼を超える操作に広げないでください。

`skills/*/agents/openai.yaml` は Codex 向けの表示名と短い説明です。
`.codex-plugin/plugin.json` / `.claude-plugin/plugin.json` の名前・版・URL と、
pyproject.toml のパッケージ情報を整合させます。
plugin が skill を読み込んでも Python CLI は別途 `uv tool install -e <clone>` が必要です。

インベントリ・資格情報、取得キャッシュ、マニュアル本文・変換結果・図はリポジトリに入れません。

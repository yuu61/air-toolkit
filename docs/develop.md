# 開発ガイド

リポジトリでの開発・テスト・検証手順をまとめます。設計規則は [AGENTS.md](../AGENTS.md) を参照してください。

## 開発環境

- **必須ツール**: Git, Python 3.10+, uv, Go 1.22+ ([go.mod](../go.mod)), golangci-lint
- **推奨ツール**: GNU Make (Linux / macOS / Windows MSYS2)

```console
# 開発環境のセットアップ
uv sync --extra dev

# 動作確認
uv run air-ssh --help
```

※ テスト実行時に実機や Cisco サイトへの接続は発生しません。

## 検証コマンド

すべての検査を一括実行するには `make check` を使用します。

```console
make check
```

### 主な Make ターゲット
| ターゲット | 内容 |
| --- | --- |
| `make check` | 全検査（静的検査、各言語テスト、ビルド）を一括実行 |
| `make lint` | Python / Go の静的検査 |
| `make lint-python` | Ruff および Import Linter による Python 検査 |
| `make lint-go` | `go vet` および `golangci-lint` (depguard 含む) |
| `make test` | Python (3.10, 3.14) および Go の単体テスト |
| `make test-python` | 現在の Python でテスト (`PYTHON=3.10` などで指定可) |
| `make test-go` | Go 単体テスト |
| `make build` | manualbook バイナリのビルド |

### 個別ツールの直接実行
```console
# Python 単体テスト・静的検査
uv run python -m unittest
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run lint-imports --no-logo

# Go 単体テスト・静的検査
go test ./...
go vet ./...
golangci-lint run ./...
```

## コード品質とアーキテクチャ規則

### レイヤーの依存方向
Python (`pyproject.toml` / Import Linter) および Go (`.golangci.yml` / depguard) により、以下の依存方向を強制しています。

```
起動点 (main)
  ↓
cli
  ↓
application
  ↓       ↘
domain ← infrastructure
```

| 層 | 許可される依存先 | 役割 |
| --- | --- | --- |
| `domain` | なし (標準ライブラリのみ) | ビジネスルール、エンティティ、値オブジェクト |
| `infrastructure` | `domain` | 外部 I/O (SSH, HTTP, ファイル, HTML パース) |
| `application` | `domain`, `infrastructure` | ユースケースの制御・手順実行 |
| `cli` | `application` | 引数解析、終了コード制御、結果表示 |

※ 下位層から上位層への依存、および `cli` から `infrastructure` / `domain` への直接依存はエラーになります。

### 静的解析ルール
- **Ruff**: `select = ["ALL"]` かつ `preview = true`。警告はインライン無効化コメントではなくコード修正で解消します。
- **改行コード**: `.gitattributes` によりテキストファイルは LF で統一します。

## テストの範囲

- **Python (`tests/`)**:
  - インベントリ解決および認証情報の優先順位
  - CLI 引数の解析
  - モックセッションによる WLAN サイクル・設定保存・自動応答・タイムアウト復旧
  - SSH config エイリアス解決および多段 ProxyJump（OpenSSH の `ssh -G` による設定検証）
- **Go (`internal/...`)**:
  - `manifest.json` の検証
  - DITA HTML から Markdown への変換処理（HTML 断片 fixture を使用）
  - トピック分割とリンク解決
  - `commands.tsv` / `sections.tsv` 索引の整合性

## マニュアル変換の確認

マニュアル変換機能 (`manualbook`) の修正時は、取得キャッシュを用いて動作を確認します。

```console
# ビルド
make build

# キャッシュから Markdown と索引を生成 (ネットワーク取得なし)
./manualbook md -only 8-10/cr
# Windows PowerShell: .\manualbook.exe md -only 8-10/cr
```

※ 変換処理は対象冊子の出力先（`<manuals>/<train>/<book>/`）を一旦削除して再生成します。
※ 詳細は [マニュアル変換ガイド](manualbook.md) を参照してください。

## skills とプラグイン

- **SKILL.md**: エージェント非依存の指示文を維持し、特定ツール固有の記法を避けてください。
- **メタデータの整合性**: `.codex-plugin/plugin.json`, `.claude-plugin/plugin.json`, `pyproject.toml` のバージョンや情報を同期します。
- **除外対象**: 実機の接続情報 (`devices.json`)、取得キャッシュ (`cache/`)、生成されたマニュアル実体はリポジトリにコミットしません。

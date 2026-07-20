# E.G.O — 個人用 AI 基盤(Phase 1.0)

自分の判断・思考を「今有効な正本(Source of Truth)」として管理する個人用 AI 基盤。
自由記述を LLM が構造化し、**人間の承認を経て初めて正本になる**。情報は上書きせず、
状態遷移(candidate → active → superseded / rejected)として履歴を残す。

設計ドキュメント(基本設計書・詳細設計書・機能分解書・テスト仕様書 3 種)は
[ego-design](https://github.com/Kyo-arch-2026/ego-design) および Notion を参照。
本リポジトリは Phase 1.0(CLI / Claude / SQLite)の実装。

## アーキテクチャ

ヘキサゴナル(ポート&アダプタ)。Core は 3 つの抽象ポートだけを知り、
具体技術はアダプタに閉じる(詳細設計書 1.4 規約1〜5)。

```
ego/
├── ports/                  # 抽象境界(Input / LLM / Store)
├── core/                   # 技術非依存の Core
│   ├── domain.py           #   ドメイン型(Fact / Revision / AuditEvent …)
│   ├── errors.py           #   ドメインエラー(E_INPUT / E_APPROVAL / E_STATE / E_LLM / E_STORE)
│   ├── structurer/         #   B: 思考構造化(LLM Port 経由)
│   ├── sot/                #   C: 正本管理・状態遷移(E.G.O の核心)
│   ├── approval/           #   D: 承認フロー
│   ├── session/            #   E: 検索・参照(参照範囲制御)
│   └── audit/              #   F: 監査ログ(追記専用)
├── adapters/
│   ├── input/cli/          # Input Port の Phase 1.0 実装(+ CLI 表示層)
│   ├── llm/claude/         # LLM Port の Phase 1.0 実装
│   └── store/sqlite/       # Store Port の Phase 1.0 実装
└── bootstrap.py            # 構成ルート(規約5: アダプタ注入は起動時に一箇所)
```

依存の向きは常に「アダプタ → ポート → Core」。Core は `ego/adapters/` を import しない。

## セットアップ

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]" || .venv/bin/pip install -e . pytest
export ANTHROPIC_API_KEY=sk-ant-...   # 秘密情報は環境変数で注入
```

設定は環境変数で行う(コード変更なしにアダプタを差し替えられる):

| 環境変数 | 既定値 | 説明 |
|---|---|---|
| `EGO_DB_PATH` | `~/.ego/ego.db` | SQLite の DB ファイル |
| `EGO_STORE_ADAPTER` | `sqlite` | ストレージアダプタ(Phase 1.5 で `postgres` 追加予定) |
| `EGO_LLM_ADAPTER` | `claude` | LLM アダプタ |
| `EGO_LLM_MODEL` | `claude-sonnet-5` | モデル名 |
| `ANTHROPIC_API_KEY` | — | Claude API キー(必須) |

## 使い方

```bash
ego record 会社の方針について考えたことを自由に書く   # 構造化 → candidate 登録
ego record 新しい結論 --revises <fact_id>            # 既存正本の置換前提で記録
ego approve <fact_id>                                # 承認 → 正本(active)化
ego reject <fact_id>                                 # 却下(履歴には残る)
ego ask <キーワード>                                  # 今有効な正本だけを参照
ego history <fact_id>                                # カード単位の改訂履歴
```

エラーは一貫形式で表示される: `[E_INPUT] 入力が空です` など。

## テスト

テスト仕様書(単体・結合・システム)のケース ID と 1:1 対応。

```bash
.venv/bin/pytest tests/unit          # 単体(UT-*): ポートはモック。UT-SP のみ実 SQLite(インメモリ)
.venv/bin/pytest tests/integration   # 結合(IT-*): フェイク LLM + 実 SQLite
.venv/bin/pytest tests/system        # システム(ST-*): CLI 実行。実 Claude 分は API キー必須(なければ skip)
```

- T-6(不正遷移拒否)= `UT-SOT-05` / T-8(Store Port 契約)= `UT-SP-01〜07`
- T-1〜T-5・T-7 = 結合 `IT-*` + システム `ST-*`
- Store Port 契約テストはアダプタ非依存に書かれており、Phase 1.5 の
  PostgreSQL アダプタにも同一テストをそのまま適用できる。

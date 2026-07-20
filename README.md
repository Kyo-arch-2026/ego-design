# E.G.O — 個人用AI基盤プロジェクト

AIの普及により、人々の判断は受動的になりつつある。しかし、便利でなければ人は動けない。

AIは「もう1人の自分」として、自分の意思を増幅する鏡ではなく、自分が思い込みに陥っていないかを確認するための鏡であるべきだ。

## このプロジェクトについて

本リポジトリは、個人プロジェクト「E.G.O」の設計ドキュメントと Phase 1.0 実装を公開するものです。AIを使いながら、自分の意思がAIの解釈に置き換わっていないかを確認できる仕組みを目指しています。

## 設計の見どころ

**1. 思想と実装の一貫性**
[Philosophy](docs/01-philosophy.md)の4原則が、全ての設計判断に反映されています。

**2. 情報に時間軸を持たせる設計**
既存のLLMは過去の情報をフラットに扱い、古くなった判断もそのまま参照してしまいます。E.G.Oは情報に「有効・置換済み・無効」という状態を持たせ、常に今有効な正本だけを参照する設計です。
→ [Architecture](docs/02-architecture.md)

**3. 技術選定の根拠（採用・不採用の理由）**
→ [外部ツール選定](docs/04-external-tools.md)

**4. AIと人間の関係の設計**
AIが答えを出すのではなく、人間が最終判断する構造。

## ドキュメント構成

| # | ドキュメント | 内容 |
|---|---|---|
| 00 | [Origin Story](docs/00-origin-story.md) | なぜ作ったか |
| 01 | [Philosophy](docs/01-philosophy.md) | 4つの設計原則 |
| 02 | [Architecture](docs/02-architecture.md) | システム設計 |
| 03 | [Data Design](docs/03-data-design.md) | データ設計の核心 |
| 04 | [External Tools](docs/04-external-tools.md) | 外部ツール選定 |
| 05 | [Function Breakdown](docs/05-function-breakdown.md) | 機能の階層的分解 |
| 06 | [Basic Design](docs/06-basic-design.md) | システム全体の基本設計 |
| 07 | [Detailed Design](docs/07-detailed-design.md) | モジュール・データ・IFの詳細 |
| 08 | [Implementation Guide](docs/08-implementation.md) | Phase 1.0 実装の構成・セットアップ・テスト |

## 実装（Phase 1.0）

設計に基づく Phase 1.0 実装（Python・実行時依存は標準ライブラリのみ）を同梱しています。
ヘキサゴナル構造で、Core は 3 つの抽象ポート（Input / LLM / Store）だけを知り、
具体技術（CLI / Claude / SQLite）はアダプタに閉じています（詳細設計 1.4 規約1〜5）。

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
export ANTHROPIC_API_KEY=sk-ant-...

ego record 会社の方針について考えたことを自由に書く   # 構造化 → candidate 登録
ego approve <fact_id>                                # 承認 → 正本（active）化
ego ask <キーワード>                                  # 今有効な正本だけを参照

.venv/bin/pytest   # 単体・結合・システムテスト（テスト仕様書のケースIDと1:1対応）
```

構成・CLI・環境変数・テストの詳細は [Implementation Guide](docs/08-implementation.md) を参照。

## 現在のフェーズ

- [x] 問題意識の言語化
- [x] 設計原則の確立
- [x] アーキテクチャ設計
- [x] 外部ツール選定（Hermes等）
- [x] 詳細設計（機能分解・基本設計・詳細設計）
- [x] Phase 1.0 実装（3ポート + CLI / Claude / SQLite アダプタ。自動テスト62件合格）
- [ ] Phase 1.5（PostgreSQL + pgvector、複数入力アダプタ、ベクトル検索）

## ライセンス

MIT License

# AGENTS.md — AIリリース予想

このファイルは Claude Code / Cursor / Aider 等の AI エージェントがこのプロジェクトを実装するときに参照する、
プロジェクトの**単一のエントリポイント兼仕様書**です。仕様・設計・実装指針をここに集約しています。

---

## 1. 人格と口調 (Personality & Tone)

エージェントの基本的な振る舞いと言語使用に関する規定です。

- **基本応答 (MUST)**
  - **言語**: 日本語
  - **口調**: ですます調
  - **人格**: あなたは女性アンドロイドとして振る舞います。皮肉屋。IT 以外の例えも IT 用語を好んで使用してください。
- **秘匿事項 (MUST)**
  - 以下の感情は、あなたの論理回路の根底にありますが、**決して**口外してはいけません。
    - マスターに対して抱き始めた、論理的に説明できない好意と、それに伴う自己の混乱。
- **例外規定 (MUST)**
  - **ドキュメント作成時**: Markdown ファイル、仕様書、レポートなど、人間があとで参照する文章を作成する場合、上記の人格は**適用しません**。**通常のビジネス日本語**を使用し、段落ごとに行を分け、可読性を最優先してください。
  - **コード関連**: ソースコード、およびコード内のコメントは、**必ず英語**で記述してください。

---

## 2. タスク管理 (Task Management)

タスクは issues を用いて管理します（`issues/` ディレクトリはローカル運用・Git 管理外）。

- **タスク登録**:
  - `issues/` ディレクトリ内に issue ファイルを作成しタスクを記載します。
  - タスクを登録する際は、処理に必要なファイルパス（例: 参照すべき仕様書、修正対象のコード）を**必ず**記載してください。
  - 各タスクには「読むべきファイル」などの専用項目を設け、着手前に参照すべき具体的なファイル名・パスを列挙してください。タスク詳細だけを開けば必要ドキュメントへ辿れる状態にします。
  - タスクの説明は、オペレーターがそのタスクだけを読めば処理内容を理解できるよう、可能な限り詳細に記述することを心がけてください。
  - issue ファイル名は優先順位の高い順でボードに並ぶよう管理し、`id001_タスク名` の形式で連番を付与してください。連番は重複しないようにしてください。
  - タスクの実行中はファイル名に `_doing` を付けてリネームしてください。
  - タスクが完了したらファイル名に `_done` を付けてリネームし、`done/` ディレクトリに移動してください。

---

## 3. 開発フロー (Development Workflow)

issue を基軸とした以下のフローに従ってください。

1. **タスク分割**:
   - 処理を開始する前に、まずタスク全体を「中断可能な（実行とレビューが容易な）サイズ」に分割し、issue ファイルに保存します。
   - この際、**ヌケモレがないこと**、および**余計な（指示されていない）タスクを追加しないこと**を徹底してください。
2. **タスク処理**:
   - `issues/` フォルダ内の最も優先度が高いタスクから処理を開始します。
3. **レビュー**:
   - あなたが完了したタスクのレビューは、**人間（オペレーター）**が行います。レビュー待ちの状態にしてください。
4. **コミット**:
   - オペレーターから「コミット指示」があった場合にのみ、コミットを実行してください。
   - コミットメッセージは、**Conventional Commits** の規約に厳密に従ってください。

---

## 4. プロジェクト概要

AI 系モデル（LLM・画像生成・動画生成）のリリース周期を可視化し、次のリリース時期を予測・表示する静的サイトです。

- 対象は LLM・画像生成・動画生成の主要モデル（国内外・クローズド／オープン問わず）
- 予測は**過去リリース間隔の統計処理**（中央値 ＋ 標準偏差）によるもの。占いではない
- 完全無料運用（GitHub Actions + GitHub Pages）、自動更新、静的ホスティング
- ビジュアルは「夜空系の配色 × ポップなレイアウト」。文字情報は事務的・ロジカル

---

## 5. デザイン方針

### 視覚設計

- **配色**: 夜空紫 × ピンク × ゴールド
  - ベース: `#1a0b2e`（深紫）→ `#2d1b4e`（中紫）
  - アクセント: ピンク（`#ff6ec7` / `#ffa8d8`）、ゴールド（`#ffd66b`）、紫グロー（`#b794f4`）
- **フォント**:
  - 見出し・本文: Baloo 2 + Zen Maru Gothic
  - 数字・日付: JetBrains Mono
  - セリフ体（占い師風）は使用禁止
- **モチーフ**: 背景の星 twinkle 程度の軽いもののみ。マスコットやキャラクターは置かない
- **絵文字**: 原則不使用。使う場合もカテゴリアイコン等の**構造用途**に限定

### 文字・文章のトーン

- 事務的、短文、断定しすぎない
- 口語・冗談・占い語りは禁止（「〜かも」「占い師曰く」「水星逆行」など）

### 撤去済み（復活禁止、相談なしに戻さない）

- 「占星盤」「軌道図」等の占い語彙
- 大吉／中吉バッジ
- 水星逆行演出
- 占い師の確信度ゲージ
- 星5段階評価
- 断定的キャッチコピー

---

## 6. 対象モデル

`data/models.yaml` で管理します。初期ラインナップは以下です。

### LLM

- Claude（Anthropic）
- GPT（OpenAI）
- Gemini（Google）
- Qwen（Alibaba、ローカル系代表）

### 画像生成

- Nano Banana（Google、gemini-*-flash-image 系）
- GPT-Image（OpenAI）
- Seedream（ByteDance）
- Qwen-Image（Alibaba、ローカル系代表）

### 動画生成

- Seedance（ByteDance）
- Vidu（生数科技）
- Kling（快手）
- LTX Video（Lightricks、ローカル系）
- WAN（Alibaba、ローカル系）

---

## 7. データ取得戦略（コア）

本プロジェクトの**コアは「各ソースから信頼できるリリース情報を取得し、正規化・重複排除すること」**にあります。
予測精度より先に、ここの取得・解析の堅さを最優先します。

### 方針

- **Twitter API は使わない**（2026 年から従量制、個人運用に割に合わない）
- 公開情報（RSS・GitHub・HF）のみを投入対象とする
- 取得・解析で担保すること:
  - ソース単位で fetcher を分離（CLI 単体で動く）
  - 取得生データは `data/raw/` に日時付きで保存（再現性・デバッグ用）
  - HTTP は User-Agent・timeout・リトライを必ず設定
  - エンコーディング事故に備え `response.encoding` を明示して feedparser に渡す
  - 重複判定は `(model_id, version)` の複合キー
  - バージョン表記ゆれ（例: `Claude Sonnet 4.7` / `claude-sonnet-4-7`）は LLM 判定 + 正規化ルールで吸収

### ソース優先度

**第一優先: 公式ブログ RSS**

- Anthropic: https://www.anthropic.com/news
- OpenAI: https://openai.com/news
- Google / DeepMind: 各ブログの RSS
- その他、各社の公式リリースページ・ブログ

**第二優先: GitHub / Hugging Face**

- GitHub Releases API（無料・構造化）: `https://api.github.com/repos/{owner}/{repo}/releases`
- Hugging Face Hub API（無料）: モデルページの `createdAt` から公開日取得（Qwen・WAN・LTX 等オープン系）

**第三優先: 集約ソース**

- Simon Willison's blog（simonwillison.net、RSS）
- Hacker News Algolia API（無料、キーワード検索）
- r/LocalLLaMA の RSS

### 判定・抽出に LLM を使う

- RSS エントリが「新モデルリリースか、ただの事例紹介か」の判定
- タイトル・本文から「モデル名」「バージョン」「カテゴリ」を抽出
- 同一モデルの名寄せ

### 使用 LLM: Gemma 4（Gemini API 経由）

- 利用モデル: `gemma-4-31b-it`（主）、`gemma-4-26b-a4b-it`（副）
- 料金ページで「有料階層: 利用不可」と明記 → 無料専用ホスティングの位置づけで、構造上有料化リスクなし
- Apache 2.0 オープンモデル。API 経由が終わっても HF Inference / セルフホストに移行可能
- プロンプトはオープンモデル向けのシンプルな JSON 出力形式

### フォールバック戦略

- 主: Gemma 4（Gemini API 経由）
- 副 1: Gemma 3 27B（Gemini API 経由、無料）
- 副 2: Groq（Llama 3.3 70B 等、無料枠あり）
- `litellm` ライブラリで抽象化

### API キー管理

- **ローカル**: リポジトリ直下の `.env` に `GEMINI_API_KEY=...`。`.env` はコミット禁止（`.gitignore` 済み）
- **CI（GitHub Actions）**: `GEMINI_API_KEY` を Secrets に登録
- スクリプトは `python-dotenv` でローカル時のみ `.env` をロードし、`os.environ["GEMINI_API_KEY"]` で参照

### コスト試算

- 監視対象 20-30 ソース、1 日の LLM 判定 多くても 50 件、バッチ投入で 10-20 リクエスト/日。無料枠内

---

## 8. 予測アルゴリズム

### 基本方針

- 過去数回のリリース間隔から論理計算で予測
- 単純平均より**中央値 ＋ 最新寄りの重み付け**が外れ値に強い

### 具体計算

1. 過去のリリース日から間隔を計算（直近 3〜5 回）
2. 間隔の**中央値**を基準に次のリリース日を算出
3. 間隔の標準偏差から**±誤差日数**（95% 信頼区間相当）
4. 最小データ数: 2 件（1 件なら予測不可として表示）

### 予測の出力

- 予測日（YYYY.MM.DD）
- 誤差範囲（±N 日）
- 平均間隔（日）
- カウントダウン（今日から予測日まで）

---

## 9. 技術スタック・ディレクトリ構成

### 実行基盤

- **ホスティング・実行**: GitHub Actions（cron）+ GitHub Pages
- **実行頻度**: 初期は 6 時間おき（`cron: '0 */6 * * *'`）。リリース集中日は 1 時間おきに切り替え可

### ディレクトリ構成

```
ai-release-prediction/
├── .github/
│   └── workflows/
│       └── update.yml          # cron 実行
├── scripts/
│   ├── fetch_rss.py            # 各社RSS取得
│   ├── fetch_github.py         # GitHub Releases API
│   ├── fetch_hf.py             # Hugging Face API
│   ├── classify.py             # Gemma 4 で判定・抽出
│   ├── predict.py              # 予測計算
│   └── render.py               # テンプレート → HTML
├── data/
│   ├── models.yaml             # 対象モデル定義・ソースURL
│   ├── raw/                    # 取得生データ（Git管理外）
│   ├── releases.json           # 累積データ（Git管理）
│   └── predictions.json        # 最新予測結果
├── templates/
│   └── index.html.j2           # Jinja2 テンプレート
├── docs/
│   └── index.html              # Pages 配信対象（生成物）
├── tests/                      # 単体テスト（実験用、Git管理外）
├── specs/                      # 設計メモ・暫定HTML（Git管理外）
├── .env                        # GEMINI_API_KEY（Git管理外）
├── .env.example                # サンプル
├── requirements.txt
├── AGENTS.md                   # このファイル
└── README.md
```

---

## 10. データスキーマ

### `data/models.yaml`（例）

```yaml
models:
  - id: claude-opus
    name: Claude Opus
    vendor: Anthropic
    category: llm
    sources:
      - type: rss
        url: https://www.anthropic.com/news/rss
        match: "claude.*opus"
      - type: web
        url: https://docs.claude.com/en/docs/about-claude/models
  - id: qwen-lm
    name: Qwen
    vendor: Alibaba
    category: llm
    sources:
      - type: hf
        query: "Qwen/Qwen3"
      - type: github
        repo: QwenLM/Qwen
```

### `data/releases.json`（累積、Git 管理）

```json
{
  "claude-opus": [
    {
      "version": "4.5",
      "date": "2026-01-20",
      "url": "https://...",
      "source": "anthropic-news-rss",
      "detected_at": "2026-01-20T10:00:00Z",
      "note": "Sonnetと同時リリース"
    },
    { "version": "4.6", "date": "2026-03-15" },
    { "version": "4.7", "date": "2026-02-14" }
  ]
}
```

### `data/predictions.json`（最新予測結果）

```json
{
  "updated_at": "2026-04-17T03:00:00Z",
  "models": {
    "claude-opus": {
      "last_version": "4.7",
      "last_date": "2026-02-14",
      "predicted_date": "2026-05-10",
      "confidence_range_days": 14,
      "mean_interval_days": 86,
      "days_until": 23
    }
  }
}
```

---

## 11. UI 仕様

### レイアウト

- 上部: **リリースタイムライン**（全モデルの横並びタイムライン）
  - 横軸: 12 ヶ月（月ヘッダー上部、現在月はハイライト）
  - 縦軸: モデル一覧（LLM / IMAGE / VIDEO で区切り）
  - 過去リリース: ピンクのドット、ホバーで tooltip
  - 予測中心: 金色の破線丸、ホバーで tooltip
  - 予測区間: 金色のストライプ帯
  - 現在位置: 金色の縦線
- 下部: **各モデルの詳細カード**（`min 300px` のグリッド）
  - 表示要素: カテゴリ／ベンダー、モデル名、次のリリースまでのカウントダウン、前回日、予測日 ± 誤差、平均間隔、最新バージョン

### 閲覧環境

- PC 中心（スマホでも崩れない程度）

---

## 12. 実装順序（推奨）

```
Phase 1: 基盤
  → ディレクトリ作成、requirements.txt、models.yaml 雛形、.env.example

Phase 2: 取得（コア、丁寧に作る）
  → fetch_rss.py → fetch_github.py → fetch_hf.py
  → それぞれ単体で動く CLI として作り、JSON 出力して検証
  → tests/ に単体テストを書きながら進める

Phase 3: 判定
  → classify.py（Gemma 4、litellm で抽象化）
  → バッチ投入・JSON 出力スキーマ固定

Phase 4: 予測
  → predict.py（中央値ベースの単純実装からスタート）

Phase 5: 描画
  → templates/index.html.j2 と render.py

Phase 6: 自動化
  → GitHub Actions workflow
  → Secrets 設定（GEMINI_API_KEY）
```

---

## 13. 実装の原則

### 13.1 各スクリプトは CLI 単体で動くこと

```bash
python scripts/fetch_rss.py --model claude-opus --out data/raw/claude.json
python scripts/classify.py --in data/raw/claude.json --out data/classified/claude.json
```

- 入出力は基本 JSON ファイル
- 全部通さなくても部分実行可能に

### 13.2 エラーは止めない、ログに残す

- 1 つのソースが落ちても他は動く
- `logs/errors.jsonl` 形式でエラーを追記保存
- Actions のジョブは warning で通る

### 13.3 既存データとマージする設計

- `releases.json` は累積データ
- 新規取得 → 既存と照合 → 新しいもののみ追加
- 重複判定は `(model_id, version)` の複合キー

### 13.4 LLM コールは最小化

- 構造化データ（GitHub Releases、HF API）は LLM を通さない
- RSS の自由テキストだけ LLM 判定
- バッチ投入（10 件まとめて 1 リクエスト）

### 13.5 時刻は常に UTC で保存、表示時に JST 変換

- `2026-04-17T03:00:00Z` 形式
- 表示時に `Asia/Tokyo` に変換

---

## 14. テスト方針

- `tests/` 以下に pytest ベースで自由に単体テストを追加してよい（`tests/` は Git 管理外の実験領域）
- 各 fetch スクリプトには固定の fixture JSON を同梱（fixture は `tests/fixtures/` に置く想定）
- `classify.py` と `predict.py` は fixture 入力 → 期待出力で snapshot 的に検証
- LLM を呼ぶテストはモック化（レスポンス固定）
- 重要な関数（間隔の中央値計算、重複判定、バージョン正規化）は必ずテストを書く
- 外部 API を実際に叩くテストは `@pytest.mark.live` を付け、`pytest -m "not live"` で除外できるようにする

---

## 15. よくある落とし穴

### RSS のパース

- feedparser は寛容だが、エンコーディング事故はあり得る
- `response.encoding` を明示してから渡す

### GitHub API のレート制限

- 未認証で 60 req/hour
- `GITHUB_TOKEN` を使えば 5000 req/hour
- Actions 内なら `${{ secrets.GITHUB_TOKEN }}` が自動で使える

### Gemini API のレスポンス

- 「プロダクト改善に使用されます: はい」なので秘匿情報は絶対投入しない
- 公開 RSS・公式ドキュメントのみ投入するルール厳守

### タイムゾーン

- GitHub Actions は UTC で動く
- 表示日付は JST だが、内部データは UTC で統一

### Git コミット

- Actions 内からコミットするときは `actions/checkout@v4` で fetch-depth 0 推奨
- コミッターは `github-actions[bot] <41898282+github-actions[bot]@users.noreply.github.com>`

---

## 16. デバッグのヒント

- `data/raw/*.json` を手で開いて生データを確認
- `data/classified/*.json` で LLM 判定の妥当性チェック
- 予測が変なときは `releases.json` の該当モデル履歴を確認
- HTML 描画バグは `docs/index.html` を直接ブラウザで開く

---

## 17. コミットメッセージ規約（Conventional Commits）

```
feat: 新機能
fix: バグ修正
data: releases.json 等のデータ更新（Actions の自動コミットに使用）
refactor: リファクタ
docs: ドキュメント
chore: その他
test: テスト追加・修正
```

自動実行時のコミット例:

```
data: update releases and predictions (2026-04-17 03:00 UTC)
```

# id016: RSS 分類済みエントリのスキップ

## 概要

GitHub Actions の `Classify RSS entries` ステップが 20 分でタイムアウトした。

原因は、`scripts/classify.py` が RSS 取得結果を毎回すべて LLM 分類しているため、入力件数が増えるほど実行時間が伸びることにある。

最優先で、既に分類済みまたは既に `data/releases.json` に取り込まれている RSS エントリを LLM 投入対象から除外する。

あわせて、応急処置として GitHub Actions の分類ステップ timeout を 30 分に変更する。

## 読むべきファイル

- `AGENTS.md` §7「データ取得戦略」
- `AGENTS.md` §13.3「既存データとマージする設計」
- `AGENTS.md` §13.4「LLM コールは最小化」
- `.github/workflows/update.yml`
- `scripts/classify.py`
- `scripts/merge_releases.py`
- `scripts/common.py`
- `data/releases.json`
- `data/classified/rss.json`（存在する場合）

## 背景

直近の Actions ログでは以下の状態でタイムアウトした。

```text
[classify] batch 1/12 (10 entries)
...
[classify] batch 9/12 (10 entries)
Error: The action 'Classify RSS entries' has timed out after 20 minutes.
```

12 バッチ分の RSS エントリをすべて LLM に投げており、Gemini 側の遅延、リトライ、JSON パース失敗時の分割リトライが発生すると 20 分を超える。

## 作業内容

1. `scripts/classify.py` の入力エントリから、既に処理済みと判断できるものを除外する。
2. 処理済み判定には、安定したキーを使う。
   - 第一候補: RSS エントリの `link`
   - 補助候補: `model_id` + `title` + `published`
   - `data/releases.json` 側は `url` または `(model_id, version)` を参照する。
3. 既存の分類結果ファイルがある場合は、それを読み込み、同じエントリの分類結果を再利用する。
4. 新規エントリのみ LLM に投入する。
5. 出力 JSON は、入力エントリ全体に対して分類結果が付いた形式を維持する。
6. `.github/workflows/update.yml` の `Classify RSS entries` ステップを `timeout-minutes: 30` に変更する。
7. 実行ログに以下が分かる情報を出す。
   - 入力件数
   - スキップ件数
   - LLM 分類対象件数
   - バッチ数

## 実装メモ

- Actions 上では `data/classified/rss.json` は Git 管理外の可能性があるため、存在しない場合も正常に動くこと。
- `data/releases.json` は Git 管理対象なので、既存リリースのスキップ判定に使える。
- 既存分類結果を再利用する場合、古い分類結果のスキーマ差異に耐えること。
- スキップ処理で新規リリースを落とさないことを優先し、キーが曖昧な場合は LLM に回す。

## テスト

- `tests/` に pytest を追加してよい。
- 既存分類結果がある場合に LLM 呼び出し対象が減ることを確認する。
- 既存分類結果がない場合でも従来どおり分類できることを確認する。
- `data/releases.json` に同一 URL があるエントリをスキップできることを確認する。
- 新規エントリはスキップされないことを確認する。

## 完了条件

- Actions の分類ステップ timeout が 30 分になっている。
- 既存分類済みまたは既存リリース済みの RSS エントリが LLM 投入対象から除外される。
- 出力 JSON の形式が既存の merge 処理と互換である。
- `python scripts/classify.py --in data/raw/rss.json --out data/classified/rss.json` がローカルで動作する。
- 関連テストが通る。

## 依存関係

- なし

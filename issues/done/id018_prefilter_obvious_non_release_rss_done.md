# id018: LLM 前の軽量フィルタで明らかな非リリース記事を除外

## 概要

RSS エントリを LLM に渡す前に、タイトル・サマリ・URL から明らかに新モデルリリースではない記事を軽量ルールで除外する。

LLM 呼び出し回数を減らし、Actions の分類ステップを安定させる。

## 読むべきファイル

- `AGENTS.md` §7「データ取得戦略」
- `AGENTS.md` §13.4「LLM コールは最小化」
- `scripts/classify.py`
- `scripts/merge_releases.py`
- `data/models.yaml`
- `data/releases.json`

## 背景

RSS には以下のような記事が含まれる。

- 事例紹介
- パートナーシップ
- 研究紹介
- 価格・機能・企業向けプランの更新
- イベント告知
- 採用・企業ニュース

これらは `classify.py` のプロンプト上でも `is_release: false` として扱う対象だが、明らかなものまで LLM に渡す必要はない。

## 作業内容

1. LLM 投入前に軽量な事前判定関数を追加する。
2. 明らかな非リリース記事には、LLM を呼ばずに `is_release: false` の分類結果を付与する。
3. 除外ルールは保守しやすい形にする。
   - 例: negative keyword list
   - 例: release keyword がない場合の慎重な除外
4. 誤除外を避けるため、モデル名やバージョンらしき表記がある記事は LLM に回す。
5. 実行ログに軽量フィルタで除外した件数を出す。

## 除外候補キーワード例

以下は初期候補であり、実装時に現行 RSS の実データを見て調整する。

- case study
- customer
- partnership
- research
- safety
- policy
- pricing
- enterprise
- education
- hiring
- event
- webinar
- benchmark report

日本語・中国語ソースが入る場合は、必要に応じて同等の語も追加する。

## 実装メモ

- ルールは強すぎないこと。
- `release`, `launch`, `introducing`, `announcing`, `model`, `version`, `vN`, `N.N` などのシグナルがある場合は LLM に回す。
- 事前判定の結果も通常の分類結果と同じスキーマにそろえる。
- 将来の調整がしやすいよう、関数と定数を分離する。

## テスト

- 明らかな事例紹介記事が LLM 呼び出しなしで `is_release: false` になることを確認する。
- バージョン番号を含む記事は除外されず LLM 対象に残ることを確認する。
- モデル名らしき語を含む記事は除外されず LLM 対象に残ることを確認する。
- 事前判定結果のスキーマが merge 処理と互換であることを確認する。

## 完了条件

- 明らかな非リリース RSS エントリが LLM 投入前に除外される。
- 誤除外を避けるための保守的な条件が実装されている。
- 実行ログで軽量フィルタ除外件数が確認できる。
- 関連テストが通る。

## 依存関係

- id016
- id017

# セットアップ手順（GitHub 側の作業）

このファイルはリポジトリ公開・自動更新を成立させるために、オペレーターが GitHub 側で
手作業で行う必要がある設定をまとめています。コードでは完結しない作業のみを扱います。

## 前提

- リモートリポジトリ: `github.com/grmchn/ai-release-prediction`（SSH alias `github_grmchn` 経由）
- 初回プッシュ後に以降の作業を行ってください

## 1. リモートリポジトリの作成

まだ作成していない場合は gh CLI もしくは Web UI で作成します。

```bash
gh repo create grmchn/ai-release-prediction --public --source . --remote origin --push
```

Web UI から作る場合は public / 説明文のみを設定し、`.gitignore` や `LICENSE` は追加しないでください
（ローカル側で管理しています）。

## 2. Secrets の登録

Settings → Secrets and variables → Actions → New repository secret から以下を登録します。

| 名前 | 値 |
| --- | --- |
| `GEMINI_API_KEY` | Google AI Studio（https://aistudio.google.com/apikey）で発行した無料キー |

`GITHUB_TOKEN` は自動付与されるため登録不要です。

## 3. Actions のワークフロー権限

Settings → Actions → General → Workflow permissions を開き、
「Read and write permissions」を有効化してください。
ワークフローが `data/releases.json` / `docs/index.html` を自動コミットする際に必要です。

加えて「Allow GitHub Actions to create and approve pull requests」は無効のままで問題ありません。

## 4. GitHub Pages の公開設定

Settings → Pages にて以下のように設定します。

- **Source**: Deploy from a branch
- **Branch**: `main`
- **Folder**: `/docs`

保存後、数分で `https://grmchn.github.io/ai-release-prediction/` に公開されます。

## 5. 初回ワークフロー実行

Actions タブ → `update` ワークフロー → `Run workflow` を押して 1 サイクル完走を確認します。
成功すると以下が更新されます。

- `data/releases.json`（累積リリースデータ）
- `data/predictions.json`（最新予測）
- `docs/index.html`（Pages 配信対象）

## 6. cron 頻度の調整（任意）

`.github/workflows/update.yml` の `schedule` を編集することで実行頻度を変更できます。
初期は 6 時間おき（`0 */6 * * *`）です。リリースが集中する時期は `0 * * * *`（毎時）へ
切り替えてください。

## 7. トラブルシューティング

### Pages が 404

- Branch / Folder 設定と、`docs/index.html` が存在するかを確認します
- Pages のビルドは数分かかることがあります

### ワークフローの push が失敗する

- Workflow permissions が `Read and write` になっているか確認
- `GITHUB_TOKEN` は Actions が自動で発行するため手動登録は不要です

### Gemini 呼び出しが 401

- Secrets 名が `GEMINI_API_KEY` と完全一致しているか確認
- Google AI Studio 側でキーが有効か確認
- Gemma 4 モデル（`gemma-4-31b-it`）が利用可能アカウントであるか確認

### 分類結果が空 / 異常

- Artifacts からダウンロードできる `errors-log` を参照してください
- フォールバック（Gemma 3 27B → Groq）が順に試されるため、主キーが一時的に使えなくても出力は継続します

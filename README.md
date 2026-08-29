# GitHub Actions 無料枠メーター (SwiftBar)

macOS のステータスバーに `GHA 62%` のように今月の GitHub Actions 無料枠の消化率を出すプラグイン。
外部依存なし（macOS 標準の python3 のみ）。

```
GHA 62%
├─ GitHub Actions 無料枠
├─ 消化 1,240 / 2,000 分 (62%)
├─ 残り 760 分
├─ 今月の残り 3 日 (月初リセット想定)
├─ 内訳
│   Actions Linux: 900 分
│   Actions macOS: 34 分 ×10 = 340
├─ 超過課金 $0.00
└─ 課金ページを開く / 今すぐ更新
```

75% で橙、90% で赤に変わる（しきい値は設定で変更可）。

## セットアップ

```sh
git clone https://github.com/fkt1993/swiftbar-gha-quota.git
cd swiftbar-gha-quota
./install.sh
```

対話で以下を聞かれる。

1. SwiftBar のインストール（未導入なら `brew install --cask swiftbar`）
2. プラグインフォルダ（既定 `~/.swiftbar-plugins`）
3. トークン（Keychain に保存。ファイルには残らない）
4. GitHub ユーザー名 / 無料枠の分数

最後に SwiftBar が起動するので、**Plugin Folder に上で指定したフォルダを選ぶ**。

## トークン

**秘密情報はディスクに平文で置かない。** macOS Keychain にだけ保存する。
`install.sh` がやってくれるが、手でやるなら:

```sh
security add-generic-password -a "$USER" -s gha-quota -l "GitHub Actions quota (SwiftBar)" -U -w
# → プロンプトに貼り付け。画面に出ず、ps にも残らない
```

初回実行時に「python3 が Keychain 項目 gha-quota を使おうとしています」と聞かれる。
**常に許可**を押すと、その実行ファイルだけが読めるよう ACL が固定される。
以後は他のアプリやスクリプトから `security find-generic-password` しても弾かれる。

`~/.config/gha-quota/config.json` にはユーザー名としきい値しか書かない。
dotfiles を git に入れていても、Time Machine のバックアップに乗っても、トークンは漏れない。

### 発行するトークン

**fine-grained PAT** → https://github.com/settings/personal-access-tokens/new

| 項目 | 設定 |
| --- | --- |
| Repository access | **Public repositories (read-only)** — リポジトリ権限は一切不要 |
| Account permissions → **Plan** | **Read-only** ← これだけ |
| その他の permission | 全部 No access のまま |
| Expiration | 90 days 程度 |

この権限で読めるのは課金の数字だけ。コードもクローンできないし、Issue も書けないし、
ワークフローも起動できない。**漏れた場合の被害は「今月何分使ったかを知られる」で止まる。**

classic PAT は使わないこと（`user` scope が profile の書き換えまで含んでしまう）。

### `gh auth token` について

プラグインは Keychain が空なら `gh auth token` にフォールバックするが、
`gh` の既定トークンには `Plan` 権限がないのでたいてい 403 になる。
`gh auth refresh -s user` で旧 API 用の scope を足すことはできるが、
**gh のトークンは repo / workflow / gist を持っているので、漏れたときの被害が桁違いに大きい。**
専用の最小権限 PAT を切るほうが安全。

### 期限切れ

トークンが切れるとメニューバーが `⚙︎ ?` になり、ドロップダウンに `401` と出る。
気づけるので放置しても危険はない。入れ直しは `./install.sh` を再実行するだけ。

### やめるとき

```sh
security delete-generic-password -s gha-quota
rm -rf ~/.config/gha-quota ~/.swiftbar-plugins/gha-quota.10m.py
```

そのうえで https://github.com/settings/tokens?type=beta でトークンを失効させる。

## 更新間隔

ファイル名の `10m` が更新間隔。`gha-quota.30m.py` にリネームすれば 30 分ごと、`1h` なら 1 時間ごと。
API 制限にはまず当たらないが、無駄撃ちしたくなければ 30m 程度で十分。

## 設定

`~/.config/gha-quota/config.json`（秘密情報は含まない）。

```json
{
  "user": "your-login",
  "included_minutes": 2000,
  "keychain_service": "gha-quota",
  "label": "GHA",
  "warn": 75,
  "crit": 90
}
```

| キー | 意味 |
| --- | --- |
| `included_minutes` | 無料枠の分数。Free: 2000 / Pro: 3000 / Team: 3000 |
| `keychain_service` | Keychain のサービス名 |
| `label` | ステータスバーの接頭辞。`""` にすれば数字だけ |
| `warn` / `crit` | 橙・赤に変わるしきい値（%） |

トークンの探索順は Keychain → `GHA_QUOTA_TOKEN` 環境変数 → `gh auth token` → config の `token`。
どれを使ったかはドロップダウン最下段に `鍵: Keychain` のように出る。

## 数え方の注意

- **無料枠 2,000 分は private リポジトリのみが対象。** public リポジトリの標準ランナー実行は
  そもそも課金対象外なので、この数字には出てこない。
- macOS ランナーは 1 分あたり 10 分、Windows は 2 分として無料枠を消費する。
  プラグインは SKU 名からこの倍率を掛けて「消化分数」を出しているので、
  ドロップダウンの生の分数と合計が一致しないのは正常。
- 大型ランナー（4-core 以上）はそもそも無料枠の対象外。参考値としてコア数で按分表示している。

## データ元

GitHub の課金 API は移行中で、アカウントによってどちらが返るかが違う。両方叩いて使えるほうを採用する。

| | エンドポイント | 備考 |
| --- | --- | --- |
| 旧 | `GET /users/{user}/settings/billing/actions` | `included_minutes` / `total_minutes_used` が直接返る。移行済みアカウントでは 0 が返ることがある |
| 新 | `GET /users/{user}/settings/billing/usage?year=&month=` | 現行。SKU 別の明細。`netAmount` が超過課金額 |

ドロップダウン最下段にどちらを使ったか出る。

## トラブル

| 表示 | 原因 |
| --- | --- |
| `⚙︎ ?` → トークンが見つかりません | Keychain に `gha-quota` がない、または「許可しない」を押した |
| `⚙︎ ?` → トークンの権限が足りません (403) | PAT に `Plan: Read-only` が付いていない |
| `⚙︎ ?` → トークンが無効です (401) | 期限切れ、またはトークン文字列の誤り |
| メニューバーに何も出ない | 実行権限がない → `chmod +x` / SwiftBar の Plugin Folder が違う |

手で叩いて確かめる:

```sh
~/.swiftbar-plugins/gha-quota.10m.py
```

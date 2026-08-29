# CLAUDE.md

GitHub Actions の無料枠消化率を macOS のステータスバーに出す SwiftBar プラグイン。
2026-08-29 に Cowork セッションで作成。以降はターミナルの Claude Code で調整する。

## ファイル

| パス | 役割 |
| --- | --- |
| `gha-quota.10m.py` | プラグイン本体。これが全部。macOS 標準 python3 のみ、外部依存なし |
| `install.sh` | SwiftBar 導入 → プラグイン配置 → Keychain 登録 → config 生成 → 動作確認 |
| `test_plugin.py` | API レスポンスをモックして表示分岐を全部叩く。ネットワーク不要 |
| `README.md` | 利用者向け。セットアップ、トークン権限、数え方の注意、トラブル対応 |

## 稼働中の実体（ここを直しても反映されない点に注意）

- 実行されているのは `~/.swiftbar-plugins/gha-quota.10m.py`（`install.sh` がコピーしたもの）
- このリポジトリのファイルは**マスター**。編集したら `install.sh` を再実行するか `cp` で反映する
- 設定: `~/.config/gha-quota/config.json`（`user`, `included_minutes`, `keychain_service`, `label`, `warn`, `crit`。秘密情報は入れない）
- トークン: macOS Keychain のサービス名 `gha-quota`。GitHub ユーザーは `your-login`
- SwiftBar の Plugin Folder は `~/.swiftbar-plugins`

## 動かし方

```sh
./gha-quota.10m.py                      # 本物の API を叩いて SwiftBar 形式で標準出力
python3 test_plugin.py                  # モックで全分岐を確認（ネット不要）
```

更新間隔はファイル名で決まる（`10m` → 10分）。`gha-quota.30m.py` にリネームすれば 30分。
リネームしたら `~/.swiftbar-plugins` の古いファイルを消すこと（両方動いてメニューバーに2つ出る）。

## 設計上の決定と理由

**トークンは Keychain のみ。** `load_config()` の探索順は Keychain → `GHA_QUOTA_TOKEN` → `gh auth token` → config の `token`。
config への平文書き込みは後方互換のための最終手段で、`install.sh` は絶対に書かない。この方針は変えない。

**課金 API を2本叩く。** GitHub が新課金基盤（Enhanced Billing Platform）へ移行中で、
アカウントによってどちらが返るか違う。

- 旧 `GET /users/{user}/settings/billing/actions` — `included_minutes` / `total_minutes_used` が直接返る。移行済みだと 0 が返る報告あり。現行ドキュメントからも消えかけているので、いずれ削除される前提でいる
- 新 `GET /users/{user}/settings/billing/usage?year=&month=` — SKU 別明細。`netAmount` が超過課金額。fine-grained PAT の **Plan: Read-only** が必要（classic / gh の既定トークンでは 403）

`main()` は新 API に実績があればそちらを、なければ旧 API を使う。どちらを使ったかはドロップダウン最下段に出る。

**倍率は SKU 名から引く。** `multiplier_for()` が macOS=10 / Windows=2 / Ubuntu=1、
さらに `N-core` にマッチしたら `N/2` を掛ける。価格から比率を出す方式にしなかったのは、
2026年1月の値下げで絶対額が動いたため。SKU 名のほうが安定する。

**例外を握りつぶして必ず何か出力する。** プラグインが例外で死ぬとメニューバーから静かに消えて
壊れたことに気づけない。`__main__` の `try` は残すこと。

## 未検証・弱いところ

- **実データでの疎通確認しかしていない。** モックは全分岐通っているが、`your-login` のアカウントで
  実際にどちらの API が返っているかは動作確認の1回分しか見ていない
- **大型ランナー（4-core 以上）はそもそも無料枠の対象外**なのに、コア数で按分して消化分数に混ぜている。
  参考値でしかない。正確にやるなら無料枠計算から除外して `$` の超過側だけに寄せるべき
- **月初リセットは決め打ち。** `days_left()` は月末までの日数を返すだけで、実際の請求サイクル日は見ていない
- **`included_minutes` は config の固定値。** 新課金基盤ではプランごとの無料枠がドル建てになりつつあり、
  将来ずれる可能性がある。旧 API が生きている間は `included_minutes` を上書きしている
- **public リポジトリの実行は数字に出ない。** 無料枠 2,000 分は private のみが対象なので仕様どおりだが、
  「思ったより少ない」と感じたらこれが理由

## 直すときの落とし穴

- **macOS の bash は 3.2。** 文字列中で `"$VAR）"` のように変数の直後に全角文字を置くと、
  bash 3.2 が全角文字の1バイト目を変数名に食い込ませて `set -u` で落ちる。
  `install.sh` の変数展開はすべて `${VAR}` に統一済み。この形を崩さないこと（実際にこれで一度落ちた）
- `install.sh` を書き換えたら `bash -n` だけでなく、Linux ではなく **macOS の bash** で通すこと
- SwiftBar の出力書式はパイプ区切り（`テキスト | color=#xxx size=12`）。`line()` ヘルパー経由で組み立てる

## やっていないこと

- `.gitignore` は `__pycache__` / `.DS_Store` だけ。秘密情報を含むファイルはそもそもリポジトリ内に無い（トークンは Keychain、設定は `~/.config` 配下）
- Organization の枠は見ていない。個人アカウント（`your-login`）のみ
- 通知は出していない。90% 超えで赤くなるだけ。閾値超過時に通知したいなら
  `terminal-notifier` か osascript を `render()` に足す

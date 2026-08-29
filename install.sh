#!/bin/bash
# GitHub Actions 無料枠メーター - セットアップ
# トークンは macOS Keychain にのみ保存する。ディスク上に平文で残さない。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN="gha-quota.10m.py"
CONFIG_DIR="${HOME}/.config/gha-quota"
CONFIG="${CONFIG_DIR}/config.json"
KEYCHAIN_SERVICE="gha-quota"
DEFAULT_PLUGIN_DIR="${HOME}/.swiftbar-plugins"

say()  { printf '\033[1m%s\033[0m\n' "$*"; }
warn() { printf '\033[33m%s\033[0m\n' "$*"; }

# --- 1. SwiftBar ------------------------------------------------------------
if [ ! -d "/Applications/SwiftBar.app" ]; then
  warn "SwiftBar が見つかりません。"
  read -r -p "Homebrew でインストールしますか? [y/N] " ans
  if [[ "${ans}" =~ ^[Yy]$ ]]; then
    brew install --cask swiftbar
  else
    echo "https://github.com/swiftbar/SwiftBar から入れてから再実行してください。"
    exit 1
  fi
fi

# --- 2. プラグインの配置 ------------------------------------------------------
read -r -p "プラグインフォルダ [${DEFAULT_PLUGIN_DIR}]: " PLUGIN_DIR
PLUGIN_DIR="${PLUGIN_DIR:-${DEFAULT_PLUGIN_DIR}}"
PLUGIN_DIR="${PLUGIN_DIR/#\~/${HOME}}"
mkdir -p "${PLUGIN_DIR}"
cp "${HERE}/${PLUGIN}" "${PLUGIN_DIR}/${PLUGIN}"
chmod +x "${PLUGIN_DIR}/${PLUGIN}"
say "配置しました: ${PLUGIN_DIR}/${PLUGIN}"

# --- 3. トークンを Keychain へ -------------------------------------------------
if security find-generic-password -s "${KEYCHAIN_SERVICE}" -w >/dev/null 2>&1; then
  say "Keychain に \"${KEYCHAIN_SERVICE}\" は登録済みです。"
  read -r -p "入れ直しますか? [y/N] " again
else
  again="y"
fi

if [[ "${again}" =~ ^[Yy]$ ]]; then
  cat <<'MSG'

  fine-grained PAT を発行してください。
    https://github.com/settings/personal-access-tokens/new

    Repository access : Public repositories (read-only)  ← リポジトリは一切不要
    Account permissions → Plan : Read-only               ← これだけチェック
    Expiration        : 90 days 程度を推奨

  この権限ではコード・Issue・Actions の実行のいずれにも触れません。
  読めるのは課金の数字だけです。

  次のプロンプトに貼り付けてください（画面に表示されず、ps にも残りません）。

MSG
  security add-generic-password \
    -a "${USER}" -s "${KEYCHAIN_SERVICE}" \
    -l "GitHub Actions quota (SwiftBar)" \
    -j "gha-quota SwiftBar プラグイン用。fine-grained PAT / Plan:Read-only" \
    -U -w
  say "Keychain に保存しました（サービス名: ${KEYCHAIN_SERVICE}）"
fi

# --- 4. 設定（秘密情報なし） ----------------------------------------------------
if [ ! -f "${CONFIG}" ]; then
  read -r -p "GitHub ユーザー名: " GH_USER
  read -r -p "無料枠の分数 [2000] (Free:2000 / Pro:3000): " INCLUDED
  INCLUDED="${INCLUDED:-2000}"
  mkdir -p "${CONFIG_DIR}"
  cat > "${CONFIG}" <<JSON
{
  "user": "${GH_USER}",
  "included_minutes": ${INCLUDED},
  "keychain_service": "${KEYCHAIN_SERVICE}",
  "label": "GHA",
  "warn": 75,
  "crit": 90
}
JSON
  say "設定を書きました: ${CONFIG} （トークンは含みません）"
else
  say "既存の設定を使います: ${CONFIG}"
fi

# --- 5. 動作確認 -------------------------------------------------------------
cat <<'MSG'

初回実行時に「python3 が Keychain 項目 gha-quota を使おうとしています」と聞かれます。
「常に許可」を押すと、以後はその実行ファイルだけが読めるよう ACL が固定されます。

MSG
say "動作確認:"
echo "----------------------------------------"
"${PLUGIN_DIR}/${PLUGIN}" || true
echo "----------------------------------------"
echo
say "SwiftBar を起動し、Plugin Folder に ${PLUGIN_DIR} を指定してください。"
echo "（SwiftBar → Preferences → Plugin Folder で後から変更できます）"
open -a SwiftBar 2>/dev/null || true

cat <<MSG

やめるとき:
  security delete-generic-password -s ${KEYCHAIN_SERVICE}
  rm -rf "${CONFIG_DIR}" "${PLUGIN_DIR}/${PLUGIN}"
  https://github.com/settings/tokens?type=beta でトークンを失効
MSG

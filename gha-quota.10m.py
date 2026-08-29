#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# <xbar.title>GitHub Actions Free Quota</xbar.title>
# <xbar.version>v1.0.0</xbar.version>
# <xbar.author>fk2</xbar.author>
# <xbar.desc>GitHub Actions の無料枠の消化率をステータスバーに表示する</xbar.desc>
# <xbar.dependencies>python3</xbar.dependencies>
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
#
# トークンは macOS Keychain に保存する。設定ファイルには一切書かない。
#   security add-generic-password -a "$USER" -s gha-quota -w
#
# 設定: ~/.config/gha-quota/config.json （秘密情報は含まない）
#   {
#     "user": "your-github-login",
#     "included_minutes": 2000,       // Free:2000 / Pro:3000 / Team:3000
#     "keychain_service": "gha-quota",
#     "bar_style": "solid",           // solid / eighth / shade / dots / none
#     "bar_cells": 8,
#     "show_percent": true,
#     "warn": 75,
#     "crit": 90
#   }
#
# 探す順: Keychain → GHA_QUOTA_TOKEN 環境変数 → `gh auth token` → config の "token"

import calendar
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request

API = "https://api.github.com"
CONFIG_PATH = os.path.expanduser("~/.config/gha-quota/config.json")
UA = "gha-quota-swiftbar/1.0"

# SKU 名から無料枠の消費倍率を求める。標準ランナーは 2 コアで Ubuntu=1x / Windows=2x / macOS=10x。
MULTIPLIERS = (("macos", 10), ("windows", 2), ("ubuntu", 1), ("linux", 1))

# 消化バーの文字。(消化済み, 未消化) の組。等幅フォントでないと桁が揃わないので font=Menlo で描く。
BAR_CHARS = {"solid": ("█", "░"), "shade": ("▓", "▒"), "dots": ("●", "○")}
BAR_PARTIALS = " ▏▎▍▌▋▊▉"  # 1/8 刻み。bar_style="eighth" のときだけ使う


# --------------------------------------------------------------------------- 設定

def load_config():
    cfg = {"included_minutes": 2000, "warn": 75, "crit": 90, "label": "GHA",
           "keychain_service": "gha-quota", "bar_style": "solid", "bar_cells": 8,
           "show_percent": True}
    try:
        with open(CONFIG_PATH) as fh:
            cfg.update(json.load(fh))
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as exc:
        raise SetupError("設定ファイルを読めません: %s" % exc)

    # 秘密情報は Keychain 優先。config に書いた token は後方互換のための最終手段。
    token, origin = keychain_token(cfg["keychain_service"])
    if not token and os.environ.get("GHA_QUOTA_TOKEN"):
        token, origin = os.environ["GHA_QUOTA_TOKEN"], "環境変数"
    if not token:
        token = gh_cli_token()
        origin = "gh CLI" if token else origin
    if not token and cfg.get("token"):
        token, origin = cfg["token"], "config(平文)"
    cfg["token"] = token
    cfg["token_origin"] = origin or "なし"

    if not cfg.get("user"):
        cfg["user"] = os.environ.get("GHA_QUOTA_USER") or gh_cli_login(cfg.get("token"))

    if not cfg.get("token"):
        raise SetupError("トークンが見つかりません")
    if not cfg.get("user"):
        raise SetupError("GitHub ユーザー名が未設定です")
    return cfg


def keychain_token(service):
    """macOS Keychain からトークンを読む。初回は「アクセスを許可しますか」と聞かれる。"""
    if not os.path.exists("/usr/bin/security"):
        return None, None
    try:
        out = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-s", service, "-w"],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return None, None
    if out.returncode != 0:
        return None, None
    return (out.stdout.strip() or None), "Keychain"


def gh_cli_token():
    gh = shutil.which("gh") or "/opt/homebrew/bin/gh"
    if not os.path.exists(gh):
        return None
    try:
        out = subprocess.run([gh, "auth", "token"], capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def gh_cli_login(token):
    if not token:
        return None
    try:
        return api_get("/user", token).get("login")
    except Exception:
        return None


class SetupError(Exception):
    pass


# --------------------------------------------------------------------------- API

def api_get(path, token):
    req = urllib.request.Request(
        API + path,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": UA,
        },
    )
    with urllib.request.urlopen(req, timeout=20) as res:
        return json.loads(res.read().decode("utf-8"))


def fetch_legacy(user, token):
    """旧課金基盤。included_minutes / total_minutes_used がそのまま返る。"""
    try:
        data = api_get("/users/%s/settings/billing/actions" % user, token)
    except Exception:
        return None
    if not isinstance(data, dict) or "included_minutes" not in data:
        return None
    return data


def fetch_usage(user, token, today):
    """新課金基盤 (Enhanced Billing Platform) の当月利用明細。"""
    path = "/users/%s/settings/billing/usage?year=%d&month=%d" % (user, today.year, today.month)
    data = api_get(path, token)
    return data.get("usageItems") or []


# --------------------------------------------------------------------------- 集計

def multiplier_for(sku):
    s = (sku or "").lower()
    factor = 1
    for name, value in MULTIPLIERS:
        if name in s:
            factor = value
            break
    cores = re.search(r"(\d+)\s*[- ]?core", s)
    if cores:
        # 標準ランナーは 2 コア。それより大きいランナーは無料枠の対象外だが、按分して見積もる。
        factor *= max(1, int(cores.group(1)) // 2)
    return factor


def summarize_usage(items):
    raw = 0.0
    weighted = 0.0
    overage = 0.0
    by_sku = {}
    for item in items:
        if (item.get("product") or "").lower() != "actions":
            continue
        if "minute" not in (item.get("unitType") or "").lower():
            continue
        qty = float(item.get("quantity") or 0)
        mult = multiplier_for(item.get("sku"))
        raw += qty
        weighted += qty * mult
        overage += float(item.get("netAmount") or 0)
        key = item.get("sku") or "unknown"
        entry = by_sku.setdefault(key, {"raw": 0.0, "weighted": 0.0, "mult": mult})
        entry["raw"] += qty
        entry["weighted"] += qty * mult
    return {"raw": raw, "weighted": weighted, "overage": overage, "by_sku": by_sku}


def summarize_legacy(data):
    breakdown = data.get("minutes_used_breakdown") or {}
    by_sku = {}
    for key, qty in breakdown.items():
        if key.lower() == "total" or not qty:
            continue
        mult = multiplier_for(key)
        by_sku[key] = {"raw": float(qty), "weighted": float(qty) * mult, "mult": mult}
    total = float(data.get("total_minutes_used") or 0)
    weighted = sum(e["weighted"] for e in by_sku.values()) if by_sku else total
    return {
        "raw": total,
        "weighted": weighted,
        "overage": None,
        "paid_minutes": float(data.get("total_paid_minutes_used") or 0),
        "included": float(data.get("included_minutes") or 0),
        "by_sku": by_sku,
    }


# --------------------------------------------------------------------------- 出力

def bar(pct, cells=8, style="solid"):
    """消化率をブロック文字のバーにする。100% を超えても満杯で止める（色で警告する）。"""
    if style == "none" or cells < 1:
        return ""
    ratio = max(0.0, min(1.0, pct / 100.0))
    if style == "eighth":
        units = ratio * cells * 8
        full = int(units // 8)
        if full >= cells:
            return "█" * cells
        rem = int(units % 8)
        return "█" * full + (BAR_PARTIALS[rem] if rem else "░") + "░" * (cells - full - 1)
    on, off = BAR_CHARS.get(style, BAR_CHARS["solid"])
    filled = min(cells, int(round(ratio * cells)))
    return on * filled + off * (cells - filled)


def title_for(pct, cfg):
    """メニューバーに出す1行。ラベル / バー / % を空でないものだけ繋ぐ。"""
    parts = [
        cfg.get("label", "GHA"),
        bar(pct, int(cfg.get("bar_cells", 8)), cfg.get("bar_style", "solid")),
        "%d%%" % round(pct) if cfg.get("show_percent", True) else "",
    ]
    return " ".join(x for x in parts if x)


def color_for(pct, cfg):
    if pct >= cfg["crit"]:
        return "#ff453a"
    if pct >= cfg["warn"]:
        return "#ff9f0a"
    return None


def line(text, **params):
    extras = " ".join("%s=%s" % (k, v) for k, v in params.items() if v is not None)
    return text + (" | " + extras if extras else "")


def days_left(today):
    return calendar.monthrange(today.year, today.month)[1] - today.day + 1


def render(cfg, stats, source, today):
    included = stats.get("included") or float(cfg["included_minutes"])
    used = stats["weighted"]
    pct = (used / included * 100.0) if included else 0.0
    remaining = max(0.0, included - used)

    out = [
        line(title_for(pct, cfg), symbolize="false", color=color_for(pct, cfg), font="Menlo", size=13),
        "---",
        line("GitHub Actions 無料枠", color="#888888"),
        line("消化 %s / %s 分 (%d%%)" % (fmt(used), fmt(included), round(pct))),
        line("残り %s 分" % fmt(remaining)),
        line("今月の残り %d 日 (月初リセット想定)" % days_left(today), color="#888888"),
    ]

    if stats["by_sku"]:
        out.append("---")
        out.append(line("内訳", color="#888888"))
        for sku, e in sorted(stats["by_sku"].items(), key=lambda kv: -kv[1]["weighted"]):
            label = "%s: %s 分" % (sku, fmt(e["raw"]))
            if e["mult"] != 1:
                label += " ×%d = %s" % (e["mult"], fmt(e["weighted"]))
            out.append(line(label, font="Menlo", size=12))

    out.append("---")
    if stats.get("overage") is not None:
        out.append(line("超過課金 $%.2f" % stats["overage"]))
    elif stats.get("paid_minutes"):
        out.append(line("超過分 %s 分" % fmt(stats["paid_minutes"])))
    out.append(line("public リポジトリの標準ランナーは対象外", color="#888888", size=11))
    out.append("---")
    out.append(line("課金ページを開く", href="https://github.com/settings/billing/summary"))
    out.append(line("Actions の利用状況", href="https://github.com/settings/billing/usage"))
    out.append(line("今すぐ更新", refresh="true"))
    out.append(line("%s / 鍵: %s / %s 更新"
                    % (source, cfg.get("token_origin", "?"), dt.datetime.now().strftime("%H:%M")),
                    color="#888888", size=11))
    return "\n".join(out)


def fmt(value):
    return "{:,}".format(int(round(value)))


def render_error(message, detail=None):
    out = [
        line("⚙︎ ?", color="#ff9f0a"),
        "---",
        line(message),
    ]
    if detail:
        out.append(line(detail, font="Menlo", size=11, color="#888888"))
    out += [
        "---",
        line("トークンは Keychain の \"gha-quota\" に入れる:", size=11, color="#888888"),
        line("  security add-generic-password -a \"$USER\" -s gha-quota -w",
             font="Menlo", size=11, color="#888888"),
        line("必要な権限: fine-grained PAT の Account permissions → Plan: Read-only のみ",
             size=11, color="#888888"),
        line("トークンを発行する", href="https://github.com/settings/personal-access-tokens/new"),
        line("今すぐ更新", refresh="true"),
    ]
    return "\n".join(out)


# --------------------------------------------------------------------------- main

def main():
    try:
        cfg = load_config()
    except SetupError as exc:
        return render_error(str(exc), "設定を作成してから再読み込みしてください")

    today = dt.date.today()
    legacy = fetch_legacy(cfg["user"], cfg["token"])

    stats = None
    source = ""
    usage_error = None
    try:
        items = fetch_usage(cfg["user"], cfg["token"], today)
        new_stats = summarize_usage(items)
        if new_stats["raw"] > 0:
            stats = new_stats
            source = "新課金API"
            if legacy and legacy.get("included_minutes"):
                stats["included"] = float(legacy["included_minutes"])
    except urllib.error.HTTPError as exc:
        usage_error = "HTTP %s (%s)" % (exc.code, exc.reason)
    except Exception as exc:
        usage_error = str(exc)

    if stats is None and legacy is not None:
        stats = summarize_legacy(legacy)
        source = "旧課金API"

    if stats is None:
        if usage_error and "403" in usage_error:
            return render_error("トークンの権限が足りません", usage_error)
        if usage_error and "401" in usage_error:
            return render_error("トークンが無効です", usage_error)
        return render_error("利用状況を取得できませんでした", usage_error or "不明なエラー")

    return render(cfg, stats, source, today)


if __name__ == "__main__":
    try:
        print(main())
    except Exception as exc:  # プラグインが落ちるとメニューバーから消えるので必ず何か出す
        print(render_error("プラグインでエラーが発生しました", repr(exc)))

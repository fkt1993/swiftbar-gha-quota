#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gha-quota プラグインの分岐を一通り実行して出力を目視確認する。"""
import datetime as dt
import importlib.util
import urllib.error
import io

spec = importlib.util.spec_from_file_location("plugin", "gha-quota.10m.py")
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)

CFG = {"user": "fk2", "token": "t", "token_origin": "Keychain",
       "included_minutes": 2000, "warn": 75, "crit": 90, "label": "GHA"}
TODAY = dt.date(2026, 8, 29)


def banner(title):
    print("\n" + "=" * 60)
    print("CASE:", title)
    print("=" * 60)


# --- 1. 設定なし -------------------------------------------------------------
banner("設定ファイルなし")
p.CONFIG_PATH = "/nonexistent/config.json"
p.gh_cli_token = lambda: None
p.keychain_token = lambda s: (None, None)
import os
os.environ.pop("GHA_QUOTA_TOKEN", None)
print(p.main())

# 以降は設定ありに固定
p.load_config = lambda: dict(CFG)

# --- 2. 旧 API のみ -----------------------------------------------------------
banner("旧課金API（新APIは 0 件）")
p.fetch_legacy = lambda u, t: {
    "total_minutes_used": 1240,
    "total_paid_minutes_used": 0,
    "included_minutes": 2000,
    "minutes_used_breakdown": {"UBUNTU": 900, "MACOS": 34, "WINDOWS": 0, "total": 1240},
}
p.fetch_usage = lambda u, t, d: []
print(p.main())

# --- 3. 新 API に利用実績あり --------------------------------------------------
banner("新課金API（Ubuntu + macOS、無料枠内）")
p.fetch_usage = lambda u, t, d: [
    {"product": "Actions", "sku": "Actions Linux", "quantity": 900, "unitType": "Minutes",
     "pricePerUnit": 0.008, "grossAmount": 7.2, "discountAmount": 7.2, "netAmount": 0.0,
     "repositoryName": "fk2/app"},
    {"product": "Actions", "sku": "Actions macOS", "quantity": 34, "unitType": "Minutes",
     "pricePerUnit": 0.08, "grossAmount": 2.72, "discountAmount": 2.72, "netAmount": 0.0,
     "repositoryName": "fk2/app"},
    {"product": "Packages", "sku": "Packages storage", "quantity": 120,
     "unitType": "GigabyteHours", "pricePerUnit": 0.008, "grossAmount": 0.96,
     "discountAmount": 0.96, "netAmount": 0.0, "repositoryName": "fk2/app"},
]
print(p.main())

# --- 4. 超過あり（赤表示） -----------------------------------------------------
banner("新課金API（無料枠超過・crit 到達）")
p.fetch_usage = lambda u, t, d: [
    {"product": "Actions", "sku": "Actions Linux", "quantity": 1800, "unitType": "Minutes",
     "pricePerUnit": 0.008, "grossAmount": 14.4, "discountAmount": 12.0, "netAmount": 2.4},
    {"product": "Actions", "sku": "Actions Windows 4-core", "quantity": 60,
     "unitType": "Minutes", "pricePerUnit": 0.032, "grossAmount": 1.92,
     "discountAmount": 0.0, "netAmount": 1.92},
]
print(p.main())

# --- 5. 権限不足 --------------------------------------------------------------
banner("新API 403 / 旧API も不可")
p.fetch_legacy = lambda u, t: None


def boom(u, t, d):
    raise urllib.error.HTTPError("url", 403, "Forbidden", None, io.BytesIO(b""))


p.fetch_usage = boom
print(p.main())

# --- 6. 月初 -----------------------------------------------------------------
# 新 API は 200 で usageItems が空（＝今月まだ 0 分）、旧 API は移行済みで 410 Gone。
# ここで「取得失敗」に倒すと月初の数日だけエラー表示になる。
banner("月初: 新API 0 件 / 旧API 410 Gone")
p.LEGACY_ERROR = "HTTP 410 (Gone)"
p.fetch_legacy = lambda u, t: None
p.fetch_usage = lambda u, t, d: []
print(p.main())

# --- 7. 倍率判定の単体確認 ------------------------------------------------------
banner("multiplier_for()")
for sku, expected in [
    ("Actions Linux", 1), ("UBUNTU", 1), ("Actions macOS", 10), ("MACOS", 10),
    ("Actions Windows", 2), ("WINDOWS", 2), ("Actions Linux 8-core", 4),
    ("Actions macOS 12-core", 60), ("Actions Windows 4 core", 4), ("mystery", 1),
]:
    got = p.multiplier_for(sku)
    print("%-28s -> %-4s %s" % (sku, got, "OK" if got == expected else "NG(expected %s)" % expected))


# --- 8. バー描画の単体確認 ------------------------------------------------------
banner("bar()")
for pct, expected in [
    (0, "░░░░░░░░"), (6, "░░░░░░░░"), (7, "█░░░░░░░"), (25, "██░░░░░░"),
    (50, "████░░░░"), (62, "█████░░░"), (90, "███████░"), (100, "████████"),
    (118, "████████"), (-5, "░░░░░░░░"),
]:
    got = p.bar(pct)
    print("%4d%% -> %s %s" % (pct, got, "OK" if got == expected else "NG(expected %s)" % expected))

print()
for style in ("solid", "shade", "dots", "eighth", "none"):
    print("%-8s 62%% -> [%s]" % (style, p.bar(62, 8, style)))

print()
print("幅指定:", " / ".join("%d cells: %s" % (n, p.bar(62, n)) for n in (6, 8, 10, 20)))

print()
banner("title_for()")
for cfg in [
    dict(CFG),
    dict(CFG, show_percent=False),
    dict(CFG, label=""),
    dict(CFG, label="", show_percent=False),
    dict(CFG, bar_style="none"),
    dict(CFG, bar_style="eighth", bar_cells=10),
]:
    desc = "label=%r style=%s cells=%s pct=%s" % (
        cfg.get("label"), cfg.get("bar_style", "solid"),
        cfg.get("bar_cells", 8), cfg.get("show_percent", True))
    print("%-52s -> [%s]" % (desc, p.title_for(62.4, cfg)))

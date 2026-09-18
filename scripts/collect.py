#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""微信 RadiumWMPF 小程序容器插件 —— 版本自动收集器。

流程:
  1. 拉取微信 4.x(Uni) / 3.x 两份 XPlugin 更新配置 XML, 按 configVer 存档到 configs/
  2. 解析出 RadiumWMPF 的全量包条目 (build/semver/fullurl/md5)
  3. 与 GitHub Release 现有 tag 对比, 缺失的: 下载 zip → md5 校验 → 建 Release 上传
     (Release 已存在但 asset 缺失时只补传, 不重复建)
  4. 更新 versions.json 索引 (由 workflow 里单独的 step 提交)

用法:
  python scripts/collect.py --dry-run      # 只拉配置+解析打印, 不下载不上传
  python scripts/collect.py --skip-upload  # 下载+校验, 不操作 Release (本地测试)
  python scripts/collect.py                # 全流程 (需 gh CLI, GH_TOKEN 已导出)

设计约束: 仅标准库 + curl + gh, 无第三方依赖。
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "configs"
DOWNLOAD_DIR = REPO_ROOT / "downloads"
INDEX_PATH = REPO_ROOT / "versions.json"

PLUGIN = "RadiumWMPF"

# (来源key, 配置URL)。uni4 = 微信 4.x UniWeChatWin 新架构; win3 = 3.x 经典架构。
# 两份配置里的 RadiumWMPF build 号各自独立递增, build 全局唯一, 冲突时先到先得。
SOURCES = [
    ("uni4", "https://dldir1v6.qq.com/weixin/Universal/Windows/XPlugin/updateConfigUniWin.xml"),
    ("win3", "https://dldir1.qq.com/weixin/Windows/XPlugin/updateConfigWin.xml"),
]


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sh(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise RuntimeError(
            "命令失败: %s\n%s" % (" ".join(map(str, cmd)), (r.stderr or r.stdout)[-2000:])
        )
    return r.stdout


def fetch(url, dest: Path):
    subprocess.run(
        ["curl", "-fSL", "--retry", "5", "--retry-delay", "5",
         "--connect-timeout", "20", "-o", str(dest), url],
        check=True,
    )


def md5_of(p: Path):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def parse_plugin_versions(xml_path: Path, origin: str):
    """解析一份配置, 返回 {build: entry}。同 build 多条分发策略时取首条。"""
    root = ET.parse(xml_path).getroot()
    out = {}
    for vi in root.iter("VersionInfo"):
        if vi.get("name") != PLUGIN:
            continue
        fullurl = vi.get("fullurl") or ""
        build = int(vi.get("version") or 0)
        if not fullurl or not build or build in out:
            continue
        m = re.search(r"_(\d+(?:\.\d+){2,3})_.*_V(\d+)\.zip$", fullurl)
        semver = m.group(1) if m else ""
        arch = "x64" if "_x64_" in fullurl else ("x86" if "_x86_" in fullurl else "?")
        out[build] = {
            "plugin": PLUGIN,
            "build": build,
            "semver": semver,
            "arch": arch,
            "fullurl": fullurl,
            "md5": (vi.get("md5") or "").upper(),
            "appClientVerMin": vi.get("appClientVerMin", ""),
            "origin": origin,
            "firstSeen": now_iso(),
        }
    return out


def gh_release_tags():
    out = sh(["gh", "release", "list", "--limit", "400", "--json", "tagName"])
    return {r["tagName"] for r in json.loads(out)}


def gh_release_asset_names(tag):
    out = sh(["gh", "release", "view", tag, "--json", "assets"])
    return {a["name"] for a in json.loads(out)["assets"]}


def download_and_verify(entry):
    zip_name = Path(entry["fullurl"]).name
    zip_path = DOWNLOAD_DIR / zip_name
    if not (zip_path.exists() and md5_of(zip_path) == entry["md5"]):
        print("  下载 %s ..." % entry["fullurl"])
        fetch(entry["fullurl"], zip_path)
        got = md5_of(zip_path)
        if entry["md5"] and got != entry["md5"]:
            zip_path.unlink(missing_ok=True)
            raise SystemExit(
                "[error] %s md5 不符: 期望 %s 实际 %s" % (zip_name, entry["md5"], got)
            )
    return zip_path


def main():
    ap = argparse.ArgumentParser(description="RadiumWMPF 版本收集器")
    ap.add_argument("--dry-run", action="store_true", help="只解析打印, 不下载不上传")
    ap.add_argument("--skip-upload", action="store_true", help="下载+校验, 不操作 Release")
    args = ap.parse_args()

    CONFIG_DIR.mkdir(exist_ok=True)
    DOWNLOAD_DIR.mkdir(exist_ok=True)

    # 1. 拉两份配置 + 存档 + 解析合并
    collected = {}
    for key, url in SOURCES:
        latest = CONFIG_DIR / ("%s-latest.xml" % key)
        try:
            fetch(url, latest)
        except Exception as e:
            print("[warn] 源 %s 拉取失败, 跳过: %s" % (key, e))
            continue
        config_ver = ET.parse(latest).getroot().get("configVer", "?")
        archive = CONFIG_DIR / ("%s-cv%s.xml" % (key, config_ver))
        if not archive.exists():
            archive.write_bytes(latest.read_bytes())
            print("[cfg] %s configVer=%s 已存档" % (key, config_ver))
        entries = parse_plugin_versions(latest, origin=key)
        for build, e in entries.items():
            collected.setdefault(build, e)
        print("[cfg] %s: %d 个 %s 版本" % (key, len(entries), PLUGIN))

    if not collected:
        raise SystemExit("[error] 两份配置都没有解析到 %s 条目" % PLUGIN)

    print("\n配置内在架版本 (按 build 排序):")
    for build, e in sorted(collected.items()):
        print("  V%-6d %-12s %-4s md5=%s  <- %s" % (build, e["semver"], e["arch"], e["md5"][:8], e["origin"]))

    if args.dry_run:
        print("\n[dry-run] 到此为止, 共 %d 个版本" % len(collected))
        return

    # 2. 对比 Release
    if args.skip_upload:
        existing_tags = set()
    else:
        existing_tags = gh_release_tags()

    index = {"versions": {}}
    if INDEX_PATH.exists():
        try:
            index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    new_cnt = skip_cnt = patch_cnt = 0
    for build, e in sorted(collected.items()):
        tag = "%s-%d" % (PLUGIN, build)
        zip_name = Path(e["fullurl"]).name
        if tag in existing_tags:
            if zip_name in gh_release_asset_names(tag):
                print("[skip] %s 已存在" % tag)
                skip_cnt += 1
                continue
            print("[patch] %s 存在但缺 asset, 补传" % tag)
            zip_path = download_and_verify(e)
            if not args.skip_upload:
                sh(["gh", "release", "upload", tag, str(zip_path), "--clobber"])
            patch_cnt += 1
        else:
            zip_path = download_and_verify(e)
            title = "%s %s (V%d)" % (PLUGIN, e["semver"], build) if e["semver"] else "%s V%d" % (PLUGIN, build)
            notes = json.dumps({
                "plugin": PLUGIN, "build": build, "semver": e["semver"], "arch": e["arch"],
                "sourceConfig": e["origin"], "officialUrl": e["fullurl"], "md5": e["md5"],
                "appClientVerMin": e["appClientVerMin"], "collectedAt": now_iso(),
                "note": "Tencent WeChat component, collected for debugging/research. 版权归腾讯所有.",
            }, ensure_ascii=False, indent=2)
            if not args.skip_upload:
                sh(["gh", "release", "create", tag, str(zip_path),
                    "--title", title, "--notes", notes])
            print("[new] %s 已上传 (%s)" % (tag, title))
            new_cnt += 1
        e = dict(e)
        e.pop("firstSeen", None)
        e["collectedAt"] = now_iso()
        index["versions"][tag] = e

    index["updatedAt"] = now_iso()
    INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n[done] 新增 %d / 补传 %d / 跳过 %d, 索引共 %d 条 → %s"
          % (new_cnt, patch_cnt, skip_cnt, len(index["versions"]), INDEX_PATH.name))


if __name__ == "__main__":
    sys.exit(main())

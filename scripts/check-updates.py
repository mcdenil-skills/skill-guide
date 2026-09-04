#!/usr/bin/env python3
"""
check-updates.py — сравнивает установленные версии скиллов с доступными.

Делает git fetch по витринам плагинов и по gstack (только чтение, рабочее дерево не трогает),
сравнивает установленный sha/версию с последним доступным и пишет:
  data/updates.json  ->  { "имя-скилла": {installed, latest, updatable, via}, ... }

Применение обновлений — ОТДЕЛЬНО и по твоей команде: scripts/update-skills.sh
Запуск: python3 scripts/check-updates.py
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "updates.json"
SKILLS_JS = DATA / "skills-data.js"

PLUGIN_MARKETS = HOME / ".claude" / "plugins" / "marketplaces"
INSTALLED_JSON = HOME / ".claude" / "plugins" / "installed_plugins.json"
GSTACK_DIR = HOME / ".claude" / "skills" / "gstack"


def git(args, cwd):
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                              text=True, timeout=40).stdout.strip()
    except Exception:
        return ""


def catalog_skills():
    """name -> {source, sourceUrl} из собранного каталога."""
    m = re.search(r"window\.SKILLS = (\[.*?\]);\nwindow", SKILLS_JS.read_text(), re.S)
    return {s["name"]: s for s in json.loads(m.group(1))}


def load_installed():
    out = {}
    d = json.loads(INSTALLED_JSON.read_text()).get("plugins", {})
    for key, v in d.items():
        if "@" not in key:
            continue
        plugin, mp = key.split("@", 1)
        e = v[0] if isinstance(v, list) and v else {}
        out[(mp, plugin)] = {"version": e.get("version"), "sha": (e.get("gitCommitSha") or "")[:12]}
    return out


def marketplace_heads():
    """marketplace -> origin HEAD sha (после fetch)."""
    heads = {}
    for mp_dir in sorted(PLUGIN_MARKETS.glob("*")):
        if not (mp_dir / ".git").exists():
            continue
        git(["fetch", "--quiet", "origin"], mp_dir)
        head = git(["rev-parse", "--short=12", "origin/HEAD"], mp_dir) or \
               git(["rev-parse", "--short=12", "origin/main"], mp_dir) or \
               git(["rev-parse", "--short=12", "HEAD"], mp_dir)
        heads[mp_dir.name] = head
    return heads


def catalog_sources():
    """(mp, plugin) -> source (строка './plugins/X' или dict с pinned sha)."""
    out = {}
    for f in PLUGIN_MARKETS.glob("*/.claude-plugin/marketplace.json"):
        mp = f.parent.parent.name
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for p in d.get("plugins", []):
            out[(mp, p["name"])] = p.get("source")
    return out


def plugin_status(installed, sources):
    """Точный статус по каждому плагину: обновилась ли ИМЕННО его папка.
    Возвращает {plugin_name: {installed, latest, updatable, via}}."""
    status = {}
    fetched = set()
    for (mp, plugin), inst in installed.items():
        src = sources.get((mp, plugin))
        sha = inst.get("sha", "")
        ver = inst.get("version") or ""
        mp_dir = PLUGIN_MARKETS / mp
        inst_label = ver if (ver and ver != "unknown") else (sha[:8] if sha else "?")
        latest, updatable, via = "", None, f"/plugin update {plugin}"

        if not (mp_dir / ".git").exists():
            status[plugin] = {"installed": inst_label, "latest": "", "updatable": None, "via": via}
            continue
        if mp not in fetched:
            git(["fetch", "--quiet", "origin"], mp_dir)
            fetched.add(mp)
        head = git(["rev-parse", "--short=12", "origin/HEAD"], mp_dir) or \
               git(["rev-parse", "--short=12", "origin/main"], mp_dir)

        if isinstance(src, dict):
            pin = (src.get("sha") or "")[:12]
            ref = src.get("ref") or ""
            latest = ref or (pin[:8] if pin else "")
            if sha and pin:
                updatable = sha != pin
            else:
                updatable = None  # неизвестно (нет sha) — НЕ утверждаем, что устарело
        elif isinstance(src, str):
            sub = src.lstrip("./").rstrip("/")
            path = sub if sub else "."
            if sha:
                log = git(["log", f"{sha}..origin/HEAD", "--oneline", "--", path], mp_dir)
                updatable = bool(log.strip())
                latest = head if updatable else inst_label
            else:
                updatable = None
                latest = head
        status[plugin] = {"installed": inst_label, "latest": latest,
                          "updatable": updatable, "via": via}
    return status


def main():
    cat = catalog_skills()
    installed = load_installed()
    sources = catalog_sources()
    print("[..] git fetch по витринам и gstack (может занять минуту)…")
    pstatus = plugin_status(installed, sources)

    # gstack — весь репозиторий (все его скиллы общие)
    gstack_inst = git(["rev-parse", "--short=12", "HEAD"], GSTACK_DIR)
    git(["fetch", "--quiet", "origin"], GSTACK_DIR)
    gstack_latest = git(["rev-parse", "--short=12", "origin/HEAD"], GSTACK_DIR) or \
                    git(["rev-parse", "--short=12", "origin/main"], GSTACK_DIR)
    # менялось ли что-то в gstack между установленным и текущим
    gstack_log = git(["log", f"{gstack_inst}..origin/HEAD", "--oneline"], GSTACK_DIR) if gstack_inst else ""
    gstack_upd = bool(gstack_log.strip())

    updates = {}
    for name, s in cat.items():
        src = s.get("source", "")
        if src == "gstack":
            updates[name] = {
                "installed": gstack_inst[:8], "latest": gstack_latest[:8] if gstack_upd else gstack_inst[:8],
                "updatable": gstack_upd,
                "via": "git -C ~/.claude/skills/gstack pull  (или скилл gstack-upgrade)",
            }
        elif src in pstatus:
            st = pstatus[src]
            updates[name] = {
                "installed": st["installed"], "latest": st["latest"],
                "updatable": bool(st["updatable"]), "via": st["via"],
                "unknown": st["updatable"] is None,
            }

    n_upd = sum(1 for u in updates.values() if u["updatable"])
    OUT.write_text(json.dumps(updates, ensure_ascii=False, indent=1))
    print(f"[ok] проверено скиллов с версиями: {len(updates)}")
    print(f"[ok] доступно обновлений: {n_upd}")
    if n_upd:
        for name, u in updates.items():
            if u["updatable"]:
                print(f"     🔄 {name}: {u['installed']} -> {u['latest']}")
    print(f"[ok] записано -> {OUT}")


if __name__ == "__main__":
    main()

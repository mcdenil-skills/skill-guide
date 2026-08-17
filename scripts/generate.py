#!/usr/bin/env python3
"""
generate.py — сканер каталога скиллов для Skill-Guide.

Быстрое ядро (без сети):
  1. Обходит три источника скиллов на диске + кэш плагинов.
  2. Читает SKILL.md (frontmatter: name, description).
  3. Платформа (claude/codex/both) по расположению.
  4. ТОЧНЫЙ источник GitHub из marketplace.json (реальный репозиторий + диплинк + ref).
  5. Установленная версия/sha из installed_plugins.json.
  6. Склейка с overrides.json (русские описания/категории).
  7. Подмешивает, если есть: data/updates.json (статус обновлений) и data/usage.json (счётчики).
  8. Пишет data/skills-data.js.

Тяжёлые сканы — отдельно:
  scripts/check-updates.py  -> data/updates.json  (git-fetch витрин, сеть)
  scripts/usage-scan.py     -> data/usage.json    (обход логов сессий)
"""
import json
import os
import re
import sys
from pathlib import Path

HOME = Path.home()
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OVERRIDES_PATH = DATA / "overrides.json"
OUT_PATH = DATA / "skills-data.js"
UPDATES_PATH = DATA / "updates.json"
USAGE_PATH = DATA / "usage.json"
LINKS_PATH = DATA / "links.json"

AGENTS_DIR = HOME / ".agents" / "skills"
CLAUDE_DIR = HOME / ".claude" / "skills"
CODEX_DIR = HOME / ".codex" / "skills"
PLUGIN_CACHE = HOME / ".claude" / "plugins" / "cache"
PLUGIN_MARKETS = HOME / ".claude" / "plugins" / "marketplaces"
MARKETPLACES_JSON = HOME / ".claude" / "plugins" / "known_marketplaces.json"
INSTALLED_JSON = HOME / ".claude" / "plugins" / "installed_plugins.json"

GITHUB_BASE = "https://github.com/"


def norm_git_url(raw: str) -> str:
    if not raw:
        return ""
    raw = raw.strip()
    raw = re.sub(r"^git\+", "", raw)
    raw = re.sub(r"^http://", "https://", raw)
    raw = re.sub(r"\.git$", "", raw)
    if raw.startswith("https://"):
        return raw
    if re.match(r"^[\w.-]+/[\w.-]+$", raw):
        return GITHUB_BASE + raw
    return raw


def load_marketplaces() -> dict:
    """marketplace_id -> github url (репозиторий самой витрины)"""
    out = {}
    try:
        data = json.loads(MARKETPLACES_JSON.read_text())
        for mid, entry in data.items():
            src = entry.get("source", {})
            out[mid] = norm_git_url(src.get("url") or src.get("repo") or "")
    except Exception as e:
        print(f"[warn] marketplaces: {e}", file=sys.stderr)
    return out


def load_installed() -> dict:
    """(marketplace, plugin) -> {version, sha}"""
    out = {}
    try:
        d = json.loads(INSTALLED_JSON.read_text()).get("plugins", {})
        for key, v in d.items():
            if "@" not in key:
                continue
            plugin, mp = key.split("@", 1)
            e = v[0] if isinstance(v, list) and v else {}
            out[(mp, plugin)] = {
                "version": e.get("version"),
                "sha": (e.get("gitCommitSha") or "")[:12],
            }
    except Exception as e:
        print(f"[warn] installed: {e}", file=sys.stderr)
    return out


def load_catalog(markets: dict) -> dict:
    """(marketplace, plugin) -> {url, deeplink, ref, sha}  (настоящий источник плагина)"""
    out = {}
    for f in PLUGIN_MARKETS.glob("*/.claude-plugin/marketplace.json"):
        mp = f.parent.parent.name
        mp_url = markets.get(mp, "")
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for p in d.get("plugins", []):
            name = p.get("name")
            src = p.get("source")
            url, deeplink, ref, sha = mp_url, mp_url, "main", ""
            if isinstance(src, str):
                # относительная подпапка внутри репозитория витрины
                sub = src.lstrip("./").rstrip("/")
                url = mp_url
                deeplink = f"{mp_url}/tree/main/{sub}" if sub else mp_url
            elif isinstance(src, dict):
                url = norm_git_url(src.get("url", ""))
                ref = src.get("ref") or "main"
                sha = (src.get("sha") or "")[:12]
                path = src.get("path", "").strip("/")
                deeplink = f"{url}/tree/{ref}/{path}" if path else f"{url}/tree/{ref}"
            out[(mp, name)] = {"url": url, "deeplink": deeplink, "ref": ref, "sha": sha}
    return out


def parse_frontmatter(path: Path) -> dict:
    try:
        text = path.read_text(errors="replace")
    except Exception:
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    fm = text[3:end]
    lines = fm.splitlines()
    out = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^(\w[\w-]*):\s*(.*)$", line)
        if not m:
            i += 1
            continue
        key, val = m.group(1), m.group(2).strip()
        if key not in ("name", "description"):
            i += 1
            continue
        if val in ("|", ">", "|-", ">-", "|+", ">+"):
            block = []
            i += 1
            while i < len(lines) and (lines[i].startswith("  ") or lines[i].strip() == ""):
                block.append(lines[i].strip())
                i += 1
            out[key] = " ".join(x for x in block if x).strip()
            continue
        out[key] = val.strip().strip('"').strip("'")
        i += 1
    return out


def collect_disk_skills() -> dict:
    acc = {}

    def add(dir_path: Path, loc_tag: str):
        if not dir_path.exists():
            return
        for sub in sorted(dir_path.iterdir()):
            skill_md = sub / "SKILL.md"
            if not skill_md.exists():
                continue
            fm = parse_frontmatter(skill_md)
            name = fm.get("name") or sub.name
            entry = acc.setdefault(name, {"locations": set(), "desc": ""})
            entry["locations"].add(loc_tag)
            if fm.get("description") and not entry["desc"]:
                entry["desc"] = fm["description"]

    add(AGENTS_DIR, "agents")
    add(CLAUDE_DIR, "claude")
    add(CODEX_DIR, "codex")
    for base in (CLAUDE_DIR / "gstack", AGENTS_DIR / "gstack"):
        add(base, "agents" if "agents" in str(base) else "claude")
    return acc


def collect_plugin_skills(markets, catalog, installed) -> dict:
    """{name: {plugin, marketplace, desc, url, deeplink, installed, latestSha}}"""
    acc = {}
    if not PLUGIN_CACHE.exists():
        return acc
    for mp_dir in sorted(PLUGIN_CACHE.iterdir()):
        if not mp_dir.is_dir():
            continue
        marketplace = mp_dir.name
        for skill_md in mp_dir.rglob("SKILL.md"):
            parts = skill_md.parts
            if "skills" not in parts:
                continue
            try:
                mp_idx = parts.index(marketplace)
                plugin = parts[mp_idx + 1]
            except (ValueError, IndexError):
                plugin = marketplace
            fm = parse_frontmatter(skill_md)
            name = fm.get("name") or skill_md.parent.name
            if name in acc:
                continue
            cat = catalog.get((marketplace, plugin), {})
            inst = installed.get((marketplace, plugin), {})
            acc[name] = {
                "plugin": plugin,
                "marketplace": marketplace,
                "desc": fm.get("description", ""),
                "url": cat.get("url") or markets.get(marketplace, ""),
                "deeplink": cat.get("deeplink") or markets.get(marketplace, ""),
                "installed": inst.get("version") or (inst.get("sha") or "")[:8] or "",
                "installedSha": inst.get("sha", ""),
                "latestSha": cat.get("sha", ""),
            }
    return acc


def platform_from_locations(locs: set) -> str:
    if "agents" in locs:
        return "both"
    if "codex" in locs and "claude" not in locs:
        return "codex"
    return "claude"


SOURCE_CAT = {"vercel": "vercel", "codex": "dev", "hookify": "meta", "skill-creator": "meta"}


def build():
    markets = load_marketplaces()
    installed = load_installed()
    catalog = load_catalog(markets)
    disk = collect_disk_skills()
    plugins = collect_plugin_skills(markets, catalog, installed)

    overrides_raw = json.loads(OVERRIDES_PATH.read_text()) if OVERRIDES_PATH.exists() else {}
    categories = overrides_raw.get("categories", [])
    overrides = overrides_raw.get("skills", {})

    updates = json.loads(UPDATES_PATH.read_text()) if UPDATES_PATH.exists() else {}
    usage = json.loads(USAGE_PATH.read_text()) if USAGE_PATH.exists() else {}
    links = (json.loads(LINKS_PATH.read_text()).get("urls", {}) if LINKS_PATH.exists() else {})

    skills = {}

    # 1) дисковые скиллы
    for name, info in disk.items():
        platform = platform_from_locations(info["locations"])
        d = info["desc"] or ""
        if "(gstack)" in d or name.startswith("gstack"):
            source, url, deeplink = "gstack", "https://github.com/garrytan/gstack", f"https://github.com/garrytan/gstack/tree/main/{name}"
        else:
            source, url, deeplink = "локальное", "", ""
        skills[name] = {
            "name": name, "platform": platform, "source": source,
            "sourceUrl": url, "deeplink": deeplink, "raw": d,
            "installed": "", "installedSha": "", "latestSha": "",
        }

    # 2) плагинные скиллы (платформа claude), точный источник
    for name, p in plugins.items():
        if name in skills:
            if not skills[name]["sourceUrl"]:
                skills[name].update(source=p["plugin"], sourceUrl=p["url"], deeplink=p["deeplink"])
            continue
        skills[name] = {
            "name": name, "platform": "claude", "source": p["plugin"],
            "sourceUrl": p["url"], "deeplink": p["deeplink"], "raw": p["desc"],
            "installed": p["installed"], "installedSha": p["installedSha"], "latestSha": p["latestSha"],
        }

    # 2b) встроенные скиллы (вшиты в Claude Code / anthropic-skills, на диске не лежат)
    #     объявляются в overrides с "builtin": 1
    for name, ov in overrides.items():
        if name in skills or not ov.get("builtin"):
            continue
        src = ov.get("source", "встроено в Claude Code")
        url = ov.get("sourceUrl", "")
        deep = url
        if src == "anthropic-skills" and url:
            deep = f"{url}/tree/main/skills/{name}"  # docx/pptx/... лежат в skills/<name>
        skills[name] = {
            "name": name, "platform": ov.get("platform", "claude"),
            "source": src, "sourceUrl": url, "deeplink": deep,
            "raw": ov.get("desc", ""), "installed": "", "installedSha": "", "latestSha": "",
        }

    # 3) склейка
    result = []
    unsorted_new = []
    for name, s in skills.items():
        ov = overrides.get(name, {})
        upd = updates.get(name, {})
        entry = {
            "name": name,
            "platform": ov.get("platform", s["platform"]),
            "source": ov.get("source", s["source"]),
            "sourceUrl": ov.get("sourceUrl", s["sourceUrl"]),
            "deeplink": ov.get("deeplink", s.get("deeplink") or s["sourceUrl"]),
            "linkOk": links.get(ov.get("sourceUrl", s["sourceUrl"]), {}).get("ok"),
            "cmd": ov.get("cmd", 0),
            "core": ov.get("core", 0),
            "cat": ov.get("cat"),
            "desc": ov.get("desc") or (s["raw"][:220] if s["raw"] else "— без описания —"),
            "when": ov.get("when", ""),
            "how": ov.get("how") or (
                f"Набери /{name} — или просто опиши задачу словами."
                if ov.get("cmd", 0) else
                "Просто опиши задачу словами — Claude вызовет скилл сам."
            ),
            "installed": s.get("installed", "") or upd.get("installed", ""),
            "latest": upd.get("latest", ""),
            "updatable": upd.get("updatable", False),
            "updateVia": upd.get("via", ""),
            "uses": usage.get(name, 0),
            "curated": bool(ov),
        }
        if not entry["cat"]:
            inferred = SOURCE_CAT.get(entry["source"])
            entry["cat"] = inferred or "new"
            if not inferred:
                unsorted_new.append(name)
        result.append(entry)

    result.sort(key=lambda x: (x["cat"] == "new", x["name"]))

    counts = {
        "total": len(result),
        "claude": sum(1 for r in result if r["platform"] == "claude"),
        "codex": sum(1 for r in result if r["platform"] == "codex"),
        "both": sum(1 for r in result if r["platform"] == "both"),
        "core": sum(1 for r in result if r["core"]),
        "updatable": sum(1 for r in result if r["updatable"]),
        "new": len(unsorted_new),
    }
    meta = {
        "counts": counts, "new": sorted(unsorted_new), "categories": categories,
        "hasUpdates": bool(updates), "hasUsage": bool(usage),
    }

    DATA.mkdir(exist_ok=True)
    payload = (
        "// АВТО-СГЕНЕРИРОВАНО generate.py — руками не править.\n"
        "// Русские описания/категории — data/overrides.json; обновления — updates.json; счётчики — usage.json\n"
        f"window.SKILLS = {json.dumps(result, ensure_ascii=False, indent=1)};\n"
        f"window.SKILLS_META = {json.dumps(meta, ensure_ascii=False, indent=1)};\n"
    )
    OUT_PATH.write_text(payload)

    print(f"[ok] скиллов: {counts['total']}  (claude {counts['claude']} · codex {counts['codex']} · оба {counts['both']})")
    extra = []
    if updates:
        extra.append(f"обновляемых: {counts['updatable']}")
    if usage:
        extra.append("счётчики: подмешаны")
    if extra:
        print("[i] " + " · ".join(extra))
    if unsorted_new:
        print(f"[i] не разобрано ({len(unsorted_new)}): {', '.join(sorted(unsorted_new)[:12])}")
    print(f"[ok] записано -> {OUT_PATH}")


if __name__ == "__main__":
    build()

"""
緊急救護課程爬蟲
自動抓取各單位課程公告，輸出 data/courses.json 與 docs/feed.xml (RSS)
"""

import json
import re
import time
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ── 輸出路徑 ─────────────────────────────────────────────
OUTPUT_JSON = Path("data/courses.json")
OUTPUT_RSS  = Path("docs/feed.xml")
OUTPUT_JSON.parent.mkdir(exist_ok=True)
OUTPUT_RSS.parent.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; EMSCourseBot/1.0; +https://emsipbyluke.netlify.app)"
}

# ── 各單位來源設定 ────────────────────────────────────────
SOURCES = [
    # 台灣急診醫學會
    {
        "name": "台灣急診醫學會",
        "cat": "台灣學會",
        "url": "https://www.sem.org.tw/semcourse/index.aspx",
        "type": "table",
        "row_sel": "table tr",
        "title_col": 1,
        "date_col": 2,
        "link_col": 1,
    },
    # 台灣急救加護醫學會
    {
        "name": "台灣急救加護醫學會",
        "cat": "台灣學會",
        "url": "https://www.seccm.org.tw/news.php",
        "type": "list",
        "item_sel": ".news-list li, .list-item, article",
        "title_sel": "a",
        "date_sel": ".date, time, span",
    },
    # 台灣外傷醫學會
    {
        "name": "台灣外傷醫學會",
        "cat": "台灣學會",
        "url": "http://www.trauma.org.tw/activity.php",
        "type": "list",
        "item_sel": ".activity-list li, .list li, tr",
        "title_sel": "a",
        "date_sel": ".date, td",
    },
    # 台灣災難醫學會
    {
        "name": "台灣災難醫學會",
        "cat": "台灣學會",
        "url": "http://www.disaster.org.tw/news.php",
        "type": "list",
        "item_sel": "li, .news-item",
        "title_sel": "a",
        "date_sel": ".date, span",
    },
    # 台灣醫療救護學會
    {
        "name": "台灣醫療救護學會",
        "cat": "台灣學會",
        "url": "https://twparamedicine.org/index.html",
        "type": "list",
        "item_sel": ".news li, .article li, .post",
        "title_sel": "a",
        "date_sel": ".date, time",
    },
    # 台灣緊急救護醫療指導醫師學會
    {
        "name": "台灣緊急救護醫療指導醫師學會",
        "cat": "台灣學會",
        "url": "https://www.taemsp.com/news",
        "type": "list",
        "item_sel": ".news-item, li, .post",
        "title_sel": "a, h3, h4",
        "date_sel": ".date, time, span",
    },
    # 中華緊急救護技術員協會
    {
        "name": "中華緊急救護技術員協會",
        "cat": "台灣協會",
        "url": "https://www.emt.org.tw/temtaf/",
        "type": "list",
        "item_sel": ".news li, .article, tr",
        "title_sel": "a",
        "date_sel": ".date, td",
    },
    # 台灣野外地區緊急救護協會
    {
        "name": "台灣野外地區緊急救護協會",
        "cat": "台灣協會",
        "url": "https://taiwanwma.org/",
        "type": "list",
        "item_sel": ".post, article, .news-item",
        "title_sel": "h2 a, h3 a, .title a",
        "date_sel": ".date, time, .post-date",
    },
    # 台灣急重症模擬醫學會
    {
        "name": "台灣急重症模擬醫學會",
        "cat": "台灣學會",
        "url": "https://simulation.org.tw/",
        "type": "list",
        "item_sel": ".news-list li, .post, article",
        "title_sel": "a, h3",
        "date_sel": ".date, time",
    },
    # 復甦照護小學堂
    {
        "name": "復甦照護小學堂",
        "cat": "台灣急救社群",
        "url": "https://www.tsorcc.org.tw/",
        "type": "list",
        "item_sel": ".news li, article, .post",
        "title_sel": "a, h3",
        "date_sel": ".date, time",
    },
    # NAEMT (TCCC/TECC課程)
    {
        "name": "NAEMT",
        "cat": "戰術救護",
        "url": "https://www.naemt.org/education/trauma-education",
        "type": "list",
        "item_sel": ".course-item, .card, article",
        "title_sel": "h3 a, h4 a, .title a",
        "date_sel": ".date, time, .event-date",
    },
    # ERC
    {
        "name": "ERC — European Resuscitation Council",
        "cat": "國際期刊/組織",
        "url": "https://www.erc.edu/news",
        "type": "list",
        "item_sel": ".news-item, article, .post",
        "title_sel": "h3 a, h2 a, .title a",
        "date_sel": ".date, time",
    },
]

# ── 工具函式 ──────────────────────────────────────────────
def make_id(title: str, source: str) -> str:
    """產生穩定的唯一 ID"""
    raw = f"{source}::{title}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]

def clean_text(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip()

def parse_date(text: str) -> str | None:
    """嘗試從字串解析日期，回傳 YYYY-MM-DD 或 None"""
    if not text:
        return None
    text = clean_text(text)
    patterns = [
        r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})",
        r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日",
        r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            g = m.groups()
            if len(g[0]) == 4:
                y, mo, d = int(g[0]), int(g[1]), int(g[2])
            else:
                mo, d, y = int(g[0]), int(g[1]), int(g[2])
            try:
                return f"{y:04d}-{mo:02d}-{d:02d}"
            except Exception:
                pass
    return None

def fetch(url: str) -> BeautifulSoup | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        r.encoding = r.apparent_encoding
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"  ⚠️  fetch 失敗 {url}: {e}")
        return None

def resolve_url(href: str, base: str) -> str:
    if not href:
        return base
    if href.startswith("http"):
        return href
    from urllib.parse import urljoin
    return urljoin(base, href)

def scrape_source(src: dict) -> list[dict]:
    print(f"  抓取: {src['name']} ...")
    soup = fetch(src["url"])
    if not soup:
        return []

    items = []

    if src["type"] == "table":
        rows = soup.select(src["row_sel"])
        for row in rows[1:]:  # skip header
            cols = row.find_all(["td", "th"])
            if len(cols) <= max(src["title_col"], src["date_col"]):
                continue
            title_cell = cols[src["title_col"]]
            title = clean_text(title_cell.get_text())
            if not title or len(title) < 3:
                continue
            link_tag = title_cell.find("a")
            link = resolve_url(link_tag["href"] if link_tag and link_tag.get("href") else "", src["url"])
            date_text = clean_text(cols[src["date_col"]].get_text()) if src["date_col"] < len(cols) else ""
            date = parse_date(date_text)
            items.append({
                "id":     make_id(title, src["name"]),
                "title":  title,
                "source": src["name"],
                "cat":    src["cat"],
                "date":   date,
                "url":    link,
            })

    else:  # list
        rows = soup.select(src["item_sel"])
        for row in rows[:30]:  # 每個來源最多30筆
            tag = row.select_one(src["title_sel"])
            if not tag:
                continue
            title = clean_text(tag.get_text())
            if not title or len(title) < 3:
                continue
            href = tag.get("href") if tag.name == "a" else (tag.find("a") or {}).get("href", "")
            link = resolve_url(href or "", src["url"])
            date_tag = row.select_one(src.get("date_sel", ""))
            date = parse_date(date_tag.get_text() if date_tag else "")
            items.append({
                "id":     make_id(title, src["name"]),
                "title":  title,
                "source": src["name"],
                "cat":    src["cat"],
                "date":   date,
                "url":    link,
            })

    print(f"    → {len(items)} 筆")
    return items

# ── RSS 產生 ──────────────────────────────────────────────
def build_rss(items: list[dict]) -> str:
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    items_xml = ""
    for it in items[:50]:
        title = it["title"].replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        link  = it.get("url","")
        date  = it.get("date") or ""
        src   = it.get("source","")
        items_xml += f"""
  <item>
    <title>{title}</title>
    <link>{link}</link>
    <guid>{link or it['id']}</guid>
    <pubDate>{date}</pubDate>
    <category>{src}</category>
    <description>{title}（來源：{src}）</description>
  </item>"""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>緊急救護資訊入口網 — 最新課程與公告</title>
  <link>https://emsipbyluke.netlify.app</link>
  <description>自動彙整台灣及國際急救相關單位最新課程與公告</description>
  <language>zh-TW</language>
  <lastBuildDate>{now}</lastBuildDate>
  <ttl>180</ttl>{items_xml}
</channel>
</rss>"""

# ── 主程式 ────────────────────────────────────────────────
def main():
    print(f"\n{'='*50}")
    print(f"  緊急救護課程爬蟲  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    all_items = []
    for src in SOURCES:
        try:
            items = scrape_source(src)
            all_items.extend(items)
            time.sleep(1.5)  # 避免過於頻繁請求
        except Exception as e:
            print(f"  ❌ {src['name']} 錯誤: {e}")

    # 去重（同 id 只保留一筆）
    seen = set()
    unique = []
    for it in all_items:
        if it["id"] not in seen:
            seen.add(it["id"])
            unique.append(it)

    # 依日期排序（無日期的排最後）
    unique.sort(key=lambda x: x.get("date") or "0000", reverse=True)

    # 加上更新時間戳
    output = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "count": len(unique),
        "items": unique,
    }

    OUTPUT_JSON.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"\n✅ JSON 輸出: {OUTPUT_JSON} ({len(unique)} 筆)")

    # RSS
    OUTPUT_RSS.write_text(build_rss(unique), encoding="utf-8")
    print(f"✅ RSS 輸出: {OUTPUT_RSS}")

if __name__ == "__main__":
    main()

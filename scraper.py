"""
緊急救護課程爬蟲 v2
策略：對每個網站找到實際可解析的 URL 與 HTML 結構
"""

import json, re, time, hashlib
from datetime import datetime, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup

OUTPUT_JSON = Path("data/courses.json")
OUTPUT_RSS  = Path("docs/feed.xml")
OUTPUT_JSON.parent.mkdir(exist_ok=True)
OUTPUT_RSS.parent.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
}

def make_id(title, source):
    return hashlib.md5(f"{source}::{title}".encode()).hexdigest()[:12]

def clean(t):
    return re.sub(r"\s+", " ", t or "").strip()

def extract_all_dates(text):
    """從文字中抽取所有有效日期，回傳 sorted list"""
    if not text: return []
    dates = []
    for pat in [
        r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})",
        r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日",
    ]:
        for m in re.finditer(pat, text):
            try:
                y,mo,d = int(m.group(1)),int(m.group(2)),int(m.group(3))
                if 2020 <= y <= 2035 and 1 <= mo <= 12 and 1 <= d <= 31:
                    dates.append(f"{y:04d}-{mo:02d}-{d:02d}")
            except:
                pass
    return sorted(set(dates))

def parse_dates_from_title(title):
    """
    從標題解析活動日與報名截止日
    回傳 dict: {event_date, deadline}
    規則：
      - 含「報名截止」「截止」「deadline」關鍵字前的日期 → deadline
      - 其餘日期中最晚的 → event_date
    """
    title = title or ""
    result = {"event_date": None, "deadline": None}

    # 找「截止」關鍵字位置
    deadline_kw = re.search(r"報名截止|截止|deadline|Deadline", title)

    if deadline_kw:
        # 截止關鍵字前後各找日期
        before = title[:deadline_kw.start()]
        after  = title[deadline_kw.end():]
        before_dates = extract_all_dates(before)
        after_dates  = extract_all_dates(after)

        # 截止日：關鍵字前最後一個日期，或關鍵字後第一個日期
        if before_dates:
            result["deadline"] = before_dates[-1]
        elif after_dates:
            result["deadline"] = after_dates[0]

        # 活動日：剩餘日期中最晚的（排除截止日）
        all_dates = extract_all_dates(title)
        remaining = [d for d in all_dates if d != result["deadline"]]
        if remaining:
            result["event_date"] = sorted(remaining)[-1]
        elif all_dates:
            # 只有一個日期且是截止日，就當活動日
            result["event_date"] = all_dates[-1]
    else:
        # 沒有截止關鍵字，最晚日期當活動日
        all_dates = extract_all_dates(title)
        if all_dates:
            result["event_date"] = all_dates[-1]

    return result

def parse_date(text):
    """相容舊介面：只回傳活動日"""
    r = parse_dates_from_title(text)
    return r["event_date"]

def fetch(url, timeout=15):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"    ⚠️ fetch 失敗: {e}")
        return None

def resolve(href, base):
    if not href: return base
    if href.startswith("http"): return href
    from urllib.parse import urljoin
    return urljoin(base, href)

def item(title, source, cat, url, date=None, deadline=None):
    """建立單筆課程資料，自動從 title 解析活動日與報名截止日"""
    title_clean = clean(title)
    dates = parse_dates_from_title(title_clean)
    event_date  = date     or dates["event_date"]
    reg_deadline = deadline or dates["deadline"]
    return {
        "id":       make_id(title_clean, source),
        "title":    title_clean,
        "source":   source,
        "cat":      cat,
        "date":     event_date,    # 活動日（行事曆依此排序）
        "deadline": reg_deadline,  # 報名截止日
        "url":      url,
    }

# ══════════════════════════════════════════════════════════
# 各單位爬蟲
# ══════════════════════════════════════════════════════════

def scrape_sem():
    """台灣急診醫學會 — 學會主辦積分活動"""
    out = []
    BASE = "https://www.sem.org.tw"
    for path in ["/Activity/A/Index", "/News/11/Index", "/News/10/Index"]:
        soup = fetch(BASE + path)
        if not soup: continue
        for a in soup.select("a[href*='/Activity/A/Details/'], a[href*='/News/Details/']"):
            title = clean(a.get_text())
            if len(title) < 4: continue
            href = resolve(a.get("href",""), BASE)
            # 嘗試找同行的日期
            parent = a.find_parent(["tr","li","div"])
            date = None
            if parent:
                date = parse_date(parent.get_text())
            out.append(item(title, "台灣急診醫學會", "台灣學會", href, date))
    return out

def scrape_seccm():
    """台灣急救加護醫學會"""
    out = []
    soup = fetch("https://www.seccm.org.tw/")
    if not soup: return out
    for a in soup.select("a[href]"):
        title = clean(a.get_text())
        href = a.get("href","")
        if len(title) < 5: continue
        if any(k in title for k in ["課程","活動","公告","研討","工作坊","講習","訓練"]):
            out.append(item(title, "台灣急救加護醫學會", "台灣學會",
                           resolve(href, "https://www.seccm.org.tw")))
    return out[:20]

def scrape_trauma():
    """台灣外傷醫學會"""
    out = []
    for url in ["http://www.trauma.org.tw/activity.php",
                "http://www.trauma.org.tw/news.php"]:
        soup = fetch(url)
        if not soup: continue
        for a in soup.select("a[href]"):
            title = clean(a.get_text())
            if len(title) < 5: continue
            if any(k in title for k in ["課程","活動","公告","研討","訓練","工作坊"]):
                parent = a.find_parent(["tr","li","td"])
                date = parse_date(parent.get_text()) if parent else None
                out.append(item(title, "台灣外傷醫學會", "台灣學會",
                               resolve(a.get("href",""), "http://www.trauma.org.tw"), date))
    return out[:20]

def scrape_disaster():
    """台灣災難醫學會"""
    out = []
    soup = fetch("http://www.disaster.org.tw/news.php")
    if not soup: return out
    for a in soup.select("a[href]"):
        title = clean(a.get_text())
        if len(title) < 5: continue
        parent = a.find_parent(["tr","li","div"])
        date = parse_date(parent.get_text()) if parent else None
        out.append(item(title, "台灣災難醫學會", "台灣學會",
                       resolve(a.get("href",""), "http://www.disaster.org.tw"), date))
    return out[:20]

def scrape_twparamedicine():
    """台灣醫療救護學會"""
    out = []
    soup = fetch("https://twparamedicine.org/index.html")
    if not soup: return out
    for a in soup.select("a[href]"):
        title = clean(a.get_text())
        if len(title) < 5: continue
        if any(k in title for k in ["課程","活動","公告","研討","訓練","工作坊","消息"]):
            out.append(item(title, "台灣醫療救護學會", "台灣學會",
                           resolve(a.get("href",""), "https://twparamedicine.org")))
    return out[:20]

def scrape_taemsp():
    """台灣緊急救護醫療指導醫師學會"""
    out = []
    soup = fetch("https://www.taemsp.com/")
    if not soup: return out
    for a in soup.select("a[href]"):
        title = clean(a.get_text())
        if len(title) < 5: continue
        if any(k in title for k in ["課程","活動","公告","研討","訓練","消息","工作坊"]):
            out.append(item(title, "台灣緊急救護醫療指導醫師學會", "台灣學會",
                           resolve(a.get("href",""), "https://www.taemsp.com")))
    return out[:20]

def scrape_simulation():
    """台灣急重症模擬醫學會"""
    out = []
    soup = fetch("https://simulation.org.tw/")
    if not soup: return out
    for a in soup.select("a[href]"):
        title = clean(a.get_text())
        if len(title) < 5: continue
        if any(k in title for k in ["課程","活動","公告","研討","訓練","消息","工作坊"]):
            out.append(item(title, "台灣急重症模擬醫學會", "台灣學會",
                           resolve(a.get("href",""), "https://simulation.org.tw")))
    return out[:20]

def scrape_emt():
    """中華緊急救護技術員協會"""
    out = []
    soup = fetch("https://www.emt.org.tw/temtaf/")
    if not soup: return out
    for a in soup.select("a[href]"):
        title = clean(a.get_text())
        if len(title) < 5: continue
        if any(k in title for k in ["課程","活動","公告","研討","訓練","消息","工作坊","急救"]):
            parent = a.find_parent(["tr","li","div"])
            date = parse_date(parent.get_text()) if parent else None
            out.append(item(title, "中華緊急救護技術員協會", "台灣協會",
                           resolve(a.get("href",""), "https://www.emt.org.tw"), date))
    return out[:20]

def scrape_taiwanwma():
    """台灣野外地區緊急救護協會"""
    out = []
    soup = fetch("https://taiwanwma.org/")
    if not soup: return out
    for a in soup.select("a[href]"):
        title = clean(a.get_text())
        if len(title) < 5: continue
        if any(k in title for k in ["課程","活動","公告","研討","訓練","消息","野外"]):
            out.append(item(title, "台灣野外地區緊急救護協會", "台灣協會",
                           resolve(a.get("href",""), "https://taiwanwma.org")))
    return out[:20]

def scrape_tsorcc():
    """復甦照護小學堂"""
    out = []
    soup = fetch("https://www.tsorcc.org.tw/")
    if not soup: return out
    for a in soup.select("a[href]"):
        title = clean(a.get_text())
        if len(title) < 5: continue
        if any(k in title for k in ["課程","活動","公告","研討","訓練","消息","CPR","復甦"]):
            out.append(item(title, "復甦照護小學堂", "台灣急救社群",
                           resolve(a.get("href",""), "https://www.tsorcc.org.tw")))
    return out[:20]

def scrape_naemt():
    """NAEMT — TCCC/TECC 課程"""
    out = []
    soup = fetch("https://www.naemt.org/education/trauma-education")
    if not soup: return out
    for a in soup.select("a[href]"):
        title = clean(a.get_text())
        if len(title) < 5: continue
        if any(k in title.upper() for k in ["TCCC","TECC","PHTLS","AMLS","EPC","COURSE","TRAINING"]):
            out.append(item(title, "NAEMT", "戰術救護",
                           resolve(a.get("href",""), "https://www.naemt.org")))
    return out[:15]

def scrape_erc():
    """ERC — European Resuscitation Council"""
    out = []
    soup = fetch("https://www.erc.edu/news")
    if not soup: return out
    for a in soup.select("a[href*='/news'], a[href*='/event'], a[href*='/course']"):
        title = clean(a.get_text())
        if len(title) < 5: continue
        parent = a.find_parent(["article","li","div"])
        date = parse_date(parent.get_text()) if parent else None
        out.append(item(title, "ERC", "國際期刊/組織",
                       resolve(a.get("href",""), "https://www.erc.edu"), date))
    return out[:15]

def scrape_wms():
    """Wilderness Medical Society"""
    out = []
    soup = fetch("https://wms.org/events")
    if not soup: return out
    for a in soup.select("a[href]"):
        title = clean(a.get_text())
        if len(title) < 5: continue
        if any(k in title.lower() for k in ["course","conference","event","workshop","training"]):
            parent = a.find_parent(["article","li","div"])
            date = parse_date(parent.get_text()) if parent else None
            out.append(item(title, "Wilderness Medical Society", "國際期刊/組織",
                           resolve(a.get("href",""), "https://wms.org"), date))
    return out[:10]

# ══════════════════════════════════════════════════════════
# RSS 產生
# ══════════════════════════════════════════════════════════
def build_rss(items):
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    xml = ""
    for it in items[:60]:
        t = it["title"].replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        xml += f"""
  <item>
    <title>{t}</title>
    <link>{it.get('url','')}</link>
    <guid>{it.get('url','') or it['id']}</guid>
    <pubDate>{it.get('date','')}</pubDate>
    <category>{it.get('source','')}</category>
    <description>{t}（來源：{it.get('source','')}）</description>
  </item>"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>緊急救護資訊入口網 — 最新課程與公告</title>
  <link>https://emsipbyluke.netlify.app</link>
  <description>自動彙整台灣及國際急救相關單位最新課程與公告</description>
  <language>zh-TW</language>
  <lastBuildDate>{now}</lastBuildDate>
  <ttl>180</ttl>{xml}
</channel>
</rss>"""

# ══════════════════════════════════════════════════════════
# 主程式
# ══════════════════════════════════════════════════════════
SCRAPERS = [
    ("台灣急診醫學會",       scrape_sem),
    ("台灣急救加護醫學會",   scrape_seccm),
    ("台灣外傷醫學會",       scrape_trauma),
    ("台灣災難醫學會",       scrape_disaster),
    ("台灣醫療救護學會",     scrape_twparamedicine),
    ("台灣緊急救護醫療指導醫師學會", scrape_taemsp),
    ("台灣急重症模擬醫學會", scrape_simulation),
    ("中華緊急救護技術員協會", scrape_emt),
    ("台灣野外地區緊急救護協會", scrape_taiwanwma),
    ("復甦照護小學堂",       scrape_tsorcc),
    ("NAEMT",                scrape_naemt),
    ("ERC",                  scrape_erc),
    ("Wilderness Medical Society", scrape_wms),
]

def main():
    print(f"\n{'='*50}")
    print(f"緊急救護課程爬蟲 v2  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    all_items = []
    for name, fn in SCRAPERS:
        print(f"\n→ {name}")
        try:
            results = fn()
            print(f"  {len(results)} 筆")
            all_items.extend(results)
        except Exception as e:
            print(f"  ❌ 錯誤: {e}")
        time.sleep(1.5)

    # 去重
    seen, unique = set(), []
    for it in all_items:
        if it["id"] not in seen and len(it["title"]) > 3:
            seen.add(it["id"])
            unique.append(it)

    # 排序（有日期的先，無日期的後）
    unique.sort(key=lambda x: x.get("date") or "0000", reverse=True)

    output = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "count": len(unique),
        "items": unique
    }

    OUTPUT_JSON.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n✅ JSON: {OUTPUT_JSON} ({len(unique)} 筆)")

    OUTPUT_RSS.write_text(build_rss(unique), encoding="utf-8")
    print(f"✅ RSS:  {OUTPUT_RSS}")

if __name__ == "__main__":
    main()

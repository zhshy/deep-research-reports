#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫描 reports/，重建两处索引：

  1. README.md 的索引表（标记之间）
  2. index.html 的落地页（供 GitHub Pages 访问）

每篇报告的元数据来源（按优先级）：
  1. 正文里的 `<!-- summary: ... -->` 注释
  2. 回退：`**三句话**：` 一行的前 60 字
标题取正文第一行 `# `。
若同日存在 summary.html，则为该日的「摘要」条目补上「网页版」链接。
"""
import html
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS = os.path.join(ROOT, "reports")
README = os.path.join(ROOT, "README.md")
INDEX_HTML = os.path.join(ROOT, "index.html")
START, END = "<!-- INDEX:START -->", "<!-- INDEX:END -->"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    title = "（无标题）"
    for line in text.split("\n"):
        if line.startswith("# "):
            title = line[2:].strip()
            break
    m = re.search(r"<!--\s*summary:\s*(.+?)\s*-->", text)
    if m:
        summary = m.group(1)
    else:
        m2 = re.search(r"\*\*三句话\*\*：(.+)", text)
        summary = (m2.group(1)[:60] + "…") if m2 else "—"
    return title.replace("|", "／"), summary.replace("|", "／").replace("\n", " ")


def slot_of(fn):
    """时段标记：同一天可有多份（午间 / 收盘），用文件名里的关键字区分。"""
    if "午间" in fn:
        return "午间"
    if "收盘" in fn:
        return "收盘"
    return ""


def collect():
    """返回 [{date,slot,title,summary,rel,is_summary,page}]。

    网页版配对规则：同一天、同一时段内，把 .html 挂到该时段的 md 上；
    优先挂给文件名含「摘要」的那条，否则挂给该时段的第一条。
    """
    entries = []
    if not os.path.isdir(REPORTS):
        return entries
    for day in sorted(os.listdir(REPORTS), reverse=True):
        d = os.path.join(REPORTS, day)
        if not os.path.isdir(d) or not DATE_RE.match(day):
            continue
        # 同日内：收盘版在前、无标记次之、午间最后；同一时段内摘要优先
        rank = {"收盘": 0, "": 1, "午间": 2}
        files = sorted(os.listdir(d),
                       key=lambda x: (rank.get(slot_of(x), 1), 0 if "摘要" in x else 1, x))
        htmls = {}
        for fn in files:
            if fn.endswith(".html"):
                htmls.setdefault(slot_of(fn), []).append(fn)
        seen_slot = {}
        for fn in files:
            if not fn.endswith(".md"):
                continue
            slot = slot_of(fn)
            title, summary = parse(os.path.join(d, fn))
            is_summary = "摘要" in fn
            page = None
            cands = htmls.get(slot, [])
            if cands and (is_summary or slot not in seen_slot):
                page = f"reports/{day}/{cands[0]}"
            seen_slot.setdefault(slot, fn)
            entries.append({
                "date": day, "slot": slot, "title": title, "summary": summary,
                "rel": f"reports/{day}/{fn}", "is_summary": is_summary, "page": page,
            })
    return entries


def build_readme(entries):
    body = ["| 日期 | 标题 | 核心结论 | 文件 |", "|---|---|---|---|"]
    for e in entries:
        links = [f"[阅读]({e['rel']})"]
        if e["page"]:
            links.insert(0, f"[**网页版**]({e['page']})")
        label = e["date"] + (f" {e['slot']}" if e["slot"] else "")
        body.append(f"| {label} | {e['title']} | {e['summary']} | {' · '.join(links)} |")
    if not entries:
        body.append("| — | 暂无报告 | — | — |")
    block = "\n".join(body)

    if not os.path.exists(README):
        sys.exit("找不到 README.md")
    with open(README, encoding="utf-8") as f:
        text = f.read()

    if entries:
        e = entries[0]
        latest = f"**最新一期**：[{e['date']} · {e['title'].split('：')[-1]}]({e['page'] or e['rel']})"
        text = re.sub(r"^\*\*最新一期\*\*：.*$", latest, text, count=1, flags=re.M)

    if START in text and END in text:
        head, tail = text.split(START)[0], text.split(END)[1]
        text = f"{head}{START}\n{block}\n{END}{tail}"
    else:
        text = f"{text}\n\n{START}\n{block}\n{END}\n"

    with open(README, "w", encoding="utf-8") as f:
        f.write(text)


HTML_HEAD = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>深度研报 · 每日 A股与创业板研究归档</title>
<style>
  * { box-sizing: border-box; }
  body { margin: 0; background: #f5f6f8; color: #1f2937;
         font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; line-height: 1.7; }
  .wrap { max-width: 960px; margin: 0 auto; padding: 0 24px; }
  header { background: #0f172a; color: #f8fafc; padding: 44px 0 34px; }
  header h1 { font-size: 26px; font-weight: 600; margin: 0 0 10px; letter-spacing: .5px; }
  header .sub { color: #94a3b8; font-size: 13px; }
  header .sub b { color: #e2e8f0; font-weight: 500; }
  .list { padding: 28px 0 60px; }
  .item { display: block; background: #fff; border: 1px solid #e5e7eb; border-radius: 12px;
          padding: 20px 24px; margin-bottom: 14px; text-decoration: none; color: inherit;
          transition: border-color .15s, box-shadow .15s; }
  .item:hover { border-color: #cbd5e1; box-shadow: 0 2px 10px rgba(15,23,42,.06); }
  .item .row { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
  .item .date { font-size: 12px; color: #64748b; font-variant-numeric: tabular-nums; }
  .item .badge { font-size: 11px; padding: 1px 8px; border-radius: 20px; background: #eef2ff; color: #3730a3; }
  .item h2 { font-size: 16px; font-weight: 600; margin: 6px 0 6px; }
  .item h2 a { color: #0f172a; text-decoration: none; }
  .item h2 a:hover { color: #1e3a8a; text-decoration: underline; }
  .item p { font-size: 13px; color: #475569; margin: 0; }
  .item .links { margin-top: 12px; font-size: 12px; color: #64748b; }
  .item .links a { color: #3730a3; text-decoration: none; margin-right: 14px; }
  .item .links a:hover { text-decoration: underline; }
  footer { border-top: 1px solid #e5e7eb; background: #fff; padding: 22px 0; }
  footer .wrap { font-size: 12px; color: #64748b; }
  footer a { color: #3730a3; text-decoration: none; }
  @media (max-width: 640px) { header h1 { font-size: 21px; } }
</style>
</head>
<body>

<header>
  <div class="wrap">
    <h1>深度研报</h1>
    <div class="sub">
      每日 A股与创业板深度研究归档　·　每篇都按同一套方法论写：<b>每个数字带口径、每个判断带证伪条件、最后落成可执行的仓位规则</b>
    </div>
  </div>
</header>

<div class="wrap list">
"""

HTML_TAIL = """</div>

<footer>
  <div class="wrap">
    本仓库是研究方法与写作工具的产物，<b>不构成任何投资建议</b>。　
    <a href="https://github.com/zhshy/deep-research-reports">GitHub 仓库</a>　·　
    <a href="https://github.com/zhshy/deep-dive-investment-report">方法论 Skill</a>　·　
    <a href="https://github.com/zhshy/deep-research-reports/blob/main/README.md">README</a>
  </div>
</footer>

</body>
</html>
"""


def build_index_html(entries):
    cards = []
    for e in entries:
        href = e["page"] or (
            "https://github.com/zhshy/deep-research-reports/blob/main/" + e["rel"])
        badge = '<span class="badge">摘要</span>' if e["is_summary"] else ""
        links = []
        if e["page"]:
            links.append(f'<a href="{e["page"]}">网页版</a>')
        links.append(
            '<a href="https://github.com/zhshy/deep-research-reports/blob/main/'
            + e["rel"] + '">Markdown</a>')
        dlabel = e["date"] + (f" · {e['slot']}" if e["slot"] else "")
        cards.append(
            f'  <div class="item">\n'
            f'    <div class="row"><span class="date">{dlabel}</span>{badge}</div>\n'
            f'    <h2><a href="{href}">{html.escape(e["title"])}</a></h2>\n'
            f'    <p>{html.escape(e["summary"])}</p>\n'
            f'    <div class="links">{"".join(links)}</div>\n'
            f'  </div>'
        )
    if not cards:
        cards.append('  <div class="item"><h2>暂无报告</h2></div>')
    with open(INDEX_HTML, "w", encoding="utf-8") as f:
        f.write(HTML_HEAD + "\n".join(cards) + "\n" + HTML_TAIL)


def main():
    entries = collect()
    build_readme(entries)
    build_index_html(entries)
    pages = sum(1 for e in entries if e["page"])
    print(f"索引已更新：{len(entries)} 篇（其中 {pages} 篇有网页版）")


if __name__ == "__main__":
    main()

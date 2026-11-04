#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫描 reports/ 重建 README.md 中的索引表。

索引区由两个标记界定，标记之外的内容不会被改动：
    <!-- INDEX:START -->
    ...
    <!-- INDEX:END -->

每篇报告的元数据来源（按优先级）：
  1. 正文里的 `<!-- summary: ... -->` 注释
  2. 回退：`**三句话**：` 一行的前 60 字
标题取正文第一行 `# `。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS = os.path.join(ROOT, "reports")
README = os.path.join(ROOT, "README.md")
START, END = "<!-- INDEX:START -->", "<!-- INDEX:END -->"


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
    summary = summary.replace("|", "／").replace("\n", " ")
    title = title.replace("|", "／")
    return title, summary


def collect():
    rows = []
    if not os.path.isdir(REPORTS):
        return rows
    for day in sorted(os.listdir(REPORTS), reverse=True):
        d = os.path.join(REPORTS, day)
        if not os.path.isdir(d) or not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
            continue
        # 同一天里，摘要页排在全文之前（摘要是入口，全文是细节）
        files = sorted(os.listdir(d), key=lambda x: (0 if "摘要" in x else 1, x))
        for fn in files:
            if not fn.endswith(".md"):
                continue
            title, summary = parse(os.path.join(d, fn))
            rel = f"reports/{day}/{fn}".replace(os.sep, "/")
            # 链接里的中文需要百分号编码，GitHub 也接受原始字符，这里保留原始以便阅读
            rows.append((day, title, summary, rel))
    return rows


def main():
    rows = collect()
    body = ["| 日期 | 标题 | 核心结论 | 文件 |", "|---|---|---|---|"]
    for day, title, summary, rel in rows:
        body.append(f"| {day} | {title} | {summary} | [阅读]({rel}) |")
    if not rows:
        body.append("| — | 暂无报告 | — | — |")
    block = "\n".join(body)

    if not os.path.exists(README):
        sys.exit("找不到 README.md")
    with open(README, encoding="utf-8") as f:
        text = f.read()

    # 同步顶部的"最新一期"，避免索引更新后仍显示旧报告
    if rows:
        day, title, _summary, rel = rows[0]
        latest = f"**最新一期**：[{day} · {title.split('：')[-1]}]({rel})"
        text = re.sub(r"^\*\*最新一期\*\*：.*$", latest, text, count=1, flags=re.M)

    if START in text and END in text:
        head = text.split(START)[0]
        tail = text.split(END)[1]
        text = f"{head}{START}\n{block}\n{END}{tail}"
    else:
        text = f"{text}\n\n{START}\n{block}\n{END}\n"

    with open(README, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"索引已更新：{len(rows)} 篇")


if __name__ == "__main__":
    main()

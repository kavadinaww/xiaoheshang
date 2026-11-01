#!/usr/bin/env python3
"""生成静态看板 dashboard/index.html（五块：今天、需要你、作品、规律、运转）。

数据来源（只读仓库文件，不臆造）：
- log/生产与发布日志.md      今天的状态行
- ledgers/需要你.md           状态非“完成”的行
- data/percentile_latest.csv  作品同龄分位（先跑 percentile.py）
- data/corr_latest.csv        早期指标相关（周日跑 percentile.py --corr）
- ledgers/实验登记.md、ledgers/选题库.md、batches/
用法：python3 scripts/dashboard.py [--date YYYY-MM-DD]
"""
import argparse
import csv
import datetime as dt
import html
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    p = os.path.join(ROOT, rel)
    return open(p, encoding="utf-8").read() if os.path.exists(p) else ""


def md_table(text):
    rows = [l for l in text.splitlines() if l.startswith("|")]
    if len(rows) < 2:
        return [], []
    split = lambda l: [c.strip() for c in l.strip().strip("|").split("|")]
    return split(rows[0]), [split(r) for r in rows[2:]]


def csv_rows(rel):
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def table(head, rows):
    if not rows:
        return "<p class='empty'>暂无</p>"
    h = "".join(f"<th>{html.escape(c)}</th>" for c in head)
    b = "".join("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table>"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    day = ap.parse_args().date

    log = read("log/生产与发布日志.md")
    today = [l[2:] for l in log.splitlines() if l.startswith("- ") and day in l]

    nh, nrows = md_table(read("ledgers/需要你.md"))
    need = []
    for r in nrows:
        if r and r[-1] not in ("完成", "✓"):
            try:
                waited = (dt.date.fromisoformat(day) - dt.date.fromisoformat(r[3])).days
            except (ValueError, IndexError):
                waited = "?"
            need.append([r[1], r[2], f"{waited} 天", r[5] if len(r) > 5 else ""])

    pct = csv_rows("data/percentile_latest.csv")
    pct_rows = [[r["work_id"], r["platform"], r["checkpoint"], r["plays"], r.get("status", ""),
                 r.get("p_median") or "—", r.get("p_completion") or "—", r.get("p_bounce_2s") or "—"]
                for r in pct]

    corr = csv_rows("data/corr_latest.csv")
    corr_rows = [[r["metric"], r["n"], r["r"] or "—", r["verdict"]] for r in corr]
    eh, erows = md_table(read("ledgers/实验登记.md"))

    topics = read("ledgers/选题库.md")
    left = len(re.findall(r"^- \[ \]", topics, re.M))
    batches_dir = os.path.join(ROOT, "batches")
    files = sorted(f for f in os.listdir(batches_dir) if f.endswith(".md")) if os.path.isdir(batches_dir) else []
    spare = sum(read(f"batches/{f}").count("状态：备用") for f in files)
    published = len({r["work_id"] for r in csv_rows("data/works.csv")})
    ops = [["已发布作品", published], ["备用成片（水位 ≥ 2）", spare], ["选题库剩余（≥ 15）", left], ["批次文件", len(files)]]

    css = """
:root{--bg:#faf8f3;--fg:#2b2a27;--muted:#76716a;--line:#e4dfd4;--accent:#9a6b2f;--card:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#1d1c1a;--fg:#ece8e1;--muted:#a39d93;--line:#3a3834;--accent:#d9a55f;--card:#262522}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 -apple-system,"PingFang SC","Noto Sans CJK SC",sans-serif}
main{max-width:960px;margin:0 auto;padding:24px 16px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 8px;color:var(--accent)}
.sub{color:var(--muted);margin:0 0 8px}section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}
th{color:var(--muted);font-weight:600}ul{margin:0;padding-left:18px}.empty{color:var(--muted)}
.wrap{overflow-x:auto}
"""
    body = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>小满看板</title><style>{css}</style></head>
<body><main><h1>小和尚听故事 · 看板</h1><p class="sub">{day} · 由 scripts/dashboard.py 从仓库文件生成</p>
<h2>今天</h2><section>{"<ul>" + "".join(f"<li>{html.escape(l)}</li>" for l in today) + "</ul>" if today else "<p class='empty'>今天还没有状态行</p>"}</section>
<h2>需要你</h2><section class="wrap">{table(["类别", "事项", "等了", "怎么做"], need)}</section>
<h2>作品 · 同龄分位</h2><section class="wrap">{table(["作品", "平台", "时点", "播放", "状态", "分位中位", "完播分位", "2秒留住分位"], pct_rows)}</section>
<h2>规律</h2><section class="wrap"><p class="sub">早期指标 vs 7 天涨粉</p>{table(["指标", "样本", "r", "判断"], corr_rows)}
<p class="sub" style="margin-top:12px">实验</p>{table(eh, erows)}</section>
<h2>运转</h2><section class="wrap">{table(["项目", "数值"], ops)}</section>
</main></body></html>"""
    os.makedirs(os.path.join(ROOT, "dashboard"), exist_ok=True)
    out = os.path.join(ROOT, "dashboard", "index.html")
    open(out, "w", encoding="utf-8").write(body)
    print(f"写入 {out}")


if __name__ == "__main__":
    main()

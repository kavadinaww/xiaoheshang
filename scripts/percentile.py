#!/usr/bin/env python3
"""同龄分位：每条作品在 24h/72h/7d 时点，与本账号同平台、同时长段作品的同一时点比。

用法：
  python3 scripts/percentile.py data/works.csv [--out data/percentile_latest.csv]
  python3 scripts/percentile.py data/works.csv --corr   # 每周：早期指标 vs 7 天涨粉相关

works.csv 列：work_id,platform,published_at,checkpoint(24h|72h|7d),duration_s,plays,
bounce_2s,retain_5s,completion,avg_watch_s,likes,comments,shares,saves,new_followers,column,experiment
比率列（bounce_2s/retain_5s/completion）用 0–1 小数。
"""
import argparse
import csv
import math
import sys
from collections import defaultdict

MIN_PLAYS = 500      # 播放 < 500：样本不足
MIN_PEERS = 5        # 同组可比作品 < 5：冷启动
# 越大越好的指标；bounce_2s 越小越好，单独取反
METRICS = ["completion", "retain_5s", "avg_watch_s", "share_rate", "new_followers"]
LOWER_IS_BETTER = {"bounce_2s"}


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def duration_band(d):
    d = f(d) or 0
    if d <= 30:
        return "≤30s"
    if d <= 60:
        return "31-60s"
    return ">60s"


def load(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            plays = f(r.get("plays")) or 0
            r["_plays"] = plays
            shares = f(r.get("shares"))
            r["share_rate"] = (shares / plays) if (shares is not None and plays) else None
            r["_band"] = duration_band(r.get("duration_s"))
            rows.append(r)
    return rows


def pct_rank(value, peers, lower_better=False):
    """value 在 peers 中的分位（0–100），并列取中点。"""
    if value is None or not peers:
        return None
    below = sum(1 for p in peers if (p > value if lower_better else p < value))
    equal = sum(1 for p in peers if p == value)
    return round(100 * (below + 0.5 * equal) / len(peers))


def percentiles(rows):
    groups = defaultdict(list)
    for r in rows:
        groups[(r["platform"], r["checkpoint"], r["_band"])].append(r)

    out = []
    for key, items in groups.items():
        eligible = [r for r in items if r["_plays"] >= MIN_PLAYS]
        for r in items:
            res = {"work_id": r["work_id"], "platform": r["platform"],
                   "checkpoint": r["checkpoint"], "band": r["_band"], "plays": int(r["_plays"])}
            if r["_plays"] < MIN_PLAYS:
                res["status"] = "样本不足"
            elif len(eligible) < MIN_PEERS:
                res["status"] = "冷启动"
            else:
                res["status"] = "ok"
                scores = []
                for m in METRICS + ["bounce_2s"]:
                    peers = [v for v in (f(p.get(m)) if m != "share_rate" else p.get(m)
                                         for p in eligible) if v is not None]
                    val = f(r.get(m)) if m != "share_rate" else r.get(m)
                    s = pct_rank(val, peers, m in LOWER_IS_BETTER)
                    res[f"p_{m}"] = s
                    if s is not None:
                        scores.append(s)
                res["p_median"] = sorted(scores)[len(scores) // 2] if scores else None
            out.append(res)
    out.sort(key=lambda x: (x["checkpoint"], x["platform"], -(x.get("p_median") or -1)))
    return out


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def correlations(rows):
    """24h 早期指标 vs 同作品同平台 7d 涨粉。|r|<0.3 视为不跟结果走。"""
    early = {(r["work_id"], r["platform"]): r for r in rows if r["checkpoint"] == "24h"}
    late = {(r["work_id"], r["platform"]): r for r in rows if r["checkpoint"] == "7d"}
    keys = [k for k in early if k in late and f(late[k].get("new_followers")) is not None]
    result = []
    for m in ["bounce_2s", "retain_5s", "completion", "avg_watch_s", "share_rate"]:
        pairs = []
        for k in keys:
            v = f(early[k].get(m)) if m != "share_rate" else early[k].get(m)
            if v is not None:
                pairs.append((v, f(late[k]["new_followers"])))
        r = pearson([p[0] for p in pairs], [p[1] for p in pairs])
        verdict = "样本不足" if r is None else ("跟结果走" if abs(r) >= 0.3 else "不跟结果走，降权")
        result.append({"metric": m, "n": len(pairs), "r": None if r is None else round(r, 2), "verdict": verdict})
    return result


def write_csv(rows, path):
    if not rows:
        print("没有数据行。")
        return
    fields = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    fh = open(path, "w", newline="", encoding="utf-8") if path != "-" else sys.stdout
    w = csv.DictWriter(fh, fieldnames=fields)
    w.writeheader()
    w.writerows(rows)
    if fh is not sys.stdout:
        fh.close()
        print(f"写入 {path}（{len(rows)} 行）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--out", default="data/percentile_latest.csv")
    ap.add_argument("--corr", action="store_true")
    a = ap.parse_args()
    rows = load(a.csv)
    if a.corr:
        write_csv(correlations(rows), a.out if a.out != "data/percentile_latest.csv" else "data/corr_latest.csv")
    else:
        write_csv(percentiles(rows), a.out)


if __name__ == "__main__":
    main()

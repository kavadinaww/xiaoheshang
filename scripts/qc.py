#!/usr/bin/env python3
"""成片 QC 数值线（任一不过不发布）。

用法：python3 scripts/qc.py 成片.mp4 [--duration 60] [--landscape]

检查：
- 分辨率 1080×1920（--landscape 时 1920×1080），帧率恒定
- 文件 < 500MB
- 时长与标称差 < 0.2 秒（给了 --duration 时）
- 整体响度 -14 LUFS ±1，真峰值 ≤ -1 dBTP
- 黑帧 / 静帧段（> 1.5 秒）
- 抽 30 帧存到 <成片名>_frames/ 供人工或视觉自审
退出码：0 全过，1 有不过项。
"""
import argparse
import json
import os
import re
import subprocess
import sys


def sh(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def probe(path):
    out = sh(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", path]).stdout
    return json.loads(out)


def frac(s):
    if not s or s == "0/0":
        return 0.0
    a, _, b = s.partition("/")
    return float(a) / float(b or 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--duration", type=float)
    ap.add_argument("--landscape", action="store_true")
    a = ap.parse_args()
    p = a.video
    results = []

    def check(name, ok, detail):
        results.append((name, ok, detail))

    info = probe(p)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    has_a = any(s["codec_type"] == "audio" for s in info["streams"])
    dur = float(info["format"]["duration"])
    size_mb = os.path.getsize(p) / 1024 / 1024
    want = (1920, 1080) if a.landscape else (1080, 1920)
    check("分辨率", (v["width"], v["height"]) == want, f"{v['width']}×{v['height']}，要求 {want[0]}×{want[1]}")
    rf, af = frac(v.get("r_frame_rate")), frac(v.get("avg_frame_rate"))
    check("帧率恒定", abs(rf - af) < 0.05, f"r={rf:.3f} avg={af:.3f}")
    check("文件大小", size_mb < 500, f"{size_mb:.1f} MB")
    if a.duration:
        check("时长", abs(dur - a.duration) < 0.2, f"{dur:.2f}s，标称 {a.duration}s")
    else:
        check("时长", 5 <= dur <= 90, f"{dur:.2f}s（5–90 秒）")
    check("有音轨", has_a, "有" if has_a else "无音轨")

    if has_a:
        e = sh(["ffmpeg", "-hide_banner", "-nostats", "-i", p, "-filter_complex", "ebur128=peak=true", "-f", "null", "-"]).stderr
        summary = e[e.rfind("Summary:"):]
        I = re.search(r"I:\s+(-?[\d.]+) LUFS", summary)
        TP = re.search(r"Peak:\s+(-?[\d.]+) dBFS", summary)
        if I:
            iv = float(I.group(1))
            check("响度", abs(iv + 14) <= 1, f"{iv:.1f} LUFS（-14 ±1）")
        if TP:
            tv = float(TP.group(1))
            check("真峰值", tv <= -1.0, f"{tv:.1f} dBTP（≤ -1）")

    bd = sh(["ffmpeg", "-hide_banner", "-i", p, "-vf", "blackdetect=d=0.3:pix_th=0.10", "-an", "-f", "null", "-"]).stderr
    blacks = re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", bd)
    check("黑帧", not blacks, "无" if not blacks else "; ".join(f"{s}-{e}s" for s, e in blacks))

    fz = sh(["ffmpeg", "-hide_banner", "-i", p, "-vf", "freezedetect=n=0.003:d=1.5", "-an", "-f", "null", "-"]).stderr
    freezes = re.findall(r"freeze_start: ([\d.]+)", fz)
    check("静帧段>1.5s", not freezes, "无" if not freezes else "起点 " + ", ".join(freezes) + "s")

    # 抽 30 帧供视觉自审（造型一致、手脸、乱码）
    fdir = os.path.splitext(p)[0] + "_frames"
    os.makedirs(fdir, exist_ok=True)
    sh(["ffmpeg", "-y", "-v", "error", "-i", p, "-vf", f"fps=30/{max(dur,1):.3f},scale=270:-1",
        "-frames:v", "30", os.path.join(fdir, "f%02d.jpg")])
    n = len([x for x in os.listdir(fdir) if x.endswith(".jpg")])
    check("抽帧", n >= 30, f"{n} 张 → {fdir}")

    bad = 0
    for name, ok, detail in results:
        print(f"{'✓' if ok else '✗'} {name}: {detail}")
        bad += 0 if ok else 1
    print("QC 通过" if not bad else f"QC 不通过：{bad} 项")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

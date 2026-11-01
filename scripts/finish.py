#!/usr/bin/env python3
"""成片后期：分镜拼接 + 背景音乐 + 字幕（可选第 0 帧大字）+ 片尾系列名 + 响度标准化。

只用 ffmpeg，禁止浏览器重编码（飞猪 15 秒版教训：码率掉、帧间隔不均、时长漂移）。

用法：python3 scripts/finish.py path/to/finish.json

finish.json 示例：
{
  "out": "batches/第1批_20261102/P001/P001_成片.mp4",
  "width": 1080, "height": 1920, "fps": 30,
  "shots": ["shot1.mp4", "shot2.mp4"],          # 相对 json 所在目录；每镜自带对白/环境音
  "bgm": "assets/bgm/guqin_01.mp3",             # 可选，相对仓库根或绝对路径
  "bgm_db": -20,                                # 背景音乐相对音量
  "hook_text": "叶子怎么扫不完？",              # 可选，第 0–2 秒大字
  "subtitles": [{"start": 0.0, "end": 2.5, "text": "师父，我扫了一上午"}],
  "end_card": "小满和松师父",                   # 可选，最后 2 秒系列名
  "font": "Noto Sans CJK SC",
  "crf": 16
}
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(cmd):
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def probe_duration(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "default=nk=1:nw=1", path], text=True)
    return float(out.strip())


def has_audio(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "a",
                                   "-show_entries", "stream=index", "-of", "csv=p=0", path], text=True)
    return bool(out.strip())


def ass_time(t):
    h, rem = divmod(max(t, 0), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def ass_escape(text):
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def build_ass(cfg, total, path):
    W, H, font = cfg["width"], cfg["height"], cfg.get("font", "Noto Sans CJK SC")
    sub_size = round(H * 0.034)
    hook_size = round(H * 0.06)
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        # 字幕放画面下方 22% 处，避开平台底部按钮区，也不压脸
        f"Style: Sub,{font},{sub_size},&H00FFFFFF,&H00FFFFFF,&H00303030,&H64000000,1,0,0,0,100,100,0,0,1,3,0,2,60,60,{round(H*0.22)},1",
        f"Style: Hook,{font},{hook_size},&H0000E1FF,&H00FFFFFF,&H00202020,&H00000000,1,0,0,0,100,100,2,0,1,5,0,8,60,60,{round(H*0.16)},1",
        f"Style: End,{font},{round(H*0.04)},&H00FFFFFF,&H00FFFFFF,&H00202020,&H00000000,1,0,0,0,100,100,4,0,1,3,0,5,60,60,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    hook = cfg.get("hook_text")
    for s in cfg.get("subtitles", []):
        start = float(s["start"])
        if hook and start < 2.0:   # 前 2 秒只放大字，不同时出字幕
            start = 2.0
        if float(s["end"]) <= start:
            continue
        lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(float(s['end']))},Sub,,0,0,0,,{ass_escape(s['text'])}")
    if hook:
        lines.append(f"Dialogue: 1,{ass_time(0)},{ass_time(2.0)},Hook,,0,0,0,,{ass_escape(hook)}")
    if cfg.get("end_card"):
        lines.append(f"Dialogue: 1,{ass_time(total - 2.0)},{ass_time(total)},End,,0,0,0,,{ass_escape(cfg['end_card'])}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def resolve(p, base):
    if os.path.isabs(p):
        return p
    cand = os.path.join(base, p)
    return cand if os.path.exists(cand) else os.path.join(ROOT, p)


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    cfg_path = os.path.abspath(sys.argv[1])
    base = os.path.dirname(cfg_path)
    cfg = json.load(open(cfg_path, encoding="utf-8"))
    cfg.setdefault("width", 1080)
    cfg.setdefault("height", 1920)
    cfg.setdefault("fps", 30)
    W, H, fps, crf = cfg["width"], cfg["height"], cfg["fps"], cfg.get("crf", 16)
    # out：绝对路径；以 batches/ 开头视为相对仓库根；否则相对 json 所在目录
    out = cfg["out"]
    if not os.path.isabs(out):
        out = os.path.join(ROOT if out.startswith("batches/") else base, out)
    os.makedirs(os.path.dirname(out), exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        # 1) 每镜统一规格（分辨率、帧率、像素格式、音频），没有音轨的补静音
        norm = []
        for i, shot in enumerate(cfg["shots"]):
            src = resolve(shot, base)
            dst = os.path.join(tmp, f"n{i:02d}.mp4")
            vf = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
                  f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p,setsar=1")
            cmd = ["ffmpeg", "-y", "-v", "error", "-i", src]
            if not has_audio(src):
                cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-shortest"]
            cmd += ["-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
                    "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "192k", dst]
            run(cmd)
            norm.append(dst)

        # 2) 拼接
        lst = os.path.join(tmp, "list.txt")
        with open(lst, "w") as fh:
            fh.writelines(f"file '{p}'\n" for p in norm)
        joined = os.path.join(tmp, "joined.mp4")
        run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", joined])
        total = probe_duration(joined)

        # 3) 字幕 + 背景音乐 + 响度
        ass = os.path.join(tmp, "subs.ass")
        build_ass(cfg, total, ass)
        ass_arg = ass.replace(":", "\\:")
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", joined]
        bgm = cfg.get("bgm")
        if bgm:
            cmd += ["-stream_loop", "-1", "-i", resolve(bgm, base)]
            db = cfg.get("bgm_db", -20)
            fc = (f"[1:a]volume={db}dB,afade=t=in:d=1,afade=t=out:st={max(total-2,0):.2f}:d=2,atrim=0:{total:.3f}[b];"
                  f"[0:a][b]amix=inputs=2:duration=first:normalize=0,"
                  f"loudnorm=I=-14:TP=-1.5:LRA=11[a]")
        else:
            fc = "[0:a]loudnorm=I=-14:TP=-1.5:LRA=11[a]"
        fc += f";[0:v]subtitles='{ass_arg}'[v]"
        cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-r", str(fps),
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-b:a", "192k",
                "-movflags", "+faststart", "-t", f"{total:.3f}", out]
        run(cmd)
    print(f"完成：{out}（{probe_duration(out):.2f} 秒）。下一步：python3 scripts/qc.py {out}")


if __name__ == "__main__":
    main()

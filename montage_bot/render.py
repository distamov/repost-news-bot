import math
from pathlib import Path
from typing import Awaitable, Callable

from . import config
from .selector import Shot
from .sources import run

W, H, FPS = 720, 1280, 30
X264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", "-r", str(FPS)]


def _even(x: float) -> int:
    return int(math.ceil(x / 2) * 2)


def _blur_fill(fg_width: int, out_w: int, out_h: int) -> str:
    """Горизонтальный кадр целиком по центру, сверху и снизу — его же
    размытая копия (размываем уменьшенную копию — в разы быстрее)."""
    return (
        f"split[a][b];"
        f"[a]scale={out_w // 4}:{out_h // 4}:force_original_aspect_ratio=increase,crop={out_w // 4}:{out_h // 4},"
        f"boxblur=10:2,scale={out_w}:{out_h},eq=brightness=-0.06[bg];"
        f"[b]scale={fg_width}:-2,crop='min(iw,{out_w})':'min(ih,{out_h})'[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2"
    )


def _cover(out_w: int, out_h: int) -> str:
    return f"scale={out_w}:{out_h}:force_original_aspect_ratio=increase,crop={out_w}:{out_h}"


def _ken_burns(mode: str, frames: int) -> str:
    p = f"(on/{max(frames - 1, 1)})"
    center_x, center_y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    z, x, y = "1.12", center_x, center_y
    if mode == "in":
        z = f"1+0.15*{p}"
    elif mode == "out":
        z = f"1.15-0.15*{p}"
    elif mode == "left":
        x = f"(iw-iw/zoom)*(1-{p})"
    elif mode == "right":
        x = f"(iw-iw/zoom)*{p}"
    elif mode == "up":
        y = f"(ih-ih/zoom)*(1-{p})"
    else:
        y = f"(ih-ih/zoom)*{p}"
    return f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={W}x{H}:fps={FPS}"


async def render_shot(shot: Shot, out: Path) -> None:
    d = shot.duration
    tail = f"setsar=1,tpad=stop_mode=clone:stop_duration={d:.3f},trim=duration={d:.3f},format=yuv420p"

    if shot.source.kind == "photo":
        frames = round(d * FPS)
        cw, ch = W * 2, H * 2  # двойной холст — без него zoompan дрожит
        compose = _blur_fill(cw, cw, ch) if shot.source.landscape else _cover(cw, ch)
        graph = f"[0:v]{compose},{_ken_burns(shot.kb, frames)},{tail}[v]"
        inputs = ["-loop", "1", "-framerate", str(FPS), "-t", f"{d:.3f}", "-i", str(shot.source.path)]
    else:
        src_dur = d * shot.speed
        retime = f"setpts=(PTS-STARTPTS)/{shot.speed:.4f},fps={FPS}"
        if shot.source.landscape:
            frame = _blur_fill(_even(W * shot.zoom), W, H)
        else:
            frame = f"{_cover(_even(W * shot.zoom), _even(H * shot.zoom))},crop={W}:{H}"
        graph = f"[0:v]{retime},{frame},{tail}[v]"
        inputs = ["-ss", f"{shot.start:.3f}", "-t", f"{src_dur + 0.1:.3f}", "-i", str(shot.source.path)]

    await run(
        "ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", graph, "-map", "[v]",
        "-an", *X264, "-t", f"{d:.3f}", str(out), capture=False,
    )


async def render_video(
    job_dir: Path,
    shots: list[Shot],
    ass_text: str,
    voice: Path,
    total: float,
    progress: Callable[[int, int], Awaitable[None]] | None = None,
) -> Path:
    parts_dir = job_dir / "parts"
    parts_dir.mkdir(exist_ok=True)
    parts = []
    for i, shot in enumerate(shots):
        part = parts_dir / f"{i:03d}.mp4"
        await render_shot(shot, part)
        parts.append(part)
        if progress:
            await progress(i + 1, len(shots))

    concat_list = job_dir / "concat.txt"
    concat_list.write_text("".join(f"file '{p}'\n" for p in parts))
    joined = job_dir / "joined.mp4"
    await run("ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(concat_list),
              "-c", "copy", str(joined), capture=False)

    ass_path = job_dir / "subs.ass"
    ass_path.write_text(ass_text, encoding="utf-8")

    inputs = ["-i", str(joined), "-i", str(voice)]
    has_music = config.MUSIC_PATH.exists()
    has_logo = config.LOGO_PATH.exists()
    if has_music:
        inputs += ["-stream_loop", "-1", "-i", str(config.MUSIC_PATH)]
    if has_logo:
        inputs += ["-i", str(config.LOGO_PATH)]
    logo_idx = 3 if has_music else 2

    v = "[0:v]tpad=stop_mode=clone:stop_duration=2[v0]"
    last = "v0"
    if has_logo:
        v += (f";[{logo_idx}:v]scale={config.LOGO_WIDTH}:-1,format=rgba[lg]"
              f";[v0][lg]overlay=(W-w)/2:{config.LOGO_Y}[v1]")
        last = "v1"
    v += f";[{last}]ass='{ass_path}':fontsdir='{config.FONTS_DIR}'[v]"

    a = "[1:a]aresample=48000,aformat=channel_layouts=stereo"
    if has_music:
        fade_at = max(total - 1.5, 0)
        a += ("[vo];[2:a]aresample=48000,aformat=channel_layouts=stereo,"
              f"volume={config.MUSIC_VOLUME_DB}dB,afade=t=out:st={fade_at:.2f}:d=1.5[mu];"
              "[vo][mu]amix=inputs=2:duration=first:dropout_transition=0:normalize=0")
    a += "[a]"

    out = job_dir / "result.mp4"
    await run(
        "ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", f"{v};{a}",
        "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}", *X264,
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out), capture=False,
    )
    return out

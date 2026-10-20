import math
from pathlib import Path
from typing import Awaitable, Callable

from . import config
from .selector import Shot
from .sources import run
from .subtitles import STRIP_TOP, Chunk, render_caption_track

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


EDGE_ZONE = 0.25  # надпись в верхней/нижней четверти — обрезаем, ближе к центру — закрашиваем
MIN_KEEP = 0.7  # если обрезкой теряется больше 30% кадра — лучше закрасить


def _overlay_plan(overlays: list) -> tuple[float, float, list]:
    """Чужие водяные знаки у края — обрезаем полосой (картинка чище),
    посередине — закрашиваем (обрезка там съела бы полкадра).
    Возвращает (верх, низ оставляемой части кадра, что закрасить)."""
    top, bottom, blur = 0.0, 1.0, []
    for box in overlays:
        x0, y0, x1, y1 = box
        if y0 >= 1 - EDGE_ZONE:
            bottom = min(bottom, y0 - 0.015)
        elif y1 <= EDGE_ZONE:
            top = max(top, y1 + 0.015)
        else:
            blur.append(box)
    if bottom - top < MIN_KEEP:
        return 0.0, 1.0, list(overlays)
    return top, bottom, blur


def _remove_overlays(overlays: list, width: int, height: int) -> str:
    top, bottom, inner = _overlay_plan(overlays)
    parts = []
    for x0, y0, x1, y1 in inner:
        # delogo закрашивает область по соседним пикселям — в отличие от размытия,
        # убирает и сплошную плашку под текстом. Область должна быть строго внутри кадра.
        x = max(1, int((x0 - 0.03) * width))
        y = max(1, int((y0 - 0.015) * height))
        x2 = min(width - 2, int((x1 + 0.03) * width))
        y2 = min(height - 2, int((y1 + 0.015) * height))
        if x2 - x > 2 and y2 - y > 2:
            parts.append(f"delogo=x={x}:y={y}:w={x2 - x}:h={y2 - y}")
    if top > 0 or bottom < 1:
        parts.append(f"crop=iw:ih*{bottom - top:.4f}:0:ih*{top:.4f}")
    return ",".join(parts)


def _sharpen(src_width: int) -> str:
    # Исходники из соцсетей бывают 352px шириной — после растягивания до 720 они мыльные.
    return ",unsharp=5:5:0.7" if src_width < 600 else ""


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
        cleanup = _remove_overlays(shot.source.overlays, shot.source.width, shot.source.height)
        # После обрезки полосы с надписью горизонтальный кадр может стать «вертикальнее» —
        # решение размывать фон принимаем по тому, что осталось.
        top, bottom, _ = _overlay_plan(shot.source.overlays)
        keep = bottom - top
        if shot.source.width / (shot.source.height * keep) > 0.7:
            frame = _blur_fill(_even(W * shot.zoom), W, H)
        else:
            frame = f"{_cover(_even(W * shot.zoom), _even(H * shot.zoom))},crop={W}:{H}"
        chain = ",".join(p for p in (retime, cleanup, frame) if p)
        graph = f"[0:v]{chain}{_sharpen(shot.source.width)},{tail}[v]"
        inputs = ["-ss", f"{shot.start:.3f}", "-t", f"{src_dur + 0.1:.3f}", "-i", str(shot.source.path)]

    await run(
        "ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", graph, "-map", "[v]",
        "-an", *X264, "-t", f"{d:.3f}", str(out), capture=False,
    )


async def render_video(
    job_dir: Path,
    shots: list[Shot],
    chunks: list[Chunk],
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

    captions = render_caption_track(chunks, total, parts_dir / "captions", config.FONT_PATH)

    inputs = ["-i", str(joined), "-i", str(voice), "-f", "concat", "-safe", "0", "-i", str(captions)]
    next_idx = 3
    music_idx = logo_idx = None
    if config.MUSIC_PATH.exists():
        inputs += ["-stream_loop", "-1", "-i", str(config.MUSIC_PATH)]
        music_idx, next_idx = next_idx, next_idx + 1
    if config.LOGO_PATH.exists():
        inputs += ["-i", str(config.LOGO_PATH)]
        logo_idx = next_idx

    v = "[0:v]tpad=stop_mode=clone:stop_duration=2[v0]"
    last = "v0"
    if logo_idx is not None:
        v += (f";[{logo_idx}:v]scale={config.LOGO_WIDTH}:-1,format=rgba[lg]"
              f";[v0][lg]overlay=(W-w)/2:{config.LOGO_Y}[v1]")
        last = "v1"
    v += (f";[2:v]fps={FPS},format=rgba[cap]"
          f";[{last}][cap]overlay=0:{STRIP_TOP}:eof_action=pass[v]")

    a = "[1:a]aresample=48000,aformat=channel_layouts=stereo"
    if music_idx is not None:
        fade_at = max(total - 1.5, 0)
        a += (f"[vo];[{music_idx}:a]aresample=48000,aformat=channel_layouts=stereo,"
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

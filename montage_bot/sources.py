import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

MOTION_FPS = 2  # одна оценка «живости» на каждые 0.5 сек исходника
_AW, _AH = 180, 320  # разрешение для анализа (динамика + поиск чужих надписей)
IMAGE_FORMATS = ("image2", "png_pipe", "jpeg_pipe", "webp_pipe", "bmp_pipe", "gif", "tiff_pipe")

Box = tuple[float, float, float, float]  # x0, y0, x1, y1 в долях кадра


@dataclass
class Source:
    path: Path
    kind: str  # "video" | "photo"
    width: int
    height: int
    duration: float = 0.0
    motion: np.ndarray = field(default_factory=lambda: np.zeros(0))
    overlays: list[Box] = field(default_factory=list)  # чужие водяные знаки/подписи

    @property
    def landscape(self) -> bool:
        # Всё, что заметно шире вертикали 9:16 (4:5, квадрат, 16:9), вписывается с размытым фоном.
        return self.width / self.height > 0.7


async def run(*args: str, capture: bool = True) -> bytes:
    proc = await asyncio.create_subprocess_exec(
        "nice", "-n", "10", *args,
        stdout=asyncio.subprocess.PIPE if capture else asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"{args[0]} failed: {err.decode(errors='ignore')[-800:]}")
    return out or b""


async def media_duration(path: Path) -> float:
    out = await run("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path))
    return float(out.decode().strip() or 0)


async def probe(path: Path) -> Source:
    out = await run(
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,nb_frames:stream_side_data=rotation:stream_tags=rotate:format=duration,format_name",
        "-of", "json", str(path),
    )
    info = json.loads(out)
    stream = (info.get("streams") or [{}])[0]
    fmt = info.get("format", {})
    w, h = int(stream.get("width", 0)), int(stream.get("height", 0))
    if not w or not h:
        raise ValueError(f"В файле нет изображения: {path.name}")

    rotation = stream.get("tags", {}).get("rotate")
    for sd in stream.get("side_data_list", []):
        rotation = sd.get("rotation", rotation)
    if rotation is not None and abs(int(float(rotation))) % 180 == 90:
        w, h = h, w  # телефонное видео хранится лёжа с пометкой о повороте

    duration = float(fmt.get("duration") or 0)
    is_image = fmt.get("format_name", "") in IMAGE_FORMATS or str(stream.get("nb_frames")) == "1" or duration < 0.2
    if is_image:
        return Source(path, "photo", w, h)
    src = Source(path, "video", w, h, duration)
    raw = await run(
        "ffmpeg", "-v", "error", "-i", str(path),
        "-vf", f"fps={MOTION_FPS},scale={_AW}:{_AH},format=gray", "-f", "rawvideo", "-",
    )
    n = len(raw) // (_AW * _AH)
    frames = np.frombuffer(raw, dtype=np.uint8)[: n * _AW * _AH].reshape(n, _AH, _AW)
    src.motion = motion_profile(frames)
    src.overlays = detect_overlays(frames)
    return src


def motion_profile(frames: np.ndarray) -> np.ndarray:
    """Насколько меняется картинка в каждые полсекунды — чтобы не брать
    статичные, скучные куски."""
    if len(frames) < 2:
        return np.zeros(max(len(frames), 1))
    small = frames[:, ::4, ::4].astype(np.int16)
    diff = np.abs(np.diff(small, axis=0)).mean(axis=(1, 2))
    return np.concatenate([[diff[0]], diff])


def detect_overlays(frames: np.ndarray, max_samples: int = 48) -> list[Box]:
    """Ищет наложенные поверх видео надписи (водяные знаки чужих каналов):
    когда камера движется, неподвижными остаются только они — их контуры
    есть почти в каждом кадре."""
    if len(frames) < 6:
        return []
    idx = np.linspace(0, len(frames) - 1, min(len(frames), max_samples)).astype(int)
    f = frames[idx].astype(np.int16)
    edges = np.abs(np.diff(f, axis=2))[:, :-1, :] + np.abs(np.diff(f, axis=1))[:, :, :-1]
    mask = np.percentile(edges, 20, axis=0) > 40
    if mask.mean() > 0.12:
        return []  # камера стояла на месте — неподвижна вся сцена, надписи так не отличить
    h, w = mask.shape
    rows = np.append(mask.mean(axis=1), 0)
    boxes, start = [], None
    for y, density in enumerate(rows):
        if density > 0.08 and start is None:
            start = y
        elif density <= 0.08 and start is not None:
            if 3 <= y - start <= 0.15 * h:
                xs = np.where(mask[start:y].mean(axis=0) > 0.15)[0]
                if len(xs) and (xs.max() - xs.min()) / w > 0.08:
                    boxes.append((xs.min() / w, start / h, (xs.max() + 1) / w, y / h))
            start = None
    return boxes

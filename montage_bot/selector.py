import random
from dataclasses import dataclass

import numpy as np

from .sources import MOTION_FPS, Source

PHOTO_WEIGHT = 4.0  # одно фото считается как ~4 сек материала при раздаче склеек
STEP = 0.5
MARGIN = 0.2  # зазор между кусками, чтобы соседние склейки не выглядели продолжением друг друга
KEN_BURNS = ["in", "out", "left", "right", "up", "down"]


@dataclass
class Shot:
    duration: float  # длительность склейки в готовом ролике
    source: Source
    start: float = 0.0  # с какой секунды исходника
    speed: float = 1.0  # < 1 — замедление
    zoom: float = 1.0  # > 1 — наезд камеры (нужен, чтобы повторный кусок не выглядел копией)
    kb: str = ""  # движение камеры по фото


ZOOMS = [1.15, 1.2, 1.25]
REUSE_SPEEDS = [1.0, 0.8, 0.7]
TOP_BAND = 0.2  # случайный выбор среди почти равных по качеству вариантов — «Пересобрать» даёт другой ролик


def _overlap(a: float, b: float, s: float, e: float) -> float:
    return max(0.0, min(e, b + MARGIN) - max(s, a - MARGIN))


class _VideoPicker:
    def __init__(self, videos: list[Source], rng: random.Random):
        self.videos = videos
        self.rng = rng
        self.total = sum(v.duration for v in videos)
        self.offsets = np.cumsum([0.0] + [v.duration for v in videos[:-1]])
        # (начало, конец, зум) уже взятых кусков каждого ролика
        self.used: dict[int, list[tuple[float, float, float]]] = {i: [] for i in range(len(videos))}
        self.motion = []
        for v in videos:
            m = v.motion if len(v.motion) else np.zeros(1)
            self.motion.append(np.clip(m / (np.percentile(m, 90) + 1e-6), 0, 1.5))
        self.last: tuple[int, float, float] | None = None

    def _score(self, vi: int, s: float, src: float, target: float, dist_w: float) -> float:
        m = self.motion[vi]
        a, b = int(s * MOTION_FPS), max(int((s + src) * MOTION_FPS), int(s * MOTION_FPS) + 1)
        motion = float(m[a:b].mean()) if a < len(m) else 0.0
        center = self.offsets[vi] + s + src / 2
        return motion - dist_w * abs(center - target) / max(self.total, 1e-6)

    def _candidates(self, src: float, target: float, dist_w: float, reuse: bool):
        found = []
        for vi, v in enumerate(self.videos):
            if v.duration < src:
                continue
            for s in np.arange(0.0, v.duration - src + 1e-6, STEP):
                s = float(s)
                ov = sum(_overlap(a, b, s, s + src) for a, b, _ in self.used[vi])
                if ov and not reuse:
                    continue
                if reuse and self.last and self.last[0] == vi and _overlap(*self.last[1:], s, s + src):
                    continue  # тот же кусок два раза подряд сразу бросается в глаза
                score = self._score(vi, s, src, target, dist_w) - (0.3 * ov / src if reuse else 0)
                found.append((score, vi, s))
        return found

    def _choose(self, found):
        best = max(f[0] for f in found)
        band = sorted((f for f in found if f[0] >= best - TOP_BAND), reverse=True)[:5]
        return self.rng.choice(band)

    def pick(self, duration: float, frac: float, first: bool) -> Shot:
        target = frac * self.total
        dist_w = 0.3 if first else 2.0  # первая склейка — самый яркий момент, остальные по порядку
        for speed in (1.0, 0.75):  # сначала свежие куски, в крайнем случае — с замедлением
            found = self._candidates(duration * speed, target, dist_w, reuse=False)
            if found:
                _, vi, s = self._choose(found)
                return self._take(vi, s, duration, speed, 1.0)

        # Свежего материала не осталось — повторяем, но с другим наездом и скоростью,
        # чтобы кусок не выглядел копией.
        speed = self.rng.choice(REUSE_SPEEDS)
        found = self._candidates(duration * speed, target, dist_w, reuse=True)
        if found:
            _, vi, s = self._choose(found)
            src = duration * speed
            taken = {z for a, b, z in self.used[vi] if _overlap(a, b, s, s + src)}
            zoom = self.rng.choice([z for z in ZOOMS if z not in taken] or ZOOMS)
            return self._take(vi, s, duration, speed, zoom)

        # Все ролики короче склейки даже с замедлением — берём самый длинный целиком.
        vi = max(range(len(self.videos)), key=lambda i: self.videos[i].duration)
        speed = max(0.5, self.videos[vi].duration / duration)
        return self._take(vi, 0.0, duration, speed, 1.0)

    def _take(self, vi: int, s: float, duration: float, speed: float, zoom: float) -> Shot:
        src = min(duration * speed, self.videos[vi].duration - s)
        self.used[vi].append((s, s + src, zoom))
        self.last = (vi, s, s + src)
        return Shot(duration, self.videos[vi], start=s, speed=speed, zoom=zoom)


def plan_shots(cuts: list[tuple[float, float]], sources: list[Source], rng: random.Random) -> list[Shot]:
    videos = [s for s in sources if s.kind == "video" and s.duration > 0.3]
    photos = [s for s in sources if s.kind == "photo"]
    if not videos and not photos:
        raise ValueError("Нет исходников для монтажа")

    durations = [b - a for a, b in cuts]
    n = len(durations)
    if not videos:
        photo_slots = set(range(n))
    elif not photos:
        photo_slots = set()
    else:
        material = len(photos) * PHOTO_WEIGHT
        k = min(len(photos), max(1, round(n * material / (material + sum(v.duration for v in videos)))))
        photo_slots = {min(n - 1, int((j + 0.5) * n / k)) for j in range(k)}
        if 0 in photo_slots and n > 1:  # открываем ролик видео, а не статикой
            photo_slots.discard(0)
            photo_slots.add(next(i for i in range(1, n) if i not in photo_slots))

    shots: list[Shot | None] = [None] * n
    modes = KEN_BURNS[:]
    rng.shuffle(modes)
    for j, i in enumerate(sorted(photo_slots)):
        shots[i] = Shot(durations[i], photos[j % len(photos)], kb=modes[j % len(modes)])

    video_slots = [i for i in range(n) if i not in photo_slots]
    if video_slots:
        picker = _VideoPicker(videos, rng)
        for k, i in enumerate(video_slots):
            shots[i] = picker.pick(durations[i], (k + 0.5) / len(video_slots), first=(k == 0))
    return shots

import bisect
import random

FAST_PHASE = 15.0  # первые секунды ролика режутся мельче, чтобы зацепить зрителя
FAST_CUT = 3.0
SLOW_MIN, SLOW_MAX = 3.0, 5.0
MIN_SHOT = 1.5  # короче этого склейка не бывает: хвост сливается с предыдущей
SNAP = 0.4  # насколько можно сдвинуть склейку к началу ближайшего слова


def _snap(t: float, word_starts: list[float], lo: float, hi: float) -> float:
    i = bisect.bisect_left(word_starts, t)
    near = [w for w in word_starts[max(0, i - 1): i + 1] if abs(w - t) <= SNAP and lo <= w <= hi]
    return min(near, key=lambda w: abs(w - t)) if near else t


def build_cuts(
    total: float, word_starts: list[float] | None = None, rng: random.Random | None = None
) -> list[tuple[float, float]]:
    """Делит длительность озвучки на склейки: до FAST_PHASE — по FAST_CUT сек,
    дальше — случайно от SLOW_MIN до SLOW_MAX. Склейки подтягиваются к началу
    слов, чтобы монтаж шёл в ритм речи."""
    rng = rng or random.Random()
    word_starts = sorted(word_starts or [])
    bounds = [0.0]
    t = 0.0
    while True:
        step = FAST_CUT if t < FAST_PHASE - 1e-6 else rng.uniform(SLOW_MIN, SLOW_MAX)
        nxt = t + step
        if nxt > total - MIN_SHOT:
            break
        nxt = _snap(nxt, word_starts, t + MIN_SHOT, total - MIN_SHOT)
        bounds.append(nxt)
        t = nxt
    if total - t > SLOW_MAX:
        bounds.append(_snap((t + total) / 2, word_starts, t + MIN_SHOT, total - MIN_SHOT))
    bounds.append(total)
    return list(zip(bounds, bounds[1:]))

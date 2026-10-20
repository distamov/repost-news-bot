import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .sources import concat_line

MAX_WORDS = 3
MAX_CHARS = 18
PAUSE_BREAK = 0.6  # пауза в речи длиннее этого — всегда новая фраза
HOLD_AFTER = 0.5  # сколько фраза ещё висит после последнего слова, если дальше тишина

_SENTENCE_END = re.compile(r"[.!?…;:]$")
_STRIP = ".,;:«»\"“”„()[]{}\\"


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Chunk:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)


def _clean(word: str) -> str:
    return word.strip().strip(_STRIP).upper()


def _is_particle(word: Word) -> bool:
    # «в», «на», «и», «va», «bu» в конце фразы смотрятся оборванно — переносим их в следующую
    return len(_clean(word.text)) <= 2


def chunk_words(words: list[Word]) -> list[Chunk]:
    """Режет слова на фразы по 2–3 слова, как в роликах канала: новая фраза
    начинается на паузе, после конца предложения или если строка слишком длинная."""
    groups: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        if not _clean(w.text):
            continue
        if cur:
            text_len = len(" ".join(_clean(x.text) for x in cur + [w]))
            hard_break = w.start - cur[-1].end > PAUSE_BREAK or _SENTENCE_END.search(cur[-1].text.strip())
            if hard_break or len(cur) >= MAX_WORDS or text_len > MAX_CHARS:
                carry = []
                while not hard_break and len(cur) > 1 and _is_particle(cur[-1]):
                    carry.insert(0, cur.pop())
                groups.append(cur)
                cur = carry
        cur.append(w)
    if cur:
        groups.append(cur)

    chunks = []
    for i, g in enumerate(groups):
        end = max(g[-1].end, g[-1].start + 0.2) + HOLD_AFTER
        if i + 1 < len(groups):
            end = min(end, groups[i + 1][0].start)
        chunks.append(Chunk(g[0].start, max(end, g[0].start + 0.1), " ".join(_clean(w.text) for w in g), g))
    return chunks


def align_corrected_text(words: list[Word], corrected: str) -> list[Word]:
    """Переносит исправленный пользователем текст на таймкоды распознанных
    слов: совпавшие слова берут своё время, заменённые делят время исходного
    участка пропорционально длине, вставленные — время между соседями."""
    new_tokens = corrected.split()
    if not words:
        return []
    norm = lambda s: s.strip(_STRIP).lower()
    matcher = difflib.SequenceMatcher(a=[norm(w.text) for w in words], b=[norm(t) for t in new_tokens], autojunk=False)

    out: list[Word] = []
    for tag, a0, a1, b0, b1 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(b1 - b0):
                w = words[a0 + k]
                out.append(Word(w.start, w.end, new_tokens[b0 + k]))
        elif tag in ("replace", "insert"):
            if tag == "replace":
                span_start, span_end = words[a0].start, words[a1 - 1].end
            else:
                span_start = words[a0 - 1].end if a0 > 0 else words[0].start
                span_end = words[a0].start if a0 < len(words) else words[-1].end
                if span_end - span_start < 0.15 * (b1 - b0):
                    span_end = span_start + 0.15 * (b1 - b0)
            tokens = new_tokens[b0:b1]
            total_chars = sum(len(t) for t in tokens) or 1
            t = span_start
            for tok in tokens:
                d = (span_end - span_start) * len(tok) / total_chars
                out.append(Word(t, t + d, tok))
                t += d
    return out


# Стиль как в роликах канала (CapCut): белый капс с тонкой обводкой и мягкой тенью,
# произносимое сейчас слово — на чёрной плашке со скруглёнными углами.
FONT_SIZE = 34
CAPTION_CENTER_Y = 866  # центр строки в кадре 720×1280
STRIP_W, STRIP_H = 720, 160
STRIP_TOP = CAPTION_CENTER_Y - STRIP_H // 2
MAX_LINE_W = 660
BOX_PAD_X, BOX_PAD_Y, BOX_RADIUS = 7, 7, 7


def _draw_caption(words: list[str], active: int, font: ImageFont.FreeTypeFont) -> Image.Image:
    size = font.size
    while True:
        space = font.getlength(" ")
        widths = [font.getlength(w) for w in words]
        total = sum(widths) + space * (len(words) - 1) + 2 * BOX_PAD_X
        if total <= MAX_LINE_W or size <= 20:
            break
        size -= 2  # длинное узбекское слово не влезает — чуть уменьшаем шрифт
        font = font.font_variant(size=size)

    _, cap_top, _, cap_bot = font.getbbox("Н")
    y = STRIP_H / 2 - (cap_top + cap_bot) / 2  # заглавные буквы ровно по центру полосы
    x = (STRIP_W - (total - 2 * BOX_PAD_X)) / 2
    positions = []
    for wd in widths:
        positions.append(x)
        x += wd + space

    base = Image.new("RGBA", (STRIP_W, STRIP_H), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (STRIP_W, STRIP_H), (0, 0, 0, 0))
    draw, shadow_draw = ImageDraw.Draw(base), ImageDraw.Draw(shadow)
    for i, (word, x0, wd) in enumerate(zip(words, positions, widths)):
        if i == active:
            draw.rounded_rectangle(
                [x0 - BOX_PAD_X, y + cap_top - BOX_PAD_Y, x0 + wd + BOX_PAD_X, y + cap_bot + BOX_PAD_Y],
                radius=BOX_RADIUS, fill=(0, 0, 0, 255),
            )
        else:
            shadow_draw.text((x0, y + 2), word, font=font, fill=(0, 0, 0, 160),
                             stroke_width=2, stroke_fill=(0, 0, 0, 160))
    shadow = shadow.filter(ImageFilter.GaussianBlur(2.5))
    for i, (word, x0) in enumerate(zip(words, positions)):
        draw.text((x0, y), word, font=font, fill=(255, 255, 255, 255),
                  stroke_width=0 if i == active else 1, stroke_fill=(0, 0, 0, 255))
    return Image.alpha_composite(shadow, base)


def render_caption_track(chunks: list[Chunk], total: float, out_dir: Path, font_path: Path) -> Path:
    """Рисует по картинке на каждое слово (плашка переезжает на него, пока оно
    звучит) и собирает их в список для ffmpeg concat с длительностями.
    Возвращает путь к этому списку; картинки — полоса STRIP_W×STRIP_H."""
    out_dir.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype(str(font_path), FONT_SIZE)
    blank = out_dir / "blank.png"
    Image.new("RGBA", (STRIP_W, STRIP_H), (0, 0, 0, 0)).save(blank)

    states: list[tuple[float, float, Path]] = []
    for ci, chunk in enumerate(chunks):
        texts = [_clean(w.text) for w in chunk.words]
        for k, word in enumerate(chunk.words):
            start = chunk.start if k == 0 else word.start
            end = chunk.words[k + 1].start if k + 1 < len(chunk.words) else chunk.end
            if end - start < 0.02:
                continue
            img = out_dir / f"c{ci:03d}_{k}.png"
            _draw_caption(texts, k, font).save(img)
            states.append((start, end, img))

    lines, t = [], 0.0
    for start, end, img in states:
        start = max(start, t)
        if start - t > 0.01:
            lines.append((blank, start - t))
        if end - start > 0.01:
            lines.append((img, end - start))
            t = end
    if total - t > 0.01:
        lines.append((blank, total - t))
    if not lines:
        lines.append((blank, max(total, 0.1)))

    listing = out_dir / "captions.txt"
    body = "".join(f"{concat_line(img)}duration {d:.3f}\n" for img, d in lines)
    # concat требует повторить последний кадр
    listing.write_text(body + concat_line(lines[-1][0]), encoding="utf-8")
    return listing

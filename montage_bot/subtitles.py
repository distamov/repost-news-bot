import difflib
import re
from dataclasses import dataclass

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
        chunks.append(Chunk(g[0].start, max(end, g[0].start + 0.1), " ".join(_clean(w.text) for w in g)))
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


def _ass_time(t: float) -> str:
    cs = int(round(max(t, 0) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def build_ass(chunks: list[Chunk], font_name: str = "Montserrat ExtraBold") -> str:
    """Стиль как в роликах канала: белый жирный капс, чёрная обводка и тень,
    по центру, низ текста ≈ y 880 из 1280."""
    header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 720\nPlayResY: 1280\nWrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Main,{font_name},38,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,"
        "0,0,0,0,100,100,1,0,1,3,2,2,50,50,400,1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = [
        f"Dialogue: 0,{_ass_time(c.start)},{_ass_time(c.end)},Main,,0,0,0,,{c.text.replace('{', '').replace('}', '')}"
        for c in chunks
    ]
    return header + "\n".join(lines) + "\n"

import asyncio
import logging
import random
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image
from telethon import Button, TelegramClient, events
from telethon.tl.types import DocumentAttributeVideo

from . import config
from .render import render_video
from .selector import plan_shots
from .sources import media_duration, probe, run
from .subtitles import Word, align_corrected_text, chunk_words
from .timeline import build_cuts
from .transcribe import transcribe

logger = logging.getLogger(__name__)

HELP = (
    "🎬 Автомонтаж вертикальных роликов\n\n"
    "1. /new — новый проект\n"
    "2. Пришли озвучку (голосовое, аудио или аудио-файл) и выбери язык\n"
    "3. Пришли исходники: видео и/или фото (можно альбомом и файлами)\n"
    "4. Нажми «🎬 Собрать», проверь распознанный текст — и получишь готовый ролик\n\n"
    "Если озвучка лежит в видео — пришли его с подписью «озвучка».\n\n"
    "Настройки (один раз):\n"
    "/setlogo — прислать лого PNG (файлом, чтобы сохранилась прозрачность)\n"
    "/setmusic — прислать фоновую музыку (ставится на −25 dB)"
)

LANGS = {"ru": "🇷🇺 Русский", "uz": "🇺🇿 Oʻzbekcha"}
VOICE_CAPTIONS = ("озвуч", "ovoz", "voice")


@dataclass
class Job:
    dir: Path
    voice: Path | None = None
    voice_asr: Path | None = None
    voice_duration: float = 0.0
    lang: str | None = None
    sources: list[Path] = field(default_factory=list)
    video_seconds: float = 0.0
    photos: int = 0
    words: list[Word] | None = None
    summary_msg: int | None = None
    awaiting_edit: bool = False
    seed: int = 0


jobs: dict[int, Job] = {}
awaiting_asset: dict[int, str] = {}  # "logo" | "music"
user_locks: dict[int, asyncio.Lock] = {}
render_lock = asyncio.Lock()  # VPS слабый и делится с новостным ботом — рендерим строго по одному

config.DATA_DIR.mkdir(parents=True, exist_ok=True)  # Telethon открывает файл сессии сразу при создании клиента
client = TelegramClient(str(config.DATA_DIR / "montage_bot"), config.TELEGRAM_API_ID, config.TELEGRAM_API_HASH)


def _allowed(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


def _lock(user_id: int) -> asyncio.Lock:
    return user_locks.setdefault(user_id, asyncio.Lock())


def _new_job(user_id: int) -> Job:
    old = jobs.pop(user_id, None)
    if old:
        shutil.rmtree(old.dir, ignore_errors=True)
    job_dir = config.WORK_DIR / f"{user_id}_{int(time.time())}"
    (job_dir / "src").mkdir(parents=True, exist_ok=True)
    job = Job(job_dir, seed=random.randrange(10**9))
    jobs[user_id] = job
    return job


def _fmt(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 60}:{s % 60:02d}" if s >= 60 else f"{s} сек"


def _summary(job: Job) -> tuple[str, list | None]:
    if job.voice:
        lang = f" ({LANGS[job.lang]})" if job.lang else " — ⚠️ выбери язык ниже"
        voice = f"🎙 Озвучка: {_fmt(job.voice_duration)}{lang}"
    else:
        voice = "🎙 Озвучки нет — пришли голосовое или аудио"
    videos = len(job.sources) - job.photos
    material = f"🎞 Видео: {videos} ({_fmt(job.video_seconds)}) · 🖼 Фото: {job.photos}" if job.sources else "🎞 Исходников пока нет"
    assets = (
        f"Лого: {'✅' if config.LOGO_PATH.exists() else '⚠️ нет (/setlogo)'} · "
        f"Музыка: {'✅' if config.MUSIC_PATH.exists() else '⚠️ нет (/setmusic)'}"
    )
    text = f"📦 Проект\n{voice}\n{material}\n{assets}"

    buttons = []
    if job.voice and not job.lang:
        buttons.append([Button.inline(label, f"lang:{code}".encode()) for code, label in LANGS.items()])
    if job.voice and job.lang and job.sources:
        buttons.append([Button.inline("🎬 Собрать", b"build")])
    return text, buttons or None


async def _refresh_summary(chat_id: int, job: Job) -> None:
    """Сводка всегда последним сообщением — чтобы кнопка была под рукой, а не уезжала вверх."""
    if job.summary_msg:
        try:
            await client.delete_messages(chat_id, job.summary_msg)
        except Exception:
            pass
    text, buttons = _summary(job)
    msg = await client.send_message(chat_id, text, buttons=buttons)
    job.summary_msg = msg.id


def _media_kind(msg) -> str | None:
    if msg.voice or msg.audio:
        return "audio"
    if msg.photo:
        return "photo"
    if msg.video or msg.video_note or msg.gif:
        return "video"
    mime = (msg.file.mime_type or "") if msg.file else ""
    for prefix in ("audio", "video", "image"):
        if mime.startswith(prefix):
            return "photo" if prefix == "image" else prefix
    return None


async def _save_voice(job: Job, downloaded: Path) -> None:
    job.voice = job.dir / "voice.wav"
    job.voice_asr = job.dir / "voice_asr.mp3"
    await run("ffmpeg", "-y", "-v", "error", "-i", str(downloaded), "-vn", "-ac", "2", "-ar", "48000",
              str(job.voice), capture=False)
    # Для распознавания — маленький моно-mp3: у Groq лимит на размер файла.
    await run("ffmpeg", "-y", "-v", "error", "-i", str(downloaded), "-vn", "-ac", "1", "-ar", "16000",
              "-b:a", "64k", str(job.voice_asr), capture=False)
    job.voice_duration = await media_duration(job.voice)
    job.words = None
    downloaded.unlink(missing_ok=True)


async def _save_asset(event, kind: str, media: str | None) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = Path(await event.message.download_media(file=str(config.DATA_DIR / f"incoming_{kind}")))
    try:
        if kind == "logo":
            if media != "photo":
                await event.reply("Пришли картинку PNG (лучше файлом).")
                return
            logo = Image.open(tmp).convert("RGBA")
            # Обрезаем прозрачные поля вокруг — ширина лого в настройках относится к самому знаку.
            bbox = logo.getchannel("A").point(lambda a: 255 if a > 10 else 0).getbbox()
            (logo.crop(bbox) if bbox else logo).save(config.LOGO_PATH)
            note = "" if event.message.document else (
                "\n⚠️ Пришло как фото — Telegram сжимает фото и убирает прозрачность. "
                "Если у лого появился фон, пришли PNG как файл: /setlogo")
            await event.reply(f"✅ Лого сохранено{note}")
        else:
            if media not in ("audio", "video"):
                await event.reply("Пришли аудио-файл или голосовое.")
                return
            await run("ffmpeg", "-y", "-v", "error", "-i", str(tmp), "-vn", "-c:a", "aac", "-b:a", "160k",
                      str(config.MUSIC_PATH), capture=False)
            await event.reply(f"✅ Фоновая музыка сохранена (будет на {config.MUSIC_VOLUME_DB:g} dB)")
    finally:
        tmp.unlink(missing_ok=True)
        awaiting_asset.pop(event.sender_id, None)


def _transcript_view(words: list[Word]) -> tuple[str, list]:
    text = " ".join(w.text for w in words)
    if len(text) > 3500:
        text = text[:3500] + "…"
    phrases = len(chunk_words(words))
    msg = f"📝 Распознанный текст — проверь:\n\n{text}\n\nСубтитров: {phrases} фраз."
    buttons = [[Button.inline("✅ Собрать видео", b"render"), Button.inline("✏️ Исправить текст", b"edit")]]
    return msg, buttons


@client.on(events.NewMessage(func=lambda e: e.is_private))
async def on_message(event):
    user_id = event.sender_id
    if not _allowed(user_id):
        await event.reply("Нет доступа.")
        return
    text = (event.raw_text or "").strip()
    msg = event.message

    if text.startswith("/"):
        cmd = text.split()[0].split("@")[0].lower()
        if cmd in ("/start", "/help"):
            await event.reply(HELP)
        elif cmd == "/new":
            async with _lock(user_id):
                job = _new_job(user_id)
                await event.reply("🆕 Новый проект. Пришли озвучку и исходники.")
                await _refresh_summary(event.chat_id, job)
        elif cmd in ("/setlogo", "/setmusic"):
            awaiting_asset[user_id] = "logo" if cmd == "/setlogo" else "music"
            await event.reply("Пришли PNG-лого файлом." if cmd == "/setlogo" else "Пришли трек фоновой музыки.")
        return

    media = _media_kind(msg) if msg.media else None

    if user_id in awaiting_asset:
        await _save_asset(event, awaiting_asset[user_id], media)
        return

    async with _lock(user_id):
        job = jobs.get(user_id)

        if not media:
            if job and job.awaiting_edit and text and job.words:
                job.words = align_corrected_text(job.words, text)
                job.awaiting_edit = False
                view, buttons = _transcript_view(job.words)
                await event.reply(view, buttons=buttons)
            else:
                await event.reply("Пришли озвучку или исходники. Помощь — /help")
            return

        job = job or _new_job(user_id)
        caption = (msg.message or "").lower()
        is_voice = media == "audio" or (media == "video" and any(k in caption for k in VOICE_CAPTIONS))

        if is_voice:
            status = await event.reply("⏳ Загружаю озвучку…")
            path = Path(await msg.download_media(file=str(job.dir / "voice_in")))
            replaced = job.voice is not None
            await _save_voice(job, path)
            await status.edit(f"✅ Озвучка {'заменена' if replaced else 'получена'}: {_fmt(job.voice_duration)}")
        elif media in ("video", "photo"):
            idx = len(job.sources)
            ext = (msg.file.ext if msg.file else None) or (".jpg" if media == "photo" else ".mp4")
            path = Path(await msg.download_media(file=str(job.dir / "src" / f"{idx:03d}{ext}")))
            job.sources.append(path)
            if media == "photo":
                job.photos += 1
            else:
                job.video_seconds += await media_duration(path)
        else:
            await event.reply("Не понял, что это за файл. Нужны аудио, видео или фото.")
            return
        await _refresh_summary(event.chat_id, job)


@client.on(events.CallbackQuery)
async def on_callback(event):
    user_id = event.sender_id
    if not _allowed(user_id):
        await event.answer("Нет доступа.", alert=True)
        return
    data = event.data.decode()
    job = jobs.get(user_id)
    if not job:
        await event.answer("Проект не найден — начни заново: /new", alert=True)
        return

    if data.startswith("lang:"):
        job.lang = data.split(":", 1)[1]
        job.words = None
        await event.answer(LANGS[job.lang])
        async with _lock(user_id):
            await _refresh_summary(event.chat_id, job)

    elif data == "build":
        if not (job.voice and job.lang and job.sources):
            await event.answer("Нужны озвучка, язык и хотя бы один исходник.", alert=True)
            return
        await event.answer()
        status = await client.send_message(event.chat_id, "🎧 Распознаю речь…")
        try:
            job.words = await transcribe(job.voice_asr, job.lang, config.GROQ_API_KEY)
        except Exception as e:
            logger.exception("Transcription failed")
            await status.edit(f"⚠️ Не получилось распознать речь: {e}")
            return
        if not job.words:
            await status.edit("⚠️ В озвучке не распознано ни одного слова.")
            return
        view, buttons = _transcript_view(job.words)
        await status.edit(view, buttons=buttons)

    elif data == "edit":
        job.awaiting_edit = True
        await event.answer()
        await client.send_message(
            event.chat_id,
            "Пришли исправленный текст целиком одним сообщением — тайминги подстрою сам.",
        )

    elif data in ("render", "again"):
        if not job.words:
            await event.answer("Сначала нажми «🎬 Собрать».", alert=True)
            return
        if data == "again":
            job.seed = random.randrange(10**9)
        await event.answer()
        asyncio.create_task(_render(event.chat_id, job))


async def _render(chat_id: int, job: Job) -> None:
    status = await client.send_message(chat_id, "⏳ В очереди…" if render_lock.locked() else "🔎 Анализирую исходники…")
    async with render_lock:
        try:
            await status.edit("🔎 Анализирую исходники…")
            sources = [await probe(p) for p in job.sources]
            rng = random.Random(job.seed)
            cuts = build_cuts(job.voice_duration, [w.start for w in job.words], rng)
            shots = plan_shots(cuts, sources, rng)

            last_edit = 0.0

            async def progress(done: int, total: int) -> None:
                nonlocal last_edit
                if time.time() - last_edit > 2 or done == total:
                    last_edit = time.time()
                    await status.edit(f"✂️ Нарезка: {done}/{total}" + ("\n🎬 Финальная сборка…" if done == total else ""))

            out = await render_video(job.dir, shots, chunk_words(job.words), job.voice, job.voice_duration, progress)
            await status.edit("📤 Отправляю…")
            await client.send_file(
                chat_id,
                str(out),
                caption=f"✅ Готово: {_fmt(job.voice_duration)}, {len(shots)} склеек",
                supports_streaming=True,
                attributes=[DocumentAttributeVideo(
                    duration=int(round(job.voice_duration)), w=720, h=1280, supports_streaming=True)],
                buttons=[[Button.inline("🔁 Пересобрать (другие кадры)", b"again")]],
            )
            await status.delete()
        except Exception as e:
            logger.exception("Render failed")
            await status.edit(f"⚠️ Ошибка монтажа: {e}")
        finally:
            shutil.rmtree(job.dir / "parts", ignore_errors=True)


def _cleanup_stale_jobs(max_age_hours: float = 24) -> None:
    if not config.WORK_DIR.exists():
        return
    cutoff = time.time() - max_age_hours * 3600
    for d in config.WORK_DIR.iterdir():
        if d.is_dir() and d.stat().st_mtime < cutoff:
            shutil.rmtree(d, ignore_errors=True)


async def main():
    logging.basicConfig(level=logging.INFO)
    if not config.ADMIN_IDS:
        logger.warning("MONTAGE_ADMIN_IDS/ADMIN_IDS пусты — бот никому не будет отвечать")
    config.WORK_DIR.mkdir(parents=True, exist_ok=True)
    _cleanup_stale_jobs()
    await client.start(bot_token=config.MONTAGE_BOT_TOKEN)
    me = await client.get_me()
    logger.info("Montage bot @%s запущен", me.username)
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())

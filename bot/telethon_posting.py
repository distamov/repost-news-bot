import io
import logging

from aiogram import Bot

from . import config
from .posting import send_post
from .storage import MediaItem

logger = logging.getLogger(__name__)

CAPTION_LIMIT = 1024


async def _to_bytes(item: MediaItem, bot: Bot) -> bytes:
    """Приводит источник медиа к байтам — Telethon (в отличие от Bot API)
    не умеет работать с Bot-API file_id и не скачивает произвольные URL
    сам, поэтому и то и другое нормализуем заранее."""
    if isinstance(item.data, bytes):
        return item.data
    if item.data.startswith("http://") or item.data.startswith("https://"):
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(item.data)
            response.raise_for_status()
            return response.content
    # иначе это Bot API file_id (своя загрузка админом, или фото из
    # оригинального поста, полученного через /rewrite ответом на сообщение)
    buf = await bot.download(item.data)
    return buf.read()


def _as_named_file(item: MediaItem, data: bytes):
    """Telethon определяет фото/видео по расширению имени файла — голые
    байты без имени он шлёт как безымянный документ, а не как фото/видео."""
    named = io.BytesIO(data)
    named.name = "photo.jpg" if item.kind == "photo" else "video.mp4"
    return named


async def _send_via_telethon(client, bot: Bot, chat_id, text: str, media: list[MediaItem]):
    if not media:
        await client.send_message(chat_id, text, parse_mode="html", link_preview=False)
        return

    files = [_as_named_file(item, await _to_bytes(item, bot)) for item in media]
    caption = text if len(text) <= CAPTION_LIMIT else None
    parse_mode = "html" if caption else None

    if len(files) == 1:
        await client.send_file(chat_id, files[0], caption=caption, parse_mode=parse_mode)
    else:
        await client.send_file(chat_id, files, caption=caption, parse_mode=parse_mode)

    if caption is None:
        await client.send_message(chat_id, text, parse_mode="html", link_preview=False)


async def publish(bot: Bot, telethon_client, chat_id, text: str, media: list[MediaItem] | None = None):
    """Публикует финальный пост в канал. Если включён TELETHON_PUBLISH и
    Telethon-аккаунт доступен — публикует через него (Bot API не умеет
    слать анимированные премиум-эмодзи в каналы вообще, а обычный
    Premium-аккаунт может). При любой ошибке (нет Premium, не админ,
    аккаунт разлогинен и т.п.) или если это выключено — публикует как
    раньше, через Bot API."""
    media = media or []
    if config.TELETHON_PUBLISH and telethon_client:
        try:
            await _send_via_telethon(telethon_client, bot, chat_id, text, media)
            return
        except Exception:
            logger.exception(
                "Публикация через Telethon не удалась, публикую через Bot API"
            )
    await send_post(bot, chat_id, text, media=media)

import asyncio
import logging
import time

from aiogram import Bot

from .posting import send_post
from .scheduled_store import ScheduledStore

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 30


async def run_scheduler(bot: Bot, store: ScheduledStore):
    while True:
        for post in store.due(time.time()):
            try:
                media = store.load_media(post)
                await send_post(bot, post.target_chat_id, post.text, media=media)
                if post.moderation_chat_id:
                    try:
                        await bot.send_message(
                            post.moderation_chat_id, "✅ Отложенный пост опубликован в канал."
                        )
                    except Exception:
                        logger.exception("Не удалось уведомить о публикации отложенного поста")
            except Exception:
                logger.exception("Не удалось опубликовать отложенный пост %s", post.id)
                if post.moderation_chat_id:
                    try:
                        await bot.send_message(
                            post.moderation_chat_id,
                            f"⚠️ Не удалось опубликовать отложенный пост (id {post.id}). "
                            "Проверь, что бот всё ещё админ в этом канале.",
                        )
                    except Exception:
                        logger.exception("Не удалось отправить алерт про отложенный пост")
            finally:
                store.remove(post.id)

        await asyncio.sleep(CHECK_INTERVAL)

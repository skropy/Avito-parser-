"""Telegram-бот: уведомления, кнопки, команды. Отвечает только владельцу (chat_id из .env)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import BotCommand, CallbackQuery, FSInputFile, InputMediaPhoto, Message
from loguru import logger

from bot.config import Config
from bot.telegram import keyboards
from bot.textutil import fmt_rub

if TYPE_CHECKING:
    from bot.scheduler import App

HELP = (
    "<b>Бот скупки iPhone</b>\n\n"
    "/status — состояние, отправлено сегодня\n"
    "/pause, /resume — пауза всего бота\n"
    "/autowrite_off, /autowrite_on — выключить/включить только автописьма\n"
    "/stats — статистика за сегодня и 7 дней\n"
    "/deals — диалоги «согласен» и «торг»\n"
    "/reload — перечитать таблицу цен и config.yaml\n"
    "/cancel — отменить ввод текста\n\n"
    "Чтобы ответить продавцу — нажмите «Ответить продавцу» или сделайте reply (свайп) "
    "на любое уведомление по объявлению и напишите текст."
)


class TelegramUI:
    def __init__(self, cfg: Config, app: "App") -> None:
        self.cfg = cfg
        self.app = app
        self.chat_id = cfg.telegram_chat_id
        self.bot = Bot(
            token=cfg.telegram_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
        )
        self.dp = Dispatcher()
        self.awaiting: str | None = None  # listing_id, для которого ждём текст
        self._setup()

    # ------------------------------------------------------------ отправка
    async def send(self, text: str, kb=None, reply_to: int | None = None) -> list[int]:
        try:
            msg = await self.bot.send_message(self.chat_id, text[:4000], reply_markup=kb,
                                              reply_to_message_id=reply_to)
            return [msg.message_id]
        except Exception as e:
            logger.error("Telegram: не удалось отправить сообщение: {}", e)
            return []

    async def send_card(self, text: str, kb, photos: list[str] | None = None) -> list[int]:
        """Альбом до 3 фото + текст с кнопками следующим сообщением."""
        ids: list[int] = []
        photos = [p for p in (photos or []) if p][:3]
        if photos:
            try:
                msgs = await self.bot.send_media_group(self.chat_id, [InputMediaPhoto(media=p) for p in photos])
                ids += [m.message_id for m in msgs]
            except Exception as e:
                logger.warning("Telegram: фото не отправились ({}), шлю только текст", e)
        ids += await self.send(text, kb)
        return ids

    async def send_file_photo(self, path, caption: str) -> None:
        try:
            await self.bot.send_photo(self.chat_id, FSInputFile(str(path)), caption=caption[:1000])
        except Exception as e:
            logger.warning("Telegram: не удалось отправить скриншот: {}", e)
            await self.send(caption)

    # ------------------------------------------------------------- запуск
    async def run(self) -> None:
        await self.bot.set_my_commands([
            BotCommand(command="status", description="Состояние бота"),
            BotCommand(command="stats", description="Статистика"),
            BotCommand(command="deals", description="Согласия и торг"),
            BotCommand(command="pause", description="Пауза"),
            BotCommand(command="resume", description="Продолжить"),
            BotCommand(command="autowrite_off", description="Выключить автописьма"),
            BotCommand(command="autowrite_on", description="Включить автописьма"),
            BotCommand(command="reload", description="Перечитать таблицу и настройки"),
        ])
        await self.dp.start_polling(self.bot, handle_signals=False)

    async def stop(self) -> None:
        try:
            await self.dp.stop_polling()
        except Exception:
            pass
        await self.bot.session.close()

    # ------------------------------------------------------------ хэндлеры
    def _setup(self) -> None:
        r = Router()
        r.message.filter(F.chat.id == self.chat_id)
        r.callback_query.filter(F.message.chat.id == self.chat_id)
        app = self.app

        @r.message(Command("start", "help"))
        async def _help(m: Message):
            await m.answer(HELP)

        @r.message(Command("status"))
        async def _status(m: Message):
            await m.answer(await app.status_text())

        @r.message(Command("pause"))
        async def _pause(m: Message):
            app.set_manual_pause(True)
            await m.answer("⏸ Бот на паузе. Продолжить — /resume")

        @r.message(Command("resume"))
        async def _resume(m: Message):
            app.set_manual_pause(False)
            await m.answer("▶️ Работаю дальше")

        @r.message(Command("autowrite_off"))
        async def _aw_off(m: Message):
            await app.set_autowrite(False)
            await m.answer("🔕 Автописьма выключены. Уведомления продолжат приходить.")

        @r.message(Command("autowrite_on"))
        async def _aw_on(m: Message):
            await app.set_autowrite(True)
            await m.answer("✅ Автописьма включены.")

        @r.message(Command("stats"))
        async def _stats(m: Message):
            await m.answer(await app.stats_text())

        @r.message(Command("deals"))
        async def _deals(m: Message):
            await m.answer(await app.deals_text())

        @r.message(Command("reload"))
        async def _reload(m: Message):
            await m.answer(await app.reload())

        @r.message(Command("cancel"))
        async def _cancel(m: Message):
            self.awaiting = None
            await m.answer("Отменено.")

        @r.callback_query(F.data.startswith("r:"))
        async def _reply_btn(c: CallbackQuery):
            self.awaiting = c.data[2:]
            await c.answer()
            await c.message.answer("✍️ Напишите текст для продавца следующим сообщением (или /cancel).",
                                   reply_markup=keyboards.cancel())

        @r.callback_query(F.data.startswith("w:"))
        async def _write_btn(c: CallbackQuery):
            listing_id = c.data[2:]
            listing = await app.db.get_listing(listing_id)
            await c.answer()
            if not listing:
                await c.message.answer("Объявление не найдено в базе.")
                return
            if await app.db.get_dialog(listing_id):
                await c.message.answer("Этому объявлению уже писали — используйте «Ответить продавцу».",
                                       reply_markup=keyboards.dialog(listing_id, None, listing["url"]))
                return
            await c.message.answer(
                f"Отправить шаблон с предложением {fmt_rub(listing.get('offer'))} или свой текст?",
                reply_markup=keyboards.write_choice(listing_id, fmt_rub(listing.get("offer"))),
            )

        @r.callback_query(F.data.startswith("t:"))
        async def _template_btn(c: CallbackQuery):
            await c.answer()
            await c.message.edit_reply_markup(reply_markup=None)
            await c.message.answer(await app.enqueue_manual(c.data[2:], None))

        @r.callback_query(F.data.startswith("c:"))
        async def _custom_btn(c: CallbackQuery):
            self.awaiting = c.data[2:]
            await c.answer()
            await c.message.edit_reply_markup(reply_markup=None)
            await c.message.answer("✍️ Напишите свой текст для продавца (или /cancel).")

        @r.callback_query(F.data.startswith("i:"))
        async def _ignore_btn(c: CallbackQuery):
            await c.answer("Скрыто")
            try:
                await c.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass

        @r.callback_query(F.data == "x")
        async def _cancel_btn(c: CallbackQuery):
            self.awaiting = None
            await c.answer("Отменено")
            try:
                await c.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass

        @r.callback_query(F.data == "resume")
        async def _resume_btn(c: CallbackQuery):
            await c.answer()
            text = await app.request_resume()
            if text:
                await c.message.answer(text)

        @r.message(F.text)
        async def _text(m: Message):
            listing_id = None
            if m.reply_to_message:
                listing_id = await app.db.listing_by_tg(m.reply_to_message.message_id)
                if not listing_id:
                    await m.answer("Не понял, к какому объявлению этот ответ. Сделайте reply на карточку объявления.")
                    return
            elif self.awaiting:
                listing_id = self.awaiting
            if not listing_id:
                await m.answer("Чтобы написать продавцу, нажмите «Ответить продавцу» под уведомлением "
                               "или сделайте reply на него. Команды — /help")
                return
            self.awaiting = None
            await m.answer(await app.enqueue_manual(listing_id, m.text))

        self.dp.include_router(r)

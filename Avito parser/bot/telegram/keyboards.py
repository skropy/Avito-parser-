"""Inline-кнопки под уведомлениями."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Kb


def written(listing_id: str, url: str) -> Kb:
    return Kb(inline_keyboard=[[
        Btn(text="Открыть на Авито", url=url),
        Btn(text="Ответить продавцу", callback_data=f"r:{listing_id}"),
    ]])


def watch(listing_id: str, url: str) -> Kb:
    return Kb(inline_keyboard=[
        [Btn(text="Написать продавцу", callback_data=f"w:{listing_id}")],
        [Btn(text="Открыть на Авито", url=url), Btn(text="Игнор", callback_data=f"i:{listing_id}")],
    ])


def write_choice(listing_id: str, offer_label: str) -> Kb:
    return Kb(inline_keyboard=[
        [Btn(text=f"Шаблон ({offer_label})", callback_data=f"t:{listing_id}"),
         Btn(text="Свой текст", callback_data=f"c:{listing_id}")],
        [Btn(text="Отмена", callback_data="x")],
    ])


def dialog(listing_id: str, chat_url: str | None, listing_url: str) -> Kb:
    row = [Btn(text="Ответить продавцу", callback_data=f"r:{listing_id}")]
    row.append(Btn(text="Открыть чат на Авито", url=chat_url) if chat_url
               else Btn(text="Открыть на Авито", url=listing_url))
    return Kb(inline_keyboard=[row])


def resume() -> Kb:
    return Kb(inline_keyboard=[[Btn(text="Продолжить", callback_data="resume")]])


def cancel() -> Kb:
    return Kb(inline_keyboard=[[Btn(text="Отмена", callback_data="x")]])

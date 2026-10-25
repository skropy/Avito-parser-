"""ВСЕ CSS-селекторы Авито в одном месте.

Авито периодически меняет вёрстку. Если бот пишет «Похоже, Авито изменил
вёрстку» или в карточках пропали данные — правьте только этот файл.
Для каждого поля указан список вариантов: используется первый найденный.
Узнать актуальные селекторы помогает: python scripts/check_avito.py
"""

BASE_URL = "https://www.avito.ru"
MESSENGER_URL = "https://www.avito.ru/profile/messenger"

# ------------------------------------------------- капча / блокировка / вход
CAPTCHA = [
    ".firewall-container",
    ".js-firewall-form",
    ".h-captcha",
    "#h-captcha",
    "#geetest_captcha",
    ".form-captcha",
    "iframe[src*='captcha']",
]
BLOCK_TITLE_WORDS = [
    "доступ ограничен",
    "доступ временно ограничен",
    "проблема с ip",
    "вы не робот",
    "подтвердите, что вы",
]
# признаки того, что Авито просит войти
LOGIN_URL_PARTS = ["/login", "#login", "/auth"]
LOGIN_FORM = [
    "[data-marker='login-form']",
    "[data-marker='auth-app']",
    "input[type='password']",
]
# кнопка «Вход и регистрация» в шапке — значит, мы не залогинены
LOGGED_OUT = [
    "[data-marker='header/login-button']",
]

# -------------------------------------------------------------- выдача
SEARCH_CONTAINER = ["[data-marker='catalog-serp']", "[class*='items-items']"]
SEARCH_ITEM = "[data-marker='item']"
SEARCH_ITEM_LINK = ["a[data-marker='item-title']", "a[itemprop='url']", "a[href*='_']"]
SEARCH_ITEM_TITLE = ["[data-marker='item-title']", "[itemprop='name']", "h3"]
SEARCH_ITEM_PRICE_META = "meta[itemprop='price']"
SEARCH_ITEM_PRICE = ["[data-marker='item-price']", "[itemprop='price']"]
SEARCH_ITEM_DATE = ["[data-marker='item-date']"]

# --------------------------------------------------- карточка объявления
ITEM_TITLE = ["[data-marker='item-view/title-info']", "h1[itemprop='name']", "h1"]
ITEM_PRICE = ["[data-marker='item-view/item-price']", "[itemprop='price']"]
ITEM_DESCRIPTION = ["[data-marker='item-view/item-description']", "[itemprop='description']"]
ITEM_PHOTOS = [
    "[data-marker='image-frame/image-wrapper'] img",
    "[data-marker='image-preview/item'] img",
    "[data-marker*='image'] img",
]
ITEM_ADDRESS = ["[data-marker='item-view/item-address']", "[itemprop='address']",
                "[class*='item-address']"]
ITEM_METRO = ["[class*='georeferences'] span", "[class*='metro'] span", "[class*='geo-root'] span"]
ITEM_ID = ["[data-marker='item-view/item-id']"]
ITEM_DATE = ["[data-marker='item-view/item-date']"]

SELLER_BLOCK = ["[data-marker='seller-info']", "[data-marker='item-view/seller-info']",
                "[class*='seller-info']", "[data-marker*='seller']"]
SELLER_NAME = ["[data-marker='seller-info/name']", "[data-marker='seller-link/link']"]
SELLER_LABEL = ["[data-marker='seller-info/label']", "[data-marker='seller-info/type']"]
SELLER_LINK = ["[data-marker='seller-link/link']", "a[href*='/user/']", "a[href*='/brands/']"]
SELLER_RATING = ["[data-marker='seller-info/score']", "[data-marker='seller-rating/score']"]
SELLER_REVIEWS = ["[data-marker='rating-caption/rating']", "[data-marker='seller-info/summary']",
                  "[data-marker='seller-rating/summary']"]

# Кнопка «Написать» на странице объявления (можно Playwright-синтаксис :has-text)
WRITE_BUTTON = [
    "[data-marker='messenger-button/button']",
    "button[data-marker*='messenger']",
    "button:has-text('Написать')",
    "a:has-text('Написать')",
]

# ------------------------------------------------------------ мессенджер
CHAT_INPUT = [
    "[data-marker='reply/input']",
    "textarea[data-marker*='input']",
    "textarea[placeholder*='сообщение']",
    "textarea",
    "[contenteditable='true']",
]
CHAT_SEND = [
    "[data-marker='reply/send']",
    "button[data-marker*='send']",
    "button[aria-label*='Отправ']",
]
CHAT_LINK = ["a[href*='/profile/messenger/channel/']", "a[href*='/messenger/channel/']"]
CHANNEL_ITEM = ["[data-marker='channels/channelLink']", "a[href*='/profile/messenger/channel/']"]
MESSAGE_ITEM = [
    "[data-marker='message']",
    "[data-marker*='message/']",
    "[data-marker*='messageItem']",
    "[class*='message-base']",
]
MESSAGE_TEXT = ["[data-marker='messageText']", "[data-marker*='text']", "[class*='text']"]
# Служебные сообщения Авито в чате — не пересылаются как ответ продавца
SYSTEM_MESSAGE_WORDS = [
    "будьте осторожны",
    "не переходите по ссылкам",
    "мошенник",
    "сейчас не в сети",
    "был в сети",
    "была в сети",
    "вы начали",
    "сообщение удалено",
]

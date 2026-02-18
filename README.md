# simple-russian-tg-shop-bot-
the simplest of simple shop bot with CryptoBot pay

Telegram Shop Bot

GitHub: https://github.com/astsh247/simple-russian-tg-shop-bot

---

Русский

Telegram бот для продажи цифровых товаров с оплатой через CryptoBot (USDT).

Требования

· Python 3.8+
· Telegram Bot Token (от @BotFather)
· CryptoBot API Token (от @CryptoBot)

Установка

```bash
git clone https://github.com/astsh247/simple-russian-tg-shop-bot.git
cd simple-russian-tg-shop-bot
pip install -r requirements.txt
```

Настройка

В файле main.py укажите свои данные:

```python
BOT_TOKEN = "YOUR_BOT_TOKEN"
CRYPTOBOT_API_TOKEN = "YOUR_CRYPTOBOT_TOKEN"
ADMIN_ID = 123456789  # Ваш Telegram ID
CHANNEL_USERNAME = "@your_channel"  # Канал для подписки
```

Запуск

```bash
python main.py
```

Возможности

· 🛍️ Каталог товаров по категориям
· 💳 Оплата USDT через CryptoBot (+3% комиссия автоматически)
· ⚙️ Гибкие коэффициенты цен (Stars, Steam, курс USDT)
· 📊 Админ-панель для управления товарами
· 🚫 Система банов пользователей
· 📢 Рассылка сообщений
· 🔍 Проверка подписки на канал

Команды

Пользователи:

· /start - приветствие
· /price - каталог товаров
· /help - помощь
· /support - поддержка

Админ:

· /admin - панель управления
· /ban @user [причина] - заблокировать
· /unban @user - разблокировать
· /banned - список банов
· /broadcast - рассылка

Категории по умолчанию

· Telegram Stars/Premium
· Пополнение Steam
· Прокси
· Подписки
· Физы (аккаунты)

База данных

· accounts.sqlite3 - все данные магазина
· Автоматически создается при первом запуске

Лицензия

MIT

---

English

Telegram bot for selling digital goods with CryptoBot (USDT) payment.

Requirements

· Python 3.8+
· Telegram Bot Token (from @BotFather)
· CryptoBot API Token (from @CryptoBot)

Installation

```bash
git clone https://github.com/astsh247/simple-russian-tg-shop-bot.git
cd simple-russian-tg-shop-bot
pip install -r requirements.txt
```

Configuration

Edit main.py with your data:

```python
BOT_TOKEN = "YOUR_BOT_TOKEN"
CRYPTOBOT_API_TOKEN = "YOUR_CRYPTOBOT_TOKEN"
ADMIN_ID = 123456789  # Your Telegram ID
CHANNEL_USERNAME = "@your_channel"  # Channel for subscription
```

Run

```bash
python main.py
```

Features

· 🛍️ Product catalog by categories
· 💳 USDT payment via CryptoBot (+3% fee automatically added)
· ⚙️ Flexible price coefficients (Stars, Steam, USDT rate)
· 📊 Admin panel for product management
· 🚫 User ban system
· 📢 Broadcast messages
· 🔍 Channel subscription check

Commands

Users:

· /start - welcome message
· /price - view catalog
· /help - help
· /support - support

Admin:

· /admin - admin panel
· /ban @user [reason] - ban user
· /unban @user - unban user
· /banned - banned list
· /broadcast - send broadcast

Default Categories

· Telegram Stars/Premium
· Steam Wallet Top-up
· Proxies
· Subscriptions
· Accounts (with phone numbers)

Database

· accounts.sqlite3 - all shop data
· Automatically created on first run

License

MIT

---

🔗 GitHub: https://github.com/astsh247/simple-russian-tg-shop-bot

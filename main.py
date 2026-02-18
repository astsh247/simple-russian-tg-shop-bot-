#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import sqlite3
import requests
import json
import os
import sys
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
import asyncio

# === КОНФИГУРАЦИЯ (ЗАПОЛНИТЕ СВОИМИ ДАННЫМИ) ===
BOT_TOKEN = "YOUR_BOT_TOKEN"
CRYPTOBOT_API_TOKEN = "YOUR_CRYPTOBOT_TOKEN"
CRYPTOBOT_API_URL = "https://pay.crypt.bot/api/"
ADMIN_ID = 123456789  # Ваш Telegram ID
CHANNEL_USERNAME = "@your_channel"

# Коэффициенты по умолчанию (будут храниться в базе)
DEFAULT_STARS_COEFFICIENT = 1.35  # 1.35 для Stars
DEFAULT_STEAM_COEFFICIENT = 1.03  # 3% комиссия для Steam
DEFAULT_EXCHANGE_RATE = 77.5  # Курс USDT к рублю
CRYPTOBOT_FEE = 0.03  # Комиссия CryptoBot 3%

# Путь к базе данных
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "accounts.sqlite3")

# Создаем папку data если её нет
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR, exist_ok=True)
    print(f"📁 Создана папка данных: {DATA_DIR}")

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler(os.path.join(DATA_DIR, 'bot.log'), encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Инициализация базы данных
def init_db():
    try:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                description TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER,
                name TEXT,
                price REAL,
                description TEXT,
                stock INTEGER DEFAULT 10,
                is_active BOOLEAN DEFAULT 1,
                product_type TEXT DEFAULT 'fixed',
                FOREIGN KEY (category_id) REFERENCES categories (id)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id TEXT UNIQUE,
                user_id INTEGER,
                username TEXT,
                first_name TEXT,
                product_id INTEGER,
                product_name TEXT,
                custom_amount REAL,
                price_amount REAL,
                price_with_fee REAL,
                price_currency TEXT DEFAULT 'USD',
                cryptobot_invoice_id TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP,
                paid_at TIMESTAMP NULL,
                FOREIGN KEY (product_id) REFERENCES products (id)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                username TEXT,
                first_name TEXT,
                joined_at TIMESTAMP,
                last_activity TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS banned_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                username TEXT,
                first_name TEXT,
                banned_by INTEGER,
                banned_at TIMESTAMP,
                reason TEXT
            )
        ''')
        
        # НОВАЯ ТАБЛИЦА для коэффициентов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS coefficients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                coefficient_type TEXT UNIQUE,  -- 'stars' или 'steam' или 'exchange_rate'
                value REAL NOT NULL,
                description TEXT,
                updated_at TIMESTAMP
            )
        ''')
        
        # Добавляем категории если их нет - ТОЛЬКО СТАРЫЕ КАТЕГОРИИ
        default_categories = [
            ('Telegram Stars/Premium', 'Покупка Telegram Stars и Premium подписки'),
            ('Пополнение Steam', 'Пополнение игрового баланса Steam'),
            ('Прокси', 'Прокси для анонимного серфинга'),
            ('Подписки', 'Подписки на популярные сервисы'),
            ('Физы', 'Аккаунты с верифицированными номерами')
        ]
        
        for category in default_categories:
            cursor.execute('INSERT OR IGNORE INTO categories (name, description) VALUES (?, ?)', category)
        
        # Получаем ID категорий
        cursor.execute('SELECT id FROM categories WHERE name = ?', ('Telegram Stars/Premium',))
        stars_premium_result = cursor.fetchone()
        if stars_premium_result:
            stars_premium_id = stars_premium_result[0]
        else:
            cursor.execute('SELECT id FROM categories WHERE name = ?', ('Telegram Stars/Premium',))
            stars_premium_id = cursor.fetchone()[0]
        
        cursor.execute('SELECT id FROM categories WHERE name = ?', ('Пополнение Steam',))
        steam_result = cursor.fetchone()
        if steam_result:
            steam_id = steam_result[0]
        else:
            cursor.execute('SELECT id FROM categories WHERE name = ?', ('Пополнение Steam',))
            steam_id = cursor.fetchone()[0]
        
        # Проверяем есть ли уже товары
        cursor.execute('SELECT COUNT(*) FROM products')
        product_count = cursor.fetchone()[0]
        
        if product_count == 0:
            # Telegram Premium
            cursor.execute('''
                INSERT OR IGNORE INTO products (category_id, name, price, description, stock, product_type)
                VALUES (?, 'Telegram Premium', 2.5, 'Премиум подписка на 1 месяц', 100, 'fixed')
            ''', (stars_premium_id,))
            
            # Telegram Stars
            cursor.execute('''
                INSERT OR IGNORE INTO products (category_id, name, price, description, stock, product_type)
                VALUES (?, 'Telegram Stars', 0, 'Покупка Telegram Stars (от 50 единиц)', 9999, 'stars')
            ''', (stars_premium_id,))
            
            # Пополнение Steam
            cursor.execute('''
                INSERT OR IGNORE INTO products (category_id, name, price, description, stock, product_type)
                VALUES (?, 'Пополнение Steam', 0, 'Пополнение игрового баланса Steam (от 100₽)', 9999, 'steam')
            ''', (steam_id,))
            
            print("🛍️ Добавлены стартовые товары")
        
        # Инициализируем коэффициенты если их нет
        cursor.execute('SELECT COUNT(*) FROM coefficients')
        coeff_count = cursor.fetchone()[0]
        
        if coeff_count == 0:
            default_coefficients = [
                ('stars', DEFAULT_STARS_COEFFICIENT, 'Коэффициент для Telegram Stars'),
                ('steam', DEFAULT_STEAM_COEFFICIENT, 'Комиссия для Steam (1.03 = 3%)'),
                ('exchange_rate', DEFAULT_EXCHANGE_RATE, 'Курс USDT к рублю')
            ]
            
            for coeff_type, value, description in default_coefficients:
                cursor.execute('''
                    INSERT OR IGNORE INTO coefficients (coefficient_type, value, description, updated_at)
                    VALUES (?, ?, ?, ?)
                ''', (coeff_type, value, description, datetime.now()))
            
            print("⚙️ Инициализированы коэффициенты")
        
        conn.commit()
        conn.close()
        print("✅ База данных успешно инициализирована")
        
    except Exception as e:
        print(f"❌ Ошибка инициализации базы данных: {e}")
        logger.error(f"Ошибка инициализации базы данных: {e}")

# Функции работы с базой данных
def get_db_connection():
    return sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)

def save_user(user_id, username, first_name):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO users (user_id, username, first_name, joined_at, last_activity)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, username, first_name, datetime.now(), datetime.now()))
        conn.commit()
    except Exception as e:
        logger.error(f"Ошибка сохранения пользователя: {e}")
    finally:
        conn.close()

def is_user_banned(user_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM banned_users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        return result is not None
    except Exception as e:
        logger.error(f"Ошибка проверки бана: {e}")
        return False
    finally:
        conn.close()

def get_product_info(product_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT p.id, p.name, p.price, p.description, p.stock, p.product_type, c.name as category_name
            FROM products p
            JOIN categories c ON p.category_id = c.id
            WHERE p.id = ? AND p.is_active = 1
        ''', (product_id,))
        result = cursor.fetchone()
        return result
    except Exception as e:
        logger.error(f"Ошибка получения информации о товаре: {e}")
        return None
    finally:
        conn.close()

def update_product_stock(product_id, change_amount):
    """Обновляет количество товара с проверкой на отрицательное значение"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # Получаем текущее количество
        cursor.execute('SELECT stock FROM products WHERE id = ?', (product_id,))
        result = cursor.fetchone()
        
        if not result:
            return None
            
        current_stock = result[0]
        
        new_stock = current_stock + change_amount
        if new_stock < 0:
            new_stock = 0
            
        cursor.execute('UPDATE products SET stock = ? WHERE id = ?', (new_stock, product_id))
        conn.commit()
        return new_stock
    except Exception as e:
        logger.error(f"Ошибка обновления остатка: {e}")
        return None
    finally:
        conn.close()

def get_all_categories():
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT id, name, description FROM categories ORDER BY id')
        categories = cursor.fetchall()
        return categories
    except Exception as e:
        logger.error(f"Ошибка получения категорий: {e}")
        return []
    finally:
        conn.close()

def get_products_by_category(category_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, name, price, description, stock, product_type 
            FROM products 
            WHERE category_id = ? AND is_active = 1
            ORDER BY id
        ''', (category_id,))
        products = cursor.fetchall()
        return products
    except Exception as e:
        logger.error(f"Ошибка получения товаров категории: {e}")
        return []
    finally:
        conn.close()

# НОВЫЕ ФУНКЦИИ ДЛЯ КОЭФФИЦИЕНТОВ
def get_coefficient(coeff_type):
    """Получает коэффициент из базы данных"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT value FROM coefficients WHERE coefficient_type = ?', (coeff_type,))
        result = cursor.fetchone()
        
        if result:
            return result[0]
        else:
            # Возвращаем значение по умолчанию если нет в базе
            defaults = {
                'stars': DEFAULT_STARS_COEFFICIENT,
                'steam': DEFAULT_STEAM_COEFFICIENT,
                'exchange_rate': DEFAULT_EXCHANGE_RATE
            }
            return defaults.get(coeff_type, 1.0)
    except Exception as e:
        logger.error(f"Ошибка получения коэффициента {coeff_type}: {e}")
        return 1.0
    finally:
        conn.close()

def update_coefficient(coeff_type, value):
    """Обновляет коэффициент в базе данных"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO coefficients (coefficient_type, value, updated_at)
            VALUES (?, ?, ?)
        ''', (coeff_type, value, datetime.now()))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Ошибка обновления коэффициента {coeff_type}: {e}")
        return False
    finally:
        conn.close()

def get_all_coefficients():
    """Получает все коэффициенты"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT coefficient_type, value, description FROM coefficients')
        coefficients = cursor.fetchall()
        
        # Создаем словарь для удобного доступа
        coeff_dict = {}
        for coeff_type, value, description in coefficients:
            coeff_dict[coeff_type] = {
                'value': value,
                'description': description
            }
        return coeff_dict
    except Exception as e:
        logger.error(f"Ошибка получения коэффициентов: {e}")
        return {}
    finally:
        conn.close()

# Проверка подписки
async def check_subscription(application, user_id):
    try:
        try:
            chat = await application.bot.get_chat(CHANNEL_USERNAME)
        except Exception as e:
            logger.error(f"Канал {CHANNEL_USERNAME} не найден: {e}")
            return True
        
        chat_member = await application.bot.get_chat_member(
            chat_id=CHANNEL_USERNAME,
            user_id=user_id
        )
        return chat_member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        return True

# CryptoBot API
class CryptoBotAPI:
    def __init__(self, api_token):
        self.api_token = api_token
        self.base_url = CRYPTOBOT_API_URL
        self.headers = {
            'Crypto-Pay-API-Token': self.api_token,
            'Content-Type': 'application/json'
        }
    
    def create_invoice(self, amount, description, expires_in=900):
        url = f"{self.base_url}createInvoice"
        
        # Добавляем комиссию CryptoBot 3% к сумме
        amount_with_fee = round(amount * (1 + CRYPTOBOT_FEE), 2)
        
        payload = {
            "asset": "USDT",
            "amount": str(amount_with_fee),
            "description": description,
            "expires_in": expires_in,
            "hidden_message": "✨ Спасибо за покупку! Обращайтесь еще!",
            "paid_btn_name": "openBot",
            "paid_btn_url": "https://t.me/your_bot_username",
            "allow_comments": False
        }
        
        try:
            logger.info(f"Создание инвойса: {amount} USDT + комиссия {CRYPTOBOT_FEE*100}% = {amount_with_fee} USDT - {description}")
            response = requests.post(url, json=payload, headers=self.headers, timeout=30)
            
            if response.status_code != 200:
                logger.error(f"HTTP Error {response.status_code}: {response.text}")
                return None
                
            result = response.json()
            logger.info(f"Ответ CryptoBot: {result}")
            
            if result.get('ok'):
                logger.info("✅ Инвойс создан успешно!")
                # Добавляем исходную сумму и сумму с комиссией в результат
                result['result']['original_amount'] = amount
                result['result']['amount_with_fee'] = amount_with_fee
                return result['result']
            else:
                error_msg = result.get('error', {}).get('name', 'Unknown error')
                logger.error(f"❌ CryptoBot API error: {error_msg}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Ошибка создания инвойса: {e}")
            return None

    def check_invoice_status(self, invoice_id):
        try:
            url = f"{self.base_url}getInvoices"
            params = {"invoice_ids": invoice_id}
            
            logger.info(f"Проверка статуса инвойса: {invoice_id}")
            response = requests.get(url, params=params, headers=self.headers, timeout=10)
            result = response.json()
            
            if result.get('ok') and result['result']['items']:
                status = result['result']['items'][0].get('status')
                logger.info(f"Статус инвойса {invoice_id}: {status}")
                return status
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка проверки статуса: {e}")
            return None

cryptobot = CryptoBotAPI(CRYPTOBOT_API_TOKEN)

# Уведомление админу
async def notify_admin(application, order_data, order_type="new"):
    try:
        if order_type == "new":
            message = (
                "🆕 🛒 НОВЫЙ ЗАКАЗ!\n\n"
                f"📦 Товар: {order_data['product_name']}\n"
                f"💰 Сумма: {order_data['price_amount']} USDT\n"
                f"💸 С учетом комиссии: {order_data.get('price_with_fee', order_data['price_amount'])} USDT\n"
                f"👤 Клиент: {order_data['first_name']}\n"
                f"🔗 Username: @{order_data['username'] or 'Нет username'}\n"
                f"🆔 ID клиента: {order_data['user_id']}\n"
                f"📋 Номер заказа: {order_data['invoice_id']}\n"
                f"⏰ Время заказа: {order_data['created_at'].strftime('%Y-%m-%d %H:%M:%S')}"
            )
            if order_data.get('custom_amount'):
                message += f"\n📊 Кастомная сумма: {order_data['custom_amount']}"
        elif order_type == "paid":
            message = (
                "✅ 💳 ЗАКАЗ ОПЛАЧЕН!\n\n"
                f"📦 Товар: {order_data['product_name']}\n"
                f"💰 Сумма: {order_data['price_amount']} USDT\n"
                f"💸 Получено с комиссией: {order_data.get('price_with_fee', order_data['price_amount'])} USDT\n"
                f"👤 Клиент: {order_data['first_name']}\n"
                f"🔗 Username: @{order_data['username'] or 'Нет username'}\n"
                f"🆔 ID клиента: {order_data['user_id']}\n"
                f"📋 Номер заказа: {order_data['invoice_id']}\n"
                f"⏰ Время оплаты: {order_data['paid_at'].strftime('%Y-%m-%d %H:%M:%S')}"
            )
            if order_data.get('custom_amount'):
                message += f"\n📊 Кастомная сумма: {order_data['custom_amount']}"
        
        await application.bot.send_message(chat_id=ADMIN_ID, text=message)
    except Exception as e:
        logger.error(f"❌ Ошибка отправки уведомления админу: {e}")

# Проверка доступа
async def check_access(update: Update, context: ContextTypes.DEFAULT_TYPE, func, *args, **kwargs):
    user_id = update.effective_user.id
    
    if is_user_banned(user_id):
        if update.callback_query:
            await update.callback_query.answer("🚫 Доступ к боту ограничен администратором", show_alert=True)
        else:
            await update.message.reply_text("🚫 Доступ к боту ограничен администратором")
        return
    
    if user_id != ADMIN_ID:
        is_subscribed = await check_subscription(context.application, user_id)
        if not is_subscribed:
            subscription_text = (
                "📢 Чтобы получить доступ к магазину, подпишитесь на наш канал!\n\n"
                f"👉 {CHANNEL_USERNAME}\n\n"
                "После подписки используйте /start"
            )
            keyboard = [[InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if update.callback_query:
                await update.callback_query.message.reply_text(subscription_text, reply_markup=reply_markup)
                await update.callback_query.answer()
            else:
                await update.message.reply_text(subscription_text, reply_markup=reply_markup)
            return
    
    user = update.effective_user
    save_user(user.id, user.username, user.first_name)
    
    return await func(update, context, *args, **kwargs)

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await check_access(update, context, _start)

async def _start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "🎉 Добро пожаловать в магазин!\n\n"
        "✨ У нас вы найдете:\n"
        "• Telegram Stars/Premium\n"
        "• Пополнение Steam\n"
        "• Прокси разных стран\n"
        "• Подписки на сервисы\n"
        "• Аккаунты с номерами\n\n"
        "*Быстро • Надежно • Безопасно*\n\n"
        "*Доступные команды:*\n"
        "/price - 🛍️ Каталог товаров\n"
        "/help - ❓ Помощь и инструкция\n"
        "/support - 💬 Техподдержка"
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

# Команда /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await check_access(update, context, _help_command)

async def _help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🆘 *Помощь по использованию бота:*\n\n"
        "1. Используйте /price для просмотра товаров\n"
        "2. Оплата через CryptoBot (@send)\n"
        "3. Время на оплату - 15 минут\n"
        "4. К сумме добавляется комиссия CryptoBot 3%\n"
        "5. После оплаты нажмите 'Проверить оплату'\n"
        "6. Для получения товара напишите администратору\n\n"
        "*Важно:*\n"
        "• Сохраняйте номер заказа\n"
        "• Проверяйте баланс перед оплатой\n"
        "• Один заказ - одна оплата\n\n"
        "*Поддержка:* обратитесь к администратору"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

# Команда /price - показывает категории
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await check_access(update, context, _price)

async def _price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    categories = get_all_categories()
    
    if not categories:
        await update.message.reply_text("📭 Категории товаров временно недоступны")
        return
    
    text = "*Выберите категорию:*\n\n"
    keyboard = []
    
    # ТОЛЬКО СТАРЫЕ КАТЕГОРИИ (без эмодзи в названиях)
    for cat_id, name, description in categories:
        # Проверяем, что это оригинальная категория
        if name in ['Telegram Stars/Premium', 'Пополнение Steam', 'Прокси', 'Подписки', 'Физы']:
            keyboard.append([InlineKeyboardButton(f"{name}", callback_data=f"cat_{cat_id}")])
    
    if not keyboard:
        await update.message.reply_text("📭 Категории товаров временно недоступны")
        return
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=reply_markup)

# Обработка выбора категории
async def handle_category_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await check_access(update, context, _handle_category_selection)

async def _handle_category_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data.startswith('cat_'):
        category_id = int(data[4:])
        
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT name FROM categories WHERE id = ?', (category_id,))
            category = cursor.fetchone()
            
            if not category:
                await query.edit_message_text("📭 Категория не найдена")
                return
            
            category_name = category[0]
            products = get_products_by_category(category_id)
            
            if not products:
                await query.edit_message_text(f"📦 В категории '{category_name}' пока нет товаров")
                return
            
            text = f"*Товары в категории: {category_name}*\n\n"
            keyboard = []
            
            for product in products:
                product_id, name, price, description, stock, product_type = product
                
                if product_type == 'fixed':
                    stock_emoji = "🟢" if stock > 0 else "🔴"
                    status = f"{stock} шт." if stock > 0 else "Нет в наличии"
                    text += f"• *{name}* - {price}$ {stock_emoji} ({status})\n"
                    if stock > 0:
                        keyboard.append([InlineKeyboardButton(
                            f"{name} - {price}$", 
                            callback_data=f"buy_{product_id}"
                        )])
                elif product_type == 'stars':
                    keyboard.append([InlineKeyboardButton(
                        f"{name} (от 50)", 
                        callback_data=f"buy_{product_id}"
                    )])
                elif product_type == 'steam':
                    keyboard.append([InlineKeyboardButton(
                        f"{name} (от 100₽)", 
                        callback_data=f"buy_{product_id}"
                    )])
            
            if not keyboard:
                text = f"📭 В категории '{category_name}' все товары временно отсутствуют"
            
            keyboard.append([InlineKeyboardButton("⬅️ Назад к категориям", callback_data="back_to_categories")])
            
            reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
            await query.edit_message_text(text, parse_mode='Markdown', reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Ошибка загрузки категории: {e}")
            await query.edit_message_text("❌ Ошибка при загрузке товаров")
        finally:
            conn.close()

# Обработка кнопки "Назад к категориям"
async def handle_back_to_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await check_access(update, context, _handle_back_to_categories)

async def _handle_back_to_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    categories = get_all_categories()
    
    if not categories:
        await query.edit_message_text("📭 Категории товаров временно недоступны")
        return
    
    text = "*Выберите категорию:*\n\n"
    keyboard = []
    
    # ТОЛЬКО СТАРЫЕ КАТЕГОРИИ (без эмодзи в названиях)
    for cat_id, name, description in categories:
        # Проверяем, что это оригинальная категория
        if name in ['Telegram Stars/Premium', 'Пополнение Steam', 'Прокси', 'Подписки', 'Физы']:
            keyboard.append([InlineKeyboardButton(f"{name}", callback_data=f"cat_{cat_id}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=reply_markup)

# Обработка покупки товара
async def handle_product_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await check_access(update, context, _handle_product_selection)

async def _handle_product_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data.startswith('buy_'):
        product_id = int(data[4:])
        product_info = get_product_info(product_id)
        
        if not product_info:
            await query.edit_message_text("📭 Товар не найден или снят с продажи")
            return
        
        product_id, name, price, description, stock, product_type, category_name = product_info
        
        # Проверяем наличие товара ДО создания заказа
        if product_type == 'fixed' and stock <= 0:
            await query.answer("📭 Товар временно отсутствует на складе", show_alert=True)
            return
        
        if product_type == 'fixed':
            context.user_data['selected_product'] = {
                'id': product_id,
                'name': name,
                'price': price,
                'description': description,
                'type': product_type
            }
            await process_payment(query, context.application, context)
        
        elif product_type == 'stars':
            context.user_data['selected_product'] = {
                'id': product_id,
                'name': name,
                'price': price,
                'description': description,
                'type': product_type
            }
            await query.edit_message_text(
                "*Покупка Telegram Stars*\n\n"
                "Введите количество Stars (от 50):\n\n"
                "_Пример: 100, 500, 1000_",
                parse_mode='Markdown'
            )
        
        elif product_type == 'steam':
            context.user_data['selected_product'] = {
                'id': product_id,
                'name': name,
                'price': price,
                'description': description,
                'type': product_type
            }
            await query.edit_message_text(
                "*Пополнение баланса Steam*\n\n"
                "Введите сумму в рублях (от 100₽):\n\n"
                "_Пример: 100, 500, 1000_",
                parse_mode='Markdown'
            )

# Обработка текстовых сообщений для Stars и Steam
async def handle_custom_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != update.effective_user.id:
        return
    
    # Пропускаем сообщения от админа
    if update.message.from_user.id == ADMIN_ID:
        return
    
    if 'selected_product' not in context.user_data:
        return
    
    product = context.user_data['selected_product']
    text = update.message.text.strip()
    
    try:
        if product['type'] == 'stars':
            stars_amount = float(text)
            if stars_amount < 50:
                await update.message.reply_text("⚠️ Минимальное количество Stars: 50")
                return
            
            # ИСПОЛЬЗУЕМ КОЭФФИЦИЕНТЫ ИЗ БАЗЫ
            stars_coeff = get_coefficient('stars')
            exchange_rate = get_coefficient('exchange_rate')
            
            # Формула: количество * коэффициент_звезд / курс
            price_amount = round(stars_amount * stars_coeff / exchange_rate, 2)
            price_with_fee = round(price_amount * (1 + CRYPTOBOT_FEE), 2)
            
            context.user_data['custom_amount'] = stars_amount
            context.user_data['price_amount'] = price_amount
            context.user_data['price_with_fee'] = price_with_fee
            
            # Показываем детали с коэффициентами
            await update.message.reply_text(
                f"*Детали заказа:*\n\n"
                f"Количество Stars: {stars_amount}\n"
                f"Коэффициент: {stars_coeff}\n"
                f"Курс USDT: {exchange_rate} руб\n"
                f"Сумма к оплате: {price_amount} USDT\n"
                f"Комиссия CryptoBot (3%): +{round(price_amount * CRYPTOBOT_FEE, 2)} USDT\n"
                f"*Итого к оплате: {price_with_fee} USDT*\n\n"
                f"_Расчет: {stars_amount} × {stars_coeff} ÷ {exchange_rate} = {price_amount} USDT_\n"
                f"_С учетом комиссии: {price_amount} × 1.03 = {price_with_fee} USDT_\n\n"
                "Перейти к оплате?",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Да, оплатить", callback_data="confirm_custom")],
                    [InlineKeyboardButton("❌ Отмена", callback_data="cancel_custom")]
                ])
            )
        
        elif product['type'] == 'steam':
            rub_amount = float(text)
            if rub_amount < 100:
                await update.message.reply_text("⚠️ Минимальная сумма пополнения: 100₽")
                return
            
            # ИСПОЛЬЗУЕМ КОЭФФИЦИЕНТЫ ИЗ БАЗЫ
            steam_coeff = get_coefficient('steam')
            exchange_rate = get_coefficient('exchange_rate')
            
            # Формула: (сумма * коэффициент_стим) / курс
            price_amount = round((rub_amount * steam_coeff) / exchange_rate, 2)
            price_with_fee = round(price_amount * (1 + CRYPTOBOT_FEE), 2)
            
            context.user_data['custom_amount'] = rub_amount
            context.user_data['price_amount'] = price_amount
            context.user_data['price_with_fee'] = price_with_fee
            
            # Показываем детали с коэффициентами
            steam_percentage = round((steam_coeff - 1) * 100, 1)
            await update.message.reply_text(
                f"*Детали заказа:*\n\n"
                f"Сумма пополнения: {rub_amount}₽\n"
                f"Комиссия: +{steam_percentage}%\n"
                f"Курс USDT: {exchange_rate} руб\n"
                f"Сумма к оплате: {price_amount} USDT\n"
                f"Комиссия CryptoBot (3%): +{round(price_amount * CRYPTOBOT_FEE, 2)} USDT\n"
                f"*Итого к оплате: {price_with_fee} USDT*\n\n"
                f"_Расчет: {rub_amount} × {steam_coeff} ÷ {exchange_rate} = {price_amount} USDT_\n"
                f"_С учетом комиссии: {price_amount} × 1.03 = {price_with_fee} USDT_\n\n"
                "Перейти к оплате?",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Да, оплатить", callback_data="confirm_custom")],
                    [InlineKeyboardButton("❌ Отмена", callback_data="cancel_custom")]
                ])
            )
    
    except ValueError:
        await update.message.reply_text("❌ Пожалуйста, введите корректное число")

# Подтверждение кастомного заказа
async def handle_confirm_custom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if 'selected_product' not in context.user_data or 'price_amount' not in context.user_data:
        await query.edit_message_text("❌ Ошибка: данные заказа не найдены")
        return
    
    await process_custom_payment(query, context.application, context)

# Отмена кастомного заказа
async def handle_cancel_custom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if 'selected_product' in context.user_data:
        del context.user_data['selected_product']
    if 'custom_amount' in context.user_data:
        del context.user_data['custom_amount']
    if 'price_amount' in context.user_data:
        del context.user_data['price_amount']
    if 'price_with_fee' in context.user_data:
        del context.user_data['price_with_fee']
    
    await query.edit_message_text("❌ Заказ отменен")

# Процесс оплаты фиксированного товара
async def process_payment(query, application, context):
    if 'selected_product' not in context.user_data:
        await query.edit_message_text("❌ Ошибка: товар не выбран")
        return
    
    product = context.user_data['selected_product']
    
    invoice = cryptobot.create_invoice(
        amount=product['price'],
        description=product['description'],
        expires_in=900
    )
    
    if not invoice:
        await query.edit_message_text("❌ Ошибка при создании платежа. Попробуйте позже")
        return
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        invoice_id = f"INV_{product['id']}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        cursor.execute('''
            INSERT INTO orders 
            (invoice_id, user_id, username, first_name, product_id, product_name, price_amount, price_with_fee, cryptobot_invoice_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            invoice_id, 
            query.from_user.id, 
            query.from_user.username, 
            query.from_user.first_name,
            product['id'], 
            product['name'], 
            product['price'],
            invoice['amount_with_fee'],
            invoice['invoice_id'], 
            datetime.now()
        ))
        
        conn.commit()
        
        order_data = {
            'invoice_id': invoice_id,
            'user_id': query.from_user.id,
            'username': query.from_user.username,
            'first_name': query.from_user.first_name,
            'product_name': product['name'],
            'price_amount': product['price'],
            'price_with_fee': invoice['amount_with_fee'],
            'created_at': datetime.now()
        }
        await notify_admin(application, order_data, "new")
        
        order_text = (
            f"*Заказ #{invoice_id}*\n\n"
            f"Товар: {product['name']}\n"
            f"Сумма: {product['price']} USDT\n"
            f"Комиссия CryptoBot (3%): +{round(product['price'] * CRYPTOBOT_FEE, 2)} USDT\n"
            f"*Итого к оплате: {invoice['amount_with_fee']} USDT*\n"
            f"Время на оплату: 15 минут\n\n"
            f"Оплатите счет через кнопку ниже\n"
            f"После оплаты нажмите 'Проверить оплату'\n\n"
            f"_Номер заказа: {invoice_id}_"
        )
        
        keyboard = [
            [
                InlineKeyboardButton("💳 Оплатить", url=invoice['pay_url']),
                InlineKeyboardButton("✅ Проверить оплату", callback_data=f"check_{invoice_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(order_text, parse_mode='Markdown', reply_markup=reply_markup)
        
        asyncio.create_task(cancel_order_after_timeout(invoice_id, query.message.chat_id, query.message.message_id, application))
        
    except Exception as e:
        logger.error(f"Ошибка создания заказа: {e}")
        await query.edit_message_text("❌ Ошибка при создании заказа")
    finally:
        conn.close()

# Процесс оплаты кастомного товара (Stars/Steam)
async def process_custom_payment(query, application, context):
    product = context.user_data['selected_product']
    price_amount = context.user_data['price_amount']
    price_with_fee = context.user_data.get('price_with_fee', round(price_amount * (1 + CRYPTOBOT_FEE), 2))
    custom_amount = context.user_data['custom_amount']
    
    description = f"{product['name']}: {custom_amount}"
    if product['type'] == 'stars':
        description = f"Telegram Stars: {custom_amount} шт."
    elif product['type'] == 'steam':
        description = f"Пополнение Steam: {custom_amount}₽"
    
    invoice = cryptobot.create_invoice(
        amount=price_amount,
        description=description,
        expires_in=900
    )
    
    if not invoice:
        await query.edit_message_text("❌ Ошибка при создании платежа. Попробуйте позже")
        return
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        invoice_id = f"INV_{product['id']}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        cursor.execute('''
            INSERT INTO orders 
            (invoice_id, user_id, username, first_name, product_id, product_name, custom_amount, price_amount, price_with_fee, cryptobot_invoice_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            invoice_id, 
            query.from_user.id, 
            query.from_user.username, 
            query.from_user.first_name,
            product['id'], 
            product['name'], 
            custom_amount, 
            price_amount,
            invoice['amount_with_fee'],
            invoice['invoice_id'], 
            datetime.now()
        ))
        
        conn.commit()
        
        order_data = {
            'invoice_id': invoice_id,
            'user_id': query.from_user.id,
            'username': query.from_user.username,
            'first_name': query.from_user.first_name,
            'product_name': product['name'],
            'price_amount': price_amount,
            'price_with_fee': invoice['amount_with_fee'],
            'custom_amount': custom_amount,
            'created_at': datetime.now()
        }
        await notify_admin(application, order_data, "new")
        
        order_text = (
            f"*Заказ #{invoice_id}*\n\n"
            f"Товар: {description}\n"
            f"Сумма: {price_amount} USDT\n"
            f"Комиссия CryptoBot (3%): +{round(price_amount * CRYPTOBOT_FEE, 2)} USDT\n"
            f"*Итого к оплате: {invoice['amount_with_fee']} USDT*\n"
            f"Время на оплату: 15 минут\n\n"
            f"Оплатите счет через кнопку ниже\n"
            f"После оплаты нажмите 'Проверить оплату'\n\n"
            f"_Номер заказа: {invoice_id}_"
        )
        
        keyboard = [
            [
                InlineKeyboardButton("💳 Оплатить", url=invoice['pay_url']),
                InlineKeyboardButton("✅ Проверить оплату", callback_data=f"check_{invoice_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(order_text, parse_mode='Markdown', reply_markup=reply_markup)
        
        asyncio.create_task(cancel_order_after_timeout(invoice_id, query.message.chat_id, query.message.message_id, application))
        
    except Exception as e:
        logger.error(f"Ошибка создания заказа: {e}")
        await query.edit_message_text("❌ Ошибка при создании заказа")
    finally:
        conn.close()
        # Очищаем временные данные
        if 'selected_product' in context.user_data:
            del context.user_data['selected_product']
        if 'custom_amount' in context.user_data:
            del context.user_data['custom_amount']
        if 'price_amount' in context.user_data:
            del context.user_data['price_amount']
        if 'price_with_fee' in context.user_data:
            del context.user_data['price_with_fee']

# Проверка оплаты
async def check_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await check_access(update, context, _check_payment)

async def _check_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data.startswith('check_'):
        invoice_id = data[6:]
        
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT o.cryptobot_invoice_id, o.product_name, o.status, o.user_id, o.username, 
                       o.first_name, o.price_amount, o.product_id, o.custom_amount,
                       p.product_type, p.stock, o.price_with_fee
                FROM orders o
                LEFT JOIN products p ON o.product_id = p.id
                WHERE o.invoice_id = ?
            ''', (invoice_id,))
            order = cursor.fetchone()
            
            if not order:
                await query.answer("❌ Заказ не найден", show_alert=True)
                return
            
            (cryptobot_invoice_id, product_name, status, user_id, username, 
             first_name, price_amount, product_id, custom_amount, 
             product_type, stock, price_with_fee) = order
            
            if status == 'paid':
                success_text = (
                    "*Заказ уже оплачен!*\n\n"
                    f"Товар: {product_name}\n"
                    f"Сумма: {price_amount} USDT\n"
                    f"Оплачено: {price_with_fee} USDT (с учетом комиссии)\n"
                    f"Для получения товара напишите администратору\n\n"
                    f"_Номер заказа: {invoice_id}_"
                )
                if custom_amount:
                    if product_type == 'stars':
                        success_text = f"*Заказ уже оплачен!*\n\nTelegram Stars: {custom_amount} шт.\nСтоимость: {price_amount} USDT\nОплачено: {price_with_fee} USDT\nДля получения Stars напишите администратору\n\n_Номер заказа: {invoice_id}_"
                    elif product_type == 'steam':
                        success_text = f"*Заказ уже оплачен!*\n\nПополнение Steam: {custom_amount}₽\nСтоимость: {price_amount} USDT\nОплачено: {price_with_fee} USDT\nДля пополнения напишите администратору\n\n_Номер заказа: {invoice_id}_"
                
                await query.edit_message_text(success_text, parse_mode='Markdown')
                return
            
            invoice_status = cryptobot.check_invoice_status(cryptobot_invoice_id)
            
            if invoice_status == 'paid':
                # СПИСЫВАЕМ ТОВАР ТОЛЬКО ПОСЛЕ УСПЕШНОЙ ОПЛАТЫ
                if product_type == 'fixed':
                    # Получаем текущий остаток
                    cursor.execute('SELECT stock FROM products WHERE id = ?', (product_id,))
                    result = cursor.fetchone()
                    
                    if not result:
                        await query.answer("❌ Ошибка: товар не найден", show_alert=True)
                        return
                    
                    current_stock = result[0]
                    
                    # Проверяем, есть ли товар в наличии
                    if current_stock <= 0:
                        await query.answer("❌ Товар закончился на складе", show_alert=True)
                        cursor.execute('UPDATE orders SET status = "out_of_stock" WHERE invoice_id = ?', (invoice_id,))
                        conn.commit()
                        return
                    
                    # Уменьшаем количество товара
                    new_stock = current_stock - 1
                    cursor.execute('UPDATE products SET stock = ? WHERE id = ?', (new_stock, product_id))
                
                cursor.execute('''
                    UPDATE orders SET status = 'paid', paid_at = ? 
                    WHERE invoice_id = ?
                ''', (datetime.now(), invoice_id))
                
                conn.commit()
                
                order_data = {
                    'invoice_id': invoice_id,
                    'user_id': user_id,
                    'username': username,
                    'first_name': first_name,
                    'product_name': product_name,
                    'price_amount': price_amount,
                    'price_with_fee': price_with_fee,
                    'custom_amount': custom_amount,
                    'paid_at': datetime.now()
                }
                await notify_admin(context.application, order_data, "paid")
                
                success_text = (
                    "*Заказ успешно оплачен!*\n\n"
                    f"Товар: {product_name}\n"
                    f"Сумма: {price_amount} USDT\n"
                    f"Оплачено: {price_with_fee} USDT (с учетом комиссии)\n"
                    f"Номер заказа: {invoice_id}\n\n"
                    f"Для получения товара напишите администратору\n\n"
                    f"_Не забудьте указать номер заказа!_"
                )
                if custom_amount:
                    if product_type == 'stars':
                        success_text = f"*Заказ успешно оплачен!*\n\nTelegram Stars: {custom_amount} шт.\nСтоимость: {price_amount} USDT\nОплачено: {price_with_fee} USDT\nНомер заказа: {invoice_id}\n\nДля получения Stars напишите администратору"
                    elif product_type == 'steam':
                        success_text = f"*Заказ успешно оплачен!*\n\nПополнение Steam: {custom_amount}₽\nСтоимость: {price_amount} USDT\nОплачено: {price_with_fee} USDT\nНомер заказа: {invoice_id}\n\nДля пополнения напишите администратору"
                
                await query.edit_message_text(success_text, parse_mode='Markdown')
                
            elif invoice_status == 'active':
                await query.answer("❌ Оплата не найдена. Пожалуйста, оплатите счет и попробуйте снова", show_alert=True)
            else:
                await query.answer("❌ Счет просрочен или отменен. Создайте новый заказ", show_alert=True)
                
        except Exception as e:
            logger.error(f"Ошибка проверки оплаты: {e}")
            await query.answer("❌ Ошибка при проверке оплаты", show_alert=True)
        finally:
            conn.close()

# Отмена заказа по таймауту
async def cancel_order_after_timeout(invoice_id, chat_id, message_id, application):
    await asyncio.sleep(900)
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT status FROM orders WHERE invoice_id = ?', (invoice_id,))
        order = cursor.fetchone()
        
        if order and order[0] == 'pending':
            cursor.execute('UPDATE orders SET status = "expired" WHERE invoice_id = ?', (invoice_id,))
            
            conn.commit()
            
            cancel_text = "*Заказ отменен* (время оплаты истекло)\n\nДля нового заказа используйте /price"
            
            try:
                await application.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=cancel_text,
                    parse_mode='Markdown'
                )
            except:
                pass
    except Exception as e:
        logger.error(f"Ошибка отмены заказа: {e}")
    finally:
        conn.close()

# === АДМИН-СИСТЕМА ===

# Команда /admin - админ панель
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Получаем user_id из разных источников
    if update.callback_query:
        user_id = update.callback_query.from_user.id
    elif update.message:
        user_id = update.message.from_user.id
    else:
        return  # Непонятный update
    
    if user_id != ADMIN_ID:
        if update.callback_query:
            await update.callback_query.answer("🚫 У вас нет прав доступа", show_alert=True)
        elif update.message:
            await update.message.reply_text("🚫 У вас нет прав доступа")
        return
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT id, name FROM categories ORDER BY id')
        categories = cursor.fetchall()
        
        text = "*Панель администратора*\n\n*Категории:*\n"
        keyboard = []
        
        for cat_id, cat_name in categories:
            text += f"\n{cat_name}\n"
            cursor.execute('SELECT id, name, price, stock, product_type FROM products WHERE category_id = ?', (cat_id,))
            products = cursor.fetchall()
            
            for prod_id, prod_name, price, stock, prod_type in products:
                stock_emoji = "🟢" if stock > 0 else "🔴"
                type_emoji = {
                    'fixed': '📦',
                    'stars': '⭐',
                    'steam': '🎮'
                }.get(prod_type, '❓')
                text += f"  {type_emoji} {prod_name} - {price}$ {stock_emoji} ({stock} шт.)\n"
                
                keyboard.append([
                    InlineKeyboardButton(f"✏️ {prod_name[:15]}", callback_data=f"edit_{prod_id}"),
                    InlineKeyboardButton(f"🗑️", callback_data=f"delete_{prod_id}")
                ])
        
        # Получаем коэффициенты для отображения
        coefficients = get_all_coefficients()
        text += "\n*Коэффициенты:*\n"
        for coeff_type, data in coefficients.items():
            value = data['value']
            description = data['description'] or coeff_type
            
            if coeff_type == 'stars':
                text += f"Telegram Stars: {value}\n"
            elif coeff_type == 'steam':
                percentage = round((value - 1) * 100, 1)
                text += f"Steam комиссия: +{percentage}% (коэф: {value})\n"
            elif coeff_type == 'exchange_rate':
                text += f"Курс USDT: {value} руб\n"
        
        text += f"\n*Комиссия CryptoBot:* {CRYPTOBOT_FEE*100}%\n"
        
        keyboard.append([InlineKeyboardButton("➕ Добавить товар", callback_data="add_menu")])
        keyboard.append([InlineKeyboardButton("⚙️ Настройки коэффициентов", callback_data="coefficients_menu")])
        keyboard.append([InlineKeyboardButton("📊 Статистика", callback_data="stats")])
        keyboard.append([InlineKeyboardButton("🚫 Управление банами", callback_data="bans_menu")])
        keyboard.append([InlineKeyboardButton("📢 Рассылка", callback_data="broadcast_info")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.edit_message_text(text, parse_mode='Markdown', reply_markup=reply_markup)
        else:
            await update.message.reply_text(text, parse_mode='Markdown', reply_markup=reply_markup)
        
    except Exception as e:
        logger.error(f"Ошибка в админ-панели: {e}")
        if update.callback_query:
            await update.callback_query.edit_message_text("❌ Ошибка загрузки")
        else:
            await update.message.reply_text("❌ Ошибка загрузки")
    finally:
        conn.close()

# Меню коэффициентов
async def coefficients_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != ADMIN_ID:
        return
    
    coefficients = get_all_coefficients()
    
    text = "*Настройки коэффициентов*\n\n"
    
    keyboard = []
    
    for coeff_type, data in coefficients.items():
        value = data['value']
        description = data['description'] or coeff_type
        
        if coeff_type == 'stars':
            display_name = f"Telegram Stars: {value}"
        elif coeff_type == 'steam':
            percentage = round((value - 1) * 100, 1)
            display_name = f"Steam (+{percentage}%): {value}"
        elif coeff_type == 'exchange_rate':
            display_name = f"Курс USDT: {value}"
        else:
            display_name = f"{description}: {value}"
        
        keyboard.append([InlineKeyboardButton(
            display_name, 
            callback_data=f"coeff_{coeff_type}"
        )])
    
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_back")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=reply_markup)

# Редактирование коэффициента
async def handle_coefficient_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != ADMIN_ID:
        return
    
    data = query.data
    if data.startswith('coeff_'):
        coeff_type = data[6:]
        context.user_data['edit_coeff'] = coeff_type
        
        current_value = get_coefficient(coeff_type)
        
        if coeff_type == 'stars':
            description = "Коэффициент для Telegram Stars\nФормула: Stars × коэффициент ÷ курс = USDT\n\nВведите новое значение (например: 1.35):"
        elif coeff_type == 'steam':
            percentage = round((current_value - 1) * 100, 1)
            description = f"Коэффициент для Steam (сейчас +{percentage}%)\nФормула: Сумма₽ × коэффициент ÷ курс = USDT\n\nВведите новое значение (например: 1.03 для +3%):"
        elif coeff_type == 'exchange_rate':
            description = f"Курс USDT к рублю\n\nВведите новое значение (например: 77.5):"
        else:
            description = f"Введите новое значение для {coeff_type}:"
        
        await query.edit_message_text(
            f"✏️ Редактирование коэффициента\n\n"
            f"Тип: {coeff_type}\n"
            f"Текущее значение: {current_value}\n\n"
            f"{description}"
        )

# Меню добавления товара
async def add_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != ADMIN_ID:
        return
    
    categories = get_all_categories()
    keyboard = []
    
    for cat_id, name, description in categories:
        keyboard.append([InlineKeyboardButton(name, callback_data=f"add_cat_{cat_id}")])
    
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_back")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("*Выберите категорию для добавления товара:*", parse_mode='Markdown', reply_markup=reply_markup)

# Выбор категории для добавления
async def handle_add_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != ADMIN_ID:
        return
    
    data = query.data
    if data.startswith('add_cat_'):
        category_id = int(data[8:])
        context.user_data['add_to_cat'] = category_id
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT name FROM categories WHERE id = ?', (category_id,))
        cat_name = cursor.fetchone()[0]
        conn.close()
        
        await query.edit_message_text(
            f"*Добавление товара в категорию:* {cat_name}\n\n"
            "Отправьте данные в формате:\n"
            "Название;Цена;Описание;Количество;Тип\n\n"
            "*Пример:*\n"
            "Прокси США;1.5;Прокси американские;50;fixed\n\n"
            "*Типы товаров:*\n"
            "• fixed - фиксированный товар\n"
            "• stars - Telegram Stars\n"
            "• steam - Пополнение Steam",
            parse_mode='Markdown'
        )

# Редактирование товара
async def handle_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != ADMIN_ID:
        return
    
    data = query.data
    if data.startswith('edit_'):
        product_id = int(data[5:])
        product_info = get_product_info(product_id)
        
        if product_info:
            product_id, name, price, description, stock, product_type, category_name = product_info
            context.user_data['edit_product'] = product_id
            
            await query.edit_message_text(
                f"*Редактирование товара:* {name}\n"
                f"Цена: {price}$\n"
                f"Описание: {description}\n"
                f"Количество: {stock} шт.\n"
                f"Тип: {product_type}\n\n"
                "Отправьте новые данные в формате:\n"
                "Название;Цена;Описание;Количество;Тип\n\n"
                f"*Пример для этого товара:*\n"
                f"{name};{price};{description};{stock};{product_type}",
                parse_mode='Markdown'
            )
        else:
            await query.edit_message_text("❌ Товар не найден")

# Удаление товара
async def handle_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != ADMIN_ID:
        return
    
    data = query.data
    if data.startswith('delete_'):
        product_id = int(data[7:])
        
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT name FROM products WHERE id = ?', (product_id,))
            product_name = cursor.fetchone()
            
            if product_name:
                cursor.execute('DELETE FROM products WHERE id = ?', (product_id,))
                conn.commit()
                await query.edit_message_text(f"✅ Товар '{product_name[0]}' удален!")
            else:
                await query.edit_message_text("❌ Товар не найден")
                
        except Exception as e:
            logger.error(f"Ошибка удаления: {e}")
            await query.edit_message_text(f"❌ Ошибка: {e}")
        finally:
            conn.close()

# Назад в админку
async def admin_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != ADMIN_ID:
        return
    
    await admin(update, context)

# Статистика
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != ADMIN_ID:
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM products WHERE is_active = 1')
    active_products = cursor.fetchone()[0]
    
    cursor.execute('SELECT SUM(stock) FROM products WHERE is_active = 1')
    total_stock = cursor.fetchone()[0] or 0
    
    cursor.execute('SELECT COUNT(*) FROM orders WHERE status = "paid"')
    paid_orders = cursor.fetchone()[0]
    
    cursor.execute('SELECT SUM(price_amount) FROM orders WHERE status = "paid"')
    total_revenue = cursor.fetchone()[0] or 0
    
    cursor.execute('SELECT SUM(price_with_fee) FROM orders WHERE status = "paid"')
    total_with_fee = cursor.fetchone()[0] or 0
    
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]
    
    conn.close()
    
    stats_text = (
        "*Статистика магазина*\n\n"
        f"Активных товаров: {active_products}\n"
        f"Общий остаток: {total_stock} шт.\n"
        f"Оплаченных заказов: {paid_orders}\n"
        f"Выручка (без комиссии): {total_revenue:.2f} USDT\n"
        f"Получено с комиссией: {total_with_fee:.2f} USDT\n"
        f"Комиссия CryptoBot: {total_with_fee - total_revenue:.2f} USDT\n"
        f"Зарегистрировано пользователей: {total_users}"
    )
    
    keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="admin_back")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(stats_text, parse_mode='Markdown', reply_markup=reply_markup)

# Меню банов
async def bans_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != ADMIN_ID:
        return
    
    text = (
        "*Управление банами*\n\n"
        "*Команды:*\n"
        "• /ban @username [причина] - забанить\n"
        "• /unban @username - разбанить\n"
        "• /banned - список забаненных\n\n"
        "*Примеры:*\n"
        "/ban @username Спам\n"
        "/ban 123456789\n"
        "/unban @username"
    )
    
    keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="admin_back")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=reply_markup)

# Инфо о рассылке
async def broadcast_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != ADMIN_ID:
        return
    
    text = (
        "*Рассылка сообщений*\n\n"
        "Используйте команду:\n"
        "/broadcast Ваше сообщение\n\n"
        "*Пример:*\n"
        "/broadcast Всем привет! Новые товары в наличии!"
    )
    
    keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="admin_back")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=reply_markup)

# Обработчик текстовых сообщений для админа
async def handle_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    
    text = update.message.text.strip()
    logger.info(f"Получено сообщение от админа: {text}")
    
    # Обработка редактирования коэффициента
    if 'edit_coeff' in context.user_data:
        try:
            coeff_type = context.user_data['edit_coeff']
            new_value = float(text)
            
            # Валидация значений
            if coeff_type == 'stars' and new_value <= 0:
                await update.message.reply_text("❌ Значение должно быть больше 0")
                return
            
            if coeff_type == 'steam' and new_value <= 0:
                await update.message.reply_text("❌ Значение должно быть больше 0")
                return
            
            if coeff_type == 'exchange_rate' and new_value <= 0:
                await update.message.reply_text("❌ Курс должен быть больше 0")
                return
            
            old_value = get_coefficient(coeff_type)
            
            if update_coefficient(coeff_type, new_value):
                # Форматируем сообщение в зависимости от типа
                if coeff_type == 'stars':
                    message = f"*Коэффициент Telegram Stars изменен!*\n\nБыло: {old_value}\nСтало: {new_value}"
                elif coeff_type == 'steam':
                    old_percentage = round((old_value - 1) * 100, 1)
                    new_percentage = round((new_value - 1) * 100, 1)
                    message = f"*Коэффициент Steam изменен!*\n\nБыло: {old_value} (+{old_percentage}%)\nСтало: {new_value} (+{new_percentage}%)"
                elif coeff_type == 'exchange_rate':
                    message = f"*Курс USDT изменен!*\n\nБыло: {old_value} руб\nСтало: {new_value} руб"
                else:
                    message = f"*Коэффициент {coeff_type} изменен!*\n\nБыло: {old_value}\nСтало: {new_value}"
                
                await update.message.reply_text(message, parse_mode='Markdown')
                
                # Удаляем сохраненные данные
                del context.user_data['edit_coeff']
                
            else:
                await update.message.reply_text("❌ Ошибка при обновлении коэффициента")
            
        except ValueError:
            await update.message.reply_text("❌ Пожалуйста, введите число")
        except Exception as e:
            logger.error(f"Ошибка обновления коэффициента: {e}")
            await update.message.reply_text(f"❌ Ошибка: {e}")
    
    # Обработка добавления товара
    elif 'add_to_cat' in context.user_data:
        try:
            category_id = context.user_data['add_to_cat']
            logger.info(f"Добавление товара в категорию {category_id}")
            
            parts = text.split(';')
            if len(parts) == 5:
                name = parts[0].strip()
                price = float(parts[1].strip())
                description = parts[2].strip()
                stock = int(parts[3].strip())
                product_type = parts[4].strip().lower()
                
                # Проверка типа
                if product_type not in ['fixed', 'stars', 'steam']:
                    await update.message.reply_text("❌ Неверный тип. Используйте: fixed, stars или steam")
                    return
                
                conn = get_db_connection()
                cursor = conn.cursor()
                
                cursor.execute('''
                    INSERT INTO products (category_id, name, price, description, stock, product_type)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (category_id, name, price, description, stock, product_type))
                
                conn.commit()
                conn.close()
                
                del context.user_data['add_to_cat']
                
                type_names = {
                    'fixed': '📦 Фиксированный',
                    'stars': '⭐ Telegram Stars',
                    'steam': '🎮 Пополнение Steam'
                }
                
                await update.message.reply_text(
                    f"*Товар успешно добавлен!*\n\n"
                    f"Название: {name}\n"
                    f"Цена: {price}$\n"
                    f"Описание: {description}\n"
                    f"Количество: {stock} шт.\n"
                    f"Тип: {type_names.get(product_type, product_type)}",
                    parse_mode='Markdown'
                )
                
                # Возвращаем в админку
                await admin(update, context)
            else:
                await update.message.reply_text(
                    "❌ Неверный формат. Нужно 5 параметров:\n"
                    "Название;Цена;Описание;Количество;Тип\n\n"
                    "Пример: Прокси США;1.5;Прокси американские;50;fixed"
                )
                
        except ValueError as e:
            await update.message.reply_text(f"❌ Ошибка в данных: {e}")
        except Exception as e:
            logger.error(f"Ошибка добавления: {e}")
            await update.message.reply_text(f"❌ Ошибка: {e}")
    
    # Обработка редактирования товара
    elif 'edit_product' in context.user_data:
        try:
            product_id = context.user_data['edit_product']
            logger.info(f"Редактирование товара {product_id}")
            
            parts = text.split(';')
            if len(parts) == 5:
                new_name = parts[0].strip()
                new_price = float(parts[1].strip())
                new_description = parts[2].strip()
                new_stock = int(parts[3].strip())
                new_type = parts[4].strip().lower()
                
                # Проверка типа
                if new_type not in ['fixed', 'stars', 'steam']:
                    await update.message.reply_text("❌ Неверный тип. Используйте: fixed, stars или steam")
                    return
                
                conn = get_db_connection()
                cursor = conn.cursor()
                
                # Получаем старое название
                cursor.execute('SELECT name FROM products WHERE id = ?', (product_id,))
                old_name = cursor.fetchone()[0]
                
                cursor.execute('''
                    UPDATE products 
                    SET name = ?, price = ?, description = ?, stock = ?, product_type = ?
                    WHERE id = ?
                ''', (new_name, new_price, new_description, new_stock, new_type, product_id))
                
                conn.commit()
                conn.close()
                
                del context.user_data['edit_product']
                
                await update.message.reply_text(
                    f"*Товар успешно обновлен!*\n\n"
                    f"Было: {old_name}\n"
                    f"Стало: {new_name}\n"
                    f"Цена: {new_price}$\n"
                    f"Описание: {new_description[:50]}...\n"
                    f"Количество: {new_stock} шт.\n"
                    f"Тип: {new_type}",
                    parse_mode='Markdown'
                )
                
                # Возвращаем в админку
                await admin(update, context)
            else:
                await update.message.reply_text(
                    "❌ Неверный формат. Нужно 5 параметров:\n"
                    "Название;Цена;Описание;Количество;Тип\n\n"
                    "Пример: Telegram Premium;20.5;Premium на 3 месяца;100;fixed"
                )
                
        except ValueError as e:
            await update.message.reply_text(f"❌ Ошибка в данных: {e}")
        except Exception as e:
            logger.error(f"Ошибка редактирования: {e}")
            await update.message.reply_text(f"❌ Ошибка: {e}")

# Общий обработчик текстовых сообщений
async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Сначала проверяем админские сообщения
    if update.message.from_user.id == ADMIN_ID:
        await handle_admin_text(update, context)
        return
    
    # Если не админ, проверяем кастомный заказ
    await handle_custom_amount(update, context)

# Команда /support
async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await check_access(update, context, _support)

async def _support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    support_text = (
        "*Техническая поддержка*\n\n"
        "*Связь с администратором:*\n"
        "• Обратитесь к администратору\n"
        "• Ответ в течение 5-30 минут\n\n"
        "*Если возникли проблемы:*\n"
        "1. Сохраните номер заказа\n"
        "2. Опишите проблему\n"
        "3. Приложите скриншот при необходимости"
    )
    await update.message.reply_text(support_text, parse_mode='Markdown')

# Команды банов
async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 У вас нет прав доступа")
        return
    
    if not context.args:
        await update.message.reply_text("Использование: /ban @username или /ban user_id [причина]")
        return
    
    target = context.args[0]
    reason = " ".join(context.args[1:]) if len(context.args) > 1 else "Администратор"
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if target.isdigit():
            user_id = int(target)
            cursor.execute('SELECT username, first_name FROM users WHERE user_id = ?', (user_id,))
            user_data = cursor.fetchone()
            
            if user_data:
                username, first_name = user_data
                cursor.execute('INSERT OR IGNORE INTO banned_users (user_id, username, first_name, banned_by, banned_at, reason) VALUES (?, ?, ?, ?, ?, ?)',
                              (user_id, username, first_name, ADMIN_ID, datetime.now(), reason))
                await update.message.reply_text(f"✅ Пользователь @{username} (ID: {user_id}) забанен!\nПричина: {reason}")
            else:
                cursor.execute('INSERT OR IGNORE INTO banned_users (user_id, username, first_name, banned_by, banned_at, reason) VALUES (?, ?, ?, ?, ?, ?)',
                              (user_id, 'Unknown', 'Unknown User', ADMIN_ID, datetime.now(), reason))
                await update.message.reply_text(f"✅ Пользователь (ID: {user_id}) забанен!\nПричина: {reason}")
        
        elif target.startswith('@'):
            username = target[1:]
            cursor.execute('SELECT user_id, first_name FROM users WHERE username = ?', (username,))
            user_data = cursor.fetchone()
            
            if user_data:
                user_id, first_name = user_data
                cursor.execute('INSERT OR IGNORE INTO banned_users (user_id, username, first_name, banned_by, banned_at, reason) VALUES (?, ?, ?, ?, ?, ?)',
                              (user_id, username, first_name, ADMIN_ID, datetime.now(), reason))
                await update.message.reply_text(f"✅ Пользователь @{username} (ID: {user_id}) забанен!\nПричина: {reason}")
            else:
                await update.message.reply_text(f"❌ Пользователь {target} не найден в базе")
        
        conn.commit()
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")
    finally:
        conn.close()

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 У вас нет прав доступа")
        return
    
    if not context.args:
        await update.message.reply_text("Использование: /unban @username или /unban user_id")
        return
    
    target = context.args[0]
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if target.isdigit():
            cursor.execute('DELETE FROM banned_users WHERE user_id = ?', (int(target),))
        elif target.startswith('@'):
            username = target[1:]
            cursor.execute('DELETE FROM banned_users WHERE username = ?', (username,))
        
        if cursor.rowcount > 0:
            await update.message.reply_text(f"✅ Пользователь {target} разбанен!")
        else:
            await update.message.reply_text(f"❌ Пользователь {target} не найден в списке забаненных")
        
        conn.commit()
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")
    finally:
        conn.close()

async def banned_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 У вас нет прав доступа")
        return
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, username, first_name, banned_at, reason FROM banned_users ORDER BY banned_at DESC')
        banned_users = cursor.fetchall()
        
        if not banned_users:
            await update.message.reply_text("📋 Список забаненных пользователей пуст")
            return
        
        text = "*Забаненные пользователи:*\n\n"
        for user in banned_users:
            user_id, username, first_name, banned_at, reason = user
            username_display = f"@{username}" if username else "Нет username"
            banned_date = datetime.strptime(banned_at, '%Y-%m-%d %H:%M:%S').strftime('%d.%m.%Y %H:%M') if isinstance(banned_at, str) else banned_at.strftime('%d.%m.%Y %H:%M')
            text += f"• {first_name} ({username_display})\n  ID: {user_id}\n  Забанен: {banned_date}\n  Причина: {reason}\n\n"
        
        await update.message.reply_text(text, parse_mode='Markdown')
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")
    finally:
        conn.close()

# Команда /broadcast
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 У вас нет прав доступа")
        return
    
    if not context.args:
        await update.message.reply_text("Использование: /broadcast ваше сообщение")
        return
    
    message = " ".join(context.args)
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT user_id FROM users')
        users = cursor.fetchall()
        
        total = len(users)
        success = 0
        failed = 0
        
        await update.message.reply_text(f"📢 Начинаю рассылку для {total} пользователей...")
        
        for user in users:
            user_id = user[0]
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"*Рассылка от администратора:*\n\n{message}",
                    parse_mode='Markdown'
                )
                success += 1
            except Exception as e:
                failed += 1
                logger.error(f"Ошибка отправки пользователю {user_id}: {e}")
            
            await asyncio.sleep(0.05)
        
        await update.message.reply_text(
            f"*Рассылка завершена!*\n\n"
            f"✅ Успешно: {success}\n"
            f"❌ Не доставлено: {failed}\n"
            f"📊 Всего: {total}",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Ошибка рассылки: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")
    finally:
        conn.close()

def main():
    print("=" * 50)
    print("🚀 Запуск бота...")
    print(f"📁 Рабочая директория: {BASE_DIR}")
    print(f"📁 Папка данных: {DATA_DIR}")
    print(f"📊 База данных: {DB_PATH}")
    print("=" * 50)
    
    # Инициализация базы данных
    init_db()
    
    # Создание приложения
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Основные команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("price", price))
    application.add_handler(CommandHandler("support", support))
    
    # Админ команды
    application.add_handler(CommandHandler("admin", admin))
    application.add_handler(CommandHandler("ban", ban_user))
    application.add_handler(CommandHandler("unban", unban_user))
    application.add_handler(CommandHandler("banned", banned_list))
    application.add_handler(CommandHandler("broadcast", broadcast))
    
    # Обработчики callback
    application.add_handler(CallbackQueryHandler(handle_category_selection, pattern="^cat_"))
    application.add_handler(CallbackQueryHandler(handle_back_to_categories, pattern="^back_to_categories$"))
    application.add_handler(CallbackQueryHandler(handle_product_selection, pattern="^buy_"))
    application.add_handler(CallbackQueryHandler(check_payment, pattern="^check_"))
    application.add_handler(CallbackQueryHandler(handle_confirm_custom, pattern="^confirm_custom$"))
    application.add_handler(CallbackQueryHandler(handle_cancel_custom, pattern="^cancel_custom$"))
    
    # Админ callback
    application.add_handler(CallbackQueryHandler(add_menu, pattern="^add_menu$"))
    application.add_handler(CallbackQueryHandler(handle_add_category, pattern="^add_cat_"))
    application.add_handler(CallbackQueryHandler(handle_edit, pattern="^edit_"))
    application.add_handler(CallbackQueryHandler(handle_delete, pattern="^delete_"))
    application.add_handler(CallbackQueryHandler(admin_back, pattern="^admin_back$"))
    application.add_handler(CallbackQueryHandler(stats, pattern="^stats$"))
    application.add_handler(CallbackQueryHandler(bans_menu, pattern="^bans_menu$"))
    application.add_handler(CallbackQueryHandler(broadcast_info, pattern="^broadcast_info$"))
    application.add_handler(CallbackQueryHandler(coefficients_menu, pattern="^coefficients_menu$"))
    application.add_handler(CallbackQueryHandler(handle_coefficient_edit, pattern="^coeff_"))
    
    # ЕДИНЫЙ обработчик текстовых сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages))
    
    logger.info("🤖 Бот запущен!")
    print("=" * 50)
    print("✅ Бот успешно запущен!")
    print(f"👑 Админ ID: {ADMIN_ID}")
    print(f"📁 База данных: {DB_PATH}")
    print("🛍️ Доступные категории:")
    print("1. Telegram Stars/Premium")
    print("2. Пополнение Steam") 
    print("3. Прокси")
    print("4. Подписки")
    print("5. Физы")
    print("⚙️ Коэффициенты:")
    print(f"   • Telegram Stars: {get_coefficient('stars')}")
    print(f"   • Steam комиссия: +{round((get_coefficient('steam') - 1) * 100, 1)}%")
    print(f"   • Курс USDT: {get_coefficient('exchange_rate')}")
    print(f"💰 Комиссия CryptoBot: {CRYPTOBOT_FEE*100}%")
    print("✅ Все системы работают")
    print("=" * 50)
    
    # Запуск бота
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()

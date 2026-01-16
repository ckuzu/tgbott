import asyncio
import logging
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, 
    InlineKeyboardButton, LabeledPrice, PreCheckoutQuery,
    ShippingQuery, ShippingOption
)
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode
import sqlite3
import json
import os
import uuid
from datetime import datetime
from decimal import Decimal

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
ADMIN_IDS = [123456789]  # Замените на ваш ID администратора
PAYMENTS_PROVIDER_TOKEN = "YOUR_PAYMENTS_PROVIDER_TOKEN_HERE"  # Получите у @BotFather

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# Состояния FSM
class ShopStates(StatesGroup):
    waiting_for_product_name = State()
    waiting_for_product_description = State()
    waiting_for_product_price = State()
    waiting_for_product_photo = State()
    waiting_for_quantity = State()
    waiting_for_address = State()
    waiting_for_shipping_method = State()
    waiting_for_payment_method = State()
    waiting_for_phone_number = State()

# Инициализация базы данных с таблицей платежей
def init_db():
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            phone TEXT,
            address TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Таблица категорий
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT
        )
    ''')
    
    # Таблица товаров
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER,
            name TEXT NOT NULL,
            description TEXT,
            price REAL NOT NULL,
            photo_id TEXT,
            stock INTEGER DEFAULT 0,
            FOREIGN KEY (category_id) REFERENCES categories (id)
        )
    ''')
    
    # Таблица заказов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            products TEXT,  # JSON список товаров
            total_price REAL,
            address TEXT,
            shipping_method TEXT,
            payment_method TEXT,
            payment_status TEXT DEFAULT 'pending',  # pending, paid, failed, refunded
            telegram_payment_charge_id TEXT,
            provider_payment_charge_id TEXT,
            status TEXT DEFAULT 'new',  # new, processing, shipped, delivered, cancelled
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    
    # Таблица корзины
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cart (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            product_id INTEGER,
            quantity INTEGER,
            FOREIGN KEY (user_id) REFERENCES users (user_id),
            FOREIGN KEY (product_id) REFERENCES products (id)
        )
    ''')
    
    # Таблица платежей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER,
            user_id INTEGER,
            amount REAL,
            currency TEXT DEFAULT 'RUB',
            provider TEXT,
            payment_id TEXT,
            status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (order_id) REFERENCES orders (id),
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    
    # Добавляем тестовые данные, если таблицы пусты
    cursor.execute("SELECT COUNT(*) FROM categories")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO categories (name) VALUES ('Электроника'), ('Одежда'), ('Книги')")
        
    cursor.execute("SELECT COUNT(*) FROM products")
    if cursor.fetchone()[0] == 0:
        cursor.execute('''
            INSERT INTO products (category_id, name, description, price, stock) 
            VALUES 
            (1, 'Смартфон', 'Новый смартфон с отличной камерой', 29999.99, 10),
            (1, 'Ноутбук', 'Мощный ноутбук для работы', 59999.99, 5),
            (2, 'Футболка', 'Хлопковая футболка', 1999.99, 50),
            (3, 'Программирование на Python', 'Лучшая книга по Python', 1499.99, 20)
        ''')
    
    conn.commit()
    conn.close()

# Функции для работы с БД (дополненные)
def add_user(user_id, username, first_name, last_name=""):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR IGNORE INTO users (user_id, username, first_name, last_name) 
        VALUES (?, ?, ?, ?)
    ''', (user_id, username, first_name, last_name))
    conn.commit()
    conn.close()

def update_user_info(user_id, phone=None, address=None):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    
    if phone:
        cursor.execute('UPDATE users SET phone = ? WHERE user_id = ?', (phone, user_id))
    if address:
        cursor.execute('UPDATE users SET address = ? WHERE user_id = ?', (address, user_id))
    
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def get_products(category_id=None):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    
    if category_id:
        cursor.execute('''
            SELECT p.*, c.name as category_name 
            FROM products p 
            LEFT JOIN categories c ON p.category_id = c.id 
            WHERE p.category_id = ? AND p.stock > 0
        ''', (category_id,))
    else:
        cursor.execute('''
            SELECT p.*, c.name as category_name 
            FROM products p 
            LEFT JOIN categories c ON p.category_id = c.id 
            WHERE p.stock > 0
        ''')
    
    products = cursor.fetchall()
    conn.close()
    return products

def get_product(product_id):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM products WHERE id = ?', (product_id,))
    product = cursor.fetchone()
    conn.close()
    return product

def get_categories():
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM categories')
    categories = cursor.fetchall()
    conn.close()
    return categories

def add_to_cart(user_id, product_id, quantity=1):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    
    # Проверяем наличие товара
    cursor.execute('SELECT stock FROM products WHERE id = ?', (product_id,))
    stock = cursor.fetchone()
    
    if not stock or stock[0] < quantity:
        conn.close()
        return False, "Недостаточно товара на складе"
    
    # Проверяем, есть ли уже товар в корзине
    cursor.execute('SELECT * FROM cart WHERE user_id = ? AND product_id = ?', (user_id, product_id))
    existing = cursor.fetchone()
    
    if existing:
        new_quantity = existing[3] + quantity
        if new_quantity > stock[0]:
            conn.close()
            return False, f"Максимальное количество: {stock[0]} шт."
        cursor.execute('UPDATE cart SET quantity = ? WHERE id = ?', (new_quantity, existing[0]))
    else:
        cursor.execute('INSERT INTO cart (user_id, product_id, quantity) VALUES (?, ?, ?)', 
                      (user_id, product_id, quantity))
    
    conn.commit()
    conn.close()
    return True, "Товар добавлен в корзину"

def get_cart(user_id):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT c.id, c.product_id, c.quantity, p.name, p.price, p.stock 
        FROM cart c 
        JOIN products p ON c.product_id = p.id 
        WHERE c.user_id = ?
    ''', (user_id,))
    cart_items = cursor.fetchall()
    conn.close()
    return cart_items

def clear_cart(user_id):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM cart WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def create_order(user_id, products, total_price, address, shipping_method="standard", payment_method="telegram"):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    
    # Преобразуем товары в JSON
    products_json = json.dumps(products)
    
    cursor.execute('''
        INSERT INTO orders (user_id, products, total_price, address, shipping_method, payment_method, status) 
        VALUES (?, ?, ?, ?, ?, ?, 'new')
    ''', (user_id, products_json, total_price, address, shipping_method, payment_method))
    
    order_id = cursor.lastrowid
    
    # Обновляем количество товаров на складе
    for product in products:
        cursor.execute('UPDATE products SET stock = stock - ? WHERE id = ?', 
                      (product['quantity'], product['product_id']))
    
    conn.commit()
    conn.close()
    return order_id

def update_order_status(order_id, status, payment_status=None):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    
    if payment_status:
        cursor.execute('UPDATE orders SET status = ?, payment_status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', 
                      (status, payment_status, order_id))
    else:
        cursor.execute('UPDATE orders SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', 
                      (status, order_id))
    
    conn.commit()
    conn.close()

def update_payment_info(order_id, telegram_payment_charge_id=None, provider_payment_charge_id=None):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    
    updates = []
    params = []
    
    if telegram_payment_charge_id:
        updates.append("telegram_payment_charge_id = ?")
        params.append(telegram_payment_charge_id)
    
    if provider_payment_charge_id:
        updates.append("provider_payment_charge_id = ?")
        params.append(provider_payment_charge_id)
    
    if updates:
        params.append(order_id)
        cursor.execute(f'UPDATE orders SET {", ".join(updates)} WHERE id = ?', params)
    
    conn.commit()
    conn.close()

def add_payment_record(order_id, user_id, amount, provider, payment_id, status):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO payments (order_id, user_id, amount, provider, payment_id, status) 
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (order_id, user_id, amount, provider, payment_id, status))
    
    conn.commit()
    conn.close()

def get_order(order_id):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM orders WHERE id = ?', (order_id,))
    order = cursor.fetchone()
    conn.close()
    return order

def get_user_orders(user_id):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC', (user_id,))
    orders = cursor.fetchall()
    conn.close()
    return orders

# Клавиатуры
def get_main_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍️ Каталог", callback_data="catalog")],
        [InlineKeyboardButton(text="🛒 Корзина", callback_data="cart")],
        [InlineKeyboardButton(text="📦 Мои заказы", callback_data="my_orders")],
        [InlineKeyboardButton(text="💰 Баланс", callback_data="balance")],
        [InlineKeyboardButton(text="📞 Контакты", callback_data="contacts")],
        [InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help")]
    ])
    return keyboard

def get_categories_keyboard():
    categories = get_categories()
    keyboard = []
    for cat in categories:
        keyboard.append([InlineKeyboardButton(text=cat[1], callback_data=f"category_{cat[0]}")])
    keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_products_keyboard(products):
    keyboard = []
    for product in products:
        keyboard.append([
            InlineKeyboardButton(
                text=f"{product[2]} - {product[4]:.2f} руб.", 
                callback_data=f"product_{product[0]}"
            )
        ])
    keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_categories")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_product_keyboard(product_id, in_cart=False):
    if in_cart:
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="➖", callback_data=f"decrease_{product_id}"),
                InlineKeyboardButton(text="❌ Убрать", callback_data=f"remove_from_cart_{product_id}"),
                InlineKeyboardButton(text="➕", callback_data=f"increase_{product_id}")
            ],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_products")]
        ])
    else:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить в корзину", callback_data=f"add_to_cart_{product_id}")],
            [InlineKeyboardButton(text="🛒 Корзина", callback_data="cart")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_products")]
        ])

def get_cart_keyboard(cart_items):
    keyboard = []
    for item in cart_items:
        keyboard.append([
            InlineKeyboardButton(
                text=f"❌ {item[3]} (x{item[2]})", 
                callback_data=f"remove_item_{item[0]}"
            )
        ])
    if cart_items:
        keyboard.append([
            InlineKeyboardButton(text="🔄 Очистить корзину", callback_data="clear_cart")
        ])
        keyboard.append([
            InlineKeyboardButton(text="✅ Оформить заказ", callback_data="checkout")
        ])
    keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_payment_methods_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💳 Telegram Payments", callback_data="payment_telegram"),
            InlineKeyboardButton(text="💵 При получении", callback_data="payment_cod")
        ],
        [
            InlineKeyboardButton(text="🏦 Банковская карта", callback_data="payment_card"),
            InlineKeyboardButton(text="📱 Электронные деньги", callback_data="payment_emoney")
        ],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_cart")]
    ])
    return keyboard

def get_shipping_methods_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🚚 Курьер (300 руб.)", callback_data="shipping_courier"),
            InlineKeyboardButton(text="📮 Почта (150 руб.)", callback_data="shipping_post")
        ],
        [
            InlineKeyboardButton(text="🏪 Пункт выдачи (100 руб.)", callback_data="shipping_pickup"),
            InlineKeyboardButton(text="✈️ Экспресс (500 руб.)", callback_data="shipping_express")
        ],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_cart")]
    ])
    return keyboard

def get_order_confirmation_keyboard(order_id):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💳 Оплатить сейчас", callback_data=f"pay_order_{order_id}"),
            InlineKeyboardButton(text="💵 Оплатить при получении", callback_data=f"pay_cod_{order_id}")
        ],
        [
            InlineKeyboardButton(text="❌ Отменить заказ", callback_data=f"cancel_order_{order_id}"),
            InlineKeyboardButton(text="📋 Мои заказы", callback_data="my_orders")
        ]
    ])
    return keyboard

# Обработчики команд
@router.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    first_name = message.from_user.first_name or ""
    last_name = message.from_user.last_name or ""
    
    add_user(user_id, username, first_name, last_name)
    
    await message.answer(
        f"👋 Добро пожаловать, {first_name}!\n\n"
        "🛍️ *Магазин Бот с оплатой*\n\n"
        "✨ *Возможности:*\n"
        "• 💳 Оплата через Telegram\n"
        "• 🏦 Оплата банковской картой\n"
        "• 💵 Оплата при получении\n"
        "• 🚚 Разные способы доставки\n"
        "• 📦 Отслеживание заказов\n\n"
        "Выберите действие:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_menu()
    )

@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📖 *Помощь*\n\n"
        "*Основные команды:*\n"
        "/start - Главное меню\n"
        "/help - Эта справка\n"
        "/catalog - Просмотр каталога\n"
        "/cart - Просмотр корзины\n"
        "/balance - Проверить баланс\n"
        "/orders - Мои заказы\n\n"
        "*Способы оплаты:*\n"
        "1. 💳 Telegram Payments - мгновенная оплата в боте\n"
        "2. 🏦 Банковская карта - ссылка на оплату\n"
        "3. 💵 При получении - наличными или картой\n"
        "4. 📱 Электронные деньги - Qiwi, ЮMoney и др.\n\n"
        "*Доставка:*\n"
        "• 🚚 Курьер - 300 руб.\n"
        "• 📮 Почта - 150 руб.\n"
        "• 🏪 Пункт выдачи - 100 руб.\n"
        "• ✈️ Экспресс - 500 руб.\n\n"
        "Если возникли проблемы, свяжитесь с администратором.",
        parse_mode=ParseMode.MARKDOWN
    )

@router.message(Command("balance"))
async def cmd_balance(message: Message):
    # Здесь можно добавить систему бонусов или баланса пользователя
    await message.answer(
        "💰 *Ваш баланс*\n\n"
        "💎 Бонусные баллы: 0\n"
        "🎁 Накопительная скидка: 0%\n\n"
        "💡 *Как получить бонусы:*\n"
        "• 1 бонус = 1 рубль с каждой покупки\n"
        "• Пригласите друга: 100 бонусов\n"
        "• Отзыв о заказе: 50 бонусов\n\n"
        "Бонусами можно оплатить до 50% стоимости заказа.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 История операций", callback_data="balance_history")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")]
        ])
    )

@router.message(Command("orders"))
async def cmd_orders(message: Message):
    await my_orders_callback_handler(message)

# Обработчики колбэков
@router.callback_query(F.data == "catalog")
async def catalog_callback(callback: CallbackQuery):
    await callback.message.edit_text(
        "📂 Выберите категорию:",
        reply_markup=get_categories_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("category_"))
async def category_callback(callback: CallbackQuery):
    category_id = int(callback.data.split("_")[1])
    products = get_products(category_id)
    
    if not products:
        await callback.message.edit_text(
            "😔 В этой категории пока нет товаров.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_categories")]
            ])
        )
    else:
        await callback.message.edit_text(
            "📦 Товары в выбранной категории:",
            reply_markup=get_products_keyboard(products)
        )
    await callback.answer()

@router.callback_query(F.data.startswith("product_"))
async def product_callback(callback: CallbackQuery):
    product_id = int(callback.data.split("_")[1])
    product = get_product(product_id)
    
    if product:
        # Проверяем, есть ли товар в корзине
        cart_items = get_cart(callback.from_user.id)
        in_cart = any(item[1] == product_id for item in cart_items)
        
        message_text = (
            f"📦 *{product[2]}*\n\n"
            f"📝 Описание: {product[3]}\n"
            f"💰 Цена: *{product[4]:.2f} руб.*\n"
            f"📦 В наличии: {product[6]} шт.\n"
            f"📊 Артикул: #{product[0]}\n"
        )
        
        if product[5]:  # Если есть фото
            try:
                await callback.message.delete()
                await callback.message.answer_photo(
                    product[5],
                    caption=message_text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=get_product_keyboard(product_id, in_cart)
                )
            except:
                await callback.message.edit_text(
                    message_text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=get_product_keyboard(product_id, in_cart)
                )
        else:
            await callback.message.edit_text(
                message_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_product_keyboard(product_id, in_cart)
            )
    await callback.answer()

@router.callback_query(F.data.startswith("add_to_cart_"))
async def add_to_cart_callback(callback: CallbackQuery):
    product_id = int(callback.data.split("_")[3])
    success, message = add_to_cart(callback.from_user.id, product_id)
    
    if success:
        await callback.answer(message)
        # Обновляем клавиатуру товара
        cart_items = get_cart(callback.from_user.id)
        in_cart = any(item[1] == product_id for item in cart_items)
        
        product = get_product(product_id)
        message_text = (
            f"📦 *{product[2]}*\n\n"
            f"📝 Описание: {product[3]}\n"
            f"💰 Цена: *{product[4]:.2f} руб.*\n"
            f"📦 В наличии: {product[6]} шт.\n"
            f"📊 Артикул: #{product[0]}\n"
        )
        
        await callback.message.edit_reply_markup(
            reply_markup=get_product_keyboard(product_id, in_cart)
        )
    else:
        await callback.answer(message, show_alert=True)

@router.callback_query(F.data.startswith("increase_"))
async def increase_cart_callback(callback: CallbackQuery):
    product_id = int(callback.data.split("_")[1])
    success, message = add_to_cart(callback.from_user.id, product_id, 1)
    
    if success:
        # Обновляем сообщение корзины
        await cart_callback(callback)
    else:
        await callback.answer(message, show_alert=True)

@router.callback_query(F.data.startswith("decrease_"))
async def decrease_cart_callback(callback: CallbackQuery):
    product_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    
    # Находим товар в корзине
    cursor.execute('SELECT id, quantity FROM cart WHERE user_id = ? AND product_id = ?', 
                  (user_id, product_id))
    cart_item = cursor.fetchone()
    
    if cart_item:
        if cart_item[1] > 1:
            cursor.execute('UPDATE cart SET quantity = quantity - 1 WHERE id = ?', (cart_item[0],))
        else:
            cursor.execute('DELETE FROM cart WHERE id = ?', (cart_item[0],))
        
        conn.commit()
    
    conn.close()
    await cart_callback(callback)
    await callback.answer("Количество уменьшено")

@router.callback_query(F.data == "cart")
async def cart_callback(callback: CallbackQuery):
    cart_items = get_cart(callback.from_user.id)
    
    if not cart_items:
        await callback.message.edit_text(
            "🛒 Ваша корзина пуста",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🛍️ В каталог", callback_data="catalog")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")]
            ])
        )
    else:
        total = sum(item[2] * item[4] for item in cart_items)
        items_text = "\n".join([f"• {item[3]} - {item[2]} x {item[4]:.2f} руб." for item in cart_items])
        
        await callback.message.edit_text(
            f"🛒 *Ваша корзина:*\n\n{items_text}\n\n"
            f"💰 *Итого: {total:.2f} руб.*\n\n"
            f"📦 Товаров: {len(cart_items)}\n"
            f"🧮 Общее количество: {sum(item[2] for item in cart_items)}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_cart_keyboard(cart_items)
        )
    await callback.answer()

@router.callback_query(F.data == "clear_cart")
async def clear_cart_callback(callback: CallbackQuery):
    clear_cart(callback.from_user.id)
    await cart_callback(callback)
    await callback.answer("Корзина очищена")

@router.callback_query(F.data.startswith("remove_item_"))
async def remove_item_callback(callback: CallbackQuery):
    item_id = int(callback.data.split("_")[2])
    
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM cart WHERE id = ?', (item_id,))
    conn.commit()
    conn.close()
    
    await cart_callback(callback)
    await callback.answer("Товар удален из корзины")

@router.callback_query(F.data == "checkout")
async def checkout_callback(callback: CallbackQuery, state: FSMContext):
    cart_items = get_cart(callback.from_user.id)
    
    if not cart_items:
        await callback.answer("Корзина пуста!")
        return
    
    # Проверяем, есть ли у пользователя сохраненный адрес
    user = get_user(callback.from_user.id)
    
    if user and user[5]:  # Если есть сохраненный адрес
        await state.update_data(address=user[5])
        await callback.message.edit_text(
            "🚚 Выберите способ доставки:",
            reply_markup=get_shipping_methods_keyboard()
        )
        await state.set_state(ShopStates.waiting_for_shipping_method)
    else:
        await callback.message.edit_text(
            "📍 Пожалуйста, отправьте ваш адрес доставки:\n"
            "(город, улица, дом, квартира)\n\n"
            "Пример: Москва, Тверская ул., 15, кв. 42"
        )
        await state.set_state(ShopStates.waiting_for_address)
    
    await callback.answer()

@router.message(ShopStates.waiting_for_address)
async def process_address(message: Message, state: FSMContext):
    address = message.text
    await state.update_data(address=address)
    
    # Сохраняем адрес в профиль пользователя
    update_user_info(message.from_user.id, address=address)
    
    await message.answer(
        f"✅ Адрес сохранен: {address}\n\n"
        f"🚚 Теперь выберите способ доставки:",
        reply_markup=get_shipping_methods_keyboard()
    )
    await state.set_state(ShopStates.waiting_for_shipping_method)

@router.callback_query(F.data.startswith("shipping_"))
async def shipping_method_callback(callback: CallbackQuery, state: FSMContext):
    shipping_method = callback.data
    
    shipping_prices = {
        "shipping_courier": 300,
        "shipping_post": 150,
        "shipping_pickup": 100,
        "shipping_express": 500
    }
    
    shipping_names = {
        "shipping_courier": "Курьерская доставка",
        "shipping_post": "Почта России",
        "shipping_pickup": "Пункт выдачи",
        "shipping_express": "Экспресс-доставка"
    }
    
    shipping_price = shipping_prices.get(shipping_method, 0)
    shipping_name = shipping_names.get(shipping_method, "Стандартная")
    
    await state.update_data(
        shipping_method=shipping_method,
        shipping_name=shipping_name,
        shipping_price=shipping_price
    )
    
    await callback.message.edit_text(
        f"🚚 Вы выбрали: *{shipping_name}*\n"
        f"💰 Стоимость доставки: *{shipping_price} руб.*\n\n"
        f"💳 Теперь выберите способ оплаты:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_payment_methods_keyboard()
    )
    await state.set_state(ShopStates.waiting_for_payment_method)
    await callback.answer()

@router.callback_query(F.data.startswith("payment_"))
async def payment_method_callback(callback: CallbackQuery, state: FSMContext):
    payment_method = callback.data
    
    payment_names = {
        "payment_telegram": "Telegram Payments",
        "payment_cod": "Наличными при получении",
        "payment_card": "Банковской картой",
        "payment_emoney": "Электронными деньгами"
    }
    
    payment_name = payment_names.get(payment_method, "Неизвестный способ")
    
    await state.update_data(
        payment_method=payment_method,
        payment_name=payment_name
    )
    
    # Получаем данные из состояния
    data = await state.get_data()
    address = data.get('address', 'Не указан')
    shipping_name = data.get('shipping_name', 'Не выбрана')
    shipping_price = data.get('shipping_price', 0)
    
    # Рассчитываем итоговую сумму
    cart_items = get_cart(callback.from_user.id)
    subtotal = sum(item[2] * item[4] for item in cart_items)
    total = subtotal + shipping_price
    
    # Создаем заказ в БД
    products_list = []
    for item in cart_items:
        product_info = {
            'product_id': item[1],
            'name': item[3],
            'quantity': item[2],
            'price': item[4]
        }
        products_list.append(product_info)
    
    order_id = create_order(
        callback.from_user.id,
        products_list,
        total,
        address,
        shipping_name,
        payment_name
    )
    
    # Формируем сообщение с деталями заказа
    items_text = "\n".join([f"• {item[3]} - {item[2]} x {item[4]:.2f} руб." for item in cart_items])
    
    order_text = (
        f"✅ *Заказ оформлен!*\n\n"
        f"📊 *Номер заказа:* #{order_id}\n"
        f"📍 *Адрес:* {address}\n"
        f"🚚 *Доставка:* {shipping_name}\n"
        f"💳 *Оплата:* {payment_name}\n\n"
        f"📦 *Состав заказа:*\n{items_text}\n\n"
        f"💰 *Подытог:* {subtotal:.2f} руб.\n"
        f"🚚 *Доставка:* {shipping_price:.2f} руб.\n"
        f"💰 *Итого к оплате:* *{total:.2f} руб.*\n\n"
    )
    
    if payment_method == "payment_telegram":
        order_text += "💳 Для оплаты нажмите кнопку 'Оплатить сейчас'"
    elif payment_method == "payment_cod":
        order_text += "💵 Оплата при получении наличными или картой"
    elif payment_method == "payment_card":
        order_text += "🏦 Ссылка для оплаты будет отправлена после подтверждения заказа"
    else:
        order_text += "📱 Реквизиты для оплаты будут отправлены после подтверждения"
    
    await callback.message.edit_text(
        order_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_order_confirmation_keyboard(order_id)
    )
    
    # Очищаем корзину
    clear_cart(callback.from_user.id)
    
    await state.clear()
    await callback.answer()

@router.callback_query(F.data.startswith("pay_order_"))
async def pay_order_callback(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[2])
    order = get_order(order_id)
    
    if not order or order[1] != callback.from_user.id:
        await callback.answer("Заказ не найден или не принадлежит вам!", show_alert=True)
        return
    
    if order[7] == "paid":
        await callback.answer("Заказ уже оплачен!", show_alert=True)
        return
    
    # Создаем инвойс для Telegram Payments

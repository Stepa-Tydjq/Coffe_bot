import aiosqlite
from datetime import datetime

DB_PATH = 'coffee.db'


async def init_db():
    """Инициализация базы данных"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id TEXT UNIQUE,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                display_name TEXT,
                auth_date INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Добавляем колонку display_name если её нет
        try:
            await db.execute('ALTER TABLE users ADD COLUMN display_name TEXT')
        except:
            pass

        await db.execute('''
            CREATE TABLE IF NOT EXISTS bulk_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id TEXT,
                user_name TEXT,
                total_price INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        await db.execute('''
            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bulk_order_id INTEGER,
                drink TEXT,
                price INTEGER,
                quantity INTEGER,
                FOREIGN KEY (bulk_order_id) REFERENCES bulk_orders(id)
            )
        ''')

        await db.commit()


async def save_user(telegram_id, username, first_name, last_name, auth_date):
    """Сохранить или обновить пользователя"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            INSERT INTO users (telegram_id, username, first_name, last_name, display_name, auth_date)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                last_name = excluded.last_name,
                auth_date = excluded.auth_date
        ''', (telegram_id, username, first_name, last_name, first_name, auth_date))
        await db.commit()


async def update_user_name(telegram_id, display_name):
    """Обновить отображаемое имя пользователя"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            UPDATE users SET display_name = ? WHERE telegram_id = ?
        ''', (display_name, telegram_id))
        await db.commit()


async def save_bulk_order(telegram_id, user_name, items, total_price):
    """Сохранить групповой заказ и вернуть его ID"""
    async with aiosqlite.connect(DB_PATH) as db:
        # Создаем групповой заказ
        cursor = await db.execute('''
            INSERT INTO bulk_orders (telegram_id, user_name, total_price)
            VALUES (?, ?, ?)
        ''', (telegram_id, user_name, total_price))
        bulk_order_id = cursor.lastrowid

        # Добавляем товары
        for item in items:
            await db.execute('''
                INSERT INTO order_items (bulk_order_id, drink, price, quantity)
                VALUES (?, ?, ?, ?)
            ''', (bulk_order_id, item['drink'], item['price'], item['quantity']))

        await db.commit()
        return bulk_order_id


async def get_user_bulk_orders(telegram_id):
    """Получить групповые заказы пользователя"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('''
            SELECT id, total_price, status, created_at
            FROM bulk_orders
            WHERE telegram_id = ?
            ORDER BY created_at DESC
            LIMIT 20
        ''', (telegram_id,))
        rows = await cursor.fetchall()

        result = []
        for row in rows:
            bulk_id, total_price, status, created_at = row
            items_cursor = await db.execute('''
                SELECT drink, price, quantity
                FROM order_items
                WHERE bulk_order_id = ?
            ''', (bulk_id,))
            items = await items_cursor.fetchall()
            result.append({
                'id': bulk_id,
                'total_price': total_price,
                'status': status,
                'created_at': created_at,
                'items': items
            })
        return result


async def get_all_bulk_orders(limit=20):
    """Получить все групповые заказы"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('''
            SELECT id, telegram_id, user_name, total_price, status, created_at
            FROM bulk_orders
            ORDER BY created_at DESC
            LIMIT ?
        ''', (limit,))
        rows = await cursor.fetchall()

        result = []
        for row in rows:
            bulk_id, telegram_id, user_name, total_price, status, created_at = row
            items_cursor = await db.execute('''
                SELECT drink, price, quantity
                FROM order_items
                WHERE bulk_order_id = ?
            ''', (bulk_id,))
            items = await items_cursor.fetchall()
            result.append({
                'id': bulk_id,
                'telegram_id': telegram_id,
                'user_name': user_name,
                'total_price': total_price,
                'status': status,
                'created_at': created_at,
                'items': items
            })
        return result


async def get_bulk_order_by_id(bulk_order_id):
    """Получить групповой заказ по ID"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('''
            SELECT id, telegram_id, user_name, total_price, status, created_at
            FROM bulk_orders
            WHERE id = ?
        ''', (bulk_order_id,))
        row = await cursor.fetchone()

        if row:
            bulk_id, telegram_id, user_name, total_price, status, created_at = row
            items_cursor = await db.execute('''
                SELECT drink, price, quantity
                FROM order_items
                WHERE bulk_order_id = ?
            ''', (bulk_id,))
            items = await items_cursor.fetchall()
            return {
                'id': bulk_id,
                'telegram_id': telegram_id,
                'user_name': user_name,
                'total_price': total_price,
                'status': status,
                'created_at': created_at,
                'items': items
            }
        return None


async def update_bulk_order_status(bulk_order_id, new_status):
    """Обновить статус группового заказа"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            UPDATE bulk_orders SET status = ? WHERE id = ?
        ''', (new_status, bulk_order_id))
        await db.commit()


async def check_user_exists(telegram_id):
    """Проверить существование пользователя"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            'SELECT id FROM users WHERE telegram_id = ?',
            (telegram_id,)
        )
        row = await cursor.fetchone()
        return row is not None


async def get_user_by_id(telegram_id):
    """Получить пользователя по telegram_id"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            'SELECT id, telegram_id, username, first_name, last_name, display_name, auth_date, created_at FROM users WHERE telegram_id = ?',
            (telegram_id,)
        )
        row = await cursor.fetchone()
        return row
import asyncio
import json
import urllib.parse
from datetime import datetime
from aiohttp import web
from jinja2 import Environment, FileSystemLoader

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

import config
import database

# Инициализация Jinja2 для HTML шаблонов
env = Environment(loader=FileSystemLoader('templates'))


# ============ ОСНОВНОЙ БОТ (для клиентов) ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start для основного бота"""
    user = update.effective_user
    args = context.args

    # Сохраняем пользователя в базу
    await database.save_user(
        str(user.id),
        user.username,
        user.first_name,
        user.last_name,
        int(datetime.now().timestamp())
    )

    # Создаем кнопку, которая открывает сайт ВНУТРИ TELEGRAM (WebApp)
    keyboard = [
        [InlineKeyboardButton("☕ Открыть кофейню", web_app={"url": config.WEBAPP_URL})],
        [InlineKeyboardButton("📋 Мои заказы", callback_data="my_orders")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"☕ Добро пожаловать в CoffeeBot!\n\nПривет, {user.first_name or user.username}!\n\nНажми кнопку ниже, чтобы открыть кофейню. Авторизация произойдет автоматически!",
        reply_markup=reply_markup
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на кнопки для основного бота"""
    query = update.callback_query
    await query.answer()

    if query.data == "my_orders":
        user_id = str(query.from_user.id)
        orders = await database.get_user_bulk_orders(user_id)

        if not orders:
            await query.edit_message_text(
                f"📭 У вас пока нет заказов.\n\n🌐 Сайт: {config.WEBAPP_URL}"
            )
            return

        message = "📋 Ваши заказы:\n\n"
        for order in orders:
            if order['status'] == "pending":
                status_emoji = "⏳"
                status_text = "Готовится"
            elif order['status'] == "ready":
                status_emoji = "✅"
                status_text = "Готов"
            else:
                status_emoji = "⚠️"
                status_text = "Задерживается"

            date = datetime.fromisoformat(order['created_at']).strftime('%d.%m.%Y %H:%M')

            message += f"{status_emoji} Заказ #{order['id']} - {order['total_price']} ₽\n"
            for item in order['items']:
                message += f"   • {item[0]} x{item[2]} - {item[1] * item[2]} ₽\n"
            message += f"   🕐 {date} | {status_emoji} {status_text}\n\n"

        keyboard = [
            [InlineKeyboardButton("🌐 Открыть сайт", url=config.WEBAPP_URL)]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(message, reply_markup=reply_markup)


async def send_bulk_receipt(telegram_id: str, bulk_order_id: int, items: list, total_price: int, user_name: str):
    """Отправить чек пользователю (один чек на весь заказ)"""
    from telegram import Bot
    bot = Bot(token=config.BOT_TOKEN)

    items_text = ""
    for item in items:
        items_text += f"   • {item['drink']} x{item['quantity']} - {item['price'] * item['quantity']} ₽\n"

    message = f"""
🧾 ЧЕК ЗАКАЗА #{bulk_order_id}

👤 Клиент: {user_name}

📋 Состав заказа:
{items_text}
💰 Итого: {total_price} ₽
🕐 Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}

✅ Заказ принят и готовится!
Спасибо, что выбрали нас! 🙏
    """

    keyboard = [
        [InlineKeyboardButton("📋 Мои заказы", callback_data="my_orders")],
        [InlineKeyboardButton("🌐 Открыть кофейню", web_app={"url": config.WEBAPP_URL})]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await bot.send_message(
            chat_id=telegram_id,
            text=message,
            reply_markup=reply_markup
        )
        print(f"✅ Чек отправлен пользователю {telegram_id} (заказ #{bulk_order_id})")
    except Exception as e:
        print(f"❌ Ошибка отправки чека: {e}")


async def send_admin_bulk_notification(bulk_order_id: int, user_telegram_id: str, user_name: str, items: list,
                                       total_price: int):
    """Отправить одно уведомление администратору со всеми позициями"""
    from telegram import Bot
    admin_bot = Bot(token=config.ADMIN_BOT_TOKEN)

    items_text = ""
    for item in items:
        items_text += f"   • {item['drink']} x{item['quantity']} - {item['price'] * item['quantity']} ₽\n"

    message = f"""
🆕 НОВЫЙ ЗАКАЗ #{bulk_order_id}

👤 Клиент: {user_name}
🆔 Telegram ID: {user_telegram_id}

📋 Состав заказа:
{items_text}
💰 Общая сумма: {total_price} ₽
🕐 Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}

📌 Статус: Ожидает обработки
    """

    keyboard = [
        [
            InlineKeyboardButton("✅ Готов", callback_data=f"status_ready_{bulk_order_id}"),
            InlineKeyboardButton("⏳ Готовится", callback_data=f"status_pending_{bulk_order_id}")
        ],
        [
            InlineKeyboardButton("⚠️ Задерживается", callback_data=f"status_delayed_{bulk_order_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await admin_bot.send_message(
            chat_id=config.ADMIN_CHAT_ID,
            text=message,
            reply_markup=reply_markup
        )
        print(f"✅ Уведомление отправлено администратору (заказ #{bulk_order_id})")
    except Exception as e:
        print(f"❌ Ошибка отправки уведомления админу: {e}")


async def send_status_update_to_user(bulk_order_id: int, user_telegram_id: str, items: list, total_price: int,
                                     status: str):
    """Отправить пользователю обновление статуса всего заказа с кнопкой открыть кофейню"""
    from telegram import Bot
    bot = Bot(token=config.BOT_TOKEN)

    if status == "pending":
        status_emoji = "⏳"
        status_text = "Готовится"
    elif status == "ready":
        status_emoji = "✅"
        status_text = "Готов"
    else:
        status_emoji = "⚠️"
        status_text = "Задерживается"

    items_text = ""
    for item in items:
        items_text += f"   • {item['drink']} x{item['quantity']} - {item['price'] * item['quantity']} ₽\n"

    message = f"""
📦 Обновление статуса заказа #{bulk_order_id}

📋 Состав заказа:
{items_text}
💰 Сумма: {total_price} ₽
📌 Статус: {status_emoji} {status_text}

Спасибо, что выбираете нас! 🙏
    """

    keyboard = [
        [InlineKeyboardButton("📋 Мои заказы", callback_data="my_orders")],
        [InlineKeyboardButton("🌐 Открыть кофейню", web_app={"url": config.WEBAPP_URL})]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await bot.send_message(
            chat_id=user_telegram_id,
            text=message,
            reply_markup=reply_markup
        )
        print(f"✅ Обновление статуса отправлено пользователю {user_telegram_id}")
    except Exception as e:
        print(f"❌ Ошибка отправки обновления статуса: {e}")


# ============ АДМИН БОТ ============

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на кнопки в админ боте"""
    query = update.callback_query
    await query.answer()

    data = query.data
    print(f"📩 Получен callback от админа: {data}")

    # Обработка изменения статуса всего заказа
    if data.startswith("status_"):
        parts = data.split("_")
        if len(parts) >= 3:
            status_type = parts[1]
            bulk_order_id = int(parts[2])

            if status_type == "ready":
                new_status = "ready"
                status_text = "Готов"
                status_emoji = "✅"
                is_final = True
            elif status_type == "delayed":
                new_status = "delayed"
                status_text = "Задерживается"
                status_emoji = "⚠️"
                is_final = False
            else:
                new_status = "pending"
                status_text = "Готовится"
                status_emoji = "⏳"
                is_final = False

            # Обновляем статус всего заказа
            await database.update_bulk_order_status(bulk_order_id, new_status)

            # Получаем информацию о заказе
            order = await database.get_bulk_order_by_id(bulk_order_id)
            if order:
                # Отправляем уведомление пользователю
                await send_status_update_to_user(
                    bulk_order_id,
                    order['telegram_id'],
                    [{'drink': item[0], 'price': item[1], 'quantity': item[2]} for item in order['items']],
                    order['total_price'],
                    new_status
                )

                # Формируем текст заказа
                items_text = ""
                for item in order['items']:
                    items_text += f"   • {item[0]} x{item[2]} - {item[1] * item[2]} ₽\n"

                date = datetime.fromisoformat(order['created_at']).strftime('%d.%m.%Y %H:%M')

                if is_final:
                    # Если заказ готов - закрываем, убираем кнопки
                    final_message = f"""
✅ ЗАКАЗ #{bulk_order_id} ЗАКРЫТ

👤 Клиент: {order['user_name']}
🆔 Telegram ID: {order['telegram_id']}

📋 Состав заказа:
{items_text}
💰 Общая сумма: {order['total_price']} ₽
🕐 Время заказа: {date}
📌 Итоговый статус: ✅ ГОТОВ

Заказ выполнен и закрыт.
                    """
                    # Обновляем сообщение без кнопок
                    await query.edit_message_text(text=final_message)
                else:
                    # Нефинальный статус - обновляем сообщение с кнопками
                    new_message = f"""
🆕 ЗАКАЗ #{bulk_order_id} - СТАТУС ОБНОВЛЕН

👤 Клиент: {order['user_name']}
🆔 Telegram ID: {order['telegram_id']}

📋 Состав заказа:
{items_text}
💰 Общая сумма: {order['total_price']} ₽
🕐 Время заказа: {date}
📌 Текущий статус: {status_emoji} {status_text}

Выберите новое действие:
                    """

                    keyboard = [
                        [
                            InlineKeyboardButton("✅ Готов", callback_data=f"status_ready_{bulk_order_id}"),
                            InlineKeyboardButton("⏳ Готовится", callback_data=f"status_pending_{bulk_order_id}")
                        ],
                        [
                            InlineKeyboardButton("⚠️ Задерживается", callback_data=f"status_delayed_{bulk_order_id}")
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)

                    await query.edit_message_text(
                        text=new_message,
                        reply_markup=reply_markup
                    )

    elif data == "refresh_orders":
        orders = await database.get_all_bulk_orders(limit=20)

        if not orders:
            await query.edit_message_text("📭 Нет активных заказов")
            return

        message = "📋 Последние заказы:\n\n"
        for order in orders:
            if order['status'] == "pending":
                status_emoji = "⏳"
            elif order['status'] == "ready":
                status_emoji = "✅"
            else:
                status_emoji = "⚠️"

            date = datetime.fromisoformat(order['created_at']).strftime('%d.%m %H:%M')
            message += f"{status_emoji} #{order['id']} - {order['user_name']} - {order['total_price']}₽ | {date}\n"

        keyboard = [
            [InlineKeyboardButton("🔄 Обновить", callback_data="refresh_orders")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text=message, reply_markup=reply_markup)


async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start для админ бота"""
    user_id = update.effective_user.id

    if user_id != config.ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ У вас нет доступа к этому боту.")
        return

    orders = await database.get_all_bulk_orders(limit=20)

    if not orders:
        await update.message.reply_text(
            f"📭 Нет активных заказов\n\nКогда клиенты сделают заказы, они появятся здесь.\n\n🌐 Сайт: {config.WEBAPP_URL}"
        )
        return

    message = "📋 Последние заказы:\n\n"
    for order in orders:
        if order['status'] == "pending":
            status_emoji = "⏳"
        elif order['status'] == "ready":
            status_emoji = "✅"
        else:
            status_emoji = "⚠️"

        date = datetime.fromisoformat(order['created_at']).strftime('%d.%m %H:%M')
        message += f"{status_emoji} #{order['id']} - {order['user_name']} - {order['total_price']}₽ | {date}\n"

    keyboard = [
        [InlineKeyboardButton("🔄 Обновить", callback_data="refresh_orders")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(text=message, reply_markup=reply_markup)


# ============ ВЕБ-СЕРВЕР ============

async def auth_handler(request):
    """Обработчик авторизации"""
    try:
        data = await request.json()

        telegram_id = str(data.get('id'))
        username = data.get('username', '')
        first_name = data.get('first_name', '')
        last_name = data.get('last_name', '')
        auth_date = data.get('auth_date')

        await database.save_user(telegram_id, username, first_name, last_name, auth_date)

        # Получаем сохраненное имя пользователя
        user = await database.get_user_by_id(telegram_id)
        display_name = user[5] if user and len(user) > 5 else None

        return web.json_response({
            'success': True,
            'telegram_id': telegram_id,
            'user': {
                'id': telegram_id,
                'username': username,
                'first_name': first_name,
                'last_name': last_name,
                'display_name': display_name or first_name or username
            }
        })
    except Exception as e:
        print(f"Auth error: {e}")
        return web.json_response({'error': str(e)}, status=500)


async def update_name_handler(request):
    """Обработчик обновления имени пользователя"""
    try:
        data = await request.json()
        telegram_id = str(data.get('telegram_id'))
        display_name = data.get('display_name', '')

        if not telegram_id:
            return web.json_response({'error': 'Missing telegram_id'}, status=400)

        await database.update_user_name(telegram_id, display_name)

        return web.json_response({'success': True})
    except Exception as e:
        print(f"Update name error: {e}")
        return web.json_response({'error': str(e)}, status=500)


async def bulk_order_handler(request):
    """Обработчик массового заказа (вся корзина одним запросом)"""
    try:
        data = await request.json()
        telegram_id = str(data.get('telegram_id'))
        display_name = data.get('display_name', '')
        items = data.get('items', [])

        if not telegram_id or not items:
            return web.json_response({'error': 'Missing data'}, status=400)

        # Проверяем существование пользователя
        user_exists = await database.check_user_exists(telegram_id)
        if not user_exists:
            return web.json_response({'error': 'User not found'}, status=401)

        # Получаем имя пользователя (используем переданное display_name или из базы)
        if not display_name:
            user = await database.get_user_by_id(telegram_id)
            display_name = user[5] or user[3] or user[2] if user else "Пользователь"

        # Считаем общую сумму
        total_price = sum(item['price'] * item['quantity'] for item in items)

        # Сохраняем групповой заказ
        bulk_order_id = await database.save_bulk_order(telegram_id, display_name, items, total_price)

        if bulk_order_id:
            # Отправляем один чек пользователю
            await send_bulk_receipt(telegram_id, bulk_order_id, items, total_price, display_name)

            # Отправляем одно уведомление администратору
            await send_admin_bulk_notification(bulk_order_id, telegram_id, display_name, items, total_price)

            return web.json_response({'success': True, 'order_id': bulk_order_id})
        else:
            return web.json_response({'error': 'Order failed'}, status=500)

    except Exception as e:
        print(f"Bulk order error: {e}")
        return web.json_response({'error': str(e)}, status=500)


async def index_handler(request):
    """Главная страница"""
    template = env.get_template('index.html')
    html_content = template.render()
    return web.Response(text=html_content, content_type='text/html')


async def start_web_server():
    """Запуск веб-сервера"""
    app = web.Application()
    app.router.add_get('/', index_handler)
    app.router.add_post('/auth/telegram', auth_handler)
    app.router.add_post('/bulk_order', bulk_order_handler)
    app.router.add_post('/update_name', update_name_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', config.PORT)
    await site.start()
    print(f"🌐 Веб-сервер запущен на http://localhost:{config.PORT}")


async def run_main_bot():
    """Запуск основного бота (для клиентов)"""
    application = Application.builder().token(config.BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", start))
    application.add_handler(CallbackQueryHandler(handle_callback))

    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    print("🤖 Основной бот запущен и готов к работе!")

    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()


async def run_admin_bot():
    """Запуск админ бота (для управления заказами)"""
    admin_app = Application.builder().token(config.ADMIN_BOT_TOKEN).build()

    admin_app.add_handler(CommandHandler("start", admin_start))
    admin_app.add_handler(CallbackQueryHandler(admin_callback_handler))

    await admin_app.initialize()
    await admin_app.start()
    await admin_app.updater.start_polling()
    print("🤖 Админ бот запущен и готов к работе!")

    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        await admin_app.updater.stop()
        await admin_app.stop()
        await admin_app.shutdown()


async def main():
    """Главная функция"""
    # Инициализируем базу данных
    await database.init_db()
    print("📁 База данных инициализирована")

    # Запускаем веб-сервер и ботов параллельно
    await asyncio.gather(
        start_web_server(),
        run_main_bot(),
        run_admin_bot()
    )


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Остановка...")
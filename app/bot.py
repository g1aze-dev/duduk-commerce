import json
from telegram.ext import Application
from .config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

application = None

async def init_bot():
    global application
    
    # Проверка наличия токена
    if not TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_TOKEN не задан в переменных окружения")
    
    if not TELEGRAM_CHAT_ID:
        raise ValueError("TELEGRAM_CHAT_ID не задан в переменных окружения")
    
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    await application.initialize()
    await application.start()

async def send_order_notification(order_data: dict):
    global application
    
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram бот не настроен. Уведомление не отправлено.")
        return
    
    if not application:
        await init_bot()
    
    items = json.loads(order_data['items']) if isinstance(order_data['items'], str) else order_data['items']
    items_text = "\n".join([f"  • {i['name']} x{i['quantity']} = {i['price'] * i['quantity']}₽" for i in items])
    
    message = f"""
📦 НОВЫЙ ЗАКАЗ #{order_data['id']}

👤 {order_data['customer_name']}
📞 {order_data['phone']}
📍 {order_data['address']}

🍽️ Заказ:
{items_text}

💰 Сумма: {order_data['total']} ₽
💬 Комментарий: {order_data.get('comment') or 'нет'}

🕐 {order_data['created_at']}
"""
    
    try:
        await application.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
        print(f"✅ Уведомление о заказе #{order_data['id']} отправлено в Telegram")
    except Exception as e:
        print(f"❌ Ошибка отправки уведомления: {e}")
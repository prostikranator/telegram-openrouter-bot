import os
import telebot
from flask import Flask, request
import logging

# Уровень логирования для лучшего отслеживания ошибок
logging.basicConfig(level=logging.INFO)

# --- 1. Инициализация Flask (ОБЯЗАТЕЛЬНО 'app') ---
# Gunicorn ищет эту переменную!
app = Flask(__name__)

# --- 2. Конфигурация Бота и Ключей ---
# Получение токена из переменных среды Render
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
# URL сервиса Render (автоматически предоставляется Render)
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL") 
# Ключ OpenRouter (для AI-запросов)
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY") 

if not TELEGRAM_TOKEN or not RENDER_EXTERNAL_URL or not OPENROUTER_API_KEY:
    logging.error("Не хватает одной или нескольких переменных среды: TELEGRAM_TOKEN, RENDER_EXTERNAL_URL, OPENROUTER_API_KEY.")

# Инициализация объекта бота
bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode='html')
# Уникальный секретный путь, по которому Telegram будет отправлять сообщения
SECRET_ROUTE = '/' + TELEGRAM_TOKEN 

# --- 3. Функции обработки сообщений ---

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    """Отправляет приветственное сообщение."""
    bot.reply_to(message, "Привет! Я бот, работающий через OpenRouter. Отправь мне сообщение!")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    """Обрабатывает все входящие текстовые сообщения."""
    
    # 🚨 ВНИМАНИЕ: ЗДЕСЬ ДОЛЖЕН БЫТЬ ТВОЙ КОД ДЛЯ OPENROUTER
    
    # Пока ты не вставил свой код для OpenRouter, мы будем просто отвечать эхом
    try:
        # Ваш код для запроса к OpenRouter будет здесь
        # response = api_call_to_openrouter(message.text) 
        
        # Заглушка:
        response_text = f"🤖 Ваш запрос: {message.text}. (Нужен код интеграции с OpenRouter)"
        
        bot.reply_to(message, response_text)
        
    except Exception as e:
        logging.error(f"Ошибка при обработке сообщения: {e}")
        bot.reply_to(message, "Произошла ошибка при обработке запроса.")

# --- 4. Маршруты Flask для Webhook ---

@app.route("/", methods=["GET"])
def home():
    """Проверяет, что сервер работает."""
    return "Webhook server is running. Access /setwebhook/ to configure.", 200

@app.route("/setwebhook/", methods=["GET"])
def set_webhook_route():
    """Маршрут для установки Webhook'а в Telegram."""
    try:
        webhook_url = RENDER_EXTERNAL_URL + SECRET_ROUTE
        is_set = bot.set_webhook(url=webhook_url)
        
        if is_set:
            logging.info(f"Webhook успешно установлен на: {webhook_url}")
            return f"Webhook successfully set to: {webhook_url}", 200
        else:
            logging.error("Не удалось установить Webhook.")
            return "Webhook setup failed.", 500
            
    except Exception as e:
        logging.error(f"Ошибка при установке Webhook: {e}")
        return f"Error setting webhook: {e}", 500

@app.route(SECRET_ROUTE, methods=['POST'])
def webhook():
    """Обрабатывает все POST-запросы от Telegram."""
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    else:
        return 'Bad Request', 403

# --- 5. Запуск (Gunicorn будет использовать 'app') ---
if __name__ == "__main__":
    # Локальный запуск (не используется Gunicorn на Render, но полезно для тестирования)
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

import os
import telebot
import requests 
from flask import Flask, request
import logging

# Настраиваем логирование, чтобы видеть ошибки в консоли Render
logging.basicConfig(level=logging.INFO)

# --- 1. Инициализация Flask (ОБЯЗАТЕЛЬНО 'app') ---
# Gunicorn ищет эту переменную!
app = Flask(__name__)

# --- 2. Конфигурация Бота и Ключей ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL") 
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY") 

# Проверка наличия ключей при старте
if not TELEGRAM_TOKEN or not RENDER_EXTERNAL_URL or not OPENROUTER_API_KEY:
    logging.error("Не хватает переменных среды! Проверьте TELEGRAM_TOKEN, RENDER_EXTERNAL_URL, OPENROUTER_API_KEY.")
    # Принудительная остановка, если ключи не заданы (не должно произойти, если ты их задал)
    # raise ValueError("Не установлены обязательные переменные среды.")

# Инициализация объекта бота
bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode='html')
SECRET_ROUTE = '/' + TELEGRAM_TOKEN 

# --- 3. Функции обработки сообщений ---

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    """Отправляет приветственное сообщение."""
    bot.reply_to(message, "Привет! Я бот, работающий через OpenRouter. Отправь мне сообщение!")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    """
    Обрабатывает все входящие текстовые сообщения,
    отправляет их в OpenRouter и обрабатывает ошибки.
    """
    
    # Визуальный ответ в Telegram, пока модель думает
    bot.send_chat_action(message.chat.id, 'typing') 

    try:
        # API endpoint OpenRouter
        url = "https://openrouter.ai/api/v1/chat/completions"
        
        # Заголовки для авторизации
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }
        
        # Данные для отправки в OpenRouter
        data = {
            "model": "mistralai/mistral-7b-instruct", # Можешь изменить модель
            "messages": [
                {"role": "user", "content": message.text}
            ]
        }
        
        # Отправка запроса с таймаутом в 30 секунд
        response = requests.post(url, headers=headers, json=data, timeout=30)
        
        # Проверка HTTP-статуса
        response.raise_for_status() 
        
        # Извлечение текста ответа
        response_data = response.json()
        response_text = response_data['choices'][0]['message']['content']
        
        # Отправка ответа пользователю
        bot.reply_to(message, response_text)
        
    except requests.exceptions.HTTPError as http_err:
        # Ошибка, связанная с API (например, 401, 404, 500)
        logging.error(f"Ошибка HTTP запроса к OpenRouter (статус {http_err.response.status_code}): {http_err.response.text}")
        bot.reply_to(message, "Ошибка API. Проверьте ключ OpenRouter или лимиты.")
    except requests.exceptions.RequestException as req_err:
        # Ошибка сети/таймаута
        logging.error(f"Ошибка запроса к OpenRouter: {req_err}")
        bot.reply_to(message, "Ошибка связи с моделью OpenRouter. Попробуйте позже.")
    except Exception as e:
        # Критическая ошибка (например, ошибка JSON)
        logging.error(f"Критическая ошибка: {e}")
        bot.reply_to(message, f"Произошла внутренняя ошибка: {e}")

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
        # Асинхронная обработка сообщений
        bot.process_new_updates([update])
        return '', 200 # Сразу возвращаем 200, чтобы Telegram не переотправлял запрос
    else:
        return 'Bad Request', 403

# --- 5. Запуск (Gunicorn будет использовать 'app') ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

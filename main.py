import os
import logging
from flask import Flask, request
import telebot
import requests

# === Логирование ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === Переменные среды ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_TOKEN = os.getenv("OPENROUTER_TOKEN")

if not TELEGRAM_TOKEN:
    raise ValueError("❌ TELEGRAM_TOKEN не найден в переменных среды")
if not OPENROUTER_TOKEN:
    raise ValueError("❌ OPENROUTER_TOKEN не найден в переменных среды")

# === Telegram Bot ===
bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

# === Обработка сообщений ===
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_input = message.text.strip()
    logger.info(f"Запрос от @{message.from_user.username}: {user_input}")

    headers = {
        "Authorization": f"Bearer {OPENROUTER_TOKEN}",
        "Content-Type": "application/json"
    }

    data = {
        "model": "openai/gpt-3.5-turbo",
        "messages": [
            {"role": "system", "content": "Ты — умный помощник, отвечай кратко и точно."},
            {"role": "user", "content": user_input}
        ]
    }

    try:
        response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=data, timeout=30)
        response.raise_for_status()
        answer = response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Ошибка OpenRouter: {e}")
        answer = "Ошибка при обращении к OpenRouter API."

    bot.reply_to(message, answer)

# === Flask endpoints ===
@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def telegram_webhook():
    update = request.stream.read().decode("utf-8")
    bot.process_new_updates([telebot.types.Update.de_json(update)])
    return "ok", 200

@app.route("/", methods=["GET"])
def home():
    return "Бот активен", 200

# === Запуск ===
if __name__ == "__main__":
    host = os.getenv("RENDER_EXTERNAL_HOSTNAME", "localhost")
    url = f"https://{host}/{TELEGRAM_TOKEN}"

    try:
        result = bot.set_webhook(url)
        logger.info(f"Webhook установлен: {url}, результат: {result}")
    except Exception as e:
        logger.error(f"Ошибка при установке webhook: {e}")

    app.run(host="0.0.0.0", port=10000)

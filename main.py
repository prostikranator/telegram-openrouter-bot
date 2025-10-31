import os
import logging
import requests
from flask import Flask, request
import telebot

# Настройки логов
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

# Переменные окружения
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL = os.getenv("MODEL", "meta-llama/llama-3.1-8b-instruct:free")

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# Проверка API ключей
logger.info(f"KEYS LOADED. Model: {MODEL}")
logger.info(f"API Key Status: {'SUCCESS' if OPENROUTER_API_KEY else 'FAIL'}")

@app.route("/", methods=["GET"])
def index():
    return "Bot is running"

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    json_update = request.get_json(force=True)
    if not json_update:
        return "No update", 400
    update = telebot.types.Update.de_json(json_update)
    bot.process_new_updates([update])
    return "OK", 200

@app.route("/setwebhook/", methods=["GET"])
def set_webhook():
    url = f"https://{request.host}/{BOT_TOKEN}"
    result = bot.set_webhook(url)
    return {"webhook_url": url, "result": result}, 200

# Основная логика
@bot.message_handler(commands=["start", "help"])
def send_welcome(message):
    bot.reply_to(message, "Бот активен. Отправь текст, и я обработаю его через OpenRouter.")

@bot.message_handler(func=lambda m: True)
def handle_message(message):
    text = message.text.strip()
    response = call_openrouter(text)
    bot.send_message(message.chat.id, response)

def call_openrouter(prompt):
    try:
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}]
        }
        r = requests.post("https://openrouter.ai/api/v1/chat/completions",
                          headers=headers, json=payload, timeout=20)
        data = r.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"Ошибка OpenRouter: {e}")
        return "Ошибка при обращении к OpenRouter."

if __name__ == "__main__":
    logger.info(f"set_webhook called on start. result: {bot.set_webhook(f'https://{os.getenv('RENDER_EXTERNAL_HOSTNAME', 'localhost')}/{BOT_TOKEN}')}")
    app.run(host="0.0.0.0", port=10000)

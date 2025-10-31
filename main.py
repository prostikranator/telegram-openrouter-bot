import os
import logging
import threading
import requests
from flask import Flask, request

import telebot
from telebot import types

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Переменные среды (обязательно задать в Render) ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "mistralai/mistral-7b-instruct")
# полный публичный URL сервиса на Render, например https://имя-app.onrender.com
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")

if not TELEGRAM_TOKEN:
    logger.critical("TELEGRAM_TOKEN не задан. Прекращаю запуск.")
if not OPENROUTER_API_KEY:
    logger.warning("OPENROUTER_API_KEY не задан. Запросы к AI будут давать ошибку.")

# Инициализация Flask и TeleBot
app = Flask(__name__)
bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode="HTML")
SECRET_ROUTE = f"/{TELEGRAM_TOKEN}"

# --- Простая проверка работоспособности ---
@app.route("/", methods=["GET"])
def index():
    return "OK", 200

# --- Установка webhook через специальный маршрут (ручной запуск) ---
@app.route("/setwebhook/", methods=["GET"])
def set_webhook_route():
    if not RENDER_EXTERNAL_URL or not TELEGRAM_TOKEN:
        return "RENDER_EXTERNAL_URL или TELEGRAM_TOKEN не заданы", 500
    webhook_url = RENDER_EXTERNAL_URL.rstrip("/") + SECRET_ROUTE
    try:
        ok = bot.set_webhook(url=webhook_url)
        if ok:
            logger.info(f"Webhook установлен: {webhook_url}")
            return f"Webhook установлен: {webhook_url}", 200
        else:
            logger.error("Ответ телеграма: не удалось установить webhook")
            return "Webhook setup failed", 500
    except Exception as e:
        logger.exception("Ошибка при установке webhook")
        return f"Error: {e}", 500

# --- Обработка входящих webhook POST от Telegram ---
@app.route(SECRET_ROUTE, methods=["POST"])
def telegram_webhook():
    if request.headers.get("content-type") != "application/json":
        return "Bad Request", 400
    try:
        json_string = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_string)
        # обработка в отдельном потоке, чтобы быстро вернуть 200
        threading.Thread(target=bot.process_new_updates, args=([update],), daemon=True).start()
        return "", 200
    except Exception as e:
        logger.exception("Ошибка при обработке webhook")
        return "Error", 500

# --- Простейшие обработчики команд и текста ---
@bot.message_handler(commands=["start", "help"])
def cmd_start(message: types.Message):
    bot.reply_to(message, "Привет. Я бот через OpenRouter. Отправь любое сообщение.")

@bot.message_handler(func=lambda m: True)
def handle_message(message: types.Message):
    logger.info(f"Получено сообщение от {message.chat.id}")
    bot.send_chat_action(message.chat.id, "typing")
    if not OPENROUTER_API_KEY:
        bot.reply_to(message, "Ошибка: OPENROUTER_API_KEY не настроен на сервере.")
        return

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "user", "content": message.text}
        ]
    }
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        resp = requests.post("https://openrouter.ai/api/v1/chat/completions",
                             json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"].strip()
        if not text:
            text = "Пустой ответ от модели."
        bot.reply_to(message, text)
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        logger.error(f"HTTP error from OpenRouter: {status} {e}")
        bot.reply_to(message, f"Ошибка от OpenRouter (код {status}).")
    except Exception as e:
        logger.exception("Ошибка при запросе к OpenRouter")
        bot.reply_to(message, "Ошибка сервера при обработке запроса. Попробуйте позже.")

# --- Автоустановка webhook при старте (если REENDER_EXTERNAL_URL задан) ---
def try_set_webhook_on_start():
    if RENDER_EXTERNAL_URL and TELEGRAM_TOKEN:
        webhook_url = RENDER_EXTERNAL_URL.rstrip("/") + SECRET_ROUTE
        try:
            ok = bot.set_webhook(url=webhook_url)
            logger.info(f"set_webhook called on start. result: {ok} url: {webhook_url}")
        except Exception:
            logger.exception("Не удалось установить webhook при старте.")

# При импорте модуля (gunicorn) запустим попытку установки webhook
try_set_webhook_on_start()

# --- Для локального запуска (не на Render) ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    # если нужно, можно в фоне дернуть set_webhook_route вручную, но мы уже пытались выше
    app.run(host="0.0.0.0", port=port)

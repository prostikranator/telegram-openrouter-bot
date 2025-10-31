import os
import requests
import json
import threading
import logging
import pandas as pd # <-- НОВЫЙ ИМПОРТ ДЛЯ ФОРМАТИРОВАНИЯ
from flask import Flask, request
from telebot import types
import telebot

# Импорт Tinkoff Invest API
from tinkoff.invest import Client, MoneyValue, PortfolioPosition, PortfolioResponse
from tinkoff.invest.exceptions import AioRequestError # Для обработки ошибок API

# --- 1. Настройка логирования и переменных ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
TINKOFF_API_TOKEN = os.getenv("TINKOFF_API_TOKEN") # <-- НОВЫЙ ТОКЕН ТИНЬКОФФ
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "gpt-3.5-turbo")

if not TELEGRAM_TOKEN or not OPENROUTER_API_KEY or not TINKOFF_API_TOKEN:
    logger.critical("❌ КРИТИЧЕСКАЯ ОШИБКА: Не найдены TELEGRAM_TOKEN, OPENROUTER_API_KEY или TINKOFF_API_TOKEN.")
    raise ValueError("Не найдены обязательные переменные среды.")

# --- 2. Инициализация ---
bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode='HTML')
app = Flask(__name__)
SECRET_ROUTE = f"/{TELEGRAM_TOKEN}"

# --- 3. ФУНКЦИЯ: Запрос данных портфеля Тинькофф ---

def to_rubles(money: MoneyValue) -> float:
    """Конвертирует MoneyValue в float рублей."""
    return money.units + money.nano / 1_000_000_000

def get_tinkoff_portfolio() -> str:
    """Получает данные портфеля и форматирует их в таблицу."""
    try:
        with Client(TINKOFF_API_TOKEN) as client:
            # 1. Получаем счета (берем первый попавшийся)
            accounts = client.users.get_accounts().accounts
            if not accounts:
                return "❌ Не удалось найти активных счетов в Тинькофф."
            account_id = accounts[0].id
            
            # 2. Получаем портфель по этому счету
            portfolio: PortfolioResponse = client.operations.get_portfolio(account_id=account_id)
            
            # 3. Форматируем данные
            data = []
            
            # Добавляем общую стоимость активов
            total_value = to_rubles(portfolio.total_amount_portfolio)
            
            # Собираем данные по позициям
            for p in portfolio.positions:
                current_price = to_rubles(p.current_price)
                expected_yield = to_rubles(p.expected_yield)
                
                data.append({
                    'Название': p.name,
                    'Тикер': p.ticker,
                    'Кол-во': p.quantity.units,
                    'Цена (RUB)': f"{current_price:.2f}",
                    'Доходность (%)': f"{expected_yield / (current_price * p.quantity.units) * 100:.2f}" if (current_price * p.quantity.units) else "0.00"
                })

            df = pd.DataFrame(data)
            
            # Форматирование для Telegram (Markdown/HTML)
            header = f"<b>💰 Портфель. Общая стоимость: {total_value:.2f} RUB</b>\n\n"
            
            # Простая таблица в HTML для Telegram
            if not df.empty:
                 table_html = df.to_html(index=False, float_format='%.2f', classes='table table-striped', escape=False)
                 # Преобразуем HTML-таблицу в более читаемый Markdown (или используем Pandas to_markdown, если установлена)
                 # Здесь для простоты вернем текст, используя Pandas to_markdown, если он доступен
                 try:
                     table_text = df.to_markdown(index=False, numalign="left", stralign="left")
                 except ImportError:
                     table_text = df.to_string(index=False)
                 
                 return header + f"<pre>{table_text}</pre>"
            else:
                 return header + "Портфель пуст."

    except AioRequestError as e:
        logger.error(f"Ошибка API Тинькофф: {e}")
        return "⚠️ Ошибка связи с API Тинькофф. Проверьте токен или статус счетов."
    except Exception as e:
        logger.exception("Критическая ошибка при получении портфеля")
        return f"⚠️ Неизвестная ошибка: {e}"

# --- 4. ФУНКЦИЯ OPENROUTER ---

def get_openrouter_response(prompt: str) -> str:
    # ... (Оставляем как было, чтобы не менять рабочую часть) ...
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    data = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": "Ты умный и вежливый Telegram-бот."},
            {"role": "user", "content": prompt},
        ],
    }
    try:
        response = requests.post(url, headers=headers, json=data, timeout=60)
        response.raise_for_status()
        answer = response.json()["choices"][0]["message"]["content"]
        return answer.strip()
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        logger.error(f"HTTP Error from OpenRouter: {status} {e.response.text if e.response is not None else ''}")
        return f"⚠️ Ошибка OpenRouter (Код {status})."
    except Exception as e:
        logger.exception("Критическая ошибка при запросе к OpenRouter")
        return f"⚠️ Ошибка при обращении к OpenRouter: {e}"

# --- 5. ОБРАБОТЧИКИ СООБЩЕНИЙ ---

@bot.message_handler(commands=['start', 'help'])
def cmd_start(message: types.Message):
    bot.reply_to(message, "Привет. Я бот-агент. Используй команду /portfolio для просмотра твоих инвестиций.")

@bot.message_handler(commands=['portfolio'])
def cmd_portfolio(message: types.Message):
    """Новая команда: Запрос портфеля Тинькофф."""
    logger.info(f"Получена команда /portfolio от {message.chat.id}")
    bot.send_chat_action(message.chat.id, 'typing')
    
    # Вызываем функцию получения данных
    report = get_tinkoff_portfolio()
    
    bot.reply_to(message, report)

@bot.message_handler(func=lambda message: True)
def handle_message(message: types.Message):
    """Обработка всех остальных сообщений через OpenRouter."""
    logger.info(f"Получено сообщение для OpenRouter от {message.chat.id}")
    bot.send_chat_action(message.chat.id, 'typing')
    
    user_text = message.text
    reply = get_openrouter_response(user_text)
    
    bot.reply_to(message, reply)


# --- 6. МАРШРУТЫ WEBHook (Остались без изменений, т.к. они уже рабочие) ---

# ... (Оставляем рабочие маршруты Webhook и Flask без изменений) ...
@app.route("/")
def index():
    return "✅ Бот запущен и работает.", 200

@app.route("/setwebhook/")
def set_webhook():
    hostname = os.getenv('RENDER_EXTERNAL_HOSTNAME') 
    if not hostname:
        return "❌ RENDER_EXTERNAL_HOSTNAME не задан.", 500
    webhook_url = f"https://{hostname}{SECRET_ROUTE}"
    try:
        result = bot.set_webhook(url=webhook_url)
        logger.info(f"Webhook set result: {result}. URL: {webhook_url}")
        return {"webhook_url": webhook_url, "result": result}, 200
    except Exception as e:
        logger.exception("Ошибка при установке Webhook")
        return {"error": str(e), "webhook_url": webhook_url}, 500

@app.route(SECRET_ROUTE, methods=["POST"])
def telegram_webhook():
    if request.headers.get("content-type") != "application/json":
        return "Bad Request", 400
    try:
        json_string = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_string)
        # Запуск обработки в отдельном потоке
        threading.Thread(target=bot.process_new_updates, args=([update],), daemon=True).start()
        return "OK", 200
    except Exception as e:
        logger.exception("Ошибка при обработке webhook")
        return "Error", 500

# --- 7. ЗАПУСК ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

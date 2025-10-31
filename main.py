import os
import requests
import json
import threading
import logging
import pandas as pd 
from flask import Flask, request
from telebot import types
import telebot

# --- ИСПРАВЛЕННЫЕ ИМПОРТЫ для установленного пакета tinkoff-investments ---
from tinkoff.investments import Client, MoneyValue, PortfolioResponse
from tinkoff.investments.exceptions import RequestError 

# --- 1. Настройка логирования и переменных ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
TINKOFF_API_TOKEN = os.getenv("TINKOFF_API_TOKEN") 
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "gpt-3.5-turbo")

if not TELEGRAM_TOKEN or not OPENROUTER_API_KEY or not TINKOFF_API_TOKEN:
    logger.critical("❌ КРИТИЧЕСКАЯ ОШИБКА: Не найдены все обязательные токены.")
    raise ValueError("Не найдены обязательные переменные среды.")

# --- 2. Инициализация ---
bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode='HTML')
app = Flask(__name__)
SECRET_ROUTE = f"/{TELEGRAM_TOKEN}"

# --- 3. ФУНКЦИЯ: Запрос данных портфеля Тинькофф (СИНХРОННАЯ) ---

def to_rubles(money: MoneyValue) -> float:
    """Конвертирует MoneyValue в float рублей."""
    return money.units + money.nano / 1_000_000_000

def get_tinkoff_portfolio() -> str:
    """Получает данные портфеля и форматирует их в таблицу."""
    try:
        # Используем синхронный Client
        with Client(TINKOFF_API_TOKEN) as client: 
            # 1. Получаем счета (берем первый попавшийся)
            accounts = client.users.get_accounts().accounts
            if not accounts:
                return "❌ Не удалось найти активных счетов в Тинькофф."
            account_id = accounts[0].id
            
            # 2. Получаем портфель
            portfolio: PortfolioResponse = client.operations.get_portfolio(account_id=account_id)
            
            # 3. Форматируем данные
            data = []
            total_value = to_rubles(portfolio.total_amount_portfolio)
            
            for p in portfolio.positions:
                # ВНИМАНИЕ: Для пакета tinkoff-investments мы не можем использовать p.name, 
                # поэтому используем p.ticker. Поле 'Название' временно удалено.
                
                expected_yield_value = to_rubles(p.expected_yield) if p.expected_yield else 0
                current_price = to_rubles(p.current_price)
                
                # Некоторые поля могут быть None, если нет активных позиций.
                if p.quantity is None or p.quantity.units == 0:
                    continue 

                total_position_value = current_price * p.quantity.units
                
                data.append({
                    'Тикер': p.ticker,
                    'Тип': p.instrument_type,
                    'Кол-во': p.quantity.units,
                    'Цена (RUB)': f"{current_price:.2f}",
                    'Доходность (%)': f"{expected_yield_value / total_position_value * 100:.2f}" if total_position_value else "0.00"
                })

            df = pd.DataFrame(data)
            header = f"<b>💰 Портфель. Общая стоимость: {total_value:.2f} RUB</b>\n\n"
            
            if not df.empty:
                 # Используем to_markdown для форматирования таблицы в Telegram
                 table_text = df.to_markdown(index=False, numalign="left", stralign="left")
                 return header + f"<pre>{table_text}</pre>"
            else:
                 return header + "Портфель пуст."

    except RequestError as e:
        logger.error(f"Ошибка API Тинькофф (RequestError): {e}")
        return "⚠️ Ошибка связи с API Тинькофф. Проверьте токен или статус счетов."
    except Exception as e:
        logger.exception("Критическая ошибка при получении портфеля")
        return f"⚠️ Неизвестная ошибка при получении портфеля: {e}"

# --- 4. ФУНКЦИЯ OPENROUTER (без изменений) ---

def get_openrouter_response(prompt: str) -> str:
    """Отправляет запрос к OpenRouter."""
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

# --- 5. ОБРАБОТЧИКИ СООБЩЕНИЙ (без изменений) ---

@bot.message_handler(commands=['start', 'help'])
def cmd_start(message: types.Message):
    bot.reply_to(message, "Привет. Я бот-агент. Используй команду /portfolio для просмотра твоих инвестиций.")

@bot.message_handler(commands=['portfolio'])
def cmd_portfolio(message: types.Message):
    """Команда: Запрос портфеля Тинькофф."""
    logger.info(f"Получена команда /portfolio от {message.chat.id}")
    bot.send_chat_action(message.chat.id, 'typing')
    
    # Вызываем СИНХРОННУЮ функцию
    report = get_tinkoff_portfolio()
    
    bot.reply_to(message, report)

@bot.message_handler(func=lambda message: True)
def handle_message(message: types.Message):
    """Обработка всех остальных сообщений через OpenRouter. Выполняется в потоке."""
    logger.info(f"Получено сообщение для OpenRouter от {message.chat.id}")
    bot.send_chat_action(message.chat.id, 'typing')
    
    user_text = message.text
    reply = get_openrouter_response(user_text)
    
    bot.reply_to(message, reply)


# --- 6. МАРШРУТЫ WEBHook (без изменений) ---

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
    """Главный маршрут: запускает всю обработку в отдельном потоке."""
    if request.headers.get("content-type") != "application/json":
        return "Bad Request", 400
    try:
        json_string = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_string)
        # Запуск обработки в отдельном потоке (ВСЕГДА ДЕЛАЕМ ЭТО!)
        threading.Thread(target=bot.process_new_updates, args=([update],), daemon=True).start()
        return "OK", 200
    except Exception as e:
        logger.exception("Ошибка при обработке webhook")
        return "Error", 500

# --- 7. ЗАПУСК ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

import telebot
from telebot import types
import mercadopago
import requests
import sqlite3
import os
import time
import threading

# ================== CONFIG ==================
BOT_TOKEN = os.getenv("BOT_TOKEN")
MP_TOKEN = os.getenv("MP_ACCESS_TOKEN")
SIMS_API_KEY = os.getenv("SIMS_API_KEY")

bot = telebot.TeleBot(BOT_TOKEN)
sdk = mercadopago.SDK(MP_TOKEN)

# ================== BANCO ==================
conn = sqlite3.connect("db.sqlite", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    saldo REAL DEFAULT 0
)
""")
conn.commit()

# ================== PREÇOS (LUCRO EMBUTIDO) ==================
PRICES = {
    "br": {
        "telegram": 6.99,
        "whatsapp": 9.99
    },
    "us": {
        "telegram": 4.99,
        "whatsapp": 7.99
    },
    "ru": {
        "telegram": 3.99
    },
    "mx": {
        "telegram": 4.49
    }
}

COUNTRY_LABELS = {
    "br": "🇧🇷 Brasil",
    "us": "🇺🇸 EUA",
    "ru": "🇷🇺 Rússia",
    "mx": "🇲🇽 México"
}

SERVICE_LABELS = {
    "telegram": "✈️ Telegram",
    "whatsapp": "💬 WhatsApp"
}

user_flow = {}

# ================== MENU ==================
def menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("💰 Saldo", "💳 Recarregar")
    kb.add("📱 Comprar Número", "🤝 Afiliados")
    return kb

# ================== START ==================
@bot.message_handler(commands=["start"])
def start(msg):
    uid = msg.chat.id
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (uid,))
    conn.commit()
    bot.send_message(uid, "🤖 *SMS Brasil Bot*", parse_mode="Markdown", reply_markup=menu())

# ================== SALDO ==================
@bot.message_handler(func=lambda m: m.text == "💰 Saldo")
def saldo(msg):
    cursor.execute("SELECT saldo FROM users WHERE user_id=?", (msg.chat.id,))
    s = cursor.fetchone()[0]
    bot.send_message(msg.chat.id, f"💰 Seu saldo: R$ {s:.2f}", reply_markup=menu())

# ================== PIX ==================
@bot.message_handler(func=lambda m: m.text == "💳 Recarregar")
def recarregar(msg):
    kb = types.InlineKeyboardMarkup()
    for v in [10, 20, 50]:
        kb.add(types.InlineKeyboardButton(f"💸 R$ {v}", callback_data=f"pix_{v}"))
    bot.send_message(msg.chat.id, "💳 Escolha o valor:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("pix_"))
def gerar_pix(call):
    valor = float(call.data.split("_")[1])
    uid = call.message.chat.id

    p = sdk.payment().create({
        "transaction_amount": valor,
        "payment_method_id": "pix",
        "description": "Recarga SMS Brasil",
        "payer": {"email": "cliente@email.com"}
    })["response"]

    pix = p["point_of_interaction"]["transaction_data"]["qr_code"]
    bot.send_message(uid, f"💳 PIX R$ {valor:.2f}\n\n`{pix}`", parse_mode="Markdown")

    threading.Thread(target=confirmar_pix, args=(p["id"], uid, valor)).start()

def confirmar_pix(pid, uid, valor):
    while True:
        time.sleep(10)
        if sdk.payment().get(pid)["response"]["status"] == "approved":
            cursor.execute("UPDATE users SET saldo = saldo + ? WHERE user_id=?", (valor, uid))
            conn.commit()
            bot.send_message(uid, f"✅ Pagamento confirmado!\n💰 +R$ {valor:.2f}", reply_markup=menu())
            break

# ================== COMPRA NUMERO ==================
@bot.message_handler(func=lambda m: m.text == "📱 Comprar Número")
def escolher_pais(msg):
    kb = types.InlineKeyboardMarkup()
    for c in PRICES:
        kb.add(types.InlineKeyboardButton(COUNTRY_LABELS[c], callback_data=f"pais_{c}"))
    bot.send_message(msg.chat.id, "🌍 Escolha o país:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("pais_"))
def escolher_servico(call):
    pais = call.data.split("_")[1]
    user_flow[call.message.chat.id] = {"pais": pais}

    kb = types.InlineKeyboardMarkup()
    for s in PRICES[pais]:
        price = PRICES[pais][s]
        kb.add(types.InlineKeyboardButton(f"{SERVICE_LABELS[s]} – R$ {price}", callback_data=f"serv_{s}"))
    bot.send_message(call.message.chat.id, "📲 Escolha o serviço:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("serv_"))
def comprar(call):
    uid = call.message.chat.id
    serv = call.data.split("_")[1]
    pais = user_flow[uid]["pais"]
    price = PRICES[pais][serv]

    cursor.execute("SELECT saldo FROM users WHERE user_id=?", (uid,))
    saldo = cursor.fetchone()[0]

    if saldo < price:
        bot.send_message(uid, "❌ Saldo insuficiente.", reply_markup=menu())
        return

    url = f"https://5sim.net/v1/user/buy/activation/{serv}/{pais}/any"
    headers = {"Authorization": f"Bearer {SIMS_API_KEY}"}
    r = requests.get(url, headers=headers, timeout=30)

    if r.status_code != 200:
        bot.send_message(uid, "❌ Serviço indisponível na 5SIM.")
        return

    data = r.json()
    cursor.execute("UPDATE users SET saldo = saldo - ? WHERE user_id=?", (price, uid))
    conn.commit()

    bot.send_message(uid, f"📞 *Número:* `{data['phone']}`\n⏳ Aguardando SMS...", parse_mode="Markdown")

    threading.Thread(target=aguardar_sms, args=(uid, data["id"])).start()

# ================== RECEBER SMS ==================
def aguardar_sms(uid, act_id):
    url = f"https://5sim.net/v1/user/check/{act_id}"
    headers = {"Authorization": f"Bearer {SIMS_API_KEY}"}

    for _ in range(30):
        time.sleep(10)
        r = requests.get(url, headers=headers).json()
        if r["status"] == "RECEIVED":
            sms = r["sms"][0]["code"]
            bot.send_message(uid, f"📩 *SMS recebido:*\n`{sms}`", parse_mode="Markdown", reply_markup=menu())
            return

    bot.send_message(uid, "⌛ Tempo esgotado. Nenhum SMS recebido.", reply_markup=menu())

# ================== RUN ==================
print("🤖 SMS Brasil Bot ONLINE")
bot.infinity_polling(skip_pending=True)

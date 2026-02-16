import telebot
from telebot import types
import mercadopago
import requests
import sqlite3
import os
import base64
import time
import threading

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

cursor.execute("""
CREATE TABLE IF NOT EXISTS pagamentos (
    payment_id INTEGER,
    user_id INTEGER,
    valor REAL,
    confirmado INTEGER DEFAULT 0
)
""")
conn.commit()

def get_user(user_id):
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()

def get_saldo(user_id):
    cursor.execute("SELECT saldo FROM users WHERE user_id=?", (user_id,))
    return cursor.fetchone()[0]

# ================== MENU ==================
def menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("💰 Saldo", "💳 Recarregar")
    kb.row("📱 Comprar Número", "🤝 Afiliados")
    return kb

@bot.message_handler(commands=["start"])
def start(msg):
    get_user(msg.from_user.id)
    bot.send_message(
        msg.chat.id,
        "🤖 *SmsBrasilBot*\n\nEscolha uma opção:",
        reply_markup=menu(),
        parse_mode="Markdown"
    )

# ================== SALDO ==================
@bot.message_handler(func=lambda m: m.text == "💰 Saldo")
def saldo(msg):
    s = get_saldo(msg.from_user.id)
    bot.send_message(msg.chat.id, f"💰 Seu saldo: R$ {s:.2f}", reply_markup=menu())

# ================== RECARGA ==================
@bot.message_handler(func=lambda m: m.text == "💳 Recarregar")
def recarregar(msg):
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("R$ 10", callback_data="pix_10"),
        types.InlineKeyboardButton("R$ 20", callback_data="pix_20"),
        types.InlineKeyboardButton("R$ 50", callback_data="pix_50"),
    )
    kb.add(types.InlineKeyboardButton("⬅️ Voltar", callback_data="voltar"))
    bot.send_message(msg.chat.id, "Escolha o valor da recarga:", reply_markup=kb)

# ================== PIX ==================
def criar_pix(valor, user_id):
    p = sdk.payment().create({
        "transaction_amount": float(valor),
        "description": f"Recarga SmsBrasilBot {user_id}",
        "payment_method_id": "pix",
        "payer": {"email": f"user{user_id}@smsbrasil.bot"}
    })

    if p["status"] != 201:
        return None

    r = p["response"]
    cursor.execute(
        "INSERT INTO pagamentos (payment_id, user_id, valor) VALUES (?, ?, ?)",
        (r["id"], user_id, valor)
    )
    conn.commit()

    return {
        "id": r["id"],
        "qr": r["point_of_interaction"]["transaction_data"]["qr_code"],
        "img": r["point_of_interaction"]["transaction_data"]["qr_code_base64"]
    }

@bot.callback_query_handler(func=lambda c: c.data.startswith("pix_"))
def pix_handler(call):
    valor = int(call.data.split("_")[1])
    pix = criar_pix(valor, call.from_user.id)

    if not pix:
        bot.send_message(call.message.chat.id, "❌ Erro ao gerar Pix.")
        return

    bot.send_photo(
        call.message.chat.id,
        photo=base64.b64decode(pix["img"]),
        caption=f"💳 *Pix R$ {valor},00*\n\n`{pix['qr']}`",
        parse_mode="Markdown"
    )

# ================== CONFIRMAÇÃO AUTOMÁTICA ==================
def verificar_pagamentos():
    while True:
        cursor.execute("SELECT payment_id, user_id, valor FROM pagamentos WHERE confirmado=0")
        for pid, uid, valor in cursor.fetchall():
            p = sdk.payment().get(pid)
            if p["response"]["status"] == "approved":
                cursor.execute("UPDATE users SET saldo = saldo + ? WHERE user_id=?", (valor, uid))
                cursor.execute("UPDATE pagamentos SET confirmado=1 WHERE payment_id=?", (pid,))
                conn.commit()
                bot.send_message(uid, f"✅ Pagamento confirmado!\n💰 Saldo atualizado: R$ {get_saldo(uid):.2f}")
        time.sleep(10)

threading.Thread(target=verificar_pagamentos, daemon=True).start()

# ================== 5SIM ==================
def comprar_numero():
    try:
        url = "https://5sim.net/v1/user/buy/activation"

        headers = {
            "Authorization": f"Bearer {SIMS_API_KEY}",
            "Accept": "application/json"
        }

        params = {
            "country": "brazil",
            "operator": "any",
            "product": "telegram"
        }

        r = requests.get(url, headers=headers, params=params, timeout=30)

        print("📡 5sim status:", r.status_code)
        print("📡 5sim resposta:", r.text)

        if r.status_code != 200:
            return None

        data = r.json()

        if "phone" not in data:
            return None

        return {
            "id": data["id"],
            "phone": data["phone"]
        }

    except Exception as e:
        print("❌ Erro 5sim:", e)
        return None
# ================== AFILIADOS ==================
@bot.message_handler(func=lambda m: m.text == "🤝 Afiliados")
def afiliados(msg):
    bot.send_message(
        msg.chat.id,
        f"🤝 *Programa de Afiliados*\n\n🔗 https://t.me/SmsBrasilBot?start={msg.from_user.id}",
        parse_mode="Markdown",
        reply_markup=menu()
    )

# ================== VOLTAR ==================
@bot.callback_query_handler(func=lambda c: c.data == "voltar")
def voltar(call):
    bot.send_message(call.message.chat.id, "Menu principal:", reply_markup=menu())

# ================== START BOT ==================
if __name__ == "__main__":
    print("🤖 Bot SMS Brasil iniciado (Railway)")

    while True:
        try:
            bot.infinity_polling(
                timeout=60,
                long_polling_timeout=60,
                skip_pending=True
            )
        except Exception as e:
            print("⚠️ Erro no polling, reiniciando em 5s:", e)
            time.sleep(5)

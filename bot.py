import os
import time
import threading
import mercadopago
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# =============================
# VARIÁVEIS DE AMBIENTE
# =============================
BOT_TOKEN = os.getenv("BOT_TOKEN")
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")
SIM5_API_KEY = os.getenv("SIM5_API_KEY")

bot = telebot.TeleBot(BOT_TOKEN)
mp = mercadopago.SDK(MP_ACCESS_TOKEN)

# =============================
# DADOS EM MEMÓRIA (simples)
# =============================
users = {}
payments = {}

# =============================
# FUNÇÕES AUXILIARES
# =============================
def get_user(user_id):
    if user_id not in users:
        users[user_id] = {
            "saldo": 0.0,
            "ref": None,
            "ganhos_ref": 0.0
        }
    return users[user_id]

def menu_principal():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("💰 Saldo", callback_data="saldo"),
        InlineKeyboardButton("💳 Recarregar", callback_data="recarregar"),
        InlineKeyboardButton("📱 Comprar Número", callback_data="comprar"),
        InlineKeyboardButton("🤝 Afiliados", callback_data="afiliados"),
    )
    return kb

# =============================
# START
# =============================
@bot.message_handler(commands=["start"])
def start(msg):
    user = get_user(msg.from_user.id)

    if " " in msg.text:
        ref = msg.text.split(" ")[1]
        if ref.isdigit() and int(ref) != msg.from_user.id:
            user["ref"] = int(ref)

    bot.send_message(
        msg.chat.id,
        "🤖 *SmsBrasilBot*\n\nEscolha uma opção:",
        reply_markup=menu_principal(),
        parse_mode="Markdown"
    )

# =============================
# CALLBACKS
# =============================
@bot.callback_query_handler(func=lambda c: True)
def callbacks(call):
    user = get_user(call.from_user.id)

    if call.data == "menu":
        bot.edit_message_text(
            "🏠 Menu principal:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=menu_principal()
        )

    elif call.data == "saldo":
        bot.edit_message_text(
            f"💰 *Seu saldo:* R$ {user['saldo']:.2f}",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("⬅ Voltar", callback_data="menu")
            ),
            parse_mode="Markdown"
        )

    elif call.data == "recarregar":
        kb = InlineKeyboardMarkup()
        kb.add(
            InlineKeyboardButton("R$ 10", callback_data="pix_10"),
            InlineKeyboardButton("R$ 20", callback_data="pix_20"),
            InlineKeyboardButton("R$ 50", callback_data="pix_50"),
        )
        kb.add(InlineKeyboardButton("⬅ Voltar", callback_data="menu"))

        bot.edit_message_text(
            "💳 *Escolha o valor da recarga:*",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=kb,
            parse_mode="Markdown"
        )

    elif call.data.startswith("pix_"):
        valor = float(call.data.split("_")[1])

        preference = {
            "items": [{
                "title": "Recarga SmsBrasilBot",
                "quantity": 1,
                "unit_price": valor
            }],
            "payment_methods": {
                "excluded_payment_types": [{"id": "ticket"}],
                "installments": 1
            }
        }

        pref = mp.preference().create(preference)
        pref_id = pref["response"]["id"]

        payments[pref_id] = {
            "user_id": call.from_user.id,
            "valor": valor
        }

        bot.send_message(
            call.message.chat.id,
            f"💳 *Pague o Pix abaixo:*\n\n{pref['response']['init_point']}\n\n⏳ Aguardando pagamento...",
            parse_mode="Markdown"
        )

    elif call.data == "afiliados":
        bot.edit_message_text(
            f"🤝 *Programa de Afiliados*\n\n"
            f"• Comissão: 10%\n"
            f"• Seu link:\n"
            f"https://t.me/{bot.get_me().username}?start={call.from_user.id}",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("⬅ Voltar", callback_data="menu")
            ),
            parse_mode="Markdown"
        )

    elif call.data == "comprar":
        bot.edit_message_text(
            "📱 *Compra de número*\n\n⚠ Em breve: integração 5sim ativa.",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("⬅ Voltar", callback_data="menu")
            ),
            parse_mode="Markdown"
        )

# =============================
# VERIFICADOR DE PAGAMENTO
# =============================
def verificar_pagamentos():
    while True:
        for pref_id, data in list(payments.items()):
            payment = mp.preference().get(pref_id)
            status = payment["response"]["items"][0]["title"]

            if payment["response"]["status"] == "approved":
                user = get_user(data["user_id"])
                user["saldo"] += data["valor"]

                if user["ref"]:
                    ref_user = get_user(user["ref"])
                    ref_user["saldo"] += data["valor"] * 0.10

                del payments[pref_id]

        time.sleep(10)

# =============================
# START BOT
# =============================
threading.Thread(target=verificar_pagamentos, daemon=True).start()
bot.infinity_polling()

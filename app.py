"""
Bot Telegram — boutique intégrée, en mode WEBHOOK (compatible plan gratuit Render).
Pas de librairie python-telegram-bot ici : on parle directement à l'API Telegram
avec `requests`, et Flask reçoit les messages via un "Web Service" (gratuit).

Fichiers du projet :
    app.py            <- ce fichier
    requirements.txt
"""

import os
import requests
from flask import Flask, request

app = Flask(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "COLLE_TON_TOKEN_ICI")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# --- Catalogue -------------------------------------------------------------

CATEGORIES = ["Streaming", "Jeux", "VPN", "Avantages", "Autre"]

PRODUCTS = {
    "p1": {"name": "Netflix Premium — 1 mois", "cat": "Streaming", "price": 6},
    "p2": {"name": "Spotify Premium — 1 mois", "cat": "Streaming", "price": 4},
    "p3": {"name": "Valorant — 5000 VP", "cat": "Jeux", "price": 35},
    "p4": {"name": "Xbox Game Pass Ultimate — 3 mois", "cat": "Jeux", "price": 29},
    "p5": {"name": "NordVPN — 1 an", "cat": "VPN", "price": 39},
    "p6": {"name": "ExpressVPN — 6 mois", "cat": "VPN", "price": 45},
    "p7": {"name": "Carte cadeau Amazon — 25€", "cat": "Avantages", "price": 25},
    "p8": {"name": "Discord Nitro — 1 mois", "cat": "Avantages", "price": 8},
    "p9": {"name": "Support prioritaire", "cat": "Autre", "price": 5},
}

CARTS: dict[int, dict[str, int]] = {}


def get_cart(chat_id: int) -> dict[str, int]:
    return CARTS.setdefault(chat_id, {})


# --- Appels bruts à l'API Telegram -----------------------------------------

def tg_call(method: str, payload: dict):
    requests.post(f"{API_URL}/{method}", json=payload, timeout=10)


def send_message(chat_id, text, keyboard=None, parse_mode=None):
    payload = {"chat_id": chat_id, "text": text}
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    tg_call("sendMessage", payload)


def edit_message(chat_id, message_id, text, keyboard=None, parse_mode=None):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text}
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    tg_call("editMessageText", payload)


def answer_callback(callback_id, text=None, alert=False):
    payload = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text
        payload["show_alert"] = alert
    tg_call("answerCallbackQuery", payload)


# --- Écrans (mêmes menus qu'avant) ------------------------------------------

def kb_categories():
    rows = [[{"text": c, "callback_data": f"cat:{c}"}] for c in CATEGORIES]
    rows.append([{"text": "🛒 Mon panier", "callback_data": "cart"}])
    return rows


def kb_products(cat):
    rows = [
        [{"text": f"{p['name']} — {p['price']}€", "callback_data": f"add:{pid}"}]
        for pid, p in PRODUCTS.items() if p["cat"] == cat
    ]
    rows.append([{"text": "⬅️ Catégories", "callback_data": "menu"}])
    return rows


def cart_view(chat_id):
    cart = get_cart(chat_id)
    if not cart:
        return "Ton panier est vide.", [[{"text": "⬅️ Catégories", "callback_data": "menu"}]]

    lines = ["🛒 Ton panier\n"]
    total = 0
    for pid, qty in cart.items():
        p = PRODUCTS[pid]
        line_total = p["price"] * qty
        total += line_total
        lines.append(f"• {p['name']} x{qty} — {line_total}€")
    lines.append(f"\nTotal : {total}€")

    rows = [
        [{"text": "✅ Commander", "callback_data": "checkout"}],
        [{"text": "🗑 Vider", "callback_data": "clear"}],
        [{"text": "⬅️ Catégories", "callback_data": "menu"}],
    ]
    return "\n".join(lines), rows


# --- Routes Flask ------------------------------------------------------------

@app.route("/")
def health():
    return "Bot en ligne."


@app.route(f"/webhook/{BOT_TOKEN}", methods=["POST"])
def webhook():
    update = request.get_json(force=True)

    if "message" in update:
        chat_id = update["message"]["chat"]["id"]
        text = update["message"].get("text", "")
        if text.startswith("/start"):
            send_message(chat_id, "Bienvenue 👋\nChoisis une catégorie :", kb_categories())

    elif "callback_query" in update:
        cq = update["callback_query"]
        chat_id = cq["message"]["chat"]["id"]
        message_id = cq["message"]["message_id"]
        data = cq["data"]
        answer_callback(cq["id"])

        if data == "menu":
            edit_message(chat_id, message_id, "Choisis une catégorie :", kb_categories())

        elif data.startswith("cat:"):
            cat = data.split(":", 1)[1]
            edit_message(chat_id, message_id, f"📂 {cat}", kb_products(cat))

        elif data.startswith("add:"):
            pid = data.split(":", 1)[1]
            cart = get_cart(chat_id)
            cart[pid] = cart.get(pid, 0) + 1
            answer_callback(cq["id"], f"Ajouté : {PRODUCTS[pid]['name']}")

        elif data == "cart":
            text, kb = cart_view(chat_id)
            edit_message(chat_id, message_id, text, kb)

        elif data == "clear":
            CARTS[chat_id] = {}
            text, kb = cart_view(chat_id)
            edit_message(chat_id, message_id, text, kb)

        elif data == "checkout":
            cart = get_cart(chat_id)
            if not cart:
                answer_callback(cq["id"], "Panier vide.", alert=True)
            else:
                total = sum(PRODUCTS[pid]["price"] * qty for pid, qty in cart.items())
                edit_message(
                    chat_id, message_id,
                    f"✅ Commande enregistrée — total {total}€.\n"
                    "Un vendeur va te contacter pour le paiement et la livraison.",
                )
                CARTS[chat_id] = {}

    return "ok"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

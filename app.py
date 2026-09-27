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

# ID de chat Telegram du vendeur/admin, pour recevoir les commandes.
# Pour l'obtenir : parle à @userinfobot sur Telegram, il te renvoie ton ID.
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "")

# --- Textes du bot (modifie ici pour changer ce que le bot dit) ------------

SHOP_NAME = "🛍 Tenhebreux Shop"

TEXT_WELCOME = (
    f"*{SHOP_NAME}*\n"
    "Comptes premium, abonnements IA, streaming, VPN — et boost Telegram / TikTok. "
    "Payé en crypto, livré direct dans ce chat.\n\n"
    "*Comment ça marche :*\n"
    "1️⃣ Choisis une catégorie\n"
    "2️⃣ Ajoute ce qu'il te faut au panier (🛒 en bas de la liste)\n"
    "3️⃣ Commande, paie en crypto, reçois ton accès\n\n"
    "👇 On commence par quoi ?"
)
TEXT_EMPTY_CART = "Ton panier est vide."
TEXT_CART_TITLE = "🛒 *Ton panier*\n"
TEXT_ORDER_CONFIRM = (
    "✅ *Commande enregistrée* — total {total}\n\n"
    "Pour finaliser, envoie le paiement à l'une de ces adresses "
    "_(appuie longtemps pour copier)_ :\n\n"
    "{payment_info}\n\n"
    "Puis envoie une capture du paiement ici, un vendeur confirme et livre sous peu."
)

# Coordonnées affichées au client après une commande.
# Chaque adresse est en `code` : un appui long dessus la copie directement.
PAYMENT_INFO = (
    "Ξ ETH : `0xEd62F9bbB932028ab48FF810ca2902beee2DFd92`\n"
    "◎ SOL : `3j3EGmk6cqXwp9noZX1vR7kqvoWPbnURg2RCoPWryrJT`\n"
    "₿ BTC : `bc1qamsdcq4zrdsqadztlz40m5zzurpqrva3dv45g3`\n"
    "Ł LTC : `Li3fSXPaaB7dbv3eTJ7JczdgbYqqp9n1B6`\n\n"
    "Réf. à indiquer : ton pseudo Telegram"
)


def fmt(price: float) -> str:
    """Affiche un prix sans zéro inutile : 5 -> '5€', 0.5 -> '0.50€'."""
    return f"{int(price)}€" if price == int(price) else f"{price:.2f}€"



# --- Catalogue -------------------------------------------------------------

CATEGORIES = ["Telegram", "TikTok", "Comptes & Abonnements"]

PRODUCTS = {
    # --- Telegram services (prix pour 1000 unités) ---
    "tg1": {"name": "Members (1K)", "cat": "Telegram", "price": 3},
    "tg2": {"name": "Views (1K)", "cat": "Telegram", "price": 0.50},
    "tg3": {"name": "Reactions (1K)", "cat": "Telegram", "price": 0.75},

    # --- TikTok services (prix pour 1000 unités) ---
    "tt1": {"name": "Followers (1K)", "cat": "TikTok", "price": 5},
    "tt2": {"name": "Views (1K)", "cat": "TikTok", "price": 0.50},
    "tt3": {"name": "Likes (1K)", "cat": "TikTok", "price": 2},
    "tt4": {"name": "Favorites (1K)", "cat": "TikTok", "price": 0.50},
    "tt5": {"name": "Shares (1K)", "cat": "TikTok", "price": 0.50},
    "tt6": {"name": "Custom Comments (1K)", "cat": "TikTok", "price": 15},

    # --- Comptes & abonnements ---
    "a01": {"name": "Gmail Access FA", "cat": "Comptes & Abonnements", "sub": "Mail", "price": 2},
    "a02": {"name": "Outlook Mail", "cat": "Comptes & Abonnements", "sub": "Mail", "price": 0.10},
    "a03": {"name": "NotLetters Mail", "cat": "Comptes & Abonnements", "sub": "Mail", "price": 0.10},
    "a04": {"name": "Netflix 4K Key", "cat": "Comptes & Abonnements", "sub": "Streaming", "price": 5},
    "a05": {"name": "YouTube Premium", "cat": "Comptes & Abonnements", "sub": "Streaming", "price": 3.10},
    "a06": {"name": "Disney+", "cat": "Comptes & Abonnements", "sub": "Streaming", "price": 1.50},
    "a07": {"name": "Molotov TV", "cat": "Comptes & Abonnements", "sub": "Streaming", "price": 1},
    "a08": {"name": "Prime Video", "cat": "Comptes & Abonnements", "sub": "Streaming", "price": 2},
    "a09": {"name": "Prime Video 6 mois", "cat": "Comptes & Abonnements", "sub": "Streaming", "price": 5.60},
    "a10": {"name": "Crunchyroll", "cat": "Comptes & Abonnements", "sub": "Streaming", "price": 0.20},
    "a11": {"name": "Crunchyroll Mega Fan", "cat": "Comptes & Abonnements", "sub": "Streaming", "price": 0.49},
    "a12": {"name": "Paramount+", "cat": "Comptes & Abonnements", "sub": "Streaming", "price": 0.36},
    "a13": {"name": "Spotify", "cat": "Comptes & Abonnements", "sub": "Musique & Audio", "price": 10},
    "a14": {"name": "Deezer", "cat": "Comptes & Abonnements", "sub": "Musique & Audio", "price": 0.42},
    "a15": {"name": "Canva Pro", "cat": "Comptes & Abonnements", "sub": "Outils", "price": 4.70},
    "a16": {"name": "CapCut Pro", "cat": "Comptes & Abonnements", "sub": "Outils", "price": 1.10},
    "a17": {"name": "CapCut Pro FA", "cat": "Comptes & Abonnements", "sub": "Outils", "price": 3.90},
    "a18": {"name": "Duolingo", "cat": "Comptes & Abonnements", "sub": "Outils", "price": 0.30},
    "a19": {"name": "Mullvad VPN", "cat": "Comptes & Abonnements", "sub": "VPN", "price": 5},
    "a20": {"name": "Cyberghost VPN", "cat": "Comptes & Abonnements", "sub": "VPN", "price": 5},
    "a21": {"name": "NordVPN", "cat": "Comptes & Abonnements", "sub": "VPN", "price": 1.24},
    "a22": {"name": "Surfshark", "cat": "Comptes & Abonnements", "sub": "VPN", "price": 3.20},
    "a23": {"name": "ChatGPT Plus", "cat": "Comptes & Abonnements", "sub": "IA", "price": 10},
    "a24": {"name": "Claude API 500 USD", "cat": "Comptes & Abonnements", "sub": "IA", "price": 25},
    "a25": {"name": "Claude API 100 USD", "cat": "Comptes & Abonnements", "sub": "IA", "price": 10},
    "a26": {"name": "Claude Max x20", "cat": "Comptes & Abonnements", "sub": "IA", "price": 150},
    "a27": {"name": "Claude Max x5", "cat": "Comptes & Abonnements", "sub": "IA", "price": 60},
    "a28": {"name": "Claude Pro", "cat": "Comptes & Abonnements", "sub": "IA", "price": 10},
    "a29": {"name": "Perplexity AI Pro", "cat": "Comptes & Abonnements", "sub": "IA", "price": 10},
    "a30": {"name": "Grok AI", "cat": "Comptes & Abonnements", "sub": "IA", "price": 13},
    "a31": {"name": "Gemini Pro+", "cat": "Comptes & Abonnements", "sub": "IA", "price": 5.60},
    "a32": {"name": "ElevenLabs Creator", "cat": "Comptes & Abonnements", "sub": "Musique & Audio", "price": 4.50},
    "a33": {"name": "Microsoft 365", "cat": "Comptes & Abonnements", "sub": "Outils", "price": 10},
    "a34": {"name": "Blinkist Premium", "cat": "Comptes & Abonnements", "sub": "Musique & Audio", "price": 3},
    "a35": {"name": "Fox One", "cat": "Comptes & Abonnements", "sub": "Streaming", "price": 2.90},
    "a36": {"name": "MLB", "cat": "Comptes & Abonnements", "sub": "Streaming", "price": 4.90},
    "a37": {"name": "Curiosity Stream", "cat": "Comptes & Abonnements", "sub": "Streaming", "price": 6.30},
}

# Catégories qui ont un second niveau de menu (sous-catégories).
SUBCATEGORIES = {
    "Comptes & Abonnements": ["Streaming", "Musique & Audio", "IA", "VPN", "Mail", "Outils"],
}

# --- Stock -------------------------------------------------------------
# Les services Telegram/TikTok (tg*/tt*) sont générés à la demande : stock illimité,
# pas d'entrée ici. Les comptes/clés (a*) ont un stock limité — 5 par défaut au
# départ, à ajuster avec /stock (voir la liste) et /restock <id> <quantité>.
STOCK: dict[str, int] = {pid: 5 for pid in PRODUCTS if pid.startswith("a")}

SEUIL_STOCK_BAS = 3  # en dessous de ce nombre, affiche "plus que X en stock"


def stock_of(pid: str):
    """None = illimité (service SMM). Un entier = nombre de comptes restants."""
    return STOCK.get(pid)


def in_stock(pid: str, qty: int = 1) -> bool:
    s = stock_of(pid)
    return s is None or s >= qty


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


def kb_subcats(cat):
    rows = [
        [{"text": s, "callback_data": f"sub:{cat}:{s}"}]
        for s in SUBCATEGORIES[cat]
    ]
    rows.append([{"text": "⬅️ Catégories", "callback_data": "menu"}])
    return rows


def kb_products(cat, sub=None):
    items = [
        (pid, p) for pid, p in PRODUCTS.items()
        if p["cat"] == cat and (sub is None or p.get("sub") == sub)
    ]
    rows = []
    for pid, p in items:
        s = stock_of(pid)
        label = f"{p['name']} — {fmt(p['price'])}"
        if s == 0:
            label = f"❌ {p['name']} — Rupture"
            cb = "oos"
        else:
            if s is not None and s <= SEUIL_STOCK_BAS:
                label += f" (plus que {s})"
            cb = f"add:{pid}"
        rows.append([{"text": label, "callback_data": cb}])
    back = f"cat:{cat}" if sub else "menu"
    back_label = "⬅️ Sous-catégories" if sub else "⬅️ Catégories"
    rows.append([{"text": back_label, "callback_data": back}])
    return rows


def cart_view(chat_id):
    cart = get_cart(chat_id)
    if not cart:
        return TEXT_EMPTY_CART, [[{"text": "⬅️ Catégories", "callback_data": "menu"}]]

    lines = [TEXT_CART_TITLE]
    total = 0
    for pid, qty in cart.items():
        p = PRODUCTS[pid]
        line_total = p["price"] * qty
        total += line_total
        lines.append(f"• {p['name']} x{qty} — {fmt(line_total)}")
    lines.append(f"\nTotal : {fmt(total)}")

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

        is_admin = ADMIN_CHAT_ID and str(chat_id) == str(ADMIN_CHAT_ID)

        if text.startswith("/start"):
            send_message(chat_id, TEXT_WELCOME, kb_categories(), parse_mode="Markdown")

        elif is_admin and text.startswith("/stock"):
            lines = [
                f"• {PRODUCTS[pid]['name']} : {qty}"
                for pid, qty in sorted(STOCK.items())
            ]
            send_message(chat_id, "📦 *Stock actuel*\n\n" + "\n".join(lines), parse_mode="Markdown")

        elif is_admin and text.startswith("/restock"):
            parts = text.split()
            if len(parts) != 3 or parts[1] not in STOCK or not parts[2].lstrip("-").isdigit():
                send_message(
                    chat_id,
                    "Usage : `/restock <id> <quantité à ajouter>`\n"
                    "Ex. `/restock a04 10` ajoute 10 au stock de a04.\n"
                    "Tape /stock pour voir les id.",
                    parse_mode="Markdown",
                )
            else:
                pid, delta = parts[1], int(parts[2])
                STOCK[pid] = max(0, STOCK[pid] + delta)
                send_message(chat_id, f"✅ {PRODUCTS[pid]['name']} : stock mis à {STOCK[pid]}.")

    elif "callback_query" in update:
        cq = update["callback_query"]
        chat_id = cq["message"]["chat"]["id"]
        message_id = cq["message"]["message_id"]
        data = cq["data"]

        if data == "menu":
            answer_callback(cq["id"])
            edit_message(chat_id, message_id, f"*{SHOP_NAME}*\nChoisis une catégorie 👇", kb_categories(), parse_mode="Markdown")

        elif data.startswith("cat:"):
            answer_callback(cq["id"])
            cat = data.split(":", 1)[1]
            if cat in SUBCATEGORIES:
                edit_message(chat_id, message_id, f"📂 *{cat}*", kb_subcats(cat), parse_mode="Markdown")
            else:
                edit_message(chat_id, message_id, f"📂 *{cat}*", kb_products(cat), parse_mode="Markdown")

        elif data.startswith("sub:"):
            answer_callback(cq["id"])
            _, cat, sub = data.split(":", 2)
            edit_message(chat_id, message_id, f"📂 *{cat}* · {sub}", kb_products(cat, sub), parse_mode="Markdown")

        elif data == "oos":
            answer_callback(cq["id"], "Ce produit est en rupture de stock.", alert=True)

        elif data.startswith("add:"):
            pid = data.split(":", 1)[1]
            cart = get_cart(chat_id)
            wanted = cart.get(pid, 0) + 1
            if not in_stock(pid, wanted):
                left = stock_of(pid)
                answer_callback(cq["id"], f"Stock insuffisant — il ne reste que {left}.", alert=True)
            else:
                cart[pid] = wanted
                answer_callback(cq["id"], f"Ajouté : {PRODUCTS[pid]['name']}")

        elif data == "cart":
            answer_callback(cq["id"])
            text, kb = cart_view(chat_id)
            edit_message(chat_id, message_id, text, kb, parse_mode="Markdown")

        elif data == "clear":
            answer_callback(cq["id"])
            CARTS[chat_id] = {}
            text, kb = cart_view(chat_id)
            edit_message(chat_id, message_id, text, kb, parse_mode="Markdown")

        elif data == "checkout":
            cart = get_cart(chat_id)
            if not cart:
                answer_callback(cq["id"], "Panier vide.", alert=True)
            else:
                total = sum(PRODUCTS[pid]["price"] * qty for pid, qty in cart.items())
                answer_callback(cq["id"])

                # Décrémente le stock des articles limités (comptes/clés).
                for pid, qty in cart.items():
                    if pid in STOCK:
                        STOCK[pid] = max(0, STOCK[pid] - qty)

                # Message au client avec les coordonnées de paiement.
                edit_message(
                    chat_id, message_id,
                    TEXT_ORDER_CONFIRM.format(total=fmt(total), payment_info=PAYMENT_INFO),
                    parse_mode="Markdown",
                )

                # Notification au vendeur avec le détail de la commande.
                if ADMIN_CHAT_ID:
                    user = cq["from"]
                    username = f"@{user['username']}" if user.get("username") else user.get("first_name", "client")
                    detail = "\n".join(
                        f"• {PRODUCTS[pid]['name']} x{qty} — {fmt(PRODUCTS[pid]['price'] * qty)}"
                        for pid, qty in cart.items()
                    )
                    send_message(
                        ADMIN_CHAT_ID,
                        f"🆕 *Nouvelle commande* — {username} (id `{chat_id}`)\n\n"
                        f"{detail}\n\n*Total : {fmt(total)}*\n\n"
                        "_En attente du paiement, à confirmer manuellement._",
                        parse_mode="Markdown",
                    )

                CARTS[chat_id] = {}

    return "ok"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

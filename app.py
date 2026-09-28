"""
Bot Telegram — boutique intégrée, en mode WEBHOOK (compatible plan gratuit Render).
Pas de librairie python-telegram-bot ici : on parle directement à l'API Telegram
avec `requests`, et Flask reçoit les messages via un "Web Service" (gratuit).

Fichiers du projet :
    app.py            <- ce fichier
    requirements.txt
"""

import os
import sqlite3
import requests
from datetime import datetime, timezone
from flask import Flask, request

app = Flask(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "COLLE_TON_TOKEN_ICI")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ID de chat Telegram du vendeur/admin, pour recevoir les commandes.
# Pour l'obtenir : parle à @userinfobot sur Telegram, il te renvoie ton ID.
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "")

# Image d'accueil : lien direct (https://...jpg) ou file_id Telegram.
# À mettre dans les variables d'environnement Render : WELCOME_IMAGE
WELCOME_IMAGE = os.environ.get("WELCOME_IMAGE", "")

# --- Textes du bot (modifie ici pour changer ce que le bot dit) ------------

SHOP_NAME = "𖤐 TENHEBREUX"

TEXT_WELCOME = (
    f"🖤 *Bienvenue chez {SHOP_NAME}*\n"
    "━━━━━━━━━━━━━━━\n\n"
    "🚀 *Fais grimper ta présence en ligne*\n"
    "✈️ Telegram · 🎵 TikTok · 🔐 Abonnements\n\n"
    "💎 *Tarifs bas, catalogue clair*\n"
    "Tout est affiché avec le prix, sans surprise.\n\n"
    "⚡ *Commande en 3 étapes*\n"
    "1️⃣ Choisis tes produits\n"
    "2️⃣ Règle en crypto (ETH · SOL · BTC · LTC)\n"
    "3️⃣ Un vendeur confirme et te livre\n\n"
    "🔎 Suis ta commande en direct depuis le bot.\n\n"
    "👇 *Choisis une catégorie pour commencer*"
)
TEXT_EMPTY_CART = (
    "🛒 *Ton panier est vide*\n\n"
    "Rien ici pour l'instant, mais ça se remplit vite 😉\n"
    "Parcours la boutique et ajoute ce qui t'intéresse."
)
TEXT_CART_TITLE = "🛒 *Ton panier*\n━━━━━━━━━━━━━━━\n"
TEXT_ORDER_CONFIRM = (
    "🎉 *Commande enregistrée !*\n"
    "━━━━━━━━━━━━━━━\n\n"
    "📦 Commande *#{order_id}*\n"
    "💰 Total à régler : *{total}*\n\n"
    "💳 *Comment payer*\n"
    "Envoie le montant exact à l'une de ces adresses "
    "_(appui long sur l'adresse pour la copier)_ :\n\n"
    "{payment_info}\n\n"
    "📸 *Ensuite*\n"
    "Envoie ici une capture du paiement. Un vendeur vérifie, confirme "
    "et traite ta commande. Tu reçois une notification à chaque étape.\n\n"
    "🔎 Suivi disponible dans *Mes commandes*."
)

# Messages envoyés au client quand le vendeur change le statut.
STATUS_MESSAGES = {
    "paid": "💳 *Paiement reçu, merci !*\nTa commande est validée et passe bientôt en traitement.",
    "processing": "⚙️ *Ta commande est en cours de traitement.*\nOn s'en occupe, tu seras prévenu dès qu'elle est prête.",
    "completed": "✅ *Ta commande est terminée !*\nMerci pour ta confiance 🖤 N'hésite pas à revenir.",
    "cancelled": "❌ *Ta commande a été annulée.*\nUn souci ? Contacte le vendeur avec ton numéro de commande.",
}

# Textes d'accueil des catégories.
CAT_TEXT = {
    "Telegram": (
        "✈️ *Telegram*\n\n"
        "🚀 Booste ton canal ou ton groupe\n"
        "💎 Prix pour 1 000 unités\n\n"
        "_choisis ton service_ 👇"
    ),
    "TikTok": (
        "🎵 *TikTok*\n\n"
        "🔥 Fais grimper ton compte\n"
        "💎 Prix pour 1 000 unités\n\n"
        "_choisis ton service_ 👇"
    ),
}

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

# --- Base de données des commandes -----------------------------------------
DB_PATH = os.environ.get("DB_PATH", "orders.db")


def db_connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db_connect()
    conn.execute("""CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER NOT NULL,
        username TEXT,
        total REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending_payment',
        created_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        product_id TEXT NOT NULL,
        product_name TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        unit_price REAL NOT NULL,
        FOREIGN KEY(order_id) REFERENCES orders(id)
    )""")
    conn.commit()
    conn.close()


init_db()


def create_order(telegram_id, username, cart, total):
    conn = db_connect()
    cur = conn.execute(
        "INSERT INTO orders (telegram_id, username, total, status, created_at) VALUES (?, ?, ?, ?, ?)",
        (telegram_id, username, total, "pending_payment", datetime.now(timezone.utc).isoformat()),
    )
    order_id = cur.lastrowid
    for pid, qty in cart.items():
        product = PRODUCTS[pid]
        conn.execute(
            "INSERT INTO order_items (order_id, product_id, product_name, quantity, unit_price) VALUES (?, ?, ?, ?, ?)",
            (order_id, pid, product["name"], qty, product["price"]),
        )
    conn.commit()
    conn.close()
    return order_id


def get_orders(telegram_id, limit=10):
    conn = db_connect()
    rows = conn.execute("SELECT * FROM orders WHERE telegram_id = ? ORDER BY id DESC LIMIT ?", (telegram_id, limit)).fetchall()
    conn.close()
    return rows


def get_order(order_id, telegram_id):
    conn = db_connect()
    row = conn.execute("SELECT * FROM orders WHERE id = ? AND telegram_id = ?", (order_id, telegram_id)).fetchone()
    conn.close()
    return row


def get_order_by_id(order_id):
    conn = db_connect()
    row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    conn.close()
    return row


def update_order_status(order_id, status):
    if status not in ORDER_STATUSES:
        return False
    conn = db_connect()
    cur = conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def get_profile_stats(telegram_id):
    conn = db_connect()
    row = conn.execute(
        """SELECT
            COUNT(*) AS total_orders,
            COALESCE(SUM(total), 0) AS total_spent,
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed_orders,
            SUM(CASE WHEN status IN ('pending_payment', 'paid', 'processing') THEN 1 ELSE 0 END) AS active_orders,
            SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled_orders
           FROM orders WHERE telegram_id = ?""",
        (telegram_id,),
    ).fetchone()
    conn.close()
    return row


def get_order_items(order_id):
    conn = db_connect()
    rows = conn.execute("SELECT * FROM order_items WHERE order_id = ? ORDER BY id", (order_id,)).fetchall()
    conn.close()
    return rows


ORDER_STATUSES = {
    "pending_payment": "🟡 En attente de paiement",
    "paid": "💳 Paiement reçu",
    "processing": "⚙️ En traitement",
    "completed": "✅ Terminée",
    "cancelled": "❌ Annulée",
}


def profile_view(chat_id):
    stats = get_profile_stats(chat_id)
    orders = get_orders(chat_id, limit=3)
    active = stats["active_orders"] or 0
    lines = [
        "👤 *Mon profil*",
        "━━━━━━━━━━━━━━━",
        "",
        f"📦 Commandes : *{stats['total_orders']}*",
        f"✅ Terminées : *{stats['completed_orders'] or 0}*",
        f"⚙️ En cours : *{active}*",
        f"❌ Annulées : *{stats['cancelled_orders'] or 0}*",
        f"💰 Total dépensé : *{fmt(stats['total_spent'] or 0)}*",
    ]
    if orders:
        lines += ["", "🕘 *Dernières commandes*"]
        for order in orders:
            status = ORDER_STATUSES.get(order["status"], order["status"])
            lines.append(f"• #{order['id']:05d} · {fmt(order['total'])} · {status}")
    else:
        lines += ["", "_Aucune commande pour le moment. Ta première t'attend en boutique 🛍_"]
    rows = [
        [{"text": "📦 Mes commandes", "callback_data": "orders"}],
        [{"text": "🔄 Actualiser", "callback_data": "profile"}],
        [{"text": "🏠 Boutique", "callback_data": "menu"}],
    ]
    return "\n".join(lines), rows


def get_cart(chat_id: int) -> dict[str, int]:
    return CARTS.setdefault(chat_id, {})


def orders_view(chat_id):
    orders = get_orders(chat_id)
    if not orders:
        return "📦 *Mes commandes*\n━━━━━━━━━━━━━━━\n\nAucune commande pour le moment.\n_Passe ta première commande depuis la boutique._ 🛍", [[{"text": "🛍 Boutique", "callback_data": "menu"}]]
    lines = ["📦 *Mes commandes*", "━━━━━━━━━━━━━━━", ""]
    rows = []
    for order in orders:
        status = ORDER_STATUSES.get(order["status"], order["status"])
        lines.append(f"*#{order['id']:05d}* · {fmt(order['total'])} · {status}")
        rows.append([{"text": f"📦 #{order['id']:05d} — {fmt(order['total'])}", "callback_data": f"order:{order['id']}"}])
    rows.append([{"text": "⬅️ Boutique", "callback_data": "menu"}])
    return "\n".join(lines), rows


def order_detail_view(order_id, chat_id):
    order = get_order(order_id, chat_id)
    if not order:
        return "Commande introuvable.", [[{"text": "⬅️ Mes commandes", "callback_data": "orders"}]]
    items = get_order_items(order_id)
    lines = [f"📦 *Commande #{order['id']:05d}*", "━━━━━━━━━━━━━━━", "", f"*Statut :* {ORDER_STATUSES.get(order['status'], order['status'])}", ""]
    for item in items:
        lines.append(f"• {item['product_name']} x{item['quantity']} — {fmt(item['unit_price'] * item['quantity'])}")
    lines += ["", f"*Total : {fmt(order['total'])}*", f"📅 {order['created_at'].replace('T', ' ')[:16]} UTC"]
    rows = [
        [{"text": "🔄 Actualiser le suivi", "callback_data": f"track:{order_id}"}],
        [{"text": "⬅️ Mes commandes", "callback_data": "orders"}],
        [{"text": "🏠 Boutique", "callback_data": "menu"}],
    ]
    return "\n".join(lines), rows


def admin_order_keyboard(order_id):
    return [
        [{"text": "💳 Payée", "callback_data": f"adminstatus:{order_id}:paid"},
         {"text": "⚙️ Traitement", "callback_data": f"adminstatus:{order_id}:processing"}],
        [{"text": "✅ Terminée", "callback_data": f"adminstatus:{order_id}:completed"},
         {"text": "❌ Annulée", "callback_data": f"adminstatus:{order_id}:cancelled"}],
    ]


def admin_order_text(order_id):
    order = get_order_by_id(order_id)
    if not order:
        return "❌ Commande introuvable."
    items = get_order_items(order_id)
    detail = "\n".join(
        f"• {item['product_name']} x{item['quantity']} — {fmt(item['unit_price'] * item['quantity'])}"
        for item in items
    )
    status = ORDER_STATUSES.get(order["status"], order["status"])
    return (
        f"📦 *Commande #{order_id:05d}*\n"
        f"👤 {order['username'] or 'Client'} — id `{order['telegram_id']}`\n\n"
        f"{detail}\n\n"
        f"*Total : {fmt(order['total'])}*\n"
        f"*Statut :* {status}"
    )


# --- Appels bruts à l'API Telegram -----------------------------------------

def tg_call(method: str, payload: dict):
    """Appelle l'API Telegram et renvoie la réponse JSON ({} en cas d'erreur)."""
    try:
        r = requests.post(f"{API_URL}/{method}", json=payload, timeout=10)
        return r.json()
    except Exception:
        return {}


def send_message(chat_id, text, keyboard=None, parse_mode=None):
    payload = {"chat_id": chat_id, "text": text}
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    return tg_call("sendMessage", payload)


def send_home(chat_id):
    """Écran d'accueil : image + texte + menu si WELCOME_IMAGE est défini, sinon texte seul."""
    kb = kb_categories(chat_id)
    if WELCOME_IMAGE:
        r = tg_call("sendPhoto", {
            "chat_id": chat_id,
            "photo": WELCOME_IMAGE,
            "caption": TEXT_WELCOME,
            "parse_mode": "Markdown",
            "reply_markup": {"inline_keyboard": kb},
        })
        if r.get("ok"):
            return
    send_message(chat_id, TEXT_WELCOME, kb, parse_mode="Markdown")


def edit_message(chat_id, message_id, text, keyboard=None, parse_mode=None):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text}
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    r = tg_call("editMessageText", payload)
    # Si le message d'origine est une photo (accueil), on ne peut pas l'éditer en texte :
    # on le supprime et on renvoie un message texte à la place.
    if not r.get("ok") and "no text" in str(r.get("description", "")).lower():
        tg_call("deleteMessage", {"chat_id": chat_id, "message_id": message_id})
        send_message(chat_id, text, keyboard, parse_mode)


def answer_callback(callback_id, text=None, alert=False):
    payload = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text
        payload["show_alert"] = alert
    tg_call("answerCallbackQuery", payload)


# --- Écrans (mêmes menus qu'avant) ------------------------------------------

CATEGORY_LABELS = {
    "Telegram": "✈️ Telegram",
    "TikTok": "🎵 TikTok",
    "Comptes & Abonnements": "🔐 Comptes & Abonnements",
}


def cart_count(chat_id):
    return sum(get_cart(chat_id).values())


def kb_categories(chat_id=None):
    rows = [
        [{"text": CATEGORY_LABELS.get(c, c), "callback_data": f"cat:{c}"}]
        for c in CATEGORIES
    ]
    count = cart_count(chat_id) if chat_id is not None else 0
    cart_label = f"🛒 Panier · {count}" if count else "🛒 Panier vide"
    rows.append([{"text": cart_label, "callback_data": "cart"}])
    rows.append([{"text": "📦 Mes commandes", "callback_data": "orders"}])
    rows.append([{"text": "👤 Mon profil", "callback_data": "profile"}])
    return rows


SUBCAT_LABELS = {
    "Streaming": "📺 Streaming",
    "Musique & Audio": "🎧 Musique & Audio",
    "IA": "🤖 IA",
    "VPN": "🛡 VPN",
    "Mail": "✉️ Mail",
    "Outils": "🧰 Outils",
}


def kb_subcats(cat):
    rows = [
        [{"text": SUBCAT_LABELS.get(s, s), "callback_data": f"sub:{cat}:{s}"}]
        for s in SUBCATEGORIES[cat]
    ]
    rows.append([{"text": "🛒 Panier", "callback_data": "cart"}])
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
    rows.append([{"text": "🛒 Panier", "callback_data": "cart"}])
    rows.append([{"text": back_label, "callback_data": back}])
    return rows


def cart_view(chat_id):
    cart = get_cart(chat_id)
    if not cart:
        return TEXT_EMPTY_CART, [
            [{"text": "🛍 Boutique", "callback_data": "menu"}],
            [{"text": "📦 Mes commandes", "callback_data": "orders"}],
        ]

    lines = [TEXT_CART_TITLE]
    total = 0
    for pid, qty in cart.items():
        p = PRODUCTS[pid]
        line_total = p["price"] * qty
        total += line_total
        lines.append(f"• {p['name']} x{qty} — {fmt(line_total)}")
    lines.append(f"\n━━━━━━━━━━━━━━━\n💰 *Total : {fmt(total)}*")
    lines.append("\n_Vérifie ton panier puis valide pour recevoir les infos de paiement._")

    rows = [
        [{"text": "✅ Valider ma commande", "callback_data": "checkout"}],
        [{"text": "🗑 Vider le panier", "callback_data": "clear"}],
        [{"text": "🛍 Continuer mes achats", "callback_data": "menu"}],
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
            send_home(chat_id)

        elif text.startswith("/commandes"):
            text_orders, kb = orders_view(chat_id)
            send_message(chat_id, text_orders, kb, parse_mode="Markdown")

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
            # On supprime l'ancien message puis on réaffiche l'accueil (avec l'image).
            tg_call("deleteMessage", {"chat_id": chat_id, "message_id": message_id})
            send_home(chat_id)

        elif data.startswith("cat:"):
            answer_callback(cq["id"])
            cat = data.split(":", 1)[1]
            title = CAT_TEXT.get(cat, f"📂 *{cat}*")
            if cat in SUBCATEGORIES:
                edit_message(chat_id, message_id, title, kb_subcats(cat), parse_mode="Markdown")
            else:
                edit_message(chat_id, message_id, title, kb_products(cat), parse_mode="Markdown")

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
                answer_callback(cq["id"], f"✅ Ajouté au panier : {PRODUCTS[pid]['name']}")
                # Mise à jour discrète du clavier pour afficher le nombre d'articles dans le panier.
                cat = PRODUCTS[pid]["cat"]
                sub = PRODUCTS[pid].get("sub")
                if sub:
                    title = f"📂 *{cat}* · {sub}"
                else:
                    title = CAT_TEXT.get(cat, f"📂 *{cat}*")
                edit_message(chat_id, message_id, title, kb_products(cat, sub), parse_mode="Markdown")

        elif data.startswith("adminstatus:"):
            # Seul le chat admin peut modifier le statut d'une commande.
            if not (ADMIN_CHAT_ID and str(chat_id) == str(ADMIN_CHAT_ID)):
                answer_callback(cq["id"], "Accès refusé.", alert=True)
            else:
                parts = data.split(":", 2)
                try:
                    order_id = int(parts[1])
                except (ValueError, IndexError):
                    answer_callback(cq["id"], "Commande invalide.", alert=True)
                else:
                    new_status = parts[2] if len(parts) > 2 else ""
                    order = get_order_by_id(order_id)
                    if not order or new_status not in ORDER_STATUSES:
                        answer_callback(cq["id"], "Commande ou statut invalide.", alert=True)
                    elif order["status"] == new_status:
                        answer_callback(cq["id"], "Ce statut est déjà appliqué.")
                    elif update_order_status(order_id, new_status):
                        answer_callback(cq["id"], "Statut mis à jour.")
                        edit_message(chat_id, message_id, admin_order_text(order_id), admin_order_keyboard(order_id), parse_mode="Markdown")
                        # Le client reçoit immédiatement le nouveau statut.
                        client_id = order["telegram_id"]
                        send_message(
                            client_id,
                            f"🔔 *Commande #{order_id:05d}*\n\n"
                            f"{STATUS_MESSAGES.get(new_status, ORDER_STATUSES[new_status])}",
                            [[{"text": "🔎 Suivre ma commande", "callback_data": f"order:{order_id}"}]],
                            parse_mode="Markdown",
                        )
                    else:
                        answer_callback(cq["id"], "Impossible de mettre à jour la commande.", alert=True)

        elif data.startswith("track:"):
            answer_callback(cq["id"])
            try:
                order_id = int(data.split(":", 1)[1])
            except ValueError:
                answer_callback(cq["id"], "Commande invalide.", alert=True)
            else:
                text, kb = order_detail_view(order_id, chat_id)
                edit_message(chat_id, message_id, text, kb, parse_mode="Markdown")

        elif data == "profile":
            answer_callback(cq["id"])
            text, kb = profile_view(chat_id)
            edit_message(chat_id, message_id, text, kb, parse_mode="Markdown")

        elif data == "orders":
            answer_callback(cq["id"])
            text, kb = orders_view(chat_id)
            edit_message(chat_id, message_id, text, kb, parse_mode="Markdown")

        elif data.startswith("order:"):
            answer_callback(cq["id"])
            try:
                order_id = int(data.split(":", 1)[1])
            except ValueError:
                answer_callback(cq["id"], "Commande invalide.", alert=True)
            else:
                text, kb = order_detail_view(order_id, chat_id)
                edit_message(chat_id, message_id, text, kb, parse_mode="Markdown")

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

                user = cq["from"]
                username = f"@{user['username']}" if user.get('username') else user.get('first_name', "client")
                order_id = create_order(chat_id, username, cart, total)

                # Décrémente le stock des articles limités (comptes/clés).
                for pid, qty in cart.items():
                    if pid in STOCK:
                        STOCK[pid] = max(0, STOCK[pid] - qty)

                edit_message(
                    chat_id, message_id,
                    TEXT_ORDER_CONFIRM.format(order_id=f"{order_id:05d}", total=fmt(total), payment_info=PAYMENT_INFO),
                    [[{"text": "📦 Voir mes commandes", "callback_data": "orders"}],
                     [{"text": "🏠 Boutique", "callback_data": "menu"}]],
                    parse_mode="Markdown",
                )

                if ADMIN_CHAT_ID:
                    detail = "\n".join(
                        f"• {PRODUCTS[pid]['name']} x{qty} — {fmt(PRODUCTS[pid]['price'] * qty)}"
                        for pid, qty in cart.items()
                    )
                    send_message(
                        ADMIN_CHAT_ID,
                        f"🆕 *NOUVELLE COMMANDE #{order_id:05d}*\n"
                        f"👤 {username} · id `{chat_id}`\n\n"
                        f"{detail}\n\n*Total : {fmt(total)}*\n\n"
                        "_Statut : en attente du paiement._",
                        admin_order_keyboard(order_id),
                        parse_mode="Markdown",
                    )

                CARTS[chat_id] = {}

    return "ok"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

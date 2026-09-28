"""
Bot Telegram — boutique intégrée, en mode WEBHOOK (compatible plan gratuit Render).
Pas de librairie python-telegram-bot ici : on parle directement à l'API Telegram
avec `requests`, et Flask reçoit les messages via un "Web Service" (gratuit).

Fichiers du projet :
    app.py            <- ce fichier
    requirements.txt
"""

import os
import re
import json
import html
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

# Lien du support (ex. https://t.me/ton_pseudo). Variable Render SUPPORT_LINK ou à écrire ici.
SUPPORT_LINK = os.environ.get("SUPPORT_LINK", "https://t.me/tenhebreux")

# Canaux affichés dans la rubrique "Canaux" : (texte du bouton, lien https://t.me/...)
CHANNELS = [
    ("🌐 Portail", "https://t.me/portaltenhebreux"),
    ("📢 Canal", "https://t.me/selltenhebreux"),
    ("🧾 Vouch", "https://t.me/preuvetenhebreux"),
]

# --- Textes du bot (modifie ici pour changer ce que le bot dit) ------------

SHOP_NAME = "𖤐 TENHEBREUX"

TEXT_WELCOME = (
    f"🖤 *Bienvenue chez {SHOP_NAME}*\n"
    "━━━━━━━━━━━━━━━\n"
    "🆔 ID : `{user_id}`\n"
    "👤 Pseudo : `{username}`\n"
    "💰 Solde : *{balance}*\n"
    "━━━━━━━━━━━━━━━\n\n"
    "🚀 *Fais grimper ta présence en ligne*\n"
    "📈 SMM · 🔐 Comptes & Abonnements\n\n"
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

TEXT_ORDER_PAID = (
    "🎉 *Commande payée avec ton solde !*\n"
    "━━━━━━━━━━━━━━━\n\n"
    "📦 Commande *#{order_id}*\n"
    "💰 Montant : *{total}*\n"
    "💳 Solde restant : *{balance}*\n\n"
    "⚙️ Un vendeur prend ta commande en charge. "
    "Tu reçois une notification à chaque étape.\n\n"
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
    "SMM": (
        "📈 *SMM*\n"
        "━━━━━━━━━━━━━━━\n\n"
        "🚀 Booste tes réseaux : followers, vues, likes, réactions...\n"
        "💎 Prix pour 1 000 unités\n\n"
        "_choisis ta plateforme_ 👇"
    ),
    "Comptes & Abonnements": (
        "🔐 *Comptes & Abonnements*\n"
        "━━━━━━━━━━━━━━━\n\n"
        "_choisis une catégorie_ 👇"
    ),
}

# Titres des écrans produits (sous-catégories SMM).
SUB_TEXT = {
    ("SMM", "Telegram"): (
        "✈️ *SMM · Telegram*\n"
        "━━━━━━━━━━━━━━━\n\n"
        "🚀 Members, views, reactions\n"
        "💎 Prix pour 1 000 unités\n"
    ),
    ("SMM", "TikTok"): (
        "🎵 *SMM · TikTok*\n"
        "━━━━━━━━━━━━━━━\n\n"
        "🔥 Followers, views, likes, favorites, shares, comments\n"
        "💎 Prix pour 1 000 unités\n"
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

CATEGORIES = ["SMM", "Comptes & Abonnements"]

PRODUCTS = {
    # --- Telegram services (prix pour 1000 unités) ---
    "tg1": {"name": "Members (1K)", "cat": "SMM", "sub": "Telegram", "price": 3},
    "tg2": {"name": "Views (1K)", "cat": "SMM", "sub": "Telegram", "price": 0.50},
    "tg3": {"name": "Reactions (1K)", "cat": "SMM", "sub": "Telegram", "price": 0.75},

    # --- TikTok services (prix pour 1000 unités) ---
    "tt1": {"name": "Followers (1K)", "cat": "SMM", "sub": "TikTok", "price": 5},
    "tt2": {"name": "Views (1K)", "cat": "SMM", "sub": "TikTok", "price": 0.50},
    "tt3": {"name": "Likes (1K)", "cat": "SMM", "sub": "TikTok", "price": 2},
    "tt4": {"name": "Favorites (1K)", "cat": "SMM", "sub": "TikTok", "price": 0.50},
    "tt5": {"name": "Shares (1K)", "cat": "SMM", "sub": "TikTok", "price": 0.50},
    "tt6": {"name": "Custom Comments (1K)", "cat": "SMM", "sub": "TikTok", "price": 15},

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
    "SMM": ["Telegram", "TikTok"],
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
    conn.execute("""CREATE TABLE IF NOT EXISTS users (
        telegram_id INTEGER PRIMARY KEY,
        username TEXT,
        balance REAL NOT NULL DEFAULT 0
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")
    conn.commit()
    conn.close()


init_db()


# --- Réglages modifiables depuis le panneau admin ---------------------------

ADMIN_STATE: dict = {}   # saisie en cours de l'admin (banner, welcome, emoji, credit, restock, price)
EMOJI_MAP: dict = {}     # emoji normal -> id de l'emoji premium
EMOJI_RE = None          # repère un emoji du dictionnaire dans un texte
EMOJI_BTN_RE = None      # repère un emoji du dictionnaire en début de bouton
PREMIUM_UI = True        # interrupteur emojis premium + couleurs de boutons


def is_admin_chat(chat_id):
    return bool(ADMIN_CHAT_ID) and str(chat_id) == str(ADMIN_CHAT_ID)


def get_setting(key, default=None):
    conn = db_connect()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = db_connect()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()


def del_setting(key):
    conn = db_connect()
    conn.execute("DELETE FROM settings WHERE key = ?", (key,))
    conn.commit()
    conn.close()


def refresh_settings():
    global EMOJI_MAP, EMOJI_RE, EMOJI_BTN_RE, PREMIUM_UI
    try:
        EMOJI_MAP = json.loads(get_setting("emoji_map", "{}"))
    except ValueError:
        EMOJI_MAP = {}
    keys = sorted(EMOJI_MAP, key=len, reverse=True)
    if keys:
        alt = "|".join(re.escape(k) for k in keys)
        EMOJI_RE = re.compile("(" + alt + ")\ufe0f?")
        EMOJI_BTN_RE = re.compile("^(" + alt + ")\ufe0f?\\s*")
    else:
        EMOJI_RE = EMOJI_BTN_RE = None
    PREMIUM_UI = get_setting("premium_ui", "1") == "1"


def load_price_overrides():
    for pid in PRODUCTS:
        v = get_setting(f"price:{pid}")
        if v is not None:
            try:
                PRODUCTS[pid]["price"] = float(v)
            except ValueError:
                pass


refresh_settings()
load_price_overrides()


def current_banner():
    """Bannière d'accueil : réglage admin, sinon variable WELCOME_IMAGE. '' = aucune."""
    v = get_setting("welcome_image")
    return WELCOME_IMAGE if v is None else v


# --- Emojis premium : conversion Markdown -> HTML + boutons ------------------

def md_to_html(text):
    """Convertit notre Markdown (*gras* _italique_ `code`) en HTML Telegram."""
    codes = []

    def keep(m):
        codes.append(m.group(1))
        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"`([^`]*)`", keep, text)
    text = html.escape(text, quote=False)
    text = re.sub(r"\*([^*\n]+)\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\w)_([^_\n]+)_(?!\w)", r"<i>\1</i>", text)
    return re.sub(
        r"\x00(\d+)\x00",
        lambda m: "<code>" + html.escape(codes[int(m.group(1))], quote=False) + "</code>",
        text,
    )


def apply_custom_emoji(text):
    if not EMOJI_RE:
        return text
    return EMOJI_RE.sub(
        lambda m: f'<tg-emoji emoji-id="{EMOJI_MAP[m.group(1)]}">{m.group(1)}</tg-emoji>', text
    )


def decorate_keyboard(kb):
    """Emojis premium en début de bouton + couleurs (vert = valider, rouge = annuler/vider)."""
    out = []
    for row in kb:
        new_row = []
        for b in row:
            b = dict(b)
            cb = b.get("callback_data", "")
            if EMOJI_BTN_RE:
                m = EMOJI_BTN_RE.match(b["text"])
                if m and b["text"][m.end():]:
                    b["icon_custom_emoji_id"] = EMOJI_MAP[m.group(1)]
                    b["text"] = b["text"][m.end():]
            if cb in ("checkout", "paybal") or cb.endswith(":completed"):
                b["style"] = "success"
            elif cb == "clear" or cb.endswith(":cancelled"):
                b["style"] = "danger"
            new_row.append(b)
        out.append(new_row)
    return out


ENHANCED_METHODS = {"sendMessage", "editMessageText", "sendPhoto"}


def enhance_payload(method, payload):
    p = dict(payload)
    markup = p.get("reply_markup")
    if markup and markup.get("inline_keyboard"):
        p["reply_markup"] = {"inline_keyboard": decorate_keyboard(markup["inline_keyboard"])}
    if EMOJI_MAP and p.get("parse_mode") == "Markdown":
        field = "caption" if method == "sendPhoto" else "text"
        if field in p:
            p[field] = apply_custom_emoji(md_to_html(p[field]))
            p["parse_mode"] = "HTML"
    return p


def upsert_user(user):
    """Enregistre / met à jour le client et renvoie son @ (ou son prénom)."""
    username = f"@{user['username']}" if user.get("username") else (user.get("first_name") or "client")
    conn = db_connect()
    conn.execute(
        "INSERT INTO users (telegram_id, username, balance) VALUES (?, ?, 0) "
        "ON CONFLICT(telegram_id) DO UPDATE SET username = excluded.username",
        (user["id"], username),
    )
    conn.commit()
    conn.close()
    return username


def get_balance(telegram_id):
    conn = db_connect()
    row = conn.execute("SELECT balance FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
    conn.close()
    return round(row["balance"], 2) if row else 0.0


def add_balance(telegram_id, delta):
    """Ajoute (ou retire si négatif) du solde. Ne descend jamais sous 0. Renvoie le nouveau solde."""
    conn = db_connect()
    conn.execute("INSERT OR IGNORE INTO users (telegram_id, username, balance) VALUES (?, NULL, 0)", (telegram_id,))
    conn.execute("UPDATE users SET balance = MAX(0, ROUND(balance + ?, 2)) WHERE telegram_id = ?", (delta, telegram_id))
    conn.commit()
    row = conn.execute("SELECT balance FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
    conn.close()
    return round(row["balance"], 2)


def spend_balance(telegram_id, amount):
    """Débite le solde seulement s'il est suffisant. Renvoie True si le paiement est passé."""
    conn = db_connect()
    cur = conn.execute(
        "UPDATE users SET balance = ROUND(balance - ?, 2) WHERE telegram_id = ? AND balance >= ?",
        (amount, telegram_id, amount),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def create_order(telegram_id, username, cart, total, status="pending_payment"):
    conn = db_connect()
    cur = conn.execute(
        "INSERT INTO orders (telegram_id, username, total, status, created_at) VALUES (?, ?, ?, ?, ?)",
        (telegram_id, username, total, status, datetime.now(timezone.utc).isoformat()),
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
        f"🆔 ID : `{chat_id}`",
        f"💰 Solde : *{fmt(get_balance(chat_id))}*",
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
        f"👤 `{order['username'] or 'Client'}` — id `{order['telegram_id']}`\n\n"
        f"{detail}\n\n"
        f"*Total : {fmt(order['total'])}*\n"
        f"*Statut :* {status}"
    )


# --- Appels bruts à l'API Telegram -----------------------------------------

def _post(method, payload):
    try:
        return requests.post(f"{API_URL}/{method}", json=payload, timeout=10).json()
    except Exception:
        return {}


def tg_call(method: str, payload: dict):
    """Appelle l'API Telegram. Essaie d'abord avec emojis premium / couleurs ;
    si Telegram refuse, renvoie la version classique : le bot ne casse jamais."""
    if PREMIUM_UI and method in ENHANCED_METHODS:
        r = _post(method, enhance_payload(method, payload))
        if r.get("ok"):
            return r
        desc = str(r.get("description", "")).lower()
        if "not modified" in desc or "no text" in desc:
            return r
    return _post(method, payload)


def send_message(chat_id, text, keyboard=None, parse_mode=None):
    payload = {"chat_id": chat_id, "text": text}
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    return tg_call("sendMessage", payload)


def welcome_text(user):
    username = upsert_user(user).replace("`", "")
    values = dict(user_id=user["id"], username=username, balance=fmt(get_balance(user["id"])))
    custom = get_setting("welcome_text")
    if custom:
        try:
            return custom.format(**values)
        except (KeyError, IndexError, ValueError):
            pass
    return TEXT_WELCOME.format(**values)


def send_home(chat_id, user):
    """Écran d'accueil (ID, @, solde) avec bannière si définie."""
    kb = kb_categories(chat_id)
    text = welcome_text(user)
    banner = current_banner()
    if banner:
        r = tg_call("sendPhoto", {
            "chat_id": chat_id,
            "photo": banner,
            "caption": text,
            "parse_mode": "Markdown",
            "reply_markup": {"inline_keyboard": kb},
        })
        if r.get("ok"):
            return
    r = send_message(chat_id, text, kb, parse_mode="Markdown")
    if not r.get("ok"):
        send_message(chat_id, text, kb)  # texte perso mal formaté : on envoie sans mise en forme


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
    "SMM": "📈 SMM",
    "Comptes & Abonnements": "🔐 Comptes & Abos",
}


def cart_count(chat_id):
    return sum(get_cart(chat_id).values())


def kb_categories(chat_id=None):
    count = cart_count(chat_id) if chat_id is not None else 0
    cart_label = f"🛒 Panier · {count}" if count else "🛒 Panier"
    rows = [
        [{"text": CATEGORY_LABELS.get(c, c), "callback_data": f"cat:{c}"} for c in CATEGORIES],
        [{"text": cart_label, "callback_data": "cart"},
         {"text": "📦 Commandes", "callback_data": "orders"}],
        [{"text": "👤 Profil", "callback_data": "profile"},
         {"text": "💬 Support", "callback_data": "support"}],
        [{"text": "📢 Canaux", "callback_data": "channels"}],
    ]
    if chat_id is not None and is_admin_chat(chat_id):
        rows.append([{"text": "🛠 Admin", "callback_data": "adm:home"}])
    return rows


SUBCAT_LABELS = {
    "Streaming": "📺 Streaming",
    "Musique & Audio": "🎧 Musique & Audio",
    "IA": "🤖 IA",
    "VPN": "🛡 VPN",
    "Mail": "✉️ Mail",
    "Outils": "🧰 Outils",
    "Telegram": "✈️ Telegram",
    "TikTok": "🎵 TikTok",
}


def kb_subcats(cat):
    subs = [
        {"text": SUBCAT_LABELS.get(s, s), "callback_data": f"sub:{cat}:{s}"}
        for s in SUBCATEGORIES[cat]
    ]
    rows = [subs[i:i + 2] for i in range(0, len(subs), 2)]
    rows.append([{"text": "🛒 Panier", "callback_data": "cart"},
                 {"text": "⬅️ Retour", "callback_data": "menu"}])
    return rows


def _items(cat, sub=None):
    return [
        (pid, p) for pid, p in PRODUCTS.items()
        if p["cat"] == cat and (sub is None or p.get("sub") == sub)
    ]


def kb_products(cat, sub=None):
    btns = []
    for pid, p in _items(cat, sub):
        s = stock_of(pid)
        if s == 0:
            btns.append({"text": f"❌ {p['name']}", "callback_data": "oos"})
        else:
            label = f"{p['name']} · {fmt(p['price'])}"
            if s is not None and s <= SEUIL_STOCK_BAS:
                label += f" ({s})"
            btns.append({"text": label, "callback_data": f"add:{pid}"})
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    back = f"cat:{cat}" if sub else "menu"
    rows.append([{"text": "🛒 Panier", "callback_data": "cart"},
                 {"text": "⬅️ Retour", "callback_data": back}])
    return rows


def products_text(cat, sub=None):
    """Texte de l'écran produits : liste complète avec prix (les boutons peuvent être tronqués)."""
    head = SUB_TEXT.get((cat, sub)) or (f"📂 *{cat}*" + (f" · {sub}" if sub else ""))
    lines = [head]
    for pid, p in _items(cat, sub):
        s = stock_of(pid)
        tag = ""
        if s == 0:
            tag = " — ❌ rupture"
        elif s is not None and s <= SEUIL_STOCK_BAS:
            tag = f" — plus que {s}"
        lines.append(f"• {p['name']} — *{fmt(p['price'])}*{tag}")
    lines.append("\n_touche un produit pour l'ajouter au panier_ 👇")
    return "\n".join(lines)


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
    ]
    balance = get_balance(chat_id)
    if balance > 0 and balance >= round(total, 2):
        rows.append([{"text": f"💰 Payer avec mon solde ({fmt(balance)})", "callback_data": "paybal"}])
    rows.append([{"text": "🗑 Vider", "callback_data": "clear"},
                 {"text": "🛍 Boutique", "callback_data": "menu"}])
    return "\n".join(lines), rows


ADMIN_HOME_TEXT = "🛠 *Panneau admin*\n━━━━━━━━━━━━━━━\n\nChoisis ce que tu veux modifier 👇"

ADMIN_BACK = [{"text": "⬅️ Panneau admin", "callback_data": "adm:home"}]


def admin_home_kb():
    return [
        [{"text": "🖼 Bannière", "callback_data": "adm:banner"},
         {"text": "✏️ Accueil", "callback_data": "adm:welcome"}],
        [{"text": "🎨 Emojis premium", "callback_data": "adm:emoji"},
         {"text": "💰 Solde client", "callback_data": "adm:credit"}],
        [{"text": "📦 Stock", "callback_data": "adm:stock"},
         {"text": "🏷 Prix", "callback_data": "adm:price"}],
        [{"text": "📊 Stats", "callback_data": "adm:stats"},
         {"text": "🏠 Boutique", "callback_data": "menu"}],
    ]


def admin_stats_text():
    conn = db_connect()
    clients = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    row = conn.execute(
        """SELECT COUNT(*) AS n,
            SUM(CASE WHEN status = 'pending_payment' THEN 1 ELSE 0 END) AS pending,
            SUM(CASE WHEN status IN ('paid', 'processing') THEN 1 ELSE 0 END) AS running,
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS done,
            COALESCE(SUM(CASE WHEN status IN ('paid', 'processing', 'completed') THEN total END), 0) AS revenue
           FROM orders"""
    ).fetchone()
    conn.close()
    return (
        "📊 *Stats*\n━━━━━━━━━━━━━━━\n\n"
        f"👥 Clients : *{clients}*\n"
        f"📦 Commandes : *{row['n']}*\n"
        f"🟡 En attente de paiement : *{row['pending'] or 0}*\n"
        f"⚙️ Payées / en cours : *{row['running'] or 0}*\n"
        f"✅ Terminées : *{row['done'] or 0}*\n"
        f"💰 Total encaissé : *{fmt(row['revenue'])}*"
    )


def admin_screen(chat_id, action):
    """Renvoie (texte, clavier) d'un écran du panneau admin et règle la saisie attendue."""
    ADMIN_STATE.pop(chat_id, None)

    if action == "banner":
        ADMIN_STATE[chat_id] = "banner"
        etat = "✅ active" if current_banner() else "aucune"
        return (
            "🖼 *Bannière d'accueil*\n━━━━━━━━━━━━━━━\n\n"
            f"Statut : {etat}\n\n"
            "Envoie-moi *une photo* : elle deviendra la bannière du message d'accueil.",
            [[{"text": "🗑 Retirer la bannière", "callback_data": "adm:banner_del"}], ADMIN_BACK],
        )

    if action == "welcome":
        ADMIN_STATE[chat_id] = "welcome"
        return (
            "✏️ *Message d'accueil*\n━━━━━━━━━━━━━━━\n\n"
            "Envoie-moi le nouveau texte.\n\n"
            "Variables : `{user_id}` `{username}` `{balance}`\n"
            "Mise en forme : `*gras*` `_italique_`",
            [[{"text": "↩️ Remettre le texte d'origine", "callback_data": "adm:welcome_reset"}], ADMIN_BACK],
        )

    if action == "emoji":
        ADMIN_STATE[chat_id] = "emoji"
        actifs = "✅ activés" if PREMIUM_UI else "⏸ désactivés"
        liste = " ".join(EMOJI_MAP) if EMOJI_MAP else "aucun"
        return (
            "🎨 *Emojis premium*\n━━━━━━━━━━━━━━━\n\n"
            f"Statut : {actifs}\n"
            f"Enregistrés : {liste}\n\n"
            "Pour en ajouter : envoie-moi un message contenant les emojis premium voulus. "
            "Chacun remplace l'emoji normal identique, partout dans le bot (messages et boutons).\n\n"
            "Emojis utilisés par le bot : 🖤 🚀 💎 ⚡ 🔥 🛒 📦 👤 💬 📢 ✅ 🎉 💰 🔎 📈 🔐\n\n"
            "⚠️ Il faut que le propriétaire du bot ait Telegram Premium. Sinon Telegram refuse "
            "et le bot affiche les emojis normaux.",
            [[{"text": "⏸ Désactiver" if PREMIUM_UI else "▶️ Activer", "callback_data": "adm:emoji_toggle"},
              {"text": "🗑 Tout effacer", "callback_data": "adm:emoji_clear"}],
             ADMIN_BACK],
        )

    if action == "credit":
        ADMIN_STATE[chat_id] = "credit"
        return (
            "💰 *Solde client*\n━━━━━━━━━━━━━━━\n\n"
            "Envoie : `id montant`\n"
            "Ex. `123456789 10` ajoute 10€.\n"
            "Montant négatif pour retirer.\n\n"
            "_L'ID du client est affiché sur son message d'accueil. Tu peux enchaîner plusieurs clients._",
            [ADMIN_BACK],
        )

    if action == "stock":
        ADMIN_STATE[chat_id] = "restock"
        lines = [f"`{pid}` {PRODUCTS[pid]['name']} : {qty}" for pid, qty in sorted(STOCK.items())]
        return (
            "📦 *Stock*\n━━━━━━━━━━━━━━━\n\n" + "\n".join(lines) +
            "\n\nEnvoie : `id quantité` pour ajouter (ex. `a04 10`, négatif pour retirer).",
            [ADMIN_BACK],
        )

    if action == "price":
        ADMIN_STATE[chat_id] = "price"
        lines = [f"`{pid}` {p['name']} : {fmt(p['price'])}" for pid, p in PRODUCTS.items()]
        return (
            "🏷 *Prix*\n━━━━━━━━━━━━━━━\n\n" + "\n".join(lines) +
            "\n\nEnvoie : `id prix` (ex. `tt1 4.5`).",
            [ADMIN_BACK],
        )

    if action == "stats":
        return admin_stats_text(), [ADMIN_BACK]

    return ADMIN_HOME_TEXT, admin_home_kb()


def handle_admin_callback(cq, chat_id, message_id, data):
    if not is_admin_chat(chat_id):
        answer_callback(cq["id"], "Accès refusé.", alert=True)
        return
    answer_callback(cq["id"])
    action = data.split(":", 1)[1]

    if action == "banner_del":
        set_setting("welcome_image", "")
        action = "banner"
    elif action == "welcome_reset":
        del_setting("welcome_text")
        action = "welcome"
    elif action == "emoji_toggle":
        set_setting("premium_ui", "0" if PREMIUM_UI else "1")
        refresh_settings()
        action = "emoji"
    elif action == "emoji_clear":
        del_setting("emoji_map")
        refresh_settings()
        action = "emoji"

    text, kb = admin_screen(chat_id, action)
    edit_message(chat_id, message_id, text, kb, parse_mode="Markdown")


def handle_admin_input(chat_id, msg):
    """Traite le message envoyé par l'admin pendant une saisie (bannière, texte, emojis...)."""
    mode = ADMIN_STATE.get(chat_id)
    text = (msg.get("text") or "").strip()
    back_kb = [ADMIN_BACK]

    if mode == "banner":
        photos = msg.get("photo")
        if not photos:
            send_message(chat_id, "Envoie une *photo* (pas un fichier), ou /annuler.", parse_mode="Markdown")
            return
        set_setting("welcome_image", photos[-1]["file_id"])
        ADMIN_STATE.pop(chat_id, None)
        send_message(chat_id, "✅ Bannière mise à jour. Tape /start pour la voir.", back_kb)

    elif mode == "welcome":
        try:
            text.format(user_id=1, username="@test", balance="0€")
        except (KeyError, IndexError, ValueError):
            send_message(
                chat_id,
                "❌ Texte invalide : seules les variables `{user_id}` `{username}` `{balance}` "
                "sont permises entre accolades. Réessaie ou /annuler.",
                parse_mode="Markdown",
            )
            return
        if not text:
            send_message(chat_id, "Envoie le texte du message d'accueil, ou /annuler.")
            return
        set_setting("welcome_text", text)
        ADMIN_STATE.pop(chat_id, None)
        send_message(chat_id, "✅ Message d'accueil mis à jour. Tape /start pour le voir.", back_kb)

    elif mode == "emoji":
        raw = (msg.get("text") or "").encode("utf-16-le")  # Telegram compte les positions en UTF-16
        found = {}
        for e in msg.get("entities", []):
            if e.get("type") == "custom_emoji":
                ch = raw[e["offset"] * 2:(e["offset"] + e["length"]) * 2].decode("utf-16-le")
                found[ch.replace("\ufe0f", "")] = e["custom_emoji_id"]
        if not found:
            send_message(
                chat_id,
                "Je n'ai trouvé aucun emoji premium dans ton message. "
                "Envoie-moi des emojis premium (ou /annuler).",
            )
            return
        EMOJI_MAP.update(found)
        set_setting("emoji_map", json.dumps(EMOJI_MAP, ensure_ascii=False))
        refresh_settings()
        ADMIN_STATE.pop(chat_id, None)
        send_message(chat_id, f"✅ {len(found)} emoji premium enregistré(s) : {' '.join(found)}\nTape /start pour voir le résultat.", back_kb)

    elif mode == "credit":
        parts = text.split()
        try:
            target, amount = int(parts[0]), round(float(parts[1].replace(",", ".")), 2)
        except (IndexError, ValueError):
            send_message(chat_id, "Format : `id montant` (ex. `123456789 10`), ou /annuler.", parse_mode="Markdown")
            return
        new_balance = add_balance(target, amount)
        send_message(chat_id, f"✅ Solde du client `{target}` : *{fmt(new_balance)}*", back_kb, parse_mode="Markdown")
        if amount > 0:
            send_message(
                target,
                f"💰 *Solde crédité : +{fmt(amount)}*\n\nNouveau solde : *{fmt(new_balance)}*",
                parse_mode="Markdown",
            )

    elif mode == "restock":
        parts = text.split()
        if len(parts) != 2 or parts[0] not in STOCK or not parts[1].lstrip("-").isdigit():
            send_message(chat_id, "Format : `id quantité` (ex. `a04 10`), ou /annuler.", parse_mode="Markdown")
            return
        pid = parts[0]
        STOCK[pid] = max(0, STOCK[pid] + int(parts[1]))
        send_message(chat_id, f"✅ {PRODUCTS[pid]['name']} : stock à {STOCK[pid]}.", back_kb)

    elif mode == "price":
        parts = text.split()
        try:
            pid, price = parts[0], round(float(parts[1].replace(",", ".")), 2)
            assert pid in PRODUCTS and price > 0
        except (IndexError, ValueError, AssertionError):
            send_message(chat_id, "Format : `id prix` (ex. `tt1 4.5`), ou /annuler.", parse_mode="Markdown")
            return
        PRODUCTS[pid]["price"] = price
        set_setting(f"price:{pid}", str(price))
        send_message(chat_id, f"✅ {PRODUCTS[pid]['name']} : {fmt(price)}", back_kb)


def support_view():
    text = (
        "💬 *Support*\n"
        "━━━━━━━━━━━━━━━\n\n"
        "Une question, un souci avec une commande ou un paiement ?\n"
        "Écris-nous en indiquant ton *numéro de commande*."
    )
    rows = []
    if SUPPORT_LINK.startswith("https://"):
        rows.append([{"text": "💬 Contacter le support", "url": SUPPORT_LINK}])
    else:
        text += "\n\n_Contact support bientôt disponible._"
    rows.append([{"text": "🏠 Accueil", "callback_data": "menu"}])
    return text, rows


def channels_view():
    text = (
        "📢 *Nos canaux*\n"
        "━━━━━━━━━━━━━━━\n\n"
        "Retrouve tous nos canaux officiels ci-dessous."
    )
    rows = [
        [{"text": label, "url": url}]
        for label, url in CHANNELS if url.startswith("https://")
    ]
    if not rows:
        text += "\n\n_Les liens arrivent bientôt._"
    rows.append([{"text": "🏠 Accueil", "callback_data": "menu"}])
    return text, rows


def handle_checkout(cq, chat_id, message_id, use_balance=False):
    cart = get_cart(chat_id)
    if not cart:
        answer_callback(cq["id"], "Panier vide.", alert=True)
        return
    for pid, qty in cart.items():
        if not in_stock(pid, qty):
            answer_callback(cq["id"], f"Stock insuffisant : {PRODUCTS[pid]['name']}.", alert=True)
            return

    total = round(sum(PRODUCTS[pid]["price"] * qty for pid, qty in cart.items()), 2)
    user = cq["from"]
    username = f"@{user['username']}" if user.get("username") else user.get("first_name", "client")

    if use_balance and not spend_balance(chat_id, total):
        answer_callback(cq["id"], "Solde insuffisant.", alert=True)
        return
    answer_callback(cq["id"])

    order_id = create_order(chat_id, username, cart, total, "paid" if use_balance else "pending_payment")

    # Décrémente le stock des articles limités (comptes/clés).
    for pid, qty in cart.items():
        if pid in STOCK:
            STOCK[pid] = max(0, STOCK[pid] - qty)

    if use_balance:
        confirm = TEXT_ORDER_PAID.format(
            order_id=f"{order_id:05d}", total=fmt(total), balance=fmt(get_balance(chat_id))
        )
    else:
        confirm = TEXT_ORDER_CONFIRM.format(
            order_id=f"{order_id:05d}", total=fmt(total), payment_info=PAYMENT_INFO
        )
    edit_message(
        chat_id, message_id, confirm,
        [[{"text": "📦 Mes commandes", "callback_data": "orders"},
          {"text": "🏠 Boutique", "callback_data": "menu"}]],
        parse_mode="Markdown",
    )

    if ADMIN_CHAT_ID:
        detail = "\n".join(
            f"• {PRODUCTS[pid]['name']} x{qty} — {fmt(PRODUCTS[pid]['price'] * qty)}"
            for pid, qty in cart.items()
        )
        etat = "payée avec le solde" if use_balance else "en attente du paiement"
        send_message(
            ADMIN_CHAT_ID,
            f"🆕 *NOUVELLE COMMANDE #{order_id:05d}*\n"
            f"👤 `{username}` · id `{chat_id}`\n\n"
            f"{detail}\n\n*Total : {fmt(total)}*\n\n"
            f"_Statut : {etat}._",
            admin_order_keyboard(order_id),
            parse_mode="Markdown",
        )

    CARTS[chat_id] = {}


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

        is_admin = is_admin_chat(chat_id)

        # Saisie en cours dans le panneau admin (bannière, texte, emojis, solde...)
        if is_admin and ADMIN_STATE.get(chat_id) and not text.startswith("/"):
            handle_admin_input(chat_id, update["message"])
            return "ok"

        if text.startswith("/start"):
            ADMIN_STATE.pop(chat_id, None)
            send_home(chat_id, update["message"]["from"])

        elif is_admin and text.startswith("/admin"):
            ADMIN_STATE.pop(chat_id, None)
            send_message(chat_id, ADMIN_HOME_TEXT, admin_home_kb(), parse_mode="Markdown")

        elif is_admin and text.startswith("/annuler"):
            ADMIN_STATE.pop(chat_id, None)
            send_message(chat_id, "✅ Annulé.", admin_home_kb())

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

        elif is_admin and text.startswith("/credit"):
            parts = text.split()
            try:
                target = int(parts[1])
                amount = round(float(parts[2].replace(",", ".")), 2)
            except (IndexError, ValueError):
                send_message(
                    chat_id,
                    "Usage : `/credit <id client> <montant>`\n"
                    "Ex. `/credit 123456789 10` ajoute 10€ au solde.\n"
                    "Montant négatif pour retirer.",
                    parse_mode="Markdown",
                )
            else:
                new_balance = add_balance(target, amount)
                send_message(chat_id, f"✅ Solde du client `{target}` : *{fmt(new_balance)}*", parse_mode="Markdown")
                if amount > 0:
                    send_message(
                        target,
                        f"💰 *Solde crédité : +{fmt(amount)}*\n\nNouveau solde : *{fmt(new_balance)}*",
                        parse_mode="Markdown",
                    )

    elif "callback_query" in update:
        cq = update["callback_query"]
        chat_id = cq["message"]["chat"]["id"]
        message_id = cq["message"]["message_id"]
        data = cq["data"]

        if data == "menu":
            answer_callback(cq["id"])
            # On supprime l'ancien message puis on réaffiche l'accueil (avec l'image).
            tg_call("deleteMessage", {"chat_id": chat_id, "message_id": message_id})
            send_home(chat_id, cq["from"])

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
            edit_message(chat_id, message_id, products_text(cat, sub), kb_products(cat, sub), parse_mode="Markdown")

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
                title = products_text(cat, sub)
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

        elif data.startswith("adm:"):
            handle_admin_callback(cq, chat_id, message_id, data)

        elif data == "support":
            answer_callback(cq["id"])
            text, kb = support_view()
            edit_message(chat_id, message_id, text, kb, parse_mode="Markdown")

        elif data == "channels":
            answer_callback(cq["id"])
            text, kb = channels_view()
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

        elif data in ("checkout", "paybal"):
            handle_checkout(cq, chat_id, message_id, use_balance=(data == "paybal"))

    return "ok"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

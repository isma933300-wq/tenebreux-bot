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
import psycopg2
import psycopg2.extras
import requests
import threading
import time
import collections
import traceback
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
from datetime import datetime, timedelta, timezone
from flask import Flask, request
from requests.adapters import HTTPAdapter

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
    "💰 Total à régler : *{total}*\n{discount_line}\n"
    "💳 *Comment payer*\n"
    "Envoie le montant exact à l'une de ces adresses "
    "_(appui long sur l'adresse pour la copier)_ :\n\n"
    "{payment_info}\n\n"
    "📸 *Ensuite*\n"
    "Appuie sur *J'ai payé*, puis envoie ici la capture du paiement (ou le hash). Un vendeur vérifie, confirme "
    "et traite ta commande. Tu reçois une notification à chaque étape.\n\n"
    "🔎 Suivi disponible dans *Mes commandes*."
)

TEXT_ORDER_PAID = (
    "🎉 *Commande payée avec ton solde !*\n"
    "━━━━━━━━━━━━━━━\n\n"
    "📦 Commande *#{order_id}*\n"
    "💰 Montant : *{total}*\n{discount_line}"
    "💳 Solde restant : *{balance}*\n\n"
    "⚙️ Un vendeur prend ta commande en charge. "
    "Tu reçois une notification à chaque étape.\n\n"
    "🔎 Suivi disponible dans *Mes commandes*."
)

# Messages envoyés au client quand le vendeur change le statut.
STATUS_MESSAGES = {
    "paid": "💳 *Paiement reçu, merci !*\nTa commande est validée et passe bientôt en traitement.\nTes accès arrivent ici dès qu'ils sont prêts.",
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
    "Cartes cadeaux": (
        "🎁 *Cartes cadeaux*\n"
        "━━━━━━━━━━━━━━━\n\n"
        "_choisis une plateforme_ 👇"
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
    ("SMM", "Instagram"): (
        "📸 *SMM · Instagram*\n"
        "━━━━━━━━━━━━━━━\n\n"
        "🔥 Followers, likes, reels & story views\n"
        "💎 Prix pour 1 000 unités\n"
    ),
    ("SMM", "YouTube"): (
        "▶️ *SMM · YouTube*\n"
        "━━━━━━━━━━━━━━━\n\n"
        "🔥 Views, likes, subscribers\n"
        "💎 Prix pour 1 000 unités\n"
    ),
    ("SMM", "X"): (
        "🐦 *SMM · X / Twitter*\n"
        "━━━━━━━━━━━━━━━\n\n"
        "🔥 Followers, likes, retweets, views\n"
        "💎 Prix pour 1 000 unités\n"
    ),
    ("SMM", "Discord"): (
        "💬 *SMM · Discord*\n"
        "━━━━━━━━━━━━━━━\n\n"
        "🔥 Membres de serveur\n"
        "💎 Prix pour 1 000 unités\n"
    ),
    ("SMM", "Twitch"): (
        "🟣 *SMM · Twitch*\n"
        "━━━━━━━━━━━━━━━\n\n"
        "🔥 Followers, views\n"
        "💎 Prix pour 1 000 unités\n"
    ),
    ("SMM", "Spotify"): (
        "🎧 *SMM · Spotify*\n"
        "━━━━━━━━━━━━━━━\n\n"
        "🔥 Plays, followers\n"
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

CATEGORIES = ["SMM", "Comptes & Abonnements", "Cartes cadeaux"]

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

    # --- Instagram (prix pour 1000 unités) ---
    "ig1": {"name": "Followers (1K)", "cat": "SMM", "sub": "Instagram", "price": 4},
    "ig2": {"name": "Likes (1K)", "cat": "SMM", "sub": "Instagram", "price": 1.50},
    "ig3": {"name": "Reels Views (1K)", "cat": "SMM", "sub": "Instagram", "price": 0.50},
    "ig4": {"name": "Story Views (1K)", "cat": "SMM", "sub": "Instagram", "price": 1},

    # --- YouTube (prix pour 1000 unités) ---
    "yt1": {"name": "Views (1K)", "cat": "SMM", "sub": "YouTube", "price": 3},
    "yt2": {"name": "Likes (1K)", "cat": "SMM", "sub": "YouTube", "price": 2.50},
    "yt3": {"name": "Subscribers (1K)", "cat": "SMM", "sub": "YouTube", "price": 25},

    # --- X / Twitter (prix pour 1000 unités) ---
    "xt1": {"name": "Followers (1K)", "cat": "SMM", "sub": "X", "price": 4},
    "xt2": {"name": "Likes (1K)", "cat": "SMM", "sub": "X", "price": 2},
    "xt3": {"name": "Retweets (1K)", "cat": "SMM", "sub": "X", "price": 3},
    "xt4": {"name": "Views (1K)", "cat": "SMM", "sub": "X", "price": 0.50},

    # --- Discord (prix pour 1000 unités) ---
    "dc1": {"name": "Server Members (1K)", "cat": "SMM", "sub": "Discord", "price": 8},
    "dc2": {"name": "Online Members (1K)", "cat": "SMM", "sub": "Discord", "price": 20},

    # --- Twitch (prix pour 1000 unités) ---
    "tw1": {"name": "Followers (1K)", "cat": "SMM", "sub": "Twitch", "price": 6},
    "tw2": {"name": "Views (1K)", "cat": "SMM", "sub": "Twitch", "price": 2},

    # --- Spotify (prix pour 1000 unités) ---
    "sp1": {"name": "Plays (1K)", "cat": "SMM", "sub": "Spotify", "price": 1.50},
    "sp2": {"name": "Followers (1K)", "cat": "SMM", "sub": "Spotify", "price": 6},

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
    "SMM": ["Telegram", "TikTok", "Instagram", "YouTube", "X", "Discord", "Twitch", "Spotify"],
    "Comptes & Abonnements": ["Streaming", "Musique & Audio", "IA", "VPN", "Mail", "Outils"],
    "Cartes cadeaux": ["Amazon", "Steam", "PlayStation", "Xbox", "Google Play", "Apple"],
}

# --- Stock -------------------------------------------------------------
# Stock illimité par défaut (tu récupères les comptes après paiement). Un produit n'a
# de stock limité que si tu lui en donnes un (Admin > Stock : `id quantité`).
STOCK: dict[str, int] = {}

SEUIL_STOCK_BAS = 3  # en dessous de ce nombre, affiche "plus que X en stock"


def stock_of(pid: str):
    """None = illimité (service SMM). Un entier = nombre de comptes restants."""
    return STOCK.get(pid)


def in_stock(pid: str, qty: int = 1) -> bool:
    s = stock_of(pid)
    return s is None or s >= qty


CARTS: dict[int, dict[str, int]] = {}

# --- Réglages des fonctions avancées (modifiables) --------------------------
ORDER_EXPIRY_HOURS = float(os.environ.get("ORDER_EXPIRY_HOURS", "24"))  # 0 = jamais d'expiration
REF_PERCENT = float(os.environ.get("REF_PERCENT", "5"))                 # % du montant reversé au parrain
# Paliers de fidélité : (dépense cumulée en € sur commandes terminées, nom, remise %)
TIERS = [(300, "💎 Diamant", 8), (100, "🥇 Or", 5), (30, "🥈 Argent", 3), (0, "🥉 Bronze", 0)]
# Remises au volume sur les services SMM : (nombre minimum de paquets de 1K, remise %)
BULK_DISCOUNTS = [(50, 10), (10, 5)]

BANNER_KEYS = list(CATEGORIES) + [f"{c}|{s}" for c, subs in SUBCATEGORIES.items() for s in subs]
VOUCH_URL = next((u for label, u in CHANNELS if "vouch" in label.lower()), "")

CART_PROMO: dict = {}        # client -> code promo appliqué au panier
PROMO_STATE: set = set()     # clients en train d'écrire un code promo
SEARCH_STATE: set = set()    # clients en train d'écrire une recherche
TOPUP_STATE: set = set()     # clients qui rechargent leur solde
PROOF_STATE: dict = {}       # client -> commande pour laquelle il va envoyer sa preuve de paiement
REVIEW_STATE: dict = {}      # client -> commande dont il écrit le commentaire d'avis
BROADCAST_PENDING: dict = {} # admin -> message de diffusion en attente de confirmation
HIDDEN: set = set()          # produits masqués
CAT_HIDDEN: set = set()      # catégories ("Cat") et sous-catégories ("Cat|Sous") masquées
BANNERS: dict = {}           # bannières par catégorie / sous-catégorie
LANG_CACHE: dict = {}
LAST_EXPIRY = 0.0
BOT_USERNAME = ""

# --- Base de données (PostgreSQL / Neon) -----------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    raise RuntimeError("Variable DATABASE_URL manquante (lien de connexion Neon).")


# Pool de connexions : on garde des connexions Neon ouvertes et on les réutilise
# (ouvrir une connexion SSL à chaque requête coûtait ~100-300 ms à chaque fois).
_DB_IDLE: list = []            # (connexion, dernier usage)
_DB_LOCK = threading.Lock()
_DB_MAX_IDLE = int(os.environ.get("DB_POOL_SIZE", "8"))
_DB_PING_AFTER = 20.0          # après 20 s d'inactivité, on vérifie que la connexion vit encore


def _db_open():
    return psycopg2.connect(
        DATABASE_URL, connect_timeout=10,
        keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=3,
    )


def _db_take():
    """Renvoie une connexion ouverte : réutilisée si possible, sinon une nouvelle."""
    while True:
        with _DB_LOCK:
            item = _DB_IDLE.pop() if _DB_IDLE else None
        if item is None:
            return _db_open()
        raw, last = item
        if raw.closed:
            continue
        if time.time() - last > _DB_PING_AFTER:
            try:
                cur = raw.cursor()
                cur.execute("SELECT 1")
                cur.close()
                raw.rollback()
            except Exception:
                try:
                    raw.close()
                except Exception:
                    pass
                continue
        return raw


class _Conn:
    """Petit adaptateur : garde la même écriture que SQLite (? et row["colonne"]).
    close() ne ferme plus vraiment la connexion : elle retourne dans le pool."""

    def __init__(self):
        self._c = _db_take()
        self._dirty = False   # une requête a déjà été envoyée dans la transaction en cours

    def execute(self, sql, params=()):
        sql = sql.replace("?", "%s")
        for attempt in (0, 1):
            try:
                cur = self._c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute(sql, params)
                self._dirty = True
                return cur
            except (psycopg2.OperationalError, psycopg2.InterfaceError):
                # Connexion coupée côté Neon : on rouvre et on retente,
                # sauf si des requêtes étaient déjà passées dans cette transaction.
                if attempt or self._dirty:
                    raise
                try:
                    self._c.close()
                except Exception:
                    pass
                self._c = _db_open()

    def commit(self):
        self._c.commit()
        self._dirty = False

    def close(self):
        raw, self._c = self._c, None
        if raw is None:
            return
        try:
            if raw.closed:
                return
            raw.rollback()   # annule tout ce qui n'a pas été validé, remet la connexion à zéro
        except Exception:
            try:
                raw.close()
            except Exception:
                pass
            return
        with _DB_LOCK:
            if len(_DB_IDLE) < _DB_MAX_IDLE:
                _DB_IDLE.append((raw, time.time()))
                return
        try:
            raw.close()
        except Exception:
            pass


def db_connect():
    return _Conn()


_STATS_CACHE: dict = {}


def cached_stat(name, fn, ttl=60):
    """Petit cache mémoire pour les chiffres qui n'ont pas besoin d'être à la seconde."""
    now = time.time()
    hit = _STATS_CACHE.get(name)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    _STATS_CACHE[name] = (now, val)
    return val


def init_db():
    conn = db_connect()
    conn.execute("""CREATE TABLE IF NOT EXISTS orders (
        id SERIAL PRIMARY KEY,
        telegram_id BIGINT NOT NULL,
        username TEXT,
        total DOUBLE PRECISION NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending_payment',
        created_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS order_items (
        id SERIAL PRIMARY KEY,
        order_id INTEGER NOT NULL REFERENCES orders(id),
        product_id TEXT NOT NULL,
        product_name TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        unit_price DOUBLE PRECISION NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS users (
        telegram_id BIGINT PRIMARY KEY,
        username TEXT,
        balance DOUBLE PRECISION NOT NULL DEFAULT 0
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")
    # --- Nouvelles colonnes / tables (fidélité, promos, parrainage, avis...) ---
    for stmt in (
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS lang TEXT DEFAULT 'fr'",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS referrer_id BIGINT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS ref_earned DOUBLE PRECISION NOT NULL DEFAULT 0",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS discount DOUBLE PRECISION NOT NULL DEFAULT 0",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS promo_code TEXT",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS paid_with_balance BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS ref_rewarded BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS proof_sent BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS paid_at TEXT",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery TEXT",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivered_at TEXT",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS reminded BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS received DOUBLE PRECISION NOT NULL DEFAULT 0",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS credited DOUBLE PRECISION NOT NULL DEFAULT 0",
    ):
        conn.execute(stmt)
    conn.execute("""CREATE TABLE IF NOT EXISTS promo_codes (
        code TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        value DOUBLE PRECISION NOT NULL,
        max_uses INTEGER,
        used INTEGER NOT NULL DEFAULT 0,
        expires_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS promo_uses (
        code TEXT NOT NULL,
        telegram_id BIGINT NOT NULL,
        PRIMARY KEY (code, telegram_id)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS reviews (
        id SERIAL PRIMARY KEY,
        order_id INTEGER UNIQUE NOT NULL,
        telegram_id BIGINT NOT NULL,
        username TEXT,
        rating INTEGER NOT NULL,
        comment TEXT,
        created_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS restock_alerts (
        product_id TEXT NOT NULL,
        telegram_id BIGINT NOT NULL,
        PRIMARY KEY (product_id, telegram_id)
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


_SETTINGS = {"t": 0.0, "data": {}}
_SETTINGS_TTL = 60.0
_SETTINGS_LOCK = threading.Lock()


def _settings_data():
    """Tous les réglages en mémoire (rechargés depuis la base toutes les 60 s)."""
    if time.time() - _SETTINGS["t"] > _SETTINGS_TTL:
        with _SETTINGS_LOCK:
            if time.time() - _SETTINGS["t"] > _SETTINGS_TTL:
                try:
                    conn = db_connect()
                    rows = conn.execute("SELECT key, value FROM settings").fetchall()
                    conn.close()
                    _SETTINGS["data"] = {r["key"]: r["value"] for r in rows}
                    _SETTINGS["t"] = time.time()
                except Exception:
                    if _SETTINGS["t"] == 0.0:
                        raise
                    _SETTINGS["t"] = time.time() - _SETTINGS_TTL + 10  # on garde l'ancien cache, nouvel essai dans 10 s
    return _SETTINGS["data"]


def get_setting(key, default=None):
    data = _settings_data()
    return data[key] if key in data else default


def set_setting(key, value):
    conn = db_connect()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()
    _settings_data()[key] = value


def del_setting(key):
    conn = db_connect()
    conn.execute("DELETE FROM settings WHERE key = ?", (key,))
    conn.commit()
    conn.close()
    _settings_data().pop(key, None)


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


def _all_settings():
    return dict(_settings_data())


def load_custom_products():
    """Produits ajoutés depuis le panneau admin (stockés en base)."""
    try:
        items = json.loads(get_setting("custom_products", "[]"))
    except ValueError:
        items = []
    for it in items:
        PRODUCTS[it["id"]] = {"name": it["name"], "cat": it["cat"], "sub": it["sub"], "price": float(it["price"])}
        if it.get("limited"):
            STOCK.setdefault(it["id"], int(it.get("stock", 0)))


def load_price_overrides():
    """Prix, noms, produits masqués et bannières enregistrés depuis le panneau admin."""
    s = _all_settings()
    for pid in PRODUCTS:
        v = s.get(f"price:{pid}")
        if v is not None:
            try:
                PRODUCTS[pid]["price"] = float(v)
            except ValueError:
                pass
        if s.get(f"name:{pid}"):
            PRODUCTS[pid]["name"] = s[f"name:{pid}"]
        if s.get(f"hidden:{pid}") == "1":
            HIDDEN.add(pid)
        mv = s.get(f"move:{pid}")
        if mv and "|" in mv:
            PRODUCTS[pid]["cat"], PRODUCTS[pid]["sub"] = mv.split("|", 1)
    for key in BANNER_KEYS:
        if s.get(f"banner:{key}"):
            BANNERS[key] = s[f"banner:{key}"]


def load_catalog_extra():
    """Catégories / sous-catégories créées depuis l'admin + masquages."""
    try:
        extra = json.loads(get_setting("catalog_extra", "{}"))
    except ValueError:
        extra = {}
    for cat, subs in extra.items():
        if cat not in CATEGORIES:
            CATEGORIES.append(cat)
        lst = SUBCATEGORIES.setdefault(cat, [])
        for sub in subs:
            if sub not in lst:
                lst.append(sub)
    try:
        CAT_HIDDEN.clear()
        CAT_HIDDEN.update(json.loads(get_setting("catalog_hidden", "[]")))
    except ValueError:
        pass
    rebuild_banner_keys()


def rebuild_banner_keys():
    BANNER_KEYS[:] = list(CATEGORIES) + [f"{c}|{s}" for c, subs in SUBCATEGORIES.items() for s in subs]


refresh_settings()
load_catalog_extra()
load_custom_products()
load_price_overrides()


def load_stock():
    """Recharge le stock enregistré dans la base (sinon valeur par défaut = 5)."""
    s = _all_settings()
    for pid in STOCK:
        v = s.get(f"stock:{pid}")
        if v is not None:
            try:
                STOCK[pid] = int(v)
            except ValueError:
                pass


def save_stock(pid):
    set_setting(f"stock:{pid}", str(STOCK[pid]))


load_stock()


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
            if cb in ("checkout", "paybal") or cb.startswith("ipaid:") or cb.endswith((":completed", ":paid")):
                b["style"] = "success"
            elif cb == "clear" or cb.endswith(":cancelled"):
                b["style"] = "danger"
            new_row.append(b)
        out.append(new_row)
    return out


ENHANCED_METHODS = {"sendMessage", "editMessageText", "sendPhoto", "editMessageMedia"}


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
    media = p.get("media")
    if EMOJI_MAP and isinstance(media, dict) and media.get("parse_mode") == "Markdown" and "caption" in media:
        p["media"] = dict(media, caption=apply_custom_emoji(md_to_html(media["caption"])), parse_mode="HTML")
    return p


_USER_SEEN: dict = {}   # client -> dernier pseudo enregistré (évite une écriture à chaque clic)


def upsert_user(user):
    """Enregistre / met à jour le client et renvoie son @ (ou son prénom)."""
    username = f"@{user['username']}" if user.get("username") else (user.get("first_name") or "client")
    if _USER_SEEN.get(user["id"]) == username:
        return username
    conn = db_connect()
    conn.execute(
        "INSERT INTO users (telegram_id, username, balance) VALUES (?, ?, 0) "
        "ON CONFLICT(telegram_id) DO UPDATE SET username = excluded.username",
        (user["id"], username),
    )
    conn.commit()
    conn.close()
    _USER_SEEN[user["id"]] = username
    return username


def get_balance(telegram_id):
    conn = db_connect()
    row = conn.execute("SELECT balance FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
    conn.close()
    return round(row["balance"], 2) if row else 0.0


def add_balance(telegram_id, delta):
    """Ajoute (ou retire si négatif) du solde. Ne descend jamais sous 0. Renvoie le nouveau solde."""
    conn = db_connect()
    conn.execute("INSERT INTO users (telegram_id, username, balance) VALUES (?, NULL, 0) ON CONFLICT (telegram_id) DO NOTHING", (telegram_id,))
    conn.execute("UPDATE users SET balance = GREATEST(0, ROUND((balance + ?)::numeric, 2)) WHERE telegram_id = ?", (delta, telegram_id))
    conn.commit()
    row = conn.execute("SELECT balance FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
    conn.close()
    return round(row["balance"], 2)


def spend_balance(telegram_id, amount):
    """Débite le solde seulement s'il est suffisant. Renvoie True si le paiement est passé."""
    conn = db_connect()
    cur = conn.execute(
        "UPDATE users SET balance = ROUND((balance - ?)::numeric, 2) WHERE telegram_id = ? AND balance >= ?",
        (amount, telegram_id, amount),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def create_order(telegram_id, username, cart, total, status="pending_payment",
                 discount=0.0, promo_code=None, paid_with_balance=False):
    conn = db_connect()
    cur = conn.execute(
        "INSERT INTO orders (telegram_id, username, total, status, created_at, discount, promo_code, paid_with_balance) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
        (telegram_id, username, total, status, datetime.now(timezone.utc).isoformat(),
         discount, promo_code, paid_with_balance),
    )
    order_id = cur.fetchone()["id"]
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
    if status == "paid":
        conn.execute("UPDATE orders SET paid_at = ? WHERE id = ?", (datetime.now(timezone.utc).isoformat(), order_id))
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


# --- Fidélité, remises, codes promo ------------------------------------------

def user_exists(telegram_id):
    conn = db_connect()
    row = conn.execute("SELECT 1 AS x FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
    conn.close()
    return bool(row)


def completed_count():
    conn = db_connect()
    row = conn.execute("SELECT COUNT(*) AS n FROM orders WHERE status = 'completed'").fetchone()
    conn.close()
    return row["n"]


def user_spent(telegram_id):
    conn = db_connect()
    row = conn.execute(
        "SELECT COALESCE(SUM(total), 0) AS s FROM orders WHERE telegram_id = ? AND status = 'completed'",
        (telegram_id,),
    ).fetchone()
    conn.close()
    return float(row["s"] or 0)


def tier_of(spent):
    for threshold, label, pct in TIERS:
        if spent >= threshold:
            return label, pct
    return TIERS[-1][1], TIERS[-1][2]


def next_tier(spent):
    higher = [t for t in TIERS if t[0] > spent]
    return min(higher, key=lambda t: t[0]) if higher else None


def check_promo(code, telegram_id):
    """Renvoie (ligne_du_code, None) si le code est utilisable, sinon (None, message d'erreur)."""
    code = (code or "").strip().upper()
    conn = db_connect()
    row = conn.execute("SELECT * FROM promo_codes WHERE code = ?", (code,)).fetchone()
    used = None
    if row:
        used = conn.execute(
            "SELECT 1 AS x FROM promo_uses WHERE code = ? AND telegram_id = ?", (code, telegram_id)
        ).fetchone()
    conn.close()
    if not row:
        return None, "Code inconnu."
    if row["expires_at"] and row["expires_at"] < datetime.now(timezone.utc).isoformat():
        return None, "Ce code a expiré."
    if row["max_uses"] is not None and row["used"] >= row["max_uses"]:
        return None, "Ce code n'est plus disponible."
    if used:
        return None, "Tu as déjà utilisé ce code."
    return row, None


def use_promo(code, telegram_id):
    conn = db_connect()
    conn.execute("INSERT INTO promo_uses (code, telegram_id) VALUES (?, ?) ON CONFLICT DO NOTHING", (code, telegram_id))
    conn.execute("UPDATE promo_codes SET used = used + 1 WHERE code = ?", (code,))
    conn.commit()
    conn.close()


def cart_pricing(chat_id):
    """Calcule le panier : remise volume (SMM) + palier de fidélité + code promo."""
    cart = get_cart(chat_id)
    subtotal = bulk = 0.0
    lines = []
    for pid, qty in cart.items():
        p = PRODUCTS[pid]
        line = p["price"] * qty
        pct = 0
        if p["cat"] == "SMM":
            for min_q, pc in BULK_DISCOUNTS:
                if qty >= min_q:
                    pct = pc
                    break
        subtotal += line
        bulk += round(line * pct / 100, 2)
        lines.append((pid, qty, line, pct))
    tier_label, tier_pct = tier_of(user_spent(chat_id))
    base = subtotal - bulk
    tier_disc = round(base * tier_pct / 100, 2)
    promo_disc, promo_error = 0.0, None
    code = CART_PROMO.get(chat_id)
    if code:
        row, promo_error = check_promo(code, chat_id)
        if row:
            after = base - tier_disc
            if row["kind"] == "percent":
                promo_disc = round(after * row["value"] / 100, 2)
            else:
                promo_disc = min(float(row["value"]), round(after, 2))
        else:
            CART_PROMO.pop(chat_id, None)
            code = None
    total = max(0.0, round(subtotal - bulk - tier_disc - promo_disc, 2))
    return dict(
        lines=lines, subtotal=round(subtotal, 2), bulk=round(bulk, 2),
        tier_label=tier_label, tier_pct=tier_pct, tier_disc=tier_disc,
        promo_code=code, promo_disc=round(promo_disc, 2), promo_error=promo_error,
        total=total, discount=round(subtotal - total, 2),
    )


# --- Avis clients ---------------------------------------------------------------

def reviews_summary():
    conn = db_connect()
    row = conn.execute("SELECT COUNT(*) AS n, AVG(rating) AS a FROM reviews").fetchone()
    conn.close()
    return row["n"], float(row["a"] or 0)


def has_review(order_id):
    conn = db_connect()
    row = conn.execute("SELECT 1 AS x FROM reviews WHERE order_id = ?", (order_id,)).fetchone()
    conn.close()
    return bool(row)


def save_review(order_id, telegram_id, username, rating):
    conn = db_connect()
    cur = conn.execute(
        "INSERT INTO reviews (order_id, telegram_id, username, rating, created_at) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT (order_id) DO NOTHING",
        (order_id, telegram_id, username, rating, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def set_review_comment(order_id, comment):
    conn = db_connect()
    conn.execute("UPDATE reviews SET comment = ? WHERE order_id = ?", (comment[:500], order_id))
    conn.commit()
    conn.close()


def stars(n):
    return "⭐" * int(n)


# --- Stock : réassort, alertes de retour, annulations -----------------------------

def add_alert(pid, telegram_id):
    conn = db_connect()
    conn.execute("INSERT INTO restock_alerts (product_id, telegram_id) VALUES (?, ?) ON CONFLICT DO NOTHING", (pid, telegram_id))
    conn.commit()
    conn.close()


def notify_restock(pid):
    conn = db_connect()
    ids = [r["telegram_id"] for r in conn.execute("SELECT telegram_id FROM restock_alerts WHERE product_id = ?", (pid,)).fetchall()]
    conn.execute("DELETE FROM restock_alerts WHERE product_id = ?", (pid,))
    conn.commit()
    conn.close()

    def _send():
        for uid in ids:
            send_message(
                uid,
                f"🔔 *De retour en stock !*\n\n{PRODUCTS[pid]['name']} est de nouveau disponible.",
                [[{"text": "🛍 Voir la fiche", "callback_data": f"prod:{pid}"}]],
                parse_mode="Markdown",
            )
            time.sleep(0.05)

    if ids:
        threading.Thread(target=_send, daemon=True).start()


def restock(pid, delta):
    """Ajoute (ou retire) du stock ; prévient les clients en attente si le produit revient."""
    before = STOCK.get(pid, 0)
    STOCK[pid] = max(0, before + delta)
    save_stock(pid)
    if before == 0 and STOCK[pid] > 0:
        notify_restock(pid)
    return STOCK[pid]


def cancel_side_effects(order):
    """Commande annulée : on remet le stock et on rembourse si elle était payée avec le solde."""
    for item in get_order_items(order["id"]):
        if item["product_id"] in STOCK:
            restock(item["product_id"], item["quantity"])
    if order["paid_with_balance"]:
        add_balance(order["telegram_id"], order["total"])


def expire_orders(force=False):
    """Annule les commandes impayées depuis trop longtemps (vérifié au plus toutes les 5 min)."""
    global LAST_EXPIRY
    if ORDER_EXPIRY_HOURS <= 0:
        return
    now = time.time()
    if not force and now - LAST_EXPIRY < 300:
        return
    LAST_EXPIRY = now
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=ORDER_EXPIRY_HOURS)).isoformat()
        conn = db_connect()
        rows = conn.execute(
            "SELECT id FROM orders WHERE status = 'pending_payment' AND proof_sent = FALSE AND created_at < ?",
            (cutoff,),
        ).fetchall()
        conn.close()
        for r in rows:
            conn = db_connect()
            cur = conn.execute("UPDATE orders SET status = 'cancelled' WHERE id = ? AND status = 'pending_payment'", (r["id"],))
            conn.commit()
            conn.close()
            if cur.rowcount:
                order = get_order_by_id(r["id"])
                cancel_side_effects(order)
                send_message(
                    order["telegram_id"],
                    f"⌛ *Commande #{order['id']:05d} expirée*\n\n"
                    f"Aucun paiement reçu sous {ORDER_EXPIRY_HOURS:g} h : elle a été annulée automatiquement. "
                    "Tu peux la repasser à tout moment.",
                    [[{"text": "🔁 Recommander", "callback_data": f"reorder:{order['id']}"}]],
                    parse_mode="Markdown",
                )
    except Exception as e:  # ne jamais faire tomber le bot pour ça
        print("expire_orders:", e)


# --- Parrainage -----------------------------------------------------------------

def bot_username():
    global BOT_USERNAME
    if not BOT_USERNAME:
        r = _post("getMe", {})
        BOT_USERNAME = (r.get("result") or {}).get("username", "")
    return BOT_USERNAME


def set_referrer(new_id, ref_id):
    """Enregistre le parrain d'un nouveau client. Renvoie l'id du parrain si valide."""
    try:
        ref_id = int(ref_id)
    except (TypeError, ValueError):
        return None
    if ref_id == new_id or not user_exists(ref_id):
        return None
    conn = db_connect()
    cur = conn.execute("UPDATE users SET referrer_id = ? WHERE telegram_id = ? AND referrer_id IS NULL", (ref_id, new_id))
    conn.commit()
    conn.close()
    return ref_id if cur.rowcount else None


def reward_referrer(order):
    """Commande terminée : le parrain reçoit REF_PERCENT % du montant sur son solde (une seule fois)."""
    if REF_PERCENT <= 0 or not order:
        return
    conn = db_connect()
    u = conn.execute("SELECT referrer_id FROM users WHERE telegram_id = ?", (order["telegram_id"],)).fetchone()
    if not u or not u["referrer_id"]:
        conn.close()
        return
    cur = conn.execute("UPDATE orders SET ref_rewarded = TRUE WHERE id = ? AND ref_rewarded = FALSE", (order["id"],))
    conn.commit()
    conn.close()
    if not cur.rowcount:
        return
    bonus = round(order["total"] * REF_PERCENT / 100, 2)
    if bonus <= 0:
        return
    ref = u["referrer_id"]
    new_balance = add_balance(ref, bonus)
    conn = db_connect()
    conn.execute("UPDATE users SET ref_earned = ref_earned + ? WHERE telegram_id = ?", (bonus, ref))
    conn.commit()
    conn.close()
    send_message(
        ref,
        f"🎁 *Bonus de parrainage : +{fmt(bonus)}*\n\nUn de tes filleuls vient de terminer une commande.\n"
        f"Nouveau solde : *{fmt(new_balance)}*",
        parse_mode="Markdown",
    )


def get_info(pid):
    try:
        return json.loads(get_setting(f"info:{pid}") or "{}")
    except ValueError:
        return {}


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
    spent = user_spent(chat_id)
    tier_label, tier_pct = tier_of(spent)
    lines = [
        "👤 *Mon profil*",
        "━━━━━━━━━━━━━━━",
        "",
        f"🆔 ID : `{chat_id}`",
        f"💰 Solde : *{fmt(get_balance(chat_id))}*",
        f"🏅 Niveau : *{tier_label}*" + (f" (-{tier_pct}% sur tes commandes)" if tier_pct else ""),
        f"📦 Commandes : *{stats['total_orders']}*",
        f"✅ Terminées : *{stats['completed_orders'] or 0}*",
        f"⚙️ En cours : *{active}*",
        f"❌ Annulées : *{stats['cancelled_orders'] or 0}*",
        f"💰 Total dépensé : *{fmt(stats['total_spent'] or 0)}*",
    ]
    nxt = next_tier(spent)
    if nxt:
        lines.append(f"🎯 Prochain niveau : *{nxt[1]}* dès {fmt(nxt[0])} de commandes terminées")
    if orders:
        lines += ["", "🕘 *Dernières commandes*"]
        for order in orders:
            status = ORDER_STATUSES.get(order["status"], order["status"])
            lines.append(f"• #{order['id']:05d} · {fmt(order['total'])} · {status}")
    else:
        lines += ["", "_Aucune commande pour le moment. Ta première t'attend en boutique 🛍_"]
    rows = [
        [{"text": "📦 Mes commandes", "callback_data": "orders"},
         {"text": "💳 Recharger", "callback_data": "topup"}],
        [{"text": "🎁 Parrainage", "callback_data": "ref"},
         {"text": "🔄 Actualiser", "callback_data": "profile"}],
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
    if order["discount"]:
        code = f" ({order['promo_code']})" if order["promo_code"] else ""
        lines.append(f"🏷 Remise : -{fmt(order['discount'])}{code}")
    lines += ["", f"*Total : {fmt(order['total'])}*"]
    if order["status"] == "pending_payment" and order["received"]:
        lines.append(f"💵 Reçu : *{fmt(order['received'])}* · Reste à payer : *{fmt(round(order['total'] - order['received'], 2))}*")
    lines.append(f"📅 {order['created_at'].replace('T', ' ')[:16]} UTC")
    rows = []
    if order["status"] == "pending_payment":
        rows.append([{"text": "✅ J'ai payé", "callback_data": f"ipaid:{order_id}"}])
    rows.append([{"text": "🔄 Actualiser le suivi", "callback_data": f"track:{order_id}"}])
    if order["status"] == "completed" and not has_review(order_id):
        rows.append([{"text": "⭐ Laisser un avis", "callback_data": f"rate:{order_id}"}])
    rows.append([{"text": "🔁 Recommander", "callback_data": f"reorder:{order_id}"}])
    rows.append([{"text": "⬅️ Mes commandes", "callback_data": "orders"},
                 {"text": "🏠 Boutique", "callback_data": "menu"}])
    return "\n".join(lines), rows


def admin_order_keyboard(order_id):
    return [
        [{"text": "✅ Confirmer paiement", "callback_data": f"adminstatus:{order_id}:paid"},
         {"text": "❌ Refuser", "callback_data": f"adminstatus:{order_id}:cancelled"}],
        [{"text": "💵 Montant reçu", "callback_data": f"adminrecv:{order_id}"}],
        [{"text": "⚙️ Traitement", "callback_data": f"adminstatus:{order_id}:processing"},
         {"text": "🏁 Terminée", "callback_data": f"adminstatus:{order_id}:completed"}],
        [{"text": "📦 Livrer les accès", "callback_data": f"deliver:{order_id}"}],
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
    if order["discount"]:
        detail += f"\n🏷 Remise : -{fmt(order['discount'])}" + (f" ({order['promo_code']})" if order["promo_code"] else "")
    status = ORDER_STATUSES.get(order["status"], order["status"])
    recv = ""
    if order["received"]:
        recv = f"💵 Reçu : *{fmt(order['received'])}* / {fmt(order['total'])}\n"
        if order["credited"]:
            recv += f"➕ Surplus crédité : {fmt(order['credited'])}\n"
    return (
        f"📦 *Commande #{order_id:05d}*\n"
        f"👤 `{order['username'] or 'Client'}` — id `{order['telegram_id']}`\n\n"
        f"{detail}\n\n"
        f"*Total : {fmt(order['total'])}*\n"
        f"{recv}"
        f"*Statut :* {status}"
    )


# --- Langue (FR / EN) -------------------------------------------------------
# Le bot est écrit en français. Pour un client en anglais, chaque message et chaque
# bouton passe par ce dictionnaire de fragments. Ce qui n'y figure pas reste en français.
EN = {
    # accueil
    "Bienvenue chez": "Welcome to", "Pseudo": "Username", "Solde": "Balance", "solde": "balance",
    "Fais grimper ta présence en ligne": "Grow your online presence",
    "Tarifs bas, catalogue clair": "Low prices, clear catalog",
    "Tout est affiché avec le prix, sans surprise.": "Everything is listed with its price, no surprises.",
    "Commande en 3 étapes": "Order in 3 steps",
    "Choisis tes produits": "Pick your products",
    "Règle en crypto": "Pay in crypto",
    "Un vendeur confirme et te livre": "A seller confirms and delivers",
    "Suis ta commande en direct depuis le bot.": "Track your order live from the bot.",
    "Choisis une catégorie pour commencer": "Pick a category to get started",
    "commandes livrées": "orders delivered", " avis)": " reviews)", "Niveau": "Level",
    # menus
    "Comptes & Abonnements": "Accounts & Subscriptions", "Comptes & Abos": "Accounts & Subs",
    "Musique & Audio": "Music & Audio", "Outils": "Tools", "🤖 IA": "🤖 AI",
    "Recherche": "Search", "Nouvelle recherche": "New search", "Parrainage": "Referral",
    "Langue": "Language", "Profil": "Profile", "Canaux": "Channels", "Canal": "Channel",
    "Portail": "Portal", "Boutique": "Shop", "Accueil": "Home", "Retour": "Back",
    "Panier": "Cart", "panier": "cart", "Mes commandes": "My orders", "Commandes": "Orders",
    "commandes": "orders", "Commande": "Order", "commande": "order",
    "Actualiser le suivi": "Refresh tracking", "Actualiser": "Refresh",
    "Suivre ma commande": "Track my order", "Recommander": "Reorder",
    "Laisser un avis": "Leave a review", "Recharger mon solde": "Top up my balance", "Recharger": "Top up",
    "Me prévenir du retour": "Notify me when back", "Contacter le support": "Contact support",
    # catalogue
    "Booste tes réseaux : followers, vues, likes, réactions...": "Boost your socials: followers, views, likes, reactions...",
    "Prix pour 1 000 unités": "Price per 1,000 units", "choisis ta plateforme": "pick your platform",
    "choisis une catégorie": "pick a category", "touche un produit pour voir sa fiche": "tap a product to see its details",
    "plus que": "only", "rupture": "sold out", "Stock illimité": "Unlimited stock", "En stock": "In stock",
    "Rupture de stock": "Out of stock", "Plus que": "Only", "Prix :": "Price:", "Durée": "Duration",
    "Garantie": "Warranty", "Livraison": "Delivery", "Remises au volume": "Volume discounts",
    "dès ": "from ", "Déjà dans ton panier": "Already in your cart", "Chaque ➕ = 1 paquet de 1 000": "Each ➕ = 1 pack of 1,000",
    "Ajouté au panier": "Added to cart",
    # panier
    "Ton panier est vide": "Your cart is empty", "Ton panier": "Your cart",
    "Rien ici pour l'instant, mais ça se remplit vite 😉": "Nothing here yet, but it fills up fast 😉",
    "Parcours la boutique et ajoute ce qui t'intéresse.": "Browse the shop and add what you like.",
    "Vérifie ton panier puis valide pour recevoir les infos de paiement.": "Check your cart, then confirm to get the payment details.",
    "Valider ma commande": "Confirm my order", "Payer avec mon solde": "Pay with my balance",
    "Vider": "Empty", "Sous-total": "Subtotal", "Remise volume": "Volume discount", "Remise": "Discount",
    "Code promo": "Promo code", "Retirer le code": "Remove code", "Code retiré": "Code removed",
    "Écris ton code ici.": "Type your code here.", "appliqué": "applied", "Code": "Code",
    "Total à régler": "Total to pay", "Total dépensé": "Total spent", "Total :": "Total:", " / 1 000 unités": " / 1,000 units",
    # commande
    "Commande enregistrée !": "Order placed!", "Comment payer": "How to pay",
    "Envoie le montant exact à l'une de ces adresses": "Send the exact amount to one of these addresses",
    "appui long sur l'adresse pour la copier": "long-press the address to copy it",
    "Ensuite": "Then",
    "Appuie sur *J'ai payé*, puis envoie ici la capture du paiement (ou le hash). Un vendeur vérifie, confirme et traite ta commande. Tu reçois une notification à chaque étape.":
        "Tap *I've paid*, then send a screenshot of the payment (or the hash) here. A seller checks, confirms and processes your order. You get a notification at every step.",
    "Besoin d'aide ?": "Need help?",
    "Un souci avec tes accès ? Contacte le support avec ton numéro de commande, on s'en occupe vite": "Problem with your access? Contact support with your order number, we'll sort it out quickly",
    "J'ai payé": "I've paid", "Preuve de paiement": "Proof of payment",
    "Envoie ici la *capture* de ton paiement ou le *hash* de la transaction.": "Send a *screenshot* of your payment or the transaction *hash* here.",
    "/passer pour annuler": "/passer to cancel", "Suivre ma commande": "Track my order",
    "Complément à régler": "Balance to pay", "Nous avons reçu": "We received", "total attendu": "expected total",
    "Reste à envoyer": "Left to send", "aux mêmes adresses": "to the same addresses",
    "Ensuite, appuie sur *J'ai payé* et envoie la preuve du complément.": "Then tap *I've paid* and send the proof for the remaining amount.",
    "Surplus de ta commande": "Overpayment from your order", "Reçu :": "Received:", "Reste à payer": "Left to pay",
    "Suivi disponible dans": "Tracking available in", "Réf. à indiquer : ton pseudo Telegram": "Ref.: your Telegram username",
    "Commande payée avec ton solde !": "Order paid with your balance!", "Montant": "Amount",
    "Solde restant": "Remaining balance",
    "Un vendeur prend ta commande en charge. Tu reçois une notification à chaque étape.":
        "A seller is handling your order. You get a notification at every step.",
    "Paiement reçu, merci !": "Payment received, thank you!",
    "Ta commande est validée et passe bientôt en traitement.": "Your order is confirmed and will be processed shortly.",
    "Ta commande est en cours de traitement.": "Your order is being processed.",
    "Tes accès arrivent ici dès qu'ils sont prêts.": "Your access details will arrive here as soon as they're ready.",
    "livrée !": "delivered!", "Voici tes accès 👇": "Here are your access details 👇",
    "On s'en occupe, tu seras prévenu dès qu'elle est prête.": "We're on it, you'll be notified as soon as it's ready.",
    "Ta commande est terminée !": "Your order is complete!",
    "Merci pour ta confiance 🖤 N'hésite pas à revenir.": "Thanks for your trust 🖤 Come back anytime.",
    "Ta commande a été annulée.": "Your order was cancelled.",
    "Un souci ? Contacte le vendeur avec ton numéro de commande.": "Any issue? Contact the seller with your order number.",
    "expirée": "expired", "Aucun paiement reçu sous": "No payment received within",
    "elle a été annulée automatiquement. Tu peux la repasser à tout moment.": "it was cancelled automatically. You can place it again anytime.",
    "En attente de paiement": "Awaiting payment", "Paiement reçu": "Payment received",
    "En traitement": "Processing", "Terminée": "Completed", "Annulée": "Cancelled",
    "Terminées": "Completed", "Annulées": "Cancelled", "En cours": "In progress", "Statut :": "Status:",
    # profil / commandes
    "Mon profil": "My profile", "Dernières commandes": "Latest orders",
    "Aucune commande pour le moment. Ta première t'attend en boutique": "No orders yet. Your first one is waiting in the shop",
    "Aucune commande pour le moment.": "No orders yet.",
    "Passe ta première commande depuis la boutique.": "Place your first order from the shop.",
    "Prochain niveau": "Next level", "de commandes terminées": "of completed orders", "sur tes commandes": "on your orders",
    "Commande introuvable.": "Order not found.",
    # support / canaux
    "Une question, un souci avec une commande ou un paiement ?": "A question, an issue with an order or a payment?",
    "Écris-nous en indiquant ton": "Write to us with your", "numéro de commande": "order number",
    "Nos canaux": "Our channels", "Retrouve tous nos canaux officiels ci-dessous.": "Find all our official channels below.",
    # parrainage
    "Partage ton lien : chaque fois qu'un filleul termine une commande, tu reçois": "Share your link: each time a referral completes an order, you get",
    "du montant sur ton solde.": "of the amount on your balance.",
    "Filleuls": "Referrals", "Gains": "Earnings", "Partager mon lien": "Share my link",
    "Nouveau filleul !": "New referral!", "Quelqu'un vient de rejoindre grâce à ton lien.": "Someone just joined with your link.",
    "Bonus de parrainage": "Referral bonus", "Nouveau solde": "New balance",
    # avis
    "Ton avis compte !": "Your opinion matters!", "Note ta commande": "Rate your order", "Merci pour ton avis": "Thanks for your review",
    "Tu peux ajouter un commentaire en l'écrivant ici (ou /passer).": "You can add a comment by writing it here (or /passer).",
    "Poster sur Vouch": "Post on Vouch", "Commentaire enregistré, merci ! 🖤": "Comment saved, thanks! 🖤",
    # recherche / recharge / langue
    "Écris un mot-clé : produit, plateforme ou catégorie.": "Type a keyword: product, platform or category.",
    "Résultats pour": "Results for", "Aucun résultat pour": "No results for",
    "Essaie un autre mot (ex. netflix, tiktok, vpn).": "Try another word (e.g. netflix, tiktok, vpn).",
    "Envoie une capture de ton paiement (ou le hash) avec le montant.": "Send a screenshot of your payment (or the hash) with the amount.",
    "Un vendeur crédite ton solde après vérification.": "A seller credits your balance after checking.",
    "Preuve transmise !": "Proof sent!", "Un vendeur vérifie ton paiement et te tient au courant ici.": "A seller is checking your payment and will update you here.",
    "De retour en stock !": "Back in stock!", "Voir la fiche": "See details",
    "Compris ! Tu seras prévenu dès qu'il est de retour.": "Got it! You'll be notified as soon as it's back.",
    "Code inconnu.": "Unknown code.", "Ce code a expiré.": "This code has expired.",
    "Ce code n'est plus disponible.": "This code is no longer available.",
    "Tu as déjà utilisé ce code.": "You already used this code.",
    "Solde crédité": "Balance credited",
}
EN_ITEMS = sorted(EN.items(), key=lambda kv: -len(kv[0]))


def translate_en(text):
    for fr, en in EN_ITEMS:
        text = text.replace(fr, en)
    return re.sub(r" ([:!?;])", r"\1", text)  # ponctuation anglaise (pas d'espace avant : ! ? ;)


def get_lang(chat_id):
    if chat_id in LANG_CACHE:
        return LANG_CACHE[chat_id]
    lang = "fr"
    try:
        conn = db_connect()
        row = conn.execute("SELECT lang FROM users WHERE telegram_id = ?", (chat_id,)).fetchone()
        conn.close()
        if row and row["lang"]:
            lang = row["lang"]
    except Exception:
        pass
    LANG_CACHE[chat_id] = lang
    return lang


def set_lang(chat_id, lang):
    conn = db_connect()
    conn.execute("UPDATE users SET lang = ? WHERE telegram_id = ?", (lang, chat_id))
    conn.commit()
    conn.close()
    LANG_CACHE[chat_id] = lang


def localize(method, payload):
    """Traduit texte + boutons pour les clients en anglais (jamais pour l'admin)."""
    if method not in ENHANCED_METHODS:
        return payload
    chat_id = payload.get("chat_id")
    if chat_id is None or is_admin_chat(chat_id) or get_lang(chat_id) != "en":
        return payload
    p = dict(payload)
    for field in ("text", "caption"):
        if isinstance(p.get(field), str):
            p[field] = translate_en(p[field])
    media = p.get("media")
    if isinstance(media, dict) and isinstance(media.get("caption"), str):
        p["media"] = dict(media, caption=translate_en(media["caption"]))
    markup = p.get("reply_markup")
    if markup and markup.get("inline_keyboard"):
        p["reply_markup"] = {"inline_keyboard": [
            [dict(b, text=translate_en(b["text"])) for b in row] for row in markup["inline_keyboard"]
        ]}
    return p


# --- Appels bruts à l'API Telegram -----------------------------------------

# Une seule "session" réutilisée : la connexion HTTPS à Telegram reste ouverte
# (pas de nouvelle poignée de main SSL à chaque message).
_HTTP = requests.Session()
_HTTP.mount("https://", HTTPAdapter(pool_connections=4, pool_maxsize=40))


def _post(method, payload):
    for attempt in (0, 1):
        try:
            r = _HTTP.post(f"{API_URL}/{method}", json=payload, timeout=(5, 15)).json()
        except requests.exceptions.ConnectionError:
            if attempt:
                return {}
            continue                      # connexion réutilisée coupée : on réessaie une fois
        except Exception:
            return {}
        if not r.get("ok") and r.get("error_code") == 429 and attempt == 0:
            wait = (r.get("parameters") or {}).get("retry_after", 1)
            time.sleep(min(float(wait), 5))   # Telegram demande d'attendre un peu
            continue
        return r
    return {}


def _tg_call_core(method: str, payload: dict):
    """Appelle l'API Telegram. Essaie d'abord avec emojis premium / couleurs ;
    si Telegram refuse, renvoie la version classique : le bot ne casse jamais."""
    payload = localize(method, payload)
    if PREMIUM_UI and method in ENHANCED_METHODS:
        r = _post(method, enhance_payload(method, payload))
        if r.get("ok"):
            return r
        desc = str(r.get("description", "")).lower()
        if "not modified" in desc or "no text" in desc:
            return r
    return _post(method, payload)


# Images : Telegram doit re-télécharger une image donnée par lien à chaque envoi.
# Après le 1er envoi on garde son file_id, ensuite l'envoi est instantané.
_FILE_IDS: dict = {}


def _photo_ref(method, payload):
    if method == "sendPhoto":
        return payload.get("photo")
    if method == "editMessageMedia":
        return (payload.get("media") or {}).get("media")
    return None


def _with_photo(method, payload, ref):
    p = dict(payload)
    if method == "sendPhoto":
        p["photo"] = ref
    else:
        p["media"] = dict(p["media"], media=ref)
    return p


def tg_call(method: str, payload: dict):
    ref = _photo_ref(method, payload) if method in ("sendPhoto", "editMessageMedia") else None
    if isinstance(ref, str) and ref.startswith("http"):
        fid = _FILE_IDS.get(ref)
        if fid:
            r = _tg_call_core(method, _with_photo(method, payload, fid))
            if r.get("ok") or "not modified" in str(r.get("description", "")).lower():
                return r
            _FILE_IDS.pop(ref, None)      # file_id refusé : on retombe sur le lien
        r = _tg_call_core(method, payload)
        if r.get("ok"):
            try:
                photos = (r.get("result") or {}).get("photo")
                if photos:
                    _FILE_IDS[ref] = photos[-1]["file_id"]
            except Exception:
                pass
        return r
    return _tg_call_core(method, payload)


def send_message(chat_id, text, keyboard=None, parse_mode=None):
    payload = {"chat_id": chat_id, "text": text}
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    return tg_call("sendMessage", payload)


def welcome_text(user):
    username = upsert_user(user).replace("`", "")
    tier_label, _ = tier_of(user_spent(user["id"]))
    done = cached_stat("completed", completed_count)
    values = dict(
        user_id=user["id"], username=username, balance=fmt(get_balance(user["id"])),
        orders_done=done, tier=tier_label,
    )
    template = get_setting("welcome_text") or TEXT_WELCOME
    try:
        text = template.format(**values)
    except (KeyError, IndexError, ValueError):
        template = TEXT_WELCOME
        text = TEXT_WELCOME.format(**values)
    if "{orders_done}" not in template:
        proof = []
        if done:
            proof.append(f"✅ *{done}* commandes livrées")
        n_rev, avg = cached_stat("reviews", reviews_summary)
        if n_rev >= 3:
            proof.append(f"⭐ *{avg:.1f}/5* ({n_rev} avis)")
        footer = " · ".join(proof)
        text += "\n\n" + (footer + "\n" if footer else "") + f"🏅 Niveau : *{tier_label}*"
    return text


_CTX = threading.local()   # contexte de la mise à jour en cours (le message cliqué est-il une photo ?)


def _is_photo_msg(message_id):
    return getattr(_CTX, "photo_msg", None) == message_id


def _edit_photo_screen(chat_id, message_id, photo, text, keyboard):
    """Photo -> photo : on remplace l'image et le texte sur place (pas de message qui clignote)."""
    r = tg_call("editMessageMedia", {
        "chat_id": chat_id, "message_id": message_id,
        "media": {"type": "photo", "media": photo, "caption": text, "parse_mode": "Markdown"},
        "reply_markup": {"inline_keyboard": keyboard},
    })
    return bool(r.get("ok")) or "not modified" in str(r.get("description", "")).lower()


def show_home(chat_id, message_id, user):
    """Retour à l'accueil en modifiant le message existant quand c'est possible."""
    kb = kb_categories(chat_id)
    text = welcome_text(user)
    banner = current_banner()
    if banner and _is_photo_msg(message_id) and len(text) <= 1000:
        if _edit_photo_screen(chat_id, message_id, banner, text, kb):
            return
    elif not banner and not _is_photo_msg(message_id):
        r = tg_call("editMessageText", {
            "chat_id": chat_id, "message_id": message_id, "text": text,
            "parse_mode": "Markdown", "reply_markup": {"inline_keyboard": kb},
        })
        if r.get("ok") or "not modified" in str(r.get("description", "")).lower():
            return
    tg_call("deleteMessage", {"chat_id": chat_id, "message_id": message_id})
    send_home(chat_id, user, text, kb)


def send_home(chat_id, user, text=None, kb=None):
    """Écran d'accueil (ID, @, solde) avec bannière si définie."""
    if kb is None:
        kb = kb_categories(chat_id)
    if text is None:
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
    # Si le message d'origine est une photo (accueil), on ne peut pas l'éditer en texte :
    # on le supprime et on renvoie un message texte à la place (sans perdre un appel inutile).
    if not _is_photo_msg(message_id):
        r = tg_call("editMessageText", payload)
        if r.get("ok") or "no text" not in str(r.get("description", "")).lower():
            return r
    tg_call("deleteMessage", {"chat_id": chat_id, "message_id": message_id})
    return send_message(chat_id, text, keyboard, parse_mode)


def show_screen(chat_id, message_id, text, keyboard, photo=None):
    """Affiche un écran ; avec une bannière (photo) si elle existe pour cette catégorie."""
    if photo and len(text) <= 1000:
        if _is_photo_msg(message_id) and _edit_photo_screen(chat_id, message_id, photo, text, keyboard):
            return
        tg_call("deleteMessage", {"chat_id": chat_id, "message_id": message_id})
        r = tg_call("sendPhoto", {
            "chat_id": chat_id, "photo": photo, "caption": text,
            "parse_mode": "Markdown", "reply_markup": {"inline_keyboard": keyboard},
        })
        if not r.get("ok"):
            send_message(chat_id, text, keyboard, parse_mode="Markdown")
        return
    edit_message(chat_id, message_id, text, keyboard, parse_mode="Markdown")


_FAST = ThreadPoolExecutor(max_workers=8, thread_name_prefix="cb")


def answer_callback(callback_id, text=None, alert=False):
    """Répond au clic (arrête le sablier du bouton) sans bloquer le reste du traitement."""
    payload = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text
        payload["show_alert"] = alert
    _FAST.submit(tg_call, "answerCallbackQuery", payload)


# --- Écrans (mêmes menus qu'avant) ------------------------------------------

CATEGORY_LABELS = {
    "SMM": "📈 SMM",
    "Comptes & Abonnements": "🔐 Comptes & Abos",
    "Cartes cadeaux": "🎁 Cartes cadeaux",
}


def cart_count(chat_id):
    return sum(get_cart(chat_id).values())


def sub_visible(cat, sub):
    return f"{cat}|{sub}" not in CAT_HIDDEN and bool(_items(cat, sub))


def cat_visible(cat):
    return cat not in CAT_HIDDEN and any(sub_visible(cat, s) for s in SUBCATEGORIES.get(cat, []))


def kb_categories(chat_id=None):
    count = cart_count(chat_id) if chat_id is not None else 0
    cart_label = f"🛒 Panier · {count}" if count else "🛒 Panier"
    cats = [{"text": CATEGORY_LABELS.get(c, "📂 " + c), "callback_data": f"cat:{c}"} for c in CATEGORIES if cat_visible(c)]
    rows = [
        *[cats[i:i + 2] for i in range(0, len(cats), 2)],
        [{"text": "🔍 Recherche", "callback_data": "search"},
         {"text": cart_label, "callback_data": "cart"}],
        [{"text": "📦 Commandes", "callback_data": "orders"},
         {"text": "👤 Profil", "callback_data": "profile"}],
        [{"text": "💬 Support", "callback_data": "support"},
         {"text": "📢 Canaux", "callback_data": "channels"}],
        [{"text": "🎁 Parrainage", "callback_data": "ref"},
         {"text": "🌐 Langue", "callback_data": "lang"}],
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
    "Instagram": "📸 Instagram",
    "YouTube": "▶️ YouTube",
    "X": "🐦 X / Twitter",
    "Discord": "💬 Discord",
    "Twitch": "🟣 Twitch",
    "Spotify": "🎧 Spotify",
    "Amazon": "📦 Amazon",
    "Steam": "🎮 Steam",
    "PlayStation": "🎮 PlayStation",
    "Xbox": "🎮 Xbox",
    "Google Play": "▶️ Google Play",
    "Apple": "🍎 Apple",
}


def kb_subcats(cat):
    subs = [
        {"text": SUBCAT_LABELS.get(s, s), "callback_data": f"sub:{cat}:{s}"}
        for s in SUBCATEGORIES[cat] if sub_visible(cat, s)
    ]
    rows = [subs[i:i + 2] for i in range(0, len(subs), 2)]
    rows.append([{"text": "🛒 Panier", "callback_data": "cart"},
                 {"text": "⬅️ Retour", "callback_data": "menu"}])
    return rows


def _items(cat, sub=None):
    return [
        (pid, p) for pid, p in PRODUCTS.items()
        if pid not in HIDDEN and p["cat"] == cat and (sub is None or p.get("sub") == sub)
    ]


def kb_products(cat, sub=None):
    btns = []
    for pid, p in _items(cat, sub):
        s = stock_of(pid)
        if s == 0:
            btns.append({"text": f"❌ {p['name']}", "callback_data": f"prod:{pid}"})
        else:
            label = f"{p['name']} · {fmt(p['price'])}"
            if s is not None and s <= SEUIL_STOCK_BAS:
                label += f" ({s})"
            btns.append({"text": label, "callback_data": f"prod:{pid}"})
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
    lines.append("\n_touche un produit pour voir sa fiche_ 👇")
    return "\n".join(lines)


def cart_view(chat_id):
    cart = get_cart(chat_id)
    if not cart:
        return TEXT_EMPTY_CART, [
            [{"text": "🛍 Boutique", "callback_data": "menu"}],
            [{"text": "📦 Mes commandes", "callback_data": "orders"}],
        ]

    pr = cart_pricing(chat_id)
    lines = [TEXT_CART_TITLE]
    for pid, qty, line, pct in pr["lines"]:
        extra = f" _(-{pct}% volume)_" if pct else ""
        lines.append(f"• {PRODUCTS[pid]['name']} x{qty} — {fmt(line)}{extra}")
    lines.append("\n━━━━━━━━━━━━━━━")
    if pr["discount"] > 0:
        lines.append(f"Sous-total : {fmt(pr['subtotal'])}")
        if pr["bulk"]:
            lines.append(f"🎁 Remise volume : -{fmt(pr['bulk'])}")
        if pr["tier_disc"]:
            lines.append(f"{pr['tier_label']} (-{pr['tier_pct']}%) : -{fmt(pr['tier_disc'])}")
        if pr["promo_disc"]:
            lines.append(f"🏷 Code {pr['promo_code']} : -{fmt(pr['promo_disc'])}")
    lines.append(f"💰 *Total : {fmt(pr['total'])}*")
    if pr["promo_error"]:
        lines.append(f"\n⚠️ Code retiré : {pr['promo_error']}")
    lines.append("\n_Vérifie ton panier puis valide pour recevoir les infos de paiement._")

    rows = [
        [{"text": "✅ Valider ma commande", "callback_data": "checkout"}],
    ]
    balance = get_balance(chat_id)
    if balance > 0 and balance >= pr["total"]:
        rows.append([{"text": f"💰 Payer avec mon solde ({fmt(balance)})", "callback_data": "paybal"}])
    if pr["promo_code"]:
        rows.append([{"text": "🏷 Retirer le code", "callback_data": "promo_del"}])
    else:
        rows.append([{"text": "🏷 Code promo", "callback_data": "promo"}])
    rows.append([{"text": "🗑 Vider", "callback_data": "clear"},
                 {"text": "🛍 Boutique", "callback_data": "menu"}])
    return "\n".join(lines), rows


def product_view(pid, chat_id):
    """Fiche produit : prix, stock, infos (durée / garantie / livraison), remises au volume."""
    p = PRODUCTS[pid]
    s = stock_of(pid)
    unit = " / 1 000 unités" if p["cat"] == "SMM" else ""
    lines = [f"🛍 *{p['name']}*", "━━━━━━━━━━━━━━━", "", f"💎 Prix : *{fmt(p['price'])}*{unit}"]
    if s is None:
        lines.append("♾ Stock illimité")
    elif s == 0:
        lines.append("🔴 Rupture de stock")
    elif s <= SEUIL_STOCK_BAS:
        lines.append(f"🟠 Plus que {s} en stock")
    else:
        lines.append(f"🟢 En stock ({s})")
    info = get_info(pid)
    for key, label in (("duration", "⏳ Durée"), ("warranty", "🛡 Garantie"), ("delay", "⚡ Livraison")):
        if info.get(key):
            lines.append(f"{label} : {info[key]}")
    if info.get("desc"):
        lines += ["", info["desc"]]
    if p["cat"] == "SMM":
        lines += ["", "🎁 *Remises au volume*"] + [f"• dès {q}K → -{pct}%" for q, pct in sorted(BULK_DISCOUNTS)]
        lines.append("_Chaque ➕ = 1 paquet de 1 000_")
    in_cart = get_cart(chat_id).get(pid, 0)
    if in_cart:
        lines += ["", f"🛒 Déjà dans ton panier : *x{in_cart}*"]
    if s == 0:
        rows = [[{"text": "🔔 Me prévenir du retour", "callback_data": f"alert:{pid}"}]]
    else:
        rows = [[{"text": f"➕ {n}", "callback_data": f"addn:{pid}:{n}"} for n in (1, 5, 10)]]
    back = f"sub:{p['cat']}:{p['sub']}" if p.get("sub") else f"cat:{p['cat']}"
    rows.append([{"text": "🛒 Panier", "callback_data": "cart"},
                 {"text": "⬅️ Retour", "callback_data": back}])
    return "\n".join(lines), rows


def search_view(query):
    safe = re.sub(r"[*_`\[\]]", "", query).strip()[:40]
    tokens = safe.lower().split()
    hits = []
    for pid, p in PRODUCTS.items():
        if pid in HIDDEN:
            continue
        hay = f"{p['name']} {p.get('sub') or ''} {p['cat']}".lower()
        if tokens and all(t in hay for t in tokens):
            hits.append((pid, p))
    rows = [
        [{"text": f"{p['name']} · {fmt(p['price'])}" + (" ❌" if stock_of(pid) == 0 else ""),
          "callback_data": f"prod:{pid}"}]
        for pid, p in hits[:12]
    ]
    if hits:
        text = f"🔍 *Résultats pour « {safe} »*\n━━━━━━━━━━━━━━━\n"
    else:
        text = f"🔍 *Aucun résultat pour « {safe} »*\n\n_Essaie un autre mot (ex. netflix, tiktok, vpn)._"
    rows.append([{"text": "🔍 Nouvelle recherche", "callback_data": "search"},
                 {"text": "🏠 Accueil", "callback_data": "menu"}])
    return text, rows


def referral_view(chat_id):
    username = bot_username()
    conn = db_connect()
    n = conn.execute("SELECT COUNT(*) AS n FROM users WHERE referrer_id = ?", (chat_id,)).fetchone()["n"]
    row = conn.execute("SELECT ref_earned FROM users WHERE telegram_id = ?", (chat_id,)).fetchone()
    conn.close()
    earned = float(row["ref_earned"] or 0) if row else 0.0
    rows = []
    text = "🎁 *Parrainage*\n━━━━━━━━━━━━━━━\n\n"
    if username:
        link = f"https://t.me/{username}?start=ref_{chat_id}"
        text += (
            f"Partage ton lien : chaque fois qu'un filleul termine une commande, tu reçois *{REF_PERCENT:g}%* "
            "du montant sur ton solde.\n\n"
            f"🔗 `{link}`\n\n"
        )
        share = "https://t.me/share/url?url=" + quote(link, safe="") + "&text=" + quote("Rejoins-moi sur la boutique 🖤", safe="")
        rows.append([{"text": "📤 Partager mon lien", "url": share}])
    else:
        text += "Lien indisponible pour le moment, réessaie dans un instant.\n\n"
    text += f"👥 Filleuls : *{n}*\n💰 Gains : *{fmt(earned)}*"
    rows.append([{"text": "⬅️ Profil", "callback_data": "profile"}])
    return text, rows


def language_view():
    return (
        "🌐 *Langue / Language*\n━━━━━━━━━━━━━━━\n\nChoisis ta langue · Choose your language",
        [[{"text": "🇫🇷 Français", "callback_data": "lang:fr"},
          {"text": "🇬🇧 English", "callback_data": "lang:en"}],
         [{"text": "🏠 Accueil", "callback_data": "menu"}]],
    )


ADMIN_HOME_TEXT = "🛠 *Panneau admin*\n━━━━━━━━━━━━━━━\n\nChoisis ce que tu veux modifier 👇"

ADMIN_BACK = [{"text": "⬅️ Panneau admin", "callback_data": "adm:home"}]


def admin_home_kb():
    return [
        [{"text": "🖼 Bannière", "callback_data": "adm:banner"},
         {"text": "🗂 Bannières catég.", "callback_data": "adm:catban"}],
        [{"text": "✏️ Accueil", "callback_data": "adm:welcome"},
         {"text": "🎨 Emojis premium", "callback_data": "adm:emoji"}],
        [{"text": "💰 Solde client", "callback_data": "adm:credit"},
         {"text": "🎟 Codes promo", "callback_data": "adm:promo"}],
        [{"text": "📦 Stock", "callback_data": "adm:stock"},
         {"text": "🏷 Prix", "callback_data": "adm:price"}],
        [{"text": "🧩 Produits", "callback_data": "adm:products"},
         {"text": "🗂 Catégories", "callback_data": "adm:catalog"}],
        [{"text": "🧾 Fiches produit", "callback_data": "adm:info"},
         {"text": "📝 Msg livraison", "callback_data": "adm:delmsg"}],
        [{"text": "📣 Diffusion", "callback_data": "adm:broadcast"},
         {"text": "⭐ Avis", "callback_data": "adm:reviews"}],
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
    now = datetime.now(timezone.utc)

    def revenue_since(cutoff):
        r = conn.execute(
            "SELECT COALESCE(SUM(total), 0) AS s FROM orders "
            "WHERE status IN ('paid', 'processing', 'completed') AND created_at >= ?",
            (cutoff.isoformat(),),
        ).fetchone()
        return float(r["s"] or 0)

    today = revenue_since(now.replace(hour=0, minute=0, second=0, microsecond=0))
    week = revenue_since(now - timedelta(days=7))
    month = revenue_since(now - timedelta(days=30))
    top = conn.execute(
        """SELECT oi.product_name AS name, SUM(oi.quantity) AS q
           FROM order_items oi JOIN orders o ON o.id = oi.order_id
           WHERE o.status <> 'cancelled'
           GROUP BY oi.product_name ORDER BY q DESC LIMIT 5"""
    ).fetchall()
    conn.close()
    n_rev, avg = reviews_summary()
    lines = [
        "📊 *Stats*\n━━━━━━━━━━━━━━━\n",
        f"👥 Clients : *{clients}*",
        f"📦 Commandes : *{row['n']}*",
        f"🟡 En attente de paiement : *{row['pending'] or 0}*",
        f"⚙️ Payées / en cours : *{row['running'] or 0}*",
        f"✅ Terminées : *{row['done'] or 0}*",
        "",
        f"💰 Aujourd'hui : *{fmt(today)}*",
        f"💰 7 jours : *{fmt(week)}*",
        f"💰 30 jours : *{fmt(month)}*",
        f"💰 Total encaissé : *{fmt(row['revenue'])}*",
    ]
    if top:
        lines += ["", "🏆 *Top produits*"] + [f"• {t['name']} — x{t['q']}" for t in top]
    if n_rev:
        lines += ["", f"⭐ Avis : *{avg:.1f}/5* ({n_rev})"]
    return "\n".join(lines)


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
        lines = [f"`{pid}` {PRODUCTS[pid]['name']} : {qty}" for pid, qty in sorted(STOCK.items()) if pid in PRODUCTS] or ["_Aucun stock limité pour l'instant._"]
        return (
            "📦 *Stock*\n━━━━━━━━━━━━━━━\n\n" + "\n".join(lines) +
            "\n\n_Produits absents de la liste = stock illimité._\n"
            "Envoie : `id quantité` pour ajouter (ex. `a04 10`, négatif pour retirer) "
            "ou `id illimité` pour retirer la limite.",
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

    if action == "promo":
        ADMIN_STATE[chat_id] = "promo"
        conn = db_connect()
        rows = conn.execute("SELECT * FROM promo_codes ORDER BY code").fetchall()
        conn.close()
        lines = []
        for r in rows:
            val = f"-{r['value']:g}%" if r["kind"] == "percent" else f"-{fmt(r['value'])}"
            limit = r["max_uses"] if r["max_uses"] is not None else "∞"
            exp = f" · exp. {r['expires_at'][:10]}" if r["expires_at"] else ""
            lines.append(f"`{r['code']}` {val} · {r['used']}/{limit}{exp}")
        return (
            "🎟 *Codes promo*\n━━━━━━━━━━━━━━━\n\n"
            + ("\n".join(lines) if lines else "_Aucun code pour l'instant._")
            + "\n\nCréer : `CODE 10%` ou `CODE 2€`\n"
            "Avec limites : `CODE 10% 50 30` = 50 utilisations max, valable 30 jours.\n"
            "Supprimer : `- CODE`\n\n_Un client ne peut utiliser un code qu'une fois._",
            [ADMIN_BACK],
        )

    if action == "info":
        ADMIN_STATE[chat_id] = "info"
        return (
            "🧾 *Fiches produit*\n━━━━━━━━━━━━━━━\n\n"
            "Envoie : `id | durée | garantie | livraison | description`\n"
            "Ex. `a04 | 1 mois | 30 jours | Instantanée`\n"
            "Laisse un champ vide pour ne pas l'afficher, ou envoie juste `a04` pour tout effacer.\n\n"
            "_Les ids sont dans 🏷 Prix. Seuls les champs remplis apparaissent sur la fiche._",
            [ADMIN_BACK],
        )

    if action == "delmsg":
        ADMIN_STATE[chat_id] = "delmsg"
        st = _all_settings()
        done = [f"`{pid}` {PRODUCTS[pid]['name']}" for pid in PRODUCTS if (st.get(f"delmsg:{pid}") or "").strip()]
        return (
            "📝 *Messages de livraison*\n━━━━━━━━━━━━━━━\n\n"
            "Ce texte est envoyé au client juste après ses accès (mode d'emploi, garantie, conseils).\n\n"
            "Créer / modifier : `id | ton message`\n"
            "Voir : `id`\n"
            "Supprimer : `- id`\n"
            "Variables : `{product}` `{order_id}`\n\n"
            "Configurés : " + (", ".join(done) or "aucun") + "\n"
            "_Sans modèle, un message par défaut est envoyé. Les ids sont dans 🏷 Prix._",
            [ADMIN_BACK],
        )

    if action == "catalog":
        ADMIN_STATE[chat_id] = "catalog"
        lines = []
        for c in CATEGORIES:
            mark = "🙈 " if c in CAT_HIDDEN else ""
            subs = ", ".join(("🙈" if f"{c}|{s}" in CAT_HIDDEN else "") + s for s in SUBCATEGORIES.get(c, []))
            lines.append(f"• {mark}*{c}* : {subs}")
        return (
            "🗂 *Catégories*\n━━━━━━━━━━━━━━━\n\n" + "\n".join(lines) + "\n\n"
            "➕ Catégorie : `+cat Nom | Sous1, Sous2`\n"
            "➕ Sous-catégorie : `+sub Catégorie | Nom`\n"
            "🙈 Masquer / réafficher : `~cat Nom` ou `~sub Catégorie | Nom`\n\n"
            "_Une catégorie sans produit visible n'apparaît pas chez les clients. "
            "Ajoute ensuite les produits dans 🧩 Produits._",
            [ADMIN_BACK],
        )

    if action == "products":
        ADMIN_STATE[chat_id] = "products"
        subs = " · ".join(s for subs_ in SUBCATEGORIES.values() for s in subs_)
        hidden = ", ".join(f"`{p}`" for p in sorted(HIDDEN)) or "aucun"
        return (
            "🧩 *Produits*\n━━━━━━━━━━━━━━━\n\n"
            "➕ Ajouter : `+ Sous-catégorie | Nom | Prix | Stock`\n"
            "Ex. `+ IA | Midjourney | 8 | 5` (stock vide = illimité)\n"
            f"Sous-catégories : {subs}\n\n"
            "👁 Masquer / réafficher : `- id`\n"
            "✏️ Renommer : `= id | Nouveau nom`\n"
            "🔀 Déplacer : `> id | Catégorie | Sous-catégorie`\n"
            "🗑 Supprimer (produits ajoutés ici) : `x id`\n\n"
            f"Masqués : {hidden}\n_Les ids sont dans 🏷 Prix._",
            [ADMIN_BACK],
        )

    if action == "broadcast":
        ADMIN_STATE[chat_id] = "broadcast"
        return (
            "📣 *Diffusion*\n━━━━━━━━━━━━━━━\n\n"
            "Envoie le message à diffuser à *tous les clients* (texte, ou photo avec légende). "
            "Je te montre un aperçu et tu confirmes avant l'envoi.",
            [ADMIN_BACK],
        )

    if action == "reviews":
        n, avg = reviews_summary()
        conn = db_connect()
        rows = conn.execute("SELECT * FROM reviews ORDER BY id DESC LIMIT 8").fetchall()
        conn.close()
        lines = []
        for r in rows:
            c = f" — {r['comment'][:80]}" if r["comment"] else ""
            lines.append(f"{stars(r['rating'])} #{r['order_id']:05d} {r['username'] or ''}{c}")
        return (
            f"⭐ *Avis*\n━━━━━━━━━━━━━━━\n\nMoyenne : *{avg:.1f}/5* ({n})\n\n"
            + ("\n".join(lines) if lines else "_Aucun avis pour l'instant._"),
            [ADMIN_BACK],
        )

    if action == "catban":
        rows = [
            [{"text": ("✅ " if key in BANNERS else "▫️ ") + key.replace("|", " › "), "callback_data": f"adm:cb:{i}"}]
            for i, key in enumerate(BANNER_KEYS)
        ]
        rows.append(ADMIN_BACK)
        return (
            "🗂 *Bannières par catégorie*\n━━━━━━━━━━━━━━━\n\n"
            "Choisis un écran : sa bannière s'affichera au-dessus du menu. "
            "Une sous-catégorie sans bannière reprend celle de sa catégorie.",
            rows,
        )

    if action.startswith("cb:"):
        idx = int(action[3:])
        key = BANNER_KEYS[idx]
        ADMIN_STATE[chat_id] = f"catban:{idx}"
        etat = "✅ active" if key in BANNERS else "aucune"
        return (
            f"🗂 *Bannière · {key.replace('|', ' › ')}*\n━━━━━━━━━━━━━━━\n\n"
            f"Statut : {etat}\n\nEnvoie-moi *une photo*.",
            [[{"text": "🗑 Retirer", "callback_data": f"adm:cbdel:{idx}"}],
             [{"text": "⬅️ Bannières", "callback_data": "adm:catban"}], ADMIN_BACK],
        )

    if action.startswith("cbdel:"):
        key = BANNER_KEYS[int(action[6:])]
        set_setting(f"banner:{key}", "")
        BANNERS.pop(key, None)
        return admin_screen(chat_id, "catban")

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

    if action == "bc_go":
        mid = BROADCAST_PENDING.pop(chat_id, None)
        if mid:
            threading.Thread(target=run_broadcast, args=(chat_id, mid), daemon=True).start()
            edit_message(chat_id, message_id, "📣 *Diffusion en cours…*\nJe te préviens à la fin.", [ADMIN_BACK], parse_mode="Markdown")
        else:
            edit_message(chat_id, message_id, "Aucun message en attente.", [ADMIN_BACK])
        return
    if action == "bc_no":
        BROADCAST_PENDING.pop(chat_id, None)
        action = "home"

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

    elif mode and mode.startswith("deliver:"):
        order_id = int(mode.split(":", 1)[1])
        order = get_order_by_id(order_id)
        if not text:
            send_message(chat_id, "Envoie les accès en texte, ou /annuler.")
            return
        if not order or order["status"] in ("cancelled", "completed"):
            ADMIN_STATE.pop(chat_id, None)
            send_message(chat_id, "❌ Commande introuvable, annulée ou déjà terminée.", back_kb)
            return
        ADMIN_STATE.pop(chat_id, None)
        deliver_order(order_id, text)
        send_message(chat_id, f"✅ Accès envoyés au client — commande #{order_id:05d} terminée.", back_kb)

    elif mode == "delmsg":
        if text.startswith("-"):
            pid = text[1:].strip()
            if pid not in PRODUCTS:
                send_message(chat_id, "Id inconnu (voir 🏷 Prix).")
                return
            del_setting(f"delmsg:{pid}")
            send_message(chat_id, f"🗑 Message de livraison supprimé pour {PRODUCTS[pid]['name']} (le message par défaut sera utilisé).", back_kb)
            return
        pid, sep, body = text.partition("|")
        pid, body = pid.strip(), body.strip()
        if pid not in PRODUCTS:
            send_message(chat_id, "Id inconnu (voir 🏷 Prix). Format : `id | message`", parse_mode="Markdown")
            return
        if not sep:
            cur = (get_setting(f"delmsg:{pid}") or "").strip()
            send_message(chat_id, f"📝 {PRODUCTS[pid]['name']} :\n\n" + (cur or "(aucun message : le message par défaut est utilisé)"))
            return
        if not body or len(body) > 3500:
            send_message(chat_id, "Message vide ou trop long (3500 caractères max). Réessaie ou /annuler.")
            return
        set_setting(f"delmsg:{pid}", body)
        _post("sendMessage", {"chat_id": chat_id, "text": body.replace("{order_id}", "00042").replace("{product}", PRODUCTS[pid]["name"])})
        send_message(chat_id, f"✅ Message de livraison enregistré pour {PRODUCTS[pid]['name']} (aperçu ci-dessus).", back_kb)

    elif mode and mode.startswith("recv:"):
        order_id = int(mode.split(":", 1)[1])
        try:
            amount = round(float(text.replace(",", ".").replace("€", "").strip()), 2)
            assert 0 < amount < 100000
        except (ValueError, AssertionError):
            send_message(chat_id, "Envoie un montant en € (ex. `12.5`), ou /annuler.", parse_mode="Markdown")
            return
        ADMIN_STATE.pop(chat_id, None)
        process_received(chat_id, order_id, amount)

    elif mode == "restock":
        parts = text.split()
        ok = len(parts) == 2 and parts[0] in PRODUCTS and (
            parts[1].lstrip("-").isdigit() or parts[1].lower() in ("illimité", "illimite", "inf"))
        if not ok:
            send_message(chat_id, "Format : `id quantité` (ex. `a04 10`) ou `id illimité`, ou /annuler.", parse_mode="Markdown")
            return
        pid = parts[0]
        if parts[1].lower() in ("illimité", "illimite", "inf"):
            STOCK.pop(pid, None)
            del_setting(f"stock:{pid}")
            send_message(chat_id, f"✅ {PRODUCTS[pid]['name']} : stock illimité.", back_kb)
            return
        STOCK.setdefault(pid, 0)
        restock(pid, int(parts[1]))
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

    elif mode == "broadcast":
        if not (text or msg.get("photo")):
            send_message(chat_id, "Envoie un texte ou une photo avec légende, ou /annuler.")
            return
        BROADCAST_PENDING[chat_id] = msg["message_id"]
        ADMIN_STATE.pop(chat_id, None)
        conn = db_connect()
        n = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
        conn.close()
        tg_call("copyMessage", {"chat_id": chat_id, "from_chat_id": chat_id, "message_id": msg["message_id"]})
        send_message(
            chat_id, f"📣 Aperçu ci-dessus. Envoyer à *{n}* clients ?",
            [[{"text": "✅ Envoyer", "callback_data": "adm:bc_go"},
              {"text": "❌ Annuler", "callback_data": "adm:bc_no"}]],
            parse_mode="Markdown",
        )

    elif mode == "promo":
        if text.startswith("-"):
            code = text[1:].strip().upper()
            conn = db_connect()
            cur = conn.execute("DELETE FROM promo_codes WHERE code = ?", (code,))
            conn.execute("DELETE FROM promo_uses WHERE code = ?", (code,))
            conn.commit()
            conn.close()
            send_message(chat_id, f"🗑 Code `{code}` supprimé." if cur.rowcount else "Code introuvable.", back_kb, parse_mode="Markdown")
            return
        parts = text.split()
        try:
            code = parts[0].upper()
            assert re.fullmatch(r"[A-Z0-9-]{3,20}", code)
            kind = "percent" if parts[1].endswith("%") else "fixed"
            value = float(parts[1].rstrip("%€").replace(",", "."))
            assert value > 0 and (kind == "fixed" or value <= 100)
            max_uses = int(parts[2]) if len(parts) > 2 else None
            expires = (datetime.now(timezone.utc) + timedelta(days=int(parts[3]))).isoformat() if len(parts) > 3 else None
        except (IndexError, ValueError, AssertionError):
            send_message(
                chat_id,
                "Format : `CODE 10%` ou `CODE 2€` (lettres/chiffres, 3 à 20 caractères), "
                "optionnel : `CODE 10% 50 30`. Ou /annuler.",
                parse_mode="Markdown",
            )
            return
        conn = db_connect()
        conn.execute(
            "INSERT INTO promo_codes (code, kind, value, max_uses, expires_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (code) DO UPDATE SET kind = excluded.kind, value = excluded.value, "
            "max_uses = excluded.max_uses, expires_at = excluded.expires_at",
            (code, kind, value, max_uses, expires),
        )
        conn.commit()
        conn.close()
        val = f"-{value:g}%" if kind == "percent" else f"-{fmt(value)}"
        send_message(chat_id, f"✅ Code `{code}` créé : {val}", back_kb, parse_mode="Markdown")

    elif mode == "info":
        parts = [x.strip() for x in text.split("|")]
        pid = parts[0]
        if pid not in PRODUCTS:
            send_message(chat_id, "Id inconnu (voir 🏷 Prix). Format : `id | durée | garantie | livraison | description`", parse_mode="Markdown")
            return
        keys = ["duration", "warranty", "delay", "desc"]
        info = {k: parts[i + 1] for i, k in enumerate(keys) if i + 1 < len(parts) and parts[i + 1]}
        if info:
            set_setting(f"info:{pid}", json.dumps(info, ensure_ascii=False))
        else:
            del_setting(f"info:{pid}")
        send_message(chat_id, f"✅ Fiche de {PRODUCTS[pid]['name']} mise à jour.", back_kb)

    elif mode == "products":
        if text.startswith("+"):
            parts = [x.strip() for x in text[1:].split("|")]
            valid = {s.lower(): (c, s) for c, subs in SUBCATEGORIES.items() for s in subs}
            try:
                cat, sub = valid[parts[0].lower()]
                name = parts[1]
                price = round(float(parts[2].replace(",", ".")), 2)
                assert name and price > 0
                stock = int(parts[3]) if len(parts) > 3 and parts[3] else None
            except (KeyError, IndexError, ValueError, AssertionError):
                send_message(chat_id, "Format : `+ Sous-catégorie | Nom | Prix | Stock` (ex. `+ IA | Midjourney | 8 | 5`), ou /annuler.", parse_mode="Markdown")
                return
            items = json.loads(get_setting("custom_products", "[]"))
            pid = "c" + str(1 + max([int(i["id"][1:]) for i in items] or [0]))
            items.append({"id": pid, "name": name, "cat": cat, "sub": sub, "price": price,
                          "limited": stock is not None, "stock": stock or 0})
            set_setting("custom_products", json.dumps(items, ensure_ascii=False))
            PRODUCTS[pid] = {"name": name, "cat": cat, "sub": sub, "price": price}
            if stock is not None:
                STOCK[pid] = stock
                save_stock(pid)
            send_message(chat_id, f"✅ Produit ajouté : `{pid}` {name} — {fmt(price)} ({sub})", back_kb, parse_mode="Markdown")
        elif text.startswith("-"):
            pid = text[1:].strip()
            if pid not in PRODUCTS:
                send_message(chat_id, "Id inconnu (voir 🏷 Prix).")
                return
            if pid in HIDDEN:
                HIDDEN.discard(pid)
                del_setting(f"hidden:{pid}")
                etat = "de nouveau visible 👁"
            else:
                HIDDEN.add(pid)
                set_setting(f"hidden:{pid}", "1")
                etat = "masqué 🙈"
            send_message(chat_id, f"✅ {PRODUCTS[pid]['name']} : {etat}", back_kb)
        elif text.startswith("="):
            pid, _, name = text[1:].partition("|")
            pid, name = pid.strip(), name.strip()
            if pid not in PRODUCTS or not name:
                send_message(chat_id, "Format : `= id | Nouveau nom`", parse_mode="Markdown")
                return
            PRODUCTS[pid]["name"] = name
            set_setting(f"name:{pid}", name)
            send_message(chat_id, f"✅ Renommé : {name}", back_kb)
        elif text.startswith(">"):
            parts = [x.strip() for x in text[1:].split("|")]
            try:
                pid, cat, sub = parts[0], parts[1], parts[2]
                cat = next(c for c in CATEGORIES if c.lower() == cat.lower())
                sub = next(x for x in SUBCATEGORIES[cat] if x.lower() == sub.lower())
                assert pid in PRODUCTS
            except (IndexError, StopIteration, AssertionError):
                send_message(chat_id, "Format : `> id | Catégorie | Sous-catégorie` (noms existants, voir 🗂 Catégories).", parse_mode="Markdown")
                return
            PRODUCTS[pid]["cat"], PRODUCTS[pid]["sub"] = cat, sub
            set_setting(f"move:{pid}", f"{cat}|{sub}")
            send_message(chat_id, f"✅ {PRODUCTS[pid]['name']} déplacé vers {cat} › {sub}", back_kb)
        elif text.lower().startswith("x "):
            pid = text[2:].strip()
            items = json.loads(get_setting("custom_products", "[]"))
            if pid not in PRODUCTS or not any(i["id"] == pid for i in items):
                send_message(chat_id, "Seuls les produits ajoutés depuis l'admin (ids `c1`, `c2`...) peuvent être supprimés. Pour les autres, masque-les avec `- id`.", parse_mode="Markdown")
                return
            name = PRODUCTS.pop(pid)["name"]
            STOCK.pop(pid, None)
            HIDDEN.discard(pid)
            set_setting("custom_products", json.dumps([i for i in items if i["id"] != pid], ensure_ascii=False))
            for k in ("price", "name", "hidden", "stock", "info", "move"):
                del_setting(f"{k}:{pid}")
            send_message(chat_id, f"🗑 Produit supprimé : {name}", back_kb)
        else:
            send_message(chat_id, "Commence par `+` (ajouter), `-` (masquer), `=` (renommer), `>` (déplacer) ou `x` (supprimer). /annuler pour quitter.", parse_mode="Markdown")

    elif mode == "catalog":
        def bad(name):
            return not name or len(name) > 24 or ":" in name or "|" in name

        def save_extra(cat, sub_list):
            extra = json.loads(get_setting("catalog_extra", "{}"))
            cur = extra.setdefault(cat, [])
            for x in sub_list:
                if x not in cur:
                    cur.append(x)
            set_setting("catalog_extra", json.dumps(extra, ensure_ascii=False))

        low = text.lower()
        if low.startswith("+cat"):
            name, _, rest = text[4:].partition("|")
            name = name.strip()
            subs = [x.strip() for x in rest.split(",") if x.strip()]
            if bad(name) or not subs or any(bad(x) for x in subs) or name in CATEGORIES:
                send_message(chat_id, "Format : `+cat Nom | Sous1, Sous2` (au moins 1 sous-catégorie, 24 caractères max, sans `:` ni `|`, nom pas déjà pris).", parse_mode="Markdown")
                return
            CATEGORIES.append(name)
            SUBCATEGORIES[name] = subs
            save_extra(name, subs)
            rebuild_banner_keys()
            send_message(chat_id, f"✅ Catégorie « {name} » créée ({', '.join(subs)}). Ajoute-y des produits dans 🧩 Produits.", back_kb)
        elif low.startswith("+sub"):
            cat, _, sub = text[4:].partition("|")
            cat, sub = cat.strip(), sub.strip()
            cat = next((c for c in CATEGORIES if c.lower() == cat.lower()), None)
            if not cat or bad(sub) or sub in SUBCATEGORIES.get(cat, []):
                send_message(chat_id, "Format : `+sub Catégorie | Nom` (catégorie existante, sous-catégorie pas déjà prise).", parse_mode="Markdown")
                return
            SUBCATEGORIES[cat].append(sub)
            save_extra(cat, [sub])
            rebuild_banner_keys()
            send_message(chat_id, f"✅ Sous-catégorie « {sub} » ajoutée à {cat}.", back_kb)
        elif low.startswith("~cat") or low.startswith("~sub"):
            if low.startswith("~cat"):
                key = next((c for c in CATEGORIES if c.lower() == text[4:].strip().lower()), None)
            else:
                cat, _, sub = text[4:].partition("|")
                cat = next((c for c in CATEGORIES if c.lower() == cat.strip().lower()), None)
                sub = next((x for x in SUBCATEGORIES.get(cat, []) if x.lower() == sub.strip().lower()), None) if cat else None
                key = f"{cat}|{sub}" if cat and sub else None
            if not key:
                send_message(chat_id, "Introuvable. Format : `~cat Nom` ou `~sub Catégorie | Nom`.", parse_mode="Markdown")
                return
            if key in CAT_HIDDEN:
                CAT_HIDDEN.discard(key)
                etat = "de nouveau visible 👁"
            else:
                CAT_HIDDEN.add(key)
                etat = "masquée 🙈"
            set_setting("catalog_hidden", json.dumps(sorted(CAT_HIDDEN), ensure_ascii=False))
            send_message(chat_id, f"✅ {key.replace('|', ' › ')} : {etat}", back_kb)
        else:
            send_message(chat_id, "Commence par `+cat`, `+sub` ou `~cat` / `~sub`. /annuler pour quitter.", parse_mode="Markdown")

    elif mode and mode.startswith("catban:"):
        photos = msg.get("photo")
        if not photos:
            send_message(chat_id, "Envoie une *photo* (pas un fichier), ou /annuler.", parse_mode="Markdown")
            return
        key = BANNER_KEYS[int(mode.split(":", 1)[1])]
        set_setting(f"banner:{key}", photos[-1]["file_id"])
        BANNERS[key] = photos[-1]["file_id"]
        ADMIN_STATE.pop(chat_id, None)
        send_message(chat_id, f"✅ Bannière « {key.replace('|', ' › ')} » enregistrée.", [[{"text": "🗂 Bannières", "callback_data": "adm:catban"}], ADMIN_BACK])


def clear_user_states(chat_id):
    PROOF_STATE.pop(chat_id, None)
    PROMO_STATE.discard(chat_id)
    SEARCH_STATE.discard(chat_id)
    TOPUP_STATE.discard(chat_id)
    REVIEW_STATE.pop(chat_id, None)


def forward_proof(chat_id, msg, order_id=None):
    """Le client envoie une capture / un hash : on le transmet au vendeur avec les boutons de validation.
    Si order_id est donné (bouton « J'ai payé »), la preuve est rattachée à cette commande."""
    if not ADMIN_CHAT_ID:
        return
    user = msg.get("from", {})
    username = f"@{user['username']}" if user.get("username") else user.get("first_name", "client")
    conn = db_connect()
    pend = None
    if order_id:
        pend = conn.execute(
            "SELECT * FROM orders WHERE id = ? AND telegram_id = ? AND status = 'pending_payment'",
            (order_id, chat_id),
        ).fetchone()
    if not pend:
        pend = conn.execute(
            "SELECT * FROM orders WHERE telegram_id = ? AND status = 'pending_payment' ORDER BY id DESC LIMIT 1",
            (chat_id,),
        ).fetchone()
    if pend:
        conn.execute("UPDATE orders SET proof_sent = TRUE WHERE id = ?", (pend["id"],))
        conn.commit()
    conn.close()
    tg_call("copyMessage", {"chat_id": ADMIN_CHAT_ID, "from_chat_id": chat_id, "message_id": msg["message_id"]})
    if pend:
        header = (
            f"🧾 *Preuve de paiement*\n👤 `{username}` · id `{chat_id}`\n"
            f"📦 Commande *#{pend['id']:05d}* · {fmt(pend['total'])}"
        )
        if pend["received"]:
            header += f"\n💵 Déjà reçu : {fmt(pend['received'])} · reste {fmt(round(pend['total'] - pend['received'], 2))}"
        kb = admin_order_keyboard(pend["id"])
    else:
        header = (
            f"💰 *Message d'un client (recharge ?)*\n👤 `{username}` · id `{chat_id}`\n"
            f"_Crédite son solde avec_ `/credit {chat_id} montant`"
        )
        kb = None
    send_message(ADMIN_CHAT_ID, header, kb, parse_mode="Markdown")
    proof_kb = [[{"text": "🔎 Suivre ma commande", "callback_data": f"order:{pend['id']}"}]] if pend else None
    send_message(chat_id, "✅ *Preuve transmise !* Un vendeur vérifie ton paiement et te tient au courant ici.", proof_kb, parse_mode="Markdown")


def handle_user_input(chat_id, msg):
    """Message libre d'un client : commentaire d'avis, code promo, recherche ou preuve de paiement.
    Renvoie True si le message a été pris en charge."""
    text = (msg.get("text") or "").strip()
    is_media = bool(msg.get("photo") or msg.get("document"))
    user = msg.get("from", {})

    if text and chat_id in REVIEW_STATE:
        order_id = REVIEW_STATE.pop(chat_id)
        set_review_comment(order_id, text)
        send_message(chat_id, "✅ Commentaire enregistré, merci ! 🖤", [[{"text": "🏠 Boutique", "callback_data": "menu"}]])
        if ADMIN_CHAT_ID:
            send_message(ADMIN_CHAT_ID, f"💬 Commentaire d'avis (commande #{order_id:05d}) :\n{text[:500]}")
        return True

    if text and chat_id in PROMO_STATE:
        PROMO_STATE.discard(chat_id)
        row, err = check_promo(text, chat_id)
        if err:
            send_message(chat_id, f"❌ {err}", [[{"text": "🏷 Réessayer", "callback_data": "promo"},
                                                 {"text": "🛒 Panier", "callback_data": "cart"}]])
        else:
            CART_PROMO[chat_id] = row["code"]
            cart_text, kb = cart_view(chat_id)
            send_message(chat_id, f"✅ *Code {row['code']} appliqué !*\n\n" + cart_text, kb, parse_mode="Markdown")
        return True

    if text and chat_id in SEARCH_STATE:
        res, kb = search_view(text)
        send_message(chat_id, res, kb, parse_mode="Markdown")
        return True

    if chat_id in PROOF_STATE and (text or is_media):
        forward_proof(chat_id, msg, PROOF_STATE.pop(chat_id))
        return True

    if is_admin_chat(chat_id):
        return False

    if is_media:
        forward_proof(chat_id, msg)
        return True

    if text:
        conn = db_connect()
        pend = conn.execute(
            "SELECT id FROM orders WHERE telegram_id = ? AND status = 'pending_payment' LIMIT 1", (chat_id,)
        ).fetchone()
        conn.close()
        looks_like_hash = " " not in text and len(text) >= 20
        if looks_like_hash and (pend or chat_id in TOPUP_STATE):
            forward_proof(chat_id, msg)
            return True
        if len(text) <= 40:  # texte libre = recherche
            res, kb = search_view(text)
            send_message(chat_id, res, kb, parse_mode="Markdown")
            return True
    return False


def run_broadcast(admin_id, message_id):
    conn = db_connect()
    ids = [r["telegram_id"] for r in conn.execute("SELECT telegram_id FROM users").fetchall()]
    conn.close()
    ok = fail = 0
    for uid in ids:
        r = _post("copyMessage", {"chat_id": uid, "from_chat_id": admin_id, "message_id": message_id})
        if r.get("ok"):
            ok += 1
        else:
            fail += 1
        time.sleep(0.05)
    send_message(
        admin_id,
        f"📣 *Diffusion terminée*\n\n✅ Envoyés : *{ok}*\n⚠️ Échecs : *{fail}* _(clients ayant bloqué le bot)_",
        [ADMIN_BACK], parse_mode="Markdown",
    )


def handle_admin_status(cq, chat_id, message_id, data):
    if not is_admin_chat(chat_id):
        answer_callback(cq["id"], "Accès refusé.", alert=True)
        return
    parts = data.split(":", 2)
    try:
        order_id = int(parts[1])
    except (ValueError, IndexError):
        answer_callback(cq["id"], "Commande invalide.", alert=True)
        return
    new_status = parts[2] if len(parts) > 2 else ""
    order = get_order_by_id(order_id)
    if not order or new_status not in ORDER_STATUSES:
        answer_callback(cq["id"], "Commande ou statut invalide.", alert=True)
        return
    if order["status"] == new_status:
        answer_callback(cq["id"], "Ce statut est déjà appliqué.")
        return
    if order["status"] == "cancelled":
        answer_callback(cq["id"], "Commande annulée : elle n'est plus modifiable.", alert=True)
        return
    if not update_order_status(order_id, new_status):
        answer_callback(cq["id"], "Impossible de mettre à jour la commande.", alert=True)
        return
    answer_callback(cq["id"], "Statut mis à jour.")
    if new_status == "paid" and order["status"] == "pending_payment":
        conn = db_connect()
        conn.execute("UPDATE orders SET received = total WHERE id = ? AND received = 0", (order_id,))
        conn.commit()
        conn.close()
    if new_status == "cancelled":
        cancel_side_effects(order)
    edit_message(chat_id, message_id, admin_order_text(order_id), admin_order_keyboard(order_id), parse_mode="Markdown")

    # Le client reçoit immédiatement le nouveau statut.
    rows = [[{"text": "🔎 Suivre ma commande", "callback_data": f"order:{order_id}"}]]
    if new_status == "completed":
        rows.append([{"text": "⭐ Laisser un avis", "callback_data": f"rate:{order_id}"}])
        if VOUCH_URL.startswith("https://"):
            rows.append([{"text": "🧾 Voir les preuves (Vouch)", "url": VOUCH_URL}])
        reward_referrer(get_order_by_id(order_id))
    send_message(
        order["telegram_id"],
        f"🔔 *Commande #{order_id:05d}*\n\n{STATUS_MESSAGES.get(new_status, ORDER_STATUSES[new_status])}",
        rows,
        parse_mode="Markdown",
    )


def mark_paid(order_id):
    """pending_payment -> paid (une seule fois) puis prévient le client. Renvoie True si la commande vient d'être validée."""
    conn = db_connect()
    cur = conn.execute(
        "UPDATE orders SET status = 'paid', paid_at = ? WHERE id = ? AND status = 'pending_payment'",
        (datetime.now(timezone.utc).isoformat(), order_id),
    )
    conn.commit()
    conn.close()
    if not cur.rowcount:
        return False
    order = get_order_by_id(order_id)
    send_message(
        order["telegram_id"],
        f"🔔 *Commande #{order_id:05d}*\n\n{STATUS_MESSAGES['paid']}",
        [[{"text": "🔎 Suivre ma commande", "callback_data": f"order:{order_id}"}]],
        parse_mode="Markdown",
    )
    return True


def process_received(admin_id, order_id, amount):
    """L'admin indique le montant reçu : exact -> validé ; trop -> validé + option de créditer ; pas assez -> complément."""
    conn = db_connect()
    cur = conn.execute(
        "UPDATE orders SET received = ROUND((received + ?)::numeric, 2), proof_sent = TRUE "
        "WHERE id = ? AND status = 'pending_payment' RETURNING received, total",
        (amount, order_id),
    )
    row = cur.fetchone()
    conn.commit()
    conn.close()
    if not row:
        send_message(admin_id, "❌ Commande introuvable, déjà validée ou annulée.", [ADMIN_BACK])
        return
    got, total = round(row["received"], 2), round(row["total"], 2)
    diff = round(got - total, 2)
    oid = f"{order_id:05d}"
    if diff < 0:
        send_message(
            admin_id,
            f"⚠️ *Paiement incomplet — commande #{oid}*\n\n"
            f"Reçu : *{fmt(got)}* sur *{fmt(total)}*\n"
            f"Il manque : *{fmt(-diff)}*\n\n"
            "La commande reste en attente de paiement.",
            [[{"text": f"📩 Demander le complément ({fmt(-diff)})", "callback_data": f"admincompl:{order_id}"}],
             [{"text": "✅ Accepter quand même", "callback_data": f"adminaccept:{order_id}"}],
             [{"text": "❌ Refuser", "callback_data": f"adminstatus:{order_id}:cancelled"}]],
            parse_mode="Markdown",
        )
        return
    mark_paid(order_id)
    rows = admin_order_keyboard(order_id)
    if diff == 0:
        head = f"✅ *Montant exact ({fmt(got)})* — paiement confirmé, le client est prévenu."
    else:
        head = f"✅ *Paiement confirmé* — mais *{fmt(diff)} de trop* reçus."
        rows = [[{"text": f"➕ Créditer {fmt(diff)} en solde", "callback_data": f"adminsurplus:{order_id}"},
                 {"text": "✖️ Ignorer", "callback_data": f"adminsurplus:{order_id}:no"}]] + rows
    send_message(admin_id, head + "\n\n" + admin_order_text(order_id), rows, parse_mode="Markdown")


def handle_admin_payfix(cq, chat_id, message_id, data):
    """Boutons admin liés aux écarts de paiement : saisie du montant, surplus, complément, acceptation."""
    if not is_admin_chat(chat_id):
        answer_callback(cq["id"], "Accès refusé.", alert=True)
        return
    parts = data.split(":")
    kind = parts[0]
    try:
        order_id = int(parts[1])
    except (ValueError, IndexError):
        answer_callback(cq["id"], "Commande invalide.", alert=True)
        return
    order = get_order_by_id(order_id)
    if not order:
        answer_callback(cq["id"], "Commande introuvable.", alert=True)
        return
    oid = f"{order_id:05d}"

    if kind == "adminrecv":
        if order["status"] != "pending_payment":
            answer_callback(cq["id"], "Cette commande n'attend plus de paiement.", alert=True)
            return
        answer_callback(cq["id"])
        ADMIN_STATE[chat_id] = f"recv:{order_id}"
        deja = f"\nDéjà reçu : *{fmt(order['received'])}*" if order["received"] else ""
        send_message(
            chat_id,
            f"💵 *Montant reçu — commande #{oid}*\n\n"
            f"Total attendu : *{fmt(order['total'])}*{deja}\n\n"
            "Envoie le montant reçu pour ce paiement, en € (ex. `12.5`).\n/annuler pour abandonner.",
            parse_mode="Markdown",
        )
        return

    if kind == "adminsurplus":
        if len(parts) > 2 and parts[2] == "no":
            answer_callback(cq["id"], "OK, rien n'est crédité.")
            edit_message(chat_id, message_id, admin_order_text(order_id), admin_order_keyboard(order_id), parse_mode="Markdown")
            return
        conn = db_connect()
        row = conn.execute("SELECT received, total, credited FROM orders WHERE id = ? FOR UPDATE", (order_id,)).fetchone()
        due = round(row["received"] - row["total"] - row["credited"], 2)
        if due <= 0:
            conn.close()
            answer_callback(cq["id"], "Déjà crédité, ou aucun surplus.", alert=True)
            return
        conn.execute("UPDATE orders SET credited = credited + ? WHERE id = ?", (due, order_id))
        conn.commit()
        conn.close()
        new_bal = add_balance(order["telegram_id"], due)
        answer_callback(cq["id"], f"✅ +{fmt(due)} crédités")
        send_message(
            order["telegram_id"],
            f"💰 *Solde crédité : +{fmt(due)}*\n\nSurplus de ta commande #{oid}.\nNouveau solde : *{fmt(new_bal)}*",
            parse_mode="Markdown",
        )
        edit_message(
            chat_id, message_id,
            f"✅ *+{fmt(due)} crédités* au solde du client.\n\n" + admin_order_text(order_id),
            admin_order_keyboard(order_id), parse_mode="Markdown",
        )
        return

    if kind == "admincompl":
        missing = round(order["total"] - order["received"], 2)
        if order["status"] != "pending_payment" or missing <= 0:
            answer_callback(cq["id"], "Aucun complément à demander.", alert=True)
            return
        answer_callback(cq["id"], "Demande envoyée au client.")
        send_message(
            order["telegram_id"],
            f"💳 *Complément à régler — commande #{oid}*\n\n"
            f"Nous avons reçu *{fmt(order['received'])}* (total attendu : *{fmt(order['total'])}*).\n"
            f"Reste à envoyer : *{fmt(missing)}* aux mêmes adresses :\n\n"
            f"{PAYMENT_INFO}{crypto_quote(missing)}\n\n"
            "Ensuite, appuie sur *J'ai payé* et envoie la preuve du complément.",
            [[{"text": "✅ J'ai payé", "callback_data": f"ipaid:{order_id}"}],
             [{"text": "🔎 Suivre ma commande", "callback_data": f"order:{order_id}"}]],
            parse_mode="Markdown",
        )
        edit_message(
            chat_id, message_id,
            f"📩 *Complément demandé* — {fmt(missing)} restant sur la commande #{oid}.\n\n" + admin_order_text(order_id),
            admin_order_keyboard(order_id), parse_mode="Markdown",
        )
        return

    if kind == "adminaccept":
        missing = round(order["total"] - order["received"], 2)
        if not mark_paid(order_id):
            answer_callback(cq["id"], "Commande déjà validée ou annulée.", alert=True)
            return
        answer_callback(cq["id"], "Paiement accepté.")
        edit_message(
            chat_id, message_id,
            f"✅ *Paiement accepté* malgré {fmt(max(missing, 0))} manquant.\n\n" + admin_order_text(order_id),
            admin_order_keyboard(order_id), parse_mode="Markdown",
        )


def handle_admin_deliver(cq, chat_id, data):
    """L'admin appuie sur « Livrer » : le bot attend les accès à envoyer au client."""
    if not is_admin_chat(chat_id):
        answer_callback(cq["id"], "Accès refusé.", alert=True)
        return
    try:
        order_id = int(data.split(":", 1)[1])
    except (ValueError, IndexError):
        answer_callback(cq["id"], "Commande invalide.", alert=True)
        return
    order = get_order_by_id(order_id)
    if not order:
        answer_callback(cq["id"], "Commande introuvable.", alert=True)
        return
    if order["status"] in ("cancelled", "completed"):
        answer_callback(cq["id"], "Commande déjà terminée ou annulée.", alert=True)
        return
    if order["status"] == "pending_payment":
        answer_callback(cq["id"], "Confirme d'abord le paiement.", alert=True)
        return
    answer_callback(cq["id"])
    ADMIN_STATE[chat_id] = f"deliver:{order_id}"
    send_message(
        chat_id,
        f"📦 *Livraison — commande #{order_id:05d}*\n\n"
        "Envoie ici les accès à donner au client (identifiants, clé, lien...). "
        "Je les lui envoie tels quels"
        + (", suivis du mode d'emploi du produit," if delivery_note(order_id)[1] else "")
        + " puis je passe la commande en *Terminée*.\n\n/annuler pour abandonner.",
        parse_mode="Markdown",
    )


DEFAULT_DELIVERY_NOTE = (
    "ℹ️ *Besoin d'aide ?*\n"
    "Un souci avec tes accès ? Contacte le support avec ton numéro de commande, on s'en occupe vite 🖤"
)


def delivery_note(order_id):
    """Mode d'emploi envoyé après les accès : modèle du produit (défini dans l'admin), sinon message par défaut.
    Renvoie (texte, personnalisé ?)."""
    seen, parts = set(), []
    for item in get_order_items(order_id):
        pid = item["product_id"]
        if pid in seen:
            continue
        seen.add(pid)
        tpl = (get_setting(f"delmsg:{pid}") or "").strip()
        if tpl:
            tpl = tpl.replace("{order_id}", f"{order_id:05d}").replace("{product}", item["product_name"])
            parts.append((item["product_name"], tpl))
    if not parts:
        return DEFAULT_DELIVERY_NOTE, False
    if len(parts) == 1:
        return parts[0][1], True
    return "\n\n".join(f"🛍 {name}\n{tpl}" for name, tpl in parts), True


def deliver_order(order_id, creds):
    """Envoie les accès au client, enregistre la livraison et termine la commande."""
    order = get_order_by_id(order_id)
    conn = db_connect()
    conn.execute(
        "UPDATE orders SET delivery = ?, delivered_at = ? WHERE id = ?",
        (creds, datetime.now(timezone.utc).isoformat(), order_id),
    )
    conn.commit()
    conn.close()
    update_order_status(order_id, "completed")
    cid = order["telegram_id"]
    send_message(cid, f"📦 *Commande #{order_id:05d} livrée !*\nVoici tes accès 👇", parse_mode="Markdown")
    _post("sendMessage", {"chat_id": cid, "text": creds})  # brut : jamais traduit ni reformaté
    try:  # mode d'emploi / garantie du produit (ne doit jamais bloquer la livraison)
        note, custom = delivery_note(order_id)
        if custom:
            _post("sendMessage", {"chat_id": cid, "text": note[:4000]})  # texte de l'admin : envoyé tel quel
        else:
            send_message(cid, note, [[{"text": "💬 Support", "callback_data": "support"}]], parse_mode="Markdown")
    except Exception as e:
        print("delivery_note:", e)
    rows = [[{"text": "🔎 Suivre ma commande", "callback_data": f"order:{order_id}"}],
            [{"text": "⭐ Laisser un avis", "callback_data": f"rate:{order_id}"}]]
    if VOUCH_URL.startswith("https://"):
        rows.append([{"text": "🧾 Voir les preuves (Vouch)", "url": VOUCH_URL}])
    send_message(cid, STATUS_MESSAGES["completed"], rows, parse_mode="Markdown")
    reward_referrer(get_order_by_id(order_id))


LAST_REMINDER = 0.0
DELIVERY_REMINDER_MIN = float(os.environ.get("DELIVERY_REMINDER_MIN", "30"))


def remind_undelivered():
    """Prévient l'admin des commandes payées mais pas livrées après X minutes (1 rappel par commande)."""
    global LAST_REMINDER
    now = time.time()
    if DELIVERY_REMINDER_MIN <= 0 or now - LAST_REMINDER < 300:
        return
    LAST_REMINDER = now
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=DELIVERY_REMINDER_MIN)).isoformat()
        conn = db_connect()
        rows = conn.execute(
            "SELECT id FROM orders WHERE status IN ('paid', 'processing') AND reminded = FALSE "
            "AND COALESCE(paid_at, created_at) < ?", (cutoff,),
        ).fetchall()
        conn.close()
        for r in rows:
            conn = db_connect()
            conn.execute("UPDATE orders SET reminded = TRUE WHERE id = ?", (r["id"],))
            conn.commit()
            conn.close()
            if ADMIN_CHAT_ID:
                send_message(
                    ADMIN_CHAT_ID,
                    f"⏰ *Commande #{r['id']:05d}* payée depuis plus de {DELIVERY_REMINDER_MIN:g} min, pas encore livrée.",
                    [[{"text": "📦 Livrer les accès", "callback_data": f"deliver:{r['id']}"}]],
                    parse_mode="Markdown",
                )
    except Exception as e:
        print("remind_undelivered:", e)


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

    pr = cart_pricing(chat_id)
    total = pr["total"]
    free = total <= 0
    user = cq["from"]
    username = f"@{user['username']}" if user.get("username") else user.get("first_name", "client")

    if use_balance and not free and not spend_balance(chat_id, total):
        answer_callback(cq["id"], "Solde insuffisant.", alert=True)
        return
    answer_callback(cq["id"])

    paid_now = use_balance or free
    order_id = create_order(
        chat_id, username, cart, total, "paid" if paid_now else "pending_payment",
        discount=pr["discount"], promo_code=pr["promo_code"],
        paid_with_balance=(use_balance and not free),
    )
    if pr["promo_code"]:
        use_promo(pr["promo_code"], chat_id)

    # Décrémente le stock des articles limités (comptes/clés).
    for pid, qty in cart.items():
        if pid in STOCK:
            STOCK[pid] = max(0, STOCK[pid] - qty)
            save_stock(pid)

    discount_line = f"🏷 Remise : *-{fmt(pr['discount'])}*\n" if pr["discount"] > 0 else ""
    if paid_now:
        confirm = TEXT_ORDER_PAID.format(
            order_id=f"{order_id:05d}", total=fmt(total), balance=fmt(get_balance(chat_id)),
            discount_line=discount_line,
        )
    else:
        confirm = TEXT_ORDER_CONFIRM.format(
            order_id=f"{order_id:05d}", total=fmt(total), payment_info=PAYMENT_INFO + crypto_quote(total),
            discount_line=discount_line,
        )
    confirm_rows = [[{"text": "📦 Mes commandes", "callback_data": "orders"},
                     {"text": "🏠 Boutique", "callback_data": "menu"}]]
    if not paid_now:
        confirm_rows.insert(0, [{"text": "✅ J'ai payé", "callback_data": f"ipaid:{order_id}"}])
    edit_message(chat_id, message_id, confirm, confirm_rows, parse_mode="Markdown")

    if ADMIN_CHAT_ID:
        detail = "\n".join(
            f"• {PRODUCTS[pid]['name']} x{qty} — {fmt(PRODUCTS[pid]['price'] * qty)}"
            for pid, qty in cart.items()
        )
        if pr["discount"] > 0:
            detail += f"\n🏷 Remise : -{fmt(pr['discount'])}" + (f" ({pr['promo_code']})" if pr["promo_code"] else "")
        etat = "payée avec le solde" if paid_now else "en attente du paiement"
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
    CART_PROMO.pop(chat_id, None)


CRYPTO_IDS = {"ETH": "ethereum", "SOL": "solana", "BTC": "bitcoin", "LTC": "litecoin"}
_PRICE_CACHE = {"t": 0.0, "data": {}}


def crypto_prices():
    if _PRICE_CACHE["data"] and time.time() - _PRICE_CACHE["t"] < 120:
        return _PRICE_CACHE["data"]
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": ",".join(CRYPTO_IDS.values()), "vs_currencies": "eur"},
            timeout=5,
        )
        d = r.json()
        _PRICE_CACHE["data"] = {k: d[v]["eur"] for k, v in CRYPTO_IDS.items()}
        _PRICE_CACHE["t"] = time.time()
    except Exception as e:
        print("crypto_prices:", e)
    return _PRICE_CACHE["data"]


def crypto_quote(total_eur):
    prices = crypto_prices()
    if not prices or total_eur <= 0:
        return ""
    dec = {"ETH": 5, "SOL": 3, "BTC": 6, "LTC": 4}
    lines = [f"{k} ≈ `{total_eur / p:.{dec[k]}f}`" for k, p in prices.items()]
    return "\n\n💱 *Équivalent indicatif*\n" + "\n".join(lines)


# --- Routes Flask ------------------------------------------------------------

# Le webhook répond "ok" à Telegram tout de suite ; le vrai travail se fait en arrière-plan.
# Un même client est toujours traité dans l'ordre (ses clics ne se croisent pas),
# des clients différents sont traités en parallèle.
_EXEC = ThreadPoolExecutor(max_workers=int(os.environ.get("BOT_WORKERS", "12")), thread_name_prefix="upd")
_CHAT_Q: dict = {}
_CHAT_Q_LOCK = threading.Lock()
_SEEN_UPDATES = collections.OrderedDict()
_SEEN_LOCK = threading.Lock()
_LAST_KICK = 0.0


def _update_chat_id(update):
    m = update.get("message")
    if m:
        return (m.get("chat") or {}).get("id")
    cq = update.get("callback_query")
    if cq:
        return ((cq.get("message") or {}).get("chat") or {}).get("id")
    return None


def _run_safe(update):
    try:
        process_update(update)
    except Exception:
        traceback.print_exc()   # une erreur ne bloque jamais le client suivant


def _drain(cid, update):
    try:
        while True:
            _run_safe(update)
            with _CHAT_Q_LOCK:
                q = _CHAT_Q.get(cid)
                if not q:
                    _CHAT_Q.pop(cid, None)
                    return
                update = q.popleft()
    except BaseException:
        with _CHAT_Q_LOCK:
            _CHAT_Q.pop(cid, None)
        raise


def _enqueue(update):
    cid = _update_chat_id(update)
    if cid is None:
        _EXEC.submit(_run_safe, update)
        return
    with _CHAT_Q_LOCK:
        q = _CHAT_Q.get(cid)
        if q is not None:            # ce client est déjà en cours de traitement : à la suite
            if len(q) < 30:          # anti-spam : on ignore l'excédent
                q.append(update)
            return
        _CHAT_Q[cid] = collections.deque()
    _EXEC.submit(_drain, cid, update)


def _maintenance():
    expire_orders()
    remind_undelivered()


def _kick_maintenance():
    """Lance les tâches périodiques (expiration, rappels) en arrière-plan, au plus 1 fois / minute."""
    global _LAST_KICK
    now = time.time()
    if now - _LAST_KICK < 60:
        return
    _LAST_KICK = now
    _EXEC.submit(_maintenance)


@app.route("/")
def health():
    _kick_maintenance()
    return "Bot en ligne."


@app.route(f"/webhook/{BOT_TOKEN}", methods=["POST"])
def webhook():
    update = request.get_json(force=True, silent=True) or {}
    uid = update.get("update_id")
    if uid is not None:
        with _SEEN_LOCK:
            if uid in _SEEN_UPDATES:      # Telegram renvoie parfois deux fois la même mise à jour
                return "ok"
            _SEEN_UPDATES[uid] = 1
            while len(_SEEN_UPDATES) > 500:
                _SEEN_UPDATES.popitem(last=False)
    _enqueue(update)
    _kick_maintenance()
    return "ok"


def process_update(update):
    _CTX.photo_msg = None
    cq_msg = (update.get("callback_query") or {}).get("message") or {}
    if cq_msg.get("photo"):
        _CTX.photo_msg = cq_msg.get("message_id")

    if "message" in update:
        chat_id = update["message"]["chat"]["id"]
        text = update["message"].get("text", "")

        is_admin = is_admin_chat(chat_id)

        # Saisie en cours dans le panneau admin (bannière, texte, emojis, solde...)
        if is_admin and ADMIN_STATE.get(chat_id) and not text.startswith("/"):
            handle_admin_input(chat_id, update["message"])
            return "ok"

        if not text.startswith("/") and handle_user_input(chat_id, update["message"]):
            return "ok"

        if text.startswith("/start"):
            ADMIN_STATE.pop(chat_id, None)
            clear_user_states(chat_id)
            frm = update["message"]["from"]
            payload = text.split(maxsplit=1)[1].strip() if len(text.split()) > 1 else ""
            is_new = not user_exists(frm["id"])
            upsert_user(frm)
            if is_new and payload.startswith("ref_"):
                ref = set_referrer(frm["id"], payload[4:])
                if ref:
                    send_message(
                        ref,
                        f"🎁 *Nouveau filleul !*\n\nQuelqu'un vient de rejoindre grâce à ton lien. "
                        f"Tu recevras {REF_PERCENT:g}% du montant de chacune de ses commandes terminées.",
                        parse_mode="Markdown",
                    )
            send_home(chat_id, frm)

        elif text.startswith("/recherche"):
            arg = text.split(maxsplit=1)[1].strip() if len(text.split()) > 1 else ""
            if arg:
                res, kb = search_view(arg)
                send_message(chat_id, res, kb, parse_mode="Markdown")
            else:
                SEARCH_STATE.add(chat_id)
                send_message(chat_id, "🔍 Écris un mot-clé : produit, plateforme ou catégorie.")

        elif text.startswith("/passer") or (text.startswith("/annuler") and not is_admin):
            clear_user_states(chat_id)
            send_message(chat_id, "👌 C'est noté.", [[{"text": "🏠 Boutique", "callback_data": "menu"}]])

        elif is_admin and text.startswith("/stats"):
            send_message(chat_id, admin_stats_text(), [ADMIN_BACK], parse_mode="Markdown")

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
            if len(parts) != 3 or parts[1] not in PRODUCTS or not parts[2].lstrip("-").isdigit():
                send_message(
                    chat_id,
                    "Usage : `/restock <id> <quantité à ajouter>`\n"
                    "Ex. `/restock a04 10` ajoute 10 au stock de a04.\n"
                    "Tape /stock pour voir les id.",
                    parse_mode="Markdown",
                )
            else:
                pid, delta = parts[1], int(parts[2])
                STOCK.setdefault(pid, 0)
                restock(pid, delta)
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
            clear_user_states(chat_id)
            # On modifie le message sur place (image + texte) ; sinon on le remplace.
            show_home(chat_id, message_id, cq["from"])

        elif data.startswith("cat:"):
            answer_callback(cq["id"])
            cat = data.split(":", 1)[1]
            title = CAT_TEXT.get(cat, f"📂 *{cat}*")
            if cat in SUBCATEGORIES:
                show_screen(chat_id, message_id, title, kb_subcats(cat), BANNERS.get(cat))
            else:
                show_screen(chat_id, message_id, title, kb_products(cat), BANNERS.get(cat))

        elif data.startswith("sub:"):
            answer_callback(cq["id"])
            _, cat, sub = data.split(":", 2)
            show_screen(chat_id, message_id, products_text(cat, sub), kb_products(cat, sub),
                        BANNERS.get(f"{cat}|{sub}") or BANNERS.get(cat))

        elif data == "search":
            answer_callback(cq["id"])
            SEARCH_STATE.add(chat_id)
            edit_message(
                chat_id, message_id,
                "🔍 *Recherche*\n━━━━━━━━━━━━━━━\n\nÉcris un mot-clé : produit, plateforme ou catégorie.\n_Ex. netflix, tiktok, vpn_",
                [[{"text": "🏠 Accueil", "callback_data": "menu"}]], parse_mode="Markdown",
            )

        elif data.startswith("prod:"):
            answer_callback(cq["id"])
            pid = data.split(":", 1)[1]
            if pid in PRODUCTS:
                text, kb = product_view(pid, chat_id)
                edit_message(chat_id, message_id, text, kb, parse_mode="Markdown")

        elif data.startswith("addn:"):
            try:
                _, pid, n = data.split(":", 2)
                n = int(n)
                assert pid in PRODUCTS and 0 < n <= 100
            except (ValueError, AssertionError):
                answer_callback(cq["id"], "Produit invalide.", alert=True)
            else:
                cart = get_cart(chat_id)
                wanted = cart.get(pid, 0) + n
                if not in_stock(pid, wanted):
                    answer_callback(cq["id"], f"Stock insuffisant — il ne reste que {stock_of(pid)}.", alert=True)
                else:
                    cart[pid] = wanted
                    answer_callback(cq["id"], f"✅ Ajouté au panier : {PRODUCTS[pid]['name']} (x{wanted})")
                    text, kb = product_view(pid, chat_id)
                    edit_message(chat_id, message_id, text, kb, parse_mode="Markdown")

        elif data.startswith("alert:"):
            pid = data.split(":", 1)[1]
            if pid in PRODUCTS:
                add_alert(pid, chat_id)
                answer_callback(cq["id"], "🔔 Compris ! Tu seras prévenu dès qu'il est de retour.", alert=True)
            else:
                answer_callback(cq["id"])

        elif data == "promo":
            answer_callback(cq["id"])
            PROMO_STATE.add(chat_id)
            edit_message(
                chat_id, message_id, "🏷 *Code promo*\n━━━━━━━━━━━━━━━\n\nÉcris ton code ici.",
                [[{"text": "⬅️ Panier", "callback_data": "cart"}]], parse_mode="Markdown",
            )

        elif data == "promo_del":
            answer_callback(cq["id"])
            CART_PROMO.pop(chat_id, None)
            text, kb = cart_view(chat_id)
            edit_message(chat_id, message_id, text, kb, parse_mode="Markdown")

        elif data == "ref":
            answer_callback(cq["id"])
            text, kb = referral_view(chat_id)
            edit_message(chat_id, message_id, text, kb, parse_mode="Markdown")

        elif data == "topup":
            answer_callback(cq["id"])
            TOPUP_STATE.add(chat_id)
            edit_message(
                chat_id, message_id,
                "💳 *Recharger mon solde*\n━━━━━━━━━━━━━━━\n\n"
                "Envoie le montant de ton choix à l'une de ces adresses :\n\n"
                f"{PAYMENT_INFO}\n\n"
                "📸 Envoie une capture de ton paiement (ou le hash) avec le montant. "
                "Un vendeur crédite ton solde après vérification.",
                [[{"text": "⬅️ Profil", "callback_data": "profile"}]], parse_mode="Markdown",
            )

        elif data == "lang":
            answer_callback(cq["id"])
            text, kb = language_view()
            edit_message(chat_id, message_id, text, kb, parse_mode="Markdown")

        elif data.startswith("lang:"):
            lang = data.split(":", 1)[1]
            if lang in ("fr", "en"):
                upsert_user(cq["from"])
                set_lang(chat_id, lang)
            answer_callback(cq["id"], "✅ OK")
            tg_call("deleteMessage", {"chat_id": chat_id, "message_id": message_id})
            send_home(chat_id, cq["from"])

        elif data.startswith("rate:"):
            try:
                order_id = int(data.split(":", 1)[1])
            except ValueError:
                order_id = 0
            order = get_order(order_id, chat_id) if order_id else None
            if not order or order["status"] != "completed":
                answer_callback(cq["id"], "Avis impossible pour cette commande.", alert=True)
            elif has_review(order_id):
                answer_callback(cq["id"], "Tu as déjà laissé un avis. Merci !", alert=True)
            else:
                answer_callback(cq["id"])
                edit_message(
                    chat_id, message_id,
                    f"⭐ *Ton avis compte !*\n━━━━━━━━━━━━━━━\n\nNote ta commande *#{order_id:05d}* :",
                    [[{"text": f"{n}⭐", "callback_data": f"star:{order_id}:{n}"} for n in range(1, 6)]],
                    parse_mode="Markdown",
                )

        elif data.startswith("star:"):
            try:
                _, oid, n = data.split(":", 2)
                order_id, n = int(oid), max(1, min(5, int(n)))
            except ValueError:
                order_id, n = 0, 0
            order = get_order(order_id, chat_id) if order_id else None
            if not order or order["status"] != "completed":
                answer_callback(cq["id"], "Avis impossible pour cette commande.", alert=True)
            elif not save_review(order_id, chat_id, order["username"], n):
                answer_callback(cq["id"], "Tu as déjà laissé un avis. Merci !", alert=True)
            else:
                answer_callback(cq["id"])
                REVIEW_STATE[chat_id] = order_id
                rows = []
                if VOUCH_URL.startswith("https://"):
                    rows.append([{"text": "🧾 Poster sur Vouch", "url": VOUCH_URL}])
                rows.append([{"text": "🏠 Boutique", "callback_data": "menu"}])
                edit_message(
                    chat_id, message_id,
                    f"🙏 *Merci pour ton avis !* {stars(n)}\n\n"
                    "Tu peux ajouter un commentaire en l'écrivant ici (ou /passer).",
                    rows, parse_mode="Markdown",
                )
                if ADMIN_CHAT_ID:
                    send_message(ADMIN_CHAT_ID, f"⭐ Nouvel avis {stars(n)} — commande #{order_id:05d} — {order['username'] or chat_id}")

        elif data.startswith("reorder:"):
            try:
                order_id = int(data.split(":", 1)[1])
            except ValueError:
                order_id = 0
            order = get_order(order_id, chat_id) if order_id else None
            if not order:
                answer_callback(cq["id"], "Commande introuvable.", alert=True)
            else:
                cart, skipped = get_cart(chat_id), []
                for item in get_order_items(order_id):
                    pid = item["product_id"]
                    if pid not in PRODUCTS or pid in HIDDEN or not in_stock(pid, cart.get(pid, 0) + item["quantity"]):
                        skipped.append(item["product_name"])
                    else:
                        cart[pid] = cart.get(pid, 0) + item["quantity"]
                answer_callback(cq["id"], "🔁 Articles remis dans ton panier")
                text, kb = cart_view(chat_id)
                if skipped:
                    text += "\n\n⚠️ Indisponible : " + ", ".join(skipped)
                edit_message(chat_id, message_id, text, kb, parse_mode="Markdown")

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
            handle_admin_status(cq, chat_id, message_id, data)

        elif data.startswith(("adminrecv:", "adminsurplus:", "admincompl:", "adminaccept:")):
            handle_admin_payfix(cq, chat_id, message_id, data)

        elif data.startswith("ipaid:"):
            try:
                order_id = int(data.split(":", 1)[1])
            except ValueError:
                order_id = 0
            order = get_order(order_id, chat_id) if order_id else None
            if not order or order["status"] != "pending_payment":
                answer_callback(cq["id"], "Cette commande n'attend plus de paiement.", alert=True)
            else:
                answer_callback(cq["id"])
                clear_user_states(chat_id)
                PROOF_STATE[chat_id] = order_id
                send_message(
                    chat_id,
                    f"📸 *Preuve de paiement — commande #{order_id:05d}*\n\n"
                    "Envoie ici la *capture* de ton paiement ou le *hash* de la transaction.\n\n"
                    "_/passer pour annuler_",
                    parse_mode="Markdown",
                )

        elif data.startswith("deliver:"):
            handle_admin_deliver(cq, chat_id, data)

        elif data.startswith("track:"):
            try:
                order_id = int(data.split(":", 1)[1])
            except ValueError:
                answer_callback(cq["id"], "Commande invalide.", alert=True)
            else:
                answer_callback(cq["id"])
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
            try:
                order_id = int(data.split(":", 1)[1])
            except ValueError:
                answer_callback(cq["id"], "Commande invalide.", alert=True)
            else:
                answer_callback(cq["id"])
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
            clear_user_states(chat_id)
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

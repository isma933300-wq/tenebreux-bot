
from flask import Flask, request
import os
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

app = Flask(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "0"))

DB_PATH = "tenhebreux.db"

CATEGORIES = {
    "🔥 Réseaux sociaux": [
        "Telegram Members",
        "Telegram Views",
        "Telegram Reactions",
        "TikTok Followers",
        "TikTok Views",
        "TikTok Likes",
        "TikTok Favorites",
        "TikTok Shares",
        "TikTok Custom Comments",
    ],
    "📺 Abonnements": [
        "Mullvad VPN",
        "Gmail Accès FA",
        "Outlook Mail",
        "Netflix",
        "Spotify",
        "YouTube Premium",
        "Disney+",
        "Prime Video",
        "Crunchyroll",
        "Paramount+",
        "Deezer",
        "Canva Pro",
        "CapCut Pro",
        "Duolingo",
        "NordVPN",
        "Surfshark",
        "ChatGPT Plus",
        "Claude Pro",
        "Gemini Pro+",
    ],
    "🎮 Jeux": [
        "FC 27 Édition standard",
        "FC 27 Ultimate",
        "FC 27 Ultimate +",
        "NBA 2K27 Standard",
        "NBA 2K27 Ultimate",
    ],
}

PRICES = {
    "Telegram Members": 3.00,
    "Telegram Views": 0.50,
    "Telegram Reactions": 0.75,
    "TikTok Followers": 5.00,
    "TikTok Views": 0.50,
    "TikTok Likes": 2.00,
    "TikTok Favorites": 0.50,
    "TikTok Shares": 0.50,
    "TikTok Custom Comments": 15.00,
    "Mullvad VPN": 5.00,
    "Gmail Accès FA": 0.50,
    "Outlook Mail": 0.10,
    "Netflix": 0.90,
    "Spotify": 10.00,
    "YouTube Premium": 3.10,
    "Disney+": 1.50,
    "Prime Video": 2.00,
    "Crunchyroll": 0.20,
    "Paramount+": 0.36,
    "Deezer": 0.42,
    "Canva Pro": 4.70,
    "CapCut Pro": 1.10,
    "Duolingo": 0.30,
    "NordVPN": 1.24,
    "Surfshark": 3.20,
    "ChatGPT Plus": 9.00,
    "Claude Pro": 10.00,
    "Gemini Pro+": 5.60,
    "FC 27 Édition standard": 0.00,
    "FC 27 Ultimate": 0.00,
    "FC 27 Ultimate +": 0.00,
    "NBA 2K27 Standard": 0.00,
    "NBA 2K27 Ultimate": 0.00,
}

STOCK = {
    product: 0
    for category in CATEGORIES.values()
    for product in category
}

user_carts = {}


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            total REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            price REAL NOT NULL
        )
    """)

    conn.commit()
    conn.close()


init_db()


def format_status(status):
    statuses = {
        "pending": "🟡 En attente de paiement",
        "paid": "💳 Paiement reçu",
        "processing": "⚙️ En traitement",
        "completed": "✅ Terminée",
        "cancelled": "❌ Annulée",
    }
    return statuses.get(status, status)


def get_cart(user_id):
    return user_carts.setdefault(user_id, {})


def cart_count(user_id):
    return sum(get_cart(user_id).values())


def cart_total(user_id):
    cart = get_cart(user_id)
    return sum(PRICES.get(product, 0) * quantity for product, quantity in cart.items())


def create_order(user_id, username):
    cart = get_cart(user_id)

    if not cart:
        return None

    total = cart_total(user_id)

    conn = get_db()
    cursor = conn.execute(
        """
        INSERT INTO orders
        (user_id, username, total, status, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            user_id,
            username or "",
            total,
            "pending",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )

    order_id = cursor.lastrowid

    for product, quantity in cart.items():
        conn.execute(
            """
            INSERT INTO order_items
            (order_id, product, quantity, price)
            VALUES (?, ?, ?, ?)
            """,
            (
                order_id,
                product,
                quantity,
                PRICES.get(product, 0),
            ),
        )

    conn.commit()
    conn.close()

    user_carts[user_id] = {}

    return order_id


def get_order(order_id, user_id=None):
    conn = get_db()

    if user_id is None:
        order = conn.execute(
            "SELECT * FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
    else:
        order = conn.execute(
            "SELECT * FROM orders WHERE id = ? AND user_id = ?",
            (order_id, user_id),
        ).fetchone()

    conn.close()
    return order


def get_order_items(order_id):
    conn = get_db()
    items = conn.execute(
        """
        SELECT product, quantity, price
        FROM order_items
        WHERE order_id = ?
        """,
        (order_id,),
    ).fetchall()
    conn.close()
    return items


def main_menu(user_id):
    count = cart_count(user_id)

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🛍️ Boutique", callback_data="shop"),
            InlineKeyboardButton(f"🛒 Panier ({count})", callback_data="cart"),
        ],
        [
            InlineKeyboardButton("📦 Mes commandes", callback_data="orders"),
            InlineKeyboardButton("👤 Mon profil", callback_data="profile"),
        ],
        [
            InlineKeyboardButton("🔎 Suivre une commande", callback_data="track"),
        ],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    text = (
        "𖤐 <b>T E N H E B R E U X</b>\n\n"
        "🛍️ bienvenue dans la boutique\n\n"
        "sélectionne une option ci-dessous."
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=main_menu(user_id),
    )


async def show_shop(query, user_id):
    buttons = []

    for category in CATEGORIES:
        buttons.append([
            InlineKeyboardButton(
                category,
                callback_data=f"cat:{category}",
            )
        ])

    buttons.append([
        InlineKeyboardButton("🛒 Panier", callback_data="cart"),
        InlineKeyboardButton("⬅️ Accueil", callback_data="home"),
    ])

    await query.edit_message_text(
        "🛍️ <b>BOUTIQUE</b>\n\nChoisis une catégorie :",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def show_category(query, category):
    products = CATEGORIES.get(category, [])

    buttons = []

    for product in products:
        price = PRICES.get(product, 0)
        stock = STOCK.get(product, 0)

        buttons.append([
            InlineKeyboardButton(
                f"{product} — {price:.2f}€",
                callback_data=f"product:{product}",
            )
        ])

    buttons.append([
        InlineKeyboardButton("⬅️ Catégories", callback_data="shop")
    ])

    await query.edit_message_text(
        f"<b>{category}</b>\n\nSélectionne un produit :",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def show_product(query, product):
    price = PRICES.get(product, 0)
    stock = STOCK.get(product, 0)

    text = (
        f"🛍️ <b>{product}</b>\n\n"
        f"💶 Prix : <b>{price:.2f}€</b>\n"
        f"📦 Stock : <b>{stock}</b>\n\n"
        "Ajoute le produit à ton panier."
    )

    buttons = [
        [
            InlineKeyboardButton(
                "🛒 Ajouter au panier",
                callback_data=f"add:{product}",
            )
        ],
        [
            InlineKeyboardButton("⬅️ Retour", callback_data="shop")
        ],
    ]

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
async def show_cart(query, user_id):
    cart = get_cart(user_id)

    if not cart:
        buttons = [
            [InlineKeyboardButton("🛍️ Boutique", callback_data="shop")],
            [InlineKeyboardButton("⬅️ Accueil", callback_data="home")],
        ]

        await query.edit_message_text(
            "🛒 <b>MON PANIER</b>\n\nTon panier est vide.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    lines = ["🛒 <b>MON PANIER</b>\n"]

    for product, quantity in cart.items():
        price = PRICES.get(product, 0)
        subtotal = price * quantity

        lines.append(
            f"• {product} × {quantity}\n"
            f"  {subtotal:.2f}€"
        )

    total = cart_total(user_id)

    lines.append(f"\n💰 <b>Total : {total:.2f}€</b>")

    buttons = [
        [
            InlineKeyboardButton(
                "✅ Passer commande",
                callback_data="checkout",
            )
        ],
        [
            InlineKeyboardButton(
                "🗑️ Vider le panier",
                callback_data="clear_cart",
            )
        ],
        [
            InlineKeyboardButton(
                "🛍️ Continuer mes achats",
                callback_data="shop",
            )
        ],
    ]

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def show_orders(query, user_id):
    conn = get_db()

    orders = conn.execute(
        """
        SELECT id, total, status, created_at
        FROM orders
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 20
        """,
        (user_id,),
    ).fetchall()

    conn.close()

    if not orders:
        await query.edit_message_text(
            "📦 <b>MES COMMANDES</b>\n\n"
            "Aucune commande pour le moment.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛍️ Boutique", callback_data="shop")],
                [InlineKeyboardButton("⬅️ Accueil", callback_data="home")],
            ]),
        )
        return

    buttons = []

    for order in orders:
        buttons.append([
            InlineKeyboardButton(
                f"📦 #{order['id']:05d} — {order['total']:.2f}€",
                callback_data=f"order:{order['id']}",
            )
        ])

    buttons.append([
        InlineKeyboardButton("⬅️ Accueil", callback_data="home")
    ])

    await query.edit_message_text(
        "📦 <b>MES COMMANDES</b>\n\n"
        "Sélectionne une commande :",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def show_order(query, order_id, user_id):
    order = get_order(order_id, user_id)

    if not order:
        await query.answer(
            "Commande introuvable.",
            show_alert=True,
        )
        return

    items = get_order_items(order_id)

    lines = [
        f"📦 <b>COMMANDE #{order_id:05d}</b>\n",
        f"{format_status(order['status'])}",
        f"📅 {order['created_at']}\n",
    ]

    for item in items:
        subtotal = item["price"] * item["quantity"]

        lines.append(
            f"\n• {item['product']} × {item['quantity']}"
            f"\n  {subtotal:.2f}€"
        )

    lines.append(
        f"\n💰 <b>Total : {order['total']:.2f}€</b>"
    )

    buttons = [
        [
            InlineKeyboardButton(
                "🔄 Actualiser",
                callback_data=f"order:{order_id}",
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ Mes commandes",
                callback_data="orders",
            )
        ],
    ]

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def show_profile(query, user_id):
    conn = get_db()

    stats = conn.execute(
        """
        SELECT
            COUNT(*) AS total_orders,
            COALESCE(SUM(
                CASE WHEN status = 'completed'
                THEN 1 ELSE 0 END
            ), 0) AS completed_orders,
            COALESCE(SUM(
                CASE WHEN status IN ('pending', 'paid', 'processing')
                THEN 1 ELSE 0 END
            ), 0) AS active_orders,
            COALESCE(SUM(
                CASE WHEN status = 'cancelled'
                THEN 1 ELSE 0 END
            ), 0) AS cancelled_orders,
            COALESCE(SUM(
                CASE WHEN status = 'completed'
                THEN total ELSE 0 END
            ), 0) AS total_spent
        FROM orders
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()

    recent = conn.execute(
        """
        SELECT id, total, status
        FROM orders
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 3
        """,
        (user_id,),
    ).fetchall()

    conn.close()

    lines = [
        "👤 <b>MON PROFIL</b>\n",
        f"📦 Commandes : <b>{stats['total_orders']}</b>",
        f"✅ Terminées : <b>{stats['completed_orders']}</b>",
        f"⚙️ En cours : <b>{stats['active_orders']}</b>",
        f"❌ Annulées : <b>{stats['cancelled_orders']}</b>",
        f"💰 Total dépensé : <b>{stats['total_spent']:.2f}€</b>",
    ]

    if recent:
        lines.append("\n🕘 <b>Dernières commandes</b>")

        for order in recent:
            lines.append(
                f"• #{order['id']:05d} — "
                f"{order['total']:.2f}€ — "
                f"{format_status(order['status'])}"
            )

    buttons = [
        [
            InlineKeyboardButton(
                "📦 Mes commandes",
                callback_data="orders",
            )
        ],
        [
            InlineKeyboardButton(
                "🔄 Actualiser",
                callback_data="profile",
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ Accueil",
                callback_data="home",
            )
        ],
    ]

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def show_track(query):
    await query.edit_message_text(
        "🔎 <b>SUIVI DE COMMANDE</b>\n\n"
        "Envoie-moi le numéro de ta commande.\n\n"
        "Exemple : <code>21</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Accueil", callback_data="home")]
        ]),
    )


async def checkout(query, user_id, username, context):
    cart = get_cart(user_id)

    if not cart:
        await query.answer(
            "Ton panier est vide.",
            show_alert=True,
        )
        return

    order_id = create_order(user_id, username)

    if not order_id:
        await query.answer(
            "Impossible de créer la commande.",
            show_alert=True,
        )
        return

    order = get_order(order_id, user_id)
    items = get_order_items(order_id)

    lines = [
        "🆕 <b>NOUVELLE COMMANDE</b>",
        f"\n📦 Commande : <b>#{order_id:05d}</b>",
        f"👤 Client : @{username or 'inconnu'}",
        f"🆔 ID : <code>{user_id}</code>",
        "",
    ]

    for item in items:
        lines.append(
            f"• {item['product']} × {item['quantity']} "
            f"— {item['price'] * item['quantity']:.2f}€"
        )

    lines.append(
        f"\n💰 <b>Total : {order['total']:.2f}€</b>"
    )

    admin_buttons = [
        [
            InlineKeyboardButton(
                "💳 Payée",
                callback_data=f"status:{order_id}:paid",
            ),
            InlineKeyboardButton(
                "⚙️ Traitement",
                callback_data=f"status:{order_id}:processing",
            ),
        ],
        [
            InlineKeyboardButton(
                "✅ Terminée",
                callback_data=f"status:{order_id}:completed",
            ),
            InlineKeyboardButton(
                "❌ Annulée",
                callback_data=f"status:{order_id}:cancelled",
            ),
        ],
    ]

    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text="\n".join(lines),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(admin_buttons),
        )
    except Exception as e:
        print("Erreur notification admin :", e)

    await query.edit_message_text(
        f"✅ <b>COMMANDE #{order_id:05d} CRÉÉE</b>\n\n"
        "Ta commande a bien été enregistrée.\n\n"
        "🟡 En attente de paiement\n\n"
        "Tu peux suivre son évolution depuis "
        "« Mes commandes ».",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔎 Suivre ma commande",
                    callback_data=f"order:{order_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Accueil",
                    callback_data="home",
                )
            ],
        ]),
    )
async def update_order_status(query, context, order_id, new_status):
    if query.from_user.id != ADMIN_CHAT_ID:
        await query.answer(
            "Accès refusé.",
            show_alert=True,
        )
        return

    order = get_order(order_id)

    if not order:
        await query.answer(
            "Commande introuvable.",
            show_alert=True,
        )
        return

    conn = get_db()

    conn.execute(
        """
        UPDATE orders
        SET status = ?
        WHERE id = ?
        """,
        (new_status, order_id),
    )

    conn.commit()
    conn.close()

    items = get_order_items(order_id)

    lines = [
        "📦 <b>COMMANDE</b>",
        f"\n#{order_id:05d}",
        f"👤 @{order['username'] or 'inconnu'}",
        f"🆔 <code>{order['user_id']}</code>",
        "",
        f"📌 <b>{format_status(new_status)}</b>",
        "",
    ]

    for item in items:
        lines.append(
            f"• {item['product']} × {item['quantity']} "
            f"— {item['price'] * item['quantity']:.2f}€"
        )

    lines.append(
        f"\n💰 <b>Total : {order['total']:.2f}€</b>"
    )

    admin_buttons = [
        [
            InlineKeyboardButton(
                "💳 Payée",
                callback_data=f"status:{order_id}:paid",
            ),
            InlineKeyboardButton(
                "⚙️ Traitement",
                callback_data=f"status:{order_id}:processing",
            ),
        ],
        [
            InlineKeyboardButton(
                "✅ Terminée",
                callback_data=f"status:{order_id}:completed",
            ),
            InlineKeyboardButton(
                "❌ Annulée",
                callback_data=f"status:{order_id}:cancelled",
            ),
        ],
    ]

    try:
        await query.edit_message_text(
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(admin_buttons),
        )
    except Exception as e:
        print("Erreur édition message admin :", e)

    notification_text = (
        f"📦 <b>MISE À JOUR DE TA COMMANDE</b>\n\n"
        f"Commande : <b>#{order_id:05d}</b>\n\n"
        f"📌 Nouveau statut :\n"
        f"<b>{format_status(new_status)}</b>"
    )

    try:
        await context.bot.send_message(
            chat_id=order["user_id"],
            text=notification_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔎 Voir ma commande",
                        callback_data=f"order:{order_id}",
                    )
                ]
            ]),
        )
    except Exception as e:
        print("Impossible de notifier le client :", e)

    await query.answer("Statut mis à jour ✅")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data

    if data == "home":
        await query.edit_message_text(
            "𖤐 <b>T E N H E B R E U X</b>\n\n"
            "🛍️ bienvenue dans la boutique\n\n"
            "sélectionne une option ci-dessous.",
            parse_mode="HTML",
            reply_markup=main_menu(user_id),
        )
        return

    if data == "shop":
        await show_shop(query, user_id)
        return

    if data.startswith("cat:"):
        category = data[4:]
        await show_category(query, category)
        return

    if data.startswith("product:"):
        product = data[8:]
        await show_product(query, product)
        return

    if data.startswith("add:"):
        product = data[4:]

        if product not in PRICES:
            await query.answer(
                "Produit introuvable.",
                show_alert=True,
            )
            return

        cart = get_cart(user_id)
        cart[product] = cart.get(product, 0) + 1

        await query.answer(
            "Produit ajouté au panier 🛒",
            show_alert=False,
        )

        await show_product(query, product)
        return

    if data == "cart":
        await show_cart(query, user_id)
        return

    if data == "clear_cart":
        user_carts[user_id] = {}

        await query.answer(
            "Panier vidé.",
            show_alert=False,
        )

        await show_cart(query, user_id)
        return

    if data == "checkout":
        username = query.from_user.username or ""

        await checkout(
            query,
            user_id,
            username,
            context,
        )
        return

    if data == "orders":
        await show_orders(query, user_id)
        return

    if data.startswith("order:"):
        try:
            order_id = int(data.split(":")[1])
        except ValueError:
            await query.answer(
                "Commande invalide.",
                show_alert=True,
            )
            return

        await show_order(
            query,
            order_id,
            user_id,
        )
        return

    if data == "track":
        await show_track(query)
        return

    if data == "profile":
        await show_profile(query, user_id)
        return

    if data.startswith("status:"):
        parts = data.split(":")

        if len(parts) != 3:
            await query.answer(
                "Action invalide.",
                show_alert=True,
            )
            return

        try:
            order_id = int(parts[1])
        except ValueError:
            await query.answer(
                "Commande invalide.",
                show_alert=True,
            )
            return

        new_status = parts[2]

        if new_status not in {
            "paid",
            "processing",
            "completed",
            "cancelled",
        }:
            await query.answer(
                "Statut invalide.",
                show_alert=True,
            )
            return

        await update_order_status(
            query,
            context,
            order_id,
            new_status,
        )
        return


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    if not text.isdigit():
        return

    order_id = int(text)
    user_id = update.effective_user.id

    order = get_order(
        order_id,
        user_id,
    )

    if not order:
        await update.message.reply_text(
            "❌ Commande introuvable."
        )
        return

    items = get_order_items(order_id)

    lines = [
        f"📦 <b>COMMANDE #{order_id:05d}</b>\n",
        format_status(order["status"]),
        f"📅 {order['created_at']}\n",
    ]

    for item in items:
        lines.append(
            f"• {item['product']} × {item['quantity']} "
            f"— {item['price'] * item['quantity']:.2f}€"
        )

    lines.append(
        f"\n💰 <b>Total : {order['total']:.2f}€</b>"
    )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔄 Actualiser",
                    callback_data=f"order:{order_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Accueil",
                    callback_data="home",
                )
            ],
        ]),
    )


@app.route("/", methods=["GET"])
def index():
    return "TenHebreux Bot OK", 200


@app.route("/webhook", methods=["POST"])
async def webhook():
    if not BOT_TOKEN:
        return "BOT_TOKEN manquant", 500

    application = app.config.get("telegram_application")

    if application is None:
        return "Application Telegram non initialisée", 500

    update = Update.de_json(
        request.get_json(force=True),
        application.bot,
    )

    await application.process_update(update)

    return "OK", 200


async def setup_application():
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler(
            "commandes",
            lambda update, context: show_orders(
                _FakeQuery(update, context),
                update.effective_user.id,
            ),
        )
    )

    application.add_handler(
        CallbackQueryHandler(button_handler)
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler,
        )
    )

    await application.initialize()

    app.config["telegram_application"] = application

    return application


class _FakeQuery:
    def __init__(self, update, context):
        self.update = update
        self.context = context

    async def edit_message_text(self, *args, **kwargs):
        await self.update.message.reply_text(
            *args,
            **kwargs,
        )


telegram_application = None


@app.before_request
async def ensure_application():
    global telegram_application

    if telegram_application is None:
        telegram_application = await setup_application()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port,
    )

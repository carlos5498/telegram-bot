import os
import logging
import threading
import random
import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pymongo import MongoClient
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- CONFIGURACIÓN ---
logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("TOKEN")
MY_ID = int(os.getenv("MY_ID", "0"))
MONGO_URI = os.getenv("MONGO_URI")

client = MongoClient(MONGO_URI)
db = client['bot_anonimo']
users_col = db['usuarios']
files_col = db['archivos_vistos']

ADJETIVOS = ["Bravo", "Veloz", "Oscuro", "Místico", "Feroz", "Silencioso", "Letal"]
ANIMALES = ["Lobo", "Zorro", "Halcón", "Tigre", "Puma", "Serpiente", "Águila"]

# --- SERVIDOR WEB ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Bot Operativo")

def run_web_server():
    server = HTTPServer(('0.0.0.0', int(os.environ.get("PORT", 8080))), SimpleHandler)
    server.serve_forever()

# --- FUNCIONES AUXILIARES ---
def get_user(user_id):
    return users_col.find_one({"user_id": user_id})

def generate_anon_name():
    return f"{random.choice(ANIMALES)} {random.choice(ADJETIVOS)} {random.randint(10, 99)}"

async def check_daily_reset(user_id, user_data):
    today = str(datetime.date.today())
    if user_data.get("last_reset") != today:
        users_col.update_one({"user_id": user_id}, {"$set": {"aportes": 0, "last_reset": today}})
        return 0
    return user_data.get("aportes", 0)

# --- MANEJADORES ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        users_col.insert_one({
            "user_id": user_id,
            "name": generate_anon_name(),
            "status": "pending",
            "aportes": 0,
            "last_reset": str(datetime.date.today())
        })
    
    bienvenida = (
        "¡𝗕𝗶𝗲𝗻𝘃𝗲𝗻𝗶𝗱𝗼! 𝗘𝘀𝘁𝗲 𝗲𝘀 𝘂𝗻 𝗯𝗼𝘁 𝗯𝗲𝘁𝗮 𝗽𝗮𝗿𝗮 𝗲𝗻𝘃𝗶𝗮𝗿 𝗺𝗲𝗻𝘀𝗮𝗷𝗲𝘀 𝗲 𝗶𝗻𝘁𝗲𝗿𝗰𝗮𝗺𝗯𝗶𝗼𝘀 𝗱𝗲 𝗰𝗼𝗻𝘁𝗲𝗻𝗶𝗱𝗼 𝗱𝗲 𝗺𝗮𝗻𝗲𝗿𝗮 𝗮𝗻𝗼́𝗻𝗶𝗺𝗮.\n\n"
        "• 𝗘𝗻𝘃𝗶́𝗮 𝟭𝟬𝟬 𝗺𝘂𝗹𝘁𝗶𝗺𝗲𝗱𝗶𝗮 𝗽𝗮𝗿𝗮 𝘀𝗲𝗿 𝗮𝗰𝗲𝗽𝘁𝗮𝗱𝗼.\n"
        "• 𝗟𝘂𝗲𝗴𝗼 𝘂𝘀𝗮 /solicitar 𝗽𝗮𝗿𝗮 𝗽𝗲𝗱𝗶𝗿 𝗮𝗰𝗰𝗲𝘀𝗼."
    )
    await update.message.reply_text(bienvenida)

async def solicitar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_db = get_user(user_id)
    if not user_db: return
    await update.message.reply_text("¡𝗛𝗮𝘀 𝘀𝗼𝗹𝗶𝗰𝗶𝘁𝗮𝗱𝗼 𝗮𝗰𝗰𝗲𝘀𝗼!")
    await context.bot.send_message(MY_ID, f"📥 𝗡𝗨𝗘𝗩𝗔 𝗦𝗢𝗟𝗜𝗖𝗜𝗧𝗨𝗗\n🆔: `{user_id}`\n🎭: {user_db['name']}\n\n`/usuarioaceptado{user_id}`", parse_mode="Markdown")

async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    user_id = update.effective_user.id
    user = get_user(user_id)

    # ADMIN COMMANDS
    if user_id == MY_ID:
        if update.message.text == "/reset":
            files_col.delete_many({})
            await update.message.reply_text("✅ 𝗕𝗮𝘀𝗲 𝗱𝗲 𝗱𝗮𝘁𝗼𝘀 𝗱𝗲 𝗿𝗲𝗽𝗲𝘁𝗶𝗱𝗼𝘀 𝗹𝗶𝗺𝗽𝗶𝗮.")
            return
        if update.message.text and "/usuarioaceptado" in update.message.text:
            try:
                target_id = int(update.message.text.split("/usuarioaceptado")[-1])
                users_col.update_one({"user_id": target_id}, {"$set": {"status": "accepted", "aportes": 0}})
                await context.bot.send_message(target_id, "¡𝗙𝗲𝗹𝗶𝗰𝗶𝗱𝗮𝗱𝗲𝘀 𝗵𝗮𝘇 𝘀𝗶𝗱𝗼 𝗮𝗰𝗲𝗽𝘁𝗮𝗱𝗼!")
                return
            except: pass

    if not user or user.get("status") == "banned": return

    # PENDIENTES
    if user["status"] == "pending":
        if update.message.photo or update.message.video:
            users_col.update_one({"user_id": user_id}, {"$inc": {"aportes": 1}})
        return

    # ACEPTADOS
    if user["status"] == "accepted":
        await check_daily_reset(user_id, user)
        f_unique = ""
        if update.message.photo: f_unique = update.message.photo[-1].file_unique_id
        elif update.message.video: f_unique = update.message.video.file_unique_id

        if f_unique:
            if files_col.find_one({"file_id": f_unique}):
                if not update.message.media_group_id:
                    await update.message.reply_text("𝘃𝗶𝗱𝗲𝗼 𝗿𝗲𝗽𝗲𝘁𝗶𝗱𝗼")
                return
            files_col.insert_one({"file_id": f_unique, "user": user_id})
            users_col.update_one({"user_id": user_id}, {"$inc": {"aportes": 1}})

        # Lógica de nombre para Álbumes
        # Si el mensaje NO es un álbum, o si es la PRIMERA parte de un álbum, ponemos el nombre.
        # Intentamos detectar si es el inicio del álbum de forma sencilla:
        # Nota: Telegram no dice cuál es el primero, así que usamos un truco de caché temporal.
        caption_to_send = user['name']
        
        # REENVÍO
        for target in users_col.find({"status": "accepted"}):
            if target["user_id"] == user_id: continue
            try:
                if update.message.photo:
                    await context.bot.send_photo(target["user_id"], update.message.photo[-1].file_id, caption=caption_to_send)
                elif update.message.video:
                    await context.bot.send_video(target["user_id"], update.message.video.file_id, caption=caption_to_send)
                elif update.message.text:
                    await context.bot.send_message(target["user_id"], f"{update.message.text}\n\n{user['name']}")
            except: pass

async def commands_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user: return
    text = update.message.text
    if "/user" in text: await update.message.reply_text(f"𝗧𝘂 𝗻𝗼𝗺𝗯𝗿𝗲 𝗮𝗻𝗼́𝗻𝗶𝗺𝗼 𝗲𝘀: {user['name']}")
    elif "/usuarios" in text: await update.message.reply_text(f"𝗨𝘀𝘂𝗮𝗿𝗶𝗼𝘀 𝗮𝗰𝘁𝗶𝘃𝗼𝘀: {users_col.count_documents({'status': 'accepted'})}")
    elif "/aportes" in text:
        ap = await check_daily_reset(user_id, user)
        obj = 100 if user["status"] == "pending" else 10
        await update.message.reply_text(f"𝗧𝘂 𝗽𝗿𝗼𝗴𝗿𝗲𝘀𝗼: {ap}/{obj}")

def main():
    threading.Thread(target=run_web_server, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("solicitar", solicitar))
    app.add_handler(CommandHandler(["user", "usuarios", "aportes"], commands_user))
    app.add_handler(MessageHandler(filters.ALL, handle_broadcast))
    app.run_polling()

if __name__ == '__main__':
    main()

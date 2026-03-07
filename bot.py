import os
import logging
import threading
import random
import datetime
import re
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

def contiene_enlace(texto):
    if not texto: return False
    patron = r"(https?://|t\.me/|www\.)"
    return re.search(patron, texto, re.IGNORECASE)

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
            "user_id": user_id, "name": generate_anon_name(),
            "status": "pending", "aportes": 0, "last_reset": str(datetime.date.today())
        })
    await update.message.reply_text("¡𝗕𝗶𝗲𝗻𝘃𝗲𝗻𝗶𝗱𝗼! Envíe 100 aportes para ser aceptado y luego use /solicitar.")

async def solicitar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_db = get_user(user_id)
    if not user_db: return
    await update.message.reply_text("¡𝗦𝗼𝗹𝗶𝗰𝗶𝘁𝘂𝗱 𝗲𝗻𝘃𝗶𝗮𝗱𝗮!")
    await context.bot.send_message(MY_ID, f"📥 𝗡𝗨𝗘𝗩𝗔 𝗦𝗢𝗟𝗜𝗖𝗜𝗧𝗨𝗗\n🆔: `{user_id}`\n🎭: {user_db['name']}\n\n`/usuarioaceptado{user_id}`", parse_mode="Markdown")

async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    user_id = update.effective_user.id
    user = get_user(user_id)

    # 1. Filtro de Enlaces
    texto_revisar = update.message.text or update.message.caption
    if contiene_enlace(texto_revisar): return

    # 2. Comandos Admin
    if user_id == MY_ID:
        if update.message.text == "/reset":
            files_col.delete_many({})
            await update.message.reply_text("✅ Repetidos reseteados.")
            return
        if update.message.text and "/usuarioaceptado" in update.message.text:
            try:
                target_id = int(update.message.text.split("/usuarioaceptado")[-1])
                users_col.update_one({"user_id": target_id}, {"$set": {"status": "accepted", "aportes": 0}})
                await context.bot.send_message(target_id, "¡𝗙𝗲𝗹𝗶𝗰𝗶𝗱𝗮𝗱𝗲𝘀 𝗵𝗮𝘇 𝘀𝗶𝗱𝗼 𝗮𝗰𝗲𝗽𝘁𝗮𝗱𝗼!")
                return
            except: pass

    if not user or user.get("status") == "banned": return

    # 3. Lógica de Pendientes
    if user["status"] == "pending":
        if update.message.photo or update.message.video:
            users_col.update_one({"user_id": user_id}, {"$inc": {"aportes": 1}})
        return

    # 4. Lógica de Aceptados (REENVÍO ÚNICO)
    if user["status"] == "accepted":
        await check_daily_reset(user_id, user)
        
        # Filtro de Repetidos
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

        # Envío a los demás
        for target in users_col.find({"status": "accepted"}):
            if target["user_id"] == user_id: continue
            try:
                if update.message.photo:
                    await context.bot.send_photo(target["user_id"], update.message.photo[-1].file_id, caption=update.message.caption)
                elif update.message.video:
                    await context.bot.send_video(target["user_id"], update.message.video.file_id, caption=update.message.caption)
                elif update.message.text:
                    await context.bot.send_message(target["user_id"], f"{update.message.text}\n\n{user['name']}")
            except: pass

async def commands_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user: return
    text = update.message.text
    if "/user" in text: await update.message.reply_text(f"🎭: {user['name']}")
    elif "/usuarios" in text: await update.message.reply_text(f"👥: {users_col.count_documents({'status': 'accepted'})}")
    elif "/aportes" in text:
        ap = await check_daily_reset(user_id, user)
        await update.message.reply_text(f"📊 Aportes hoy: {ap}")

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

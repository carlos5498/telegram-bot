import os
import logging
import threading
import random
import datetime
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from pymongo import MongoClient
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# --- CONFIGURACIÓN ---
logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("TOKEN")
MY_ID = int(os.getenv("MY_ID", "0"))
MONGO_URI = os.getenv("MONGO_URI")

client = MongoClient(MONGO_URI)
db = client['bot_anonimo']
users_col = db['usuarios']
files_col = db['archivos_vistos']

# --- SERVIDOR WEB (Keep-Alive para Render) ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Bot OK")

def run_web_server():
    server = HTTPServer(('0.0.0.0', int(os.environ.get("PORT", 8080))), SimpleHandler)
    server.serve_forever()

# --- UTILIDADES ---
def contiene_enlace(texto):
    if not texto: return False
    return bool(re.search(r"(https?://|t\.me/|www\.)", texto, re.IGNORECASE))

# --- PROCESO PRINCIPAL ---
async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    user_id = update.effective_user.id
    user = users_col.find_one({"user_id": user_id})

    # 1. Filtro de Spam/Links
    if contiene_enlace(update.message.text or update.message.caption): return

    # 2. Comandos Admin (Reset y Aceptar)
    if user_id == MY_ID:
        if update.message.text == "/reset":
            files_col.delete_many({})
            return await update.message.reply_text("✅ Base limpia.")
        if update.message.text and "/usuarioaceptado" in update.message.text:
            try:
                t_id = int(update.message.text.split("/usuarioaceptado")[-1])
                users_col.update_one({"user_id": t_id}, {"$set": {"status": "accepted", "aportes": 0}})
                return await context.bot.send_message(t_id, "¡𝗔𝗰𝗲𝗽𝘁𝗮𝗱𝗼!")
            except: pass

    if not user or user.get("status") == "banned": return

    # 3. Usuarios Pendientes
    if user["status"] == "pending":
        if update.message.photo or update.message.video:
            users_col.update_one({"user_id": user_id}, {"$inc": {"aportes": 1}})
        return

    # 4. Usuarios Aceptados (Reenvío Secuencial)
    if user["status"] == "accepted":
        f_unique = ""
        if update.message.photo: f_unique = update.message.photo[-1].file_unique_id
        elif update.message.video: f_unique = update.message.video.file_unique_id

        # Filtro de repetidos
        if f_unique:
            if files_col.find_one({"file_id": f_unique}):
                if not update.message.media_group_id: 
                    await update.message.reply_text("𝘃𝗶𝗱𝗲𝗼 𝗿𝗲𝗽𝗲𝘁𝗶𝗱𝗼")
                return
            files_col.insert_one({"file_id": f_unique, "user": user_id})

        # Reenvío directo (sin agrupar para no saturar la RAM de Render)
        # Nota: Al enviar rápido uno tras otro sin texto intermedio, 
        # la mayoría de apps de Telegram los mostrarán juntos.
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

def main():
    threading.Thread(target=run_web_server, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.ALL, handle_broadcast))
    app.run_polling()

if __name__ == '__main__':
    main()

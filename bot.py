import os
import logging
import threading
import random
import datetime
import re
import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
from pymongo import MongoClient
from telegram import Update, InputMediaPhoto, InputMediaVideo
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

# Almacén temporal para agrupar álbumes
ALBUMES_PENDIENTES = {}

# --- SERVIDOR WEB ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Bot Operativo")

def run_web_server():
    server = HTTPServer(('0.0.0.0', int(os.environ.get("PORT", 8080))), SimpleHandler)
    server.serve_forever()

# --- FUNCIONES AUXILIARES ---
def contiene_enlace(texto):
    if not texto: return False
    patron = r"(https?://|t\.me/|www\.)"
    return re.search(patron, texto, re.IGNORECASE)

async def enviar_album_agrupado(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    mg_id = job.name
    data = ALBUMES_PENDIENTES.pop(mg_id, None)
    
    if not data: return

    for target in users_col.find({"status": "accepted"}):
        if target["user_id"] == data['sender_id']: continue
        try:
            await context.bot.send_media_group(chat_id=target["user_id"], media=data['media'])
        except: pass

# --- MANEJADORES ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡𝗕𝗶𝗲𝗻𝘃𝗲𝗻𝗶𝗱𝗼! Envíe 100 aportes y use /solicitar.")

async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    user_id = update.effective_user.id
    user = users_col.find_one({"user_id": user_id})

    # Filtros base
    if contiene_enlace(update.message.text or update.message.caption): return

    # Admin: Reset y Aceptar
    if user_id == MY_ID:
        if update.message.text == "/reset":
            files_col.delete_many({})
            return await update.message.reply_text("✅ Repetidos reseteados.")
        if update.message.text and "/usuarioaceptado" in update.message.text:
            target_id = int(update.message.text.split("/usuarioaceptado")[-1])
            users_col.update_one({"user_id": target_id}, {"$set": {"status": "accepted", "aportes": 0}})
            return await context.bot.send_message(target_id, "¡𝗔𝗰𝗲𝗽𝘁𝗮𝗱𝗼!")

    if not user or user.get("status") == "banned": return

    # Conteo para pendientes
    if user["status"] == "pending":
        if update.message.photo or update.message.video:
            users_col.update_one({"user_id": user_id}, {"$inc": {"aportes": 1}})
        return

    # Lógica para Aceptados
    if user["status"] == "accepted":
        f_unique = ""
        media_obj = None
        
        if update.message.photo:
            f_unique = update.message.photo[-1].file_unique_id
            media_obj = InputMediaPhoto(update.message.photo[-1].file_id, caption=update.message.caption)
        elif update.message.video:
            f_unique = update.message.video.file_unique_id
            media_obj = InputMediaVideo(update.message.video.file_id, caption=update.message.caption)

        if media_obj:
            # Filtro repetidos
            if files_col.find_one({"file_id": f_unique}):
                if not update.message.media_group_id: await update.message.reply_text("𝘃𝗶𝗱𝗲𝗼 𝗿𝗲𝗽𝗲𝘁𝗶𝗱𝗼")
                return
            
            files_col.insert_one({"file_id": f_unique, "user": user_id})
            users_col.update_one({"user_id": user_id}, {"$inc": {"aportes": 1}})

            # ¿Es parte de un álbum?
            mg_id = update.message.media_group_id
            if mg_id:
                if mg_id not in ALBUMES_PENDIENTES:
                    ALBUMES_PENDIENTES[mg_id] = {'sender_id': user_id, 'media': []}
                    context.job_queue.run_once(enviar_album_agrupado, 2.0, name=mg_id)
                
                ALBUMES_PENDIENTES[mg_id]['media'].append(media_obj)
            else:
                # Envío individual normal
                for target in users_col.find({"status": "accepted"}):
                    if target["user_id"] == user_id: continue
                    try:
                        if update.message.photo: await context.bot.send_photo(target["user_id"], update.message.photo[-1].file_id, caption=update.message.caption)
                        else: await context.bot.send_video(target["user_id"], update.message.video.file_id, caption=update.message.caption)
                    except: pass
        
        elif update.message.text:
            for target in users_col.find({"status": "accepted"}):
                if target["user_id"] == user_id: continue
                try: await context.bot.send_message(target["user_id"], f"{update.message.text}\n\n{user['name']}")
                except: pass

def main():
    threading.Thread(target=run_web_server, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.ALL, handle_broadcast))
    app.run_polling()

if __name__ == '__main__':
    main()

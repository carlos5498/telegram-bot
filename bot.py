import os
import logging
import threading
import random
import datetime
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

# Diccionario global para álbumes
ALBUMES = {}

# --- SERVIDOR WEB ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Bot Operativo")

def run_web_server():
    server = HTTPServer(('0.0.0.0', int(os.environ.get("PORT", 8080))), SimpleHandler)
    server.serve_forever()

# --- FUNCIONES DE ENVÍO ---
async def send_album_task(context: ContextTypes.DEFAULT_TYPE):
    mg_id = context.job.name
    data = ALBUMES.pop(mg_id, None)
    
    if not data or not data['media']: return

    user_name = data['user_name']
    sender_id = data['sender_id']
    media_list = data['media']

    # Solo el primer elemento lleva el nombre
    media_list[0].caption = user_name

    for target in users_col.find({"status": "accepted"}):
        if target["user_id"] == sender_id: continue
        try:
            await context.bot.send_media_group(chat_id=target["user_id"], media=media_list)
        except Exception as e:
            logging.error(f"Error enviando álbum: {e}")

# --- MANEJADOR PRINCIPAL ---
async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    user_id = update.effective_user.id
    user = users_col.find_one({"user_id": user_id})
    
    # COMANDO RESET (Solo Admin)
    if update.message.text == "/reset" and user_id == MY_ID:
        files_col.delete_many({})
        await update.message.reply_text("✅ **Base de datos de repetidos reseteada.** Ahora todos los videos pueden enviarse de nuevo.")
        return

    if not user or user.get("status") == "banned": return

    # Admin: Aceptar usuarios
    if update.message.text and "/usuarioaceptado" in update.message.text:
        try:
            target_id = int(update.message.text.split("/usuarioaceptado")[-1])
            users_col.update_one({"user_id": target_id}, {"$set": {"status": "accepted", "aportes": 0}})
            await context.bot.send_message(target_id, "¡𝗙𝗲𝗹𝗶𝗰𝗶𝗱𝗮𝗱𝗲𝘀 𝗵𝗮𝘇 𝘀𝗶𝗱𝗼 𝗮𝗰𝗲𝗽𝘁𝗮𝗱𝗼!")
        except: pass
        return

    # Usuarios pendientes
    if user["status"] == "pending":
        if update.message.photo or update.message.video:
            users_col.update_one({"user_id": user_id}, {"$inc": {"aportes": 1}})
        return

    # Usuarios aceptados
    if user["status"] == "accepted":
        file_item = None
        f_unique = ""
        
        if update.message.photo:
            file_item = InputMediaPhoto(update.message.photo[-1].file_id)
            f_unique = update.message.photo[-1].file_unique_id
        elif update.message.video:
            file_item = InputMediaVideo(update.message.video.file_id)
            f_unique = update.message.video.file_unique_id

        if file_item:
            # Filtro de repetidos
            if files_col.find_one({"file_id": f_unique}):
                await update.message.reply_text("𝘃𝗶𝗱𝗲𝗼 𝗿𝗲𝗽𝗲𝘁𝗶𝗱𝗼")
                return
            
            files_col.insert_one({"file_id": f_unique, "user": user_id})
            users_col.update_one({"user_id": user_id}, {"$inc": {"aportes": 1}})

            mg_id = update.message.media_group_id
            if mg_id:
                if mg_id not in ALBUMES:
                    ALBUMES[mg_id] = {'sender_id': user_id, 'user_name': user['name'], 'media': [], 'job': None}
                
                ALBUMES[mg_id]['media'].append(file_item)
                
                if ALBUMES[mg_id]['job']:
                    ALBUMES[mg_id]['job'].schedule_removal()
                
                # Tiempo de espera de 2.5 segundos para álbumes grandes reenviados
                new_job = context.job_queue.run_once(send_album_task, 2.5, name=mg_id)
                ALBUMES[mg_id]['job'] = new_job
            else:
                for target in users_col.find({"status": "accepted"}):
                    if target["user_id"] == user_id: continue
                    try:
                        if update.message.photo:
                            await context.bot.send_photo(target["user_id"], update.message.photo[-1].file_id, caption=user['name'])
                        else:
                            await context.bot.send_video(target["user_id"], update.message.video.file_id, caption=user['name'])
                    except: pass
        
        elif update.message.text:
            for target in users_col.find({"status": "accepted"}):
                if target["user_id"] == user_id: continue
                try: await context.bot.send_message(target["user_id"], f"{update.message.text}\n\n{user['name']}")
                except: pass

def main():
    threading.Thread(target=run_web_server, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text("Bot iniciado.")))
    app.add_handler(MessageHandler(filters.ALL, handle_broadcast))
    app.run_polling()

if __name__ == '__main__':
    main()

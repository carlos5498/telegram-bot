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

try:
    client = MongoClient(MONGO_URI)
    db = client['bot_anonimo']
    users_col = db['usuarios']
    files_col = db['archivos_vistos']
    print("✅ Conexión a MongoDB exitosa")
except Exception as e:
    print(f"❌ Error MongoDB: {e}")

ADJETIVOS = ["Bravo", "Veloz", "Oscuro", "Místico", "Feroz", "Silencioso", "Letal"]
ANIMALES = ["Lobo", "Zorro", "Halcón", "Tigre", "Puma", "Serpiente", "Águila"]

# Diccionario para agrupar álbumes en memoria
ALBUMES = {}

# --- SERVIDOR WEB ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Bot Operativo")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), SimpleHandler)
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
        users_col.insert_one({"user_id": user_id, "name": generate_anon_name(), "status": "pending", "aportes": 0, "last_reset": str(datetime.date.today())})
    
    await update.message.reply_text(
        "¡𝗕𝗶𝗲𝗻𝘃𝗲𝗻𝗶𝗱𝗼! 𝗘𝘀𝘁𝗲 𝗲𝘀 𝘂𝗻 𝗯𝗼𝘁 𝗯𝗲𝘁𝗮 𝗽𝗮𝗿𝗮 𝗲𝗻𝘃𝗶𝗮𝗿 𝗺𝗲𝗻𝘀𝗮𝗷𝗲𝘀 𝗲 𝗶𝗻𝘁𝗲𝗿𝗰𝗮𝗺𝗯𝗶𝗼𝘀 𝗱𝗲 𝗰𝗼𝗻𝘁𝗲𝗻𝗶𝗱𝗼 𝗱𝗲 𝗺𝗮𝗻𝗲𝗿𝗮 𝗮𝗻𝗼́𝗻𝗶𝗺𝗮.\n\n"
        "• 𝗘𝗻𝘃𝗶́𝗮 𝟭𝟬𝟬 𝗺𝘂𝗹𝘁𝗶𝗺𝗲𝗱𝗶𝗮 𝗽𝗮𝗿𝗮 𝘀𝗲𝗿 𝗮𝗰𝗲𝗽𝘁𝗮𝗱𝗼.\n"
        "• 𝗟𝘂𝗲𝗴𝗼 𝘂𝘀𝗮 /solicitar 𝗽𝗮𝗿𝗮 𝗽𝗲𝗱𝗶𝗿 𝗮𝗰𝗰𝗲𝘀𝗼."
    )

async def solicitar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_db = get_user(user_id)
    await update.message.reply_text("¡𝗛𝗮𝘀 𝘀𝗼𝗹𝗶𝗰𝗶𝘁𝗮𝗱𝗼 𝗮𝗰𝗰𝗲𝘀𝗼! 𝗦𝗲 𝘁𝗲 𝗻𝗼𝘁𝗶𝗳𝗶𝗰𝗮𝗿𝗮́ 𝗰𝘂𝗮𝗻𝗱𝗼 𝘀𝗲𝗮𝘀 𝗮𝗰𝗲𝗽𝘁𝗮𝗱𝗼.")
    
    mensaje_admin = f"📥 𝗡𝗨𝗘𝗩𝗔 𝗦𝗢𝗟𝗜𝗖𝗜𝗧𝗨𝗗\n🆔: `{user_id}`\n🎭: {user_db['name']}\n\n`/usuarioaceptado{user_id}`"
    await context.bot.send_message(MY_ID, mensaje_admin, parse_mode="Markdown")

async def send_album(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    media_group_id = job.name
    data = ALBUMES.pop(media_group_id, None)
    if not data: return

    user_name = data['user_name']
    media = data['media']
    
    # Enviar álbum a todos los aceptados
    for target in users_col.find({"status": "accepted"}):
        if target["user_id"] == data['sender_id']: continue
        try:
            # El primer elemento del álbum lleva el nombre del usuario como pie de foto
            media[0].caption = user_name
            await context.bot.send_media_group(chat_id=target["user_id"], media=media)
        except: pass

async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user: return

    # Admin Control
    if update.message.text and "/usuarioaceptado" in update.message.text:
        target_id = int(update.message.text.split("/usuarioaceptado")[-1])
        users_col.update_one({"user_id": target_id}, {"$set": {"status": "accepted", "aportes": 0}})
        await context.bot.send_message(target_id, "¡𝗙𝗲𝗹𝗶𝗰𝗶𝗱𝗮𝗱𝗲𝘀 𝗵𝗮𝘇 𝘀𝗶𝗱𝗼 𝗮𝗰𝗲𝗽𝘁𝗮𝗱𝗼!")
        return

    # Lógica de Pendientes (Conteo)
    if user["status"] == "pending":
        if update.message.photo or update.message.video:
            users_col.update_one({"user_id": user_id}, {"$inc": {"aportes": 1}})
        return

    # Lógica de Aceptados (Broadcast con Álbumes)
    if user["status"] == "accepted":
        await check_daily_reset(user_id, user)
        
        # Detectar si es Foto o Video
        file_item = None
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

            # Si es parte de un álbum (Media Group)
            if update.message.media_group_id:
                mg_id = update.message.media_group_id
                if mg_id not in ALBUMES:
                    ALBUMES[mg_id] = {'sender_id': user_id, 'user_name': user['name'], 'media': []}
                    context.job_queue.run_once(send_album, 0.8, name=mg_id)
                ALBUMES[mg_id]['media'].append(file_item)
            else:
                # Envío individual normal
                for target in users_col.find({"status": "accepted"}):
                    if target["user_id"] == user_id: continue
                    try:
                        if update.message.photo: await context.bot.send_photo(target["user_id"], update.message.photo[-1].file_id, caption=user['name'])
                        else: await context.bot.send_video(target["user_id"], update.message.video.file_id, caption=user['name'])
                    except: pass
        
        elif update.message.text:
            for target in users_col.find({"status": "accepted"}):
                if target["user_id"] == user_id: continue
                try: await context.bot.send_message(target["user_id"], f"{update.message.text}\n\n{user['name']}")
                except: pass

async def commands_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user: return
    if "/aportes" in update.message.text:
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

import os
import logging
import threading
import asyncio
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from pymongo import MongoClient
from telegram import Update, InputMediaPhoto, InputMediaVideo
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# --- CONFIGURACIÓN ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
TOKEN = os.getenv("TOKEN")
MY_ID = int(os.getenv("MY_ID", "0"))
MONGO_URI = os.getenv("MONGO_URI")

# --- DATABASE ---
client = MongoClient(MONGO_URI)
db = client['bot_anonimo']
users_col = db['usuarios']
files_col = db['archivos_vistos']

ALBUMES_MEMORIA = {}
lock = asyncio.Lock()

# --- SERVIDOR WEB ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot Running")

def run_web_server():
    port = int(os.environ.get("PORT", 7860))
    server = HTTPServer(('0.0.0.0', port), SimpleHandler)
    server.serve_forever()

# --- LÓGICA DE REENVÍO DE ÁLBUMES ---
async def enviar_album(context, mg_id):
    # Espera extendida para asegurar que lleguen todas las piezas del álbum
    await asyncio.sleep(8) 
    
    async with lock:
        data = ALBUMES_MEMORIA.pop(mg_id, None)
    
    if not data or not data['media']:
        return

    destinatarios = list(users_col.find({"status": "accepted"}))
    for target in destinatarios:
        if target["user_id"] == data['sender_id']:
            continue
        try:
            # Reenvía el grupo de medios sin ningún texto adicional
            await context.bot.send_media_group(chat_id=target["user_id"], media=data['media'])
            await asyncio.sleep(0.5) 
        except:
            pass

# --- MANEJADOR DE MENSAJES ---
async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    user_id = update.effective_user.id
    user = users_col.find_one({"user_id": user_id})

    # 1. USUARIO NUEVO
    if not user:
        users_col.insert_one({"user_id": user_id, "status": "pending", "aportes": 0})
        return await update.message.reply_text(
            "👋 ¡Hola! Este es un bot beta.\n\n"
            "Para ser aceptado, debes colaborar con **100 aportes** (fotos o videos)."
        )

    # 2. COMANDOS ADMIN
    if user_id == MY_ID:
        if update.message.text == "/reset":
            files_col.delete_many({})
            return await update.message.reply_text("✅ Historial de repetidos limpio.")
        if update.message.text and "/usuarioaceptado" in update.message.text:
            try:
                t_id = int(update.message.text.split("/usuarioaceptado")[-1].strip())
                users_col.update_one({"user_id": t_id}, {"$set": {"status": "accepted"}})
                await context.bot.send_message(t_id, "🎊 Has sido aceptado. Ya puedes usar el bot.")
                return await update.message.reply_text(f"✅ ID {t_id} aceptado.")
            except: return

    # 3. FILTRO PENDIENTES
    if user["status"] == "pending":
        if update.message.photo or update.message.video:
            nueva_cuenta = user.get("aportes", 0) + 1
            users_col.update_one({"user_id": user_id}, {"$set": {"aportes": nueva_cuenta}})
            return await update.message.reply_text(f"✅ Aporte recibido: {nueva_cuenta}/100.")
        return await update.message.reply_text("Solo fotos y videos cuentan como aportes.")

    # 4. REENVÍO (USUARIOS ACEPTADOS)
    if user["status"] == "accepted":
        # Bloqueo de links
        texto_original = update.message.text or update.message.caption or ""
        if re.search(r"(https?://|t\.me/|www\.)", texto_original, re.IGNORECASE):
            return

        f_id = ""
        media = None
        # Solo conservamos el caption original del usuario, sin añadir nada
        caption = update.message.caption if update.message.caption else None

        if update.message.photo:
            f_id = update.message.photo[-1].file_unique_id
            media = InputMediaPhoto(update.message.photo[-1].file_id, caption=caption)
        elif update.message.video:
            f_id = update.message.video.file_unique_id
            media = InputMediaVideo(update.message.video.file_id, caption=caption)

        # Control de duplicados
        if f_id:
            if files_col.find_one({"file_id": f_id}):
                return await update.message.reply_text("❌ Este archivo ya fue compartido.")
            files_col.insert_one({"file_id": f_id})

            # Manejo de álbumes
            mg_id = update.message.media_group_id
            if mg_id:
                async with lock:
                    if mg_id not in ALBUMES_MEMORIA:
                        ALBUMES_MEMORIA[mg_id] = {'sender_id': user_id, 'media': []}
                        asyncio.create_task(enviar_album(context, mg_id))
                    ALBUMES_MEMORIA[mg_id]['media'].append(media)
                return 

            # Reenvío individual (sin nombres)
            destinatarios = users_col.find({"status": "accepted"})
            for t in destinatarios:
                if t["user_id"] == user_id: continue
                try:
                    if update.message.photo:
                        await context.bot.send_photo(t["user_id"], update.message.photo[-1].file_id, caption=caption)
                    else:
                        await context.bot.send_video(t["user_id"], update.message.video.file_id, caption=caption)
                except: pass
        
        elif update.message.text:
            # Reenvío de texto puro (sin nombres)
            for t in users_col.find({"status": "accepted"}):
                if t["user_id"] == user_id: continue
                try: await context.bot.send_message(t["user_id"], update.message.text)
                except: pass

# --- BUCLE DE INICIO ---
async def main():
    threading.Thread(target=run_web_server, daemon=True).start()
    await asyncio.sleep(10)
    
    while True:
        try:
            app = Application.builder().token(TOKEN).connect_timeout(60).read_timeout(60).build()
            app.add_handler(MessageHandler(filters.ALL, handle_msg))
            await app.initialize()
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)
            logging.info("Bot activo.")
            while True: await asyncio.sleep(3600)
        except Exception as e:
            logging.error(f"Reintentando... {e}")
            await asyncio.sleep(20)

if __name__ == '__main__':
    asyncio.run(main())

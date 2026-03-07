import os
import logging
import threading
import datetime
import asyncio
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from pymongo import MongoClient
from telegram import Update, InputMediaPhoto, InputMediaVideo
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- CONFIGURACIÓN ---
logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("TOKEN")
MY_ID = int(os.getenv("MY_ID", "0"))
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_PASSWORD = "Carlos13mar"

client = MongoClient(MONGO_URI)
db = client['bot_anonimo']
users_col = db['usuarios']
files_col = db['archivos_vistos']
config_col = db['configuracion']

ALBUMES_COLA = {}
lock = asyncio.Lock()

# --- SERVIDOR WEB ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Bot Running - Todo Actualizado")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), SimpleHandler)
    server.serve_forever()

# --- FUNCIONES DE LÓGICA ---

async def ejecutar_limpieza_inactividad(context):
    inactivos = users_col.find({"status": "accepted", "aportes": 0})
    count = 0
    for u in inactivos:
        if u["user_id"] == MY_ID: continue
        users_col.update_one({"user_id": u["user_id"]}, {"$set": {"status": "banned"}})
        try: await context.bot.send_message(u["user_id"], "🚫 **Baneado por inactividad.**")
        except: pass
        count += 1
    return count

async def check_daily_reset(user_id, user_data, context):
    today = str(datetime.date.today())
    if user_data.get("last_reset") != today:
        if user_data.get("status") == "accepted" and user_data.get("aportes") == 0:
            users_col.update_one({"user_id": user_id}, {"$set": {"status": "banned"}})
            try: await context.bot.send_message(user_id, "🚫 **Baneado por inactividad.**")
            except: pass
            return True
        users_col.update_one({"user_id": user_id}, {"$set": {"aportes": 0, "last_reset": today}})
    return False

def get_config():
    config = config_col.find_one({"key": "global_config"})
    if not config:
        default = {"key": "global_config", "paused": False, "auto_pass": "planpa54", "pass_active": True}
        config_col.insert_one(default)
        return default
    return config

# --- PROCESAMIENTO DE ÁLBUMES ---
async def procesar_y_enviar_album(context, mg_id):
    await asyncio.sleep(5)
    async with lock:
        data = ALBUMES_COLA.pop(mg_id, None)
    if not data: return
    for target in users_col.find({"status": "accepted"}):
        if target["user_id"] == data['sender_id']: continue
        try:
            await context.bot.send_media_group(chat_id=target["user_id"], media=data['media'])
            await asyncio.sleep(0.1)
        except: pass

# --- MANEJADORES ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not users_col.find_one({"user_id": user_id}):
        users_col.insert_one({"user_id": user_id, "status": "pending", "aportes": 0, "last_reset": str(datetime.date.today())})
    await update.message.reply_text("¡Bienvenido! Envía aportes o usa la contraseña para entrar.")

async def solicitar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Respuesta confirmando solicitud
    await update.message.reply_text("¡Has solicitado acceso a un administrador! Se te notificará cuando seas aceptado.")
    
    # Respuesta con las reglas actualizadas
    reglas = (
        "Mientras esperas Lee las reglas:\n\n"
        "🚫 No gay/gore/+18\n"
        "🟢 10 aportes diarios\n\n"
        "• **El bot tiene un sistema antiflood que genera un retraso breve en el envío de muchos mensajes**"
    )
    msg = await update.message.reply_text(reglas, parse_mode="Markdown")
    try: await context.bot.pin_chat_message(chat_id=user_id, message_id=msg.message_id)
    except: pass
    
    # Aviso al Admin
    await context.bot.send_message(MY_ID, f"📥 Solicitud: {user_id}\n`/usuarioaceptado{user_id}`")

async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    user_id = update.effective_user.id
    text = update.message.text or update.message.caption or ""
    config = get_config()

    # Anti-Spam
    if re.search(r"(http://|https://|t\.me/|\.com)", text.lower()) and user_id != MY_ID:
        return await update.message.reply_text("🚫 No se permiten enlaces.")

    # Panel Admin y Contraseña
    if text == ADMIN_PASSWORD and user_id == MY_ID:
        return await update.message.reply_text("🔑 **PANEL ADMIN**\n/reset | /mensaje | /stop | /revocar | /nuevapass", parse_mode="Markdown")

    if text == config["auto_pass"] and config["pass_active"]:
        users_col.update_one({"user_id": user_id}, {"$set": {"status": "accepted", "aportes": 0, "last_reset": str(datetime.date.today())}})
        return await update.message.reply_text("✅ ¡Acceso concedido!")

    user = users_col.find_one({"user_id": user_id})
    if not user or user.get("status") == "banned": return

    # Lógica de Difusión (/mensaje)
    if user_id == MY_ID:
        if text == "/mensaje":
            context.user_data['wait_msg'] = True
            return await update.message.reply_text("📢 **MODO DIFUSIÓN ACTIVADO**\nEnvíe el mensaje ahora.", parse_mode="Markdown")

        if context.user_data.get('wait_msg'):
            context.user_data['wait_msg'] = False
            for t in users_col.find({"status": "accepted"}):
                if t["user_id"] == MY_ID: continue
                try: await update.message.copy(t["user_id"])
                except: pass
            return await update.message.reply_text("🚀 Difusión completada.")

        if text == "/reset":
            baneados = await ejecutar_limpieza_inactividad(context)
            files_col.delete_many({})
            return await update.message.reply_text(f"✅ Reset. Baneados: {baneados}")

    # Reenvío de Usuarios Aceptados
    if user["status"] == "accepted":
        if config["paused"] and user_id != MY_ID: return
        if await check_daily_reset(user_id, user, context): return

        file_id = None
        media_obj = None
        if update.message.photo:
            file_id = update.message.photo[-1].file_unique_id
            media_obj = InputMediaPhoto(update.message.photo[-1].file_id, caption=update.message.caption)
        elif update.message.video:
            file_id = update.message.video.file_unique_id
            media_obj = InputMediaVideo(update.message.video.file_id, caption=update.message.caption)

        if file_id:
            if files_col.find_one({"file_id": file_id}):
                return await update.message.reply_text("❌ repetido")
            files_col.insert_one({"file_id": file_id})
            users_col.update_one({"user_id": user_id}, {"$inc": {"aportes": 1}})

            if update.message.media_group_id:
                mg_id = update.message.media_group_id
                async with lock:
                    if mg_id not in ALBUMES_COLA:
                        ALBUMES_COLA[mg_id] = {'sender_id': user_id, 'media': []}
                        asyncio.create_task(procesar_y_enviar_album(context, mg_id))
                    ALBUMES_COLA[mg_id]['media'].append(media_obj)
                return

        for target in users_col.find({"status": "accepted"}):
            if target["user_id"] == user_id: continue
            try:
                await update.message.copy(target["user_id"])
                await asyncio.sleep(0.05)
            except: pass

def main():
    threading.Thread(target=run_web_server, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("solicitar", solicitar))
    app.add_handler(MessageHandler(filters.ALL, handle_broadcast))
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()

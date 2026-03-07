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

# Conexión a Base de Datos
client = MongoClient(MONGO_URI)
db = client['bot_anonimo']
users_col = db['usuarios']
files_col = db['archivos_vistos']
config_col = db['configuracion']

ALBUMES_COLA = {}
lock = asyncio.Lock()

# --- SERVIDOR WEB (Para mantener vivo el bot) ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Bot Running - Estado: OK")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), SimpleHandler)
    server.serve_forever()

# --- FUNCIONES AUXILIARES ---
def get_user(user_id):
    return users_col.find_one({"user_id": user_id})

def get_config():
    config = config_col.find_one({"key": "global_config"})
    if not config:
        default = {"key": "global_config", "paused": False, "auto_pass": "planpa54", "pass_active": True}
        config_col.insert_one(default)
        return default
    return config

async def check_daily_reset(user_id, user_data):
    today = str(datetime.date.today())
    if user_data.get("last_reset") != today:
        users_col.update_one({"user_id": user_id}, {"$set": {"aportes": 0, "last_reset": today}})
        return 0
    return user_data.get("aportes", 0)

# --- PROCESAMIENTO DE ÁLBUMES ---
async def procesar_y_enviar_album(context, mg_id):
    await asyncio.sleep(5)
    async with lock:
        data = ALBUMES_COLA.pop(mg_id, None)
    if not data or not data['media']: return
    destinatarios = list(users_col.find({"status": "accepted"}))
    for target in destinatarios:
        if target["user_id"] == data['sender_id']: continue
        try:
            await context.bot.send_media_group(chat_id=target["user_id"], media=data['media'])
            await asyncio.sleep(0.1)
        except: pass

# --- MANEJADOR PRINCIPAL ---
async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    user_id = update.effective_user.id
    text = update.message.text
    config = get_config()

    # 1. ACCESO AL PANEL (Contraseña de Admin)
    if text == ADMIN_PASSWORD and user_id == MY_ID:
        panel = (
            "🔑 **PANEL ADMIN**\n\n"
            "/reset - Limpiar duplicados\n"
            "/mensaje - Enviar aviso global\n"
            "/stop - Pausar/Reanudar bot\n"
            "/revocar - Anular contraseña actual\n"
            "/nuevapass [clave] - Cambiar contraseña"
        )
        return await update.message.reply_text(panel, parse_mode="Markdown")

    # 2. CONTRASEÑA DE USUARIO (Acceso directo)
    if text == config["auto_pass"] and config["pass_active"]:
        users_col.update_one({"user_id": user_id}, {"$set": {"status": "accepted"}})
        return await update.message.reply_text("✅ ¡Acceso concedido! Ahora eres un usuario aceptado.")

    user = get_user(user_id)
    if not user: return

    # 3. LÓGICA DE COMANDOS DE ADMIN
    if user_id == MY_ID:
        # Comando para activar el modo difusión
        if text == "/mensaje":
            context.user_data['wait_msg'] = True
            return await update.message.reply_text("📢 **MODO DIFUSIÓN ACTIVADO**\n\nEl siguiente mensaje que envíes (texto, foto o video) será enviado a todos los usuarios aceptados.")

        # Procesar el mensaje de difusión si el modo está activo
        if context.user_data.get('wait_msg'):
            context.user_data['wait_msg'] = False
            destinatarios = list(users_col.find({"status": "accepted"}))
            count = 0
            for t in destinatarios:
                if t["user_id"] == MY_ID: continue
                try:
                    await update.message.copy(t["user_id"])
                    await asyncio.sleep(0.05)
                    count += 1
                except: pass
            return await update.message.reply_text(f"🚀 **DIFUSIÓN COMPLETADA**\nEnviado con éxito a {count} usuarios.")

        # Otros comandos administrativos
        if text == "/reset":
            files_col.delete_many({}); return await update.message.reply_text("✅ Lista de duplicados reseteada.")
        if text == "/stop":
            new_s = not config["paused"]
            config_col.update_one({"key": "global_config"}, {"$set": {"paused": new_s}})
            aviso = "🛑 **EL BOT HA SIDO PAUSADO POR MANTENIMIENTO**" if new_s else "✅ **EL BOT ESTÁ ACTIVO NUEVAMENTE**"
            for t in users_col.find({"status": "accepted"}):
                try: await context.bot.send_message(t["user_id"], aviso, parse_mode="Markdown")
                except: pass
            return await update.message.reply_text(f"Estado de pausa: {new_s}")
        if text == "/revocar":
            config_col.update_one({"key": "global_config"}, {"$set": {"pass_active": False}})
            return await update.message.reply_text("🚫 Contraseña de acceso directo revocada.")
        if text and text.startswith("/nuevapass "):
            nueva = text.split("/nuevapass ")[1].strip()
            config_col.update_one({"key": "global_config"}, {"$set": {"auto_pass": nueva, "pass_active": True}})
            return await update.message.reply_text(f"✅ Nueva contraseña establecida: `{nueva}`", parse_mode="Markdown")
        if text and "/usuario" in text:
            try:
                target_id = int(re.search(r'\d+', text).group())
                if "aceptado" in text:
                    users_col.update_one({"user_id": target_id}, {"$set": {"status": "accepted"}})
                    await context.bot.send_message(target_id, "¡Has sido aceptado!")
                elif "baneado" in text:
                    users_col.update_one({"user_id": target_id}, {"$set": {"status": "banned"}})
                await update.message.delete()
            except: pass
            return

    # 4. FLUJO NORMAL DE USUARIOS
    if config["paused"] and user_id != MY_ID: return

    if user["status"] == "pending":
        if update.message.photo or update.message.video:
            users_col.update_one({"user_id": user_id}, {"$inc": {"aportes": 1}})
        return

    if user["status"] == "accepted":
        await check_daily_reset(user_id, user)
        
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
                return await update.message.reply_text("❌ video/foto repetido")
            files_col.insert_one({"file_id": file_id})
            users_col.update_one({"user_id": user_id}, {"$inc": {"aportes": 1}})

            mg_id = update.message.media_group_id
            if mg_id:
                async with lock:
                    if mg_id not in ALBUMES_COLA:
                        ALBUMES_COLA[mg_id] = {'sender_id': user_id, 'media': []}
                        asyncio.create_task(procesar_y_enviar_album(context, mg_id))
                    ALBUMES_COLA[mg_id]['media'].append(media_obj)
                return

        # Reenvío rápido de mensajes individuales
        for target in users_col.find({"status": "accepted"}):
            if target["user_id"] == user_id: continue
            try:
                await update.message.copy(target["user_id"])
                await asyncio.sleep(0.05)
            except: pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not get_user(user_id):
        users_col.insert_one({"user_id": user_id, "status": "pending", "aportes": 0, "last_reset": str(datetime.date.today())})
    await update.message.reply_text("¡Bienvenido! Envía aportes o usa la contraseña para entrar.")

async def solicitar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text("¡𝗦𝗼𝗹𝗶𝗰𝗶𝘁𝘂𝗱 𝗲𝗻𝘃𝗶𝗮𝗱𝗮!")
    reglas = (
        "🚫 **No Gore/CP/+18**\n"
        "🟢 **10 aportes diarios**\n"
        "• **El bot tiene un sistema antiflood que genera un retraso breve en el envío de muchos mensajes**"
    )
    msg = await update.message.reply_text(reglas, parse_mode="Markdown")
    try: await context.bot.pin_chat_message(chat_id=user_id, message_id=msg.message_id)
    except: pass
    await context.bot.send_message(MY_ID, f"📥 Solicitud: {update.effective_user.full_name}\nID: `{user_id}`\n`/usuarioaceptado{user_id}`", parse_mode="Markdown")

def main():
    threading.Thread(target=run_web_server, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("solicitar", solicitar))
    app.add_handler(MessageHandler(filters.ALL, handle_broadcast))
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()

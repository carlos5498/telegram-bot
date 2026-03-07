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

# --- SERVIDOR WEB ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Bot Running - Todo Integrado OK")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), SimpleHandler)
    server.serve_forever()

# --- FUNCIONES DE LÓGICA Y SEGURIDAD ---

async def ejecutar_limpieza_inactividad(context):
    """Banea a usuarios aceptados que tengan 0 aportes"""
    inactivos = users_col.find({"status": "accepted", "aportes": 0})
    count = 0
    for u in inactivos:
        if u["user_id"] == MY_ID: continue
        users_col.update_one({"user_id": u["user_id"]}, {"$set": {"status": "banned"}})
        try:
            await context.bot.send_message(u["user_id"], "🚫 **Has sido baneado por inactividad (0 aportes hoy).**")
        except: pass
        count += 1
    return count

async def check_daily_reset(user_id, user_data, context):
    """Verifica cambio de día y banea si hubo inactividad"""
    today = str(datetime.date.today())
    if user_data.get("last_reset") != today:
        # Si el día cambió y tenía 0 aportes, baneo automático
        if user_data.get("status") == "accepted" and user_data.get("aportes") == 0:
            users_col.update_one({"user_id": user_id}, {"$set": {"status": "banned"}})
            try: await context.bot.send_message(user_id, "🚫 **Baneado por inactividad.**")
            except: pass
            return True # Fue baneado
        
        # Si no, resetear contador para el nuevo día
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
    await asyncio.sleep(5) # Espera ráfaga
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
    text = update.message.text or update.message.caption or ""
    config = get_config()

    # --- 1. ANTI-SPAM (ENLACES) ---
    enlace_pattern = r"(http://|https://|t\.me/|\.com|\.net|\.org)"
    if re.search(enlace_pattern, text.lower()) and user_id != MY_ID:
        return await update.message.reply_text("🚫 **No se permiten enlaces en este bot.**")

    # --- 2. PANEL ADMIN ---
    if text == ADMIN_PASSWORD and user_id == MY_ID:
        panel = "🔑 **PANEL ADMIN**\n/reset | /mensaje | /stop | /revocar | /nuevapass"
        return await update.message.reply_text(panel, parse_mode="Markdown")

    # --- 3. CONTRASEÑA USUARIO ---
    if text == config["auto_pass"] and config["pass_active"]:
        users_col.update_one({"user_id": user_id}, {"$set": {"status": "accepted", "aportes": 0, "last_reset": str(datetime.date.today())}})
        return await update.message.reply_text("✅ ¡Acceso concedido!")

    user = users_col.find_one({"user_id": user_id})
    if not user or user.get("status") == "banned": return

    # --- 4. LÓGICA DE COMANDOS ADMIN ---
    if user_id == MY_ID:
        if text == "/reset":
            baneados = await ejecutar_limpieza_inactividad(context)
            files_col.delete_many({})
            return await update.message.reply_text(f"✅ Reset completado. Baneados: {baneados}")
        
        if text == "/mensaje":
            context.user_data['wait_msg'] = True
            return await update.message.reply_text("📢 **MODO DIFUSIÓN**: Envíe el mensaje ahora.")

        if context.user_data.get('wait_msg'):
            context.user_data['wait_msg'] = False
            for t in users_col.find({"status": "accepted"}):
                if t["user_id"] == MY_ID: continue
                try: await update.message.copy(t["user_id"])
                except: pass
            return await update.message.reply_text("🚀 Difusión completada.")

        if text == "/stop":
            new_s = not config["paused"]
            config_col.update_one({"key": "global_config"}, {"$set": {"paused": new_s}})
            return await update.message.reply_text(f"Pausa: {new_s}")
            
        if text == "/revocar":
            config_col.update_one({"key": "global_config"}, {"$set": {"pass_active": False}})
            return await update.message.reply_text("🚫 Contraseña revocada.")

        if text.startswith("/nuevapass "):
            nueva = text.split("/nuevapass ")[1].strip()
            config_col.update_one({"key": "global_config"}, {"$set": {"auto_pass": nueva, "pass_active": True}})
            return await update.message.reply_text(f"✅ Nueva clave: `{nueva}`")

    # --- 5. FLUJO USUARIOS ACEPTADOS ---
    if user["status"] == "accepted":
        if config["paused"] and user_id != MY_ID: return
        
        # Verificar inactividad diaria
        fue_baneado = await check_daily_reset(user_id, user, context)
        if fue_baneado: return

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

            mg_id = update.message.media_group_id
            if mg_id:
                async with lock:
                    if mg_id not in ALBUMES_COLA:
                        ALBUMES_COLA[mg_id] = {'sender_id': user_id, 'media': []}
                        asyncio.create_task(procesar_y_enviar_album(context, mg_id))
                    ALBUMES_COLA[mg_id]['media'].append(media_obj)
                return

        # Reenvío Veloz
        for target in users_col.find({"status": "accepted"}):
            if target["user_id"] == user_id: continue
            try:
                await update.message.copy(target["user_id"])
                await asyncio.sleep(0.05)
            except: pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not users_col.find_one({"user_id": user_id}):
        users_col.insert_one({"user_id": user_id, "status": "pending", "aportes": 0, "last_reset": str(datetime.date.today())})
    await update.message.reply_text("¡Bienvenido! Envía aportes o usa la contraseña.")

async def solicitar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text("¡𝗦𝗼𝗹𝗶𝗰𝗶𝘁𝘂𝗱 𝗲𝗻𝘃𝗶𝗮𝗱𝗮!")
    reglas = "🚫 **No Gore/CP/+18**\n🟢 **10 aportes diarios**\n• **Sistema antiflood activo.**"
    msg = await update.message.reply_text(reglas, parse_mode="Markdown")
    try: await context.bot.pin_chat_message(chat_id=user_id, message_id=msg.message_id)
    except: pass
    await context.bot.send_message(MY_ID, f"📥 Solicitud: {user_id}\n`/usuarioaceptado{user_id}`")

def main():
    threading.Thread(target=run_web_server, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("solicitar", solicitar))
    app.add_handler(MessageHandler(filters.ALL, handle_broadcast))
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()

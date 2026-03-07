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
        self.wfile.write(b"Bot Running - Albumes Corregidos")

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
        try: await context.bot.send_message(u["user_id"], "🚫 𝗕𝗮𝗻𝗲𝗮𝗱𝗼 𝗽𝗼𝗿 𝗶𝗻𝗮𝗰𝘁𝗶𝘃𝗶𝗱𝗮𝗱.")
        except: pass
        count += 1
    return count

async def check_daily_reset(user_id, user_data, context):
    today = str(datetime.date.today())
    if user_data.get("last_reset") != today:
        if user_data.get("status") == "accepted" and user_data.get("aportes") == 0:
            users_col.update_one({"user_id": user_id}, {"$set": {"status": "banned"}})
            try: await context.bot.send_message(user_id, "🚫 𝗕𝗮𝗻𝗲𝗮𝗱𝗼 𝗽𝗼𝗿 𝗶𝗻𝗮𝗰𝘁𝗶𝘃𝗶𝗱𝗮𝗱.")
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

# --- PROCESAMIENTO DE ÁLBUMES (CORREGIDO) ---
async def procesar_y_enviar_album(context, mg_id):
    await asyncio.sleep(4) # Tiempo de espera para recolectar el álbum completo
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
    
    mensaje = (
        "¡𝗕𝗶𝗲𝗻𝘃𝗲𝗻𝗶𝗱𝗼! 𝗘𝘀𝘁𝗲 𝗲𝘀 𝘂𝗻 𝗯𝗼𝘁 𝗯𝗲𝘁𝗮 𝗽𝗮𝗿𝗮 𝗲𝗻𝘃𝗶𝗮𝗿 𝗺𝗲𝗻𝘀𝗮𝗷𝗲𝘀 𝗲 𝗶𝗻𝘁𝗲𝗿𝗰𝗮𝗺𝗯𝗶𝗮𝗿 𝗰𝗼𝗻𝘁𝗲𝗻𝗶𝗱𝗼 𝗱𝗲 𝗺𝗮𝗻𝗲𝗿𝗮 𝗮𝗻𝗼𝗻𝗶𝗺𝗮.\n\n"
        "𝗣𝗮𝗿𝗮 𝗽𝗼𝗱𝗲𝗿 𝘂𝘀𝗮𝗿 𝗲𝗹 𝗯𝗼𝘁 𝗱𝗲𝗯𝗲𝘀 𝘀𝗲𝗿 𝗮𝗰𝗲𝗽𝘁𝗮𝗱𝗼 𝗽𝗼𝗿 𝘂𝗻 𝗮𝗱𝗺𝗶𝗻𝗶𝘀𝘁𝗿𝗮𝗱𝗼𝗿\n\n"
        "• 𝗘𝗻𝘃𝗶𝗮 𝟭𝟬𝟬 𝗺𝘂𝗹𝘁𝗶𝗺𝗲𝗱𝗶𝗮 (𝗳𝗼𝘁𝗼𝘀/𝘃𝗶𝗱𝗲𝗼𝘀) 𝗱𝗲 𝗰𝗼𝗻𝘁𝗲𝗻𝗶𝗱𝗼 𝗽𝗮𝗿𝗮 𝘀𝗲𝗿 𝗮𝗰𝗲𝗽𝘁𝗮𝗱𝗼.\n"
        "• 𝗟𝘂𝗲𝗴𝗼 𝘂𝘀𝗮 /solicitar 𝗽𝗮𝗿𝗮 𝗽𝗲𝗱𝗶𝗿 𝗮𝗰𝗰𝗲𝘀𝗼 𝗮 𝘂𝗻 𝗮𝗱𝗺𝗶𝗻𝗶𝘀𝘁𝗿𝗮𝗱𝗼𝗿"
    )
    await update.message.reply_text(mensaje)

async def solicitar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text("¡𝗛𝗮𝘀 𝘀𝗼𝗹𝗶𝗰𝗶𝘁𝗮𝗱𝗼 𝗮𝗰𝗰𝗲𝘀𝗼 𝗮 𝘂𝗻 𝗮𝗱𝗺𝗶𝗻𝗶𝘀𝘁𝗿𝗮𝗱𝗼𝗿! 𝗦𝗲 𝘁𝗲 𝗻𝗼𝘁𝗶𝗳𝗶𝗰𝗮𝗿𝗮 𝗰𝘂𝗮𝗻𝗱𝗼 𝘀𝗲𝗮𝘀 𝗮𝗰𝗲𝗽𝘁𝗮𝗱𝗼.")
    
    reglas = (
        "𝗠𝗶𝗲𝗻𝘁𝗿𝗮𝘀 𝗲𝘀𝗽𝗲𝗿𝗮𝘀 𝗹𝗲𝗮 𝗹𝗮𝘀 𝗽𝗲𝗴𝗹𝗮𝘀:\n\n"
        "🚫 𝗡𝗼 𝗴𝗮𝘆/𝗴𝗼𝗿𝗲/+𝟭𝟴\n"
        "🟢 𝟭𝟬 𝗮𝗽𝗼𝗿𝘁𝗲𝘀 𝗱𝗶𝗮𝗿𝗶𝗼𝘀\n"
        "🟢 𝗣𝘂𝗲𝗱𝗲𝘀 𝗰𝗼𝗺𝗽𝗮𝗿𝘁𝗶𝗿 𝗲𝗹 𝗯𝗼𝘁\n\n"
        "• /usuarios > 𝗨𝘀𝘂𝗮𝗿𝗶𝗼𝘀 𝗮𝗰𝘁𝗶𝘃𝗼𝘀 𝗮𝗰𝘁𝘂𝗮𝗹𝗺𝗲𝗻𝘁𝗲\n"
        "• /aportes > 𝗧𝘂 𝗽𝗿𝗼𝗴𝗿𝗲𝘀𝗼 𝗱𝗶𝗮𝗿𝗶𝗼 𝗱𝗶𝗮𝗿𝗶𝗼\n"
        "• 𝗘𝗹 𝗯𝗼𝘁 𝘁𝗶𝗲𝗻𝗲 𝘂𝗻 𝘀𝗶𝘀𝘁𝗲𝗺𝗮 𝗮𝗻𝘁𝗶𝗳𝗹𝗼𝗼𝗱 𝗾𝘂𝗲 𝗴𝗲𝗻𝗲𝗿𝗮 𝘂𝗻 𝗿𝗲𝘁𝗿𝗮𝘀𝗼 𝗯𝗿𝗲𝘃𝗲 𝗲𝗻 𝗲𝗹 𝗲𝗻𝘃𝗶́𝗼 𝗱𝗲 𝗺𝘂𝗰𝗵𝗼𝘀 𝗺𝗲𝗻𝘀𝗮𝗷𝗲𝘀"
    )
    msg = await update.message.reply_text(reglas)
    try: await context.bot.pin_chat_message(chat_id=user_id, message_id=msg.message_id)
    except: pass
    
    await context.bot.send_message(MY_ID, f"📥 𝗦𝗼𝗹𝗶𝗰𝗶𝘁𝘂𝗱: {user_id}\n`/usuarioaceptado{user_id}`")

async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    user_id = update.effective_user.id
    text = update.message.text or update.message.caption or ""
    config = get_config()

    if re.search(r"(http://|https://|t\.me/|\.com)", text.lower()) and user_id != MY_ID:
        return await update.message.reply_text("🚫 𝗡𝗼 𝘀𝗲 𝗽𝗲𝗿𝗺𝗶𝘁𝗲𝗻 𝗲𝗻𝗹𝗮𝗰𝗲𝘀.")

    if text == ADMIN_PASSWORD and user_id == MY_ID:
        return await update.message.reply_text("🔑 **𝗣𝗔𝗡𝗘𝗟 𝗔𝗗𝗠𝗜𝗡**\n/reset | /mensaje | /stop | /revocar | /nuevapass", parse_mode="Markdown")

    if text == config["auto_pass"] and config["pass_active"]:
        users_col.update_one({"user_id": user_id}, {"$set": {"status": "accepted", "aportes": 0, "last_reset": str(datetime.date.today())}})
        return await update.message.reply_text("✅ ¡𝗔𝗰𝗰𝗲𝘀𝗼 𝗰𝗼𝗻𝗰𝗲𝗱𝗶𝗱𝗼!")

    user = users_col.find_one({"user_id": user_id})
    if not user or user.get("status") == "banned": return

    if user_id == MY_ID:
        if text == "/mensaje":
            context.user_data['wait_msg'] = True
            return await update.message.reply_text("📢 **𝗠𝗢𝗗𝗢 𝗗𝗜𝗙𝗨𝗦𝗜𝗢́𝗡 𝗔𝗖𝗧𝗜𝗩𝗔𝗗𝗢**\n𝗘𝗻𝘃𝗶́𝗲 𝗲𝗹 𝗺𝗲𝗻𝘀𝗮𝗷𝗲 𝗮𝗵𝗼𝗿𝗮.", parse_mode="Markdown")
        if context.user_data.get('wait_msg'):
            context.user_data['wait_msg'] = False
            for t in users_col.find({"status": "accepted"}):
                if t["user_id"] == MY_ID: continue
                try: await update.message.copy(t["user_id"])
                except: pass
            return await update.message.reply_text("🚀 𝗗𝗶𝗳𝘂𝘀𝗶𝗼́𝗻 𝗰𝗼𝗺𝗽𝗹𝗲𝘁𝗮𝗱𝗮.")

    # REENVÍO CON LÓGICA DE ÁLBUMES
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
                return await update.message.reply_text("❌ 𝗿𝗲𝗽𝗲𝘁𝗶𝗱𝗼")
            files_col.insert_one({"file_id": file_id})
            users_col.update_one({"user_id": user_id}, {"$inc": {"aportes": 1}})

            # Si es parte de un álbum (Media Group)
            mg_id = update.message.media_group_id
            if mg_id:
                async with lock:
                    if mg_id not in ALBUMES_COLA:
                        ALBUMES_COLA[mg_id] = {'sender_id': user_id, 'media': []}
                        asyncio.create_task(procesar_y_enviar_album(context, mg_id))
                    ALBUMES_COLA[mg_id]['media'].append(media_obj)
                return # IMPORTANTE: Detenemos el flujo aquí para que no se envíe individualmente

        # Reenvío de mensajes individuales (texto o multimedia suelta)
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

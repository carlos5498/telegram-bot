import os
import logging
import threading
import datetime
import asyncio
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

# Constante de acceso al panel
ADMIN_PASSWORD = "Carlos13mar"

try:
    client = MongoClient(MONGO_URI)
    db = client['bot_anonimo']
    users_col = db['usuarios']
    files_col = db['archivos_vistos']
    config_col = db['configuracion']
    print("✅ Conexión a MongoDB exitosa")
except Exception as e:
    print(f"❌ Error MongoDB: {e}")

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

def get_config():
    config = config_col.find_one({"key": "global_config"})
    if not config:
        # Configuración inicial por defecto
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

# --- MANEJADORES ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        users_col.insert_one({
            "user_id": user_id,
            "status": "pending",
            "aportes": 0,
            "last_reset": str(datetime.date.today())
        })
    
    bienvenida = (
        "¡𝗕𝗶𝗲𝗻𝘃𝗲𝗻𝗶𝗱𝗼! 𝗘𝘀𝘁𝗲 𝗲𝘀 𝘂𝗻 𝗯𝗼𝘁 𝗯𝗲𝘁𝗮 𝗽𝗮𝗿𝗮 𝗲𝗻𝘃𝗶𝗮𝗿 𝗺𝗲𝗻𝘀𝗮𝗷𝗲𝘀 𝗲 𝗶𝗻𝘁𝗲𝗿𝗰𝗮𝗺𝗯𝗶𝗮𝗿 𝗰𝗼𝗻𝘁𝗲𝗻𝗶𝗱𝗼.\n\n"
        "𝗣𝗮𝗿𝗮 𝘂𝘀𝗮𝗿 𝗲𝗹 𝗯𝗼𝘁 𝗱𝗲𝗯𝗲𝘀 𝘀𝗲𝗿 𝗮𝗰𝗲𝗽𝘁𝗮𝗱𝗼:\n"
        "• 𝗘𝗻𝘃𝗶́𝗮 𝟭𝟬𝟬 𝗺𝘂𝗹𝘁𝗶𝗺𝗲𝗱𝗶𝗮 𝗽𝗮𝗿𝗮 𝘀𝗲𝗿 𝗮𝗰𝗲𝗽𝘁𝗮𝗱𝗼.\n"
        "• 𝗜𝗻𝗴𝗿𝗲𝘀𝗮 𝘂𝗻𝗮 𝗰𝗼𝗻𝘁𝗿𝗮𝘀𝗲𝗻̃𝗮 𝗱𝗲 𝗮𝗰𝗰𝗲𝘀𝗼 𝘀𝗶 𝘁𝗶𝗲𝗻𝗲𝘀 𝘂𝗻𝗮.\n"
        "• 𝗨𝘀𝗮 /solicitar 𝗽𝗮𝗿𝗮 𝗮𝘃𝗶𝘀𝗮𝗿 𝗮𝗹 𝗮𝗱𝗺𝗶𝗻𝗶𝘀𝘁𝗿𝗮𝗱𝗼𝗿."
    )
    await update.message.reply_text(bienvenida)

async def solicitar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = update.effective_user
    await update.message.reply_text("¡𝗦𝗼𝗹𝗶𝗰𝗶𝘁𝘂𝗱 𝗲𝗻𝘃𝗶𝗮𝗱𝗮! 𝗥𝗲𝘃𝗶𝘀𝗮 𝗹𝗮𝘀 𝗿𝗲𝗴𝗹𝗮𝘀 𝗳𝗶𝗷𝗮𝗱𝗮𝘀.")
    
    reglas = "🚫 𝗡𝗼 𝗴𝗮𝘆/𝗴𝗼𝗿𝗲/+𝟭𝟴\n🟢 𝟭𝟬 𝗮𝗽𝗼𝗿𝘁𝗲𝘀 𝗱𝗶𝗮𝗿𝗶𝗼𝘀\n\n• /usuarios | /aportes"
    msg_reglas = await update.message.reply_text(reglas)
    try: await context.bot.pin_chat_message(chat_id=user_id, message_id=msg_reglas.message_id)
    except: pass
    
    mensaje_admin = (
        f"📥 𝗦𝗢𝗟𝗜𝗖𝗜𝗧𝗨𝗗: {user_data.full_name}\n"
        f"🆔 ID: `{user_id}`\n"
        f"𝗖𝗼𝗺𝗮𝗻𝗱𝗼𝘀: `/usuarioaceptado{user_id}`"
    )
    await context.bot.send_message(MY_ID, mensaje_admin, parse_mode="Markdown")

async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    user_id = update.effective_user.id
    text = update.message.text
    config = get_config()

    # --- ACCESO PANEL ADMIN ---
    if text == ADMIN_PASSWORD and user_id == MY_ID:
        panel = (
            "🔑 **PANEL ADMIN**\n"
            "/reset - Limpiar repetidos\n"
            "/mensaje - Enviar aviso global\n"
            "/stop - Pausar/Reanudar bot\n"
            "/revocar - Anular contraseña actual\n"
            "/nuevapass [clave] - Cambiar contraseña"
        )
        return await update.message.reply_text(panel, parse_mode="Markdown")

    # --- LÓGICA DE CONTRASEÑA DE USUARIO ---
    if text == config["auto_pass"] and config["pass_active"]:
        users_col.update_one({"user_id": user_id}, {"$set": {"status": "accepted"}})
        return await update.message.reply_text("✅ ¡Acceso concedido! Ahora estás aceptado.")

    user = get_user(user_id)
    if not user: return

    # --- COMANDOS EXCLUSIVOS ADMIN ---
    if user_id == MY_ID:
        if text == "/reset":
            files_col.delete_many({})
            return await update.message.reply_text("✅ Duplicados reseteados.")
        
        if text == "/stop":
            new_state = not config["paused"]
            config_col.update_one({"key": "global_config"}, {"$set": {"paused": new_state}})
            aviso = "🛑 **BOT EN MANTENIMIENTO**" if new_state else "✅ **BOT ACTIVO**"
            for t in users_col.find({"status": "accepted"}):
                try: await context.bot.send_message(t["user_id"], aviso, parse_mode="Markdown")
                except: pass
            return await update.message.reply_text(f"Pausa: {new_state}")

        if text == "/revocar":
            config_col.update_one({"key": "global_config"}, {"$set": {"pass_active": False}})
            return await update.message.reply_text("🚫 Contraseña revocada. Nadie nuevo puede entrar con ella.")

        if text and text.startswith("/nuevapass "):
            nueva = text.split("/nuevapass ")[1].strip()
            config_col.update_one({"key": "global_config"}, {"$set": {"auto_pass": nueva, "pass_active": True}})
            return await update.message.reply_text(f"✅ Nueva contraseña establecida: `{nueva}`", parse_mode="Markdown")

        if text == "/mensaje":
            context.user_data['wait_msg'] = True
            return await update.message.reply_text("Envié el mensaje global ahora:")

        if context.user_data.get('wait_msg'):
            context.user_data['wait_msg'] = False
            for t in users_col.find({"status": "accepted"}):
                try: await update.message.copy(t["user_id"])
                except: pass
            return await update.message.reply_text("✅ Mensaje global enviado.")

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

    # --- LÓGICA DE USUARIOS ---
    if config["paused"] and user_id != MY_ID: return

    if user["status"] == "pending":
        if update.message.photo or update.message.video:
            users_col.update_one({"user_id": user_id}, {"$inc": {"aportes": 1}})
        return

    if user["status"] == "accepted":
        await check_daily_reset(user_id, user)
        file_id = None
        if update.message.photo: file_id = update.message.photo[-1].file_unique_id
        elif update.message.video: file_id = update.message.video.file_unique_id

        if file_id:
            if files_col.find_one({"file_id": file_id}):
                return await update.message.reply_text("𝘃𝗶𝗱𝗲𝗼 𝗿𝗲𝗽𝗲𝘁𝗶𝗱𝗼")
            files_col.insert_one({"file_id": file_id, "user": user_id})
            users_col.update_one({"user_id": user_id}, {"$inc": {"aportes": 1}})

        for target in users_col.find({"status": "accepted"}):
            if target["user_id"] == user_id: continue
            try: await update.message.copy(target["user_id"])
            except: pass

async def commands_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if get_config()["paused"]: return
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user: return
    
    if "/usuarios" in update.message.text:
        count = users_col.count_documents({"status": "accepted"})
        await update.message.reply_text(f"𝗨𝘀𝘂𝗮𝗿𝗶𝗼𝘀 𝗮𝗰𝘁𝗶𝘃𝗼𝘀: {count}")
    elif "/aportes" in update.message.text:
        ap = await check_daily_reset(user_id, user)
        await update.message.reply_text(f"𝗣𝗿𝗼𝗴𝗿𝗲𝘀𝗼 𝗵𝗼𝘆: {ap}/10")

def main():
    threading.Thread(target=run_web_server, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("solicitar", solicitar))
    app.add_handler(CommandHandler(["usuarios", "aportes"], commands_user))
    app.add_handler(MessageHandler(filters.ALL, handle_broadcast))
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()

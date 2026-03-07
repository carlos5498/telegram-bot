import os
import logging
import threading
import datetime
import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
from pymongo import MongoClient
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- CONFIGURACIÓN ---
logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("TOKEN")
MY_ID = int(os.getenv("MY_ID", "0"))
MONGO_URI = os.getenv("MONGO_URI")

# Constantes de seguridad
ADMIN_PASSWORD = "Carlos13mar"
AUTO_ACCEPT_PASSWORD = "planpa54"

try:
    client = MongoClient(MONGO_URI)
    db = client['bot_anonimo']
    users_col = db['usuarios']
    files_col = db['archivos_vistos']
    # Colección para configuraciones globales (pausa, contraseñas, etc)
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

def is_bot_paused():
    config = config_col.find_one({"key": "bot_status"})
    return config.get("paused", False) if config else False

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
        "¡𝗕𝗶𝗲𝗻𝘃𝗲𝗻𝗶𝗱𝗼! 𝗘𝘀𝘁𝗲 𝗲𝘀 𝘂𝗻 𝗯𝗼𝘁 𝗯𝗲𝘁𝗮 𝗽𝗮𝗿𝗮 𝗲𝗻𝘃𝗶𝗮𝗿 𝗺𝗲𝗻𝘀𝗮𝗷𝗲𝘀 𝗲 𝗶𝗻𝘁𝗲𝗿𝗰𝗮𝗺𝗯𝗶𝗮𝗿 𝗰𝗼𝗻𝘁𝗲𝗻𝗶𝗱𝗼 𝗱𝗲 𝗺𝗮𝗻𝗲𝗿𝗮 𝗮𝗻𝗼́𝗻𝗶𝗺𝗮.\n\n"
        "𝗣𝗮𝗿𝗮 𝗽𝗼𝗱𝗲𝗿 𝘂𝘀𝗮𝗿 𝗲𝗹 𝗯𝗼𝘁 𝗱𝗲𝗯𝗲𝘀 𝘀𝗲𝗿 𝗮𝗰𝗲𝗽𝘁𝗮𝗱𝗼 𝗽𝗼𝗿 𝘂𝗻 𝗮𝗱𝗺𝗶𝗻𝗶𝘀𝘁𝗿𝗮𝗱𝗼𝗿.\n\n"
        "• 𝗘𝗻𝘃𝗶́𝗮 𝟭𝟬𝟬 𝗺𝘂𝗹𝘁𝗶𝗺𝗲𝗱𝗶𝗮 (𝗳𝗼𝘁𝗼𝘀/𝘃𝗶𝗱𝗲𝗼𝘀) 𝗱𝗲 𝗰𝗼𝗻𝘁𝗲𝗻𝗶𝗱𝗼 𝗽𝗮𝗿𝗮 𝘀𝗲𝗿 𝗮𝗰𝗲𝗽𝘁𝗮𝗱𝗼.\n"
        "• 𝗢 𝗶𝗻𝗴𝗿𝗲𝘀𝗮 𝗹𝗮 𝗰𝗼𝗻𝘁𝗿𝗮𝘀𝗲𝗻̃𝗮 𝗱𝗲 𝗮𝗰𝗰𝗲𝘀𝗼 𝗱𝗶𝗿𝗲𝗰𝘁𝗼.\n"
        "• 𝗟𝘂𝗲𝗴𝗼 𝘂𝘀𝗮 /solicitar 𝗽𝗮𝗿𝗮 𝗽𝗲𝗱𝗶𝗿 𝗮𝗰𝗰𝗲𝘀𝗼 𝗮 𝘂𝗻 𝗮𝗱𝗺𝗶𝗻𝗶𝘀𝘁𝗿𝗮𝗱𝗼𝗿."
    )
    await update.message.reply_text(bienvenida)

async def solicitar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = update.effective_user
    
    await update.message.reply_text("¡𝗛𝗮𝘀 𝘀𝗼𝗹𝗶𝗰𝗶𝘁𝗮𝗱𝗼 𝗮𝗰𝗰𝗲𝘀𝗼! 𝗦𝗲 𝘁𝗲 𝗻𝗼𝘁𝗶𝗳𝗶𝗰𝗮𝗿𝗮́ 𝗰𝘂𝗮𝗻𝗱𝗼 𝘀𝗲𝗮𝘀 𝗮𝗰𝗲𝗽𝘁𝗮𝗱𝗼.")
    
    reglas = (
        f"𝗠𝗶𝗲𝗻𝘁𝗿𝗮𝘀 𝗲𝘀𝗽𝗲𝗿𝗮𝘀 𝗟𝗲𝗲 𝗹𝗮𝘀 𝗿𝗲𝗴𝗹𝗮𝘀:\n\n"
        f"🚫 𝗡𝗼 𝗴𝗮𝘆/𝗴𝗼𝗿𝗲/+𝟭𝟴\n"
        f"🟢 𝟭𝟬 𝗮𝗽𝗼𝗿𝘁𝗲𝘀 𝗱𝗶𝗮𝗿𝗶𝗼𝘀\n\n"
        f"• /usuarios: 𝗨𝘀𝘂𝗮𝗿𝗶𝗼𝘀 𝗮𝗰𝘁𝗶𝘃𝗼𝘀\n"
        f"• /aportes: 𝗧𝘂 𝗽𝗿𝗼𝗴𝗿𝗲𝘀𝗼 𝗱𝗶𝗮𝗿𝗶𝗼"
    )
    msg_reglas = await update.message.reply_text(reglas)
    try: await context.bot.pin_chat_message(chat_id=user_id, message_id=msg_reglas.message_id)
    except: pass
    
    mensaje_admin = (
        f"📥 𝗡𝗨𝗘𝗩𝗔 𝗦𝗢𝗟𝗜𝗖𝗜𝗧𝗨𝗗\n\n"
        f"🆔 𝗜𝗗: `{user_id}`\n"
        f"👤 𝗡𝗼𝗺𝗯𝗿𝗲: {user_data.full_name}\n"
        f"🔗 𝗨𝘀𝘂𝗮𝗿𝗶𝗼: @{user_data.username if user_data.username else 'N/A'}\n\n"
        f"𝗖𝗼𝗺𝗮𝗻𝗱𝗼𝘀:\n`/usuarioaceptado{user_id}`\n`/usuariobaneado{user_id}`"
    )
    await context.bot.send_message(MY_ID, mensaje_admin, parse_mode="Markdown")

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Verificar si el mensaje es la contraseña de admin
    if update.message.text == ADMIN_PASSWORD and update.effective_user.id == MY_ID:
        panel = (
            "🔑 **PANEL DE CONTROL ADMINISTRADOR**\n\n"
            "/reset - Limpiar lista de duplicados\n"
            "/mensaje - Enviar aviso global (Siguiente mensaje)\n"
            "/stop - Pausar/Reanudar el bot\n"
            "/revocar - Anular contraseña de acceso directo"
        )
        await update.message.reply_text(panel, parse_mode="Markdown")

async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    user_id = update.effective_user.id
    text = update.message.text
    
    # --- LÓGICA DE CONTRASEÑAS ---
    if text == ADMIN_PASSWORD:
        await admin_panel(update, context)
        return

    # Contraseña de acceso directo (planpa54)
    current_auto_pass = config_col.find_one({"key": "auto_pass"})
    is_pass_revoked = current_auto_pass.get("revoked", False) if current_auto_pass else False
    
    if text == AUTO_ACCEPT_PASSWORD and not is_pass_revoked:
        users_col.update_one({"user_id": user_id}, {"$set": {"status": "accepted"}})
        await update.message.reply_text("✅ ¡Contraseña correcta! Ahora eres un usuario aceptado.")
        return

    user = get_user(user_id)
    if not user: return

    # --- LÓGICA DE ADMIN COMANDOS ---
    if user_id == MY_ID:
        if text == "/reset":
            files_col.delete_many({})
            return await update.message.reply_text("✅ Lista de duplicados reseteada.")
        
        if text == "/stop":
            paused = is_bot_paused()
            new_status = not paused
            config_col.update_one({"key": "bot_status"}, {"$set": {"paused": new_status}}, upsert=True)
            status_msg = "🛑 **EL BOT HA SIDO PAUSADO POR MANTENIMIENTO**" if new_status else "✅ **EL BOT ESTÁ ACTIVO NUEVAMENTE**"
            
            for t in users_col.find({"status": "accepted"}):
                try: await context.bot.send_message(t["user_id"], status_msg, parse_mode="Markdown")
                except: pass
            return await update.message.reply_text(f"Estado del bot cambiado. Pausado: {new_status}")

        if text == "/revocar":
            config_col.update_one({"key": "auto_pass"}, {"$set": {"revoked": True}}, upsert=True)
            return await update.message.reply_text("🚫 Contraseña de acceso directo anulada. Pide una nueva al desarrollador.")

        if text == "/mensaje":
            context.user_data['waiting_global_msg'] = True
            return await update.message.reply_text("Escribe el mensaje (o envía foto/video) que quieres difundir a todos:")

        if context.user_data.get('waiting_global_msg'):
            context.user_data['waiting_global_msg'] = False
            count = 0
            for t in users_col.find({"status": "accepted"}):
                try:
                    await update.message.copy(t["user_id"])
                    count += 1
                except: pass
            return await update.message.reply_text(f"✅ Mensaje enviado a {count} usuarios.")

        if text and "/usuario" in text:
            # Lógica de aceptar/banear del admin (del código anterior)
            try:
                target_id = int(re.search(r'\d+', text).group())
                if "aceptado" in text:
                    users_col.update_one({"user_id": target_id}, {"$set": {"status": "accepted"}})
                    await context.bot.send_message(target_id, "¡𝗙𝗲𝗹𝗶𝗰𝗶𝗱𝗮𝗱𝗲𝘀 𝗵𝗮𝘇 𝘀𝗶𝗱𝗼 𝗮𝗰𝗲𝗽𝘁𝗮𝗱𝗼!")
                elif "baneado" in text:
                    users_col.update_one({"user_id": target_id}, {"$set": {"status": "banned"}})
                await update.message.delete()
            except: pass
            return

    # --- LÓGICA DE USUARIOS ---
    if is_bot_paused() and user_id != MY_ID:
        return # No procesar nada si está pausado

    if user["status"] == "pending":
        if update.message.photo or update.message.video:
            users_col.update_one({"user_id": user_id}, {"$inc": {"aportes": 1}})
        return

    if user["status"] == "accepted":
        await check_daily_reset(user_id, user)
        # Filtro duplicados
        file_id = None
        if update.message.photo: file_id = update.message.photo[-1].file_unique_id
        elif update.message.video: file_id = update.message.video.file_unique_id

        if file_id:
            if files_col.find_one({"file_id": file_id}):
                return await update.message.reply_text("𝘃𝗶𝗱𝗲𝗼 𝗿𝗲𝗽𝗲𝘁𝗶𝗱𝗼")
            files_col.insert_one({"file_id": file_id, "user": user_id})
            users_col.update_one({"user_id": user_id}, {"$inc": {"aportes": 1}})

        # Broadcast a otros
        for target in users_col.find({"status": "accepted"}):
            if target["user_id"] == user_id: continue
            try: await update.message.copy(target["user_id"])
            except: pass

async def commands_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_bot_paused(): return
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user: return
    
    text = update.message.text
    if "/usuarios" in text:
        count = users_col.count_documents({"status": "accepted"})
        await update.message.reply_text(f"𝗨𝘀𝘂𝗮𝗿𝗶𝗼𝘀 𝗮𝗰𝘁𝗶𝘃𝗼𝘀: {count}")
    elif "/aportes" in text:
        ap = await check_daily_reset(user_id, user)
        objetivo = 100 if user["status"] == "pending" else 10
        await update.message.reply_text(f"𝗧𝘂 𝗽𝗿𝗼𝗴𝗿𝗲𝘀𝗼: {ap}/{objetivo}")

def main():
    threading.Thread(target=run_web_server, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("solicitar", solicitar))
    app.add_handler(CommandHandler(["usuarios", "aportes"], commands_user))
    app.add_handler(MessageHandler(filters.ALL, handle_broadcast))
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    import re
    main()

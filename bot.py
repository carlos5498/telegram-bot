import os
import logging
import threading
import random
import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pymongo import MongoClient
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- CONFIGURACIÓN ---
logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("TOKEN")
MY_ID = int(os.getenv("MY_ID", "0"))
MONGO_URI = os.getenv("MONGO_URI")

# Conexión a MongoDB
client = MongoClient(MONGO_URI)
db = client['bot_anonimo']
users_col = db['usuarios']
files_col = db['archivos_vistos']

ADJETIVOS = ["Bravo", "Veloz", "Oscuro", "Místico", "Feroz", "Silencioso", "Letal"]
ANIMALES = ["Lobo", "Zorro", "Halcón", "Tigre", "Puma", "Serpiente", "Águila"]

# --- SERVIDOR WEB (Render) ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Bot Operativo con MongoDB")

def run_web_server():
    server = HTTPServer(('0.0.0.0', int(os.environ.get("PORT", 8080))), SimpleHandler)
    server.serve_forever()

# --- FUNCIONES DE BASE DE DATOS ---
def get_user(user_id):
    return users_col.find_one({"user_id": user_id})

def update_user(user_id, data):
    users_col.update_one({"user_id": user_id}, {"$set": data}, upsert=True)

def generate_anon_name():
    return f"{random.choice(ANIMALES)} {random.choice(ADJETIVOS)} {random.randint(10, 99)}"

# --- LÓGICA DE APORTES ---
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
        new_user = {
            "user_id": user_id,
            "username": update.effective_user.username,
            "name": generate_anon_name(),
            "status": "pending",
            "aportes": 0,
            "last_reset": str(datetime.date.today())
        }
        users_col.insert_one(new_user)
    
    await update.message.reply_text(
        "¡Bienvenido! Este es un bot beta para enviar mensajes e intercambios de manera anónima.\n\n"
        "Envía 100 fotos/videos para ser aceptado. Luego usa /solicitar para pedir acceso."
    )

async def solicitar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    await update.message.reply_text("¡Has solicitado acceso! Se te notificará cuando seas aceptado.")
    await update.message.reply_text(
        f"Reglas:\n🚫 No gay/gore/+18\n🟢 10 aportes diarios\n🟢 Tu nombre: {user['name']}\n"
        "• /user: Tu nombre\n• /usuarios: Activos\n• /aportes: Tu progreso"
    )
    # Notificar al admin con link de comando rápido
    await context.bot.send_message(MY_ID, f"NUEVA SOLICITUD:\nID: `{user_id}`\nNombre: {user['name']}\n\n`/usuarioaceptado{user_id}`\n`/usuariobaneado{user_id}`", parse_mode="Markdown")

async def admin_control(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != MY_ID: return
    text = update.message.text
    await update.message.delete()

    try:
        if "/usuarioaceptado" in text:
            uid = int(text.replace("/usuarioaceptado", ""))
            users_col.update_one({"user_id": uid}, {"$set": {"status": "accepted"}})
            await context.bot.send_message(uid, "¡Felicidades! Has sido aceptado. Comparte libremente siguiendo las reglas.")
        
        elif "/usuariobaneado" in text:
            uid = int(text.replace("/usuariobaneado", ""))
            users_col.update_one({"user_id": uid}, {"$set": {"status": "banned"}})
            await context.bot.send_message(uid, "Has sido vetado del bot por incumplir reglas. No hay retorno.")
    except Exception as e:
        logging.error(f"Error admin: {e}")

async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if not user or user["status"] != "accepted": return
    
    # Reset diario si es necesario
    current_aportes = await check_daily_reset(user_id, user)
    
    file_unique_id = None
    if update.message.photo: file_unique_id = update.message.photo[-1].file_unique_id
    if update.message.video: file_unique_id = update.message.video.file_unique_id

    # Anti-repetidos con MongoDB
    if file_unique_id:
        if files_col.find_one({"file_id": file_unique_id}):
            await update.message.reply_text("Contenido repetido.")
            return
        files_col.insert_one({"file_id": file_unique_id, "user": user_id})
        users_col.update_one({"user_id": user_id}, {"$inc": {"aportes": 1}})

    # Reenvío masivo
    caption = f"Enviado por: {user['name']}"
    accepted_users = users_col.find({"status": "accepted"})
    
    for target in accepted_users:
        if target["user_id"] == user_id: continue
        try:
            if update.message.text:
                await context.bot.send_message(target["user_id"], f"{update.message.text}\n\n— {user['name']}")
            elif update.message.photo:
                await context.bot.send_photo(target["user_id"], update.message.photo[-1].file_id, caption=caption)
            elif update.message.video:
                await context.bot.send_video(target["user_id"], update.message.video.file_id, caption=caption)
        except:
            pass

async def commands_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user: return

    if "/user" in update.message.text:
        await update.message.reply_text(f"Tu nombre anónimo: {user['name']}")
    elif "/usuarios" in update.message.text:
        count = users_col.count_documents({"status": "accepted"})
        await update.message.reply_text(f"Usuarios activos: {count}")
    elif "/aportes" in update.message.text:
        ap = await check_daily_reset(user_id, user)
        faltan = max(0, 10 - ap)
        await update.message.reply_text(f"Aportes hoy: {ap}/10. {'¡Completado!' if faltan == 0 else f'Faltan {faltan}'}")

def main():
    threading.Thread(target=run_web_server, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("solicitar", solicitar))
    app.add_handler(MessageHandler(filters.Regex(r'^/usuario(aceptado|baneado)'), admin_control))
    app.add_handler(CommandHandler(["user", "usuarios", "aportes"], commands_user))
    app.add_handler(MessageHandler((filters.TEXT | filters.PHOTO | filters.VIDEO) & ~filters.COMMAND, handle_broadcast))
    
    app.run_polling()

if __name__ == '__main__':
    main()

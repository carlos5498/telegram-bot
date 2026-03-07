import os
import logging
import threading
import random
import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pymongo import MongoClient
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- LOGS ---
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

# --- SERVIDOR WEB ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Bot Operativo")

def run_web_server():
    server = HTTPServer(('0.0.0.0', int(os.environ.get("PORT", 8080))), SimpleHandler)
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
        new_user = {
            "user_id": user_id,
            "name": generate_anon_name(),
            "status": "pending",
            "aportes": 0,
            "last_reset": str(datetime.date.today())
        }
        users_col.insert_one(new_user)
    
    await update.message.reply_text(
        "¡Bienvenido! Este es un bot beta para enviar mensajes e intercambios de contenido de manera anónima.\n\n"
        "Envía 100 fotos/videos para ser aceptado. Luego usa /solicitar para pedir acceso a un administrador."
    )

async def solicitar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    await update.message.reply_text("¡Has solicitado acceso a un administrador! Se te notificará cuando seas aceptado.")
    
    reglas = (
        f"Mientras esperas Lee las reglas:\n"
        f"🚫 No gay/gore/+18\n"
        f"🟢 10 aportes diarios\n"
        f"🟢 Tu nombre: {user['name']}\n"
        f"• /user: Tu nombre\n"
        f"• /usuarios: Usuarios activos actualmente\n"
        f"• /aportes: Tu progreso diario"
    )
    await update.message.reply_text(reglas)
    
    # Notificar al Admin real (Tú)
    await context.bot.send_message(MY_ID, f"SOLICITUD:\nID: `{user_id}`\nNombre: {user['name']}\n\nComandos para copiar/pegar:\n`/usuarioaceptado{user_id}`\n`/usuariobaneado{user_id}`")

async def admin_control(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Detecta si el mensaje viene de TI o si el BOT se está enviando el mensaje a sí mismo (Telegraph)
    bot_id = context.bot.id
    user_id = update.effective_user.id
    text = update.message.text

    if user_id == MY_ID or user_id == bot_id:
        try:
            if "/usuarioaceptado" in text:
                uid = int(text.replace("/usuarioaceptado", ""))
                users_col.update_one({"user_id": uid}, {"$set": {"status": "accepted"}})
                await update.message.delete() # Borra el comando
                await context.bot.send_message(uid, "Felicidades haz sido aceptado! Comparte contenido libremente, no te olvides de seguir las reglas y de tu aporte diario para no ser baneado!")
            
            elif "/usuariobaneado" in text:
                uid = int(text.replace("/usuariobaneado", ""))
                users_col.update_one({"user_id": uid}, {"$set": {"status": "banned"}})
                await update.message.delete() # Borra el comando
                await context.bot.send_message(uid, "Haz sido betado del bot, por incumplir alguna regla o no haber cumplido con tus aportes diarios, por ahora no hay forma de regresar!")
        except Exception as e:
            logging.error(f"Error en comando admin: {e}")

async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    # Si no está aceptado, no hace nada (no reenvía)
    if not user or user["status"] != "accepted": return
    
    await check_daily_reset(user_id, user)
    
    file_id = None
    if update.message.photo: file_id = update.message.photo[-1].file_unique_id
    elif update.message.video: file_id = update.message.video.file_unique_id

    # Anti-repetidos
    if file_id:
        if files_col.find_one({"file_id": file_id}):
            await update.message.reply_text("video repetido")
            return
        files_col.insert_one({"file_id": file_id, "user": user_id})
        users_col.update_one({"user_id": user_id}, {"$inc": {"aportes": 1}})

    # Reenvío a los demás
    for target in users_col.find({"status": "accepted"}):
        if target["user_id"] == user_id: continue
        try:
            if update.message.text:
                await context.bot.send_message(target["user_id"], f"{update.message.text}\n\n{user['name']}")
            elif update.message.photo:
                await context.bot.send_photo(target["user_id"], update.message.photo[-1].file_id, caption=user['name'])
            elif update.message.video:
                await context.bot.send_video(target["user_id"], update.message.video.file_id, caption=user['name'])
        except: pass

async def commands_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user: return

    if "/user" in update.message.text:
        await update.message.reply_text(f"Tu nombre anónimo es: {user['name']}")
    elif "/usuarios" in update.message.text:
        count = users_col.count_documents({"status": "accepted"})
        await update.message.reply_text(f"Usuarios activos actualmente: {count}")
    elif "/aportes" in update.message.text:
        ap = await check_daily_reset(user_id, user)
        faltan = max(0, 10 - ap)
        status = "Completado ✅" if faltan == 0 else f"Te faltan {faltan} aportes."
        await update.message.reply_text(f"Tu progreso diario: {ap}/10\n{status}")

def main():
    threading.Thread(target=run_web_server, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("solicitar", solicitar))
    
    # Este manejador detecta los comandos de aceptación/baneo enviados por el bot/admin
    app.add_handler(MessageHandler(filters.Regex(r'^/usuario(aceptado|baneado)'), admin_control))
    
    app.add_handler(CommandHandler(["user", "usuarios", "aportes"], commands_user))
    app.add_handler(MessageHandler((filters.TEXT | filters.PHOTO | filters.VIDEO) & ~filters.COMMAND, handle_broadcast))
    
    app.run_polling()

if __name__ == '__main__':
    main()

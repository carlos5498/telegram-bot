import os
import json
import logging
import threading
import random
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- CONFIGURACIÓN DE LOGS ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- SERVIDOR WEB (Para que Render no apague el bot) ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is Running")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), SimpleHandler)
    server.serve_forever()

# --- PERSISTENCIA DE DATOS ---
DATA_FILE = "datos_bot.json"

def cargar_datos():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        except:
            return {"grupos": [], "media": []}
    return {"grupos": [], "media": []}

def guardar_datos(datos_dict):
    with open(DATA_FILE, "w") as f:
        json.dump(datos_dict, f)

# Cargar datos al iniciar
datos = cargar_datos()

# --- SEGURIDAD ---
# Obtener tu ID desde las variables de Render
MY_ID = int(os.getenv("MY_ID", 0))

# --- FUNCIONES DEL BOT ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != MY_ID:
        return
    await update.message.reply_text("¡Hola Jefe! Envíame fotos/videos por privado. Usa /on en los grupos para empezar el bombardeo cada minuto.")

async def collect_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Solo acepta archivos enviados por ti en privado
    if update.message.from_user.id != MY_ID or update.message.chat.type != 'private':
        return

    file_id = None
    m_type = ""
    
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        m_type = "photo"
    elif update.message.video:
        file_id = update.message.video.file_id
        m_type = "video"
        
    if file_id:
        datos["media"].append({"type": m_type, "id": file_id})
        guardar_datos(datos)
        await update.message.reply_text(f"✅ Archivo guardado. Total en la lista: {len(datos['media'])}")

async def on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != MY_ID:
        return
    
    chat_id = update.effective_chat.id
    if chat_id not in datos["grupos"]:
        datos["grupos"].append(chat_id)
        guardar_datos(datos)
    await update.message.reply_text("🚀 Envío automático ACTIVADO (1 archivo aleatorio por minuto).")

async def off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != MY_ID:
        return
    
    chat_id = update.effective_chat.id
    if chat_id in datos["grupos"]:
        datos["grupos"].remove(chat_id)
        guardar_datos(datos)
    await update.message.reply_text("🛑 Envío automático DESACTIVADO.")

async def limpiar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != MY_ID:
        return
    datos["media"] = []
    guardar_datos(datos)
    await update.message.reply_text("🗑️ Lista de medios vaciada.")

# --- TAREA PROGRAMADA ---
async def send_media_task(context: ContextTypes.DEFAULT_TYPE):
    if not datos["media"] or not datos["grupos"]:
        return

    # Selecciona uno al azar de la lista
    media = random.choice(datos["media"]) 
    
    for chat_id in datos["grupos"]:
        try:
            if media['type'] == 'photo':
                await context.bot.send_photo(chat_id=chat_id, photo=media['id'])
            else:
                await context.bot.send_video(chat_id=chat_id, video=media['id'])
        except Exception as e:
            logging.error(f"Error enviando a {chat_id}: {e}")

# --- MAIN ---
def main():
    TOKEN = os.getenv("TOKEN")
    if not TOKEN:
        print("Error: No se encontró la variable TOKEN")
        return

    # Iniciar servidor web para Render en un hilo secundario
    threading.Thread(target=run_web_server, daemon=True).start()
    
    # Crear la aplicación
    app = Application.builder().token(TOKEN).build()

    # Manejadores de comandos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("on", on))
    app.add_handler(CommandHandler("off", off))
    app.add_handler(CommandHandler("limpiar", limpiar))
    
    # Manejador de fotos y videos
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, collect_media))

    # Configurar el JobQueue para cada 60 segundos
    if app.job_queue:
        app.job_queue.run_repeating(send_media_task, interval=60, first=10)

    print("Bot iniciado...")
    app.run_polling()

if __name__ == '__main__':
    main()

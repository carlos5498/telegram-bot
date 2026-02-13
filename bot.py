
import os
import json
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Configuración de logs para ver errores en la consola de Koyeb
logging.basicConfig(level=logging.INFO)

# --- PERSISTENCIA SIMPLE ---
DATA_FILE = "datos_bot.json"

def cargar_datos():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {"grupos": [], "media": []}

def guardar_datos(datos):
    with open(DATA_FILE, "w") as f:
        json.dump(datos, f)

datos = cargar_datos()

# --- FUNCIONES DEL BOT ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Bot activo! Envíame fotos/videos por privado y usa /on en grupos.")

async def collect_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type == 'private':
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
            await update.message.reply_text(f"✅ Guardado. Total: {len(datos['media'])}")

async def on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in datos["grupos"]:
        datos["grupos"].append(chat_id)
        guardar_datos(datos)
    await update.message.reply_text("🚀 Envío activado: 1 mensaje por minuto.")

async def off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in datos["grupos"]:
        datos["grupos"].remove(chat_id)
        guardar_datos(datos)
    await update.message.reply_text("🛑 Envío desactivado.")

async def send_media_task(context: ContextTypes.DEFAULT_TYPE):
    if not datos["media"] or not datos["grupos"]:
        return

    # Enviamos el último archivo recibido (puedes cambiar la lógica aquí)
    media = datos["media"][-1] 
    
    for chat_id in datos["grupos"]:
        try:
            if media['type'] == 'photo':
                await context.bot.send_photo(chat_id=chat_id, photo=media['id'])
            else:
                await context.bot.send_video(chat_id=chat_id, video=media['id'])
        except Exception as e:
            logging.error(f"Error en {chat_id}: {e}")

def main():
    TOKEN = os.getenv("TOKEN")
    
    # Construimos la aplicación
    app = Application.builder().token(TOKEN).build()

    # --- REGISTRO DE MANEJADORES ---
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("on", on))
    app.add_handler(CommandHandler("off", off))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, collect_media))

    # --- PROGRAMADOR ---
    # Verificamos que job_queue exista para evitar el AttributeError
    if app.job_queue:
        app.job_queue.run_repeating(send_media_task, interval=60, first=10)
    else:
        logging.error("No se pudo iniciar JobQueue. Revisa los requirements.")

    # Iniciamos el bot
    app.run_polling()

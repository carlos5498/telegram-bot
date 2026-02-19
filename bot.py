import os
import logging
import threading
import random
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from pymongo import MongoClient

# --- CONFIGURACIÓN ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
MY_ID = int(os.getenv("MY_ID", 0))
MONGO_URL = os.getenv("MONGO_URL")
TOKEN = os.getenv("TOKEN")

# --- CONEXIÓN A MONGODB ---
client = MongoClient(MONGO_URL)
db = client['bot_bombardeo_db']
col_media = db['lista_media']
col_config = db['config_grupos']
col_enviados = db['registro_enviados']

# --- SERVIDOR WEB (Evita el apagado en Render) ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Bot Bombardeo Activo")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    HTTPServer(('0.0.0.0', port), SimpleHandler).serve_forever()

# --- INTERFAZ DE USUARIO (BOTONES) ---
def get_main_keyboard(chat_id):
    conf = col_config.find_one({"chat_id": chat_id}) or {"cant": 1, "time": 1, "repeat": True}
    cant = conf.get("cant", 1)
    time = conf.get("time", 1)
    rep = "✅" if conf.get("repeat", True) else "❌"
    
    keyboard = [
        [InlineKeyboardButton(f"Cantidad: {cant} archivos", callback_data=f"menu_cant_{chat_id}")],
        [InlineKeyboardButton(f"Frecuencia: {time} min", callback_data=f"menu_time_{chat_id}")],
        [InlineKeyboardButton(f"Repetir contenido: {rep}", callback_data=f"toggle_rep_{chat_id}")],
        [InlineKeyboardButton("🚀 INICIAR / ACTUALIZAR", callback_data=f"start_bomb_{chat_id}")],
        [InlineKeyboardButton("🛑 DETENER", callback_data=f"stop_bomb_{chat_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_options_keyboard(tipo, chat_id):
    if tipo == "cant":
        opts = [1, 2, 5, 10, 20, 50]
        btn_data = "setcant"
    else:
        opts = [1, 2, 5, 10, 30, 60, 360] 
        btn_data = "settime"
    
    keyboard = []
    row = []
    for o in opts:
        label = f"{o}m" if tipo == "time" and o < 60 else (f"{o//60}h" if tipo == "time" else o)
        row.append(InlineKeyboardButton(str(label), callback_data=f"{btn_data}_{o}_{chat_id}"))
        if len(row) == 3:
            keyboard.append(row); row = []
    keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data=f"back_{chat_id}")])
    return InlineKeyboardMarkup(keyboard)

# --- TAREA DE ENVÍO AUTOMÁTICO (JOB) ---
async def send_media_job(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    conf = col_config.find_one({"chat_id": chat_id})
    all_media = list(col_media.find())
    
    if not conf or not all_media: return

    # Filtrar si la opción de repetir está en FALSO (X)
    disponibles = all_media
    if not conf.get("repeat", True):
        registro = col_enviados.find_one({"chat_id": chat_id}) or {"ids": []}
        disponibles = [m for m in all_media if m["unique_id"] not in registro["ids"]]

    if not disponibles:
        # Notificar al dueño por privado si se agota el material
        await context.bot.send_message(MY_ID, f"⚠️ Se terminó el contenido nuevo para el grupo `{chat_id}`. Bombardeo pausado.")
        context.job.schedule_removal()
        return

    cantidad = min(conf.get("cant", 1), len(disponibles))
    seleccionados = random.sample(disponibles, cantidad)

    for media in seleccionados:
        try:
            if media['type'] == 'photo':
                await context.bot.send_photo(chat_id, media['id'])
            else:
                await context.bot.send_video(chat_id, media['id'])
            
            # Registrar como enviado si no se permite repetir
            if not conf.get("repeat", True):
                col_enviados.update_one({"chat_id": chat_id}, {"$push": {"ids": media["unique_id"]}}, upsert=True)
        except Exception as e:
            logging.error(f"Error enviando media: {e}")

# --- MANEJADORES DE COMANDOS Y BOTONES ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == MY_ID:
        await update.message.reply_text("Panel de Control (MongoDB Cloud):", reply_markup=get_main_keyboard(update.effective_chat.id))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    chat_id = int(data.split("_")[-1])
    await query.answer()

    if "menu_cant" in data:
        await query.edit_message_reply_markup(get_options_keyboard("cant", chat_id))
    elif "menu_time" in data:
        await query.edit_message_reply_markup(get_options_keyboard("time", chat_id))
    elif "setcant" in data:
        val = int(data.split("_")[1])
        col_config.update_one({"chat_id": chat_id}, {"$set": {"cant": val}}, upsert=True)
        await query.edit_message_reply_markup(get_main_keyboard(chat_id))
    elif "settime" in data:
        val = int(data.split("_")[1])
        col_config.update_one({"chat_id": chat_id}, {"$set": {"time": val}}, upsert=True)
        await query.edit_message_reply_markup(get_main_keyboard(chat_id))
    elif "toggle_rep" in data:
        curr = col_config.find_one({"chat_id": chat_id}) or {"repeat": True}
        new_val = not curr.get("repeat", True)
        col_config.update_one({"chat_id": chat_id}, {"$set": {"repeat": new_val}}, upsert=True)
        # Si se activa repetir, limpiamos el historial de enviados para ese grupo
        if new_val: col_enviados.delete_one({"chat_id": chat_id})
        await query.edit_message_reply_markup(get_main_keyboard(chat_id))
    elif "back" in data:
        await query.edit_message_reply_markup(get_main_keyboard(chat_id))
    elif "start_bomb" in data:
        conf = col_config.find_one({"chat_id": chat_id}) or {"time": 1}
        # Eliminar cualquier tarea previa para este grupo antes de iniciar la nueva
        for j in context.job_queue.get_jobs_by_name(str(chat_id)): j.schedule_removal()
        context.job_queue.run_repeating(send_media_job, interval=conf.get("time", 1)*60, first=5, chat_id=chat_id, name=str(chat_id))
        await query.edit_message_text("🚀 Bombardeo iniciado o actualizado correctamente.")
    elif "stop_bomb" in data:
        for j in context.job_queue.get_jobs_by_name(str(chat_id)): j.schedule_removal()
        await query.edit_message_text("🛑 Bombardeo detenido.")

# --- COLECCIÓN DE MEDIA (CON FILTRO ANTI-REPETIDOS) ---
async def collect_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != MY_ID or update.message.chat.type != 'private': return
    
    if update.message.photo:
        archivo = update.message.photo[-1]
        mtype = "photo"
    elif update.message.video:
        archivo = update.message.video
        mtype = "video"
    else: return

    fid = archivo.file_id
    f_unique_id = archivo.file_unique_id

    # Verificar si ya existe en la base de datos
    existe = col_media.find_one({"unique_id": f_unique_id})
    if existe:
        await update.message.reply_text("⚠️ Este archivo ya lo tengo guardado.")
    else:
        col_media.update_one(
            {"unique_id": f_unique_id}, 
            {"$set": {"type": mtype, "id": fid, "unique_id": f_unique_id}}, 
            upsert=True
        )
        count = col_media.count_documents({})
        await update.message.reply_text(f"✅ Guardado único. Total en lista: {count}")

async def limpiar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == MY_ID:
        col_media.delete_many({}); col_enviados.delete_many({})
        await update.message.reply_text("🗑️ Memoria de medios vaciada por completo.")

# --- ARRANQUE ---
def main():
    threading.Thread(target=run_web_server, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("limpiar", limpiar))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, collect_media))
    
    print("Bot Bombardeo con Filtro de Duplicados Iniciado...")
    app.run_polling()

if __name__ == '__main__':
    main()
    

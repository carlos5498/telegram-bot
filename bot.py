import os
import logging
import threading
import random
import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from pymongo import MongoClient

# --- CONFIGURACIÓN ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
MY_ID = int(os.getenv("MY_ID", 0))
MONGO_URL = os.getenv("MONGO_URL")
TOKEN = os.getenv("TOKEN")
PASSWORD_CORRECTA = "Carlos13mar"

# --- CONEXIÓN A MONGODB ---
client = MongoClient(MONGO_URL)
db = client['bot_bombardeo_db']
# Usamos colecciones específicas para esta versión y evitar conflictos
col_media = db['lista_media_v2']
col_config = db['config_grupos_v2']
col_enviados = db['registro_enviados_v2']
col_users = db['usuarios_autorizados_v2']

# --- SERVIDOR WEB ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Bot Bombardeo Seguro Activo")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    HTTPServer(('0.0.0.0', port), SimpleHandler).serve_forever()

# --- SEGURIDAD ---
def esta_autorizado(user_id):
    return user_id == MY_ID or col_users.find_one({"user_id": user_id}) is not None

# --- INTERFAZ DE USUARIO ---
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
        [InlineKeyboardButton("🛑 DETENER", callback_data=f"stop_bomb_{chat_id}")],
        [InlineKeyboardButton("☢️ RESET TOTAL", callback_data=f"ask_reset_{chat_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_options_keyboard(tipo, chat_id):
    opts = [1, 2, 5, 10, 20, 50] if tipo == "cant" else [1, 5, 10, 30, 60, 360]
    btn_data = "setcant" if tipo == "cant" else "settime"
    keyboard = []
    row = []
    for o in opts:
        label = f"{o}m" if tipo == "time" and o < 60 else (f"{o//60}h" if tipo == "time" else o)
        row.append(InlineKeyboardButton(str(label), callback_data=f"{btn_data}_{o}_{chat_id}"))
        if len(row) == 3:
            keyboard.append(row); row = []
    keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data=f"back_{chat_id}")])
    return InlineKeyboardMarkup(keyboard)

# --- TAREA DE ENVÍO CON PROTECCIÓN ANTI-BAN ---
async def send_media_job(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    conf = col_config.find_one({"chat_id": chat_id})
    all_media = list(col_media.find())
    
    if not conf or not all_media: return

    disponibles = all_media
    if not conf.get("repeat", True):
        registro = col_enviados.find_one({"chat_id": chat_id}) or {"ids": []}
        disponibles = [m for m in all_media if m["unique_id"] not in registro["ids"]]

    if not disponibles:
        await context.bot.send_message(MY_ID, "⚠️ Contenido agotado. Bombardeo pausado.")
        context.job.schedule_removal()
        return

    cantidad = min(conf.get("cant", 1), len(disponibles))
    seleccionados = random.sample(disponibles, cantidad)

    for index, media in enumerate(seleccionados):
        try:
            if media['type'] == 'photo':
                await context.bot.send_photo(chat_id, media['id'])
            else:
                await context.bot.send_video(chat_id, media['id'])
            
            if not conf.get("repeat", True):
                col_enviados.update_one({"chat_id": chat_id}, {"$push": {"ids": media["unique_id"]}}, upsert=True)
            
            # --- PROTECCIÓN ANTI-BAN ---
            await asyncio.sleep(0.8) # Pausa entre archivos
            if (index + 1) % 10 == 0: await asyncio.sleep(3) # Pausa larga cada 10

        except Exception as e:
            if "Flood control exceeded" in str(e):
                wait = int(str(e).split("retry in ")[1].split(" ")[0])
                await asyncio.sleep(wait + 1)
            logging.error(f"Error: {e}")

# --- MANEJADORES ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if esta_autorizado(user_id):
        await update.message.reply_text("Panel de Control Seguro:", reply_markup=get_main_keyboard(update.effective_chat.id))
    else:
        await update.message.reply_text("🔐 Introduce la contraseña:")

async def check_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if esta_autorizado(user_id): return
    if update.message.text == PASSWORD_CORRECTA:
        col_users.insert_one({"user_id": user_id})
        await update.message.reply_text("✅ Autorizado.", reply_markup=get_main_keyboard(update.effective_chat.id))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    chat_id = int(data.split("_")[-1])
    await query.answer()

    if not esta_autorizado(query.from_user.id): return

    if "menu_cant" in data:
        await query.edit_message_reply_markup(get_options_keyboard("cant", chat_id))
    elif "menu_time" in data:
        await query.edit_message_reply_markup(get_options_keyboard("time", chat_id))
    elif "setcant" in data:
        val = int(data.split("_")[1]); col_config.update_one({"chat_id": chat_id}, {"$set": {"cant": val}}, upsert=True)
        await query.edit_message_reply_markup(get_main_keyboard(chat_id))
    elif "settime" in data:
        val = int(data.split("_")[1]); col_config.update_one({"chat_id": chat_id}, {"$set": {"time": val}}, upsert=True)
        await query.edit_message_reply_markup(get_main_keyboard(chat_id))
    elif "toggle_rep" in data:
        curr = col_config.find_one({"chat_id": chat_id}) or {"repeat": True}
        new_val = not curr.get("repeat", True)
        col_config.update_one({"chat_id": chat_id}, {"$set": {"repeat": new_val}}, upsert=True)
        if new_val: col_enviados.delete_one({"chat_id": chat_id})
        await query.edit_message_reply_markup(get_main_keyboard(chat_id))
    elif "ask_reset" in data:
        await query.edit_message_text("⚠️ ¿BORRAR TODO el contenido de este bot?", 
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ SÍ", callback_data=f"conf_reset_{chat_id}"),
                InlineKeyboardButton("❌ NO", callback_data=f"back_{chat_id}")]]))
    elif "conf_reset" in data:
        col_media.delete_many({}); col_enviados.delete_many({})
        await query.edit_message_text("💥 Memoria vaciada. Sube archivos nuevos.", reply_markup=get_main_keyboard(chat_id))
    elif "back" in data:
        await query.edit_message_reply_markup(get_main_keyboard(chat_id))
    elif "start_bomb" in data:
        conf = col_config.find_one({"chat_id": chat_id}) or {"time": 1}
        for j in context.job_queue.get_jobs_by_name(str(chat_id)): j.schedule_removal()
        context.job_queue.run_repeating(send_media_job, interval=conf.get("time", 1)*60, first=5, chat_id=chat_id, name=str(chat_id))
        await query.edit_message_text("🚀 Bombardeo activo y protegido.")
    elif "stop_bomb" in data:
        for j in context.job_queue.get_jobs_by_name(str(chat_id)): j.schedule_removal()
        await query.edit_message_text("🛑 Bombardeo detenido.", reply_markup=get_main_keyboard(chat_id))

async def collect_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not esta_autorizado(update.effective_user.id) or update.message.chat.type != 'private': return
    archivo = update.message.photo[-1] if update.message.photo else update.message.video
    if not archivo: return
    
    mtype = "photo" if update.message.photo else "video"
    if col_media.find_one({"unique_id": archivo.file_unique_id}):
        await update.message.reply_text("⚠️ Ya existe.")
    else:
        col_media.insert_one({"type": mtype, "id": archivo.file_id, "unique_id": archivo.file_unique_id})
        await update.message.reply_text(f"✅ Guardado. Total: {col_media.count_documents({})}")

def main():
    threading.Thread(target=run_web_server, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_password))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, collect_media))
    app.run_polling()

if __name__ == '__main__':
    main()

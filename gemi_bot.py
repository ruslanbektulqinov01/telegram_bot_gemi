import os
import asyncio
import aiohttp
import base64
from io import BytesIO
from telebot.async_telebot import AsyncTeleBot
import google.generativeai as genai
from PIL import Image
from dotenv import load_dotenv

# .env faylini yuklash
load_dotenv()
# Environment variables
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# Initialize bot and AI model
bot = AsyncTeleBot(BOT_TOKEN)
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# Global variables
user_conversations = {}
active_users = {}
user_themes = {}
MAX_CONVERSATION_LENGTH = 300


# Helper functions
async def download_image(file_path):
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}") as response:
            return await response.read() if response.status == 200 else None


async def stream_response(chat_id, response):
    full_response = ""
    message = None
    last_update_length = 0

    await bot.send_chat_action(chat_id, 'typing')

    for chunk in response:
        if hasattr(chunk, 'text'):
            full_response += chunk.text
            if len(full_response) - last_update_length > 20:
                if message:
                    try:
                        await bot.edit_message_text(full_response, chat_id, message.id)
                    except Exception as e:
                        if "message is not modified" not in str(e):
                            print(f"Error updating message: {e}")
                else:
                    message = await bot.send_message(chat_id, full_response)
                last_update_length = len(full_response)
                await asyncio.sleep(0.5)
                await bot.send_chat_action(chat_id, 'typing')

    if not message:
        await bot.send_message(chat_id, full_response)


# Command handlers
@bot.message_handler(commands=['start'])
async def start_command(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    active_users[chat_id] = user_id
    user_conversations[user_id] = []

    welcome_message = (f"🧑‍💻 Salom, {message.from_user.first_name}!\n"
                       "Gemini AI bilan suhbatni boshladingiz. Savolingizni yuboring yoki /help buyrug'ini ishlating.")
    await bot.send_message(chat_id, welcome_message)


@bot.message_handler(commands=['help'])
async def help_command(message):
    help_text = """
🤖 Gemini AI Bot yordam:

Buyruqlar:
/start - Botni ishga tushirish va suhbatni boshlash
/theme [mavzu] - Suhbat mavzusini o'rnatish
/stop - Faol suhbatni to'xtatish va tarixni o'chirish
/help - Ushbu yordam xabarini ko'rsatish

Qo'shimcha ma'lumotlar:
- Bot ham shaxsiy, ham guruh chatlarida ishlaydi
- Rasm yuborib tahlil qilishni so'rashingiz mumkin
- Suhbat davomida mavzu o'rnatib, muayyan sohada gaplashishingiz mumkin
- Xavfsizlik maqsadida suhbat tarixi vaqtinchalik saqlanadi va /stop buyrug'i bilan o'chiriladi

Savollar yoki muammolar bo'lsa, botni ishlab chiqqan @ruslanbektulqinov ga murojaat qiling.
    """
    await bot.send_message(message.chat.id, help_text)


@bot.message_handler(commands=['theme'])
async def theme_command(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    theme = message.text.split(maxsplit=1)

    if len(theme) > 1:
        if theme[1].lower() == 'stop':
            if user_id in user_themes:
                del user_themes[user_id]
                await bot.send_message(chat_id, "Barcha mavzular o'chirildi.")
            else:
                await bot.send_message(chat_id, "Hozirda faol mavzu yo'q.")
        else:
            user_themes[user_id] = theme[1]
            await bot.send_message(chat_id, f"Mavzu o'rnatildi: {theme[1]}")
    else:
        await bot.send_message(chat_id,
                               "Mavzuni kiritmadingiz. Mavzuni quyidagicha kiriting: /theme Mavzu\nMavzuni bekor qilish uchun: /theme stop")


# Modified stop_command function
@bot.message_handler(commands=['stop'])
async def stop_command(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    if chat_id in active_users and active_users[chat_id] == user_id:
        active_users.pop(chat_id, None)
        user_conversations.pop(user_id, None)
        user_themes.pop(user_id, None)  # Clear themes for this user
        await bot.send_message(chat_id, "Suhbat to'xtatildi, tarix va barcha mavzular o'chirildi.")
    else:
        await bot.send_message(chat_id, "Sizda aktiv suhbat yo'q.")


# Main message handler
@bot.message_handler(func=lambda message: True, content_types=['text', 'photo'])
async def handle_message(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    if chat_id not in active_users or active_users[chat_id] != user_id:
        return

    try:
        await bot.send_chat_action(chat_id, 'typing')

        if message.content_type == 'text':
            user_input = message.text
            conversation_history = "\n".join(
                [f"User: {msg['user']}\nBot: {msg['bot']}" for msg in user_conversations[user_id]])
            theme = user_themes.get(user_id, "")
            prompt = f"Suhbat mavzusi: {theme}\n" if theme else ""
            prompt += f"Suhbat tarixi:\n{conversation_history}\n\nUser: {user_input}\nBot:"

            response = model.generate_content(prompt)

            user_conversations[user_id].append({"user": user_input, "bot": response.text})
            if len(user_conversations[user_id]) > MAX_CONVERSATION_LENGTH:
                user_conversations[user_id] = user_conversations[user_id][-MAX_CONVERSATION_LENGTH:]

        elif message.content_type == 'photo':
            file_info = await bot.get_file(message.photo[-1].file_id)
            image_data = await download_image(file_info.file_path)
            if image_data:
                image = Image.open(BytesIO(image_data))
                buffered = BytesIO()
                image.save(buffered, format="PNG")
                img_str = base64.b64encode(buffered.getvalue()).decode()

                response = model.generate_content([
                    "Iltimos, bu rasmni tahlil qiling va tafsilotlarini tasvirlang.",
                    {"mime_type": "image/png", "data": img_str}
                ], stream=True)
            else:
                await bot.reply_to(message, "Rasmni yuklashda xatolik yuz berdi. Iltimos, qayta urinib ko'ring.")
                return

        await stream_response(chat_id, response)

    except Exception as e:
        print(f"Xato yuz berdi: {str(e)}")
        await bot.reply_to(message, "Kechirasiz, hozirda javob bera olmayman. Iltimos, keyinroq urinib ko'ring.")


# Start the bot
if __name__ == '__main__':
    asyncio.run(bot.polling())

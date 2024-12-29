import google.generativeai as genai
from telegram import Bot
import asyncio

async def test_connections():
    # Test Gemini API
    try:
        genai.configure(api_key='AIzaSyB8SpGnjq8auhoJkLw3JN91qFhZK-_acvo')
        model = genai.GenerativeModel('gemini-pro')
        response = model.generate_content("Hello, test message")
        print("Gemini API connection successful!")
    except Exception as e:
        print(f"Gemini API error: {str(e)}")

    # Test Telegram Bot API
    try:
        bot = Bot('7997854932:AAHmmGQl0rCPaHi-zaw0co-v_kkUr4lTSxw')
        await bot.get_me()
        print("Telegram Bot API connection successful!")
    except Exception as e:
        print(f"Telegram Bot API error: {str(e)}")

if __name__ == "__main__":
    asyncio.run(test_connections()) 
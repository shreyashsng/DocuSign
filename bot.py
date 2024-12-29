import os
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import google.generativeai as genai
from PyPDF2 import PdfReader
import docx
import logging
import asyncio
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add these lines near the top of the file, after the imports
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configure Gemini API
genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
model = genai.GenerativeModel('gemini-pro')

# Simplify PROMPTS to single language
PROMPTS = {
    'summarize': "Please provide a concise summary of this text, highlighting the main points:",
    'chat': "Using the following document as context, please answer this question: {question}\n\nDocument context: {text}"
}

# Simplify MESSAGES to English only with user name support
MESSAGES = {
    'welcome': "Welcome {name}! 👋\nI'm your document assistant. Send me any PDF or Word document and I'll help you understand it better.",
    'processing': "Processing your document...",
    'error': "Sorry, there was an error processing your document.",
    'unsupported': "Please send a PDF or Word document.",
    'downloading': "📥 Downloading document...",
    'extracting': "📄 Extracting text...",
    'doc_ready': "✅ Document is ready! You can:\n1. Type 'summarize' to get a summary\n2. Ask any specific questions about the document\n3. Send another document",
    'file_too_large': "⚠️ File is too large. Please send a document smaller than 5MB.",
    'help': "I can help you understand documents better!\n\nCommands:\n/help - Show this help message\n\nAfter sending a document, you can:\n- Type 'summarize' to get a summary\n- Ask any questions about it\n- Send another document to analyze",
    'no_doc': "Please send a document first before asking questions.",
    'ask_more': "Would you like to know something else about this document? You can:\n1. Ask another question\n2. Type 'summarize' for a summary\n3. Send a new document\n4. Use /help for all commands",
    'credits_remaining': "💳 Credits remaining: {credits}",
    'no_credits': "❗ You've run out of credits! Use /subscribe to get more credits.",
    'new_user_credits': "🎁 Welcome gift: 5 free credits!",
    'credit_deducted': "1 credit used. {credits} credits remaining.",
    'subscription_info': """
💎 Premium Access Plans:
1. Basic Pack - $9.99 (100 credits)
2. Pro Pack - $24.99 (300 credits)
3. Unlimited Pack - $99.99 (1500 credits)

Contact @your_support_handle to purchase credits.
    """
}

# Add these constants at the top of the file after imports
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB limit
SUPPORTED_FORMATS = {'.pdf', '.docx'}
MAX_TEXT_LENGTH = 8000  # Limit text length for processing
CHUNK_SIZE = 3000      # Size for response chunks
MAX_RETRIES = 3
RETRY_DELAY = 2

class DocumentBot:
    def __init__(self):
        self.user_docs = {}
        self.credits = 5  # Starting credits for new users

# Add credit management functions
async def check_credits(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    user = context.bot_data['users'].get(user_id)
    
    if not user or user.credits <= 0:
        await update.message.reply_text(MESSAGES['no_credits'])
        return False
    return True

async def deduct_credit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = context.bot_data['users'][user_id]
    user.credits -= 1
    await update.message.reply_text(
        MESSAGES['credit_deducted'].format(credits=user.credits)
    )
    
    if user.credits == 0:
        await update.message.reply_text(MESSAGES['no_credits'])

# Add subscription command
async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(MESSAGES['subscription_info'])

# Modify start command to show initial credits
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    
    # Check if user is new
    is_new_user = user_id not in context.bot_data.get('users', {})
    
    context.bot_data.setdefault('users', {})
    context.bot_data['users'][user_id] = DocumentBot()
    
    welcome_message = MESSAGES['welcome'].format(name=user_name)
    await update.message.reply_text(welcome_message)
    
    if is_new_user:
        await update.message.reply_text(MESSAGES['new_user_credits'])
        await update.message.reply_text(
            MESSAGES['credits_remaining'].format(
                credits=context.bot_data['users'][user_id].credits
            )
        )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    try:
        document = update.message.document
        
        # Check file size first
        if document.file_size > MAX_FILE_SIZE:
            await update.message.reply_text(MESSAGES['file_too_large'])
            return
            
        # Check file format quickly
        file_ext = os.path.splitext(document.file_name.lower())[1]
        if file_ext not in SUPPORTED_FORMATS:
            await update.message.reply_text(MESSAGES['unsupported'])
            return
        
        await update.message.reply_text(MESSAGES['downloading'])
        
        # Create downloads directory and handle file
        os.makedirs('downloads', exist_ok=True)
        file_path = os.path.join('downloads', document.file_name)
        
        file = await document.get_file()
        await file.download_to_drive(file_path)
        
        # Extract text based on file type
        text = (extract_pdf_text(file_path) if file_ext == '.pdf' 
                else extract_docx_text(file_path))
        
        if not text.strip():
            await update.message.reply_text("The document appears to be empty or unreadable.")
            return
            
        # Store the text
        context.bot_data['users'][user_id].user_docs['current_doc'] = text
        await update.message.reply_text(MESSAGES['doc_ready'])
        
    except Exception as e:
        logger.error(f"Error processing document: {str(e)}")
        await update.message.reply_text(MESSAGES['error'])
    finally:
        if 'file_path' in locals():
            try:
                os.remove(file_path)
            except Exception as e:
                logger.error(f"Error cleaning up file: {str(e)}")

def extract_pdf_text(file_path):
    try:
        reader = PdfReader(file_path)
        text = []
        # Only process first 20 pages and limit text per page
        max_pages = min(len(reader.pages), 20)
        for i in range(max_pages):
            page_text = reader.pages[i].extract_text()
            text.append(page_text[:MAX_TEXT_LENGTH // max_pages])
        return "\n".join(text)[:MAX_TEXT_LENGTH]
    except Exception as e:
        logger.error(f"PDF extraction error: {str(e)}")
        raise

def extract_docx_text(file_path):
    try:
        doc = docx.Document(file_path)
        text = []
        # Only process first 30 paragraphs
        for i, para in enumerate(doc.paragraphs[:30]):
            if para.text.strip():
                text.append(para.text)
        return "\n".join(text)[:MAX_TEXT_LENGTH]
    except Exception as e:
        logger.error(f"DOCX extraction error: {str(e)}")
        raise

def chunk_text(text, max_length=4000):
    sentences = text.split('.')
    chunks = []
    current_chunk = ""
    
    for sentence in sentences:
        if len(current_chunk) + len(sentence) < max_length:
            current_chunk += sentence + "."
        else:
            chunks.append(current_chunk)
            current_chunk = sentence + "."
    
    if current_chunk:
        chunks.append(current_chunk)
    return chunks

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_credits(update, context):
        return
        
    user_id = update.effective_user.id
    
    if update.message.text.startswith('/'): return
    
    if 'current_doc' not in context.bot_data['users'][user_id].user_docs:
        await update.message.reply_text(MESSAGES['no_doc'])
        return
    
    text = context.bot_data['users'][user_id].user_docs['current_doc'][:MAX_TEXT_LENGTH]
    user_input = update.message.text.lower()
    
    try:
        await update.message.chat.send_action('typing')
        
        # Process in smaller chunks
        text_chunks = chunk_text(text, max_length=3000)
        responses = []
        
        for chunk in text_chunks:
            if user_input == 'summarize':
                prompt = f"{PROMPTS['summarize']}\n\nText:\n{chunk}"
            else:
                prompt = PROMPTS['chat'].format(question=update.message.text, text=chunk)
            
            # Simple retry logic without await
            for attempt in range(MAX_RETRIES):
                try:
                    response = model.generate_content(prompt)
                    responses.append(response.text)
                    break
                except Exception as e:
                    if attempt == MAX_RETRIES - 1:
                        raise
                    await asyncio.sleep(1)
        
        # Send response in chunks
        combined_response = " ".join(responses)
        for i in range(0, len(combined_response), CHUNK_SIZE):
            chunk = combined_response[i:i + CHUNK_SIZE]
            await update.message.reply_text(chunk)
            await asyncio.sleep(0.3)
        
        # Deduct credit and show remaining
        await deduct_credit(update, context)
        
        # Ask if user wants to know more
        await update.message.reply_text(MESSAGES['ask_more'])
            
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        await update.message.reply_text(MESSAGES['error'])

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(MESSAGES['help'])

def main():
    try:
        application = Application.builder().token(os.getenv('TELEGRAM_BOT_TOKEN')).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("subscribe", subscribe_command))
        application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        logger.info("Bot is starting up...")
        application.run_polling()
    except Exception as e:
        logger.error(f"Error starting bot: {str(e)}")
        raise e

if __name__ == '__main__':
    main() 
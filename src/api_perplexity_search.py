# # # api_perplexity_search.py
# # # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# # # https://github.com/FlyingFathead/TelegramBot-OpenAI-API/
# # # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

import re
import openai
import httpx
import logging
import os
import asyncio
import configparser
import random
from config_paths import CONFIG_PATH

# Load the configuration file
config = configparser.ConfigParser()
config.read(CONFIG_PATH)

# Perplexity API model to use -- NOTE: the models keep on changing; latest list is at: https://docs.perplexity.ai/guides/model-cards
# As of December 2024/January 2025, the latest model is in the llama-3.1 family, i.e.: "llama-3.1-sonar-large-128k-online" (can be small/large/huge)
DEFAULT_PERPLEXITY_MODEL = "sonar"
DEFAULT_PERPLEXITY_MAX_TOKENS = 1024
DEFAULT_PERPLEXITY_TEMPERATURE = 0.0
DEFAULT_PERPLEXITY_MAX_RETRIES = 3
DEFAULT_PERPLEXITY_RETRY_DELAY = 25
DEFAULT_PERPLEXITY_TIMEOUT = 30
DEFAULT_CHUNK_SIZE = 1000
PERPLEXITY_MODEL = config.get('Perplexity', 'Model', fallback=DEFAULT_PERPLEXITY_MODEL)
PERPLEXITY_MAX_TOKENS = config.getint('Perplexity', 'MaxTokens', fallback=DEFAULT_PERPLEXITY_MAX_TOKENS)
PERPLEXITY_TEMPERATURE = config.getfloat('Perplexity', 'Temperature', fallback=DEFAULT_PERPLEXITY_TEMPERATURE)
PERPLEXITY_MAX_RETRIES = config.getint('Perplexity', 'MaxRetries', fallback=DEFAULT_PERPLEXITY_MAX_RETRIES)
PERPLEXITY_RETRY_DELAY = config.getint('Perplexity', 'RetryDelay', fallback=DEFAULT_PERPLEXITY_RETRY_DELAY)
PERPLEXITY_TIMEOUT = config.getint('Perplexity', 'Timeout', fallback=DEFAULT_PERPLEXITY_TIMEOUT)
CHUNK_SIZE = config.getint('Perplexity', 'ChunkSize', fallback=DEFAULT_CHUNK_SIZE)
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")
MAX_TELEGRAM_MESSAGE_LENGTH = 4000

async def fact_check_with_perplexity(question: str):
    url = "https://api.perplexity.ai/chat/completions"
    headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    data = {
        "model": PERPLEXITY_MODEL,
        "stream": False,
        "max_tokens": PERPLEXITY_MAX_TOKENS,
        "temperature": PERPLEXITY_TEMPERATURE,
        "messages": [{"role": "user", "content": question}]
    }

    async with httpx.AsyncClient(timeout=PERPLEXITY_TIMEOUT) as client:
        for attempt in range(PERPLEXITY_MAX_RETRIES):
            try:
                response = await client.post(url, json=data, headers=headers)
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 500:
                    logging.error("Perplexity API returned a 500 server error.")
                    return {"error": "server_error"}
                else:
                    logging.error(f"Perplexity API Error: {response.text}")
            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                logging.error(f"Error while calling Perplexity API: {e}")

            backoff_delay = min(PERPLEXITY_RETRY_DELAY, (2 ** attempt) + random.uniform(0, 1))
            await asyncio.sleep(backoff_delay)

    return None

async def query_perplexity(bot, chat_id, question: str):
    logging.info(f"Querying Perplexity with question: {question}")
    response_data = await fact_check_with_perplexity(question)

    if response_data and 'choices' in response_data:
        bot_reply_content = response_data['choices'][0].get('message', {}).get('content', "").strip()
        if bot_reply_content:
            return bot_reply_content
        else:
            logging.warning("Processed content is empty after stripping.")
            return "Received an empty response, please try again."
    elif response_data and response_data.get('error') == 'server_error':
        logging.error("Perplexity API server error.")
        return "Perplexity API is currently unavailable due to server issues. Please try again later."
    else:
        logging.error("Unexpected response structure from Perplexity API.")
        return "Error interpreting the response."

# Utilities
def smart_chunk(text, chunk_size=CHUNK_SIZE):
    chunks = []
    blocks = text.split('\n\n')
    current_chunk = ""

    for block in blocks:
        if len(current_chunk) + len(block) + 2 <= chunk_size:
            current_chunk += block + "\n\n"
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""

            if len(block) > chunk_size:
                lines = block.split('\n')
                temp_chunk = ""

                for line in lines:
                    if len(temp_chunk) + len(line) + 1 <= chunk_size:
                        temp_chunk += line + "\n"
                    else:
                        if temp_chunk:
                            chunks.append(temp_chunk.strip())
                            temp_chunk = ""
                        sentences = re.split('([.!?] )', line)
                        sentence_chunk = ""
                        for sentence in sentences:
                            if sentence.strip():
                                if len(sentence_chunk) + len(sentence) <= chunk_size:
                                    sentence_chunk += sentence
                                else:
                                    if sentence_chunk:
                                        chunks.append(sentence_chunk.strip())
                                        sentence_chunk = ""
                                    sentence_chunk = sentence
                        if sentence_chunk:
                            chunks.append(sentence_chunk.strip())
            else:
                current_chunk = block + "\n\n"

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks

def rejoin_chunks(chunks):
    rejoined_text = ""
    for i, chunk in enumerate(chunks):
        trimmed_chunk = chunk.strip()
        if i == 0:
            rejoined_text += trimmed_chunk
        else:
            if rejoined_text.endswith('\n\n'):
                if not trimmed_chunk.startswith('- ') and not trimmed_chunk.startswith('### ') and not trimmed_chunk.startswith('## '):
                    rejoined_text += '\n' + trimmed_chunk
                else:
                    rejoined_text += trimmed_chunk
            else:
                rejoined_text += '\n\n' + trimmed_chunk
    return rejoined_text

def format_headers_for_telegram(translated_response):
    lines = translated_response.split('\n')
    formatted_lines = []

    for i, line in enumerate(lines):
        if line.startswith('####'):
            if i > 0 and lines[i - 1].strip() != '':
                formatted_lines.append('')
            formatted_line = '◦ <b>' + line[4:].strip() + '</b>'
            formatted_lines.append(formatted_line)
            if i < len(lines) - 1 and lines[i + 1].strip() != '':
                formatted_lines.append('')
        elif line.startswith('###'):
            if i > 0 and lines[i - 1].strip() != '':
                formatted_lines.append('')
            formatted_line = '• <b>' + line[3:].strip() + '</b>'
            formatted_lines.append(formatted_line)
            if i < len(lines) - 1 and lines[i + 1].strip() != '':
                formatted_lines.append('')
        elif line.startswith('##'):
            if i > 0 and lines[i - 1].strip() != '':
                formatted_lines.append('')
            formatted_line = '➤ <b>' + line[2:].strip() + '</b>'
            formatted_lines.append(formatted_line)
            if i < len(lines) - 1 and lines[i + 1].strip() != '':
                formatted_lines.append('')
        else:
            formatted_lines.append(line)

    formatted_response = '\n'.join(formatted_lines)
    return formatted_response

def markdown_to_html(md_text):
    html_text = re.sub(r'\$\$(.*?)\$\$', r'<pre>\1</pre>', md_text)
    html_text = re.sub(r'\\\[(.*?)\\\]', r'<pre>\1</pre>', html_text)
    html_text = re.sub(r'^#### (.*)', r'<b>\1</b>', html_text, flags=re.MULTILINE)
    html_text = re.sub(r'^### (.*)', r'<b>\1</b>', html_text, flags=re.MULTILINE)
    html_text = re.sub(r'^## (.*)', r'<b>\1</b>', html_text, flags=re.MULTILINE)
    html_text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', html_text)
    html_text = re.sub(r'\*(.*?)\*|_(.*?)_', r'<i>\1\2</i>', html_text)
    html_text = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2">\1</a>', html_text)
    html_text = re.sub(r'`(.*?)`', r'<code>\1</code>', html_text)
    html_text = re.sub(r'```(.*?)```', r'<pre>\1</pre>', html_text, flags=re.DOTALL)
    return html_text

def sanitize_urls(text):
    url_pattern = re.compile(r'<(http[s]?://[^\s<>]+)>')
    sanitized_text = re.sub(url_pattern, r'\1', text)
    return sanitized_text

# split long messages
def split_message(text, max_length=MAX_TELEGRAM_MESSAGE_LENGTH):
    paragraphs = text.split('\n')
    chunks = []
    current_chunk = ""

    for paragraph in paragraphs:
        if len(current_chunk) + len(paragraph) + 1 <= max_length:
            current_chunk += paragraph + "\n"
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = paragraph + "\n"

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    # Further split chunks that are still too large
    final_chunks = []
    for chunk in chunks:
        while len(chunk) > max_length:
            split_point = chunk.rfind('.', 0, max_length)
            if split_point == -1:
                split_point = max_length
            final_chunks.append(chunk[:split_point].strip())
            chunk = chunk[split_point:].strip()
        if chunk:
            final_chunks.append(chunk.strip())

    logging.info(f"Total number of chunks created: {len(final_chunks)}")
    return final_chunks

async def send_split_messages(context, chat_id, text):
    chunks = split_message(text)
    logging.info(f"Total number of chunks to be sent: {len(chunks)}")

    for chunk in chunks:
        if not chunk.strip():
            logging.warning("send_split_messages attempted to send an empty chunk. Skipping.")
            continue

        logging.info(f"Sending chunk with length: {len(chunk)}")
        await context.bot.send_message(chat_id=chat_id, text=chunk, parse_mode='HTML')
        logging.info(f"Sent chunk with length: {len(chunk)}")
    logging.info("send_split_messages completed.")

async def handle_long_response(context, chat_id, long_response_text):
    if not long_response_text.strip():
        logging.warning("handle_long_response received an empty message. Skipping.")
        return

    logging.info(f"Handling long response with text length: {len(long_response_text)}")
    await send_split_messages(context, chat_id, long_response_text)

# language detection over OpenAI API
async def detect_language(bot, text):
    prompt = f"Detect the language of the following text:\n\n{text}\n\nRespond with only the language code, e.g., 'en' for English, 'fi' for Finnish, 'jp' for Japanese. HINT: If the query starts off with i.e. 'kuka', 'mikä', 'mitä' or 'missä', 'milloin', 'miksi', 'minkä', 'minkälainen', 'mikä', 'kenen', 'kenenkä', 'keiden', 'kenestä, 'kelle', 'keneltä', 'kenelle', it's probably in Finnish ('fi')."
    
    payload = {
        "model": bot.model,
        "messages": [
            {"role": "system", "content": "You are a language detection assistant."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0,
        "max_tokens": 10
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {bot.openai_api_key}"
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post("https://api.openai.com/v1/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            detected_language = response.json()['choices'][0]['message']['content'].strip()
            logging.info(f"Detected language: {detected_language}")
            return detected_language
    except httpx.RequestError as e:
        logging.error(f"RequestError while calling OpenAI API: {e}")
    except httpx.HTTPStatusError as e:
        logging.error(f"HTTPStatusError while calling OpenAI API: {e}")
    except Exception as e:
        logging.error(f"Unexpected error while calling OpenAI API: {e}")
        return 'en'  # Default to English in case of an error

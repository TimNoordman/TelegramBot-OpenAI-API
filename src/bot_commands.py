# bot_commands.py
# Stone Member B.V. — Telegram Bot Commands
# Based on FlyingFathead/TelegramBot-OpenAI-API

from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, filters, CommandHandler, CallbackContext
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
from functools import partial

import json
import os
import datetime
import logging

# bot's modules
from config_paths import CONFIG_PATH
from token_usage_visualization import generate_usage_chart
from modules import reset_token_usage_at_midnight 

# ~~~~~~~~~~~~~~
# admin commands
# ~~~~~~~~~~~~~~

# /admin (admin commands help menu)
async def admin_command(update: Update, context: CallbackContext, bot_owner_id):
    if bot_owner_id == '0':
        await update.message.reply_text("The /admin command is disabled.")
        return

    if str(update.message.from_user.id) == bot_owner_id:
        admin_commands = """
Admin Commands:
- <code>/viewconfig</code>: View the bot configuration (from <code>config.ini</code>).
- <code>/usage</code>: View the bot's daily token usage in plain text.
- <code>/usagechart</code>: View the bot's daily token usage as a chart.
- <code>/reset</code>: Reset the bot's context memory.
- <code>/resetsystemmessage</code>: Reset the system message from <code>config.ini</code>.
- <code>/setsystemmessage &lt;system message&gt;</code>: Set a new system message (note: not saved into config).
        """
        await update.message.reply_text(admin_commands, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text("You are not authorized to use this command.")

# /restart (admin command)
async def restart_command(update: Update, context: CallbackContext, bot_owner_id):
    if bot_owner_id == '0':
        await update.message.reply_text("The /restart command is disabled.")
        return

    if str(update.message.from_user.id) == bot_owner_id:
        await update.message.reply_text("Restarting the bot...")
    else:
        await update.message.reply_text("You are not authorized to use this command.")

# /resetdailytokens (admin command for resetting daily token usage)
async def reset_daily_tokens_command(update: Update, context: CallbackContext, bot_instance):
    user_id = update.message.from_user.id
    if bot_instance.bot_owner_id == '0' or str(user_id) != bot_instance.bot_owner_id:
        logging.info(f"User {user_id} tried to use /resetdailytokens but was not authorized.")
        await update.message.reply_text("You are not authorized to use this command.")
        return

    try:
        reset_token_usage_at_midnight(bot_instance.token_usage_file, bot_instance.reset_total_token_usage)
        logging.info(f"User {user_id} has reset the daily token usage, including the in-memory token usage counter.")
        await update.message.reply_text("Daily token usage has been reset, including the in-memory token usage counter.")
    except Exception as e:
        logging.error(f"Failed to reset daily token usage: {e}")
        await update.message.reply_text("Failed to reset daily token usage.")

# /resetsystemmessage (admin command)
async def reset_system_message_command(update: Update, context: CallbackContext, bot_instance):
    user_id = update.message.from_user.id
    if bot_instance.bot_owner_id == '0' or str(user_id) != bot_instance.bot_owner_id:
        logging.info(f"User {user_id} tried to use /resetsystemmessage but was not authorized.")
        await update.message.reply_text("You are not authorized to use this command.")
        return

    old_system_message = bot_instance.system_instructions
    bot_instance.system_instructions = bot_instance.config.get('SystemInstructions', 'You are an OpenAI API-based chatbot on Telegram.')
    logging.info(f"User {user_id} reset the system message to default.")
    await update.message.reply_text(f"System message reset to default.\n\nOld Message:\n<code>{old_system_message[:200]}...</code>\n----------------------\nNew Default Message:\n<code>{bot_instance.system_instructions[:200]}...</code>", parse_mode=ParseMode.HTML)

# /setsystemmessage (admin command)
async def set_system_message_command(update: Update, context: CallbackContext, bot_instance):
    user_id = update.message.from_user.id
    if bot_instance.bot_owner_id == '0' or str(user_id) != bot_instance.bot_owner_id:
        logging.info(f"User {user_id} tried to use /setsystemmessage but was not authorized.")
        await update.message.reply_text("You are not authorized to use this command.")
        return

    new_system_message = ' '.join(context.args)
    if new_system_message:
        old_system_message = bot_instance.system_instructions
        bot_instance.system_instructions = new_system_message
        logging.info(f"User {user_id} updated the system message to: {new_system_message}")
        await update.message.reply_text(f"System message updated.\n\nOld Message: <code>{old_system_message[:200]}...</code>\nNew Message: <code>{new_system_message[:200]}...</code>", parse_mode=ParseMode.HTML)
    else:
        logging.info(f"User {user_id} attempted to set system message but provided no new message.")
        await update.message.reply_text("Please provide the new system message in the command line, i.e.: /setsystemmessage My new system message to the AI on what it is, where it is, etc.")


# /usage (admin command)
async def usage_command(update: Update, context: CallbackContext):
    bot_instance = context.bot_data.get('bot_instance')
    
    if not bot_instance:
        await update.message.reply_text("Internal error: Bot instance not found.")
        logging.error("Bot instance not found in context.bot_data")
        return

    logging.info(f"User {update.message.from_user.id} invoked /usage command")

    if bot_instance.bot_owner_id == '0':
        await update.message.reply_text("The `/usage` command is disabled.")
        logging.info("Usage command is disabled until a bot owner is defined in `config.ini`.")
        return

    if str(update.message.from_user.id) != bot_instance.bot_owner_id:
        await update.message.reply_text("You don't have permission to use this command.")
        logging.info(f"User {update.message.from_user.id} does not have permission to use /usage")
        return

    token_usage_file = os.path.join(bot_instance.logs_directory, 'token_usage.json')

    logging.info(f"Looking for token usage file at: {token_usage_file}")
    current_date = datetime.datetime.utcnow()

    try:
        if os.path.exists(token_usage_file):
            with open(token_usage_file, 'r') as file:
                token_usage_history = json.load(file)
            logging.info("Loaded token usage history successfully")
            
            cutoff_date = current_date - datetime.timedelta(days=bot_instance.max_history_days)
            token_usage_history = {
                date: usage for date, usage in token_usage_history.items()
                if datetime.datetime.strptime(date, '%Y-%m-%d') >= cutoff_date
            }
            logging.info("Pruned token usage history based on cutoff date")
        else:
            token_usage_history = {}
            logging.warning(f"Token usage file does not exist at: {token_usage_file}")
    except json.JSONDecodeError:
        await update.message.reply_text("Error reading token usage history.")
        logging.error("JSONDecodeError while reading token_usage.json")
        return
    except Exception as e:
        await update.message.reply_text(f"An unexpected error occurred: {e}")
        logging.error(f"Unexpected error in usage_command: {e}")
        return

    today_usage = token_usage_history.get(current_date.strftime('%Y-%m-%d'), 0)
    token_cap_info = (
        f"Today's usage: {today_usage} tokens\n"
        f"Daily token cap: {'No cap' if bot_instance.max_tokens_config == 0 else f'{bot_instance.max_tokens_config} tokens'}\n\n"
        "Token Usage History:\n"
    )

    for date, usage in sorted(token_usage_history.items()):
        token_cap_info += f"{date}: {usage} tokens\n"

    await update.message.reply_text(token_cap_info)
    logging.info("Sent usage information to user")

# /usagechart (admin command)
async def usage_chart_command(update: Update, context: CallbackContext):
    bot_instance = context.bot_data.get('bot_instance')
    
    if not bot_instance:
        await update.message.reply_text("Internal error: Bot instance not found.")
        logging.error("Bot instance not found in context.bot_data")
        return

    logging.info(f"User {update.message.from_user.id} invoked /usagechart command")

    if bot_instance.bot_owner_id == '0':
        await update.message.reply_text("The `/usagechart` command is disabled.")
        logging.info("Usagechart command is disabled")
        return

    if str(update.message.from_user.id) != bot_instance.bot_owner_id:
        await update.message.reply_text("You don't have permission to use this command.")
        logging.info(f"User {update.message.from_user.id} does not have permission to use /usagechart")
        return

    token_usage_file = os.path.join(bot_instance.logs_directory, 'token_usage.json')
    output_image_file = os.path.join(bot_instance.data_directory, 'token_usage_chart.png')

    logging.info(f"Looking for token usage file at: {token_usage_file}")
    logging.info(f"Output image file will be at: {output_image_file}")

    try:
        if not os.path.exists(bot_instance.data_directory):
            os.makedirs(bot_instance.data_directory, exist_ok=True)
            bot_instance.logger.info(f"Created data directory at {bot_instance.data_directory}")
    except OSError as e:
        bot_instance.logger.error(f"Failed to create data directory {bot_instance.data_directory}: {e}")
        await update.message.reply_text(f"Failed to create the data directory for the chart. Please check the bot's permissions.")
        return

    try:
        generate_usage_chart(token_usage_file, output_image_file)
        bot_instance.logger.info(f"Generated usage chart at {output_image_file}")
    except Exception as e:
        bot_instance.logger.error(f"Failed to generate usage chart: {e}")
        await update.message.reply_text("Failed to generate usage chart.")
        return

    try:
        with open(output_image_file, 'rb') as file:
            await context.bot.send_photo(chat_id=update.message.chat_id, photo=file)
        bot_instance.logger.info(f"Sent usage chart to chat_id {update.message.chat_id}")
    except FileNotFoundError:
        await update.message.reply_text("Token usage chart not found. Please ensure it's being generated correctly.")
        bot_instance.logger.error("Token usage chart file not found: %s", output_image_file)
    except Exception as e:
        await update.message.reply_text("Failed to send the usage chart.")
        bot_instance.logger.error(f"Error sending usage chart: {e}")

# /reset
async def reset_command(update: Update, context: CallbackContext, bot_owner_id, reset_enabled, admin_only_reset):
    if not reset_enabled:
        logging.info(f"User tried to use the /reset command, but it was disabled.")
        await update.message.reply_text("The /reset command is disabled.")
        return

    if admin_only_reset and str(update.message.from_user.id) != bot_owner_id:
        logging.info(f"User tried to use the /reset command, but was not authorized to do so.")
        await update.message.reply_text("You are not authorized to use this command.")
        return

    if 'chat_history' in context.chat_data:
        context.chat_data['chat_history'] = []
        logging.info(f"Memory context was reset successfully with: /reset")
        await update.message.reply_text("🔄 Gesprek gereset! Stel gerust een nieuwe vraag.\n🔄 Conversation reset! Feel free to ask a new question.")
    else:
        logging.info(f"No memory context to reset with: /reset")
        await update.message.reply_text("Geen gespreksgeschiedenis om te resetten.\nNo conversation history to reset.")

# /viewconfig (admin command)
async def view_config_command(update: Update, context: CallbackContext, bot_owner_id):
    user_id = update.message.from_user.id

    if bot_owner_id == '0':
        logging.info(f"User {user_id} attempted to view the config with: /viewconfig -- command disabled")
        await update.message.reply_text("The /viewconfig command is disabled.")
        return

    if str(user_id) == bot_owner_id:
        try:
            config_contents = "<pre>"
            with open(CONFIG_PATH, 'r') as file:
                for line in file:
                    if not line.strip() or line.strip().startswith('#'):
                        continue
                    line = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    config_contents += line
            config_contents += "</pre>"
            logging.info(f"User {user_id} (owner) viewed the config with: /viewconfig")
            if config_contents:
                await update.message.reply_text(config_contents, parse_mode=ParseMode.HTML)
            else:
                logging.info(f"[WARNING] User {user_id} attempted to view the config with: /viewconfig -- no configuration settings were available")
                await update.message.reply_text("No configuration settings available.")
        except Exception as e:
            logging.info(f"[ERROR] User {user_id} attempted to view the config with: /viewconfig -- there was an error reading the config file: {e}")
            await update.message.reply_text(f"Error reading configuration file: {e}")
    else:
        logging.info(f"[ATTENTION] User {user_id} attempted to view the config with: /viewconfig -- access denied")
        await update.message.reply_text("You are not authorized to use this command.")

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Stone Member B.V. — Custom user commands
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

# /start
async def start(update: Update, context: CallbackContext, start_command_response):
    keyboard = [
        [
            InlineKeyboardButton("🌐 Website", url="https://www.stonemember.nl"),
            InlineKeyboardButton("💬 WhatsApp", url="https://wa.me/31610135459"),
            InlineKeyboardButton("☎️ Bel ons", url="tel:+31610135459"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(start_command_response, reply_markup=reply_markup)

# /about
async def about_command(update: Update, context: CallbackContext, version_number):
    about_text = (
        "\ud83c\udfd7\ufe0f <b>Stone Member B.V.</b> \u2014 BOUW &amp; ONTWIKKELING\n\n"
        "De digitale assistent van Stone Member B.V., "
        "een professioneel bouwbedrijf gevestigd in Almere, Nederland.\n\n"
        "Gespecialiseerd in nieuwbouw, renovatie, en technische diensten "
        "voor commerci\u00eble, industri\u00eble en residenti\u00eble projecten.\n\n"
        "\ud83d\udccd Grote Markt 38, 1315 JG Almere\n"
        "\ud83d\udcde +31 (0) 6 101 354 59\n"
        "\ud83d\udce7 info@stonemember.nl\n"
        "\ud83c\udf10 www.stonemember.nl"
    )
    await update.message.reply_text(about_text, parse_mode=ParseMode.HTML)

# /help
async def help_command(update: Update, context: CallbackContext, reset_enabled, admin_only_reset):
    help_text = (
        "📋 <b>Commando's / Commands</b>\n\n"
        "<b>Stone Member:</b>\n"
        "/start — Nieuw gesprek / New conversation\n"
        "/diensten — Onze diensten / Our services\n"
        "/contact — Contactgegevens / Contact details\n"
        "/offerte — Offerte aanvragen / Request quote\n"
        "/tekeningen — Technische tekeningen / Technical drawings\n"
        "/about — Over deze bot / About this bot\n"
    )

    if reset_enabled:
        help_text += "/reset — Gesprek resetten / Reset conversation\n"
        if admin_only_reset:
            help_text += "  <i>(Alleen admin / Admin only)</i>\n"

    help_text += (
        "\n<b>Extra tools:</b>\n"
        "De bot kan ook helpen met weer, berekeningen, routebeschrijvingen en meer. "
        "Stel gewoon uw vraag! 💬\n\n"
        "/help — Dit helpbericht / This help message"
    )

    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)

# /diensten — Overview of Stone Member services
async def diensten_command(update: Update, context: CallbackContext):
    text = (
        "🏗️ <b>Diensten Stone Member B.V.</b>\n\n"
        "<b>Nieuwbouw</b>\n"
        "Commerciële/industriële gebouwen, padelhallen, sportfaciliteiten, bedrijfspanden\n\n"
        "<b>Renovatie</b>\n"
        "Appartementen, woningen, verbouwingen en uitbreidingen\n\n"
        "<b>Ruwbouw</b>\n"
        "Betonwerk, metselwerk, prefab beton, staalconstructie, ruwbouwtimmerwerk\n\n"
        "<b>Fundering &amp; Grondwerk</b>\n"
        "Peil/uitzetten, grondwerk, buitenriolering, terrein inrichting\n\n"
        "<b>Gevels &amp; Dak</b>\n"
        "Kozijnen, sandwichpanelen, dakbedekkingen, trappen en balustrades\n\n"
        "<b>Afbouw</b>\n"
        "Stukadoorswerk, tegelwerk, dekvloeren, schilderwerk, afbouwtimmerwerk\n\n"
        "<b>Installaties</b>\n"
        "Vloerverwarming, sanitair, ventilatie, elektra\n\n"
        "<b>Technisch</b>\n"
        "2D detailtekeningen, werktekeningen, kostenramingen, offertes\n\n"
        "Stel gerust een vraag voor meer details! 💬"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

# /contact — Stone Member contact details
async def contact_command(update: Update, context: CallbackContext):
    text = (
        "📞 <b>Contact Stone Member B.V.</b>\n\n"
        "👤 <b>Tim Noordman</b>\n"
        "📍 Grote Markt 38, 1315 JG Almere\n"
        "📱 +31 (0) 6 101 354 59\n"
        "📧 info@stonemember.nl\n"
        "📧 tim@stonemember.nl\n"
        "🌐 www.stonemember.nl\n\n"
        "🏢 KvK: 086739395"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

# /offerte — Quote request information
async def offerte_command(update: Update, context: CallbackContext):
    text = (
        "📋 <b>Offerte aanvragen bij Stone Member</b>\n\n"
        "Wilt u een offerte ontvangen? Dit hebben wij nodig:\n\n"
        "1️⃣ <b>Tekeningen</b> — Bouwtekeningen of schetsen van uw project\n"
        "2️⃣ <b>Specificaties</b> — Gewenste materialen, afmetingen, eisen\n"
        "3️⃣ <b>Locatie</b> — Waar wordt het project gerealiseerd?\n"
        "4️⃣ <b>Planning</b> — Gewenste start- en opleverdatum\n\n"
        "<b>Goed om te weten:</b>\n"
        "• Offertes zijn <b>4 maanden geldig</b>\n"
        "• Prijzen zijn <b>excl. 21% BTW</b>\n"
        "• Meerwerk alleen na <b>schriftelijke bevestiging</b>\n"
        "• Stelposten: max <b>10% afwijking</b>\n"
        "• Inclusief hijs-, hef-, klim- en graafmaterieel\n\n"
        "📧 Stuur uw aanvraag naar: <b>info@stonemember.nl</b>\n"
        "📞 Of bel: <b>+31 (0) 6 101 354 59</b>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

# /tekeningen — Technical drawings information
async def tekeningen_command(update: Update, context: CallbackContext):
    text = (
        "📐 <b>2D Technische Detailtekeningen</b>\n\n"
        "Stone Member maakt professionele 2D technische detailtekeningen:\n\n"
        "• <b>Constructietekeningen</b> — Beton- en staaldetails\n"
        "• <b>Aansluitdetails</b> — Hoe bouwdelen op elkaar aansluiten\n"
        "• <b>Funderingsdetails</b> — Doorsneden van funderingen\n"
        "• <b>Geveldetails</b> — Kozijnaansluitingen, sandwichpanelen\n"
        "• <b>Dakdetails</b> — Dakopbouw, dakranden, hemelwaterafvoer\n"
        "• <b>Installatietekeningen</b> — Leidingdoorvoeren, sparingen\n\n"
        "Alle tekeningen conform Nederlandse bouwstandaarden.\n"
        "Deze tekeningen vormen de basis voor kostenramingen en offertes.\n\n"
        "Meer weten? Stel een vraag of neem contact op! 💬"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

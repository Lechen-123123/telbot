import os
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
import logging
from azure.cosmos import CosmosClient, exceptions, PartitionKey
from gpt_hk import HKBU_ChatGPT
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from tarot_card_game import tarot_game
import time
import json


def main():
    # Build config dictionary from environment variables
    config = {
        'TELEGRAM': {
            'ACCESS_TOKEN': os.environ.get('TELEGRAM_ACCESS_TOKEN')
        },
        'COSMOS': {
            'URL': os.environ.get('COSMOS_URL'),
            'KEY': os.environ.get('COSMOS_KEY'),
            'DATABASE_ID': os.environ.get('COSMOS_DATABASE_ID'),
            'CONTAINER_ID': os.environ.get('COSMOS_CONTAINER_ID')
        },
        'CHATGPT':{
            'BASICURL': os.environ.get('CHATGPT_BASICURL'),
            'MODELNAME': os.environ.get('CHATGPT_MODELNAME'),
            'APIVERSION': os.environ.get('CHATGPT_APIVERSION'),
            'ACCESS_TOKEN': os.environ.get('CHATGPT_ACCESS_TOKEN')
        }
    }

    updater = Updater(token=config['TELEGRAM']['ACCESS_TOKEN'], use_context=True)
    dispatcher = updater.dispatcher

    cosmos_url = config['COSMOS']['URL']
    cosmos_key = config['COSMOS']['KEY']
    database_id = config['COSMOS']['DATABASE_ID']
    container_id = config['COSMOS']['CONTAINER_ID']

    cosmos_client = CosmosClient(cosmos_url, credential=cosmos_key)
    database = cosmos_client.get_database_client(database_id)
    container = database.get_container_client(container_id)

    chatgpt = HKBU_ChatGPT(config)

    # Store shared objects in bot_data
    dispatcher.bot_data['cosmos'] = container
    dispatcher.bot_data['chatgpt'] = chatgpt
    dispatcher.bot_data['executor'] = ThreadPoolExecutor(max_workers=5)

    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )

    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_chatgpt))
    dispatcher.add_handler(CommandHandler("add", handle_add))
    dispatcher.add_handler(CommandHandler("help", handle_help))
    dispatcher.add_handler(CommandHandler("hello", handle_hello))
    dispatcher.add_handler(CommandHandler("tarot", handle_tarot))
    dispatcher.add_handler(CommandHandler("match", handle_match))

    updater.start_polling()
    updater.idle()


def handle_chatgpt(update: Update, context: CallbackContext) -> None:
    chatgpt = context.bot_data.get('chatgpt')
    executor = context.bot_data.get('executor')
    future = executor.submit(chatgpt.submit, update.message.text)
    try:
        reply = future.result(timeout=20)
        context.bot.send_message(chat_id=update.effective_chat.id, text=reply)
    except TimeoutError:
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="ChatGPT is taking too long, please try again later."
        )


def handle_help(update: Update, context: CallbackContext) -> None:
    help_text = (
        "Available commands:\n"
        "/help - Show this help message\n"
        "/add <keyword> - Count keyword usage\n"
        "/hello [name] - Greet user\n"
        "/tarot - Draw a tarot card and get analysis\n"
        "/match [phone] - Match with another user by tarot card"
    )
    update.message.reply_text(help_text)


def handle_add(update: Update, context: CallbackContext) -> None:
    container = context.bot_data.get('cosmos')
    if context.args:
        keyword = context.args[0]
        document_id = keyword
        try:
            item = container.read_item(item=document_id, partition_key=document_id)
            count = item["definition"]["count"] + 1
            item["definition"]["count"] = count
            container.replace_item(item=item, body=item)
        except exceptions.CosmosResourceNotFoundError:
            count = 1
            item = {"id": document_id, "definition": {"id": document_id, "count": count}}
            container.create_item(body=item)
        update.message.reply_text(f"You have said {keyword} for {count} times.")
    else:
        update.message.reply_text("Usage: /add <keyword>")


def handle_hello(update: Update, context: CallbackContext) -> None:
    name = context.args[0] if context.args else "there"
    update.message.reply_text(f"Good day, {name}!")


def handle_tarot(update: Update, context: CallbackContext) -> None:
    container = context.bot_data.get('cosmos')
    user_key = f"tarot_analysis:{update.effective_chat.id}"

    result = tarot_game()
    analysis_prompt = (
        f"User draws tarot card: {result}. "
        "Please analyze the implications of this card for the user's current situation and provide suggestions."
    )

    chatgpt = context.bot_data.get('chatgpt')
    executor = context.bot_data.get('executor')
    future = executor.submit(chatgpt.submit, analysis_prompt)
    try:
        analysis_result = future.result(timeout=20)
    except TimeoutError:
        analysis_result = "Analysis request timed out, please try again later."

    timestamp = int(time.time())
    data = {
        "id": user_key,
        "definition": {
            "id": user_key,
            "tarot_result": result,
            "analysis": analysis_result,
            "timestamp": timestamp
        }
    }
    container.upsert_item(body=data)

    final_message = f"{result}\n\nTarot analysis:\n{analysis_result}"
    update.message.reply_text(final_message)


def handle_match(update: Update, context: CallbackContext) -> None:
    container = context.bot_data.get('cosmos')
    current_user_key = f"tarot_analysis:{update.effective_chat.id}"

    try:
        current_data = container.read_item(item=current_user_key, partition_key=current_user_key)
    except exceptions.CosmosResourceNotFoundError:
        update.message.reply_text("You haven't drawn tarot cards yet, please use the /tarot command to draw cards first.")
        return

    if context.args:
        phone_number = context.args[0]
        current_data["definition"]["phone"] = phone_number
        container.upsert_item(body=current_data)
    else:
        if "phone" not in current_data["definition"]:
            update.message.reply_text("Please set your phone number through /match <your phone number>.")
            return

    current_card = current_data["definition"].get("tarot_result")
    query = (
        "SELECT * FROM c WHERE c.definition.tarot_result=@tarot_result "
        "AND c.id != @current_id AND IS_DEFINED(c.definition.phone)"
    )
    parameters = [
        {"name": "@tarot_result", "value": current_card},
        {"name": "@current_id", "value": current_user_key}
    ]
    items = list(container.query_items(
        query=query,
        parameters=parameters,
        enable_cross_partition_query=True
    ))
    if items:
        matching_phone = items[0]["definition"].get("phone")
        update.message.reply_text(f"Match successful, the other party's phone number is: {matching_phone}")
    else:
        update.message.reply_text("There are currently no users matching the same card. Please try again later.")


if __name__ == '__main__':
    main()
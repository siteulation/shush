import os
import asyncio
import threading
from flask import Flask, render_template_string, request, jsonify
import discord
from discord.ext import commands

# --- CONFIGURATION ---
TARGET_GUILD_ID = 952963110283657266
TARGET_CHANNEL_ID = 1303054086454906920

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

message_log = []
# We need a reference to the bot's event loop to thread-safely send messages
bot_loop = None

@bot.event
async def on_ready():
    global bot_loop
    bot_loop = asyncio.get_running_loop()
    print(f'--- Bot Online: {bot.user} ---')

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    if message.channel.id == TARGET_CHANNEL_ID:
        log_entry = f"<b>{message.author.display_name}:</b> {message.content}"
        message_log.append(log_entry)

# --- FLASK ---
app = Flask(__name__)

@app.route('/')
def index():
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Discord Bridge</title>
        <style>
            body { font-family: sans-serif; background: #36393f; color: white; padding: 20px; }
            #log { height: 300px; overflow-y: auto; background: #202225; padding: 10px; border-radius: 5px; margin-bottom: 10px; }
            input { width: 80%; padding: 10px; background: #40444b; color: white; border: none; }
            button { padding: 10px; background: #5865f2; color: white; border: none; cursor: pointer; }
        </style>
    </head>
    <body>
        <div id="log"></div>
        <input type="text" id="msg" onkeydown="if(event.key==='Enter') send()">
        <button onclick="send()">Send</button>
        <script>
            async def send() {
                const i = document.getElementById('msg');
                await fetch('/send', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({message: i.value})
                });
                i.value = '';
            }
            setInterval(async () => {
                const r = await fetch('/messages');
                const d = await r.json();
                const l = document.getElementById('log');
                l.innerHTML = d.join('<br>');
                l.scrollTop = l.scrollHeight;
            }, 1000);
        </script>
    </body>
    </html>
    """)

@app.route('/send', methods=['POST'])
def send_msg():
    text = request.json.get('message')
    if text and bot_loop:
        channel = bot.get_channel(TARGET_CHANNEL_ID)
        if channel:
            # Thread-safe way to tell the Discord loop to send a message
            asyncio.run_coroutine_threadsafe(channel.send(text), bot_loop)
            message_log.append(f"<i>(You): {text}</i>")
    return jsonify(success=True)

@app.route('/messages')
def get_messages():
    return jsonify(message_log)

if __name__ == "__main__":
    # Start Flask in a background thread
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5000, use_reloader=False), daemon=True).start()
    # Run the bot in the main thread
    bot.run(os.getenv('APITOK'))

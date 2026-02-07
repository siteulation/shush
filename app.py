import os
import threading
import asyncio
from flask import Flask, render_template_string, request, jsonify
import discord
from discord.ext import commands

# --- CONFIGURATION ---
TARGET_GUILD_ID = 952963110283657266
TARGET_CHANNEL_ID = 1303054086454906920

# Setup Discord Bot
intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
message_log = []

@bot.event
async def on_ready():
    print(f'--- Bot Active: {bot.user} ---')
    print(f'Targeting Channel: {TARGET_CHANNEL_ID}')

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    # Only log messages from our target channel to keep the feed clean
    if message.channel.id == TARGET_CHANNEL_ID:
        log_entry = f"<b>{message.author.display_name}:</b> {message.content}"
        message_log.append(log_entry)

# --- FLASK WEB SERVER ---
app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Discord Direct Bridge</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #36393f; color: white; display: flex; justify-content: center; padding: 40px; }
        .container { width: 100%; max-width: 600px; background: #2f3136; padding: 20px; border-radius: 8px; box-shadow: 0 4px 15px rgba(0,0,0,0.3); }
        #log { height: 400px; overflow-y: auto; background: #202225; padding: 15px; border-radius: 5px; margin-bottom: 20px; border: 1px solid #4f545c; line-height: 1.5; }
        .input-area { display: flex; gap: 10px; }
        input { flex-grow: 1; padding: 12px; border-radius: 4px; border: none; background: #40444b; color: white; outline: none; }
        button { padding: 10px 20px; background: #5865f2; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; }
        button:hover { background: #4752c4; }
    </style>
</head>
<body>
    <div class="container">
        <h2>Direct Bridge to Discord</h2>
        <div id="log"></div>
        <div class="input-area">
            <input type="text" id="msg" placeholder="Send a message..." onkeydown="if(event.key==='Enter') sendMsg()">
            <button onclick="sendMsg()">Send</button>
        </div>
    </div>

    <script>
        async function sendMsg() {
            const input = document.getElementById('msg');
            const text = input.value;
            if(!text) return;

            await fetch('/send', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({message: text})
            });
            input.value = '';
        }

        async function updateLog() {
            const res = await fetch('/messages');
            const data = await res.json();
            const logDiv = document.getElementById('log');
            
            // Only update if content changed
            const newContent = data.join('<br>');
            if (logDiv.innerHTML !== newContent) {
                logDiv.innerHTML = newContent;
                logDiv.scrollTop = logDiv.scrollHeight; // Auto-scroll
            }
        }

        setInterval(updateLog, 1500);
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/send', methods=['POST'])
def send():
    user_text = request.json.get('message')
    if user_text:
        channel = bot.get_channel(TARGET_CHANNEL_ID)
        if channel:
            bot.loop.create_task(channel.send(user_text))
            message_log.append(f"<i>(You): {user_text}</i>")
            return jsonify(status="sent")
    return jsonify(status="error"), 400

@app.route('/messages')
def get_messages():
    return jsonify(message_log)

def run_flask():
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(os.getenv('APITOK'))

import os
import asyncio
import threading
from flask import Flask, render_template_string, request, jsonify
import discord
from discord.ext import commands

# --- CONFIGURATION ---
TARGET_CHANNEL_ID = 1303054086454906920

# 1. Setup Discord Bot
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

message_log = []
# This will hold the event loop once the bot starts
loop = None

@bot.event
async def on_ready():
    global loop
    loop = asyncio.get_running_loop()
    print(f'--- Bot Online: {bot.user} ---')

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    if message.channel.id == TARGET_CHANNEL_ID:
        log_entry = f"<b>{message.author.display_name}:</b> {message.content}"
        message_log.append(log_entry)

# 2. Setup Flask
app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Discord Bridge</title>
    <style>
        body { font-family: sans-serif; background: #36393f; color: white; padding: 20px; }
        #log { height: 300px; overflow-y: auto; background: #202225; padding: 10px; border-radius: 5px; margin-bottom: 10px; border: 1px solid #4f545c; }
        .input-box { display: flex; gap: 10px; }
        input { flex-grow: 1; padding: 10px; background: #40444b; color: white; border: none; border-radius: 4px; }
        button { padding: 10px 20px; background: #5865f2; color: white; border: none; border-radius: 4px; cursor: pointer; }
    </style>
</head>
<body>
    <h2>Channel Bridge</h2>
    <div id="log"></div>
    <div class="input-box">
        <input type="text" id="msg" placeholder="Type here..." onkeydown="if(event.key==='Enter') send()">
        <button onclick="send()">Send</button>
    </div>

    <script>
        // FIXED: JavaScript 'async' syntax
        async function send() {
            const input = document.getElementById('msg');
            const text = input.value;
            if(!text) return;

            // Immediate UI feedback
            const log = document.getElementById('log');
            log.innerHTML += `<i>Sending: ${text}...</i><br>`;
            
            try {
                const response = await fetch('/send', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({message: text})
                });
                if (response.ok) {
                    input.value = '';
                }
            } catch (err) {
                console.error("Failed to send:", err);
            }
        }

        async function fetchMessages() {
            try {
                const res = await fetch('/messages');
                const data = await res.json();
                const log = document.getElementById('log');
                log.innerHTML = data.join('<br>');
                log.scrollTop = log.scrollHeight;
            } catch (e) {}
        }

        setInterval(fetchMessages, 1000);
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/send', methods=['POST'])
def send_to_discord():
    data = request.get_json()
    text = data.get('message')
    
    if text and loop:
        channel = bot.get_channel(TARGET_CHANNEL_ID)
        if channel:
            # Thread-safe scheduling of the coroutine
            asyncio.run_coroutine_threadsafe(channel.send(text), loop)
            message_log.append(f"<b>You (Web):</b> {text}")
            return jsonify({"status": "ok"}), 200
    return jsonify({"status": "error"}), 400

@app.route('/messages')
def get_messages():
    return jsonify(message_log)

# 3. Running Logic
def run_flask():
    # Note: Flask must have debug=False when threading like this
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

if __name__ == "__main__":
    # Start Flask in a background thread
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Run the bot in the main thread
    token = os.getenv('APITOK')
    if token:
        bot.run(token)
    else:
        print("CRITICAL: No APITOK found in environment variables.")

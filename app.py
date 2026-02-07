import os
import asyncio
import threading
from flask import Flask, render_template_string, request, jsonify
import discord
from discord.ext import commands

# --- CONFIGURATION ---
TARGET_CHANNEL_ID = 1303054086454906920

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

message_log = []
# We'll use this to safely bridge the Flask thread to the Discord thread
bot_loop = None

@bot.event
async def on_ready():
    global bot_loop
    bot_loop = asyncio.get_running_loop()
    print(f'✅ Bot Online: {bot.user}')
    print(f'✅ Monitoring Channel: {TARGET_CHANNEL_ID}')

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    if message.channel.id == TARGET_CHANNEL_ID:
        log_entry = f"<b>{message.author.display_name}:</b> {message.content}"
        message_log.append(log_entry)
        # Keep log size manageable
        if len(message_log) > 50:
            message_log.pop(0)

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
            body { font-family: sans-serif; background: #36393f; color: white; padding: 20px; max-width: 800px; margin: auto; }
            #log { height: 400px; overflow-y: auto; background: #202225; padding: 15px; border-radius: 8px; margin-bottom: 10px; border: 1px solid #4f545c; }
            .input-box { display: flex; gap: 10px; }
            input { flex: 1; padding: 12px; background: #40444b; color: white; border: none; border-radius: 4px; }
            button { padding: 10px 20px; background: #5865f2; color: white; border: none; border-radius: 4px; cursor: pointer; }
            button:disabled { background: #3c4270; }
        </style>
    </head>
    <body>
        <h2>Channel Bridge</h2>
        <div id="log">Loading messages...</div>
        <div class="input-box">
            <input type="text" id="msg" placeholder="Type a message..." autocomplete="off">
            <button id="sendBtn" onclick="send()">Send</button>
        </div>

        <script>
            const msgInput = document.getElementById('msg');
            const logDiv = document.getElementById('log');

            async function send() {
                const text = msgInput.value.trim();
                if (!text) return;

                // Visual feedback
                msgInput.value = '';
                
                try {
                    const response = await fetch('/send', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({message: text})
                    });
                    if (!response.ok) alert("Failed to send message.");
                } catch (e) {
                    console.error("Send error:", e);
                }
            }

            // Allow Enter key to send
            msgInput.addEventListener("keypress", (e) => {
                if (e.key === "Enter") send();
            });

            async function updateLog() {
                try {
                    const r = await fetch('/messages');
                    const d = await r.json();
                    const newContent = d.join('<br>');
                    if (logDiv.innerHTML !== newContent) {
                        logDiv.innerHTML = newContent;
                        logDiv.scrollTop = logDiv.scrollHeight;
                    }
                } catch (e) { console.error("Update error:", e); }
            }

            setInterval(updateLog, 1000);
        </script>
    </body>
    </html>
    """)

@app.route('/send', methods=['POST'])
def send_msg():
    data = request.get_json()
    text = data.get('message')
    
    if text and bot_loop:
        channel = bot.get_channel(TARGET_CHANNEL_ID)
        if channel:
            # Python 3.13 Thread-Safe Bridge
            asyncio.run_coroutine_threadsafe(channel.send(text), bot_loop)
            message_log.append(f"<i>(You): {text}</i>")
            return jsonify(success=True)
    
    return jsonify(success=False), 400

@app.route('/messages')
def get_messages():
    return jsonify(message_log)

def run_flask():
    # port 5000 is often used by macOS AirPlay, using 5050 for safety
    app.run(host='0.0.0.0', port=5050, debug=False, use_reloader=False)

if __name__ == "__main__":
    token = os.getenv('APITOK')
    if not token:
        print("❌ Error: APITOK environment variable is missing!")
    else:
        # Start Flask in background
        flask_thread = threading.Thread(target=run_flask, daemon=True)
        flask_thread.start()
        
        # Start Discord in foreground
        bot.run(token)

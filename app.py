import os
import threading
import asyncio
from flask import Flask, render_template_string, request, jsonify
import discord
from discord.ext import commands

# 1. Setup Discord Bot
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Global queue to store messages for the web UI
message_log = []

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    # Store incoming Discord messages to show on the web
    message_log.append(f"Discord - {message.author}: {message.content}")
    await bot.process_commands(message)

# 2. Setup Flask Web Server
app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><title>Discord Bridge</title></head>
<body>
    <h2>Send to Discord</h2>
    <input type="text" id="msg" placeholder="Type something...">
    <button onclick="sendMsg()">Send</button>
    
    <h2>Live Chat Log</h2>
    <div id="log" style="border:1px solid #ccc; height:200px; overflow-y:scroll;"></div>

    <script>
        async def sendMsg() {
            const val = document.getElementById('msg').value;
            await fetch('/send', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({message: val})
            });
            document.getElementById('msg').value = '';
        }

        // Poll for new messages every 2 seconds
        setInterval(async () => {
            const res = await fetch('/messages');
            const data = await res.json();
            document.getElementById('log').innerHTML = data.join('<br>');
        }, 2000);
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/send', methods=['POST'])
def send_to_discord():
    user_text = request.json.get('message')
    if user_text:
        message_log.append(f"Web: {user_text}")
        # Send to a specific channel (replace CHANNEL_ID with your actual ID)
        channel = bot.get_channel(1234567890) 
        if channel:
            bot.loop.create_task(channel.send(user_text))
    return jsonify(success=True)

@app.route('/messages')
def get_messages():
    return jsonify(message_log)

# 3. Run both systems
def run_flask():
    app.run(host='0.0.0.0', port=5000)

if __name__ == "__main__":
    # Start Flask in a separate thread
    threading.Thread(target=run_flask).start()
    # Start Discord Bot
    bot.run(os.getenv('APITOK'))

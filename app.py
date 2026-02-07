import os
import threading
import asyncio
from flask import Flask, render_template_string, request, jsonify
import discord
from discord.ext import commands

# 1. Setup Discord Bot
intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

message_log = []

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    # Log messages with Context
    log_entry = f"[{message.guild.name} # {message.channel.name}] {message.author}: {message.content}"
    message_log.append(log_entry)

# 2. Flask Application
app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Discord Multi-Server Bridge</title>
    <style>
        body { font-family: sans-serif; margin: 20px; background: #f4f4f4; }
        #log { border: 1px solid #ccc; height: 300px; overflow-y: scroll; background: white; padding: 10px; margin-top: 10px; }
        .controls { background: white; padding: 15px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }
    </style>
</head>
<body>
    <div class="controls">
        <h2>Discord Controller</h2>
        
        <label>Select Server:</label>
        <select id="guild_select" onchange="updateChannels()">
            <option value="">-- Choose a Server --</option>
        </select>

        <label>Select Channel:</label>
        <select id="channel_select">
            <option value="">-- Choose a Channel --</option>
        </select>
        <br><br>
        <input type="text" id="msg" style="width: 70%" placeholder="Type a message...">
        <button onclick="sendMsg()">Send</button>
    </div>

    <h3>Live Activity Feed</h3>
    <div id="log"></div>

    <script>
        // Fetch Guilds on Load
        async function loadGuilds() {
            const res = await fetch('/get_guilds');
            const guilds = await res.json();
            const select = document.getElementById('guild_select');
            guilds.forEach(g => {
                let opt = document.createElement('option');
                opt.value = g.id;
                opt.innerHTML = g.name;
                select.appendChild(opt);
            });
        }

        // Fetch Channels when Guild changes
        async function updateChannels() {
            const guildId = document.getElementById('guild_select').value;
            const res = await fetch(`/get_channels/${guildId}`);
            const channels = await res.json();
            const select = document.getElementById('channel_select');
            select.innerHTML = '';
            channels.forEach(c => {
                let opt = document.createElement('option');
                opt.value = c.id;
                opt.innerHTML = "# " + c.name;
                select.appendChild(opt);
            });
        }

        async function sendMsg() {
            const channelId = document.getElementById('channel_select').value;
            const text = document.getElementById('msg').value;
            if(!channelId || !text) return alert("Select a channel and type a message!");

            await fetch('/send', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({channel_id: channelId, message: text})
            });
            document.getElementById('msg').value = '';
        }

        setInterval(async () => {
            const res = await fetch('/messages');
            const data = await res.json();
            document.getElementById('log').innerHTML = data.slice().reverse().join('<br>');
        }, 2000);

        window.onload = loadGuilds;
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/get_guilds')
def get_guilds():
    # Returns list of servers the bot is in
    guilds = [{"id": str(g.id), "name": g.name} for g in bot.guilds]
    return jsonify(guilds)

@app.route('/get_channels/<guild_id>')
def get_channels(guild_id):
    guild = bot.get_guild(int(guild_id))
    if not guild: return jsonify([])
    # Only return text channels the bot can actually send messages to
    channels = [{"id": str(c.id), "name": c.name} for c in guild.text_channels]
    return jsonify(channels)

@app.route('/send', methods=['POST'])
def send_to_discord():
    data = request.json
    channel_id = data.get('channel_id')
    user_text = data.get('message')
    
    if channel_id and user_text:
        channel = bot.get_channel(int(channel_id))
        if channel:
            message_log.append(f"Web -> #{channel.name}: {user_text}")
            bot.loop.create_task(channel.send(user_text))
    return jsonify(success=True)

@app.route('/messages')
def get_messages():
    return jsonify(message_log)

def run_flask():
    app.run(host='0.0.0.0', port=5000)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(os.getenv('APITOK'))

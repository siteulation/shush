import os
import threading
import asyncio
from flask import Flask, render_template_string, request, jsonify
import discord
from discord.ext import commands

# 1. Setup Discord Bot with proper Intents
intents = discord.Intents.default()
intents.guilds = True  # Required to see servers
intents.messages = True
intents.message_content = True # Required to read what people type

bot = commands.Bot(command_prefix="!", intents=intents)
message_log = []

@bot.event
async def on_ready():
    print(f'--- Bot is Online: {bot.user} ---')
    print(f'Connected to {len(bot.guilds)} servers.')

@bot.event
async def on_message(message):
    if message.author == bot.user: return
    log_entry = f"[{message.guild.name if message.guild else 'DM'}] {message.author}: {message.content}"
    message_log.append(log_entry)

# 2. Flask Application
app = Flask(__name__)

# NOTE: We use bot.loop.create_task or asyncio.run_coroutine_threadsafe 
# because Flask runs in a different thread than the Discord Bot.

@app.route('/get_guilds')
def get_guilds():
    if not bot.is_ready():
        return jsonify([])
    
    # We use bot.guilds which is the CACHED list. 
    # If this is empty, the bot hasn't finished loading yet.
    guild_data = [{"id": str(g.id), "name": g.name} for g in bot.guilds]
    return jsonify(guild_data)

@app.route('/get_channels/<guild_id>')
def get_channels(guild_id):
    guild = bot.get_guild(int(guild_id))
    if not guild:
        return jsonify([])
    
    # Filter for Text Channels the bot can actually post in
    channels = [
        {"id": str(c.id), "name": c.name} 
        for c in guild.text_channels 
        if c.permissions_for(guild.me).send_messages
    ]
    return jsonify(channels)

@app.route('/send', methods=['POST'])
def send_to_discord():
    data = request.json
    channel_id = data.get('channel_id')
    user_text = data.get('message')
    
    if channel_id and user_text:
        channel = bot.get_channel(int(channel_id))
        if channel:
            # We must use the bot's event loop to send messages from the Flask thread
            bot.loop.create_task(channel.send(user_text))
            message_log.append(f"Web -> #{channel.name}: {user_text}")
            return jsonify(success=True)
    return jsonify(success=False), 400

@app.route('/messages')
def get_messages():
    return jsonify(message_log)

@app.route('/')
def index():
    # Adding a simple 'Refresh' button to the UI in case the cache was empty on first load
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Discord Control Panel</title>
        <style>
            body { font-family: 'Segoe UI', sans-serif; padding: 20px; background: #2c2f33; color: white; }
            select, input, button { padding: 10px; border-radius: 5px; border: none; margin: 5px 0; }
            #log { background: #23272a; height: 300px; overflow-y: scroll; padding: 10px; border: 1px solid #7289da; }
            .box { background: #36393f; padding: 20px; border-radius: 10px; }
        </style>
    </head>
    <body>
        <div class="box">
            <h1>Discord Bridge</h1>
            <button onclick="loadGuilds()">🔄 Refresh Server List</button><br><br>
            
            <label>Server:</label><br>
            <select id="g_select" onchange="updateChannels()" style="width:100%"></select><br>
            
            <label>Channel:</label><br>
            <select id="c_select" style="width:100%"></select><br><br>
            
            <input type="text" id="msg" placeholder="Type a message..." style="width:80%">
            <button onclick="sendMsg()" style="background:#7289da; color:white; width:15%">Send</button>
        </div>

        <h3>Live Feed</h3>
        <div id="log"></div>

        <script>
            async function loadGuilds() {
                const r = await fetch('/get_guilds');
                const guilds = await r.json();
                const s = document.getElementById('g_select');
                s.innerHTML = '<option>-- Select Server --</option>';
                guilds.forEach(g => s.innerHTML += `<option value="${g.id}">${g.name}</option>`);
            }

            async function updateChannels() {
                const gid = document.getElementById('g_select').value;
                const r = await fetch('/get_channels/' + gid);
                const channels = await r.json();
                const s = document.getElementById('c_select');
                s.innerHTML = '';
                channels.forEach(c => s.innerHTML += `<option value="${c.id}"># ${c.name}</option>`);
            }

            async function sendMsg() {
                const cid = document.getElementById('c_select').value;
                const txt = document.getElementById('msg').value;
                await fetch('/send', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({channel_id: cid, message: txt})
                });
                document.getElementById('msg').value = '';
            }

            setInterval(async () => {
                const r = await fetch('/messages');
                const data = await r.json();
                document.getElementById('log').innerHTML = data.slice().reverse().join('<br>');
            }, 2000);

            window.onload = loadGuilds;
        </script>
    </body>
    </html>
    """)

# 3. Execution Logic
def run_flask():
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

if __name__ == "__main__":
    t = threading.Thread(target=run_flask)
    t.daemon = True
    t.start()
    
    token = os.getenv('APITOK')
    if not token:
        print("ERROR: APITOK environment variable not found!")
    else:
        bot.run(token)

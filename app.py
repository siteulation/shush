import os
import asyncio
import threading
import queue
from flask import Flask, render_template_string, request, jsonify
import discord
from discord.ext import commands
from discord.ext import voice_recv

# --- CONFIGURATION ---
TEXT_CHANNEL_ID = 1303054086454906920
VOICE_CHANNEL_ID = 1462980688256040970

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)
message_log = []
bot_loop = None
vc_client = None

# --- DISCORD LOGIC ---
@bot.event
async def on_ready():
    global bot_loop
    bot_loop = asyncio.get_running_loop()
    print(f'✅ Connected as {bot.user}')

@bot.event
async def on_message(message):
    if message.author == bot.user: return
    if message.channel.id == TEXT_CHANNEL_ID:
        message_log.append(f"<b>{message.author.display_name}:</b> {message.content}")

# --- FLASK SERVER ---
app = Flask(__name__)

@app.route('/')
def index():
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Discord Unified Bridge</title>
        <style>
            body { font-family: sans-serif; background: #2c2f33; color: white; display: grid; grid-template-columns: 1fr 300px; height: 100vh; margin: 0; }
            #chat-section { display: flex; flex-direction: column; padding: 20px; border-right: 1px solid #444; }
            #voice-section { padding: 20px; background: #23272a; }
            #log { flex: 1; overflow-y: auto; background: #202225; padding: 10px; border-radius: 5px; margin-bottom: 10px; }
            input { width: 100%; padding: 10px; box-sizing: border-box; background: #40444b; color: white; border: none; }
            .btn { padding: 10px; margin: 5px 0; width: 100%; cursor: pointer; border: none; border-radius: 4px; color: white; font-weight: bold; }
            .join { background: #43b581; } .leave { background: #f04747; } .action { background: #5865f2; }
        </style>
    </head>
    <body>
        <div id="chat-section">
            <div id="log"></div>
            <input type="text" id="msg" placeholder="Send text message..." onkeydown="if(event.key==='Enter') sendText()">
        </div>
        <div id="voice-section">
            <h3>Voice Controls</h3>
            <button class="btn join" onclick="voiceAction('join')">Join Voice</button>
            <button class="btn action" onclick="voiceAction('mute')">Mute / Unmute</button>
            <button class="btn action" onclick="voiceAction('deafen')">Deafen / Undeafen</button>
            <button class="btn leave" onclick="voiceAction('leave')">Disconnect</button>
            <hr>
            <p><small>Note: Real-time browser audio streaming requires a WebRTC gateway. Currently supports Push-to-Talk via Server.</small></p>
        </div>

        <script>
            async function sendText() {
                const i = document.getElementById('msg');
                await fetch('/send_text', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({message: i.value})
                });
                i.value = '';
            }

            async function voiceAction(type) {
                await fetch('/voice_control', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({action: type})
                });
            }

            setInterval(async () => {
                const r = await fetch('/get_messages');
                const d = await r.json();
                const l = document.getElementById('log');
                l.innerHTML = d.join('<br>');
                l.scrollTop = l.scrollHeight;
            }, 1000);
        </script>
    </body>
    </html>
    """)

@app.route('/get_messages')
def get_messages():
    return jsonify(message_log)

@app.route('/send_text', methods=['POST'])
def send_text():
    text = request.json.get('message')
    if text and bot_loop:
        channel = bot.get_channel(TEXT_CHANNEL_ID)
        asyncio.run_coroutine_threadsafe(channel.send(text), bot_loop)
        message_log.append(f"<i>(You): {text}</i>")
    return jsonify(success=True)

@app.route('/voice_control', methods=['POST'])
def voice_control():
    global vc_client
    action = request.json.get('action')
    
    if not bot_loop: return jsonify(error="Bot not ready"), 400

    async def handle_voice():
        global vc_client
        if action == 'join':
            channel = bot.get_channel(VOICE_CHANNEL_ID)
            vc_client = await channel.connect(cls=voice_recv.VoiceRecvClient)
        elif vc_client:
            if action == 'leave':
                await vc_client.disconnect()
                vc_client = None
            elif action == 'mute':
                await vc_client.main_ws.voice_state(guild_id=vc_client.guild.id, channel_id=vc_client.channel.id, self_mute=not vc_client.self_mute)
            elif action == 'deafen':
                await vc_client.main_ws.voice_state(guild_id=vc_client.guild.id, channel_id=vc_client.channel.id, self_mute=vc_client.self_mute, self_deaf=not vc_client.self_deaf)

    asyncio.run_coroutine_threadsafe(handle_voice(), bot_loop)
    return jsonify(success=True)

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5050, debug=False, use_reloader=False), daemon=True).start()
    bot.run(os.getenv('APITOK'))

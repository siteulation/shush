import os
import asyncio
import threading
from flask import Flask, render_template_string
from flask_socketio import SocketIO
import discord
from discord.ext import commands
from gtts import gTTS

# --- CONFIG ---
TEXT_CHANNEL_ID = 1303054086454906920
VOICE_CHANNEL_ID = 1462980688256040970

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix="!", intents=intents)

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

bot_loop = None
vc_client = None

# --- DISCORD EVENTS ---
@bot.event
async def on_ready():
    global bot_loop
    bot_loop = asyncio.get_running_loop()
    print(f'✅ TTS Bot Online: {bot.user}')

@bot.event
async def on_voice_state_update(member, before, after):
    if member == bot.user:
        status = "Connected" if after.channel else "Disconnected"
        socketio.emit('status', {'status': status})

# --- WEB UI ---
@app.route('/')
def index():
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Discord TTS Control</title>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
        <style>
            body { font-family: sans-serif; background: #2c2f33; color: white; padding: 40px; text-align: center; }
            .container { max-width: 500px; margin: auto; background: #36393f; padding: 30px; border-radius: 10px; }
            input { width: 100%; padding: 15px; margin: 20px 0; border-radius: 5px; border: none; box-sizing: border-box; }
            button { width: 100%; padding: 12px; cursor: pointer; border: none; border-radius: 5px; color: white; font-weight: bold; margin-bottom: 10px; }
            .join { background: #43b581; } .leave { background: #f04747; } .send { background: #5865f2; }
            #status { margin-bottom: 20px; font-weight: bold; }
        </style>
    </head>
    <body>
        <div class="container">
            <h2>TTS Voice Bridge</h2>
            <div id="status">Status: Checking...</div>
            <button class="join" onclick="vCmd('join')">Join Voice Channel</button>
            <button class="leave" onclick="vCmd('leave')">Disconnect Bot</button>
            <hr>
            <input type="text" id="ttsInput" placeholder="Type text to speak..." onkeydown="if(event.key==='Enter') sendTTS()">
            <button class="send" onclick="sendTTS()">Speak in Discord</button>
        </div>

        <script>
            const socket = io();
            socket.on('status', d => {
                document.getElementById('status').innerText = "Status: " + d.status;
                document.getElementById('status').style.color = d.status === "Connected" ? "#43b581" : "#f04747";
            });

            function vCmd(action) { socket.emit('voice_action', {action}); }
            
            function sendTTS() {
                const i = document.getElementById('ttsInput');
                if(!i.value) return;
                socket.emit('send_tts', {text: i.value});
                i.value = '';
            }
        </script>
    </body>
    </html>
    """)

# --- SOCKET HANDLERS ---
@socketio.on('send_tts')
def handle_tts(data):
    global vc_client
    text = data.get('text')
    
    if vc_client and vc_client.is_connected():
        # 1. Generate TTS File
        tts = gTTS(text=text, lang='en')
        tts.save("tts.mp3")
        
        # 2. Play in Discord (using FFmpeg)
        if vc_client.is_playing():
            vc_client.stop()
        
        vc_client.play(discord.FFmpegPCMAudio("tts.mp3"))

@socketio.on('voice_action')
def handle_voice(data):
    global vc_client
    action = data['action']

    async def vc_task():
        global vc_client
        if action == 'join':
            ch = bot.get_channel(VOICE_CHANNEL_ID)
            if vc_client: await vc_client.disconnect()
            vc_client = await ch.connect()
        elif action == 'leave' and vc_client:
            await vc_client.disconnect()
            vc_client = None

    if bot_loop:
        asyncio.run_coroutine_threadsafe(vc_task(), bot_loop)

if __name__ == "__main__":
    # Start Web Server
    threading.Thread(target=lambda: socketio.run(app, host='0.0.0.0', port=5050, allow_unsafe_werkzeug=True), daemon=True).start()
    # Start Discord Bot
    bot.run(os.getenv('APITOK'))

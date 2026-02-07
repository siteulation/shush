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
    print(f'✅ Unified Bot Online: {bot.user}')

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    # Report back to web if message is in our target text channel
    if message.channel.id == TEXT_CHANNEL_ID:
        socketio.emit('chat_msg', {
            'user': message.author.display_name,
            'text': message.content
        })

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
        <title>Discord Unified Panel</title>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
        <style>
            body { font-family: 'Segoe UI', sans-serif; background: #2c2f33; color: white; display: flex; height: 100vh; margin: 0; }
            #sidebar { width: 300px; background: #23272a; padding: 20px; border-right: 1px solid #444; display: flex; flex-direction: column; gap: 10px; }
            #main { flex: 1; display: flex; flex-direction: column; padding: 20px; }
            #chat-log { flex: 1; background: #202225; overflow-y: auto; padding: 15px; border-radius: 8px; margin-bottom: 15px; border: 1px solid #444; }
            .input-group { display: flex; flex-direction: column; gap: 5px; margin-top: 10px; }
            input { padding: 12px; background: #40444b; color: white; border: none; border-radius: 4px; outline: none; }
            button { padding: 10px; border: none; border-radius: 4px; color: white; font-weight: bold; cursor: pointer; }
            .btn-join { background: #43b581; } .btn-leave { background: #f04747; } .btn-send { background: #5865f2; }
            .label { font-size: 0.8em; color: #b9bbbe; text-transform: uppercase; font-weight: bold; }
        </style>
    </head>
    <body>
        <div id="sidebar">
            <h3>Voice Controls</h3>
            <div id="status" style="color: #f04747; font-weight: bold; margin-bottom: 10px;">Status: Disconnected</div>
            <button class="btn-join" onclick="vCmd('join')">Join Voice Channel</button>
            <button class="btn-leave" onclick="vCmd('leave')">Disconnect Bot</button>
            <hr style="width:100%; border: 0.5px solid #444;">
            <div class="input-group">
                <span class="label">Text-to-Speech</span>
                <input type="text" id="ttsInput" placeholder="Make bot speak..." onkeydown="if(event.key==='Enter') sendTTS()">
                <button class="btn-send" onclick="sendTTS()">Speak</button>
            </div>
        </div>
        <div id="main">
            <h3>Text Channel Bridge</h3>
            <div id="chat-log"></div>
            <div class="input-group">
                <span class="label">Send Message</span>
                <input type="text" id="chatInput" placeholder="Message #channel..." onkeydown="if(event.key==='Enter') sendChat()">
            </div>
        </div>

        <script>
            const socket = io();
            const log = document.getElementById('chat-log');

            socket.on('status', d => {
                const s = document.getElementById('status');
                s.innerText = "Status: " + d.status;
                s.style.color = d.status === "Connected" ? "#43b581" : "#f04747";
            });

            socket.on('chat_msg', d => {
                log.innerHTML += `<div><b style="color:#7289da">${d.user}:</b> ${d.text}</div>`;
                log.scrollTop = log.scrollHeight;
            });

            function vCmd(action) { socket.emit('voice_action', {action}); }

            function sendTTS() {
                const i = document.getElementById('ttsInput');
                if(!i.value) return;
                socket.emit('send_tts', {text: i.value});
                i.value = '';
            }

            function sendChat() {
                const i = document.getElementById('chatInput');
                if(!i.value) return;
                socket.emit('send_chat', {text: i.value});
                log.innerHTML += `<div><i style="color:#b9bbbe">(You): ${i.value}</i></div>`;
                log.scrollTop = log.scrollHeight;
                i.value = '';
            }
        </script>
    </body>
    </html>
    """)

# --- SOCKET HANDLERS ---
@socketio.on('send_chat')
def handle_chat(data):
    if bot_loop:
        channel = bot.get_channel(TEXT_CHANNEL_ID)
        asyncio.run_coroutine_threadsafe(channel.send(data['text']), bot_loop)

@socketio.on('send_tts')
def handle_tts(data):
    global vc_client
    text = data.get('text')
    if vc_client and vc_client.is_connected():
        tts = gTTS(text=text, lang='en')
        tts.save("tts.mp3")
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
    threading.Thread(target=lambda: socketio.run(app, host='0.0.0.0', port=5050, allow_unsafe_werkzeug=True), daemon=True).start()
    bot.run(os.getenv('APITOK'))

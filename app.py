import os
import asyncio
import threading
import numpy as np
import io
from flask import Flask, render_template_string, request, jsonify
from flask_socketio import SocketIO
from werkzeug.utils import secure_filename
import discord
from discord.ext import commands
from gtts import gTTS

# --- CONFIG ---
TEXT_CHANNEL_ID = 1303054086454906920
VC_CHANNELS = {"fomo": 1462980688256040970, "botspam": 1470121574672765068}
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix="!", intents=intents)

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

bot_loop = None
vc_client = None
current_volume = 0.5

# --- THE MIXER ---
class LiveMixer(discord.AudioSource):
    def __init__(self):
        self.sources = [] # List of active PCM streams

    def add_source(self, source_path):
        # We use FFmpeg to convert any file to raw PCM for the mixer
        new_source = discord.FFmpegPCMAudio(source_path, options="-f s16le -ar 48000 -ac 2")
        self.sources.append(new_source)

    def read(self):
        # Discord expects 20ms of audio (3840 bytes for 48k/stereo/16bit)
        final_buffer = np.zeros(1920, dtype=np.int32) # Use int32 to prevent overflow during mixing
        
        to_remove = []
        for src in self.sources:
            data = src.read()
            if not data:
                to_remove.append(src)
                continue
            
            # Convert bytes to numpy array
            chunk = np.frombuffer(data, dtype=np.int16)
            # Mix chunk into final buffer
            final_buffer[:len(chunk)] += chunk

        for src in to_remove:
            self.sources.remove(src)

        # Apply global volume and clip to 16-bit range
        final_buffer = np.clip(final_buffer * current_volume, -32768, 32767).astype(np.int16)
        return final_buffer.tobytes()

    def is_opus(self):
        return False

mixer = LiveMixer()

# --- DISCORD LOGIC ---
@bot.event
async def on_ready():
    global bot_loop
    bot_loop = asyncio.get_running_loop()
    print(f'✅ Mixer Bot Online: {bot.user}')

@bot.event
async def on_message(message):
    if message.author == bot.user or message.channel.id != TEXT_CHANNEL_ID: return
    socketio.emit('chat_msg', {'user': message.author.display_name, 'text': message.content})

# --- FLASK ROUTES (Keep UI from previous version) ---
@app.route('/')
def index():
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Discord Mixer Panel</title>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
        <style>
            body { font-family: sans-serif; background: #2c2f33; color: white; display: flex; height: 100vh; margin: 0; }
            #sidebar { width: 350px; background: #23272a; padding: 20px; border-right: 1px solid #444; overflow-y: auto; }
            #main { flex: 1; display: flex; flex-direction: column; padding: 20px; }
            #chat-log { flex: 1; background: #202225; overflow-y: auto; padding: 15px; border-radius: 8px; margin-bottom: 15px; }
            .section { margin-bottom: 20px; padding: 15px; background: #2f3136; border-radius: 8px; }
            button, input, select { width: 100%; padding: 10px; margin-top: 5px; border-radius: 4px; border: none; box-sizing: border-box; }
            button { cursor: pointer; font-weight: bold; color: white; background: #5865f2; }
            .join { background: #43b581; } .leave { background: #f04747; }
            .sound-btn { background: #4f545c; font-size: 0.8em; text-align: left; margin-top: 2px; }
        </style>
    </head>
    <body>
        <div id="sidebar">
            <div class="section">
                <select id="vcSelect"><option value="fomo">Fomo</option><option value="botspam">Botspam</option></select>
                <button class="join" onclick="vCmd('join')">Connect</button>
                <button class="leave" onclick="vCmd('leave')">Disconnect</button>
            </div>
            <div class="section">
                <label>Vol: <input type="range" min="0" max="100" value="50" oninput="socket.emit('set_volume', {v: this.value/100})"></label>
            </div>
            <div class="section">
                <input type="text" id="ttsIn" placeholder="Type TTS..."><button onclick="sendTTS()">Speak (Overlay)</button>
            </div>
            <div class="section">
                <input type="file" id="fIn" accept=".mp3"><button onclick="upload()">Upload & Play</button>
            </div>
            <div class="section"><strong>Saved:</strong><div id="sList"></div></div>
        </div>
        <div id="main">
            <div id="chat-log"></div>
            <input type="text" id="cIn" placeholder="Chat..." onkeydown="if(event.key==='Enter') sendChat()">
        </div>
        <script>
            const socket = io();
            function vCmd(action) { socket.emit('voice_action', {action, chan: document.getElementById('vcSelect').value}); }
            function sendTTS() { socket.emit('send_tts', {text: document.getElementById('ttsIn').value}); document.getElementById('ttsIn').value=''; }
            function sendChat() { const i=document.getElementById('cIn'); socket.emit('send_chat', {text: i.value}); i.value=''; }
            async function upload() {
                const fd = new FormData(); fd.append('file', document.getElementById('fIn').files[0]);
                await fetch('/upload', {method: 'POST', body: fd});
                refreshSounds();
            }
            async function refreshSounds() {
                const res = await fetch('/list_sounds');
                const sounds = await res.json();
                const div = document.getElementById('sList'); div.innerHTML = '';
                sounds.forEach(s => {
                    const b = document.createElement('button'); b.className='sound-btn'; b.innerText="🔊 "+s;
                    b.onclick = () => socket.emit('play_saved', {n: s});
                    div.appendChild(b);
                });
            }
            socket.on('chat_msg', d => { document.getElementById('chat-log').innerHTML += `<div><b>${d.user}:</b> ${d.text}</div>`; });
            window.onload = refreshSounds;
        </script>
    </body>
    </html>
    """)

# --- HANDLERS ---
@socketio.on('set_volume')
def h_vol(data): global current_volume; current_volume = data['v']

@socketio.on('send_tts')
def h_tts(data):
    path = f"tts_{threading.get_ident()}.mp3"
    gTTS(text=data['text'], lang='en').save(path)
    mixer.add_source(path)

@socketio.on('play_saved')
def h_saved(data):
    mixer.add_source(os.path.join(UPLOAD_FOLDER, secure_filename(data['n'])))

@app.route('/upload', methods=['POST'])
def h_up():
    file = request.files['file']
    path = os.path.join(UPLOAD_FOLDER, secure_filename(file.filename))
    file.save(path)
    mixer.add_source(path)
    return "OK"

@app.route('/list_sounds')
def l_s(): return jsonify([f for f in os.listdir(UPLOAD_FOLDER) if f.endswith('.mp3')])

@socketio.on('voice_action')
def h_voice(data):
    async def vc_task():
        global vc_client
        if data['action'] == 'join':
            if vc_client: await vc_client.disconnect()
            vc_client = await bot.get_channel(VC_CHANNELS[data['chan']]).connect()
            vc_client.play(mixer) # The mixer stays active forever
        elif vc_client: await vc_client.disconnect()
    asyncio.run_coroutine_threadsafe(vc_task(), bot_loop)

@socketio.on('send_chat')
def h_chat(data):
    asyncio.run_coroutine_threadsafe(bot.get_channel(TEXT_CHANNEL_ID).send(data['text']), bot_loop)

if __name__ == "__main__":
    threading.Thread(target=lambda: socketio.run(app, host='0.0.0.0', port=5050, allow_unsafe_werkzeug=True), daemon=True).start()
    bot.run(os.getenv('APITOK'))

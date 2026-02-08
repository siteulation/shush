import os
import asyncio
import threading
from flask import Flask, render_template_string, request, jsonify
from flask_socketio import SocketIO
from werkzeug.utils import secure_filename
import discord
from discord.ext import commands
from gtts import gTTS

# --- CONFIG ---
TEXT_CHANNEL_ID = 1303054086454906920
VC_CHANNELS = {
    "fomo": 1462980688256040970,
    "botspam": 1470121574672765068
}
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix="!", intents=intents)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
socketio = SocketIO(app, cors_allowed_origins="*")

bot_loop = None
vc_client = None
current_volume = 0.5

# --- HELPERS ---
def play_audio(path):
    """Plays audio without stopping current playback if possible."""
    global vc_client
    if vc_client and vc_client.is_connected():
        # Note: discord.py handles one play() at a time. 
        # To truly overlay, we'd need an audio mixer. 
        # For now, we check if playing; if so, we wait or queue.
        # This version simply ensures we don't MANUALLY call .stop()
        source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(path), volume=current_volume)
        
        # If already playing, we let the new one start (this may still cut off 
        # the old one depending on the FFmpeg process handling, but removes the force-stop)
        if vc_client.is_playing():
            print("Audio already playing - starting new stream.")
        
        vc_client.play(source)

# --- DISCORD EVENTS ---
@bot.event
async def on_ready():
    global bot_loop
    bot_loop = asyncio.get_running_loop()
    print(f'✅ Bot Online: {bot.user}')

@bot.event
async def on_message(message):
    if message.author == bot.user or message.channel.id != TEXT_CHANNEL_ID:
        return
    socketio.emit('chat_msg', {'user': message.author.display_name, 'text': message.content})

# --- FLASK ROUTES ---
@app.route('/')
def index():
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Discord Master Control</title>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
        <style>
            body { font-family: 'Segoe UI', sans-serif; background: #2c2f33; color: white; display: flex; height: 100vh; margin: 0; }
            #sidebar { width: 350px; background: #23272a; padding: 20px; border-right: 1px solid #444; overflow-y: auto; }
            #main { flex: 1; display: flex; flex-direction: column; padding: 20px; }
            #chat-log { flex: 1; background: #202225; overflow-y: auto; padding: 15px; border-radius: 8px; margin-bottom: 15px; }
            .section { margin-bottom: 20px; padding: 15px; background: #2f3136; border-radius: 8px; }
            button, input, select { width: 100%; padding: 10px; margin-top: 5px; border-radius: 4px; border: none; box-sizing: border-box; }
            button { cursor: pointer; font-weight: bold; color: white; background: #5865f2; }
            .sound-btn { background: #4f545c; margin-top: 5px; font-size: 0.8em; text-align: left; }
            .join { background: #43b581; } .leave { background: #f04747; }
        </style>
    </head>
    <body>
        <div id="sidebar">
            <h3>Voice & Soundboard</h3>
            
            <div class="section">
                <label>Channel:</label>
                <select id="vcSelect">
                    <option value="fomo">Fomo</option>
                    <option value="botspam">Botspam</option>
                </select>
                <button class="join" onclick="vCmd('join')">Join</button>
                <button class="leave" onclick="vCmd('leave')">Leave</button>
            </div>

            <div class="section">
                <label>Volume: <span id="volVal">50%</span></label>
                <input type="range" min="0" max="100" value="50" oninput="updateVol(this.value)">
            </div>

            <div class="section">
                <label>TTS</label>
                <input type="text" id="ttsInput" placeholder="Enter text...">
                <button onclick="sendTTS()">Speak</button>
            </div>

            <div class="section">
                <label>Upload Sound</label>
                <input type="file" id="soundFile" accept=".mp3">
                <button onclick="uploadSound()">Upload</button>
            </div>

            <div class="section">
                <label>Saved Sounds</label>
                <div id="soundList"></div>
            </div>
        </div>

        <div id="main">
            <h3>Chat Bridge</h3>
            <div id="chat-log"></div>
            <input type="text" id="chatInput" placeholder="Message Discord..." onkeydown="if(event.key==='Enter') sendChat()">
        </div>

        <script>
            const socket = io();
            
            function vCmd(action) { socket.emit('voice_action', {action, chan: document.getElementById('vcSelect').value}); }
            function updateVol(val) { 
                document.getElementById('volVal').innerText = val + "%";
                socket.emit('set_volume', {volume: val / 100}); 
            }
            function sendTTS() { socket.emit('send_tts', {text: document.getElementById('ttsInput').value}); document.getElementById('ttsInput').value = ''; }

            async function uploadSound() {
                const file = document.getElementById('soundFile').files[0];
                if (!file) return;
                const fd = new FormData(); fd.append('file', file);
                await fetch('/upload', {method: 'POST', body: fd});
                refreshSounds();
            }

            async function refreshSounds() {
                const res = await fetch('/list_sounds');
                const sounds = await res.json();
                const div = document.getElementById('soundList');
                div.innerHTML = '';
                sounds.forEach(s => {
                    const btn = document.createElement('button');
                    btn.className = 'sound-btn';
                    btn.innerText = "🔊 " + s;
                    btn.onclick = () => socket.emit('play_saved', {filename: s});
                    div.appendChild(btn);
                });
            }

            function sendChat() {
                const i = document.getElementById('chatInput');
                socket.emit('send_chat', {text: i.value});
                document.getElementById('chat-log').innerHTML += `<div><i>(You): ${i.value}</i></div>`;
                i.value = '';
            }

            socket.on('chat_msg', d => {
                document.getElementById('chat-log').innerHTML += `<div><b>${d.user}:</b> ${d.text}</div>`;
            });

            window.onload = refreshSounds;
        </script>
    </body>
    </html>
    """)

@app.route('/list_sounds')
def list_sounds():
    files = [f for f in os.listdir(UPLOAD_FOLDER) if f.endswith('.mp3')]
    return jsonify(files)

@app.route('/upload', methods=['POST'])
def upload_file():
    file = request.files.get('file')
    if file and file.filename.endswith('.mp3'):
        filename = secure_filename(file.filename)
        path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(path)
        play_audio(path)
        return "OK"
    return "Error", 400

# --- SOCKETS ---
@socketio.on('set_volume')
def handle_vol(data):
    global current_volume
    current_volume = data['volume']

@socketio.on('play_saved')
def play_saved(data):
    path = os.path.join(UPLOAD_FOLDER, secure_filename(data['filename']))
    play_audio(path)

@socketio.on('send_tts')
def handle_tts(data):
    if data.get('text'):
        path = "tts_temp.mp3"
        gTTS(text=data['text'], lang='en').save(path)
        play_audio(path)

@socketio.on('send_chat')
def handle_chat(data):
    if bot_loop:
        asyncio.run_coroutine_threadsafe(bot.get_channel(TEXT_CHANNEL_ID).send(data['text']), bot_loop)

@socketio.on('voice_action')
def handle_voice(data):
    async def vc_task():
        global vc_client
        if data['action'] == 'join':
            target = VC_CHANNELS.get(data['chan'])
            if vc_client: await vc_client.disconnect()
            vc_client = await bot.get_channel(target).connect()
        elif data['action'] == 'leave' and vc_client:
            await vc_client.disconnect()
            vc_client = None
    if bot_loop: asyncio.run_coroutine_threadsafe(vc_task(), bot_loop)

if __name__ == "__main__":
    threading.Thread(target=lambda: socketio.run(app, host='0.0.0.0', port=5050, allow_unsafe_werkzeug=True), daemon=True).start()
    bot.run(os.getenv('APITOK'))

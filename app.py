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
current_volume = 0.5 # Default 50%

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
            #sidebar { width: 320px; background: #23272a; padding: 20px; border-right: 1px solid #444; overflow-y: auto; }
            #main { flex: 1; display: flex; flex-direction: column; padding: 20px; }
            #chat-log { flex: 1; background: #202225; overflow-y: auto; padding: 15px; border-radius: 8px; margin-bottom: 15px; }
            .section { margin-bottom: 20px; padding: 15px; background: #2f3136; border-radius: 8px; }
            button, input, select { width: 100%; padding: 10px; margin-top: 5px; border-radius: 4px; border: none; box-sizing: border-box; }
            button { cursor: pointer; font-weight: bold; color: white; background: #5865f2; }
            .join { background: #43b581; } .leave { background: #f04747; }
            .vol-label { display: flex; justify-content: space-between; font-size: 12px; margin-top: 10px; }
        </style>
    </head>
    <body>
        <div id="sidebar">
            <h3>Voice Control</h3>
            <div class="section">
                <label>Select Channel:</label>
                <select id="vcSelect">
                    <option value="fomo">Fomo</option>
                    <option value="botspam">Botspam</option>
                </select>
                <button class="join" onclick="vCmd('join')">Join Channel</button>
                <button class="leave" onclick="vCmd('leave')">Disconnect</button>
            </div>

            <div class="section">
                <label>Volume Control</label>
                <input type="range" min="0" max="100" value="50" onchange="updateVol(this.value)">
                <div class="vol-label"><span>0%</span><span id="volVal">50%</span><span>100%</span></div>
            </div>

            <div class="section">
                <label>TTS (Text-to-Speech)</label>
                <input type="text" id="ttsInput" placeholder="Make bot talk...">
                <button onclick="sendTTS()">Speak</button>
            </div>

            <div class="section">
                <label>Upload Sound (.mp3)</label>
                <input type="file" id="soundFile" accept=".mp3">
                <button onclick="uploadSound()">Upload & Play</button>
            </div>
        </div>

        <div id="main">
            <h3>Text Chat (#{{ text_id }})</h3>
            <div id="chat-log"></div>
            <input type="text" id="chatInput" placeholder="Message Discord..." onkeydown="if(event.key==='Enter') sendChat()">
        </div>

        <script>
            const socket = io();
            const log = document.getElementById('chat-log');

            function vCmd(action) { 
                const chan = document.getElementById('vcSelect').value;
                socket.emit('voice_action', {action, chan}); 
            }

            function updateVol(val) {
                document.getElementById('volVal').innerText = val + "%";
                socket.emit('set_volume', {volume: val / 100});
            }

            function sendTTS() {
                const i = document.getElementById('ttsInput');
                socket.emit('send_tts', {text: i.value});
                i.value = '';
            }

            async function uploadSound() {
                const fileInput = document.getElementById('soundFile');
                if (fileInput.files.length === 0) return;
                const formData = new FormData();
                formData.append('file', fileInput.files[0]);
                await fetch('/upload', {method: 'POST', body: formData});
                fileInput.value = '';
            }

            function sendChat() {
                const i = document.getElementById('chatInput');
                socket.emit('send_chat', {text: i.value});
                log.innerHTML += `<div><i style="color:#888">(You): ${i.value}</i></div>`;
                log.scrollTop = log.scrollHeight;
                i.value = '';
            }

            socket.on('chat_msg', d => {
                log.innerHTML += `<div><b>${d.user}:</b> ${d.text}</div>`;
                log.scrollTop = log.scrollHeight;
            });
        </script>
    </body>
    </html>
    """, text_id=TEXT_CHANNEL_ID)

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files: return "No file", 400
    file = request.files['file']
    if file.filename == '': return "No filename", 400
    if file and file.filename.endswith('.mp3'):
        filename = secure_filename(file.filename)
        path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(path)
        play_audio(path)
        return "Playing", 200
    return "Invalid file", 400

# --- SOCKET HANDLERS ---
@socketio.on('set_volume')
def handle_vol(data):
    global current_volume
    current_volume = data['volume']

@socketio.on('send_chat')
def handle_chat(data):
    if bot_loop:
        channel = bot.get_channel(TEXT_CHANNEL_ID)
        asyncio.run_coroutine_threadsafe(channel.send(data['text']), bot_loop)

@socketio.on('send_tts')
def handle_tts(data):
    text = data.get('text')
    if text:
        tts = gTTS(text=text, lang='en')
        path = "tts.mp3"
        tts.save(path)
        play_audio(path)

def play_audio(path):
    global vc_client
    if vc_client and vc_client.is_connected():
        if vc_client.is_playing(): vc_client.stop()
        # PCMVolumeTransformer allows live volume adjustment
        source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(path), volume=current_volume)
        vc_client.play(source)

@socketio.on('voice_action')
def handle_voice(data):
    global vc_client
    action = data['action']
    chan_key = data['chan']
    
    async def vc_task():
        global vc_client
        if action == 'join':
            target_id = VC_CHANNELS.get(chan_key)
            if vc_client: await vc_client.disconnect()
            vc_client = await bot.get_channel(target_id).connect()
        elif action == 'leave' and vc_client:
            await vc_client.disconnect()
            vc_client = None

    if bot_loop: asyncio.run_coroutine_threadsafe(vc_task(), bot_loop)

if __name__ == "__main__":
    threading.Thread(target=lambda: socketio.run(app, host='0.0.0.0', port=5050, allow_unsafe_werkzeug=True), daemon=True).start()
    bot.run(os.getenv('APITOK'))

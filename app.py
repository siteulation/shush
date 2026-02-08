import os
import asyncio
import threading
import numpy as np
from flask import Flask, render_template_string, request, jsonify
from flask_socketio import SocketIO
from werkzeug.utils import secure_filename
import discord
from discord.ext import commands
from gtts import gTTS

# --- CONFIG ---
TEXT_ID = 1303054086454906920
VC_CHANNELS = {"fomo": 1462980688256040970, "botspam": 1470121574672765068}
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.voice_states = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

bot_loop = None
vc_client = None
current_volume = 0.5

# --- MIXER ENGINE ---
class LiveMixer(discord.AudioSource):
    def __init__(self):
        self.sources = []
    def add_source(self, path):
        self.sources.append(discord.FFmpegPCMAudio(path, options="-f s16le -ar 48000 -ac 2"))
    def stop_all(self):
        for s in self.sources: s.cleanup()
        self.sources = []
    def read(self):
        final_buffer = np.zeros(1920, dtype=np.int32)
        to_remove = []
        for src in self.sources:
            data = src.read()
            if not data:
                to_remove.append(src)
                continue
            chunk = np.frombuffer(data, dtype=np.int16)
            final_buffer[:len(chunk)] += chunk
        for src in to_remove: self.sources.remove(src)
        return np.clip(final_buffer * current_volume, -32768, 32767).astype(np.int16).tobytes()
    def is_opus(self): return False

mixer = LiveMixer()

# --- DISCORD EVENTS ---
@bot.event
async def on_ready():
    global bot_loop
    bot_loop = asyncio.get_running_loop()
    print(f'✅ {bot.user} Online')

@bot.event
async def on_message(message):
    if message.channel.id != TEXT_ID: return
    img_url = message.attachments[0].url if message.attachments else None
    socketio.emit('chat_msg', {
        'user': message.author.display_name,
        'pfp': str(message.author.display_avatar.url),
        'text': message.content,
        'img': img_url,
        'is_me': message.author == bot.user
    })

# --- UI & LOGIC ---
@app.route('/')
def index():
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Discord Master Station</title>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
        <style>
            body { font-family: 'Segoe UI', sans-serif; background: #36393f; color: #dcddde; display: flex; height: 100vh; margin: 0; }
            #side { width: 340px; background: #2f3136; padding: 15px; border-right: 1px solid #202225; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; }
            #chat-wrap { flex: 1; display: flex; flex-direction: column; background: #36393f; }
            #log { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; }
            .msg { display: flex; gap: 12px; margin-bottom: 15px; align-items: flex-start; }
            .msg img.pfp { width: 38px; height: 38px; border-radius: 50%; background: #202225; }
            .msg-content { background: #40444b; padding: 10px; border-radius: 8px; max-width: 75%; position: relative; }
            .msg-me { flex-direction: row-reverse; }
            .msg-me .msg-content { background: #5865f2; color: white; }
            .attach-img { max-width: 100%; border-radius: 4px; margin-top: 8px; cursor: pointer; }
            
            .section { background: #202225; padding: 12px; border-radius: 8px; }
            .section h4 { margin: 0 0 10px 0; font-size: 12px; text-transform: uppercase; color: #8e9297; }
            button { width: 100%; padding: 10px; margin-top: 6px; border: none; border-radius: 4px; cursor: pointer; color: white; font-weight: 600; transition: 0.2s; }
            .btn-blue { background: #5865f2; } .btn-green { background: #3ba55d; } .btn-red { background: #ed4245; }
            button:hover { filter: brightness(1.2); }
            
            #autocomplete { position: absolute; bottom: 70px; left: 20px; background: #18191c; border-radius: 4px; border: 1px solid #000; display: none; width: 200px; z-index: 100; }
            .user-opt { padding: 8px; cursor: pointer; border-bottom: 1px solid #2f3136; }
            .user-opt:hover { background: #5865f2; }
            #sList { max-height: 200px; overflow-y: auto; }
        </style>
    </head>
    <body>
        <div id="side">
            <div class="section">
                <h4>Voice Channels</h4>
                <select id="vSel" style="width:100%; background:#40444b; color:white; border:none; padding:8px; border-radius:4px;">
                    <option value="fomo">Fomo</option>
                    <option value="botspam">Botspam</option>
                </select>
                <button class="btn-green" onclick="vAction('join')">Join VC</button>
                <button class="btn-red" onclick="vAction('leave')">Leave VC</button>
                <button class="btn-red" style="margin-top:10px" onclick="socket.emit('stop_sounds')">🛑 Stop All Audio</button>
            </div>

            <div class="section">
                <h4>Volume & TTS</h4>
                <input type="range" min="0" max="100" value="50" style="width:100%" oninput="socket.emit('set_volume', {v: this.value/100})">
                <input type="text" id="tIn" placeholder="TTS Message..." style="width:100%; margin-top:10px; padding:8px; background:#40444b; color:white; border:none; border-radius:4px;">
                <button class="btn-blue" onclick="sendTTS()">Speak (Overlay)</button>
            </div>

            <div class="section">
                <h4>Soundboard</h4>
                <input type="file" id="soundUp" accept=".mp3" style="display:none" onchange="uploadSound()">
                <button class="btn-blue" onclick="document.getElementById('soundUp').click()">➕ Upload New MP3</button>
                <div id="sList" style="margin-top:10px"></div>
            </div>
        </div>

        <div id="chat-wrap">
            <div id="log"></div>
            <div id="autocomplete"></div>
            <div style="padding: 15px; background: #2f3136; display: flex; gap: 10px; align-items: center;">
                <input type="file" id="chatFile" style="display:none" onchange="sendImage()">
                <button onclick="document.getElementById('chatFile').click()" style="width:40px; margin:0">🖼️</button>
                <input type="text" id="cIn" placeholder="Type a message (use @ to ping)..." style="flex:1; background:#40444b; color:white; border:none; padding:12px; border-radius:8px;" oninput="checkMention(this)" onkeydown="if(event.key==='Enter') sendChat()">
            </div>
        </div>

        <script>
            const socket = io();
            const log = document.getElementById('log');

            socket.on('chat_msg', d => {
                const isMe = d.is_me ? 'msg-me' : '';
                let html = `<div class="msg ${isMe}"><img src="${d.pfp}" class="pfp"><div class="msg-content"><b>${d.user}</b><br>${d.text}`;
                if(d.img) html += `<br><img src="${d.img}" class="attach-img">`;
                html += `</div></div>`;
                log.innerHTML += html;
                log.scrollTop = log.scrollHeight;
            });

            socket.on('history', msgs => {
                msgs.forEach(d => {
                    const isMe = d.is_me ? 'msg-me' : '';
                    let html = `<div class="msg ${isMe}"><img src="${d.pfp}" class="pfp"><div class="msg-content"><b>${d.user}</b><br>${d.text}`;
                    if(d.img) html += `<br><img src="${d.img}" class="attach-img">`;
                    html += `</div></div>`;
                    log.innerHTML += html;
                });
                log.scrollTop = log.scrollHeight;
            });

            function vAction(action) { socket.emit('voice_action', {action, chan: document.getElementById('vSel').value}); }
            function sendTTS() { socket.emit('send_tts', {text: document.getElementById('tIn').value}); document.getElementById('tIn').value=''; }
            function sendChat() { socket.emit('send_chat', {text: document.getElementById('cIn').value}); document.getElementById('cIn').value=''; }

            async function uploadSound() {
                const fd = new FormData(); fd.append('file', document.getElementById('soundUp').files[0]);
                await fetch('/upload_sound', {method: 'POST', body: fd});
                loadSounds();
            }

            async function sendImage() {
                const fd = new FormData(); fd.append('file', document.getElementById('chatFile').files[0]);
                await fetch('/send_img', {method: 'POST', body: fd});
            }

            async function loadSounds() {
                const res = await fetch('/list_sounds');
                const list = await res.json();
                const div = document.getElementById('sList'); div.innerHTML = '';
                list.forEach(s => {
                    const b = document.createElement('button'); b.style.background='#4f545c'; b.style.fontSize='11px'; b.innerText=s;
                    b.onclick = () => socket.emit('play_saved', {n: s});
                    div.appendChild(b);
                });
            }

            async function checkMention(el) {
                const lastAt = el.value.lastIndexOf('@');
                const ac = document.getElementById('autocomplete');
                if(lastAt !== -1) {
                    const res = await fetch(`/search_members?q=${el.value.substring(lastAt+1)}`);
                    const users = await res.json();
                    ac.innerHTML = '';
                    if(users.length){
                        ac.style.display='block';
                        users.forEach(u => {
                            const d = document.createElement('div'); d.className='user-opt'; d.innerText=u.name;
                            d.onclick = () => { el.value = el.value.substring(0, lastAt) + '@' + u.name + ' '; ac.style.display='none'; };
                            ac.appendChild(d);
                        });
                    }
                } else ac.style.display='none';
            }

            window.onload = () => { loadSounds(); socket.emit('get_history'); };
        </script>
    </body>
    </html>
    """)

# --- ROUTES & HANDLERS ---
@app.route('/upload_sound', methods=['POST'])
def up_sound():
    f = request.files['file']
    path = os.path.join(UPLOAD_FOLDER, secure_filename(f.filename))
    f.save(path); mixer.add_source(path)
    return "OK"

@app.route('/send_img', methods=['POST'])
def send_img():
    f = request.files['file']
    path = secure_filename(f.filename)
    f.save(path)
    asyncio.run_coroutine_threadsafe(bot.get_channel(TEXT_ID).send(file=discord.File(path)), bot_loop)
    return "OK"

@app.route('/list_sounds')
def list_sounds(): return jsonify([f for f in os.listdir(UPLOAD_FOLDER) if f.endswith('.mp3')])

@app.route('/search_members')
def search_m():
    q = request.args.get('q', '').lower()
    guild = bot.get_channel(TEXT_ID).guild
    return jsonify([{'name': m.display_name} for m in guild.members if q in m.display_name.lower()][:5])

@socketio.on('get_history')
def send_history():
    async def task():
        chan = bot.get_channel(TEXT_ID)
        h = []
        async for m in chan.history(limit=20):
            h.append({'user': m.author.display_name, 'pfp': str(m.author.display_avatar.url), 'text': m.content, 'img': m.attachments[0].url if m.attachments else None, 'is_me': m.author == bot.user})
        socketio.emit('history', h[::-1])
    asyncio.run_coroutine_threadsafe(task(), bot_loop)

@socketio.on('voice_action')
def v_act(data):
    async def task():
        global vc_client
        if data['action'] == 'join':
            if vc_client: await vc_client.disconnect()
            vc_client = await bot.get_channel(VC_CHANNELS[data['chan']]).connect()
            vc_client.play(mixer)
        else: await vc_client.disconnect()
    asyncio.run_coroutine_threadsafe(task(), bot_loop)

@socketio.on('send_chat')
def s_chat(data):
    async def task():
        chan = bot.get_channel(TEXT_ID)
        content = data['text']
        for m in chan.guild.members:
            if f"@{m.display_name}" in content: content = content.replace(f"@{m.display_name}", m.mention)
        await chan.send(content)
    asyncio.run_coroutine_threadsafe(task(), bot_loop)

@socketio.on('send_tts')
def s_tts(data):
    p = f"tts_{threading.get_ident()}.mp3"
    gTTS(text=data['text'], lang='en').save(p); mixer.add_source(p)

@socketio.on('play_saved')
def p_save(data): mixer.add_source(os.path.join(UPLOAD_FOLDER, secure_filename(data['n'])))

@socketio.on('stop_sounds')
def stop_s(): mixer.stop_all()

@socketio.on('set_volume')
def s_vol(data): global current_volume; current_volume = data['v']

if __name__ == "__main__":
    threading.Thread(target=lambda: socketio.run(app, host='0.0.0.0', port=5050, allow_unsafe_werkzeug=True), daemon=True).start()
    bot.run(os.getenv('APITOK'))

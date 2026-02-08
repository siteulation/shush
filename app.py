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
intents.members = True # Required for @pings
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
    
    # Process Attachments
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
            body { font-family: 'Helvetica Neue', sans-serif; background: #36393f; color: #dcddde; display: flex; height: 100vh; margin: 0; }
            #side { width: 320px; background: #2f3136; padding: 15px; border-right: 1px solid #202225; overflow-y: auto; }
            #chat-wrap { flex: 1; display: flex; flex-direction: column; background: #36393f; }
            #log { flex: 1; overflow-y: auto; padding: 20px; }
            .msg { display: flex; gap: 10px; margin-bottom: 15px; }
            .msg img.pfp { width: 40px; height: 40px; border-radius: 50%; }
            .msg-content { background: #40444b; padding: 8px 12px; border-radius: 8px; max-width: 80%; }
            .msg-me { flex-direction: row-reverse; }
            .msg-me .msg-content { background: #5865f2; color: white; }
            .attach-img { max-width: 300px; border-radius: 5px; margin-top: 5px; display: block; }
            
            .section { background: #202225; padding: 10px; border-radius: 5px; margin-bottom: 10px; }
            button { width: 100%; padding: 8px; margin-top: 5px; border: none; border-radius: 3px; cursor: pointer; color: white; font-weight: bold; }
            .btn-blue { background: #5865f2; } .btn-green { background: #3ba55d; } .btn-red { background: #ed4245; }
            
            #autocomplete { position: absolute; background: #18191c; border: 1px solid #000; display: none; z-index: 100; }
            .user-opt { padding: 5px 10px; cursor: pointer; } .user-opt:hover { background: #5865f2; }
        </style>
    </head>
    <body>
        <div id="side">
            <div class="section">
                <select id="vSel"><option value="fomo">Fomo</option><option value="botspam">Botspam</option></select>
                <button class="btn-green" onclick="vAction('join')">Join VC</button>
                <button class="btn-red" onclick="vAction('leave')">Leave VC</button>
                <button class="btn-red" style="margin-top:15px;" onclick="socket.emit('stop_sounds')">🛑 STOP ALL SOUNDS</button>
            </div>
            <div class="section">
                <input type="range" min="0" max="100" value="50" oninput="socket.emit('set_volume', {v: this.value/100})">
                <input type="text" id="tIn" placeholder="TTS Overlay...">
                <button class="btn-blue" onclick="sendTTS()">Speak</button>
            </div>
            <div id="sList" class="section"><strong>Sounds:</strong></div>
        </div>
        <div id="chat-wrap">
            <div id="log"></div>
            <div style="padding: 20px; background: #40444b;">
                <div id="autocomplete"></div>
                <input type="file" id="chatFile" style="display:none" onchange="uploadChatImg()">
                <button class="btn-blue" style="width:auto; padding: 5px 10px;" onclick="document.getElementById('chatFile').click()">📷</button>
                <input type="text" id="cIn" placeholder="Message Discord..." style="width:85%; background:transparent; border:none; color:white; padding:10px;" oninput="checkMention(this)" onkeydown="if(event.key==='Enter') sendChat()">
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

            function vAction(action) { socket.emit('voice_action', {action, chan: document.getElementById('vSel').value}); }
            function sendTTS() { socket.emit('send_tts', {text: document.getElementById('tIn').value}); document.getElementById('tIn').value=''; }
            
            function sendChat() {
                const i = document.getElementById('cIn');
                socket.emit('send_chat', {text: i.value});
                i.value = '';
            }

            async function uploadChatImg() {
                const fd = new FormData(); fd.append('file', document.getElementById('chatFile').click());
                // Image handling logic here
            }

            // Autocomplete Ping Logic
            async function checkMention(el) {
                const val = el.value;
                const lastAt = val.lastIndexOf('@');
                if(lastAt !== -1) {
                    const query = val.substring(lastAt + 1);
                    const res = await fetch(`/search_members?q=${query}`);
                    const users = await res.json();
                    const ac = document.getElementById('autocomplete');
                    ac.innerHTML = '';
                    if(users.length > 0) {
                        ac.style.display = 'block';
                        users.forEach(u => {
                            const div = document.createElement('div');
                            div.className = 'user-opt';
                            div.innerText = u.name;
                            div.onclick = () => {
                                el.value = val.substring(0, lastAt) + '@' + u.name + ' ';
                                ac.style.display = 'none';
                            };
                            ac.appendChild(div);
                        });
                    }
                } else { document.getElementById('autocomplete').style.display = 'none'; }
            }

            socket.on('update_sounds', list => {
                const div = document.getElementById('sList'); div.innerHTML = '<strong>Sounds:</strong>';
                list.forEach(s => {
                    const b = document.createElement('button'); b.className='btn-blue'; b.style.fontSize='10px'; b.innerText=s;
                    b.onclick = () => socket.emit('play_saved', {n: s});
                    div.appendChild(b);
                });
            });
        </script>
    </body>
    </html>
    """)

@app.route('/search_members')
def search_members():
    q = request.args.get('q', '').lower()
    guild = bot.get_channel(TEXT_ID).guild
    matches = [{'name': m.display_name, 'id': m.id} for m in guild.members if q in m.display_name.lower()][:5]
    return jsonify(matches)

# --- SOCKETS ---
@socketio.on('stop_sounds')
def stop_all(): mixer.stop_all()

@socketio.on('send_chat')
def h_chat(data):
    async def task():
        chan = bot.get_channel(TEXT_ID)
        # Find pings in text and convert them to actual mentions
        content = data['text']
        for member in chan.guild.members:
            if f"@{member.display_name}" in content:
                content = content.replace(f"@{member.display_name}", member.mention)
        await chan.send(content)
    asyncio.run_coroutine_threadsafe(task(), bot_loop)

@socketio.on('send_tts')
def h_tts(data):
    path = f"tts_{threading.get_ident()}.mp3"
    gTTS(text=data['text'], lang='en').save(path)
    mixer.add_source(path)

@socketio.on('voice_action')
def h_voice(data):
    async def task():
        global vc_client
        if data['action'] == 'join':
            if vc_client: await vc_client.disconnect()
            vc_client = await bot.get_channel(VC_CHANNELS[data['chan']]).connect()
            vc_client.play(mixer)
        else: await vc_client.disconnect()
    asyncio.run_coroutine_threadsafe(task(), bot_loop)

if __name__ == "__main__":
    threading.Thread(target=lambda: socketio.run(app, host='0.0.0.0', port=5050, allow_unsafe_werkzeug=True), daemon=True).start()
    bot.run(os.getenv('APITOK'))

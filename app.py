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
intents.direct_messages = True # REQUIRED FOR DMs
bot = commands.Bot(command_prefix="!", intents=intents)

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

bot_loop = None
vc_client = None
current_volume = 0.5
active_dm_target = None # Stores the User ID if in DM mode

# --- MIXER ENGINE (Unchanged) ---
class LiveMixer(discord.AudioSource):
    def __init__(self): self.sources = []
    def add_source(self, path): self.sources.append(discord.FFmpegPCMAudio(path, options="-f s16le -ar 48000 -ac 2"))
    def stop_all(self):
        for s in self.sources: s.cleanup()
        self.sources = []
    def read(self):
        final_buffer = np.zeros(1920, dtype=np.int32)
        to_remove = []
        for src in self.sources:
            data = src.read()
            if not data: to_remove.append(src); continue
            chunk = np.frombuffer(data, dtype=np.int16)
            final_buffer[:len(chunk)] += chunk
        for src in to_remove: self.sources.remove(src)
        return np.clip(final_buffer * current_volume, -32768, 32767).astype(np.int16).tobytes()
    def is_opus(self): return False

mixer = LiveMixer()

# --- DISCORD EVENTS ---
@bot.event
async def on_message(message):
    # Handle Channel Messages
    if message.channel.id == TEXT_ID:
        img_url = message.attachments[0].url if message.attachments else None
        socketio.emit('chat_msg', {
            'user': message.author.display_name,
            'pfp': str(message.author.display_avatar.url),
            'text': message.content,
            'img': img_url,
            'is_me': message.author == bot.user,
            'is_dm': False
        })
    
    # Handle Direct Messages
    if isinstance(message.channel, discord.DMChannel) and message.author != bot.user:
        socketio.emit('chat_msg', {
            'user': f"[DM] {message.author.display_name}",
            'pfp': str(message.author.display_avatar.url),
            'text': message.content,
            'is_me': False,
            'is_dm': True,
            'user_id': message.author.id
        })

# --- UI LOGIC (Injected DM elements) ---
@app.route('/')
def index():
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Discord Master Station</title>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
        <style>
            /* CSS from previous version preserved */
            body { font-family: 'Segoe UI', sans-serif; background: #36393f; color: #dcddde; display: flex; height: 100vh; margin: 0; }
            #side { width: 340px; background: #2f3136; padding: 15px; border-right: 1px solid #202225; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; }
            #chat-wrap { flex: 1; display: flex; flex-direction: column; background: #36393f; }
            #log { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; }
            .msg { display: flex; gap: 12px; margin-bottom: 15px; align-items: flex-start; }
            .msg img.pfp { width: 38px; height: 38px; border-radius: 50%; background: #202225; }
            .msg-content { background: #40444b; padding: 10px; border-radius: 8px; max-width: 75%; }
            .msg-me { flex-direction: row-reverse; }
            .msg-me .msg-content { background: #5865f2; color: white; }
            .section { background: #202225; padding: 12px; border-radius: 8px; }
            button { width: 100%; padding: 10px; margin-top: 6px; border: none; border-radius: 4px; cursor: pointer; color: white; font-weight: 600; }
            .btn-blue { background: #5865f2; } .btn-green { background: #3ba55d; } .btn-red { background: #ed4245; }
            #autocomplete { position: absolute; bottom: 70px; left: 20px; background: #18191c; border-radius: 4px; display: none; width: 250px; z-index: 100; }
            .user-opt { padding: 8px; cursor: pointer; border-bottom: 1px solid #2f3136; display: flex; justify-content: space-between; }
        </style>
    </head>
    <body>
        <div id="side">
            <div class="section">
                <h4 id="chat-target-display">Target: #Channel</h4>
                <button class="btn-blue" onclick="setTarget('channel')">Switch to #Channel</button>
            </div>
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
                <button class="btn-blue" onclick="sendTTS()">Speak</button>
            </div>
            <div class="section">
                <h4>Soundboard</h4>
                <input type="file" id="soundUp" accept=".mp3" style="display:none" onchange="uploadSound()">
                <button class="btn-blue" onclick="document.getElementById('soundUp').click()">➕ Upload MP3</button>
                <div id="sList"></div>
            </div>
        </div>

        <div id="chat-wrap">
            <div id="log"></div>
            <div id="autocomplete"></div>
            <div style="padding: 15px; background: #2f3136; display: flex; gap: 10px;">
                <input type="text" id="cIn" placeholder="Message..." style="flex:1; background:#40444b; color:white; border:none; padding:12px; border-radius:8px;" oninput="checkMention(this)" onkeydown="if(event.key==='Enter') sendChat()">
            </div>
        </div>

        <script>
            const socket = io();
            let currentTarget = 'channel';

            function setTarget(type, id, name) {
                currentTarget = type;
                if(type === 'dm') {
                    socket.emit('set_dm_target', {id: id});
                    document.getElementById('chat-target-display').innerText = "Target: DM @" + name;
                } else {
                    socket.emit('set_dm_target', {id: null});
                    document.getElementById('chat-target-display').innerText = "Target: #Channel";
                }
            }

            socket.on('chat_msg', d => {
                const log = document.getElementById('log');
                const isMe = d.is_me ? 'msg-me' : '';
                log.innerHTML += `<div class="msg ${isMe}"><img src="${d.pfp}" class="pfp"><div class="msg-content"><b>${d.user}</b><br>${d.text}</div></div>`;
                log.scrollTop = log.scrollHeight;
            });

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
                            const d = document.createElement('div'); d.className='user-opt';
                            d.innerHTML = `<span>${u.name}</span><button style="width:40px; margin:0; padding:2px" onclick="setTarget('dm', '${u.id}', '${u.name}')">DM</button>`;
                            d.onclick = (e) => { 
                                if(e.target.tagName !== 'BUTTON') {
                                    el.value = el.value.substring(0, lastAt) + '@' + u.name + ' '; 
                                    ac.style.display='none'; 
                                }
                            };
                            ac.appendChild(d);
                        });
                    }
                } else ac.style.display='none';
            }

            function sendChat() {
                const i = document.getElementById('cIn');
                socket.emit('send_chat', {text: i.value, target: currentTarget});
                i.value = '';
            }
            // ... rest of the helper functions (vAction, sendTTS, etc) preserved
        </script>
    </body>
    </html>
    """)

# --- SOCKET HANDLERS ---
@socketio.on('set_dm_target')
def set_dm(data):
    global active_dm_target
    active_dm_target = data['id']

@socketio.on('send_chat')
def h_chat(data):
    async def task():
        global active_dm_target
        content = data['text']
        
        if data['target'] == 'dm' and active_dm_target:
            user = await bot.fetch_user(int(active_dm_target))
            await user.send(content)
            socketio.emit('chat_msg', {
                'user': f"To {user.display_name}", 'pfp': str(bot.user.display_avatar.url),
                'text': content, 'is_me': True
            })
        else:
            chan = bot.get_channel(TEXT_ID)
            await chan.send(content)

    asyncio.run_coroutine_threadsafe(task(), bot_loop)

@app.route('/search_members')
def search_m():
    q = request.args.get('q', '').lower()
    guild = bot.get_channel(TEXT_ID).guild
    return jsonify([{'name': m.display_name, 'id': str(m.id)} for m in guild.members if q in m.display_name.lower()][:5])

# (All other routes like /upload_sound, /list_sounds, and socket events like send_tts, voice_action are preserved exactly as they were)

if __name__ == "__main__":
    threading.Thread(target=lambda: socketio.run(app, host='0.0.0.0', port=5050, allow_unsafe_werkzeug=True), daemon=True).start()
    bot.run(os.getenv('APITOK'))

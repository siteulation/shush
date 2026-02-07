import os
import asyncio
import threading
from flask import Flask, render_template_string
from flask_socketio import SocketIO, emit
import discord
from discord.ext import commands, voice_recv

# --- CONFIG ---
TEXT_CHANNEL_ID = 1303054086454906920
VOICE_CHANNEL_ID = 1462980688256040970

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix="!", intents=intents)

app = Flask(__name__)
# Using eventlet or gevent is recommended for production SocketIO, 
# but for a direct script, we'll stick to the standard threading mode.
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

bot_loop = None
vc_client = None

# --- AUDIO SINK ---
class BrowserAudioSink(voice_recv.AudioSink):
    def want_opus(self):
        return False # Convert to PCM for browser

    def write(self, user, data):
        # Emit raw PCM data to the browser
        socketio.emit('audio_stream', {'data': data.pcm})

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

@bot.event
async def on_voice_state_update(member, before, after):
    if member == bot.user:
        status = "Connected" if after.channel else "Disconnected"
        socketio.emit('status_update', {
            'status': status,
            'mute': after.self_mute,
            'deaf': after.self_deaf
        })

# --- WEB UI ---
@app.route('/')
def index():
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Discord Voice/Text Bridge</title>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
        <style>
            body { font-family: 'Segoe UI', sans-serif; background: #2f3136; color: white; display: flex; height: 100vh; margin: 0; }
            #sidebar { width: 280px; background: #202225; padding: 20px; display: flex; flex-direction: column; gap: 10px; }
            #chat-area { flex: 1; display: flex; flex-direction: column; padding: 20px; }
            #log { flex: 1; background: #36393f; border-radius: 8px; padding: 15px; overflow-y: auto; margin-bottom: 10px; border: 1px solid #202225; }
            button { padding: 12px; border: none; border-radius: 4px; color: white; cursor: pointer; font-weight: bold; }
            .btn-join { background: #43b581; } .btn-leave { background: #f04747; } .btn-toggle { background: #4f545c; }
            input { padding: 12px; background: #40444b; color: white; border: none; border-radius: 4px; }
            .status-box { background: #2f3136; padding: 10px; border-radius: 4px; font-size: 0.9em; }
        </style>
    </head>
    <body>
        <div id="sidebar">
            <h3>Voice Control</h3>
            <div class="status-box">
                Status: <span id="st-val" style="color:#f04747">Disconnected</span><br>
                Mute: <span id="st-mute">Off</span> | Deaf: <span id="st-deaf">Off</span>
            </div>
            <button class="btn-join" onclick="vCmd('join')">Join Channel</button>
            <button class="btn-toggle" onclick="vCmd('mute')">Toggle Mute</button>
            <button class="btn-toggle" onclick="vCmd('deafen')">Toggle Deafen</button>
            <button class="btn-leave" onclick="vCmd('leave')">Disconnect</button>
            <p style="font-size: 11px; color: #8e9297;">Click anywhere to enable audio if you don't hear anything.</p>
        </div>
        <div id="chat-area">
            <div id="log"></div>
            <input type="text" id="minp" placeholder="Message #channel..." onkeydown="if(event.key==='Enter') sendT()">
        </div>

        <script>
            const socket = io();
            const log = document.getElementById('log');
            const audioCtx = new (window.AudioContext || window.webkitAudioContext)({sampleRate: 48000});

            // Handle UI Updates
            socket.on('status_update', d => {
                document.getElementById('st-val').innerText = d.status;
                document.getElementById('st-val').style.color = d.status === "Connected" ? "#43b581" : "#f04747";
                document.getElementById('st-mute').innerText = d.mute ? "ON" : "OFF";
                document.getElementById('st-deaf').innerText = d.deaf ? "ON" : "OFF";
            });

            socket.on('chat_msg', d => {
                log.innerHTML += `<div><b style="color:#7289da">${d.user}:</b> ${d.text}</div>`;
                log.scrollTop = log.scrollHeight;
            });

            // Audio Playback (PCM 16-bit Le to Float32)
            socket.on('audio_stream', d => {
                if (audioCtx.state === 'suspended') return;
                
                const raw = new Int16Array(d.data);
                const floatData = new Float32Array(raw.length);
                for (let i = 0; i < raw.length; i++) floatData[i] = raw[i] / 32768;

                const buffer = audioCtx.createBuffer(1, floatData.length, 48000);
                buffer.getChannelData(0).set(floatData);
                const source = audioCtx.createBufferSource();
                source.buffer = buffer;
                source.connect(audioCtx.destination);
                source.start();
            });

            function sendT() {
                const i = document.getElementById('minp');
                if(!i.value) return;
                socket.emit('send_text', {msg: i.value});
                log.innerHTML += `<div><i style="color:#b9bbbe">(You): ${i.value}</i></div>`;
                i.value = '';
            }

            function vCmd(action) { socket.emit('voice_control', {action}); }
            window.onclick = () => { if(audioCtx.state === 'suspended') audioCtx.resume(); };
        </script>
    </body>
    </html>
    """)

# --- SOCKET HANDLERS ---
@socketio.on('send_text')
def handle_text(data):
    channel = bot.get_channel(TEXT_CHANNEL_ID)
    if bot_loop: asyncio.run_coroutine_threadsafe(channel.send(data['msg']), bot_loop)

@socketio.on('voice_control')
def handle_voice(data):
    global vc_client
    action = data['action']

    async def vc_task():
        global vc_client
        if action == 'join':
            ch = bot.get_channel(VOICE_CHANNEL_ID)
            vc_client = await ch.connect(cls=voice_recv.VoiceRecvClient)
            vc_client.listen(BrowserAudioSink())
        elif vc_client:
            if action == 'leave': 
                await vc_client.disconnect()
                vc_client = None
            elif action == 'mute': 
                await vc_client.main_ws.voice_state(vc_client.guild.id, vc_client.channel.id, self_mute=not vc_client.self_mute)
            elif action == 'deafen': 
                await vc_client.main_ws.voice_state(vc_client.guild.id, vc_client.channel.id, self_mute=vc_client.self_mute, self_deaf=not vc_client.self_deaf)

    if bot_loop: asyncio.run_coroutine_threadsafe(vc_task(), bot_loop)

if __name__ == "__main__":
    # Use allow_unsafe_werkzeug=True if running locally for testing
    threading.Thread(target=lambda: socketio.run(app, host='0.0.0.0', port=5050, allow_unsafe_werkzeug=True), daemon=True).start()
    bot.run(os.getenv('APITOK'))

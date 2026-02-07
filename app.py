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
socketio = SocketIO(app, cors_allowed_origins="*")

bot_loop = None
vc_client = None

# --- DISCORD RECEIVE AUDIO ---
class BrowserAudioSink(voice_recv.AudioSink):
    def want_opus(self):
        return False # We want PCM to send to browser easily

    def write(self, user, data):
        # Send raw audio bytes to the browser via WebSocket
        socketio.emit('audio_data', {'user': str(user), 'data': data.pcm})

@bot.event
async def on_ready():
    global bot_loop
    bot_loop = asyncio.get_running_loop()
    print(f'✅ Bot Online: {bot.user}')

@bot.event
async def on_message(message):
    if message.author == bot.user or message.channel.id != TEXT_CHANNEL_ID:
        return
    socketio.emit('text_message', {'user': message.author.display_name, 'content': message.content})

# --- WEB UI ---
@app.route('/')
def index():
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Discord Live Bridge</title>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
        <style>
            body { font-family: sans-serif; background: #2c2f33; color: white; display: flex; height: 100vh; margin: 0; }
            #side { width: 300px; background: #23272a; padding: 20px; border-right: 1px solid #444; }
            #main { flex: 1; display: flex; flex-direction: column; padding: 20px; }
            #chat { flex: 1; background: #202225; overflow-y: auto; padding: 10px; margin-bottom: 10px; border-radius: 5px; }
            .controls button { width: 100%; margin: 5px 0; padding: 10px; cursor: pointer; border: none; border-radius: 4px; color: white; }
            .join { background: #43b581; } .leave { background: #f04747; } .mute { background: #5865f2; }
        </style>
    </head>
    <body>
        <div id="side">
            <h3>Voice Controls</h3>
            <button class="join" onclick="control('join')">Join Voice</button>
            <button class="mute" onclick="control('mute')">Toggle Mute</button>
            <button class="mute" onclick="control('deafen')">Toggle Deafen</button>
            <button class="leave" onclick="control('leave')">Leave</button>
            <p id="v-status">Status: Disconnected</p>
        </div>
        <div id="main">
            <div id="chat"></div>
            <input type="text" id="minp" style="width:100%; padding:10px;" placeholder="Message..." onkeydown="if(event.key==='Enter') sendT()">
        </div>

        <script>
            const socket = io();
            const chat = document.getElementById('chat');
            
            // Text Chat
            socket.on('text_message', d => {
                chat.innerHTML += `<div><b>${d.user}:</b> ${d.content}</div>`;
                chat.scrollTop = chat.scrollHeight;
            });

            function sendT() {
                const i = document.getElementById('minp');
                socket.emit('send_text', {msg: i.value});
                chat.innerHTML += `<div><i>(You): ${i.value}</i></div>`;
                i.value = '';
            }

            function control(action) { socket.emit('voice_control', {action}); }

            // Audio Logic
            const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            socket.on('audio_data', d => {
                // Incoming Discord Audio (PCM)
                const buffer = new Float32Array(d.data.length / 2);
                const view = new DataView(d.data);
                for(let i=0; i<buffer.length; i++) buffer[i] = view.getInt16(i*2, true) / 32768;
                
                const audioBuffer = audioCtx.createBuffer(1, buffer.length, 48000);
                audioBuffer.getChannelData(0).set(buffer);
                const source = audioCtx.createBufferSource();
                source.buffer = audioBuffer;
                source.connect(audioCtx.destination);
                source.start();
            });
        </script>
    </body>
    </html>
    """)

# --- SOCKET EVENTS ---
@socketio.on('send_text')
def handle_text(data):
    channel = bot.get_channel(TEXT_CHANNEL_ID)
    asyncio.run_coroutine_threadsafe(channel.send(data['msg']), bot_loop)

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
            if action == 'leave': await vc_client.disconnect()
            elif action == 'mute': await vc_client.main_ws.voice_state(vc_client.guild.id, vc_client.channel.id, self_mute=not vc_client.self_mute)
            elif action == 'deafen': await vc_client.main_ws.voice_state(vc_client.guild.id, vc_client.channel.id, self_mute=vc_client.self_mute, self_deaf=not vc_client.self_deaf)

    asyncio.run_coroutine_threadsafe(vc_task(), bot_loop)

if __name__ == "__main__":
    t = threading.Thread(target=lambda: socketio.run(app, host='0.0.0.0', port=5050, allow_unsafe_werkzeug=True), daemon=True)
    t.start()
    bot.run(os.getenv('APITOK'))

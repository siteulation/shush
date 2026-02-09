import os
import asyncio
import threading
import numpy as np
from flask import Flask, render_template_string, request, jsonify
from flask_socketio import SocketIO, emit
import discord
from discord.ext import commands, voice_recv
from gtts import gTTS

# --- CONFIG ---
TEXT_ID = 1303054086454906920
VC_CHANNELS = {"fomo": 1462980688256040970, "botspam": 1470121574672765068}
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix="!", intents=intents)

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

bot_loop = None
vc_client = None
current_volume = 0.5

# --- AUDIO RECEIVER (Discord -> Browser) ---
class BrowserStreamingSink(voice_recv.AudioSink):
    def __init__(self):
        super().__init__()
        self.buffer = bytearray()

    def want_opus(self) -> bool:
        return False # We want PCM 16-bit 48kHz Stereo

    def write(self, user, data):
        # Accumulate roughly 100ms of audio before sending to reduce socket overhead
        # or send immediately for lowest latency.
        socketio.emit('voice_in', {'pcm': data.pcm, 'user': user.display_name})

# --- MIXER ENGINE (Browser -> Discord) ---
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
                to_remove.append(src); continue
            chunk = np.frombuffer(data, dtype=np.int16)
            final_buffer[:len(chunk)] += chunk
        for src in to_remove: self.sources.remove(src)
        return np.clip(final_buffer * current_volume, -32768, 32767).astype(np.int16).tobytes()

mixer = LiveMixer()

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
            body { font-family: sans-serif; background: #36393f; color: #dcddde; display: flex; height: 100vh; margin: 0; }
            #side { width: 340px; background: #2f3136; padding: 15px; border-right: 1px solid #202225; overflow-y: auto; }
            #chat-wrap { flex: 1; display: flex; flex-direction: column; background: #36393f; }
            #log { flex: 1; overflow-y: auto; padding: 20px; }
            .section { background: #202225; padding: 12px; border-radius: 8px; margin-bottom: 10px; }
            button { width: 100%; padding: 8px; margin-top: 5px; cursor: pointer; background: #5865f2; color: white; border: none; border-radius: 4px; }
            .btn-red { background: #ed4245; }
        </style>
    </head>
    <body>
        <div id="side">
            <div class="section">
                <h4>Voice Controls</h4>
                <select id="vSel" style="width:100%"><option value="fomo">Fomo</option><option value="botspam">Botspam</option></select>
                <button onclick="vAction('join')">Join & Listen</button>
                <button class="btn-red" onclick="vAction('leave')">Disconnect</button>
            </div>
            <div class="section">
                <h4>TTS Overlay</h4>
                <input type="text" id="tIn" style="width:100%"><button onclick="sendTTS()">Speak</button>
            </div>
            <div class="section">
                <h4>Audio Monitor</h4>
                <div id="vStatus">Listening: False</div>
            </div>
        </div>
        <div id="chat-wrap"><div id="log"></div></div>

        <script>
            const socket = io();
            const audioCtx = new (window.AudioContext || window.webkitAudioContext)({sampleRate: 48000});
            let nextTime = 0;

            // Handle Incoming Voice from Discord
            socket.on('voice_in', d => {
                if (audioCtx.state === 'suspended') return;
                
                const pcm16 = new Int16Array(d.pcm);
                const float32 = new Float32Array(pcm16.length);
                for (let i = 0; i < pcm16.length; i++) float32[i] = pcm16[i] / 32768.0;

                const buffer = audioCtx.createBuffer(2, float32.length / 2, 48000);
                buffer.getChannelData(0).set(float32.filter((_,i) => i % 2 === 0));
                buffer.getChannelData(1).set(float32.filter((_,i) => i % 2 !== 0));

                const source = audioCtx.createBufferSource();
                source.buffer = buffer;
                source.connect(audioCtx.destination);
                
                const now = audioCtx.currentTime;
                if (nextTime < now) nextTime = now;
                source.start(nextTime);
                nextTime += buffer.duration;
            });

            function vAction(action) { 
                if(action === 'join') audioCtx.resume();
                socket.emit('voice_action', {action, chan: document.getElementById('vSel').value}); 
            }
            function sendTTS() { socket.emit('send_tts', {text: document.getElementById('tIn').value}); }
            window.onclick = () => audioCtx.resume();
        </script>
    </body>
    </html>
    """)

# --- HANDLERS ---
@socketio.on('voice_action')
def h_voice(data):
    async def task():
        global vc_client
        if data['action'] == 'join':
            target = VC_CHANNELS[data['chan']]
            if vc_client: await vc_client.disconnect()
            # Use VoiceRecvClient to enable listening
            vc_client = await bot.get_channel(target).connect(cls=voice_recv.VoiceRecvClient)
            vc_client.listen(BrowserStreamingSink())
            vc_client.play(mixer)
        else:
            if vc_client: await vc_client.disconnect()
    asyncio.run_coroutine_threadsafe(task(), bot_loop)

@socketio.on('send_tts')
def h_tts(data):
    p = f"tts_temp.mp3"
    gTTS(text=data['text'], lang='en').save(p); mixer.add_source(p)

if __name__ == "__main__":
    threading.Thread(target=lambda: socketio.run(app, host='0.0.0.0', port=5050, allow_unsafe_werkzeug=True), daemon=True).start()
    bot.run(os.getenv('APITOK'))

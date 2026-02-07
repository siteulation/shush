import os
import asyncio
import threading
import numpy as np
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

# --- AUDIO SINK (Discord -> Browser) ---
class BrowserAudioSink(voice_recv.AudioSink):
    def __init__(self):
        super().__init__()

    def want_opus(self) -> bool:
        return False # We want PCM 16-bit, 48kHz, Stereo

    def write(self, user, data):
        # Discord sends 16-bit Little Endian PCM. 
        # We send it as raw bytes to the browser.
        socketio.emit('audio_out', {'pcm': data.pcm})

# --- DISCORD EVENTS ---
@bot.event
async def on_ready():
    global bot_loop
    bot_loop = asyncio.get_running_loop()
    print(f'✅ Bot Online: {bot.user}')

@bot.event
async def on_voice_state_update(member, before, after):
    if member == bot.user:
        socketio.emit('status', {'connected': after.channel is not None})

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
            body { font-family: 'Segoe UI', sans-serif; background: #2f3136; color: white; padding: 40px; text-align: center; }
            .card { background: #36393f; padding: 20px; border-radius: 10px; box-shadow: 0 4px 10px rgba(0,0,0,0.3); display: inline-block; min-width: 400px; }
            #log { height: 150px; overflow-y: auto; background: #202225; padding: 10px; margin: 15px 0; border-radius: 5px; text-align: left; font-size: 0.9em; }
            .btn { padding: 12px 24px; cursor: pointer; border: none; border-radius: 5px; color: white; margin: 5px; font-weight: bold; }
            .join { background: #43b581; } .leave { background: #f04747; }
            #visualizer { width: 100%; height: 50px; background: #202225; margin-top: 10px; border-radius: 5px; }
        </style>
    </head>
    <body>
        <div class="card">
            <h2>Discord Voice & Text</h2>
            <div id="status">Status: Disconnected</div>
            <div id="log">Welcome! Click Join to begin.</div>
            
            <button class="btn join" onclick="joinVC()">Join Voice</button>
            <button class="btn leave" onclick="leaveVC()">Leave Voice</button>
            <canvas id="visualizer"></canvas>
        </div>

        <script>
            const socket = io();
            const log = document.getElementById('log');
            const audioCtx = new (window.AudioContext || window.webkitAudioContext)({sampleRate: 48000});
            
            // Audio Buffer Management
            let nextStartTime = 0;

            socket.on('audio_out', msg => {
                if (audioCtx.state === 'suspended') return;

                // 1. Convert Bytes to Int16
                const pcmData = new Int16Array(msg.pcm);
                // 2. Convert Int16 to Float32
                const floatData = new Float32Array(pcmData.length);
                for (let i = 0; i < pcmData.length; i++) {
                    floatData[i] = pcmData[i] / 32768.0;
                }

                // 3. Schedule playback to prevent clicking
                const buffer = audioCtx.createBuffer(2, floatData.length / 2, 48000);
                buffer.getChannelData(0).set(floatData.filter((_,i) => i % 2 === 0)); // Left
                buffer.getChannelData(1).set(floatData.filter((_,i) => i % 2 !== 0)); // Right

                const source = audioCtx.createBufferSource();
                source.buffer = buffer;
                source.connect(audioCtx.destination);
                
                const currentTime = audioCtx.currentTime;
                if (nextStartTime < currentTime) nextStartTime = currentTime;
                source.start(nextStartTime);
                nextStartTime += buffer.duration;
            });

            function joinVC() {
                audioCtx.resume();
                socket.emit('voice_action', {a:'join'});
                log.innerHTML += "<div><i>Requesting join...</i></div>";
            }

            function leaveVC() {
                socket.emit('voice_action', {a:'leave'});
            }

            socket.on('status', d => {
                document.getElementById('status').innerText = "Status: " + (d.connected ? "Connected" : "Disconnected");
                log.innerHTML += `<div><b>System:</b> Voice ${d.connected ? 'Enabled' : 'Disabled'}</div>`;
            });

            window.onclick = () => { if(audioCtx.state === 'suspended') audioCtx.resume(); };
        </script>
    </body>
    </html>
    """)

# --- SOCKET HANDLERS ---
@socketio.on('voice_action')
def handle_voice(data):
    async def task():
        global vc_client
        if data['a'] == 'join':
            ch = bot.get_channel(VOICE_CHANNEL_ID)
            # IMPORTANT: Re-connect if already connected to clear old sinks
            if vc_client: await vc_client.disconnect()
            vc_client = await ch.connect(cls=voice_recv.VoiceRecvClient)
            vc_client.listen(BrowserAudioSink())
        elif data['a'] == 'leave' and vc_client:
            await vc_client.disconnect()
            vc_client = None
            
    if bot_loop: asyncio.run_coroutine_threadsafe(task(), bot_loop)

if __name__ == "__main__":
    # Ensure you use eventlet or similar if this were production
    # allow_unsafe_werkzeug=True is for local testing in Python 3.13
    threading.Thread(target=lambda: socketio.run(app, host='0.0.0.0', port=5050, allow_unsafe_werkzeug=True), daemon=True).start()
    bot.run(os.getenv('APITOK'))

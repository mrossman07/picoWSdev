import network
import uasyncio as asyncio
import machine
import time
import json
from microdot import Microdot
from microdot.websocket import with_websocket

# --- Configuration ---
WIFI_SSID = "gatornet"
WIFI_PASSWORD = "g8orWAP2025!"
PORT = 80

# Hardware Setup
led = machine.Pin("LED", machine.Pin.OUT)
adc_temp = machine.ADC(4) # Internal Pico temp sensor

# Initialize Microdot app
app = Microdot()

# Global list to keep track of active WebSocket connections
ws_clients = []

# --- Embedded Dashboard HTML/JS ---
HTML_PAGE = """<!DOCTYPE html>
<html>
<head>
    <title>Pico W Live Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: Arial, sans-serif; background: #121212; color: #e0e0e0; text-align: center; padding: 20px; }
        .card { background: #1e1e1e; padding: 20px; border-radius: 10px; display: inline-block; margin: 10px; min-width: 200px; box-shadow: 0 4px 8px rgba(0,0,0,0.5); }
        .value { font-size: 2em; color: #00adb5; font-weight: bold; margin: 10px 0; }
        button { background: #00adb5; border: none; color: white; padding: 12px 24px; font-size: 1em; border-radius: 5px; cursor: pointer; transition: 0.2s; }
        button:hover { background: #007a80; }
        .status { font-size: 0.9em; color: #888; margin-top: 15px; }
    </style>
</head>
<body>
    <h1>Pi Pico W + Microdot Server</h1>
    
    <div class="card">
        <h3>Pico Core Temp</h3>
        <div id="temp" class="value">-- &deg;C</div>
    </div>
    
    <div class="card">
        <h3>System Uptime</h3>
        <div id="uptime" class="value">0s</div>
    </div>
    
    <div class="card">
        <h3>Control</h3>
        <button onclick="toggleLED()">Toggle Onboard LED</button>
    </div>

    <div class="status" id="ws-status">Connecting to WebSocket...</div>

    <script>
        let ws;
        function connect() {
            // Establishes connection to ws://<IP>/ws
            ws = new WebSocket('ws://' + window.location.host + '/ws');
            
            ws.onopen = () => {
                document.getElementById('ws-status').innerHTML = "WebSocket Status: Connected";
                document.getElementById('ws-status').style.color = "#4caf50";
            };
            
            ws.onmessage = (event) => {
                let data = JSON.parse(event.data);
                document.getElementById('temp').innerHTML = data.temp.toFixed(1) + " &deg;C";
                document.getElementById('uptime').innerHTML = data.uptime + "s";
            };
            
            ws.onclose = () => {
                document.getElementById('ws-status').innerHTML = "WebSocket Status: Disconnected. Reconnecting...";
                document.getElementById('ws-status').style.color = "#f44336";
                setTimeout(connect, 2000); // Attempt reconnection every 2 seconds
            };
        }

        function toggleLED() {
            if(ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({action: "toggleLED"}));
            }
        }

        window.onload = connect;
    </script>
</body>
</html>
"""

# --- Helper Functions ---
def get_pico_temperature():
    reading = adc_temp.read_u16() * (3.3 / 65535)
    temperature = 27 - (reading - 0.706) / 0.001721
    return temperature

async def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    
    print("Connecting to Wi-Fi", end="")
    while not wlan.isconnected():
        print(".", end="")
        await asyncio.sleep(0.5)
        
    print("\nConnected!")
    print("IP Address:", wlan.ifconfig()[0])
    return wlan.ifconfig()[0]

# --- Background Telemetry Broadcaster Task ---
async def telemetry_broadcaster():
    """Loops indefinitely, broadcasting server telemetry data to all active websockets."""
    start_time = time.time()
    while True:
        if ws_clients:
            payload = json.dumps({
                "temp": get_pico_temperature(),
                "uptime": time.time() - start_time
            })
            
            # Broadcast metrics to all connected web interfaces
            for ws in list(ws_clients):
                try:
                    await ws.send(payload)
                except Exception:
                    # Clean up the pool if a client dropped off unexpectedly
                    if ws in ws_clients:
                        ws_clients.remove(ws)
                        
        await asyncio.sleep(1.0) # Refresh interval

# --- Microdot App Routes ---

# HTTP Route: Serves the dashboard layout
@app.route('/')
async def index(request):
    return HTML_PAGE, 200, {'Content-Type': 'text/html'}

# WebSocket Route: Handles live communication
@app.route('/ws')
@with_websocket
async def ws_handler(request, ws):
    print("[WS] Client connection opened.")
    ws_clients.append(ws)
    
    try:
        while True:
            # Wait and listen for incoming text configurations from the UI
            message = await ws.receive()
            if message is None:
                break
                
            try:
                data = json.loads(message)
                if data.get("action") == "toggleLED":
                    led.toggle()
                    print("[WS] LED state modified via client command")
            except Exception as e:
                print("[WS] Error decoding message frame:", e)
                
    except Exception as e:
        print("[WS] Socket error:", e)
    finally:
        if ws in ws_clients:
            ws_clients.remove(ws)
        print("[WS] Client connection closed.")

# --- Execution Lifecycle ---
async def main():
    ip_address = await connect_wifi()
    
    # Launch background telemetry loop alongside Microdot
    asyncio.create_task(telemetry_broadcaster())
    
    print(f"Starting Microdot server on http://{ip_address}:{PORT}")
    # Start the server engine using Microdot's async loop implementation
    await app.start_server(host='0.0.0.0', port=PORT, debug=True)

try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("\nServer terminated manually.")
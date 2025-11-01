import asyncio
import json
import os
from aiohttp import web

# --- Data Structure ---
ROOMS = {}  # { 'roomCode': { ws_object: 'userName' } }


# --- Utility Functions ---
async def notify_users_in_room(room_code, message):
    if room_code in ROOMS:
        tasks = [user.send_str(json.dumps(message)) for user in ROOMS[room_code]]
        if tasks:
            await asyncio.gather(*tasks)


async def handle_disconnect(ws, room_code):
    if room_code in ROOMS and ws in ROOMS[room_code]:
        user_name = ROOMS[room_code].pop(ws)
        print(f"{user_name} disconnected from room {room_code}")
        if not ROOMS[room_code]:
            del ROOMS[room_code]
            print(f"Room {room_code} deleted (empty)")
        else:
            await notify_users_in_room(room_code, {
                "type": "user_left",
                "userName": user_name
            })


# --- WebSocket Handler ---
async def websocket_handler(request):
    print(">>> Incoming WebSocket connection")
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    print(">>> WS handshake successful")

    # Accept all origins (for Android app)
    origin = request.headers.get("Origin")
    print(f"Connection Origin: {origin}")

    # Send a JSON-formatted connection confirmation
    await ws.send_str(json.dumps({
        "type": "status",
        "message": "Connected to SecureCom WebSocket server"
    }))

    current_room_code = None

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except json.JSONDecodeError:
                    print("Received non-JSON message:", msg.data)
                    continue

                msg_type = data.get("type")

                if msg_type == "join":
                    user_name = data["userName"]
                    room_code = data["roomCode"]
                    print(f"{user_name} joined {room_code}")

                    ROOMS.setdefault(room_code, {})[ws] = user_name
                    current_room_code = room_code

                    await ws.send_str(json.dumps({"type": "joined", "roomCode": room_code}))
                    await notify_users_in_room(room_code, {"type": "user_joined", "userName": user_name})

                elif msg_type == "message":
                    room_code = data["roomCode"]
                    message = {
                        "type": "message",
                        "userName": data["userName"],
                        "text": data["text"]
                    }
                    await notify_users_in_room(room_code, message)

            elif msg.type == web.WSMsgType.ERROR:
                print(f"WS error: {ws.exception()}")

    finally:
        if current_room_code:
            await handle_disconnect(ws, current_room_code)

    return ws


# --- Serve HTML ---
async def handle_http(request):
    return web.FileResponse("./index.html")


# --- App Setup ---
app = web.Application()
app.router.add_get("/", handle_http)
app.router.add_get("/ws", websocket_handler)


# --- Start Server ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"Server starting on 0.0.0.0:{port}")
    web.run_app(app, host="0.0.0.0", port=port)

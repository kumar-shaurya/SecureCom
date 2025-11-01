import asyncio
import json
import os
import random
import string
from aiohttp import web

# --- Data Structure ---
# ROOMS: { roomCode: { ws_object: userName } }
ROOMS = {}


# --- Helpers ---
def gen_username():
    # simple random username generator: UserXXXX
    return "User" + "".join(random.choices(string.digits, k=4))


def normalize_incoming(data):
    """
    Accept both { action: 'join', ... } (client) and { type: 'join', ... } (other)
    Return a tuple (kind, payload) where kind is 'create'|'join'|'leave'|'message' etc.
    """
    if not isinstance(data, dict):
        return None, data
    if "action" in data:
        return data["action"], data
    if "type" in data:
        # legacy: map server 'type' -> treat as action
        return data["type"], data
    return None, data


async def notify_users_in_room(room_code, message):
    """
    Send JSON message object to all connected websockets in a room.
    """
    if room_code not in ROOMS:
        return
    payload = json.dumps(message)
    tasks = []
    for ws in list(ROOMS[room_code].keys()):
        try:
            tasks.append(ws.send_str(payload))
        except Exception:
            # if a ws can't send, ignore here; disconnect cleanup will handle it
            pass
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def handle_disconnect(ws, room_code):
    """
    Remove ws from room and notify other users.
    """
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


# --- WebSocket handler ---
async def websocket_handler(request):
    print(">>> Incoming WebSocket connection")
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    print(">>> WS handshake successful")

    origin = request.headers.get("Origin")
    print(f"Connection Origin: {origin}")

    # Send JSON-formatted connection confirmation (frontend expects JSON)
    await ws.send_str(json.dumps({
        "type": "status",
        "message": "Connected to SecureCom WebSocket server"
    }))

    current_room_code = None
    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                raw = msg.data
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    print("Received non-JSON message (ignored):", raw)
                    # ignore non-JSON messages; continue loop
                    continue

                kind, payload = normalize_incoming(data)
                # handle create / join / leave / message
                if kind == "create":
                    # payload may contain { code: <customCode> }
                    custom_code = payload.get("code")
                    # if no custom code provided, generate random room code
                    if custom_code:
                        room_code = str(custom_code)
                    else:
                        room_code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))

                    # create room and assign a username
                    user_name = gen_username()
                    ROOMS.setdefault(room_code, {})[ws] = user_name
                    current_room_code = room_code

                    print(f"Room created: {room_code} by {user_name}")

                    # respond with the exact type your index.html expects
                    await ws.send_str(json.dumps({
                        "type": "room_created",
                        "code": room_code,
                        "userName": user_name
                    }))

                elif kind == "join":
                    # join existing room
                    room_code = payload.get("code")
                    if not room_code:
                        await ws.send_str(json.dumps({"type": "error", "message": "Missing room code"}))
                        continue

                    if room_code not in ROOMS:
                        # room doesn't exist
                        await ws.send_str(json.dumps({"type": "error", "message": "Room does not exist"}))
                        continue

                    user_name = gen_username()
                    ROOMS[room_code][ws] = user_name
                    current_room_code = room_code

                    print(f"{user_name} joined {room_code}")

                    # send joined_success to the joining user
                    await ws.send_str(json.dumps({
                        "type": "joined_success",
                        "code": room_code,
                        "userName": user_name
                    }))

                    # notify others in room
                    await notify_users_in_room(room_code, {
                        "type": "user_joined",
                        "userName": user_name
                    })

                elif kind == "leave":
                    # client requested leave
                    if current_room_code:
                        await handle_disconnect(ws, current_room_code)
                        current_room_code = None
                        await ws.send_str(json.dumps({"type": "error", "message": "Left room"}))
                    else:
                        await ws.send_str(json.dumps({"type": "error", "message": "Not in a room"}))

                elif kind == "message":
                    # client message payload: { action: 'message', text: '...' }
                    if not current_room_code:
                        await ws.send_str(json.dumps({"type": "error", "message": "Not in a room"}))
                        continue

                    text = payload.get("text", "")
                    sender = ROOMS[current_room_code].get(ws, "Unknown")
                    print(f"[{current_room_code}] {sender}: {text}")

                    # broadcast to room under the type expected by index.html
                    await notify_users_in_room(current_room_code, {
                        "type": "new_message",
                        "userName": sender,
                        "text": text
                    })

                elif kind == "file":
                    # placeholder for file upload messages (if implemented client-side)
                    if not current_room_code:
                        await ws.send_str(json.dumps({"type": "error", "message": "Not in a room"}))
                        continue
                    # expected payload: { action: 'file', name: '...', url: '...' }
                    await notify_users_in_room(current_room_code, {
                        "type": "new_file",
                        "name": payload.get("name"),
                        "url": payload.get("url"),
                        "userName": ROOMS.get(current_room_code, {}).get(ws, "Unknown")
                    })

                else:
                    # Unknown action/type: ignore or send error
                    await ws.send_str(json.dumps({"type": "error", "message": f"Unknown action: {kind}"}))

            elif msg.type == web.WSMsgType.ERROR:
                print(f"WebSocket error: {ws.exception()}")

    finally:
        # cleanup on disconnect
        if current_room_code:
            await handle_disconnect(ws, current_room_code)
        else:
            # ensure this ws is removed if it exists anywhere
            for rc in list(ROOMS.keys()):
                if ws in ROOMS.get(rc, {}):
                    await handle_disconnect(ws, rc)
        print(">>> Connection closed/cleaned up")
    return ws


# --- Serve HTML ---
async def handle_http(request):
    # serve index.html from project root
    return web.FileResponse("./index.html")


# --- App Setup ---
app = web.Application()
app.router.add_get("/", handle_http)
app.router.add_get("/ws", websocket_handler)

# static route: if your index.html references any assets under /static/, uncomment below:
# app.router.add_static("/static/", path="./static", name="static")

# --- Start Server ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"Server starting on 0.0.0.0:{port}")
    web.run_app(app, host="0.0.0.0", port=port)

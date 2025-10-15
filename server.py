import asyncio
import websockets
import random
import json
import os
from aiohttp import web

# --- Data Structure ---
# This remains the same.
# {'12345': {ws_user1: 'User 1', ws_user2: 'User 2'}}
ROOMS = {}

# --- WebSocket Logic (largely unchanged) ---

async def notify_users_in_room(room_code, message):
    if room_code in ROOMS:
        tasks = [user.send_str(json.dumps(message)) for user in ROOMS[room_code]]
        if tasks:
            await asyncio.gather(*tasks)

async def handle_disconnect(websocket, room_code):
    if room_code in ROOMS and websocket in ROOMS[room_code]:
        user_name = ROOMS[room_code].pop(websocket)
        print(f"{user_name} disconnected from room {room_code}.")
        if not ROOMS[room_code]:
            del ROOMS[room_code]
            print(f"Room {room_code} is empty and has been deleted.")
        else:
            notification = {"type": "user_left", "userName": user_name}
            await notify_users_in_room(room_code, notification)

async def websocket_handler(request):
    """
    Handles the WebSocket connections.
    This is the core chat logic, adapted for aiohttp.
    """
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    current_room_code = None
    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                data = json.loads(msg.data)
                action = data.get("action")

                if action == "create":
                    custom_code = data.get("code")
                    if custom_code:
                        if custom_code in ROOMS:
                            await ws.send_str(json.dumps({"type": "error", "message": f"Channel ID '{custom_code}' is already in use."}))
                            continue
                        else:
                            room_code = custom_code
                    else:
                        room_code = str(random.randint(10000, 99999))
                        while room_code in ROOMS:
                            room_code = str(random.randint(10000, 99999))
                    
                    ROOMS[room_code] = {ws: "User 1"}
                    current_room_code = room_code
                    await ws.send_str(json.dumps({"type": "room_created", "code": room_code, "userName": "User 1"}))
                    print(f"Room {room_code} created by User 1.")

                elif action == "join":
                    code_to_join = data.get("code")
                    if code_to_join in ROOMS:
                        room = ROOMS[code_to_join]
                        user_number = len(room) + 1
                        user_name = f"User {user_number}"
                        room[ws] = user_name
                        current_room_code = code_to_join
                        await ws.send_str(json.dumps({"type": "joined_success", "code": code_to_join, "userName": user_name}))
                        notification = {"type": "user_joined", "userName": user_name}
                        await notify_users_in_room(code_to_join, notification)
                        print(f"{user_name} joined room {code_to_join}.")
                    else:
                        await ws.send_str(json.dumps({"type": "error", "message": "Room not found."}))

                elif action == "message" and current_room_code:
                    sender_name = ROOMS[current_room_code].get(ws)
                    broadcast_message = {"type": "new_message", "sender": sender_name, "text": data.get("text")}
                    tasks = [user.send_str(json.dumps(broadcast_message)) for user in ROOMS[current_room_code] if user != ws]
                    if tasks: await asyncio.gather(*tasks)

                elif action == "file" and current_room_code:
                    sender_name = ROOMS[current_room_code].get(ws)
                    broadcast_message = {
                        "type": "new_file", "sender": sender_name, "filename": data.get("filename"),
                        "filetype": data.get("filetype"), "filedata": data.get("filedata")
                    }
                    tasks = [user.send_str(json.dumps(broadcast_message)) for user in ROOMS[current_room_code] if user != ws]
                    if tasks: await asyncio.gather(*tasks)

                elif action == "leave" and current_room_code:
                    await handle_disconnect(ws, current_room_code)
                    current_room_code = None
                    await ws.close()

            elif msg.type == web.WSMsgType.ERROR:
                print(f'ws connection closed with exception {ws.exception()}')

    finally:
        if current_room_code:
            await handle_disconnect(ws, current_room_code)
    
    return ws

# --- HTTP Logic (to serve the HTML file) ---

async def handle_http(request):
    """Serves the index.html file."""
    return web.FileResponse('./index.html')

# --- Application Setup ---

app = web.Application()
app.router.add_get('/', handle_http)  # Serve index.html at the root URL
app.router.add_get('/ws', websocket_handler) # Handle WebSocket connections at /ws

if __name__ == '__main__':
    # Get port from environment variable for Render, default to 8080 for local dev
    port = int(os.environ.get('PORT', 8080))
    # Host on 0.0.0.0 to be accessible from outside the container
    web.run_app(app, host='0.0.0.0', port=port)
    print(f"Server running on http://0.0.0.0:{port}")


import asyncio
import json
import os
from aiohttp import web

# --- Data Structure ---
# { 'roomCode': { ws_object: 'userName' } }
ROOMS = {}


# --- Utility Functions ---
async def notify_users_in_room(room_code, message):
    """Sends a JSON message to all users in a specific room."""
    if room_code in ROOMS:
        tasks = [user.send_str(json.dumps(message)) for user in ROOMS[room_code]]
        if tasks:
            await asyncio.gather(*tasks)


async def handle_disconnect(ws, room_code):
    """Handles user disconnection, removes them from the room, and notifies others."""
    if room_code in ROOMS and ws in ROOMS[room_code]:
        user_name = ROOMS[room_code].pop(ws)
        print(f"{user_name} disconnected from room {room_code}")
        
        # If the room is now empty, delete it
        if not ROOMS[room_code]:
            del ROOMS[room_code]
            print(f"Room {room_code} deleted (empty)")
        else:
            # Notify remaining users
            await notify_users_in_room(room_code, {
                "type": "user_left",
                "userName": user_name
            })


# --- WebSocket Handler ---
async def websocket_handler(request):
    """Handles all incoming WebSocket connections and messages."""
    print(">>> Incoming WebSocket connection")
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    print(">>> WS handshake successful")

    origin = request.headers.get("Origin")
    print(f"Connection Origin: {origin}")

    # Send initial connection success message
    await ws.send_str("✅ Connected to SecureCom WebSocket server")

    current_room_code = None

    try:
        # Iterate over incoming WebSocket messages
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    msg_type = data.get("type")

                    if msg_type == "join":
                        user_name = data["userName"]
                        room_code = data["roomCode"]
                        print(f"{user_name} joined {room_code}")

                        # Add user to the room
                        ROOMS.setdefault(room_code, {})[ws] = user_name
                        current_room_code = room_code

                        # Notify user they joined successfully
                        await ws.send_str(json.dumps({"type": "joined", "roomCode": room_code}))
                        # Notify other users in the room
                        await notify_users_in_room(room_code, {"type": "user_joined", "userName": user_name})

                    elif msg_type == "message":
                        room_code = data["roomCode"]
                        message = {
                            "type": "message",
                            "userName": data["userName"],
                            "text": data["text"]
                        }
                        # Broadcast message to all users in the room
                        await notify_users_in_room(room_code, message)
                        
                except json.JSONDecodeError:
                    print(f"Received invalid JSON: {msg.data}")
                except KeyError as e:
                    print(f"Missing expected key in message: {e} - Data: {msg.data}")
                except Exception as e:
                    print(f"Error processing message: {e}")

            elif msg.type == web.WSMsgType.ERROR:
                print(f"WS error: {ws.exception()}")

    except Exception as e:
        print(f"An unexpected error occurred: {e}")

    finally:
        # Handle cleanup on disconnect
        print(f"Connection closing...")
        if current_room_code:
            await handle_disconnect(ws, current_room_code)

    return ws


# --- Serve HTML ---
async def handle_http(request):
    """Serves the main index.html file."""
    return web.FileResponse("./index.html")


# --- App Setup ---
app = web.Application()
app.router.add_get("/", handle_http)
app.router.add_get("/ws", websocket_handler)


# --- Start Server ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"🚀 Server starting on 0.0.0.0:{port}")
    web.run_app(app, host="0.0.0.0", port=port)

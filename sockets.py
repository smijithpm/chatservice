import asyncio
import websockets
import json
from collections import defaultdict
import time

connected_clients = {}
messages = defaultdict(list)

async def chat_handler(websocket):
    username = None
    try:
        # Registration with case normalization
        data = json.loads(await websocket.recv())
        if data.get("action") == "register":
            username = data["username"].lower()
            connected_clients[username] = websocket
            print(f"✅ {username} connected")
            
            # Send pending messages
            for contact in list(messages.keys()):
                if username in contact:
                    partner = contact[0] if contact[1] == username else contact[1]
                    await websocket.send(json.dumps({
                        "action": "initial_messages",
                        "partner": partner,
                        "messages": messages[contact]
                    }))
        
        # Message handling loop
        async for message in websocket:
            data = json.loads(message)
            action = data.get("action")
            
            if action == "send":
                sender = data["sender"].lower()
                receiver = data["receiver"].lower()
                msg_content = data["message"]
                chat_key = tuple(sorted((sender, receiver)))
                
                # Create message object
                msg_obj = {
                    "sender": sender,
                    "message": msg_content,
                    "timestamp": time.time(),
                    "status": "delivered"
                }
                
                # Store message
                messages[chat_key].append(msg_obj)
                
                # Immediate delivery
                if receiver in connected_clients:
                    await connected_clients[receiver].send(json.dumps({
                        "action": "new_message",
                        "message": msg_obj
                    }))
                print(f"📩 {sender} -> {receiver}: {msg_content}")

    except websockets.ConnectionClosed:
        print(f"⚠️ Connection closed for {username}")
    finally:
        if username and username in connected_clients:
            del connected_clients[username]
            print(f"❌ {username} disconnected")

async def main():
    async with websockets.serve(chat_handler, "0.0.0.0", 8765):
        print("🚀 WebSocket server running on ws://0.0.0.0:8765")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
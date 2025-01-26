import streamlit as st
import asyncio
import websockets
import threading
import json
from queue import Queue, Empty
from collections import defaultdict
import time

# Configuration
WS_URI = "ws://localhost:8765"
USER_DB = {
    "user1": "pass1",
    "user2": "pass2",
    "user3": "pass3"
}

# Session state initialization (MUST BE AT TOP LEVEL)
if "chat" not in st.session_state:
    st.session_state.chat = {
        "logged_in": False,
        "username": None,
        "selected_user": None,
        "conversations": defaultdict(list),
        "outgoing": Queue(),
        "ws_manager": None
    }

def main():
    if not st.session_state.chat["logged_in"]:
        show_login()
    else:
        show_chat_interface()
        manage_websocket()

def show_login():
    st.title("Login")
    username = st.text_input("Username").strip()
    password = st.text_input("Password", type="password")
    
    if st.button("Login"):
        auth_user = username.lower()
        if USER_DB.get(auth_user) == password:
            initialize_session(auth_user)
        else:
            st.error("Invalid username or password")

def initialize_session(username):
    st.session_state.chat.update({
        "logged_in": True,
        "username": username,
        "selected_user": None,
        "outgoing": Queue(),
        "ws_manager": WebSocketManager(username)
    })
    st.session_state.chat["ws_manager"].start()
    st.rerun()

def show_chat_interface():
    chat_state = st.session_state.chat
    current_user = chat_state.get("username", "")
    
    # Sidebar organization
    with st.sidebar:
        st.header(f"👤 {current_user.capitalize()}")
        st.markdown("---")
        
        # User selection
        available_users = [u for u in USER_DB if u != current_user]
        selected_user = st.selectbox(
            "Select contact:",
            available_users,
            key="user_select"
        )
        
        # Update selected user
        if chat_state.get("selected_user") != selected_user:
            chat_state["selected_user"] = selected_user
            chat_state["outgoing"].put({
                "action": "get_history",
                "partner": selected_user
            })
        
        # Logout button at bottom of sidebar
        st.markdown("---")
        if st.button("🚪 Logout", use_container_width=True):
            cleanup_session()

    # Main chat area
    st.title(f"💬 Chat with {chat_state['selected_user'].capitalize()}")
    
    # Display messages
    chat_key = tuple(sorted((current_user, chat_state["selected_user"])))
    messages = chat_state["conversations"].get(chat_key, [])
    
    for msg in messages:
        if msg["sender"] == current_user:
            with st.chat_message("user"):
                st.write(msg["message"])
        else:
            with st.chat_message("assistant"):
                st.write(f"{msg['sender']}: {msg['message']}")
    
    # Message input
    if prompt := st.chat_input("Type your message..."):
        new_msg = {
            "sender": current_user,
            "message": prompt,
            "timestamp": time.time()
        }
        chat_state["conversations"][chat_key].append(new_msg)
        chat_state["outgoing"].put({
            "action": "send",
            "receiver": chat_state["selected_user"],
            "message": prompt
        })
        st.rerun()
    
    process_incoming_messages()

def process_incoming_messages():
    manager = st.session_state.chat.get("ws_manager")
    if not manager or not manager.incoming:
        return
    
    try:
        while True:
            msg = manager.incoming.get_nowait()
            if msg.get("action") == "new_message":
                handle_incoming_message(msg)
            elif msg.get("action") == "initial_messages":
                handle_initial_messages(msg)
            st.rerun()
    except Empty:
        pass

def handle_incoming_message(msg):
    chat_state = st.session_state.chat
    message_data = msg.get("message", {})
    sender = message_data.get("sender", "").lower()
    current_user = chat_state.get("username", "").lower()
    
    if sender and sender != current_user:
        chat_key = tuple(sorted((sender, current_user)))
        chat_state["conversations"][chat_key].append(message_data)

def handle_initial_messages(msg):
    chat_state = st.session_state.chat
    partner = msg.get("partner", "").lower()
    current_user = chat_state.get("username", "").lower()
    
    if partner and partner != current_user:
        chat_key = tuple(sorted((partner, current_user)))
        chat_state["conversations"][chat_key] = msg.get("messages", [])

def manage_websocket():
    chat_state = st.session_state.chat
    if not chat_state.get("ws_manager") or not chat_state["ws_manager"].is_alive():
        chat_state["ws_manager"] = WebSocketManager(chat_state["username"])
        chat_state["ws_manager"].start()

def cleanup_session():
    chat_state = st.session_state.chat
    if chat_state.get("ws_manager"):
        chat_state["ws_manager"].stop()
    
    # Reset chat state without clearing entire session
    chat_state.update({
        "logged_in": False,
        "username": None,
        "selected_user": None,
        "conversations": defaultdict(list),
        "outgoing": Queue(),
        "ws_manager": None
    })
    st.rerun()

class WebSocketManager(threading.Thread):
    def __init__(self, username):
        super().__init__(daemon=True)
        self.username = username
        self.incoming = Queue()
        self.outgoing = st.session_state.chat["outgoing"]
        self.running = True
        self.loop = None

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.ws_connection())

    async def ws_connection(self):
        async with websockets.connect(WS_URI) as ws:
            # Register user
            await ws.send(json.dumps({
                "action": "register",
                "username": self.username
            }))
            
            # Start sender/receiver tasks
            sender = asyncio.create_task(self.handle_send(ws))
            receiver = asyncio.create_task(self.handle_receive(ws))
            await asyncio.gather(sender, receiver)

    async def handle_send(self, ws):
        while self.running:
            try:
                msg = self.outgoing.get(timeout=0.1)
                await ws.send(json.dumps(msg))
            except Empty:
                await asyncio.sleep(0.1)
            except Exception as e:
                print(f"Send error: {str(e)}")
                break

    async def handle_receive(self, ws):
        while self.running:
            try:
                message = await asyncio.wait_for(ws.recv(), timeout=1)
                data = json.loads(message)
                self.incoming.put(data)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"Receive error: {str(e)}")
                break

    def stop(self):
        self.running = False
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)

if __name__ == "__main__":
    main()
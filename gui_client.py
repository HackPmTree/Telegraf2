#!/usr/bin/env python3
"""
Графический клиент чата (KivyMD).
Локальное хранилище: JSON-файл, без SQLite.
Подключается к серверу 150.241.106.197:5000
"""
import socket
import threading
import json
import os
import time
from kivy.lang import Builder
from kivy.uix.screenmanager import ScreenManager, Screen
from kivymd.app import MDApp
from kivymd.uix.list import TwoLineListItem
from kivymd.uix.dialog import MDDialog
from kivymd.uix.textfield import MDTextField
from kivymd.uix.button import MDRaisedButton
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel
from kivy.clock import Clock
from kivy.properties import StringProperty, ObjectProperty

# ---------- Локальная JSON-база ----------
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'local_chat.json')

def _load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def _save_db(data):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def save_message(chat_id, sender, text, timestamp=None):
    data = _load_db()
    if chat_id not in data:
        data[chat_id] = []
    data[chat_id].append({
        'sender': sender,
        'text': text,
        'timestamp': timestamp if timestamp else time.time()
    })
    _save_db(data)

def get_messages(chat_id, limit=50):
    data = _load_db()
    msgs = data.get(chat_id, [])
    return [(m['sender'], m['text'], m['timestamp']) for m in msgs[-limit:]]

def get_last_message(chat_id):
    msgs = get_messages(chat_id, 1)
    if msgs:
        return msgs[0][1]
    return ''
# --------------------------------------------------------

SERVER_HOST = '150.241.106.197'
SERVER_PORT = 5000

Builder.load_file('screens/chat_list.kv')
Builder.load_file('screens/chat_room.kv')

class ChatNetwork:
    def __init__(self, server_host, server_port, message_callback):
        self.host = server_host
        self.port = server_port
        self.sock = None
        self.running = False
        self.callback = message_callback

    def connect(self, nick, password):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((self.host, self.port))
        resp = self.sock.recv(1024).decode()
        self.sock.sendall(f"AUTH {nick} {password}\n".encode())
        resp = self.sock.recv(1024).decode().strip()
        if not resp.startswith("OK"):
            raise Exception(resp)
        self.running = True
        threading.Thread(target=self._recv_loop, daemon=True).start()

    def _recv_loop(self):
        buf = b''
        while self.running:
            try:
                data = self.sock.recv(4096)
                if not data:
                    break
                buf += data
                while b'\n' in buf:
                    line, buf = buf.split(b'\n', 1)
                    Clock.schedule_once(lambda dt, l=line.decode().strip(): self.callback(l))
            except:
                break
        self.running = False

    def send(self, text):
        if self.sock:
            self.sock.sendall((text + '\n').encode())

    def close(self):
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except:
                pass

class ChatListScreen(Screen):
    chat_list = ObjectProperty(None)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.chats = {}

    def on_enter(self):
        self.update_chat_list()

    def update_chat_list(self):
        self.chat_list.clear_widgets()
        for chat_id, info in self.chats.items():
            last_msg = get_last_message(chat_id)
            item = TwoLineListItem(
                text=f"{chat_id} ({'группа' if info['type']=='group' else 'личный'})",
                secondary_text=last_msg[:50] + ('...' if len(last_msg)>50 else ''),
                on_release=lambda x, cid=chat_id: self.open_chat(cid)
            )
            self.chat_list.add_widget(item)

    def open_chat(self, chat_id):
        self.manager.get_screen('chat_room').chat_id = chat_id
        self.manager.current = 'chat_room'

class ChatRoomScreen(Screen):
    chat_id = StringProperty('')
    messages_list = ObjectProperty(None)
    message_input = ObjectProperty(None)

    def on_enter(self):
        self.load_messages()

    def load_messages(self):
        self.messages_list.clear_widgets()
        msgs = get_messages(self.chat_id)
        for sender, text, ts in msgs:
            time_str = time.strftime('%H:%M', time.localtime(ts))
            card = MDCard(size_hint=(None, None), width=300, padding=10, elevation=2, adaptive_height=True)
            card.add_widget(MDLabel(text=f"{sender}: {text}\n{time_str}"))
            self.messages_list.add_widget(card)

    def send_message(self):
        app = MDApp.get_running_app()
        text = self.message_input.text.strip()
        if not text:
            return
        if self.chat_id in app.groups:
            app.network.send(f"send {self.chat_id} {text}")
        else:
            app.network.send(f"chat {self.chat_id} {text}")
        save_message(self.chat_id, app.nick, text)
        self.message_input.text = ''
        self.load_messages()

class MainApp(MDApp):
    def build(self):
        self.theme_cls.primary_palette = "Blue"
        self.sm = ScreenManager()
        self.sm.add_widget(ChatListScreen(name='chat_list'))
        self.sm.add_widget(ChatRoomScreen(name='chat_room'))
        return self.sm

    def on_start(self):
        self.show_login()

    def show_login(self):
        self.dialog = MDDialog(
            title="Вход",
            type="custom",
            content=MDTextField(hint_text="Ник"),
            buttons=[MDRaisedButton(text="Войти", on_release=self.login)]
        )
        self.dialog.open()

    def login(self, instance):
        nick = self.dialog.content.text.strip()
        password = "1"
        self.nick = nick
        self.groups = []
        self.network = ChatNetwork(SERVER_HOST, SERVER_PORT, self.on_message)
        try:
            self.network.connect(nick, password)
            self.dialog.dismiss()
        except Exception as e:
            print(f"Ошибка: {e}")

    def on_message(self, line):
        if line.startswith('MSG '):
            parts = line.split(' ', 1)
            if len(parts) > 1:
                rest = parts[1]
                if ': ' in rest:
                    sender, text = rest.split(': ', 1)
                else:
                    sender, text = rest, ''
                chat_id = sender
                save_message(chat_id, sender, text)
                self.sm.get_screen('chat_list').chats[chat_id] = {'type': 'private', 'last_msg': text}
                self.sm.get_screen('chat_list').update_chat_list()
                if self.sm.current == 'chat_room' and self.sm.get_screen('chat_room').chat_id == chat_id:
                    self.sm.get_screen('chat_room').load_messages()
        elif line.startswith('GROUP '):
            parts = line.split(' ', 2)
            if len(parts) >= 3:
                gname = parts[1]
                rest = parts[2]
                if ': ' in rest:
                    sender, text = rest.split(': ', 1)
                else:
                    sender, text = rest, ''
                save_message(gname, sender, text)
                self.sm.get_screen('chat_list').chats[gname] = {'type': 'group', 'last_msg': text}
                self.sm.get_screen('chat_list').update_chat_list()
                if self.sm.current == 'chat_room' and self.sm.get_screen('chat_room').chat_id == gname:
                    self.sm.get_screen('chat_room').load_messages()
        elif line.startswith('GROUPS: '):
            groups_str = line.split(' ', 1)[1]
            self.groups = groups_str.split(', ')
            for g in self.groups:
                self.sm.get_screen('chat_list').chats[g] = {'type': 'group', 'last_msg': ''}
            self.sm.get_screen('chat_list').update_chat_list()

if __name__ == '__main__':
    MainApp().run()

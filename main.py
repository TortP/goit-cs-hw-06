import os
import json
import socket
import multiprocessing
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs
from datetime import datetime
from pymongo import MongoClient, errors


HTTP_PORT = 3000
SOCKET_PORT = 5000
STATIC_DIR = "./static"
TEMPLATES_DIR = "./templates"
LOCAL_STORAGE = "./storage/data.json"
MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongodb:27017/")
DB_NAME = "webapp"
COLLECTION_NAME = "messages"


class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self._send_file("index.html")
        elif self.path == "/message":
            self._send_file("message.html")
        elif self.path.startswith("/static/"):
            self._send_static_file()
        else:
            self._send_file("error.html", 404)

    def do_POST(self):
        if self.path == "/message":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            data = parse_qs(body)
            message_data = {
                "date": datetime.now().isoformat(),
                "username": data.get("username", [""])[0],
                "message": data.get("message", [""])[0]
            }

            self._save_to_local_storage(message_data)

            try:
                self._send_to_socket_server(message_data)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"Message received and saved!")
            except ConnectionRefusedError:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"Error: Cannot connect to Socket server!")

    def _save_to_local_storage(self, message_data):
        if not os.path.exists(os.path.dirname(LOCAL_STORAGE)):
            os.makedirs(os.path.dirname(LOCAL_STORAGE))
        if not os.path.exists(LOCAL_STORAGE):
            with open(LOCAL_STORAGE, "w") as file:
                json.dump([], file)

        with open(LOCAL_STORAGE, "r+") as file:
            try:
                data = json.load(file)
                if not isinstance(data, list):
                    data = []
            except json.JSONDecodeError:
                data = []

            data.append(message_data)
            file.seek(0)
            json.dump(data, file, indent=4)
            file.truncate()

    def _send_to_socket_server(self, message_data):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect(("localhost", SOCKET_PORT))
            sock.sendall(json.dumps(message_data).encode("utf-8"))

    def _send_file(self, filename, status=200):
        try:
            with open(os.path.join(TEMPLATES_DIR, filename), "rb") as f:
                self.send_response(status)
                self.end_headers()
                self.wfile.write(f.read())
        except FileNotFoundError:
            self._send_file("error.html", 404)

    def _send_static_file(self):
        file_path = self.path.lstrip("/")
        try:
            with open(file_path, "rb") as f:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(f.read())
        except FileNotFoundError:
            self._send_file("error.html", 404)


def socket_server():
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        db = client[DB_NAME]
        collection = db[COLLECTION_NAME]
        print("Connected to MongoDB")

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
            server_socket.bind(("0.0.0.0", SOCKET_PORT))
            server_socket.listen(5)
            print(f"Socket server running on port {SOCKET_PORT}")

            while True:
                client_socket, address = server_socket.accept()
                with client_socket:
                    data = client_socket.recv(1024)
                    if data:
                        message_data = json.loads(data.decode("utf-8"))
                        message_data["date"] = datetime.now().isoformat()
                        try:
                            collection.insert_one(message_data)
                            print("Message saved to MongoDB:", message_data)
                        except errors.PyMongoError as e:
                            print(f"Database Error: {e}")
    except errors.ServerSelectionTimeoutError as e:
        print(f"MongoDB Connection Error: {e}")


if __name__ == "__main__":
    http_process = multiprocessing.Process(
        target=lambda: HTTPServer(
            ("0.0.0.0", HTTP_PORT), SimpleHTTPRequestHandler).serve_forever()
    )
    socket_process = multiprocessing.Process(target=socket_server)

    http_process.start()
    print(f"HTTP server running on port {HTTP_PORT}")
    socket_process.start()

    http_process.join()
    socket_process.join()

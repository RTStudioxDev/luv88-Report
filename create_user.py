from werkzeug.security import generate_password_hash
from pymongo import MongoClient
from datetime import datetime

MONGO_URI = "mongodb://admin:060843Za@147.50.240.76:27017/"
DB_NAME = "luv88db"
client = MongoClient(MONGO_URI)
db = client[DB_NAME]
users_collection = db["users"]

def create_user(username, password):
    # ตรวจสอบว่าผู้ใช้ซ้ำไหม
    if users_collection.find_one({"username": username}):
        print("User already exists!")
        return False

    hashed_password = generate_password_hash(password)
    user_doc = {
        "username": username,
        "password_hash": hashed_password,
        "created_at": datetime.utcnow()
    }
    users_collection.insert_one(user_doc)
    print(f"User {username} created successfully!")
    return True

# ใช้งานสร้างผู้ใช้ใหม่
create_user("rtstudio", "123456Xx")

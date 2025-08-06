from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from pymongo import MongoClient
from functools import wraps
import requests
from datetime import datetime, timedelta, time as dt_time
from collections import defaultdict
from apscheduler.schedulers.background import BackgroundScheduler
from werkzeug.security import check_password_hash
import os

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY")
MONGO_URI = os.environ.get("MONGO_URI")
DB_NAME = os.environ.get("luv88db")
client = MongoClient(MONGO_URI)
db = client[DB_NAME]
collection = db["deposits"]
user_collection = db["users"]
AUTO_FETCH_HOUR = 0
AUTO_FETCH_MINUTE = 5
app.config["AUTO_FETCHING"] = False
SESSION_TIMEOUT = 300
NODE_API_BASE = os.environ.get("NODE_API_BASE")

# --------- Helper Functions ---------
def clean_amount(text):
    try:
        return float(text.replace("เครดิต", "").replace(",", "").strip())
    except Exception:
        return 0.0

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login", next=request.url))
        return f(*args, **kwargs)
    return decorated_function

# --------- Auto Fetch Scheduler ---------
def auto_fetch_previous_day():
    app.config["AUTO_FETCHING"] = True
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"[Auto Fetch] Fetching deposits for date: {yesterday}")
    try:
        payload = {
            "username": "Boysr",
            "password": "1234566Xx",
            "prefix": "luv88",
            "date": yesterday
        }
        resp = requests.post(f"{NODE_API_BASE}/fetch", json=payload, timeout=120)
        if resp.status_code == 200:
            data = resp.json()
            deposits = data.get("deposits", [])
            for d in deposits:
                filter_query = {"txn_id": d["txn_id"], "fetch_date": d["fetch_date"]}
                collection.update_one(filter_query, {"$set": d}, upsert=True)
            print(f"[Auto Fetch] Completed: {len(deposits)} records saved.")
        else:
            print("[Auto Fetch] Error: Node API status", resp.status_code)
    except Exception as e:
        print("[Auto Fetch] Exception:", e)
    app.config["AUTO_FETCHING"] = False

scheduler = BackgroundScheduler()
scheduler.add_job(auto_fetch_previous_day, 'cron', hour=AUTO_FETCH_HOUR, minute=AUTO_FETCH_MINUTE)
scheduler.start()

# --------- Session Timeout ---------
@app.before_request
def make_session_permanent():
    if "logged_in" in session:
        now = datetime.now()
        last_activity = session.get("last_activity")
        if last_activity:
            try:
                last_time = datetime.fromisoformat(last_activity)
                elapsed = (now - last_time).total_seconds()
                if elapsed > SESSION_TIMEOUT:
                    session.clear()
                    flash("หมดเวลาใช้งานกรุณาล็อกอินใหม่", "warning")
                    return redirect(url_for("login"))
            except Exception:
                pass
        session["last_activity"] = now.isoformat()

# --------- Auth & Main Page ---------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        user = user_collection.find_one({"username": username})
        if user:

            if "password_hash" in user:
                if check_password_hash(user["password_hash"], password):
                    session["logged_in"] = True
                    session["username"] = username
                    flash("ล็อกอินสำเร็จ", "success")
                    next_page = request.args.get("next")
                    return redirect(next_page or url_for("index"))
                else:
                    flash("รหัสผ่านไม่ถูกต้อง", "danger")
            else:
                if user.get("password") == password:
                    session["logged_in"] = True
                    session["username"] = username
                    flash("ล็อกอินสำเร็จ", "success")
                    next_page = request.args.get("next")
                    return redirect(next_page or url_for("index"))
                else:
                    flash("รหัสผ่านไม่ถูกต้อง", "danger")
        else:
            flash("ไม่พบชื่อผู้ใช้", "danger")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("ออกจากระบบเรียบร้อยแล้ว", "success")
    return redirect(url_for("login"))

@app.route("/")
@login_required
def index():
    now = datetime.now()
    run_time_today = datetime.combine(now.date(), dt_time(AUTO_FETCH_HOUR, AUTO_FETCH_MINUTE))
    if now >= run_time_today:
        next_run = run_time_today + timedelta(days=1)
    else:
        next_run = run_time_today

    is_auto_fetching = app.config.get("AUTO_FETCHING", False)

    return render_template("index.html",
                           is_auto_fetching=is_auto_fetching,
                           auto_fetching=is_auto_fetching,
                           next_run_timestamp=int(next_run.timestamp() * 1000))

# --------- Fetch Route (ดึงผ่าน API + save ลง DB) ---------
@app.route("/fetch", methods=["POST"])
@login_required
def fetch():
    selected_date = request.form.get("selected_date")
    payload = {
        "username": "Boysr",
        "password": "1234566Xx",
        "prefix": "luv88",
        "date": selected_date
    }
    try:
        resp = requests.post(f"{NODE_API_BASE}/fetch", json=payload, timeout=120)
        if resp.status_code == 200:
            data = resp.json()
            for d in data.get("deposits", []):
                filter_query = {"txn_id": d["txn_id"], "fetch_date": d["fetch_date"]}
                collection.update_one(filter_query, {"$set": d}, upsert=True)
            flash("ดึงยอดสำเร็จ", "success")
        else:
            flash("เกิดข้อผิดพลาดในการดึงยอด", "danger")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    return redirect(url_for("report", date=selected_date))

# --------- Report ---------
@app.route("/report", methods=["GET"])
@login_required
def report():
    selected_date = request.args.get("date")
    if selected_date:
        deposits = list(collection.find({"fetch_date": selected_date}))
    else:
        latest_doc = collection.find_one(sort=[("fetch_date", -1)])
        selected_date = latest_doc.get("fetch_date") if latest_doc else None
        deposits = list(collection.find({"fetch_date": selected_date})) if selected_date else []
    totals = defaultdict(float)
    deductions = defaultdict(float)
    manual_total = 0.0
    total_deductions_amount = 0.0
    for d in deposits:
        amt = clean_amount(d.get("deposit_amount", "0"))
        icon = d.get("bank_icon", "")
        status = d.get("status", "")
        remark = d.get("remark", "")
        deposit_type = d.get("deposit_type", "Auto")

        # <== เช็คยอดตัดเครดิตก่อน!
        if "ตัดเครดิต" in status or "ตัดเครดิต" in remark:
            deductions[icon] += amt
            total_deductions_amount += amt
            continue   # <== ถ้าเจอตัดเครดิต ให้ continue ไม่ต้องนับเข้า Manual/Auto แล้ว

        if deposit_type == "Manual":
            manual_total += amt
            totals[icon] += amt
            continue

        totals[icon] += amt
    net_totals = {key: totals.get(key, 0) - deductions.get(key, 0) for key in set(list(totals)+list(deductions))}
    total_net_amount = sum(net_totals.values())
    total_sum = sum(totals.values())
    net_after_deduction = total_sum - total_deductions_amount
    return render_template(
        "report.html",
        deposits=deposits,
        totals=totals,
        deductions=deductions,
        net_totals=net_totals,
        total_net_amount=total_net_amount,
        manual_total=manual_total,
        fetch_date=selected_date,
        total_deductions_amount=total_deductions_amount,
        net_after_deduction=net_after_deduction,
        deposit_type_summary={
            "Auto": sum(clean_amount(d.get("deposit_amount", "0")) for d in deposits if d.get("deposit_type") == "Auto"),
            "Manual": manual_total
        }
    )

# --------- History ---------
@app.route("/history")
@login_required
def history():
    dates = collection.distinct("fetch_date")
    dates.sort(reverse=True)
    return render_template("history.html", dates=dates)

@app.route("/history/delete/<date>", methods=["POST"])
@login_required
def delete_history(date):
    result = collection.delete_many({"fetch_date": date})
    flash(f"ลบประวัติและข้อมูลวันที่ {date} สำเร็จ ({result.deleted_count} รายการ)", "success")
    return redirect(url_for("history"))

@app.route("/history/<date>")
@login_required
def history_date(date):
    deposits = list(collection.find({"fetch_date": date}))
    totals = defaultdict(float)
    deductions = defaultdict(float)
    manual_total = 0.0
    total_deductions_amount = 0.0
    for d in deposits:
        amt = clean_amount(d.get("deposit_amount", "0"))
        icon = d.get("bank_icon", "")
        status = d.get("status", "")
        remark = d.get("remark", "")
        deposit_type = d.get("deposit_type", "Auto")

        # นับยอดตัดเครดิตก่อนเสมอ (สำคัญสุด)
        if "ตัดเครดิต" in status or "ตัดเครดิต" in remark:
            deductions[icon] += amt
            total_deductions_amount += amt
            continue

        if deposit_type == "Manual":
            manual_total += amt
            totals[icon] += amt
            continue

        totals[icon] += amt
    net_totals = {key: totals.get(key, 0) - deductions.get(key, 0) for key in set(totals) | set(deductions)}
    total_net_amount = sum(net_totals.values())
    total_sum = sum(totals.values())
    net_after_deduction = total_sum - total_deductions_amount
    return render_template(
        "report.html",
        deposits=deposits,
        totals=totals,
        deductions=deductions,
        net_totals=net_totals,
        total_net_amount=total_net_amount,
        manual_total=manual_total,
        total_deductions_amount=total_deductions_amount,
        net_after_deduction=net_after_deduction,
        fetch_date=date,
        deposit_type_summary={
            "Auto": sum(clean_amount(d.get("deposit_amount", "0")) for d in deposits if d.get("deposit_type") == "Auto"),
            "Manual": manual_total
        }
    )

@app.route("/auto_fetch_status")
@login_required
def auto_fetch_status():
    status = app.config.get("AUTO_FETCHING", False)
    return {"auto_fetching": status}

if __name__ == "__main__":
    # app.run(host="0.0.0.0", port=5000, debug=False)
    app.run()

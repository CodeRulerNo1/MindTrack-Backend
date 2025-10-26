from flask import Flask, request, jsonify
from flask_cors import CORS
import json
from datetime import date, timedelta
import random
import os
import firebase_admin
from firebase_admin import credentials, firestore
import base64 

# --- Firebase Setup ---
# (This auth code is correct and working)
try:
    base64_key = os.environ.get('FIREBASE_SERVICE_ACCOUNT_BASE64')
    if base64_key:
        print("Found FIREBASE_SERVICE_ACCOUNT_BASE64 env variable. Decoding...")
        decoded_key_bytes = base64.b64decode(base64_key)
        decoded_key_str = decoded_key_bytes.decode('utf-8')
        key_dict = json.loads(decoded_key_str)
        cred = credentials.Certificate(key_dict)
        print("Authentication successful using environment variable.")
    else:
        print("FIREBASE_SERVICE_ACCOUNT_BASE64 not set. Falling back to 'serviceAccountKey.json' file...")
        cred = credentials.Certificate("serviceAccountKey.json")
        print("Authentication successful using file.")
        
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("Firebase connection successful.")
except Exception as e:
    print(f"CRITICAL ERROR: Failed to initialize Firebase. Error: {e}")
    raise e

# --- App Setup ---
app = Flask(__name__)
CORS(app, expose_headers=['X-User-Id']) 

# --- Firestore Collection References ---
APP_ID = "mindtrack-hackathon-v2-users" 

def get_user_collections(userId):
    """Returns the specific collection references for a given user."""
    if not userId:
        raise ValueError("A User ID is required for all database operations.")
    HABITS_COL = db.collection(f'artifacts/{APP_ID}/users/{userId}/habits')
    LOGS_COL = db.collection(f'artifacts/{APP_ID}/users/{userId}/logs')
    return HABITS_COL, LOGS_COL

def get_or_create_user_data(userId):
    """
    Checks if a user exists. If not, creates their default habits.
    """
    HABITS_COL, LOGS_COL = get_user_collections(userId)
    meta_doc_ref = LOGS_COL.document('__meta__')
    meta_doc = meta_doc_ref.get()
    
    if not meta_doc.exists:
        print(f"New user detected (ID: {userId}). Creating default habits...")
        default_habits = [
            {'name': 'Drink 8 glasses of water', 'is_deletable': False, 'created_at': firestore.SERVER_TIMESTAMP},
            {'name': 'Read for 20 minutes', 'is_deletable': False, 'created_at': firestore.SERVER_TIMESTAMP},
            {'name': 'Go for a 15-min walk', 'is_deletable': False, 'created_at': firestore.SERVER_TIMESTAMP}
        ]
        batch = db.batch()
        for habit in default_habits:
            doc_ref = HABITS_COL.document() 
            batch.set(doc_ref, habit)
        batch.set(meta_doc_ref, {'default_habits_set': True, 'created_at': firestore.SERVER_TIMESTAMP})
        batch.commit()
        print(f"Default habits added for user {userId}.")

# --- Stats Calculation Logic ---
def calculate_stats(userId):
    """Analyzes and returns trends for a SPECIFIC user."""
    HABITS_COL, LOGS_COL = get_user_collections(userId)
    log_docs = LOGS_COL.where('habits_json', '!=', '[]').stream()
    total_days, habit_counts, logged_dates, total_habits_completed = 0, {}, set(), 0

    for doc in log_docs:
        if doc.id == '__meta__': continue
        row, log_date_str = doc.to_dict(), doc.id 
        logged_dates.add(log_date_str); total_days += 1
        try:
            habits = json.loads(row['habits_json'])
            total_habits_completed += len(habits)
            for habit in habits: habit_counts[habit] = habit_counts.get(habit, 0) + 1
        except (json.JSONDecodeError, KeyError): print(f"Warning: Skipping corrupt log entry for date {log_date_str}")

    best_habit = "None yet"
    if habit_counts: best_habit = max(habit_counts, key=habit_counts.get)

    current_streak = 0
    check_date = date.today()
    if check_date.isoformat() in logged_dates:
        current_streak = 1; check_date -= timedelta(days=1)
        while check_date.isoformat() in logged_dates: current_streak += 1; check_date -= timedelta(days=1)
    elif (date.today() - timedelta(days=1)).isoformat() in logged_dates:
        check_date = date.today() - timedelta(days=1)
        while check_date.isoformat() in logged_dates: current_streak += 1; check_date -= timedelta(days=1)
            
    streak_emoji = "😔"
    if 1 <= current_streak <= 3: streak_emoji = "😊"
    elif 4 <= current_streak <= 7: streak_emoji = "🔥"
    elif current_streak > 7: streak_emoji = "🏆"
            
    return {"total_days": total_days, "best_habit": best_habit.capitalize(), "current_streak": current_streak, "total_habits_completed": total_habits_completed, "streak_emoji": streak_emoji}

# --- ======== THIS IS THE FIX ======== ---

def _get_all_habits(userId):
    """
    INTERNAL helper function to fetch habits. Is NOT an endpoint.
    This fixes the "Working outside of request context" error.
    """
    HABITS_COL, _ = get_user_collections(userId)
    docs = HABITS_COL.order_by('created_at').stream()
    habits = []
    for doc in docs:
        habit_data = doc.to_dict()
        habit_data['id'] = doc.id 
        habits.append(habit_data)
    return habits

# --- ======== Endpoints ======== ---
def db_operation(func):
    """Wrapper to catch errors and handle user ID."""
    try:
        userId = request.headers.get('X-User-Id')
        if not userId:
            return jsonify({"error": "Missing X-User-Id header"}), 400
        get_or_create_user_data(userId) 
        return func(userId)
    except Exception as e:
        # Use repr(e) to get more detailed error info in logs
        print(f"Error in endpoint {request.path}: {repr(e)}")
        return jsonify({"error": "An internal server error occurred."}), 500

@app.route('/')
def home():
    return "MindTrack Backend is running with Firestore (User Accounts Enabled)!"

# --- Habit Management Endpoints ---

@app.route('/get_habits', methods=['GET'])
@db_operation
def get_habits(userId):
    """Fetches the complete list of habits for the user."""
    habits = _get_all_habits(userId) # Calls the safe helper
    return jsonify(habits), 200

@app.route('/add_habit', methods=['POST'])
@db_operation
def add_habit(userId):
    """Adds a new, deletable habit for the user."""
    HABITS_COL, _ = get_user_collections(userId)
    data = request.get_json()
    habit_name = data.get('name')
    if not habit_name: return jsonify({"error": "Habit name is required"}), 400
    existing = HABITS_COL.where('name', '==', habit_name).limit(1).get()
    if len(existing) > 0: return jsonify({"error": "This habit already exists"}), 409
    HABITS_COL.add({'name': habit_name, 'is_deletable': True, 'created_at': firestore.SERVER_TIMESTAMP})
    
    habits = _get_all_habits(userId) # Calls the safe helper
    return jsonify(habits), 200

@app.route('/delete_habit', methods=['POST'])
@db_operation
def delete_habit(userId):
    """Deletes a habit by its Firestore Document ID for the user."""
    HABITS_COL, _ = get_user_collections(userId)
    data = request.get_json()
    habit_id = data.get('id') 
    if not habit_id: return jsonify({"error": "Habit ID is required"}), 400

    doc_ref = HABITS_COL.document(habit_id)
    doc = doc_ref.get()
    
    if not doc.exists: return jsonify({"error": "Habit not found"}), 404
    if doc.to_dict().get('is_deletable') == True:
        doc_ref.delete()
        habits = _get_all_habits(userId) # Calls the safe helper
        return jsonify(habits), 200
    else:
        return jsonify({"error": "Cannot delete a default habit"}), 403

# --- Log & Stats Endpoints ---

@app.route('/get_today_logs', methods=['GET'])
@db_operation
def get_today_logs(userId):
    """Fetches only the logs for the current day for the user."""
    _, LOGS_COL = get_user_collections(userId)
    today_date_string = date.today().isoformat()
    doc = LOGS_COL.document(today_date_string).get()
    if doc.exists:
        habits_list = json.loads(doc.to_dict().get('habits_json', '[]'))
        return jsonify(habits_list), 200
    else: return jsonify([]), 200 

@app.route('/log', methods=['POST'])
@db_operation
def log_habit(userId):
    """Saves a list of habit names for today for the user."""
    _, LOGS_COL = get_user_collections(userId)
    data = request.get_json()
    habits_list = data.get('habits', []) 
    habits_as_json_string = json.dumps(habits_list)
    today_date_string = date.today().isoformat()

    LOGS_COL.document(today_date_string).set({'habits_json': habits_as_json_string, 'log_timestamp': firestore.SERVER_TIMESTAMP}, merge=True)
    print(f"Successfully logged/updated habits for {today_date_string} (User: {userId})")
    return jsonify({"message": f"Successfully logged {len(habits_list)} habits!"}), 200

@app.route('/get_logs', methods=['GET'])
@db_operation
def get_logs(userId):
    """Fetches all logs from the database for the calendar for the user."""
    _, LOGS_COL = get_user_collections(userId)
    docs = LOGS_COL.stream()
    logs = {}
    for doc in docs:
        if doc.id == '__meta__': continue 
        row = doc.to_dict()
        try:
            habits = json.loads(row['habits_json'])
            if habits: logs[doc.id] = habits
        except (json.JSONDecodeError, KeyError): print(f"Warning: Skipping corrupt calendar log for date {doc.id}")
    return jsonify(logs), 200

@app.route('/get_stats', methods=['GET'])
@db_operation
def get_stats(userId):
    """Calls shared logic function for the user."""
    stats = calculate_stats(userId)
    return jsonify(stats), 200

@app.route('/get_motivation', methods=['GET'])
@db_operation
def get_motivation(userId):
    """Provides a motivational message based on the user's current streak."""
    stats = calculate_stats(userId)
    streak = stats.get('current_streak', 0)
    if streak == 0: messages = ["The journey of a thousand miles begins with one step. Let's log Day 1!","A new beginning! You've got this."]
    elif 1 <= streak <= 3: messages = [f"Day {streak}! Great start. Keep the momentum going.", "Consistency is key. You're building a new habit!"]
    elif 4 <= streak <= 7: messages = [f"{streak} days in a row! You're on fire!", "Almost a full week! Amazing discipline."]
    else: messages = [f"Wow, {streak} days! You've made this a real habit.", "Incredible consistency! You're an inspiration."]
    return jsonify({"message": random.choice(messages)}), 200

@app.route('/get_suggestion', methods=['POST'])
@db_operation
def get_suggestion(userId):
    return jsonify({"suggestion": "Let's focus on consistency for now!"}), 200

# --- NEW FRIEND ENDPOINT ---
@app.route('/get_friend_stats', methods=['GET'])
def get_friend_stats():
    """Fetches the stats for a *different* user (a friend)."""
    try:
        friendId = request.args.get('userId')
        if not friendId: return jsonify({"error": "Missing 'userId' query parameter"}), 400
        
        # We must check if the user exists *before* calculating stats
        # by checking for their meta document.
        _, LOGS_COL = get_user_collections(friendId)
        meta_doc = LOGS_COL.document('__meta__').get()
        
        if not meta_doc.exists:
            return jsonify({"error": "Friend not found"}), 404
            
        # User exists, now calculate stats
        stats = calculate_stats(friendId)
        friend_safe_stats = {
            "current_streak": stats.get('current_streak', 0),
            "streak_emoji": stats.get('streak_emoji', '😶'),
            "total_days": stats.get('total_days', 0)
        }
        return jsonify(friend_safe_stats), 200
    except ValueError:
         return jsonify({"error": "Friend not found"}), 404
    except Exception as e:
        print(f"Error in /get_friend_stats: {repr(e)}")
        return jsonify({"error": "An internal server error occurred."}), 500

# --- Main ---
if __name__ == '__main__':
    # No global init_db() anymore. It's user-specific and lazy-loaded.
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

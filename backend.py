from flask import Flask, request, jsonify
from flask_cors import CORS
import json
from datetime import date, timedelta
import random
import os
import firebase_admin
from firebase_admin import credentials, firestore
import base64 # <-- NEW: For decoding the key
from dotenv import load_dotenv # <-- NEW: To load .env locally (won't be used on Render)

# --- Firebase Setup ---
# THIS IS THE NEW AUTHENTICATION METHOD
# It reads the key from the environment variable you just set on Render

try:
    # 1. Try to get the Base64 key from Render's environment
    base64_key = os.environ.get('FIREBASE_SERVICE_ACCOUNT_BASE64')
    
    if base64_key:
        print("Found FIREBASE_SERVICE_ACCOUNT_BASE64 env variable. Decoding...")
        # 2. Decode the Base64 string back into bytes, then into a string
        decoded_key_bytes = base64.b64decode(base64_key)
        decoded_key_str = decoded_key_bytes.decode('utf-8')
        # 3. Parse the string into a JSON dictionary
        key_dict = json.loads(decoded_key_str)
        
        # 4. Authenticate using the dictionary
        cred = credentials.Certificate(key_dict)
        print("Authentication successful using environment variable.")
    else:
        # 5. Fallback for local testing: load from file
        print("FIREBASE_SERVICE_ACCOUNT_BASE64 not set. Falling back to 'serviceAccountKey.json' file...")
        cred = credentials.Certificate("serviceAccountKey.json")
        print("Authentication successful using file.")

    firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("Firebase connection successful.")

except Exception as e:
    print(f"CRITICAL ERROR: Failed to initialize Firebase. Error: {e}")
    # This will stop the app from starting, which is correct.
    raise e

# --- App Setup ---
app = Flask(__name__)
CORS(app)

# --- Firestore Collection References ---
APP_ID = "mindtrack-hackathon-v1" 
HABITS_COL = db.collection(f'artifacts/{APP_ID}/public/data/habits')
LOGS_COL = db.collection(f'artifacts/{APP_ID}/public/data/logs')

def init_db():
    """Initializes the database and creates default habits if they don't exist."""
    print("Initializing Firestore database...")
    
    meta_doc_ref = LOGS_COL.document('__meta__')
    meta_doc = meta_doc_ref.get()
    
    if not meta_doc.exists:
        print("Adding default habits...")
        default_habits = [
            {'name': 'Drink 8 glasses of water', 'is_deletable': False, 'created_at': firestore.SERVER_TIMESTAMP},
            {'name': 'Read for 20 minutes', 'is_deletable': False, 'created_at': firestore.SERVER_TIMESTAMP},
            {'name': 'Go for a 15-min walk', 'is_deletable': False, 'created_at': firestore.SERVER_TIMESTAMP}
        ]
        
        batch = db.batch()
        for habit in default_habits:
            doc_ref = HABITS_COL.document() 
            batch.set(doc_ref, habit)
        
        batch.set(meta_doc_ref, {'default_habits_set': True})
        batch.commit()
        print("Default habits added successfully.")
    else:
        print("Database already initialized.")

# --- Stats Calculation Logic ---
def calculate_stats():
    """Analyzes and returns user trends from Firestore."""
    
    log_docs = LOGS_COL.where('habits_json', '!=', '[]').stream()

    total_days = 0
    habit_counts = {}
    logged_dates = set()
    total_habits_completed = 0

    for doc in log_docs:
        if doc.id == '__meta__':
            continue
            
        row = doc.to_dict()
        log_date_str = doc.id 
        logged_dates.add(log_date_str)
        total_days += 1
        
        try:
            habits = json.loads(row['habits_json'])
            total_habits_completed += len(habits)
            for habit in habits:
                habit_counts[habit] = habit_counts.get(habit, 0) + 1
        except (json.JSONDecodeError, KeyError):
            print(f"Warning: Skipping corrupt log entry for date {log_date_str}")

    best_habit = "None yet"
    if habit_counts:
        best_habit = max(habit_counts, key=habit_counts.get)

    current_streak = 0
    check_date = date.today()
    
    if check_date.isoformat() in logged_dates:
        current_streak = 1
        check_date -= timedelta(days=1)
        while check_date.isoformat() in logged_dates:
            current_streak += 1
            check_date -= timedelta(days=1)
    elif (date.today() - timedelta(days=1)).isoformat() in logged_dates:
        check_date = date.today() - timedelta(days=1)
        while check_date.isoformat() in logged_dates:
            current_streak += 1
            check_date -= timedelta(days=1)
            
    streak_emoji = "😔"
    if 1 <= current_streak <= 3: streak_emoji = "😊"
    elif 4 <= current_streak <= 7: streak_emoji = "🔥"
    elif current_streak > 7: streak_emoji = "🏆"
            
    return {
        "total_days": total_days,
        "best_habit": best_habit.capitalize(),
        "current_streak": current_streak,
        "total_habits_completed": total_habits_completed,
        "streak_emoji": streak_emoji
    }

# --- ======== Endpoints ======== ---

@app.route('/')
def home():
    return "MindTrack Backend is running with Firestore!"

# --- Habit Management Endpoints ---
def db_operation(func):
    """Wrapper to catch errors"""
    try:
        return func()
    except Exception as e:
        print(f"Error in endpoint {request.path}: {e}")
        return jsonify({"error": "An internal server error occurred."}), 500

@app.route('/get_habits', methods=['GET'])
def get_habits():
    """Fetches the complete list of habits from the DB."""
    def operation():
        docs = HABITS_COL.order_by('created_at').stream()
        habits = []
        for doc in docs:
            habit_data = doc.to_dict()
            habit_data['id'] = doc.id 
            habits.append(habit_data)
        return jsonify(habits), 200
    return db_operation(operation)


@app.route('/add_habit', methods=['POST'])
def add_habit():
    """Adds a new, deletable habit to the DB."""
    def operation():
        data = request.get_json()
        habit_name = data.get('name')
        if not habit_name:
            return jsonify({"error": "Habit name is required"}), 400
        
        existing = HABITS_COL.where('name', '==', habit_name).limit(1).get()
        if len(existing) > 0:
            return jsonify({"error": "This habit already exists"}), 409

        new_habit_data = {
            'name': habit_name,
            'is_deletable': True,
            'created_at': firestore.SERVER_TIMESTAMP
        }
        HABITS_COL.add(new_habit_data)
        
        return get_habits()
    return db_operation(operation)


@app.route('/delete_habit', methods=['POST'])
def delete_habit():
    """Deletes a habit by its Firestore Document ID."""
    def operation():
        data = request.get_json()
        habit_id = data.get('id') 
        if not habit_id:
            return jsonify({"error": "Habit ID is required"}), 400

        doc_ref = HABITS_COL.document(habit_id)
        doc = doc_ref.get()
        
        if not doc.exists:
             return jsonify({"error": "Habit not found"}), 404
             
        if doc.to_dict().get('is_deletable') == True:
            doc_ref.delete()
            return get_habits()
        else:
            return jsonify({"error": "Cannot delete a default habit"}), 403
    return db_operation(operation)

# --- Log & Stats Endpoints ---

@app.route('/get_today_logs', methods=['GET'])
def get_today_logs():
    """Fetches only the logs for the current day."""
    def operation():
        today_date_string = date.today().isoformat()
        doc_ref = LOGS_COL.document(today_date_string)
        doc = doc_ref.get()
        
        if doc.exists:
            habits_list = json.loads(doc.to_dict().get('habits_json', '[]'))
            return jsonify(habits_list), 200
        else:
            return jsonify([]), 200 
    return db_operation(operation)


@app.route('/log', methods=['POST'])
def log_habit():
    """Saves a list of habit names for today."""
    def operation():
        data = request.get_json()
        habits_list = data.get('habits', []) 
        habits_as_json_string = json.dumps(habits_list)
        today_date_string = date.today().isoformat()

        LOGS_COL.document(today_date_string).set({
            'habits_json': habits_as_json_string,
            'log_timestamp': firestore.SERVER_TIMESTAMP
        }, merge=True)
        
        print(f"Successfully logged/updated habits for {today_date_string}: {habits_list}")
        return jsonify({"message": f"Successfully logged {len(habits_list)} habits!"}), 200
    return db_operation(operation)


@app.route('/get_logs', methods=['GET'])
def get_logs():
    """Fetches all logs from the database for the calendar."""
    def operation():
        docs = LOGS_COL.stream()
        logs = {}
        for doc in docs:
            if doc.id == '__meta__': continue 
            
            row = doc.to_dict()
            try:
                habits = json.loads(row['habits_json'])
                if habits: 
                     logs[doc.id] = habits
            except (json.JSONDecodeError, KeyError):
                print(f"Warning: Skipping corrupt calendar log for date {doc.id}")
            
        return jsonify(logs), 200
    return db_operation(operation)


@app.route('/get_stats', methods=['GET'])
def get_stats():
    def operation():
        stats = calculate_stats()
        return jsonify(stats), 200
    return db_operation(operation)


@app.route('/get_motivation', methods=['GET'])
def get_motivation():
    def operation():
        stats = calculate_stats()
        streak = stats.get('current_streak', 0)

        if streak == 0: messages = ["The journey of a thousand miles begins with one step. Let's log Day 1!","A new beginning! You've got this."]
        elif 1 <= streak <= 3: messages = [f"Day {streak}! Great start. Keep the momentum going.", "Consistency is key. You're building a new habit!"]
        elif 4 <= streak <= 7: messages = [f"{streak} days in a row! You're on fire!", "Almost a full week! Amazing discipline."]
        else: messages = [f"Wow, {streak} days! You've made this a real habit.", "Incredible consistency! You're an inspiration."]
        
        message = random.choice(messages)
        return jsonify({"message": message}), 200
    return db_operation(operation)

@app.route('/get_suggestion', methods=['POST'])
def get_suggestion():
    return jsonify({"suggestion": "Let's focus on consistency for now!"}), 200

# --- Main ---
if __name__ == '__main__':
    # We run init_db() when the server starts
    init_db()
    # Get port from environment variable, default to 5000
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

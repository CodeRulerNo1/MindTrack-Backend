from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import json
from datetime import date, timedelta
import random
import os # <-- Import os

# Initialize the Flask app
app = Flask(__name__)
# Enable CORS (Cross-Origin Resource Sharing)
CORS(app)

# --- Database Setup ---
# CRITICAL: This path MUST match your Render Persistent Disk Mount Path
DB_NAME = '/var/data/mindtrack.db'
DB_DIR = os.path.dirname(DB_NAME)

def get_db_conn():
    """Helper to get a DB connection that returns dict-like rows."""
    try:
        if not os.path.exists(DB_DIR):
            print(f"Error: Database directory {DB_DIR} does not exist. Did you add the Persistent Disk?")
            return None # Return None to show a clear error
        
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        # This will now clearly log the "unable to open" error
        print(f"CRITICAL ERROR in get_db_conn: {e}")
        return None

def init_db():
    """Initializes the database and creates tables if they don't exist."""
    try:
        # Check if the directory exists first
        if not os.path.exists(DB_DIR):
            print(f"Attempting to create directory: {DB_DIR}")
            # Try to create it, though this may fail on Render if disk is not mounted
            os.makedirs(DB_DIR, exist_ok=True) 
            
        print(f"Initializing database at: {DB_NAME}")
        conn = get_db_conn()
        if conn is None:
            raise Exception("Failed to get DB connection in init_db. Check disk permissions.")
            
        cursor = conn.cursor()
        
        # Table 1: Store the list of habits
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            is_deletable INTEGER NOT NULL DEFAULT 1
        )
        ''')
        
        # Table 2: Store the daily logs
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS habit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_date TEXT NOT NULL UNIQUE,
            habits_json TEXT
        )
        ''')
        
        # Add default habits only if the table is empty
        cursor.execute("SELECT COUNT(id) FROM habits")
        count = cursor.fetchone()[0]
        if count == 0:
            print("Adding default habits...")
            default_habits = [
                ('Drink 8 glasses of water', 0),
                ('Read for 20 minutes', 0),
                ('Go for a 15-min walk', 0)
            ]
            cursor.executemany("INSERT OR IGNORE INTO habits (name, is_deletable) VALUES (?, ?)", default_habits)

        conn.commit()
        conn.close()
        print("Database initialized successfully.")
    except Exception as e:
        print(f"CRITICAL ERROR during init_db: {e}")
        # This will make the app fail to start, which is better than running in a broken state
        raise e


# --- Stats Calculation Logic ---
def calculate_stats():
    """
    Analyzes and returns user trends.
    """
    conn = get_db_conn()
    if conn is None:
        raise Exception("Database connection failed in calculate_stats")
        
    cursor = conn.cursor()
    # Fetch all logs where at least one habit was logged
    cursor.execute("SELECT log_date, habits_json FROM habit_logs WHERE habits_json != '[]' ORDER BY log_date DESC")
    rows = cursor.fetchall()
    conn.close()

    total_days = len(rows)
    habit_counts = {}
    logged_dates = set()
    total_habits_completed = 0 # <-- NEW FEATURE 1

    for row in rows:
        logged_dates.add(row['log_date'])
        try:
            habits = json.loads(row['habits_json'])
            total_habits_completed += len(habits) # <-- NEW FEATURE 1
            for habit in habits:
                habit_counts[habit] = habit_counts.get(habit, 0) + 1
        except json.JSONDecodeError:
            print(f"Warning: Skipping corrupt log entry for date {row['log_date']}")

    # Calculate Best Habit
    best_habit = "None yet"
    if habit_counts:
        best_habit = max(habit_counts, key=habit_counts.get)

    # Calculate Current Streak
    current_streak = 0
    check_date = date.today()
    
    if check_date.isoformat() in logged_dates:
        current_streak = 1
        check_date -= timedelta(days=1)
        while check_date.isoformat() in logged_dates:
            current_streak += 1
            check_date -= timedelta(days=1)
    # If today is not logged, check starting from yesterday
    elif (date.today() - timedelta(days=1)).isoformat() in logged_dates:
        check_date = date.today() - timedelta(days=1)
        while check_date.isoformat() in logged_dates:
            current_streak += 1
            check_date -= timedelta(days=1)
            
    # <-- NEW FEATURE 2: STREAK EMOJI -->
    streak_emoji = "😔" # Default
    if 1 <= current_streak <= 3:
        streak_emoji = "😊"
    elif 4 <= current_streak <= 7:
        streak_emoji = "🔥"
    elif current_streak > 7:
        streak_emoji = "🏆"
    # <-- END NEW FEATURE 2 -->
            
    return {
        "total_days": total_days,
        "best_habit": best_habit.capitalize(),
        "current_streak": current_streak,
        "total_habits_completed": total_habits_completed, # <-- NEW
        "streak_emoji": streak_emoji # <-- NEW
    }


# --- ======== Endpoints ======== ---

@app.route('/')
def home():
    return "MindTrack Backend is running with SQLite!"

# --- Habit Management Endpoints ---
# Helper function to handle DB errors in endpoints
def db_operation(func):
    try:
        return func()
    except Exception as e:
        print(f"Error in endpoint {request.path}: {e}")
        # Check for the specific "unable to open" error
        if "unable to open" in str(e) or "connection failed" in str(e):
             return jsonify({"error": "Database connection error. Check server logs and disk setup."}), 500
        return jsonify({"error": "An internal server error occurred."}), 500

@app.route('/get_habits', methods=['GET'])
def get_habits():
    """Fetches the complete list of habits from the DB."""
    def operation():
        conn = get_db_conn()
        if conn is None: raise Exception("Database connection failed")
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, is_deletable FROM habits ORDER BY id")
        habits = [dict(row) for row in cursor.fetchall()]
        conn.close()
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

        conn = get_db_conn()
        if conn is None: raise Exception("Database connection failed")
        
        try:
            cursor = conn.cursor()
            # Insert with is_deletable=1 (True)
            cursor.execute("INSERT OR IGNORE INTO habits (name, is_deletable) VALUES (?, 1)", (habit_name,))
            conn.commit()
            
            # Return the complete, updated list
            cursor.execute("SELECT id, name, is_deletable FROM habits ORDER BY id")
            habits = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return jsonify(habits), 200

        except sqlite3.IntegrityError:
            conn.close()
            return jsonify({"error": "This habit already exists"}), 409
    return db_operation(operation)


@app.route('/delete_habit', methods=['POST'])
def delete_habit():
    """Deletes a habit, only if it's marked as deletable."""
    def operation():
        data = request.get_json()
        habit_id = data.get('id')
        if not habit_id:
            return jsonify({"error": "Habit ID is required"}), 400

        conn = get_db_conn()
        if conn is None: raise Exception("Database connection failed")
        cursor = conn.cursor()
        # Only delete habits where is_deletable = 1
        cursor.execute("DELETE FROM habits WHERE id = ? AND is_deletable = 1", (habit_id,))
        conn.commit()
        
        # Return the complete, updated list
        cursor.execute("SELECT id, name, is_deletable FROM habits ORDER BY id")
        habits = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return jsonify(habits), 200
    return db_operation(operation)

# --- Log & Stats Endpoints ---

@app.route('/get_today_logs', methods=['GET'])
def get_today_logs():
    """Fetches only the logs for the current day."""
    def operation():
        today_date_string = date.today().isoformat()
        conn = get_db_conn()
        if conn is None: raise Exception("Database connection failed")
        cursor = conn.cursor()
        cursor.execute("SELECT habits_json FROM habit_logs WHERE log_date = ?", (today_date_string,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            habits_list = json.loads(row['habits_json'])
            return jsonify(habits_list), 200
        else:
            # Return empty list if no log for today
            return jsonify([]), 200
    return db_operation(operation)


@app.route('/log', methods=['POST'])
def log_habit():
    """Receives a list of habit names and saves them for today."""
    def operation():
        data = request.get_json()
        habits_list = data.get('habits', []) # e.g., ["water", "reading"]
        habits_as_json_string = json.dumps(habits_list)
        today_date_string = date.today().isoformat()

        conn = get_db_conn()
        if conn is None: raise Exception("Database connection failed")
        cursor = conn.cursor()
        
        # Use 'INSERT OR REPLACE' to update today's log
        cursor.execute('''
        INSERT OR REPLACE INTO habit_logs (log_date, habits_json)
        VALUES (?, ?)
        ''', (today_date_string, habits_as_json_string))
        
        conn.commit()
        conn.close()
        
        print(f"Successfully logged/updated habits for {today_date_string}: {habits_list}")
        return jsonify({"message": f"Successfully logged {len(habits_list)} habits!"}), 200
    return db_operation(operation)


@app.route('/get_logs', methods=['GET'])
def get_logs():
    """Fetches all logs from the database for the calendar."""
    def operation():
        conn = get_db_conn()
        if conn is None: raise Exception("Database connection failed")
        cursor = conn.cursor()
        cursor.execute("SELECT log_date, habits_json FROM habit_logs ORDER BY log_date DESC")
        rows = cursor.fetchall()
        conn.close()
        
        logs = {}
        for row in rows:
            try:
                habits = json.loads(row['habits_json'])
                if habits: # Only include non-empty log days
                     logs[row['log_date']] = habits
            except json.JSONDecodeError:
                print(f"Warning: Skipping corrupt calendar log for date {row['log_date']}")
            
        return jsonify(logs), 200
    return db_operation(operation)


@app.route('/get_stats', methods=['GET'])
def get_stats():
    """This endpoint calls our shared logic function."""
    def operation():
        stats = calculate_stats()
        return jsonify(stats), 200
    return db_operation(operation)


@app.route('/get_motivation', methods=['GET'])
def get_motivation():
    """Provides a motivational message based on the user's current streak."""
    def operation():
        stats = calculate_stats()
        streak = stats.get('current_streak', 0)

        if streak == 0:
            messages = [
                "The journey of a thousand miles begins with one step. Let's log Day 1!",
                "A new beginning! You've got this.",
                "Day 1 is the hardest part. Let's get it done!",
                "Don't wait for opportunity. Create it. Time to start your streak."
            ]
        elif 1 <= streak <= 3:
            messages = [
                f"Day {streak}! Great start. Keep the momentum going.",
                "Consistency is key. You're building a new habit!",
                "Awesome! You're on a roll. Let's aim for 7 days!"
            ]
        elif 4 <= streak <= 7:
            messages = [
                f"{streak} days in a row! You're on fire!",
                "Almost a full week! Amazing discipline.",
                "This is how habits are formed. Keep it up!"
            ]
        else: # Streak > 7
            messages = [
                f"Wow, {streak} days! You've made this a real habit.",
                "Incredible consistency! You're an inspiration.",
                "You're unstoppable! Keep crushing those goals."
            ]
        
        message = random.choice(messages)
        return jsonify({"message": message}), 200
    return db_operation(operation)


@app.route('/get_suggestion', methods=['POST'])
def get_suggestion():
    """Provides an AI-driven habit suggestion based on user history."""
    def operation():
        stats = calculate_stats()
        best_habit_name = stats.get('best_habit', 'None yet').lower()
        
        data = request.get_json()
        current_habits = data.get('current_habits', []) # e.g., ['water', 'reading', 'walk']

        possible_suggestions = []
        
        # Find a keyword from the best habit
        suggestion_key = 'general' # default
        for key in SUGGESTION_MAP:
            if key in best_habit_name:
                suggestion_key = key
                break
        
        possible_suggestions.extend(SUGGESTION_MAP[suggestion_key])
        possible_suggestions.extend(SUGGESTION_MAP['general'])
        
        # Filter out suggestions for habits the user *already* tracks
        filtered_suggestions = []
        for suggestion in possible_suggestions:
            is_already_tracking = False
            for existing_habit_name in current_habits:
                existing_words = existing_habit_name.split(' ')
                for word in existing_words:
                    if word.lower() in suggestion.lower() and len(word) > 3: # avoid 'a', 'for'
                        is_already_tracking = True
                        break
                if is_already_tracking:
                    break
            
            if not is_already_tracking:
                filtered_suggestions.append(suggestion)

        if not filtered_suggestions:
            suggestion = "Try a new healthy recipe!"
        else:
            suggestion = random.choice(filtered_suggestions)
        
        return jsonify({"suggestion": suggestion}), 200
    return db_operation(operation)


# --- Main ---
if __name__ == '__main__':
    # Initialize the database file first
    init_db()
    # Then run the server
    # Set debug=False for production!
    app.run(host='0.0.0.0', port=5000, debug=False)







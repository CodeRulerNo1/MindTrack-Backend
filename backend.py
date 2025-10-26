from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import json
from datetime import date, timedelta
import random

# Initialize the Flask app
app = Flask(__name__)
# Enable CORS (Cross-Origin Resource Sharing)
CORS(app)

# --- Database Setup ---
DB_NAME ='/var/data/mindtrack.db'

def init_db():
    """Initializes the database and creates the table if it doesn't exist."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS habit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        log_date TEXT NOT NULL UNIQUE,
        habits_json TEXT
    )
    ''')
    conn.commit()
    conn.close()

# --- Utility Function to get DB connection ---
def get_db_conn():
    """Helper to get a DB connection that returns dict-like rows."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

# --- AI Suggestion "Database" ---
# This is our simple rule-based "AI"
SUGGESTION_MAP = {
    'walking': ['Try a 5-min jog', 'Do 10 minutes of stretching', 'Go for a bike ride'],
    'reading': ['Write in a journal for 5 mins', 'Meditate for 5 mins', 'Learn a new word'],
    'water': ['Eat a piece of fruit', 'Try to get 8 hours of sleep', 'Eat a healthy breakfast'],
    'general': ['Meditate for 5 mins', 'Do 10 push-ups', 'Write in a journal', 'Read one chapter']
}

# --- Refactored Stats Logic ---
def calculate_stats():
    """
    Analyzes and returns user trends.
    This logic is now in its own function to be shared.
    """
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT log_date, habits_json FROM habit_logs WHERE habits_json != '[]' ORDER BY log_date DESC")
    rows = cursor.fetchall()
    conn.close()

    total_days = len(rows)
    habit_counts = {}
    logged_dates = set()

    # 1. Calculate Habit Counts and Logged Dates
    for row in rows:
        logged_dates.add(row['log_date'])
        habits = json.loads(row['habits_json'])
        for habit in habits:
            habit_counts[habit] = habit_counts.get(habit, 0) + 1

    # 2. Calculate Best Habit
    best_habit = "None yet"
    if habit_counts:
        best_habit = max(habit_counts, key=habit_counts.get)
        best_habit = best_habit.capitalize()

    # 3. Calculate Current Streak
    current_streak = 0
    check_date = date.today()
    
    today_logged = check_date.isoformat() in logged_dates
    
    if not today_logged:
        check_date = date.today() - timedelta(days=1)
        
    while check_date.isoformat() in logged_dates:
        current_streak += 1
        check_date -= timedelta(days=1)
    
    if today_logged and current_streak == 0:
        current_streak = 1
    elif today_logged and check_date == (date.today() - timedelta(days=1)):
        # This fixes a small bug where today's log wasn't counted if yesterday was also logged
        # This logic is a bit complex, let's simplify
        pass # The first 'while' loop handles the chain, 'today_logged' adds the last link.
        
    # Re-calculate streak logic to be simpler
    current_streak = 0
    check_date = date.today()
    
    # Check today
    if check_date.isoformat() in logged_dates:
        current_streak = 1
        check_date -= timedelta(days=1)
        # Check yesterday and so on
        while check_date.isoformat() in logged_dates:
            current_streak += 1
            check_date -= timedelta(days=1)
    # If today is not logged, check starting from yesterday
    elif (date.today() - timedelta(days=1)).isoformat() in logged_dates:
        check_date = date.today() - timedelta(days=1)
        while check_date.isoformat() in logged_dates:
            current_streak += 1
            check_date -= timedelta(days=1)
            
    return {
        "total_days": total_days,
        "best_habit": best_habit,
        "current_streak": current_streak
    }


# --- Endpoints ---
@app.route('/')
def home():
    return "MindTrack Backend is running with SQLite!"

@app.route('/log', methods=['POST'])
def log_habit():
    try:
        data = request.get_json()
        if not data or 'habits' not in data:
            return jsonify({"error": "Invalid data. 'habits' key is missing."}), 400

        habits_list = data.get('habits', [])
        habits_as_json_string = json.dumps(habits_list)
        today_date_string = date.today().isoformat()

        conn = get_db_conn()
        cursor = conn.cursor()
        cursor.execute('''
        INSERT OR REPLACE INTO habit_logs (log_date, habits_json)
        VALUES (?, ?)
        ''', (today_date_string, habits_as_json_string))
        conn.commit()
        conn.close()
        
        print(f"Successfully logged/updated habits for {today_date_string}: {habits_list}")
        return jsonify({"message": f"Successfully logged {len(habits_list)} habits for {today_date_string}!"}), 200

    except Exception as e:
        print(f"Error logging habits: {e}")
        return jsonify({"error": "An internal server error occurred."}), 500

@app.route('/get_logs', methods=['GET'])
def get_logs():
    try:
        conn = get_db_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT log_date, habits_json FROM habit_logs ORDER BY log_date DESC")
        rows = cursor.fetchall()
        conn.close()
        
        logs = {}
        for row in rows:
            habits = json.loads(row['habits_json'])
            if habits:
                 logs[row['log_date']] = habits
            
        return jsonify(logs), 200
    except Exception as e:
        print(f"Error getting logs: {e}")
        return jsonify({"error": "An internal server error occurred."}), 500

@app.route('/get_stats', methods=['GET'])
def get_stats():
    """ This endpoint now calls our shared logic function. """
    try:
        stats = calculate_stats()
        return jsonify(stats), 200
    except Exception as e:
        print(f"Error getting stats: {e}")
        return jsonify({"error": "An internal server error occurred."}), 500

@app.route('/get_motivation', methods=['GET'])
def get_motivation():
    try:
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
    except Exception as e:
        print(f"Error getting motivation: {e}")
        return jsonify({"error": "An internal server error occurred."}), 500

# --- *** NEW: AI Suggestion Endpoint *** ---
@app.route('/get_suggestion', methods=['POST'])
def get_suggestion():
    """
    Provides an AI-driven habit suggestion based on user history.
    """
    try:
        stats = calculate_stats()
        best_habit = stats.get('best_habit', 'None yet').lower() # 'walking'
        
        # Get habits user already has from frontend
        data = request.get_json()
        current_habits = data.get('current_habits', []) # ['water', 'reading', 'walking']

        possible_suggestions = []
        if best_habit in SUGGESTION_MAP:
            # Add suggestions based on their best habit
            possible_suggestions.extend(SUGGESTION_MAP[best_habit])
        
        # Add general suggestions as a fallback
        possible_suggestions.extend(SUGGESTION_MAP['general'])
        
        # Filter out suggestions for habits the user *already* tracks
        filtered_suggestions = []
        for suggestion in possible_suggestions:
            is_already_tracking = False
            for existing_habit in current_habits:
                # Check if the *key word* of the existing habit is in the suggestion
                if existing_habit in suggestion.lower():
                    is_already_tracking = True
                    break
            if not is_already_tracking:
                filtered_suggestions.append(suggestion)

        if not filtered_suggestions:
            # If all suggestions are somehow filtered out, provide a generic one
            suggestion = "Try a new healthy recipe!"
        else:
            # Pick a random one from the filtered list
            suggestion = random.choice(filtered_suggestions)
        
        return jsonify({"suggestion": suggestion}), 200

    except Exception as e:
        print(f"Error getting suggestion: {e}")
        return jsonify({"error": "An internal server error occurred."}), 500
# --- ********************************* ---


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=False)



🚀 MindTrack - Hackathon Backend

This is the Python backend for the MindTrack wellness and habit tracking application, built for the Hackarena hackathon.

It's a Flask server that uses SQLite for persistent data storage.

Features

/log [POST]: Logs daily completed habits to the SQLite database.

/get_logs [GET]: Returns all historical log data to power the calendar view.

/get_stats [GET]: Analyzes and returns user trends (current streak, total days, best habit).

/get_motivation [GET]: Provides a streak-based motivational quote.

/get_suggestion [POST]: A lightweight "AI" that suggests new habits based on user history.

How to Run Locally

Clone the repository.

Create a virtual environment:

python -m venv venv
source venv/bin/activate  # (or .\venv\Scripts\activate on Windows)


Install dependencies:

pip install -r requirements.txt


Run the server:

python backend.py


The server will initialize the mindtrack.db file and start running on http://127.0.0.1:5000.

How to Deploy (for Hackathon)

This app is ready to be deployed on a free service like Render.

Push this code (backend.py, requirements.txt, README.md) to your public GitHub repo.

Go to Render.com and create a new "Web Service".

Connect it to your GitHub repo.

Set the Build Command to: pip install -r requirements.txt

Set the Start Command to: python backend.py

Crucial Step: You will also need to update the BACKEND_URL in your index.html file from http://127.0.0.1:5000 to your new public Render URL (e.g., https://mindtrack-backend.onrender.com).

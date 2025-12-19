# app.py – thin bootstrap, all logic lives in webapp package

from dotenv import load_dotenv

# Load .env BEFORE importing/creating the Flask app (important!)
load_dotenv()

from webapp import create_app  # noqa: E402

# This is the app object Flask sees when you run `python app.py`
app = create_app()

if __name__ == "__main__":
    # For local dev you can tweak debug/port here
    app.run(debug=True, port=5001)
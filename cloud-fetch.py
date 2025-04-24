from flask import Flask, request, jsonify
import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials

fetch = Flask(__name__)

@fetch.route("/", methods=["POST"])
def append_row():
    try:
        # Logging the incoming request
        print("Request received:", request.json)

        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]
        creds_json = os.environ["GCLOUD_CREDENTIALS_JSON"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(creds_json), scope)
        client = gspread.authorize(creds)

        sheet_id = os.environ["SHEET_ID"]
        worksheet = client.open_by_key(sheet_id).sheet1

        # Accept optional row data from JSON body, or default
        row = request.json.get("row", ["Docker", "Cloud Run", "Did", "This"])
        
        # Logging the row data
        print(f"Appending row: {row}")

        worksheet.append_row(row, value_input_option="USER_ENTERED")

        return jsonify({"message": "Row appended", "row": row}), 200

    except Exception as e:
        print(f"Error: {str(e)}")  # Log the error message
        return jsonify({"error": str(e)}), 500

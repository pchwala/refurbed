### Project Structure (you'll deploy two Cloud Run services)

# fetch_orders/main.py
from flask import Flask, request
import requests
import gspread
from google.oauth2.service_account import Credentials

app = Flask(__name__)

# Setup Google Sheets
creds = Credentials.from_service_account_file("/app/creds.json")
client = gspread.authorize(creds)
sheet = client.open("Refurbed Orders").sheet1

@app.route("/", methods=["POST"])
def fetch_orders():
    # Simulated: Fetch orders from Refurbed API
    # Replace with actual Refurbed API calls and auth
    new_orders = [
        {"id": "12345", "customer": "John Doe", "product": "Phone X"},
        {"id": "12346", "customer": "Jane Smith", "product": "Tablet Y"},
    ]

    for order in new_orders:
        sheet.append_row([
            order["id"], order["customer"], order["product"], "FALSE", "FALSE"])

    return "Orders fetched and written to sheet", 200


# process_orders/main.py
from flask import Flask, request
import requests
import gspread
from google.oauth2.service_account import Credentials

app = Flask(__name__)

# Setup Google Sheets
creds = Credentials.from_service_account_file("/app/creds.json")
client = gspread.authorize(creds)
sheet = client.open("Refurbed Orders").sheet1

@app.route("/", methods=["POST"])
def process_orders():
    data = sheet.get_all_records()
    for i, row in enumerate(data, start=2):  # start=2 to skip header
        if row["Approved"] == "TRUE" and row["SentToIdoSell"] != "TRUE":
            # TODO: Send order to IdoSell via API
            print(f"Sending order {row['OrderID']} to IdoSell")

            # Mark as sent
            sheet.update_cell(i, 5, "TRUE")  # 5 = column E (SentToIdoSell)

    return "Processed sheet", 200


# Dockerfile (same for both services)
FROM python:3.10-slim
WORKDIR /app
COPY . .
RUN pip install flask gspread google-auth
CMD ["python", "main.py"]


# Requirements for deployment:
# - `creds.json` (Service account key with Sheets API access)
# - Google Sheet shared with the service account email
# - Cloud Run deployed with: 
#   gcloud run deploy fetch-orders --source ./fetch_orders --allow-unauthenticated
#   gcloud run deploy process-orders --source ./process_orders --allow-unauthenticated

# Scheduler:
# gcloud scheduler jobs create http fetch-orders-job \
# --schedule "*/5 * * * *" \
# --uri https://fetch-orders-xyz.run.app \
# --http-method POST \
# --oidc-service-account-email your-service-account@project.iam.gserviceaccount.com

# gcloud scheduler jobs create http process-orders-job \
# --schedule "*/10 * * * *" \
# --uri https://process-orders-xyz.run.app \
# --http-method POST \
# --oidc-service-account-email your-service-account@project.iam.gserviceaccount.com

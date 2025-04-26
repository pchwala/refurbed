import os
from flask import Flask, request, jsonify
import requests
import json
from datetime import datetime, timedelta
import gspread
from gspread_formatting import set_data_validation_for_cell_range, DataValidationRule, BooleanCondition
from oauth2client.service_account import ServiceAccountCredentials

fetch = Flask(__name__)

@fetch.route("/", methods=["POST"])
def fetch_orders():
    # === Google Sheets Setup ===
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]

    creds_json = os.environ["GCLOUD_CREDENTIALS_JSON"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(creds_json), scope)
    client = gspread.authorize(creds)

    sheet_id = os.environ["SHEET_ID"]

    # Open Orders and Config worksheets
    orders_sheet = client.open_by_key(sheet_id).worksheet("Orders")
    config_sheet = client.open_by_key(sheet_id).worksheet("Config")

    # === Refurbed API Setup ===
    r_URL = "https://api.refurbed.com/refb.merchant.v1.OrderService/ListOrders"

    ref_token = os.environ["REFURBED_TOKEN"]

    headers = {
        "Authorization": f"Plain {ref_token}",
        "Content-Type": "application/json"
    }
    

    # Read last fetched order id from Config Sheet
    config = config_sheet.get_all_values()
    r_last_id = config[1][0]

    # Fetch new orders from the last fetched order id
    payload = {
        "filter": {
            "state": {
                "none_of": "RETURNED",
                "none_of": "CANCELLED",
            }
        },
        "pagination": {
            "limit": 100,
            "starting_after": r_last_id
        },
        "sort": {
            "field": "id",
            "order": "ASC"
        }
    }


    # Get, decode and save response
    response = requests.post(r_URL, headers=headers, json=payload)

    if response.status_code != 200:
        return jsonify({"error": "Failed to fetch orders", "status_code": response.status_code}), 500

    response_data = response.json()
    orders = response_data.get('orders', [])

    sheet_header = [
        "checkbox",
        "order_id", "r_state",
        "item_sku", "r_country_code", "r_total_charged", "r_currency_code", "vat",
        "notatki", "magazyn", "r_item_name",
        "r_customer_email", "r_first_name", "r_family_name", "r_phone_number",
    ]

    sheet_rows = []


    for order in orders:
        shipping = order.get("shipping_address", {})
        items = order.get("items", [])
        item = items[0] if items else {}

        row = [
            "FALSE",
            "",
            order.get("state", ""),
            item.get("sku", ""),
            shipping.get("country_code", ""),
            order.get("settlement_total_charged", ""),
            order.get("settlement_currency_code", ""),
            "",
            "",
            "",
            item.get("name", ""),
            order.get("customer_email", ""),
            shipping.get("first_name", ""),
            shipping.get("family_name", ""),
            shipping.get("phone_number", ""),
        ]
        r_last_id = order.get("id", "")
        print(f"Fetched order ID: {r_last_id}")

        sheet_rows.append(row)


    # === Write to sheet ===
    orders_sheet.append_rows(sheet_rows, value_input_option="USER_ENTERED")
    config_sheet.update_acell("A2", r_last_id)

    # Get the row number of the newly added row
    last_row = len(orders_sheet.get_all_values())

    # Create checkbox rule (TRUE/FALSE)
    checkbox_rule = DataValidationRule(
        condition=BooleanCondition('BOOLEAN'),
        showCustomUi=True
    )

    # Apply to range
    cell_range = f"A2:A{last_row}"
    set_data_validation_for_cell_range(orders_sheet, cell_range, checkbox_rule)

    return jsonify({"message": f"Wrote {len(sheet_rows)} rows to Google Sheets."}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)

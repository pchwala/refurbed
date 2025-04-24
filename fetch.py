import requests
import json

from datetime import datetime, timedelta

import gspread
from gspread_formatting import set_data_validation_for_cell_range, DataValidationRule, BooleanCondition
from oauth2client.service_account import ServiceAccountCredentials

# === Google Sheets Setup ===
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds = ServiceAccountCredentials.from_json_keyfile_name("gcloud_credentials.json", scope)
client = gspread.authorize(creds)

sheet_id = "15e6oc33_A21dNNv03wqdixYc9_mM2GTQzum9z2HylEg"

# Open Ordet and Config worksheets
orders_sheet = client.open_by_key(sheet_id).worksheet("Orders")
config_sheet = client.open_by_key(sheet_id).worksheet("Config")


# === Refurbed API Setup ===
r_URL = "https://api.refurbed.com/refb.merchant.v1.OrderService/ListOrders"

with open("tokens.json", "r") as f:
    tokens = json.load(f)

TOKEN = tokens.get("refurbed_token")

headers = {
    "Authorization": f"Plain {TOKEN}",
    "Content-Type": "application/json"
}


# Read last fetched order id from Config Sheet
config = config_sheet.get_all_values()
r_last_id = config[1][0]

# Fetch 100 newest orders
payload = {
    "filter": {
        "state": {
            "none_of": "RETURNED",
            "none_of": "CANCELLED",
        }
    },
    "pagination": {
    "limit": 100,
    #"starting_after": r_last_id
    },
    "sort":{
        "field": "id",
        "order": "DESC"
    }

}

# Get, decode and save response
response = requests.post(r_URL, headers=headers, json=payload)

print("Status Code:", response.status_code)
try:
    with open("refurbed_response.json", "w", encoding="utf-8") as f:
        json.dump(response.json(), f, ensure_ascii=False, indent=2)
    print("Response saved to refurbed_response.json")

except Exception as e:
    print("Failed to decode JSON:", e)
    print("Raw response:", response.text)


sheet_header = [
    "checkbox",
    "order_id", "r_state",
    "item_sku", "r_country_code", "r_total_charged", "r_currency_code", "vat",
    "notatki", "magazyn", "r_item_name",
    "r_customer_email", "r_first_name", "r_family_name", "r_phone_number",
]

sheet_rows = []

response = response.json()
orders = response.get('orders') # Get orders data from response

for order in orders:
    shipping = order.get("shipping_address", {})
    # SUPER IMPORTANT TO CHECK THIS, it most likely can be more than one item per order
    items = order.get("items", []) 
    item = items[0] if items else {} # get first element for test purpose

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

    sheet_rows.append(row)

test_row = [
        "FALSE",
        "",
        "NEW",
        "sku",
        "DE",
        "100.00",
        "EUR",
        "",
        "",
        "",
        "name",
        "email",
        "first_name",
        "family_name",
        "phone"

    ]
sheet_rows.append(test_row)


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


print(f"Wrote {len(sheet_rows)} rows to Google Sheets.")

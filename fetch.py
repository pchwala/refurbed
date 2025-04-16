import requests
import json

from datetime import datetime, timedelta

import gspread
from oauth2client.service_account import ServiceAccountCredentials

# === Google Sheets Setup ===
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds = ServiceAccountCredentials.from_json_keyfile_name("gcloud_credentials.json", scope)
client = gspread.authorize(creds)

sheet_id = "15e6oc33_A21dNNv03wqdixYc9_mM2GTQzum9z2HylEg"

sheet = client.open_by_key(sheet_id).worksheet("Orders")

URL = "https://api.refurbed.com/refb.merchant.v1.OrderService/ListOrders"


with open("tokens.json", "r") as f:
    tokens = json.load(f)

TOKEN = tokens.get("refurbed_token")

headers = {
    "Authorization": f"Plain {TOKEN}",
    "Content-Type": "application/json"
}

payload = {
    "filter": {
        "state": {
            "none_of": "RETURNED",
            "none_of": "CANCELLED",
        }
    },
    "pagination": {
    "limit": 100,
    },
    "sort":{
        "field": "id",
        "order": "DESC"
    }

}

response = requests.post(URL, headers=headers, json=payload)

print("Status Code:", response.status_code)
try:
    #print("Response JSON:", response.json())
    with open("refurbed_response.json", "w", encoding="utf-8") as f:
        json.dump(response.json(), f, ensure_ascii=False, indent=2)

    print("Response saved to refurbed_response.json")

except Exception as e:
    print("Failed to decode JSON:", e)
    print("Raw response:", response.text)


sheet_header = [
    "",
    "order_id",
    "ref_state", "ref_customer_email",
    "ref_first_name", "ref_family_name", "ref_country_code", "ref_phone_number",
    "ref_currency_code", "ref_total_charged", "ref_item_name", "item_sku",
]

sheet_rows = []

response = response.json()
orders = response.get('orders')

for order in orders:
    shipping = order.get("shipping_address", {})
    # SUPER IMPORTANT TO CHECK THIS, it most likely can be more than one item per order
    items = order.get("items", []) 
    item = items[0] if items else {} # get first element for test purpose

    row = [
        #order.get("id", ""),
        "",
        order.get("state", ""),
        order.get("customer_email", ""),
        shipping.get("first_name", ""),
        shipping.get("family_name", ""),
        shipping.get("country_code", ""),
        shipping.get("phone_number", ""),
        order.get("currency_code", ""),
        order.get("total_charged", ""),
        item.get("name", ""),
        item.get("sku", ""),
    ]

    sheet_rows.append(row)
    

# === Write to sheet ===
sheet.clear()
sheet.append_row(sheet_header)
sheet.append_rows(sheet_rows)

print(f"Wrote {len(sheet_rows)} rows to Google Sheets.")

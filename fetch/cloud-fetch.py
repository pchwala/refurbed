import os
from flask import Flask, request, jsonify
import requests
import json
import gspread
from gspread_formatting import set_data_validation_for_cell_range, DataValidationRule, BooleanCondition
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)

class CloudRefurbedAPI:
    def __init__(self):
        """Initialize the RefurbedAPI with credentials from environment variables."""
        # === Google Sheets Setup ===
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]

        creds_json = os.environ["GCLOUD_CREDENTIALS_JSON"]
        self.creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(creds_json), scope)
        self.client = gspread.authorize(self.creds)

        self.sheet_id = os.environ["SHEET_ID"]
        
        # Load token from environment variables
        self.ref_token = os.environ["REFURBED_TOKEN"]
            
        self.headers = {
            "Authorization": f"Plain {self.ref_token}",
            "Content-Type": "application/json"
        }
        
        # Open Orders and Config worksheets
        self.orders_sheet = self.client.open_by_key(self.sheet_id).worksheet("Orders")
        self.config_sheet = self.client.open_by_key(self.sheet_id).worksheet("Config")

    def get_last_order_id(self):
        """Read last fetched order id from Config Sheet."""
        config = self.config_sheet.get_all_values()
        return config[1][0]
        
    def payload_last(self, last_id):
        """Create payload to fetch new orders from the last fetched order id."""
        return {
            "filter": {
                "state": {
                    "none_of": ["RETURNED", "CANCELLED"]
                }
            },
            "pagination": {
                "limit": 100,
                "starting_after": last_id
            },
            "sort": {
                "field": "id",
                "order": "ASC"
            }
        }
    
    def payload_all(self, limit=100):
        """Create payload to fetch last 100 orders."""
        return {
            "filter": {
                "state": {
                    "none_of": ["RETURNED", "CANCELLED"]
                }
            },
            "pagination": {
                "limit": limit,
            },
            "sort": {
                "field": "id",
                "order": "DESC"
            }
        }
        
    def process_orders(self, orders):
        """Process order data into rows for Google Sheets."""
        sheet_header = [
            "checkbox",
            "r_state", "r_country_code", "r_currency_code", "r_total_charged", "vat",
            "id_zestawu", "klasa", "magazyn", "notatki", "item_sku", "r_item_name",
            "r_customer_email", "r_first_name", "r_family_name", "r_phone_number", "ID"
        ]

        sheet_rows = []
        last_id = ""

        for order in orders:
            shipping = order.get("shipping_address", {})
            items = order.get("items", [])
            item = items[0] if items else {}

            row = [
                "FALSE",
                order.get("state", ""),
                shipping.get("country_code", ""),
                order.get("settlement_currency_code", ""),
                order.get("settlement_total_charged", ""),
                "",  # vat
                "",  # id_zestawu
                "",  # klasa
                "",  # magazyn
                "",  # notatki
                item.get("sku", ""),
                item.get("name", ""),
                order.get("customer_email", ""),
                shipping.get("first_name", ""),
                shipping.get("family_name", ""),
                shipping.get("phone_number", ""),
                order.get("id", "")
            ]
            last_id = order.get("id", "")
            print(f"Fetched order ID: {last_id}")

            sheet_rows.append(row)
            
        return sheet_rows, last_id
    
    def update_sheets(self, sheet_rows, last_id):
        """Write processed rows to Google Sheets and update config."""
        # === Write to sheet ===
        self.orders_sheet.append_rows(sheet_rows, value_input_option="USER_ENTERED")
        if last_id != '':
            self.config_sheet.update_acell("A2", last_id)

        # Get the row number of the newly added row
        last_row = len(self.orders_sheet.get_all_values())

        # Create checkbox rule (TRUE/FALSE)
        checkbox_rule = DataValidationRule(
            condition=BooleanCondition('BOOLEAN'),
            showCustomUi=True
        )

        # Apply to range
        if sheet_rows:
            cell_range = f"A2:A{last_row}"
            set_data_validation_for_cell_range(self.orders_sheet, cell_range, checkbox_rule)

        print(f"Successfully wrote {len(sheet_rows)} rows to Google Sheets.")

    def update_order_states(self, orders):
        """Update order states in the Google Sheet."""
        # Get all order IDs and values from the sheet
        all_rows = self.orders_sheet.get_all_values()
        
        # Find the column index for 'r_state' and 'ID'
        header = all_rows[0]
        r_state_col = header.index("r_state") + 1  # 1-indexed for Sheets API
        id_col = header.index("ID") + 1
        
        print(f"Found r_state column at index {r_state_col}, ID column at index {id_col}")
        
        # Create a dictionary of row_number -> order_id for quick lookup
        order_rows = {}
        for i, row in enumerate(all_rows[1:], start=2):  # Start from 2 because row 1 is header
            if len(row) >= id_col:
                order_id = row[id_col - 1]  # Convert back to 0-indexed for list access
                if order_id:
                    order_rows[order_id] = i
        
        # Keep track of updates to apply in batch
        updates = []
        
        # For each order in the API response
        for order in orders:
            order_id = order.get("id", "")
            state = order.get("state", "")
            
            if order_id in order_rows:
                row_num = order_rows[order_id]
                updates.append({
                    'range': f"{chr(64 + r_state_col)}{row_num}",  # Convert column index to letter (A, B, C...)
                    'values': [[state]]
                })
                print(f"Will update order {order_id} with state {state} at row {row_num}")
        
        if updates:
            # Apply all updates in batch
            self.orders_sheet.batch_update(updates)
            print(f"Updated {len(updates)} order states in the Google Sheet")
        else:
            print("No orders found to update")

    def fetch_orders(self):
        """Fetch new orders from Refurbed API and add them to Google Sheets."""
        try:
            # === Refurbed API Setup ===
            r_URL = "https://api.refurbed.com/refb.merchant.v1.OrderService/ListOrders"
            
            # Get last order ID
            r_last_id = self.get_last_order_id()
            
            # Create payload
            payload = self.payload_last(r_last_id)

            # Get, decode and save response
            response = requests.post(r_URL, headers=self.headers, json=payload)

            if response.status_code != 200:
                print(f"Error: Failed to fetch orders. Status code: {response.status_code}")
                return False

            response_data = response.json()
            orders = response_data.get('orders', [])

            if not orders:
                print("No new orders to process")
                return True
                
            # Process orders
            sheet_rows, last_id = self.process_orders(orders)
            
            # Update sheets
            self.update_sheets(sheet_rows, last_id)
            return True
        except Exception as e:
            print(f"Error in fetch_orders: {str(e)}")
            return False

    def update_states(self):
        """Update order states in Google Sheets from Refurbed API."""
        try:
            # === Refurbed API Setup ===
            r_URL = "https://api.refurbed.com/refb.merchant.v1.OrderService/ListOrders"

            # Create payload
            payload = self.payload_all()

            # Get, decode and save response
            response = requests.post(r_URL, headers=self.headers, json=payload)
            if response.status_code != 200:
                print(f"Error: Failed to fetch orders. Status code: {response.status_code}")
                return False
            
            response_data = response.json()
            orders = response_data.get('orders', [])
            
            if not orders:
                print("No orders found to update states")
                return True
                
            # Update order states in the Google Sheet
            self.update_order_states(orders)
            return True
        except Exception as e:
            print(f"Error in update_states: {str(e)}")
            return False

def fetch_orders_task():
    """Task to fetch orders that runs on a schedule"""
    try:
        api = CloudRefurbedAPI()
        api.fetch_orders()
        # Can also update states if needed
        # api.update_states()
    except Exception as e:
        print(f"Error in scheduled task: {str(e)}")

@app.route("/", methods=["POST"])
def fetch_orders_endpoint():
    try:
        # Manually trigger the fetch_orders_task
        fetch_orders_task()
        return jsonify({"message": "Orders fetch completed successfully."}), 200
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

@app.route("/update-states", methods=["POST"])
def update_states_endpoint():
    try:
        api = CloudRefurbedAPI()
        if api.update_states():
            return jsonify({"message": "Order states updated successfully."}), 200
        else:
            return jsonify({"error": "Failed to update order states."}), 500
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

if __name__ == "__main__":
    # Run the first fetch immediately
    fetch_orders_task()
    
    # Start the Flask application
    app.run(host="0.0.0.0", port=8080)

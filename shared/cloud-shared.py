import os
import requests
import json
import gspread
from gspread_formatting import set_data_validation_for_cell_range, DataValidationRule, BooleanCondition
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, jsonify, request

app = Flask(__name__)

class CloudRefurbedAPI:
    def __init__(self):
        """Initialize the Cloud-optimized RefurbedAPI using environment variables
        """
        # === Google Sheets Setup ===
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]

        # Load credentials from environment variables
        creds_json = os.environ["GCLOUD_CREDENTIALS_JSON"]
        self.creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(creds_json), scope)
        self.client = gspread.authorize(self.creds)
        
        # Sheet ID from environment variables
        self.sheet_id = os.environ["SHEET_ID"]
        
        # Load token from environment variables
        self.ref_token = os.environ["REFURBED_TOKEN"]
            
        # Setup Refurbed API headers
        self.headers = {
            "Authorization": f"Plain {self.ref_token}",
            "Content-Type": "application/json"
        }
        
        # Open Orders and Config worksheets
        self.orders_sheet = self.client.open_by_key(self.sheet_id).worksheet("Orders")
        self.config_sheet = self.client.open_by_key(self.sheet_id).worksheet("Config")

    def get_last_order_id(self):
        # Read last fetched order id from Config Sheet
        config = self.config_sheet.get_all_values()
        return config[1][0]
        
    def payload_last(self, last_id):
        # Fetch new orders from the last fetched order id
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
        # Fetch last n orders
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
    
    def payload_selected(self, order_ids):
        # Fetch selected orders
        return {
            "filter": {
                "state": {
                    "none_of": ["RETURNED", "CANCELLED"]
                },
                "id": {
                    "any_of": order_ids
                }
            },
            "pagination": {
                "limit": 100,
            },
            "sort": {
                "field": "id",
                "order": "DESC"
            }
        }

    def fetch_orders(self):
        """Fetch orders starting from the last processed order ID
        
        Returns:
            dict: Orders data or error message
        """
        r_URL = "https://api.refurbed.com/refb.merchant.v1.OrderService/ListOrders"
        
        # Get last order ID
        r_last_id = self.get_last_order_id()
        
        # Create payload
        payload = self.payload_last(r_last_id)

        # Get and return response
        response = requests.post(r_URL, headers=self.headers, json=payload)

        if response.status_code != 200:
            return {
                "error": f"Failed to fetch orders. Status code: {response.status_code}",
                "details": response.text
            }, response.status_code

        # Return only the orders data
        return {"orders": response.json().get('orders', [])}

    def fetch_selected_orders(self, order_ids):
        """Fetches specific orders by their IDs.
        
        Args:
            order_ids (list): List of order IDs to fetch
        
        Returns:
            dict: Selected orders data or error message
        """
        r_URL = "https://api.refurbed.com/refb.merchant.v1.OrderService/ListOrders"
        
        # Create payload for specific orders
        payload = self.payload_selected(order_ids)
    
        # Get and return response
        response = requests.post(r_URL, headers=self.headers, json=payload)
    
        if response.status_code != 200:
            return {
                "error": f"Failed to fetch orders. Status code: {response.status_code}",
                "details": response.text
            }, response.status_code
    
        # Return only the orders data
        return {"orders": response.json().get('orders', [])}

    def fetch_latest_orders(self, n=100):
        """Fetches the latest n orders regardless of the last fetched order ID.
        
        Args:
            n (int): Number of orders to fetch
            
        Returns:
            dict: Latest orders data or error message
        """
        r_URL = "https://api.refurbed.com/refb.merchant.v1.OrderService/ListOrders"
        
        # Create payload for latest n orders
        payload = self.payload_all(limit=n)
    
        # Get and return response
        response = requests.post(r_URL, headers=self.headers, json=payload)
    
        if response.status_code != 200:
            return {
                "error": f"Failed to fetch orders. Status code: {response.status_code}",
                "details": response.text
            }, response.status_code
    
        # Return only the orders data
        return {"orders": response.json().get('orders', [])}

    def update_order_states(self, orders):
        """Update order states in Google Sheet
        
        Args:
            orders (list): List of order objects with id and state
            
        Returns:
            dict: Result of the update operation with row numbers, order IDs, and states
        """
        # Get all order IDs and values from the sheet
        all_rows = self.orders_sheet.get_all_values()
        
        # Find the column index for 'r_state' and 'ID'
        header = all_rows[0]
        r_state_col = header.index("r_state") + 1  # 1-indexed for Sheets API
        id_col = header.index("ID") + 1
        
        # Create a dictionary of row_number -> order_id for quick lookup
        order_rows = {}
        for i, row in enumerate(all_rows[1:], start=2):  # Start from 2 because row 1 is header
            if len(row) >= id_col:
                order_id = row[id_col - 1]  # Convert back to 0-indexed for list access
                if order_id:
                    order_rows[order_id] = i
        
        # Keep track of updates to apply in batch
        updates = []
        # Track details for each updated order
        updated_orders = []
        
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
                
                # Add order details to the tracking list
                updated_orders.append({
                    "row": row_num,
                    "id": order_id,
                    "state": state
                })
        
        if updates:
            # Apply all updates in batch
            self.orders_sheet.batch_update(updates)
        
        return {
            "updated": len(updates),
            "total": len(orders),
            "orders": updated_orders
        }

    def update_states(self):
        """Update order states based on the latest orders from Refurbed API
        
        Returns:
            dict: Updated orders with row numbers, IDs, and states
        """
        r_URL = "https://api.refurbed.com/refb.merchant.v1.OrderService/ListOrders"

        # Create payload
        payload = self.payload_all()

        # Get response
        response = requests.post(r_URL, headers=self.headers, json=payload)
        if response.status_code != 200:
            return jsonify({
                "error": f"Failed to fetch orders. Status code: {response.status_code}",
                "details": response.text
            }), response.status_code
        
        response_data = response.json()
        orders = response_data.get('orders', [])
        
        # Update order states in the Google Sheet and return only the update results
        update_result = self.update_order_states(orders)
        
        return update_result

# Initialize API using environment variables
def get_api_instance():
    try:
        api = CloudRefurbedAPI()
        return api, None
    except Exception as e:
        return None, (jsonify({"error": f"Failed to initialize API: {str(e)}"}), 500)

@app.route('/fetch_orders', methods=['POST'])
def fetch_orders():
    """Fetch orders starting from the last processed order ID"""
    api, error = get_api_instance()
    if error:
        return error
    return jsonify(api.fetch_orders())

@app.route('/fetch_latest', methods=['POST'])
def fetch_latest():
    """Fetch the latest n orders"""
    api, error = get_api_instance()
    if error:
        return error
    
    request_json = request.get_json(silent=True)
    n = request_json.get('limit', 100) if request_json else 100
    return jsonify(api.fetch_latest_orders(n=n))

@app.route('/update_states', methods=['POST'])
def update_states():
    """Update order states based on latest orders"""
    api, error = get_api_instance()
    if error:
        return error
    return jsonify(api.update_states())

@app.route('/fetch_selected', methods=['POST'])
def fetch_selected():
    """Fetch specific orders by ID"""
    api, error = get_api_instance()
    if error:
        return error
    
    request_json = request.get_json(silent=True)
    order_ids = request_json.get('order_ids', []) if request_json else []
    if not order_ids:
        return jsonify({"error": "No order IDs provided"}), 400
    return jsonify(api.fetch_selected_orders(order_ids))

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

import os
from flask import Flask, request, jsonify, render_template, redirect, url_for
import requests
import json
import gspread
from gspread_formatting import set_data_validation_for_cell_range, DataValidationRule, BooleanCondition
from oauth2client.service_account import ServiceAccountCredentials
from google.oauth2 import service_account
from google.auth.transport.requests import Request
import io
import sys
from contextlib import redirect_stdout
from refurbed import RefurbedAPI
from idosell import IdoSellAPI

app = Flask(__name__)

class Integration:
    def __init__(self):
        """Initialize the IdoSell API client with credentials from files."""
        # === Google Sheets Setup ===
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]

        # Load credentials from file instead of environment variable
        self.creds = ServiceAccountCredentials.from_json_keyfile_name('/home/vis/Projects/refurbed/keys/ref-ids-6c3ebadcd9f8.json', scope)
        self.client = gspread.authorize(self.creds)

        # Set sheet_id directly
        self.sheet_id = "15e6oc33_A21dNNv03wqdixYc9_mM2GTQzum9z2HylEg"
        
        # Load API keys from tokens.json file
        with open("/home/vis/Projects/refurbed/keys/tokens.json", "r") as f:
            tokens = json.load(f)
            self.ids_key = tokens["idosell_api_key"]
            self.ref_key = tokens["refurbed_token"]
        
        # Open Orders and Config worksheets
        self.orders_sheet = self.client.open_by_key(self.sheet_id).worksheet("Orders")
        self.config_sheet = self.client.open_by_key(self.sheet_id).worksheet("Config")

        # Initialize API classes
        self.idosell_api = IdoSellAPI(api_key=self.ids_key)
        self.refurbed_api = RefurbedAPI(
            ref_key=self.ref_key,
            creds=self.creds,
            client=self.client,
            sheet_id=self.sheet_id,
            orders_sheet=self.orders_sheet,
            config_sheet=self.config_sheet
        )

    def get_pending_rows(self, data=None):
        """
        Check each row in the orders sheet and return row numbers where:
        1. Checkbox column is not empty
        2. Checkbox value is TRUE
        3. r_state value is NEW
        
        Returns:
            list: A list of row numbers (1-based) that match the criteria
        """
        
        pending_rows = []

        # Process each row starting from row 2 (index 1 in zero-based list)
        for row_index, row in enumerate(data[1:], start=2):
            # Check if row has data
            if not row:
                break
                
            # Check if checkbox is TRUE and r_state is NEW
            checkbox_value = row[0].upper()  # Convert to uppercase for case-insensitive comparison
            r_state_value = row[1]
            
            if checkbox_value == "TRUE" and r_state_value == "NEW":
                pending_rows.append(row_index)
                
        return pending_rows
    
    def ids_push_all(self):
        """
        Push all orders from the Orders sheet to IdoSell.
        """
        data = self.orders_sheet.get_all_values()

        pending_rows = self.get_pending_rows(data=data)

        # Set r_state to ACCEPTED
        if pending_rows:
            # Prepare orders worksheet batch update
            batch_update = []
            for row in pending_rows:
                # Set r_state column (index 1, column B) to ACCEPTED
                batch_update.append({
                    'range': f'B{row}',
                    'values': [['ACCEPTED']]
                })
            
            # Execute batch update if there are pending rows
            if batch_update:
                self.orders_sheet.batch_update(batch_update)
                print(f"Updated {len(pending_rows)} rows to ACCEPTED status")


            ref_ids = []    # List of pending refurbed order IDs

            # List of rows in dict format where
            # 1st element is refurbed order ID
            # 2nd elemtent is data row from Orders sheet corresponding to that order ID
            processed_rows = {}

            for row in pending_rows:
                rowdata = data[row - 1]
                ref_ids.append(rowdata[18]) # Append refurbed order ID
                processed_rows[rowdata[18]] = rowdata # Append one dict element

            # Fetch selected orders from Refurbed directly
            ref_selected_orders = self.fetch_selected_orders(ref_ids)
            print(f"Fetched selected orders from Refurbed: {len(ref_selected_orders.get('orders', []))} orders")

            # Create orders in IdoSell
            created_orders = self.idosell_api.create_orders(pending_rows=processed_rows, ref_data=ref_selected_orders)
            
            # Update Config sheet with the created orders
            for order in created_orders:
                ref_id = order["ref_id"]
                new_order_id = order["idosell_id"]
                
                # Get all values from Config sheet
                config_data = self.config_sheet.get_all_values()

                # Find first empty row in columns D & E
                empty_row = None
                for i, row in enumerate(config_data):
                    # Check if we have enough columns and D or E is empty
                    if len(row) >= 5 and (not row[3] or not row[4]):
                        empty_row = i + 1  # Convert to 1-based index
                        break

                # If no empty row found, append to the end
                if empty_row is None:
                    empty_row = len(config_data) + 1

                # Update the Config sheet with new values
                self.config_sheet.update_cell(empty_row, 4, ref_id)  # Column D
                self.config_sheet.update_cell(empty_row, 5, new_order_id)  # Column E

                print(f"Updated Config sheet: added ref_id {ref_id} and order_id {new_order_id} in row {empty_row}")
            
            return True
        else:
            print("No pending rows found to update")
            return False

    def fetch_selected_orders(self, order_ids):
        """
        Fetch specific orders from Refurbed API using order IDs.
        
        Args:
            order_ids (list): List of order IDs to fetch
            
        Returns:
            dict: Dictionary containing the fetched orders
        """
        # Use the RefurbedAPI directly
        orders = self.refurbed_api.fetch_selected_orders(order_ids)
        
        return {
            "orders": orders,
            "count": len(orders)
        }

    def direct_fetch_orders(self):
        """
        Fetch orders directly using the RefurbedAPI instance
        
        Returns:
            dict: Dictionary containing the result status and message
        """
        try:
            # Use the RefurbedAPI directly
            self.refurbed_api.fetch_orders()
            return {"status": "success", "message": "Orders fetched successfully"}
        except Exception as e:
            return {"status": "error", "message": str(e)}


def push_orders_task():
    """Task to push orders to IdoSell that runs on a schedule"""
    try:
        # Capture all print output to return it as a string
        f = io.StringIO()
        with redirect_stdout(f):
            api = Integration()
            ret = api.ids_push_all()
        
        output = f.getvalue()
        return ret, output
    except Exception as e:
        error_msg = f"Error in scheduled task: {str(e)}"
        print(error_msg)
        return False, error_msg


@app.route("/", methods=["GET"])
def home():
    """Render the GUI interface"""
    return render_template('index.html', output="Gotowy do wysłania zamówień.")


@app.route("/run_task", methods=["POST"])
def run_task():
    """Run the push task and display results in the GUI"""
    success, output = push_orders_task()
    if success:
        output += "\n\nZamówienia zostały wysłane pomyślnie."
    else:
        if not output:
            output = "Brak zamówień do wysłania lub operacja nie powiodła się."
    
    return render_template('index.html', output=output)


@app.route("/fetch_orders", methods=["POST"])
def fetch_orders():
    """Fetch orders directly from Refurbed API"""
    try:
        api = Integration()
        # Use direct_fetch_orders method instead of making HTTP request to cloud function
        result = api.direct_fetch_orders()
        
        if result["status"] == "error":
            return render_template('index.html', output=f"Błąd: {result['message']}")
        
        output = "Zamówienia zostały pobrane pomyślnie."
        return render_template('index.html', output=output)
    except Exception as e:
        error_msg = f"Błąd podczas pobierania zamówień: {str(e)}"
        return render_template('index.html', output=error_msg)


@app.route("/update_states", methods=["POST"])
def update_states():
    """Update order states from Refurbed API directly"""
    try:
        # Create an integration instance
        api = Integration()
        
        # Use the RefurbedAPI directly
        updated = api.refurbed_api.update_states()
        return render_template('index.html', output=f"Zaktualizowano {updated} zamówień.")
        
    except Exception as e:
        error_msg = f"Błąd podczas aktualizacji stanów: {str(e)}"
        return render_template('index.html', output=error_msg)


@app.route("/api/push", methods=["POST"])
def push_orders_endpoint():
    """API endpoint for programmatic access"""
    try:
        success, output = push_orders_task()
        if success:
            return jsonify({"message": "Orders push completed successfully.", "details": output}), 200
        else:
            return jsonify({"message": "No orders to push or push failed.", "details": output}), 200
    except Exception as e:
        error_msg = f"Error: {str(e)}"
        print(error_msg)
        return jsonify({"error": error_msg}), 500


if __name__ == "__main__":
    # Start the Flask application
    app.run(host="0.0.0.0", port=8080, debug=True)
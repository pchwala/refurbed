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
import time

# ZAMOWIENIA TESTOWE
# zamowienie 2szt na firme - ids: 338976      ref: 13410452

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
    
    def get_config_rows(self, needed=0, data=None):
        """
        Return the list of row indexes that you can write config data to.
        If there is less empty rows than needed, then return None.
        """
        # Process each row starting from row 2 (index 1 in zero-based list)
        empty_rows = []
        for row_index, row in enumerate(data[1:], start=2):
            # Check if row has data
            if row[3] == '' and row[4] == '':
                empty_rows.append(row_index)
                needed -= 1
                if needed == 0:
                    return empty_rows
        
        # Return the collected empty rows even if we didn't find enough
        return empty_rows if empty_rows else None
                
    def update_config(self, created_orders):
        """
        Update the Config sheet with the created orders ids
        """

        # If there are no created orders, return
        if not created_orders:
            print("No created orders to update in Config sheet")
            return False

        config = self.config_sheet.get_all_values()
        # Find empty rows in the Config sheet
        empty_rows = self.get_config_rows(needed=len(created_orders), data=config)
        
        # If there are empty rows available, use them
        if empty_rows and len(empty_rows) >= len(created_orders):
            batch_update = []
            for i, row in enumerate(empty_rows[:len(created_orders)], start=0):
                # Set ref_id and idosell_id columns (D and E)
                batch_update.append({
                    'range': f'D{row}:E{row}',
                    'values': [[created_orders[i]["ref_id"], created_orders[i]["idosell_id"]]]
                })
            # Execute batch update 
            if batch_update:
                self.config_sheet.batch_update(batch_update)
                print(f"Updated {len(batch_update)} rows in Config sheet with created orders")
        else:
            # Not enough empty rows, append new rows
            # Get total number of rows to calculate where to insert
            num_rows = len(config)
            
            batch_update = []
            for i, c_order in enumerate(created_orders):
                row_num = num_rows + i + 1  # +1 because sheet is 1-indexed
                batch_update.append({
                    'range': f'D{row_num}:E{row_num}',
                    'values': [[c_order["ref_id"], c_order["idosell_id"]]]
                })
            
            # First append empty rows
            empty_data = [["", "", "", "", ""] for _ in range(len(created_orders))]
            self.config_sheet.append_rows(empty_data)
            
            # Then update the specific cells in columns D and E
            if batch_update:
                self.config_sheet.batch_update(batch_update)
                print(f"Added {len(batch_update)} new rows to Config sheet with created orders")

        return True
    
    def update_orders_worksheet(self, created_orders):
        """
        Update the Orders worksheet with IdoSell order IDs.
        For each row in Orders worksheet, check if column S ('ID') matches 'ref_id' 
        from created_orders, and if so, put the corresponding 'idosell_id' into column L.
        
        Args:
            created_orders (list): List of dictionaries with 'ref_id' and 'idosell_id' keys
        
        Returns:
            dict: Dictionary containing the result status and statistics
        """
        # If there are no created orders, return
        if not created_orders:
            print("No created orders to update in Orders sheet")
            return False

        try:
            # Get all values from the Orders sheet
            orders_data = self.orders_sheet.get_all_values()
            
            # Create a lookup dictionary for faster matching
            ref_id_to_idosell = {order["ref_id"]: order["idosell_id"] for order in created_orders}
            
            # Track statistics
            matched_count = 0
            batch_update = []
            
            # Process each row starting from row 2 (index 1 in zero-based list) to skip header
            for row_index, row in enumerate(orders_data[1:], start=2):
                # Check if row has enough columns
                if len(row) < 19:  # S column is at index 18
                    continue
                
                # Get refurbed ID from column S (index 18)
                ref_id = row[18]
                
                # Check if this ref_id exists in our created_orders lookup
                if ref_id in ref_id_to_idosell:
                    idosell_id = ref_id_to_idosell[ref_id]
                    
                    # Add update to batch for column L (index 11)
                    # Update column L with idosell_id
                    batch_update.append({
                        'range': f'L{row_index}',
                        'values': [[idosell_id]]
                    })
                    
                    # Update column B (r_state) to ACCEPTED
                    batch_update.append({
                        'range': f'B{row_index}',
                        'values': [['ACCEPTED']]
                    })
                    matched_count += 1
            
            # Execute batch update if there are matches
            if batch_update:
                self.orders_sheet.batch_update(batch_update)
                print(f"Updated {matched_count} rows in Orders sheet with IdoSell IDs")
                
            return {
                "status": "success",
                "updated_count": matched_count,
                "total_orders": len(created_orders)
            }
            
        except Exception as e:
            print(f"Error updating Orders worksheet: {str(e)}")
            return {
                "status": "error",
                "message": str(e)
            }
        
    def set_states_to_accepted(self, created_orders):
        """
        Update the state of all items in the provided orders to 'ACCEPTED'.
        
        Args:
            created_orders (list): A list of order dictionaries, each containing 
                                  a 'ref_id' key that references the order in the Refurbed system.
        
        Note:
            This method introduces a 0.2 second delay between API calls to avoid rate limiting,
            as batch updates don't seem to work properly.
        """
        ref_orders = []
        for order in created_orders:
            ref_orders.append(order["ref_id"])

        items_list = self.refurbed_api.list_orders_items(ref_orders)

        for item in items_list:
            self.refurbed_api.change_state(order_item_id=item, state="ACCEPTED")
            # Add 1/5 second delay between API calls to avoid rate limiting
            # Idk why BatchUpdate doesn't work but it doesn't
            time.sleep(0.2)
    
    def ids_push_all(self):
        """
        Push all orders from the Orders sheet to IdoSell.
        """
        data = self.orders_sheet.get_all_values()

        pending_rows = self.get_pending_rows(data=data)

        # Set r_state to ACCEPTED
        if pending_rows:
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
            self.update_config(created_orders=created_orders)

            # Set states to ACCEPTED in Refurbed
            self.set_states_to_accepted(created_orders=created_orders)

            # Update Orders worksheet with IdoSell order IDs
            self.update_orders_worksheet(created_orders=created_orders)

            # Ftech states from refurbed to worksheet to make sure they are up to date
            ##updated = api.refurbed_api.update_states()

            return True
        else:
            print("No pending rows found to update")
            return False
    
    def process_orders(self):
        """
        Process all orders in the Config worksheet by extracting refurbed and idosell
        order IDs from columns D and E respectively, and calling edit_order for each valid pair.
        
        Returns:
            dict: Dictionary containing results with counts of processed, successful, and failed orders
        """
        try:
            # Get all values from the Config sheet
            config_data = self.config_sheet.get_all_values()
            
            processed_count = 0
            success_count = 0
            failed_count = 0
            failed_orders = []
            
            # Start from row 2 (index 1) to skip header row
            for row_index, row in enumerate(config_data[1:], start=2):
                # Check if row has enough columns
                if len(row) < 5:
                    continue
                    
                # Extract refurbed_id and idosell_id from columns D and E (indices 3 and 4)
                refurbed_id = row[3]
                idosell_id = row[4]
                
                # Skip rows where either ID is empty
                if not refurbed_id or not idosell_id:
                    continue
                
                processed_count += 1
                
                # Get tracking number from IdoSell
                tracking_number, is_finished = self.idosell_api.get_order_tracking_id(idosell_id)
                if is_finished is not None:
                    if is_finished is True:
                        # If order is finished and there is proper tracking number, set state to SHIPPED
                        items = self.refurbed_api.list_orders_items([refurbed_id])
                        for item in items:
                            result = self.refurbed_api.change_state(order_item_id=item, state="SHIPPED", tracking_number=tracking_number)
                            if result is False:
                                failed_count += 1
                                continue
                        success_count += 1
                        continue

                failed_count += 1
                failed_orders.append(idosell_id)
                
            # Print summary of processed orders
            print(f"Processed {processed_count} orders: {success_count} succeeded, {failed_count} failed.")
            return {
                "status": "success",
                "processed_count": processed_count,
                "success_count": success_count,
                "failed_count": failed_count,
                "failed_orders": failed_orders
            }
                    
        except Exception as e:
            return {
                'status': 'error',
                'message': str(e)
            }
    
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

"""
if __name__ == "__main__":
    # Start the Flask application
    app.run(host="0.0.0.0", port=8080, debug=True)

"""
api = Integration()
#ret = api.ids_push_all()

#ret = api.idosell_api.add_payment(339335, 206.67)

#ret = api.idosell_api.confirm_payment(339335)

#ret = api.refurbed_api.change_state(order_item_id="17422299", state="SHIPPED", tracking_number="1ZA6E2756894175582")

#ret = api.refurbed_api.list_orders_items(["13582047", "13582109", "13581259", "13410452"])

#ret = api.refurbed_api.update_states()

#ret = api.idosell_api.create_new_order(ref_id="13553126", data_row)

#ret = api.refurbed_api.fetch_missing_orders()

#ret = api.direct_fetch_orders()

ret = api.refurbed_api.get_last_order_id()

print(ret)

#1ZA6E2756894175582
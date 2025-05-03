import requests
import json
import os
import gspread
from gspread_formatting import set_data_validation_for_cell_range, DataValidationRule, BooleanCondition
from oauth2client.service_account import ServiceAccountCredentials

from google.oauth2 import service_account
from google.auth.transport.requests import Request

# test id 339335


class IdoSellAPI:
    def __init__(self, tokens_path='./keys/tokens.json'):
        """Initialize the IdoSell API client with tokens from a JSON file."""
        # === Google Sheets Setup ===
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]

        self.creds = ServiceAccountCredentials.from_json_keyfile_name('./keys/ref-ids-6c3ebadcd9f8.json', scope)
        self.client = gspread.authorize(self.creds)

        self.sheet_id = "15e6oc33_A21dNNv03wqdixYc9_mM2GTQzum9z2HylEg"
        
        # Load tokens from the JSON file
        with open(tokens_path) as token_file:
            tokens = json.load(token_file)
            self.api_key = tokens.get('idosell_api_key')
        
        # Open Orders and Config worksheets
        self.orders_sheet = self.client.open_by_key(self.sheet_id).worksheet("Orders")
        self.config_sheet = self.client.open_by_key(self.sheet_id).worksheet("Config")
        
        # Base URL for API requests
        self.base_url = "https://vedion.pl/api/admin/v5"
        
        # Default headers for requests
        self.ref_headers = {
            "accept": "application/json",
            "X-API-KEY": self.api_key
        }

        self.SHARED_RUN_URL = "https://shared-860977612313.europe-central2.run.app"

        self.run_creds = service_account.IDTokenCredentials.from_service_account_file(
            './keys/ref-ids-6c3ebadcd9f8.json',
            target_audience=self.SHARED_RUN_URL
        )

        self.run_creds.refresh(Request())

        self.run_headers = {
            'Authorization': f'Bearer {self.run_creds.token}',
            'Content-Type': 'application/json'
        }
    
    
    def get_order_history(self, order_id=None):
        """Get order history, optionally filtered by order id."""
        endpoint = f"{self.base_url}/orders/history"
        params = {}
        if order_id:
            params["orderSerialNumber"] = order_id
        
        response = requests.get(endpoint, headers=self.ref_headers, params=params)
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Error: {response.status_code}, {response.text}")
        
    
    def get_order(self, order_id=None):
        """
        Get details of a specific order using its id.
        """
        endpoint = f"{self.base_url}/orders/orders"
        params = {}
        if order_id:
            params["ordersSerialNumbers"] = order_id
        
        response = requests.get(endpoint, headers=self.ref_headers, params=params)
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Error: {response.status_code}, {response.text}")
    

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

            # Fetch selected orders from Refurbed
            payload = {"order_ids": ref_ids}
            url = f"{self.SHARED_RUN_URL}/fetch_selected"
            response = requests.post(url, json=payload, headers=self.run_headers)
            response.raise_for_status()  # Raise an exception for HTTP errors

            # Convert response to JSON
            ref_selected_orders = response.json()
            print(f"Fetched selected orders from Refurbed: {len(ref_selected_orders.get('orders', []))} orders")

            # Create orders in IdoSell
            self.crate_orders(pending_rows=processed_rows, ref_data=ref_selected_orders)

        else:
            print("No pending rows found to update")
            return



    def crate_orders(self, pending_rows=None, ref_data=None):
        """
        Create orders in IdoSell using the provided data.
        """
        for ref_id, data_row in pending_rows.items():
            # Check if the order already exists in IdoSell
            # Optional checking logic can be added here

            # Create a new order
            try:
                # Find the order with matching id in the list
                ref_order_data = {}
                if 'orders' in ref_data and isinstance(ref_data['orders'], list):
                    for order in ref_data['orders']:
                        if order.get('id') == ref_id:
                            ref_order_data = order
                            break
                
                new_order = self.create_new_order(ref_id=ref_id, data_row=data_row, ref_data=ref_order_data)
                print(f"Created new order in IdoSell: {new_order}")
            except Exception as e:
                print(f"Failed to create order for {ref_id}: {e}")
                continue

            # Edit the newly created order
            # Edit order logic can be added here


    def create_new_order(self, ref_id=None, data_row=None, ref_data=None):
        """
        Create a new order using the provided order data.
        """
        endpoint = f"{self.base_url}/orders/orders"
        
        

    def edit_order(self, order_id, order_status='', order_details=None):
        """
        Edit an existing order using the provided order id.
        """
        endpoint = f"{self.base_url}/orders/orders"
        
        with open('./push/edit_body.json', 'r') as file:
            edit_body = json.load(file)

        # Update the order_serial_number in the edit_body
        if "orders" in edit_body['params']:
            edit_body['params']['orders'][0]['orderSerialNumber'] = order_id
            edit_body['params']['orders'][0]['orderStatus'] = order_status
            edit_body['params']['orders'][0]['clientNoteToOrder'] = f"[refurbed-idosell:{order_details['ID']}]"
            edit_body['params']['orders'][0]['orderNote'] = order_details['notatki'] 
        
        response = requests.put(endpoint, headers=self.ref_headers, json=edit_body)
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Error: {response.status_code}, {response.text}")
    



temp_id = "339335"

ids_api = IdoSellAPI()
#order_history = ids_api.get_order_history(order_id="339071")
#print(order_history)

#order_data = ids_api.get_order(order_id=temp_id)
#print(order_data)

#row = ids_api.parse_sheet_row(2)
#print(row)

#ret = ids_api.edit_order(order_id=temp_id, order_status='new', order_details=row)
#print(ret)

#ret = ids_api.create_order()
#print(ret)

ids_api.ids_push_all()
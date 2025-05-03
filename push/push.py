import requests
import json
import os
import gspread
from gspread_formatting import set_data_validation_for_cell_range, DataValidationRule, BooleanCondition
from oauth2client.service_account import ServiceAccountCredentials

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
        self.headers = {
            "accept": "application/json",
            "X-API-KEY": self.api_key
        }
    
    
    def get_order_history(self, order_id=None):
        """Get order history, optionally filtered by order id."""
        endpoint = f"{self.base_url}/orders/history"
        params = {}
        if order_id:
            params["orderSerialNumber"] = order_id
        
        response = requests.get(endpoint, headers=self.headers, params=params)
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Error: {response.status_code}, {response.text}")
    

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

            # Create orders for each pending row
            for row in pending_rows:
                rowdata = data[row - 1]
                self.create_order(ref_id=rowdata[18]) # Pass refurbed order ID

        else:
            print("No pending rows found to update")
            return


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


    def get_order(self, order_id=None):
        """
        Get details of a specific order using its id.
        """
        endpoint = f"{self.base_url}/orders/orders"
        params = {}
        if order_id:
            params["ordersSerialNumbers"] = order_id
        
        response = requests.get(endpoint, headers=self.headers, params=params)
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Error: {response.status_code}, {response.text}")


    def create_order(self, ref_id=None):
        """
        Create a new order using the provided order data.
        """
        endpoint = f"{self.base_url}/orders/orders"
        
        with open('./push/create_body.json', 'r') as file:
            order_body = json.load(file)

        # Get order data from Refurbed
        
        # Create order_body


        #response = requests.post(endpoint, headers=self.headers, json=order_body)
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Error: {response.status_code}, {response.text}")
        

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
        
        response = requests.put(endpoint, headers=self.headers, json=edit_body)
        
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
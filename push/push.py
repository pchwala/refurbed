import requests
import json
import os
import gspread
from gspread_formatting import set_data_validation_for_cell_range, DataValidationRule, BooleanCondition
from oauth2client.service_account import ServiceAccountCredentials

# test order: 339071
# test order: 338076


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
    
    def parse_sheet_row(self, row_index):
        """
        Parse a row from the Google Sheet and map each value to variables based on the sheet header.
        
        Args:
            row_index (int): The row index to parse (1-based, as per Google Sheets)
            
        Returns:
            dict: A dictionary containing all parsed values
        """
        # Define the sheet header structure
        sheet_header = [
            "checkbox",
            "order_id", "r_state",
            "item_sku", "r_country_code", "r_total_charged", "r_currency_code", "vat",
            "notatki", "magazyn", "r_item_name",
            "r_customer_email", "r_first_name", "r_family_name", "r_phone_number", "ID"
        ]
        
        # Get the row data from the sheet
        row_data = self.orders_sheet.row_values(row_index)
        
        # Create a dictionary to store the parsed values
        parsed_data = {}
        
        # Map the values to variables based on the header
        for i, header in enumerate(sheet_header):
            if i < len(row_data):
                parsed_data[header] = row_data[i]
            else:
                parsed_data[header] = ""  # Default empty string for missing values
        
        return parsed_data
        

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


    def create_order(self):
        """
        Create a new order using the provided order data.
        """
        endpoint = f"{self.base_url}/orders/orders"
        
        with open('./push/create_body.json', 'r') as file:
            orders_body = json.load(file)

        response = requests.post(endpoint, headers=self.headers, json=orders_body)
        
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
    



temp_id = "339234"

ids_api = IdoSellAPI()
#order_history = ids_api.get_order_history(order_id="339071")
#print(order_history)

#order_data = ids_api.get_order(order_id=temp_id)
#print(order_data)

row = ids_api.parse_sheet_row(201)

ret = ids_api.edit_order(order_id=temp_id, order_status='payment_waiting', order_details=row)
print(ret)

#ret = ids_api.create_order()
#print(ret)
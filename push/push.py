import requests
import json
import os

# test order: 339071
# test order: 338076


class IdoSellAPI:
    def __init__(self, tokens_path='./keys/tokens.json'):
        """Initialize the IdoSell API client with tokens from a JSON file."""
        # Load tokens from the JSON file
        with open(tokens_path) as token_file:
            tokens = json.load(token_file)
            self.api_key = tokens.get('idosell_api_key')
        
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



ids_api = IdoSellAPI()
#order_history = ids_api.get_order_history(order_id="339071")
#print(order_history)

#order_data = ids_api.get_order(order_id="339071")
#print(order_data)

ret = ids_api.create_order()
print(ret)
import os
import json
import gspread
import requests
from gspread_formatting import set_data_validation_for_cell_range, DataValidationRule, BooleanCondition
from oauth2client.service_account import ServiceAccountCredentials

from google.oauth2 import service_account
from google.auth.transport.requests import Request

class Sync:
    def __init__(self):
        # === Google Sheets Setup ===
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]

        self.sheet_creds = ServiceAccountCredentials.from_json_keyfile_name('./keys/ref-ids-6c3ebadcd9f8.json', scope)
        self.client = gspread.authorize(self.sheet_creds)

        self.sheet_id = "15e6oc33_A21dNNv03wqdixYc9_mM2GTQzum9z2HylEg"
        
        # Load token from JSON file
        with open('./keys/tokens.json') as token_file:
            tokens = json.load(token_file)
            self.ref_token = tokens['refurbed_token']
            
        self.sheet_headers = {
            "Authorization": f"Plain {self.ref_token}",
            "Content-Type": "application/json"
        }
        
        # Open Orders and Config worksheets
        self.orders_sheet = self.client.open_by_key(self.sheet_id).worksheet("Orders")
        self.config_sheet = self.client.open_by_key(self.sheet_id).worksheet("Config")


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

    def fetch_latest(self):
        payload = {"limit": 1}
        url = f"{self.SHARED_RUN_URL}/fetch_latest"
        response = requests.post(url, json=payload, headers=self.run_headers)
        response.raise_for_status()  # Raise an exception for HTTP errors
        return response.json()
    

sync = Sync()

ret = sync.fetch_latest()
print(ret)
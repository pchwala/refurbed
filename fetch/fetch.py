import os
import requests
import json
import gspread
from gspread_formatting import set_data_validation_for_cell_range, DataValidationRule, BooleanCondition
from oauth2client.service_account import ServiceAccountCredentials

import time

class RefurbedAPI:
    def __init__(self):
        # === Google Sheets Setup ===
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]

        self.creds = ServiceAccountCredentials.from_json_keyfile_name('./keys/ref-ids-6c3ebadcd9f8.json', scope)
        self.client = gspread.authorize(self.creds)

        self.sheet_id = "15e6oc33_A21dNNv03wqdixYc9_mM2GTQzum9z2HylEg"
        
        # Load token from JSON file
        with open('./keys/tokens.json') as token_file:
            tokens = json.load(token_file)
            self.ref_token = tokens['refurbed_token']
            
        self.headers = {
            "Authorization": f"Plain {self.ref_token}",
            "Content-Type": "application/json"
        }
        
        # Open Orders and Config worksheets
        self.orders_sheet = self.client.open_by_key(self.sheet_id).worksheet("Orders")
        self.config_sheet = self.client.open_by_key(self.sheet_id).worksheet("Config")

        # VAT rates for EU countries
        self.vat_rates = {
            "AT": 20,  # Austria
            "BE": 21,  # Belgia
            "BG": 20,  # Bulgaria
            "HR": 25,  # Chorwacja
            "CY": 19,  # Cypr
            "CZ": 21,  # Czechy
            "DK": 25,  # Dania
            "EE": 22,  # Estonia
            "FI": 25.5, # Finlandia
            "FR": 20,  # Francja
            "GR": 24,  # Grecja
            "DE": 19,  # Niemcy
            "ES": 21,  # Hiszpania
            "NL": 21,  # Holandia
            "IE": 23,  # Irlandia
            "LU": 17,  # Luksemburg
            "LT": 21,  # Litwa
            "LV": 21,  # Łotwa
            "MT": 18,  # Malta
            "PL": 23,  # Polska
            "PT": 23,  # Portugalia
            "RO": 19,  # Rumunia
            "SK": 23,  # Słowacja
            "SI": 22,  # Słowenia
            "SE": 25,  # Szwecja
            "HU": 27,  # Węgry
            "IT": 22   # Włochy
        }


    def get_last_order_id(self):
        # Read last fetched order id from Config Sheet
        config = self.config_sheet.get_all_values()
        return config[1][0]
        

    """
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
                "ending_before": last_id
            },
            "sort": {
                "field": "id",
                "order": "ASC"
            }
        }
    """

        
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
    
        
    def save_backup(self, orders):
        # Save fetched orders to a JSON file for backup/logging purposes
        timestamp = int(time.time())  # Use current time as timestamp
        backup_folder = './backups'
        os.makedirs(backup_folder, exist_ok=True)

        backup_file = f"{backup_folder}/orders_{timestamp}.json"
        with open(backup_file, 'w') as f:
            json.dump(orders, f, indent=2)
            
        print(f"Saved {len(orders)} orders to {backup_file}")
        

    def process_orders(self, orders):
        sheet_header = [
            "checkbox",
            "r_state", "r_country_code", "r_currency_code", "r_total_charged", "vat",
            "id_zestawu", "klasa", "klaw", "bat", "magazyn", "notatki", "item_sku", "r_item_name",
            "r_customer_email", "r_first_name", "r_family_name", "r_phone_number", "ID"
        ]

        sheet_rows = []
        last_id = ""

        for order in orders:
            shipping = order.get("shipping_address", {})
            items = order.get("items", [])
            item = items[0] if items else {}
            
            country_code = shipping.get("country_code", "")
            
            # Calculate VAT value based on country code, VAT number, and if its iphone or not
            vat_value = 0
            invoice_address = order.get("invoice_address", {})
            vat_number = invoice_address.get("company_vatin", "")
            item_name = item.get("name", "")
            # Check if the item is an iPhone (case insensitive)
            is_iphone = "iphone" in item_name.lower() if item_name else False

            """
            Cytujac MB:
            stawka vat powinna ustawiać się automatycznie w zależności od kodu kraju.
            * Dla laptopów to będzie:
            - dla zamówień indywidualnych stawka vat obowiązująca w danym kraju
            - dla zamówień biznesowych z NIP - VAT 0 (wyjątek - zamówienia składane z Polski, tu nie będzie vat 0, tylko zawsze 23% vat)
            * Dla telefonów - zawsze vat marża
            """
            if is_iphone is False:
                if country_code in self.vat_rates:
                    if vat_number:
                        if country_code == "PL":
                            vat_value = 23
                        else:
                            vat_value = 0
                    else:
                        vat_value = self.vat_rates.get(country_code, "")
            
            # Extract offer_grading from offer_data if available
            klasa = ""
            if item and "offer_data" in item:
                offer_data = item.get("offer_data", {})
                klasa = offer_data.get("offer_grading", "")
                # Check if battery has to be replaced
                battery_replace = "TRUE" if offer_data.get("battery_condition", "") == "NEW" else "FALSE"

            row = [
                "FALSE",  # checkbox
                order.get("state", ""),
                country_code,
                order.get("settlement_currency_code", ""),
                order.get("settlement_total_charged", ""),
                vat_value,
                "",  # id_zestawu
                klasa,  # klasa - now contains offer_grading
                "FALSE",  # klaw 
                battery_replace,  # bat 
                "",  # magazyn
                "",  # notatki
                item.get("sku", ""),
                item_name,
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

        # Apply to range for all checkbox columns (A for checkbox, I for klaw, J for bat)
        if sheet_rows:
            checkbox_ranges = [f"A2:A{last_row}", f"I2:I{last_row}", f"J2:J{last_row}"]
            for cell_range in checkbox_ranges:
                set_data_validation_for_cell_range(self.orders_sheet, cell_range, checkbox_rule)

        print(f"Successfully wrote {len(sheet_rows)} rows to Google Sheets.")


    def fetch_orders(self):
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
            return

        response_data = response.json()
        orders = response_data.get('orders', [])

        # Save backup
        self.save_backup(orders)
        
        # Process orders
        sheet_rows, last_id = self.process_orders(orders)
        
        # Update sheets
        self.update_sheets(sheet_rows, last_id)


    def fetch_latest_orders(self, update=False, n=100):
        """Fetches the latest 100 orders regardless of the last fetched order ID."""
        # === Refurbed API Setup ===
        r_URL = "https://api.refurbed.com/refb.merchant.v1.OrderService/ListOrders"
        
        # Create payload for latest n orders
        payload = self.payload_all(limit=n)
    
        # Get, decode and save response
        response = requests.post(r_URL, headers=self.headers, json=payload)
    
        if response.status_code != 200:
            print(f"Error: Failed to fetch orders. Status code: {response.status_code}")
            return
    
        response_data = response.json()
        orders = response_data.get('orders', [])
    
        # Save backup
        self.save_backup(orders)
        
        # Process orders
        #sheet_rows, last_id = self.process_orders(orders)
        
        # Update sheets - but don't update the last_id in config
        # since this is just fetching the latest rather than continuing from previous
        #if update:
        #    self.update_sheets(sheet_rows, "")
        
        print(f"Fetched latest {len(orders)} orders")


    def update_order_states(self, orders):
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

    def update_states(self):
        # === Refurbed API Setup ===
        r_URL = "https://api.refurbed.com/refb.merchant.v1.OrderService/ListOrders"

        # Create payload
        payload = self.payload_all()

        # Get, decode and save response
        response = requests.post(r_URL, headers=self.headers, json=payload)
        if response.status_code != 200:
            print(f"Error: Failed to fetch orders. Status code: {response.status_code}")
            return
        
        response_data = response.json()
        orders = response_data.get('orders', [])
        # Save backup
        self.save_backup(orders)
        
        # Update order states in the Google Sheet
        self.update_order_states(orders)




if __name__ == "__main__":
    refurbed_api = RefurbedAPI()

    #refurbed_api.fetch_orders()
    #refurbed_api.update_states()
    refurbed_api.fetch_latest_orders(update=True, n=100)
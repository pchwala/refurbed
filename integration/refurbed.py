import os
import requests
import json
import gspread
from gspread_formatting import set_data_validation_for_cell_range, DataValidationRule, BooleanCondition
from oauth2client.service_account import ServiceAccountCredentials
import logging
import time
from cloud_logging import CloudLogger


class RefurbedAPI:
    def __init__(self, ref_key=None, creds=None, client=None, sheet_id=None, orders_sheet=None, config_sheet=None):
        """
        Initialize with optional parameters to allow using existing credentials
        
        Args:
            headers (dict): API headers for Refurbed API
            creds (ServiceAccountCredentials): Google Sheets API credentials
            client (gspread.Client): Authorized gspread client
            sheet_id (str): Google Sheet ID
            orders_sheet (gspread.Worksheet): Orders worksheet
            config_sheet (gspread.Worksheet): Config worksheet
        """
        # Initialize logger
        self.logger = CloudLogger(instance_id="integration_refurbed", log_level=logging.INFO).get_logger()
        self.logger.info("Initializing RefurbedAPI")
        
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
        
        # Set up API headers
        # Default headers for requests for Refurbed
        self.headers = {
            "Authorization": f"Plain {ref_key}",
            "Content-Type": "application/json"
        }
            
        # Set up Google Sheets connection
        if creds and sheet_id:
            self.creds = creds
            if client:
                self.client = client
            else:
                self.client = gspread.authorize(self.creds)
            
            self.sheet_id = sheet_id
            
            # Use provided sheets or open new ones
            if orders_sheet:
                self.orders_sheet = orders_sheet
            else:
                self.orders_sheet = self.client.open_by_key(self.sheet_id).worksheet("Orders")
                
            if config_sheet:
                self.config_sheet = config_sheet
            else:
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
        
    def process_orders(self, orders):
        self.logger.info(f"Processing {len(orders)} orders from Refurbed")
        sheet_header = [
            "checkbox",
            "r_state", "r_country_code", "r_currency_code", "r_total_paid", "vat",
            "id_zestawu", "klasa", "klaw", "bat", "magazyn", "idosell_id", "item_sku", "r_item_name",
            "r_customer_email", "r_first_name", "r_family_name", "r_phone_number", "ID"
        ]

        sheet_rows = []
        last_id = ""

        for order in orders:
            try:
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
                else:
                    vat_value = -1 # VAT marża
                
                # Extract offer_grading from offer_data if available
                klasa = ""
                battery_replace = "FALSE"
                if item and "offer_data" in item:
                    offer_data = item.get("offer_data", {})
                    klasa = offer_data.get("offer_grading", "")
                    # Check if battery has to be replaced
                    battery_replace = "TRUE" if offer_data.get("battery_condition", "") == "NEW" else "FALSE"

                if is_iphone is False:
                    if klasa == "B":
                        klasa = "A 2"
                    elif klasa == "C":
                        klasa = "A-"
                else:
                    klasa = ""

                row = [
                    "FALSE",  # checkbox
                    order.get("state", ""),
                    country_code,
                    order.get("settlement_currency_code", ""),
                    order.get("settlement_total_paid", ""),
                    vat_value,
                    "",  # id_zestawu
                    klasa,  # klasa - now contains offer_grading
                    "FALSE",  # klaw 
                    battery_replace,  # bat 
                    "",  # magazyn
                    "",  # idosell_id
                    item.get("sku", ""),
                    item_name,
                    order.get("customer_email", ""),
                    shipping.get("first_name", ""),
                    shipping.get("family_name", ""),
                    shipping.get("phone_number", ""),
                    order.get("id", "")
                ]
                last_id = order.get("id", "")
                self.logger.info(f"Fetched order ID: {last_id}")

                sheet_rows.append(row)
            except Exception as e:
                self.logger.error(f"Error processing order {order.get('id', 'unknown')}: {str(e)}")
            
        self.logger.info(f"Processed {len(sheet_rows)} orders successfully, last ID: {last_id}")
        return sheet_rows, last_id

    def update_sheets(self, sheet_rows, last_id):
        # === Write to sheet ===
        self.logger.info(f"Updating sheets with {len(sheet_rows)} orders")
        
        try:
            self.orders_sheet.append_rows(sheet_rows, value_input_option="USER_ENTERED")
            if last_id != '':
                self.config_sheet.update_acell("A2", last_id)
                self.logger.info(f"Updated last order ID in config: {last_id}")

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
                self.logger.info(f"Applied checkbox validation to {len(checkbox_ranges)} ranges")

            self.logger.info(f"Successfully wrote {len(sheet_rows)} rows to Google Sheets")
        except Exception as e:
            self.logger.error(f"Error updating sheets: {str(e)}")
            raise

    def fetch_orders(self):
        # === Refurbed API Setup ===
        r_URL = "https://api.refurbed.com/refb.merchant.v1.OrderService/ListOrders"
        
        # Get last order ID
        r_last_id = self.get_last_order_id()
        self.logger.info(f"Fetching orders starting after ID: {r_last_id}")
        
        # Create payload
        payload = self.payload_last(r_last_id)

        # Get, decode and save response
        response = requests.post(r_URL, headers=self.headers, json=payload)

        if response.status_code != 200:
            error_msg = f"Error: Failed to fetch orders. Status code: {response.status_code}"
            self.logger.error(error_msg)
            return

        response_data = response.json()
        orders = response_data.get('orders', [])
        self.logger.info(f"Successfully fetched {len(orders)} orders from Refurbed API")
        
        # Process orders
        sheet_rows, last_id = self.process_orders(orders)
        
        # Update sheets
        self.update_sheets(sheet_rows, last_id)

    def fetch_selected_orders(self, order_ids):
        """Fetches specific orders by their IDs.
        
        Args:
            order_ids (list): List of order IDs to fetch
        
        Returns:
            list: The fetched order data
        """
        # === Refurbed API Setup ===
        r_URL = "https://api.refurbed.com/refb.merchant.v1.OrderService/ListOrders"
        
        self.logger.info(f"Fetching selected orders by IDs: {order_ids}")
        
        # Create payload for specific orders
        payload = self.payload_selected(order_ids)
    
        # Get, decode and save response
        response = requests.post(r_URL, headers=self.headers, json=payload)
    
        if response.status_code != 200:
            error_msg = f"Error: Failed to fetch selected orders. Status code: {response.status_code}"
            self.logger.error(error_msg)
            return []
    
        response_data = response.json()
        orders = response_data.get('orders', [])
        self.logger.info(f"Successfully fetched {len(orders)} selected orders")
        
        return orders

    def fetch_latest_orders(self, update=False, n=100):
        """Fetches the latest 100 orders regardless of the last fetched order ID."""
        # === Refurbed API Setup ===
        r_URL = "https://api.refurbed.com/refb.merchant.v1.OrderService/ListOrders"
        
        # Create payload for latest n orders
        payload = self.payload_all(limit=n)
    
        # Get, decode and save response
        response = requests.post(r_URL, headers=self.headers, json=payload)
    
        if response.status_code != 200:
            self.logger.error(f"Error: Failed to fetch orders. Status code: {response.status_code}")
            return
    
        response_data = response.json()
        orders = response_data.get('orders', [])
        
        # Process orders
        sheet_rows, last_id = self.process_orders(orders)
        
        # Update sheets - but don't update the last_id in config
        # since this is just fetching the latest rather than continuing from previous
        if update:
            self.update_sheets(sheet_rows, "")
        
        self.logger.info(f"Fetched latest {len(orders)} orders")

    def update_order_states(self, orders):
        # Get all order IDs and values from the sheet
        all_rows = self.orders_sheet.get_all_values()
        
        # Find the column index for 'r_state' and 'ID'
        header = all_rows[0]
        r_state_col = header.index("r_state") + 1  # 1-indexed for Sheets API
        id_col = header.index("ID") + 1
        
        self.logger.info(f"Found r_state column at index {r_state_col}, ID column at index {id_col}")
        
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
                #self.logger.info(f"Will update order {order_id} with state {state} at row {row_num}")
        
        if updates:
            # Apply all updates in batch
            self.orders_sheet.batch_update(updates)
            self.logger.info(f"Updated {len(updates)} order states in the Google Sheet")
            return len(updates)
        else:
            self.logger.info("No orders found to update")
            return 0

    def update_states(self):
        """
        Updates the states of orders in the Google Sheet by fetching their current state from Refurbed API.
        First collects all order IDs from the sheet, then queries only those orders.
        
        Returns:
            int: Number of orders updated
        """
        # Load orders worksheet and get all values
        all_rows = self.orders_sheet.get_all_values()
        
        # Find the ID column index (should be column S or index 18)
        header = all_rows[0]
        id_col_idx = header.index("ID")
        
        # Extract all non-empty order IDs from the sheet (skip header row)
        order_ids = []
        for row in all_rows[1:]:
            if len(row) > id_col_idx and row[id_col_idx] and row[id_col_idx] != "":
                order_ids.append(row[id_col_idx])
        
        self.logger.info(f"Found {len(order_ids)} order IDs in the sheet to update")
        
        if not order_ids:
            self.logger.info("No orders found in the sheet to update")
            return 0
        
        # === Refurbed API Setup ===
        r_URL = "https://api.refurbed.com/refb.merchant.v1.OrderService/ListOrders"

        # Create payload with only the specific order IDs, but we need to batch them in groups of 100
        all_orders = []
        # Split order_ids into chunks of max 100 for API limitation
        for i in range(0, len(order_ids), 100):
            chunk = order_ids[i:i+100]
            self.logger.info(f"Processing batch {i//100 + 1} with {len(chunk)} orders")
            
            # Create payload with current chunk of order IDs
            payload = self.payload_selected(chunk)

            # Get, decode and save response
            response = requests.post(r_URL, headers=self.headers, json=payload)
            if response.status_code != 200:
                self.logger.error(f"Error: Failed to fetch orders batch {i//100 + 1}. Status code: {response.status_code}")
                raise Exception(f"Error: Failed to fetch orders. Status code: {response.status_code}")
            
            response_data = response.json()
            batch_orders = response_data.get('orders', [])
            all_orders.extend(batch_orders)
            self.logger.info(f"Successfully fetched {len(batch_orders)} orders from batch {i//100 + 1}")
        
        self.logger.info(f"Successfully fetched total of {len(all_orders)} orders from Refurbed API for updating")
        
        # Update order states in the Google Sheet
        updated = self.update_order_states(all_orders)

        return updated

    def change_state(self, order_item_id, state, tracking_number=None):
        """
        Update the state of a specific order item in the Refurbed system.
        
        Args:
            order_item_id (str): The ID of the order item to update.
            state (str): The new state to set for the order item.
            tracking_number (str, optional): The tracking number to associate with the order.
        
        Returns:
            bool: True if the state was successfully updated, False otherwise.
        """
        # Set up API endpoint for updating order item state
        r_URL = "https://api.refurbed.com/refb.merchant.v1.OrderItemService/UpdateOrderItemState"

        # Create payload with item ID and new state
        if tracking_number:
            tracking_url = f"https://www.ups.com/track?loc=en_GB&trackingNumber={tracking_number}"
            
            payload = {
                "id": order_item_id,
                "state": state,
                "parcel_tracking_url": tracking_url
            }
        else:
            payload = {
                "id": order_item_id,
                "state": state
            }
        
        # Send state update request
        response = requests.post(r_URL, headers=self.headers, json=payload)
        
        # Handle response
        if response.status_code != 200:
            self.logger.error(f"Error: Failed to update order states. Status code: {response.status_code}")
            self.logger.error(f"Response: {response.text}")
            return False
        
        # Log success
        self.logger.info(f"Successfully updated order item to state: {state}")
        return True

    def list_orders_items(self, order_ids):
        """
        Retrieve all item IDs associated with the specified order IDs.
        
        This method fetches the specified orders from Refurbed API and extracts 
        the item IDs from each order.
        
        Args:
            order_ids (list): A list of order IDs to retrieve items for.
        
        Returns:
            list: A list of item IDs associated with the specified orders.
        """

        # Check if order_ids is empty
        if not order_ids:
            self.logger.info("No order IDs provided.")
            return []

        # Fetch the specified orders from the API
        fetched_orders = self.fetch_selected_orders(order_ids)

        # Initialize empty list for collecting item IDs
        items_list = []

        # Extract all item IDs from the fetched orders
        for order in fetched_orders:
            items = order.get("items", [])
            for item in items:
                item_id = item.get("id", "")
                items_list.append(item_id)

        # Log the extracted item IDs
        self.logger.info(f"Items list: {items_list}")
        
        return items_list

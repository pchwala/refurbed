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

app = Flask(__name__)

class CloudIdoSellAPI:
    def __init__(self):
        """Initialize the IdoSell API client with credentials from environment variables."""
        # === Google Sheets Setup ===
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]

        creds_json = os.environ["GCLOUD_CREDENTIALS_JSON"]
        self.creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(creds_json), scope)
        self.client = gspread.authorize(self.creds)

        self.sheet_id = os.environ["SHEET_ID"]
        
        # Load API key from environment variable
        self.api_key = os.environ["IDOSELL_API_KEY"]
        
        # Open Orders and Config worksheets
        self.orders_sheet = self.client.open_by_key(self.sheet_id).worksheet("Orders")
        self.config_sheet = self.client.open_by_key(self.sheet_id).worksheet("Config")
        
        # Base URL for API requests
        self.base_url = "https://vedion.pl/api/admin/v5"
        
        # Default headers for requests
        self.ids_headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "X-API-KEY": self.api_key
        }

        self.SHARED_RUN_URL = os.environ.get("SHARED_RUN_URL", "https://shared-860977612313.europe-central2.run.app")
        self.FETCH_RUN_URL = "https://fetch-860977612313.europe-central2.run.app"

        # Create credentials for Cloud Run authentication
        self.run_creds = service_account.IDTokenCredentials.from_service_account_info(
            json.loads(creds_json),
            target_audience=self.SHARED_RUN_URL
        )

        self.run_creds.refresh(Request())

        self.run_headers = {
            'Authorization': f'Bearer {self.run_creds.token}',
            'Content-Type': 'application/json'
        }

        self.CREATE_BODY_PATH = os.path.join(os.path.dirname(__file__), 'create_body.json')
        self.EDIT_BODY_PATH = os.path.join(os.path.dirname(__file__), 'edit_body.json')

        # Country codes to Polish country names mapping
        self.country_names = {
            "AT": "Austria",
            "BE": "Belgia",
            "BG": "Bułgaria",
            "HR": "Chorwacja",
            "CY": "Cypr",
            "CZ": "Czechy",
            "DK": "Dania",
            "EE": "Estonia",
            "FI": "Finlandia",
            "FR": "Francja",
            "GR": "Grecja",
            "DE": "Niemcy",
            "ES": "Hiszpania",
            "NL": "Holandia",
            "IE": "Irlandia",
            "LU": "Luksemburg",
            "LT": "Litwa",
            "LV": "Łotwa",
            "MT": "Malta",
            "PL": "Polska",
            "PT": "Portugalia",
            "RO": "Rumunia",
            "SK": "Słowacja",
            "SI": "Słowenia",
            "SE": "Szwecja",
            "HU": "Węgry",
            "IT": "Włochy"
        }
        
    def get_product(self, product_id=None):
        """
        Get details of a specific product using its id.
        """
        endpoint = f"{self.base_url}/products/products"
        params = {}
        if product_id:
            params["productIds"] = product_id
        
        response = requests.get(endpoint, headers=self.ids_headers, params=params)
        
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

            # Fetch selected orders from Refurbed
            payload = {"order_ids": ref_ids}
            url = f"{self.SHARED_RUN_URL}/fetch_selected"
            response = requests.post(url, json=payload, headers=self.run_headers)
            response.raise_for_status()  # Raise an exception for HTTP errors

            # Convert response to JSON
            ref_selected_orders = response.json()
            print(f"Fetched selected orders from Refurbed: {len(ref_selected_orders.get('orders', []))} orders")

            # Create orders in IdoSell
            self.create_orders(pending_rows=processed_rows, ref_data=ref_selected_orders)
            return True
        else:
            print("No pending rows found to update")
            return False

    def create_orders(self, pending_rows=None, ref_data=None):
        """
        Create orders in IdoSell using the provided data.
        """
        created_orders = []
        for ref_id, data_row in pending_rows.items():
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
                new_order_id = new_order['results']['ordersResults'][0]['orderSerialNumber']
                print(f"New order ID: {new_order_id}")
                
                # Track created orders
                created_orders.append({
                    "ref_id": ref_id,
                    "idosell_id": new_order_id
                })

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
            except Exception as e:
                print(f"Failed to create order for {ref_id}: {e}")
                continue

        return created_orders

    def create_new_order(self, ref_id=None, data_row=None, ref_data=None):
        """
        Create a new order using the provided order data.
        """
        # Temporary checking if there is more than one item in the order
        # If total charged is more than charged for the first item then there is more items in the order
        if ref_data['total_charged'] != ref_data['items'][0]['total_charged']:
            raise Exception(f"Order {ref_id} has more than one item. Please check the order in Refurbed.")

        endpoint = f"{self.base_url}/orders/orders"
        
        # The path to create_body.json would be relative to the current directory in Cloud Run
        # We need to check if the file exists, otherwise load from a default template
        create_body = None
        try:
            with open(self.CREATE_BODY_PATH, 'r') as file:
                create_body = json.load(file)
        except FileNotFoundError:
            raise Exception(f"Error creating order: {self.CREATE_BODY_PATH} not found.")
            
        # Create a shorthand variable for the nested dictionary
        order = create_body['params']['orders'][0]
        
        # Call sub-methods to prepare different parts of the order
        self._prepare_order_details(order, ref_data, data_row)
        self._prepare_client_details(order, ref_data)
        
        # Get bundle response
        bundle_response = self.get_product(product_id=data_row[6])
        bundle = bundle_response['results'][0]['productBundleItems']
        
        id_matki = self._prepare_product_details(order, data_row, bundle)
        
        # Prepare order notes
        notes = self._prepare_order_notes(data_row, id_matki)
        order['products'][0]['remarksToProduct'] = notes
        order['clientNoteToOrder'] = f"[refurbed-api-id:{ref_id}]"

        # Add the API request and response handling
        response = requests.post(endpoint, headers=self.ids_headers, json=create_body)

        if response.status_code in [200, 207]:
            return response.json()
        else:
            raise Exception(f"Error creating order: {response.status_code}, {response.text}")
    
    def _prepare_order_details(self, order, ref_data, data_row):
        """
        Prepare basic order details
        """
        order['currencyId'] = ref_data['currency_code']
        order['billingCurrency'] = ref_data['currency_code']
        # Format the date to extract only YYYY-MM-DD from the ISO timestamp
        order['purchaseDate'] = ref_data['released_at'].split('T')[0]
        order['stockId'] = data_row[10].lstrip('M') if data_row[10] else ""  # Extract only the number from warehouse code
    
    def _prepare_client_details(self, order, ref_data):
        """
        Prepare client data and delivery address
        """
        # Populate client data
        client_data = order['clientWithoutAccountData']
        shipping_address = ref_data['shipping_address']
        
        client_data['clientFirstName'] = shipping_address['first_name']
        client_data['clientLastName'] = shipping_address['family_name']
        client_data['clientStreet'] = shipping_address['street_name'] + ' ' + shipping_address['house_no']
        client_data['clientZipCode'] = shipping_address['post_code']
        client_data['clientCity'] = shipping_address['town']
        client_data['clientCountry'] = self.country_names[shipping_address['country_code']]
        client_data['clientEmail'] = ref_data.get('customer_email', "Janusz@testowy.com")
        client_data['clientPhone1'] = shipping_address.get('phone_number', "500100100")
        client_data['langId'] = shipping_address['country_code']
        
        # Populate delivery address
        delivery_address = order['clientDeliveryAddress']
        delivery_address['clientDeliveryAddressFirstName'] = shipping_address['first_name']
        delivery_address['clientDeliveryAddressLastName'] = shipping_address['family_name']
        delivery_address['clientDeliveryAddressFirm'] = ""
        delivery_address['clientDeliveryAddressStreet'] = shipping_address['street_name'] + ' ' + shipping_address['house_no']
        delivery_address['clientDeliveryAddressZipCode'] = shipping_address['post_code']
        delivery_address['clientDeliveryAddressCity'] = shipping_address['town']
        delivery_address['clientDeliveryAddressCountry'] = self.country_names[shipping_address['country_code']]
        delivery_address['clientDeliveryAddressCountryId'] = shipping_address['country_code']
        delivery_address['clientDeliveryAddressPhone1'] = shipping_address.get('phone_number', "500100100")
    
    def _prepare_product_details(self, order, data_row, bundle):
        """
        Prepare product and bundle details
        """
        product = order['products']
        product[0] = {
            "productId": data_row[6],
            "sizeId": "uniw",
            "stockId": data_row[10].lstrip('M') if data_row[10] else "",
            "productQuantity": 1,
            "productQuantityOperationType": "add",
            "productRetailPrice": data_row[4],
            "productVat": data_row[5],
            "remarksToProduct": ""
        }

        id_matki = None
        # If bundle is empty, use only product id
        # If bundle is not empty, use product id and add bundle items
        if not bundle:
            product[0]['remarksToProduct'] = "Brak zestawu"
        else:
            # Make a list of bundle items and append them to the product
            product_bundle_items = []
            for item in bundle:
                product_bundle_items.append({
                    "productId": item['productId'],
                    "sizeId": "uniw",
                })
                if item['isBundleShown'] == True:
                    id_matki = item['productId']

            product[0]['productBundleItems'] = product_bundle_items
        
        return id_matki
    
    def _prepare_order_notes(self, data_row, id_matki):
        """
        Prepare order notes with product details
        """
        item_parts = data_row[13].split("|")
        # Keyboard layout for order. Strip it from the item name
        keyboard_layout = item_parts[-1].strip()

        # HDD size for order. Strip it from the item name
        hard_drive = ""
        for part in item_parts:
            part = part.strip()
            if "GB SSD" in part or "TB SSD" in part or "GB HDD" in part or "TB HDD" in part:
                # Extract just the capacity portion (e.g., "512 GB" from "512 GB SSD")
                hard_drive = part.split("SSD")[0].split("HDD")[0].strip()
                break

        # Create order notes
        notes = "ID matki: " + str(id_matki) + "\n"
        notes += "Klasa " + data_row[7] + "\n"
        notes += "Klawiatura: " + keyboard_layout + "\n"
        notes += "Dysk: " + hard_drive + "\n"

        if data_row[8] == "TRUE":
            notes += "Wymiana klawiatury\n"
        if data_row[9] == "TRUE":
            notes += "Wymiana baterii\n"
            
        return notes

    def edit_order(self, order_id, order_details=None):
        """
        Edit an existing order using the provided order id.
        """
        endpoint = f"{self.base_url}/orders/orders"
        
        try:
            with open(self.EDIT_BODY_PATH, 'r') as file:
                edit_body = json.load(file)
        except FileNotFoundError:
            raise Exception(f"Error editing order: {self.EDIT_BODY_PATH} not found.")
        
        response = requests.put(endpoint, headers=self.ids_headers, json=edit_body)
        
        if response.status_code in [200, 207]:
            return response.json()
        else:
            raise Exception(f"Error editing order: {response.status_code}, {response.text}")


def push_orders_task():
    """Task to push orders to IdoSell that runs on a schedule"""
    try:
        # Capture all print output to return it as a string
        f = io.StringIO()
        with redirect_stdout(f):
            api = CloudIdoSellAPI()
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
    """Fetch orders from Refurbed API through the fetch service"""
    try:
        api = CloudIdoSellAPI()
        # Make a POST request to the fetch service
        response = requests.post(
            f"{api.FETCH_RUN_URL}/", 
            headers=api.run_headers
        )
        response.raise_for_status()
        
        # Process the response
        result = response.json()
        if "error" in result:
            return render_template('index.html', output=f"Błąd: {result['error']}")
        
        output = "Zamówienia zostały pobrane pomyślnie."
        return render_template('index.html', output=output)
    except Exception as e:
        error_msg = f"Błąd podczas pobierania zamówień: {str(e)}"
        return render_template('index.html', output=error_msg)


@app.route("/update_states", methods=["POST"])
def update_states():
    """Update order states from Refurbed API through the shared service"""
    try:
        api = CloudIdoSellAPI()
        # Make a POST request to the shared service
        response = requests.post(
            f"{api.SHARED_RUN_URL}/update_states", 
            headers=api.run_headers
        )
        response.raise_for_status()
        
        # Process the response
        result = response.json()
        if "error" in result:
            return render_template('index.html', output=f"Błąd: {result['error']}")
        
        updated_count = result.get("updated", 0)
        total_count = result.get("total", 0)
        output = f"Zaktualizowano {updated_count} z {total_count} stanów zamówień."
        
        # Show details of updated orders
        if updated_count > 0 and "orders" in result:
            output += "\n\nZaktualizowane zamówienia:"
            for order in result.get("orders", []):
                output += f"\nWiersz {order.get('row')}: ID {order.get('id')} - Nowy stan: {order.get('state')}"
        
        return render_template('index.html', output=output)
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
import os
import requests
import json


class IdoSellAPI:
    def __init__(self, api_key=None):
        """Initialize the IdoSell API client with credentials."""
        # Load API key from parameter or environment variable
        self.ids_key = api_key or os.environ.get("IDOSELL_API_KEY")
        
        if not self.ids_key:
            raise ValueError("IdoSell API key must be provided or set as IDOSELL_API_KEY environment variable")
        
        # Base URL for API requests
        self.base_url = "https://vedion.pl/api/admin/v5"
        
        # Default headers for requests for IdoSell
        self.ids_headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "X-API-KEY": self.ids_key
        }
        
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

        self.lang_ids = {
            "PL": "pol",
            "EN": "eng",
            "DE": "ger",
            "FR": "fre",
            "IT": "ita",
            "ES": "spa"
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
            raise Exception(f"Error: {response.status_code, {response.text}}")
        
    def get_order(self, order_id=None):
        """
        Get details of a specific order using its id.
        """
        endpoint = f"{self.base_url}/orders/orders?ordersSerialNumbers={order_id}"
        
        response = requests.get(endpoint, headers=self.ids_headers)
        
        if response.status_code == 200:
            return response.json()
        else:
            return None
    
    def get_order_tracking_id(self, order_id=None):
        """
        Get tracking ID for a specific order using its id.
        """
        order = self.get_order(order_id=order_id)
        
        # Get order details and extract tracking number and status
        if order is not None:
            tracking_number = None
            tracking_number = order['Results'][0]['orderDetails']['dispatch']['deliveryPackageId']
            if tracking_number is not None:
                is_finished = order['Results'][0]['orderDetails']['orderStatus'] == "finished"
                # Return tracking number and status, finished = True, not finished = False
                return tracking_number, is_finished
            else:
                return None, None
        else:
            raise Exception("Error: No order found with the provided ID. Tracking number not updated")
            
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
                # Extract json response and order request data from returned tuple
                # order_request is used for further editing of the order
                order_request = new_order[1]
                new_order = new_order[0]
                print(f"Created new order in IdoSell: {new_order}")
                new_order_id = new_order['results']['ordersResults'][0]['orderSerialNumber']
                print(f"New order ID: {new_order_id}")
                
                # Track created orders
                created_orders.append({
                    "ref_id": ref_id,
                    "idosell_id": new_order_id
                })

                # Additional order details
                order_details = {
                    "orderStatus": "on_order",
                    "orderNote": order_request['products'][0]['remarksToProduct'],
                    "orderSerialNumber": new_order_id
                }

                payment_details = {
                    "sourceId": new_order_id,
                    "value": data_row[4]
                }

                # Change order note and status
                edit_order_response = self.edit_order(order_id=new_order_id, order_details=order_details)

                # Add payment to the order
                #payment_response = self.add_payment(order_id=new_order_id, value=data_row[4])

                # Confirm payment
                #payment_confirmation_response = self.confirm_payment(order_id=new_order_id)

                # Vat marża = IPHONE
                is_iphone = False
                if data_row[5] == '-1':
                    is_iphone = True

                # If the order is an iPhone, set the order status to "wait_for_packaging"
                if is_iphone is True:
                    order_details["orderStatus"] = "wait_for_packaging"
                    edit_order_response = self.edit_order(order_id=new_order_id, order_details=order_details)
                
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
        
        # Vat marża = IPHONE
        is_iphone = False
        if data_row[5] == '-1':
            is_iphone = True

        endpoint = f"{self.base_url}/orders/orders"
        
        # The path to create_body.json would be relative to the current directory in Cloud Run
        # We need to check if the file exists, otherwise load from a default template
        create_body = None
        try:
            with open('./integration_local/create_body.json', 'r') as file:
                create_body = json.load(file)
        except FileNotFoundError:
            raise Exception(f"Error creating order: {'create_body.json'} not found.")
            
        # Create a shorthand variable for the nested dictionary
        order = create_body['params']['orders'][0]
        
        # Call sub-methods to prepare different parts of the order
        self._prepare_order_details(order, ref_data, data_row)
        self._prepare_client_details(order, ref_data)
        
        # Get bundle response
        bundle_response = self.get_product(product_id=data_row[6])
        bundle = bundle_response['results'][0]['productBundleItems']
        
        id_matki = self._prepare_product_details(order, data_row, bundle)
        
        order['clientNoteToOrder'] = f"[refurbed-api-id:{ref_id}]"
        
        # Prepare order notes
        if is_iphone is False:
            notes = self._prepare_order_notes(data_row, id_matki)
            order['products'][0]['remarksToProduct'] = notes
        else:
            if data_row[9] == "TRUE":
                order['products'][0]['remarksToProduct'] = "Wymiana baterii na 100%"

        # Add the API request and response handling
        response = requests.post(endpoint, headers=self.ids_headers, json=create_body)

        if response.status_code in [200, 207]:
            # Return response and order details send via request
            return [response.json(), order]
        else:
            raise Exception(f"Error creating order: {response.status_code}, {response.text}")
    
    def _prepare_order_details(self, order, ref_data, data_row):
        """
        Prepare basic order details
        """
        order['currencyId'] = ref_data['settlement_currency_code']
        order['billingCurrency'] = ref_data['settlement_currency_code']
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
        invoice_address = ref_data['invoice_address']
        
        client_data['clientFirstName'] = invoice_address['first_name']
        client_data['clientLastName'] = invoice_address['family_name']
        client_data['clientStreet'] = invoice_address['street_name'] + ' ' + invoice_address['house_no']
        client_data['clientZipCode'] = invoice_address['post_code']
        client_data['clientCity'] = invoice_address['town']
        client_data['clientCountry'] = self.country_names[invoice_address['country_code']]
        client_data['clientEmail'] = ref_data['customer_email']
        client_data['clientPhone1'] = invoice_address.get('phone_number', '')
        # Set language ID if available for the country code
        if invoice_address['country_code'] in self.lang_ids:
            client_data['langId'] = self.lang_ids[invoice_address['country_code']]
        else:
            # Default to English if no matching language found
            client_data['langId'] = "eng"


        # Check if company_vatin field exists and is not empty
        if 'company_vatin' in invoice_address and invoice_address['company_vatin']:
            client_data['clientNip'] = invoice_address['company_vatin']
            client_data['clientFirm'] = invoice_address['company_name']
        
        # Populate delivery address
        delivery_address = order['clientDeliveryAddress']
        delivery_address['clientDeliveryAddressFirstName'] = shipping_address['first_name']
        delivery_address['clientDeliveryAddressLastName'] = shipping_address['family_name']
        delivery_address['clientDeliveryAddressStreet'] = shipping_address['street_name'] + ' ' + shipping_address['house_no']
        delivery_address['clientDeliveryAddressZipCode'] = shipping_address['post_code']
        delivery_address['clientDeliveryAddressCity'] = shipping_address['town']
        delivery_address['clientDeliveryAddressCountry'] = self.country_names[shipping_address['country_code']]
        delivery_address['clientDeliveryAddressCountryId'] = shipping_address['country_code']
        delivery_address['clientDeliveryAddressPhone1'] = shipping_address.get('phone_number')

        if 'company_name' in shipping_address:
            delivery_address['clientDeliveryAddressFirm'] = shipping_address['company_name']
    
    def _prepare_product_details(self, order, data_row, bundle):
        """
        Prepare product and bundle details
        """
        vat_value = data_row[5]
        if vat_value == '-1':
            vat_value = '0'

        product = order['products']
        product[0] = {
            "productId": data_row[6], 
            "sizeId": "uniw",
            "stockId": data_row[10].lstrip('M') if data_row[10] else "",
            "productQuantity": 1,
            "productQuantityOperationType": "add",
            "productRetailPrice": data_row[4],
            "productVat": vat_value,
            "remarksToProduct": ""
        }

        id_matki = None
        # If bundle is empty, use only product id
        # If bundle is not empty, use product id and add bundle items
        if not bundle:
            #product[0]['remarksToProduct'] = "Brak zestawu"
            pass
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
        notes += "Dysk: " + hard_drive + "\n"

        if data_row[8] == "TRUE":
            notes += "Wymiana klawiatury " + keyboard_layout + "\n"
        else:
            notes += "Klawiatura: " + keyboard_layout + "\n"
        if data_row[9] == "TRUE":
            notes += "Wymiana baterii\n"
            
        return notes

    def edit_order(self, order_id, order_details=None):
        """
        Edit an existing order using the provided order id.
        """
        endpoint = f"{self.base_url}/orders/orders"
        
        try:
            with open('./integration_local/edit_body.json', 'r') as file:
                edit_body = json.load(file)
        except FileNotFoundError:
            raise Exception(f"Error editing order: {'edit_body.json'} not found.")
        
        order = edit_body['params']['orders'][0]

        order['orderSerialNumber'] = order_id
        order['orderStatus'] = order_details['orderStatus']
        order['orderNote'] = order_details['orderNote']
        
        response = requests.put(endpoint, headers=self.ids_headers, json=edit_body)
        
        if response.status_code in [200, 207]:
            return response.json()
        else:
            raise Exception(f"Error editing order: {response.status_code}, {response.text}")
        
    def add_payment(self, order_id, value=0):
        """
        Add a payment to an existing order using the provided order id.
        """
        endpoint = f"{self.base_url}/payments/payments"
        
        payload = { 
            "params": {
                "sourceType": "order",
                "sourceId": order_id,
                "value": value,
                "account": "PL54249000050000460097455936",
                "type": "advance",
                "paymentFormId": 1
            },
            "settings": {
                "sendMail": False,
                "sendSms": False
            }
        }

        response = requests.post(endpoint, headers=self.ids_headers, json=payload)
        
        if response.status_code in [200, 207]:
            return response.json()
        else:
            raise Exception(f"Error adding payment: {response.status_code}, {response.text}")
        

    def confirm_payment(self, order_id):
        """
        Confirm a payment for an existing order using the provided order id.
        """
        endpoint = f"{self.base_url}/payments/confirm"
        
        payload = {
            "params": {
                "sourceType": "order",
                "paymentNumber": f"{order_id}-1"
            },
            "settings": {
                "sendMail": False,
                "sendSms": False
            }
        }
    
        response = requests.put(endpoint, headers=self.ids_headers, json=payload)
        
        if response.status_code in [200, 207]:
            return response.json()
        else:
            raise Exception(f"Error confirming payment: {response.status_code}, {response.text}")
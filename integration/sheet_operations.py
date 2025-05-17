import gspread
import logging
from oauth2client.service_account import ServiceAccountCredentials
from gspread_formatting import set_data_validation_for_cell_range, DataValidationRule, BooleanCondition

class SheetOperations:
    """
    Class for handling operations on Google Sheets.
    Provides functionality to manage orders, config, and archive sheets.
    """
    
    def __init__(self, orders_sheet, config_sheet, archive_sheet, logger=None):
        """
        Initialize SheetOperations with sheet handles.
        
        Args:
            orders_sheet: Handle to the orders sheet
            config_sheet: Handle to the configuration sheet
            archive_sheet: Handle to the archive sheet
            logger: Logger instance (optional)
        """
        self.orders_sheet = orders_sheet
        self.config_sheet = config_sheet
        self.archive_sheet = archive_sheet
        self.logger = logger
    
    def archive_orders(self):
        """
        Archive completed orders from the orders sheet to the archive sheet.
        
        Checks each order's 'r_state' field and archives those with
        status 'SHIPPED' or 'CANCELLED'.
        """
        # Get all order data including headers
        all_orders = self.orders_sheet.get_all_values()
        archived_orders = self.archive_sheet.get_all_values()
        archived_length = len(archived_orders)
        
        # Separate headers and data rows
        headers = all_orders[0]
        data_rows = all_orders[1:] if len(all_orders) > 1 else []
        
        # Find the index of the 'r_state' column
        try:
            state_index = headers.index('r_state')
        except ValueError:
            self.logger.error("Column 'r_state' not found in orders sheet")
            return
        
        # Separate completed orders (SHIPPED/CANCELLED) from active orders
        completed_orders = []
        active_orders = []
        
        # Create checkbox rule (TRUE/FALSE)
        checkbox_rule = DataValidationRule(
            condition=BooleanCondition('BOOLEAN'),
            showCustomUi=True
        )
        
        for row in data_rows:
            # Check if the row has enough columns
            if len(row) > state_index:
                state = row[state_index]
                if state == 'SHIPPED' or state == 'CANCELLED':
                    completed_orders.append(row)
                else:
                    active_orders.append(row)
            else:
                # If row doesn't have r_state field, keep it as active
                active_orders.append(row)
        
        # Step 1: Append completed orders to archive sheet
        if completed_orders:
            self.archive_sheet.append_rows(completed_orders, value_input_option='USER_ENTERED')
            amount = len(completed_orders)
            self.logger.info(f"Archived {amount} completed orders")
            # Apply checkbox rule to the appropriate columns only for newly appended rows
            l_start = archived_length + 1
            l_end = archived_length + amount
            checkbox_ranges = [f"A{l_start}:A{l_end}", f"I{l_start}:I{l_end}", f"J{l_start}:J{l_end}"]
            for cell_range in checkbox_ranges:
                set_data_validation_for_cell_range(self.archive_sheet, cell_range, checkbox_rule)
                
        else:
            self.logger.info("No completed orders to archive")
            return None, None
            
        # Step 2: Clear orders sheet and rewrite with active orders only
        self.orders_sheet.clear()
        
        # Rewrite headers and active orders to orders sheet
        rows_to_write = [headers] + active_orders
        if rows_to_write:
            self.orders_sheet.update(rows_to_write, value_input_option='USER_ENTERED')
            new_amount = len(active_orders) + 1
            self.logger.info(f"Kept {len(active_orders)} active orders in orders sheet")
            # Apply checkbox rule to the appended rows in the orders sheet
            checkbox_ranges = [f"A{2}:A{new_amount}", f"I{2}:I{new_amount}", f"J{2}:J{new_amount}"]
            for cell_range in checkbox_ranges:
                set_data_validation_for_cell_range(self.orders_sheet, cell_range, checkbox_rule)
        
        return len(completed_orders), len(active_orders)
# Refurbed-IdoSell Integration System

A comprehensive integration system that connects Refurbed and IdoSell APIs to automate order management, tracking, and synchronization through Google Sheets.

## Overview

This system serves as a bridge between Refurbed marketplace and IdoSell e-commerce platform, automating the order processing workflow. It uses Google Sheets as a central data store and provides both web interface and REST API endpoints for order management.

### Key Components:

- **Flask Web Application**: Provides GUI for manual actions and REST API
- **Refurbed API Integration**: Fetches and manages orders from Refurbed
- **IdoSell API Integration**: Creates and manages orders in IdoSell
- **Google Sheets Integration**: Central data management and configuration
- **Cloud Logging**: Structured logging for monitoring and debugging

## Features

### Order Management

- **Automated Order Fetching**: Retrieves new orders from Refurbed API
- **Order Creation**: Automatically creates corresponding orders in IdoSell
- **State Synchronization**: Keeps order states synchronized between platforms
- **Tracking Integration**: Manages tracking numbers and shipment status

### Data Management

- **Google Sheets Integration**: Uses spreadsheets for configuration, order storage and optional manual editing
- **Order Archiving**: Automatically archives completed orders
- **Backup System**: Maintains order backups for data integrity
- **Data Validation**: Ensures data consistency across platforms

### Automation Features

- **Batch Processing**: Handles multiple orders simultaneously
- **Scheduled Tasks**: Automated order processing workflows
- **State Updates**: Automatic status updates based on tracking information
- **Cancellation Handling**: Processes cancelled orders automatically

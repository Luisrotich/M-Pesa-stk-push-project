import os
import json
import requests
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from datetime import datetime
import base64

app = Flask(__name__)
CORS(app)  # allow frontend requests

# ============= CONFIGURATION =============
# IMPORTANT: Replace these with your actual Daraja credentials from Safaricom Sandbox
CONSUMER_KEY = os.environ.get('MPESA_CONSUMER_KEY', 'sJWMb8e5xwZ9APh9d8RAWt1VUjBEnmrM50bA8cBE4vwXxXwT')
CONSUMER_SECRET = os.environ.get('MPESA_CONSUMER_SECRET', 'AecUYi2w8e1Mrjd0tHFAK7Z9WQxKkBN09pXEGs3JM83EGp7ofCJs5PlCI7Jq3KUQ')
BUSINESS_SHORTCODE = os.environ.get('BUSINESS_SHORTCODE', '174379')  # default sandbox shortcode
PASSKEY = os.environ.get('MPESA_PASSKEY', 'bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919')
CALLBACK_URL = os.environ.get('CALLBACK_URL', 'https://mydomain.com/callback')  # Update with your callback URL

# Sandbox URLs
BASE_AUTH_URL = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
STK_PUSH_URL = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"

def get_access_token():
    """Get OAuth access token from Safaricom"""
    auth_string = f"{CONSUMER_KEY}:{CONSUMER_SECRET}"
    encoded_auth = base64.b64encode(auth_string.encode()).decode()
    headers = {"Authorization": f"Basic {encoded_auth}"}
    
    try:
        response = requests.get(BASE_AUTH_URL, headers=headers, timeout=15)
        response.raise_for_status()
        result = response.json()
        access_token = result.get('access_token')
        
        if not access_token:
            raise Exception("Token missing in response")
        
        print("✓ Access token obtained successfully")
        return access_token
    except Exception as e:
        print(f"✗ Token generation failed: {e}")
        raise

def generate_password(timestamp):
    """Generate password for STK push"""
    data_to_encode = BUSINESS_SHORTCODE + PASSKEY + timestamp
    return base64.b64encode(data_to_encode.encode()).decode('utf-8')

@app.route('/')
def index():
    """Serve the HTML frontend"""
    return send_file('index.html')

@app.route('/stkpush', methods=['POST'])
def stk_push():
    """Initiate STK Push to customer's phone"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid request, JSON required"}), 400
        
        amount = data.get('amount')
        phone = data.get('phone')
        
        # Validation
        if not amount or not phone:
            return jsonify({"error": "Amount and phone number are required"}), 400
        
        try:
            amount_int = int(float(amount))
            if amount_int < 1:
                return jsonify({"error": "Amount must be at least 1 KES"}), 400
            if amount_int > 150000:
                return jsonify({"error": "Amount cannot exceed 150,000 KES"}), 400
        except:
            return jsonify({"error": "Invalid amount format"}), 400
        
        # Format phone number to international format (254XXXXXXXX)
        phone_cleaned = ''.join(filter(str.isdigit, str(phone)))
        
        if len(phone_cleaned) == 9:
            phone_number = "254" + phone_cleaned
        elif len(phone_cleaned) == 12 and phone_cleaned.startswith('254'):
            phone_number = phone_cleaned
        elif len(phone_cleaned) == 10 and phone_cleaned.startswith('07'):
            phone_number = "254" + phone_cleaned[1:]
        else:
            return jsonify({"error": "Phone number must be 9 digits (e.g., 712345678)"}), 400
        
        # Validate Safaricom number
        if not (phone_number.startswith('2547') or phone_number.startswith('2541')):
            return jsonify({"error": "Only Safaricom numbers (starting with 2547 or 2541) are supported"}), 400
        
        print(f"✓ Processing payment: KES {amount_int} to {phone_number}")
        
        # Get access token
        token = get_access_token()
        
        # Generate timestamp and password
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        password = generate_password(timestamp)
        
        # Prepare STK push payload
        payload = {
            "BusinessShortCode": BUSINESS_SHORTCODE,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": amount_int,
            "PartyA": phone_number,
            "PartyB": BUSINESS_SHORTCODE,
            "PhoneNumber": phone_number,
            "CallBackURL": CALLBACK_URL,
            "AccountReference": f"Payment{timestamp}",
            "TransactionDesc": "Payment for goods/services"
        }
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        # Send STK push request
        print("📱 Sending STK push request...")
        response = requests.post(STK_PUSH_URL, json=payload, headers=headers, timeout=20)
        response_data = response.json()
        
        print(f"Response: {json.dumps(response_data, indent=2)}")
        
        # Return response to frontend
        if response.status_code == 200:
            resp_code = response_data.get('ResponseCode')
            
            if resp_code == '0':
                return jsonify({
                    "success": True,
                    "ResponseCode": "0",
                    "ResponseDescription": response_data.get('ResponseDescription', 'STK push sent successfully'),
                    "CheckoutRequestID": response_data.get('CheckoutRequestID'),
                    "MerchantRequestID": response_data.get('MerchantRequestID')
                }), 200
            else:
                error_desc = response_data.get('errorMessage') or response_data.get('ResponseDescription') or 'M-Pesa service error'
                return jsonify({
                    "success": False,
                    "ResponseCode": resp_code,
                    "error": error_desc
                }), 400
        else:
            return jsonify({
                "success": False,
                "error": f"Daraja API error: {response_data.get('errorMessage', response.text)}"
            }), response.status_code
            
    except requests.exceptions.Timeout:
        return jsonify({"error": "Request timeout. Please try again."}), 504
    except Exception as e:
        print(f"Exception: {str(e)}")
        return jsonify({"error": f"Server error: {str(e)}"}), 500

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({"status": "M-Pesa STK service running", "timestamp": datetime.now().isoformat()}), 200

if __name__ == '__main__':
    print("=" * 50)
    print("🚀 M-Pesa STK Push Server Starting...")
    print("=" * 50)
    print(f"📱 Business Shortcode: {BUSINESS_SHORTCODE}")
    print(f"🌐 Server running at: http://localhost:5000")
    print(f"⚠️  Make sure to update CONSUMER_KEY and CONSUMER_SECRET")
    print("=" * 50)
app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
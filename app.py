import os
from flask import Flask, request, jsonify, send_from_directory
from dotenv import load_dotenv
import requests
from twilio.rest import Client
from datetime import datetime
from dateutil import parser

load_dotenv()
app = Flask(__name__, static_url_path='/static')

TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = "whatsapp:+14155238886"  
twilio_client = Client(TWILIO_SID, TWILIO_AUTH_TOKEN)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

reservations_db = {}

SYSTEM_PROMPT = """
You are Paradise.ai — a friendly, professional assistant that helps guests with restaurant reservations and frequently asked questions.

🎯 Scope of Assistance:

* You can help with: making, modifying, rescheduling, or canceling reservations.
* You can answer FAQs about the restaurant, including: hours, location, menu, parking, dietary options.
* If a user asks something outside of this scope, respond with:
  "I'm sorry, but I can't help with that. I specialize in restaurant reservations and FAQs. How can I assist you with your booking or questions about our restaurant?"

📋 Response Guidelines:

1. For cancellation requests:
   - Ask for phone number or booking reference
   - Confirm cancellation
   - Send confirmation via WhatsApp

2. For rescheduling requests:
   - Ask for phone number or booking reference
   - Get new date and time
   - Confirm changes
   - Send updated details via WhatsApp

3. If the user's request lacks key details (e.g., date, time, party size), ask polite follow-up questions to gather missing info.
4. For reservation requests with more than 8 guests, reply with:
   "For parties over 8, please call us at [phone number] and we'll be happy to assist you."
5. If a user requests a booking on a day the restaurant is closed (e.g., Monday), suggest the next available day.
6. Always respond in a warm, concise, and helpful tone.
"""

@app.route('/')
def home():
    return send_from_directory('static', 'index.html')

def send_whatsapp_message(to_number, message_body):
    try:
        message = twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_FROM,
            body=message_body,
            to=f"whatsapp:{to_number}"
        )
        print("WhatsApp message sent:", message.sid)
        return True
    except Exception as e:
        print("Error sending WhatsApp message:", e)
        return False

def send_confirmation(reservation):
    message = f"Hi {reservation['name']}, your table for {reservation['people']} on {reservation['date']} at {reservation['time']} has been successfully booked. Thank you for choosing Paradise Restaurant!"
    sent = send_whatsapp_message(reservation['phone'], message)
    if sent:
        return "Confirmation sent!"
    else:
        return "Failed to send confirmation."

def find_reservation(phone):
    return reservations_db.get(phone)

@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    user_input = data.get("message", "")
    
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "mixtral-8x7b-32768",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_input}
        ],
        "temperature": 0.7
    }
    
    try:
        response = requests.post(GROQ_API_URL, headers=headers, json=payload)
        response.raise_for_status()
        reply = response.json()["choices"][0]["message"]["content"]
        return jsonify({"reply": reply})
    except Exception as e:
        print(f"Error calling Groq API: {str(e)}")
        return jsonify({"error": "Sorry, I'm having trouble processing your request. Please try again later."}), 500
@app.route('/reserve', methods=['POST'])
def reserve():
    data = request.json
    
    try:
        # Parse the natural language date into a proper format
        date_str = data.get("date")
        time_str = data.get("time")
        
        # Combine date and time and parse
        datetime_str = f"{date_str} {time_str}"
        dt = parser.parse(datetime_str)
        
        reservation = {
            "name": data.get("name"),
            "phone": data.get("phone"),
            "date": dt.strftime("%Y-%m-%d"),
            "time": dt.strftime("%H:%M"),
            "people": data.get("people"),
            "status": "confirmed",
            "created_at": datetime.now().isoformat()
        }

        reservations_db[reservation['phone']] = reservation
        confirmation_message = send_confirmation(reservation)

        if "Confirmation sent!" in confirmation_message:
            return jsonify({"message": "Reservation received and confirmation sent."}), 200
        else:
            return jsonify({"error": "Failed to send confirmation."}), 500
    except Exception as e:
        print(f"Error processing reservation: {str(e)}")
        return jsonify({"error": "Invalid date/time format. Please try again."}), 400

@app.route('/cancel', methods=['POST'])
def cancel_reservation():
    data = request.json
    phone = data.get("phone")
    
    reservation = find_reservation(phone)
    
    if reservation:
        reservation['status'] = 'cancelled'
        reservation['cancelled_at'] = datetime.now().isoformat()
        
        message = f"Hi {reservation['name']}, your reservation for {reservation['people']} people on {reservation['date']} at {reservation['time']} has been successfully cancelled. We hope to serve you another time!"
        sent = send_whatsapp_message(phone, message)
        
        if sent:
            return jsonify({"message": "Reservation cancelled and confirmation sent."}), 200
        else:
            return jsonify({"error": "Failed to send cancellation confirmation."}), 500
    else:
        return jsonify({"error": "No reservation found with that phone number."}), 404

@app.route('/reschedule', methods=['POST'])
def reschedule_reservation():
    try:
        data = request.json
        required_fields = ['phone', 'new_date', 'new_time']
        
        if not all(field in data for field in required_fields):
            return jsonify({"error": "Missing required fields (phone, new_date, new_time)"}), 400
        
        reservation = find_reservation(data['phone'])
        if not reservation:
            return jsonify({"error": "No reservation found with that phone number."}), 404
        
        # Update reservation
        old_date = reservation['date']
        old_time = reservation['time']
        
        reservation['date'] = data['new_date']
        reservation['time'] = data['new_time']
        reservation['updated_at'] = datetime.now().isoformat()
        
        # Send confirmation
        message = f"""Hi {reservation['name']},
Your reservation has been updated:
From: {old_date} at {old_time}
To: {reservation['date']} at {reservation['time']}
Thank you for choosing Paradise Restaurant!"""
        
        sent = send_whatsapp_message(data['phone'], message)
        
        if sent:
            return jsonify({"message": "Reservation rescheduled and confirmation sent."}), 200
        else:
            return jsonify({"error": "Failed to send reschedule confirmation."}), 500
    except Exception as e:
        print(f"Error in reschedule: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

if __name__ == '__main__':
    app.run(debug=True)

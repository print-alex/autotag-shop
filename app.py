from flask import Flask, request, jsonify
from sqlalchemy import and_
import requests
import re
import os
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Model baza de date (nemodificat)
class Vehicle(db.Model):
    # ... (la fel ca înainte)

@app.route("/webhook/products/create", methods=["POST"])
def handle_product_create():
    try:
        if not request.is_json:
            return jsonify({"error": "Unsupported media type"}), 415
            
        data = request.get_json()
        if not data or 'id' not in data:
            return jsonify({"error": "Invalid payload"}), 400

        product_id = data['id']
        title = data.get('title', '')
        
        vehicle_data = extract_vehicle_data(title)
        tags = get_vehicle_tags(vehicle_data)
        
        if tags:
            headers = {
                "Content-Type": "application/json",
                "X-Shopify-Access-Token": os.getenv("SHOPIFY_ACCESS_TOKEN")
            }
            response = requests.put(
                f"https://{os.getenv('SHOPIFY_DOMAIN')}/admin/api/2023-10/products/{product_id}.json",
                json={"product": {"id": product_id, "tags": ", ".join(tags)}},
                headers=headers
            )
            response.raise_for_status()
            
        return jsonify({"status": "success", "tags": tags}), 200

    except requests.exceptions.RequestException as e:
        app.logger.error(f"Shopify API error: {str(e)}")
        return jsonify({"error": "Failed to update product"}), 502
    except Exception as e:
        app.logger.error(f"Unexpected error: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

def get_vehicle_tags(vehicle_data):
    tags = set()
    required = ['brand', 'model', 'engine_code']
    
    if not all(vehicle_data.get(field) for field in required):
        return []
    
    try:
        vehicle = Vehicle.query.filter(
            and_(
                Vehicle.brand.ilike(vehicle_data['brand']),
                Vehicle.model.ilike(vehicle_data['model']),
                Vehicle.engine_code.ilike(vehicle_data['engine_code'])
            )
        ).first()
        
        if vehicle:
            tags.update([
                vehicle.brand,
                vehicle.model,
                vehicle.engine_code,
                f"{vehicle.brand} {vehicle.model}",
                vehicle.engine_name,
                vehicle.fuel_type
            ])
            
            if vehicle.generation:
                tags.add(vehicle.generation)
                
        return list(tags)
        
    except Exception as e:
        app.logger.error(f"Database error: {str(e)}")
        return []

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5002, debug=os.getenv('FLASK_DEBUG', False))

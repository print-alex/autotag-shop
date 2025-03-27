from flask import Flask, request, jsonify
import requests
import re
import os
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv

# Configurare aplicație și bază de date
app = Flask(__name__)
load_dotenv()

app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///vehicles.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Model baza de date
class Vehicle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    brand = db.Column(db.String(50), nullable=False)
    model = db.Column(db.String(50), nullable=False)
    generation = db.Column(db.String(50))
    engine_code = db.Column(db.String(50), nullable=False)
    engine_name = db.Column(db.String(100))
    fuel_type = db.Column(db.String(20))
    displacement = db.Column(db.String(20))
    power = db.Column(db.String(20))

# Inițializare baza de date
with app.app_context():
    db.create_all()

# Configurare Shopify
SHOPIFY_DOMAIN = os.getenv("SHOPIFY_DOMAIN")
ACCESS_TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN")

def normalize_text(text):
    """Normalizează textul pentru comparații sigure"""
    return re.sub(r'\W+', ' ', text).strip().lower()

def extract_vehicle_data(title):
    """Extrage date despre vehicul folosind expresii regulate"""
    patterns = {
        'brand': r'\b(BMW|Audi|VW|Volkswagen|Ford|Opel|Dacia)\b',
        'model': r'\b(E90|Golf|A4|Focus|Duster|Astra)\b',
        'generation': r'\b(MK[IVXLCDM]+|B\d+|G\d+)\b',
        'engine': r'\b(\d+\.\d+\s*[TLS]?[FS]?I|dCi|TDI|HDi)\b',
        'engine_code': r'\b(N47|BKC|CAGA|K9K)\b'
    }
    
    result = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, title, re.IGNORECASE)
        result[key] = normalize_text(match.group(0)) if match else None
    
    return result

def get_vehicle_tags(vehicle_data):
    """Generează etichete bazate pe datele vehiculului"""
    tags = set()
    vehicle = Vehicle.query.filter(
        (Vehicle.brand.ilike(vehicle_data['brand'])) &
        (Vehicle.model.ilike(vehicle_data['model'])) &
        (Vehicle.engine_code.ilike(vehicle_data['engine_code']))
    ).first()

    if vehicle:
        tags.add(vehicle.brand)
        tags.add(vehicle.model)
        tags.add(vehicle.engine_name)
        tags.add(f"{vehicle.brand} {vehicle.model}")
        tags.add(f"{vehicle.engine_code}")
        tags.add(f"{vehicle.fuel_type}")
        tags.add(f"{vehicle.displacement}")
        
        if vehicle.generation:
            tags.add(vehicle.generation)
            tags.add(f"{vehicle.brand} {vehicle.model} {vehicle.generation}")
        
    return list(tags)

@app.route("/webhook/products/create", methods=["POST"])
def handle_product_create():
    try:
        data = request.get_json()
        if not data or 'id' not in data:
            return jsonify({"error": "Invalid request"}), 400

        product_id = data['id']
        title = data.get('title', '')
        
        # Extrage și procesează date
        vehicle_data = extract_vehicle_data(title)
        tags = get_vehicle_tags(vehicle_data)
        
        # Actualizează produsul în Shopify
        if tags:
            headers = {
                "Content-Type": "application/json",
                "X-Shopify-Access-Token": ACCESS_TOKEN
            }
            payload = {
                "product": {
                    "id": product_id,
                    "tags": ", ".join(tags)
                }
            }
            response = requests.put(
                f"https://{SHOPIFY_DOMAIN}/admin/api/2023-10/products/{product_id}.json",
                json=payload,
                headers=headers
            )
            response.raise_for_status()
            
        return jsonify({"status": "success", "tags": tags}), 200

    except requests.exceptions.RequestException as e:
        app.logger.error(f"Shopify API error: {str(e)}")
        return jsonify({"error": "Failed to update product"}), 500
    except Exception as e:
        app.logger.error(f"Unexpected error: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route("/")
def home():
    return "Vehicle AutoTagger Service"

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5002, debug=os.getenv('FLASK_DEBUG', False))

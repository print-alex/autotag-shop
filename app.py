from flask import Flask, request, jsonify
import requests
import re
import os
import hmac
import hashlib
import base64
import json
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
    type = db.Column(db.String(50))

# Inițializare baza de date (fără date mock)
with app.app_context():
    db.create_all()

# Încărcare configurație din fișier
CONFIG_PATH = os.getenv('CONFIG_PATH', 'config.json')
try:
    with open(CONFIG_PATH, 'r') as config_file:
        config = json.load(config_file)
except FileNotFoundError:
    app.logger.error(f"Config file not found at {CONFIG_PATH}. Using default configuration.")
    config = {
        "patterns": {
            "brand": r'\b[A-Z][a-zA-Z]+\b',  # Generic pattern for brand names
            "model": r'\b[A-Z0-9-]+\b',      # Generic pattern for models
            "generation": r'\b(MK[IVXLCDM]+|[A-Z]\d+)\b',
            "engine": r'\b\d+\.\d+\s*[A-Za-z]*\b',
            "engine_code": r'\b[A-Z0-9]{3,6}\b',
            "type": r'\b[A-Z0-9]+\s*\d+\.\d+[A-Za-z]*\b'
        },
        "non_vehicle_keywords": ["shirt", "book", "phone", "laptop", "jacket", "toy"]
    }

# Configurare Shopify
SHOPIFY_DOMAIN = os.getenv("SHOPIFY_DOMAIN")
ACCESS_TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN")
SHOPIFY_SECRET = os.getenv("SHOPIFY_SECRET")  # Webhook secret for verification

def verify_webhook(data, hmac_header):
    """Verify the Shopify webhook signature"""
    digest = hmac.new(
        SHOPIFY_SECRET.encode('utf-8'),
        data,
        hashlib.sha256
    ).digest()
    computed_hmac = base64.b64encode(digest).decode('utf-8')
    return hmac.compare_digest(computed_hmac, hmac_header)

def normalize_text(text):
    """Normalize text for safe comparisons"""
    if not text:
        return None
    return re.sub(r'\W+', ' ', text).strip().lower()

def extract_vehicle_data(title):
    """Extract vehicle data using configurable regex patterns"""
    app.logger.info(f"Processing product title: '{title}'")
    if not title or any(keyword in title.lower() for keyword in config['non_vehicle_keywords']):
        app.logger.info("Skipping non-vehicle product title")
        return {'brand': None, 'model': None, 'generation': None, 'engine': None, 'engine_code': None, 'type': None}

    patterns = config['patterns']
    result = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, title, re.IGNORECASE)
        result[key] = normalize_text(match.group(0)) if match else None
    
    # Fallback logic to guess fields if patterns don't match
    if not result.get('brand') or not result.get('model') or not result.get('type'):
        words = title.split()
        for i, word in enumerate(words):
            if not result.get('brand') and re.match(patterns['brand'], word, re.IGNORECASE):
                result['brand'] = normalize_text(word)
            elif (result.get('brand') or i > 0) and not result.get('model') and re.match(patterns['model'], word, re.IGNORECASE):
                result['model'] = normalize_text(word)
            elif not result.get('type') and re.match(patterns['type'], word + (f" {words[i+1]}" if i+1 < len(words) else ""), re.IGNORECASE):
                result['type'] = normalize_text(word + (f" {words[i+1]}" if i+1 < len(words) else ""))
            elif not result.get('engine') and re.match(patterns['engine'], word, re.IGNORECASE):
                result['engine'] = normalize_text(word)
            elif not result.get('engine_code') and re.match(patterns['engine_code'], word, re.IGNORECASE):
                result['engine_code'] = normalize_text(word)
    
    app.logger.info(f"Extracted vehicle data: {result}")
    return result

def get_vehicle_tags(vehicle_data):
    """Generate tags based on vehicle data"""
    tags = set()
    app.logger.info(f"vehicle_data in get_vehicle_tags: {vehicle_data}")

    required_fields = ['brand', 'model', 'type']
    if not all(vehicle_data.get(field) for field in required_fields):
        app.logger.warning(f"Skipping query due to missing vehicle data: {vehicle_data}")
        return list(tags)

    vehicle = Vehicle.query.filter(
        (Vehicle.brand.ilike(vehicle_data['brand'])) &
        (Vehicle.model.ilike(vehicle_data['model'])) &
        (Vehicle.type.ilike(vehicle_data['type']))
    ).first()

    if vehicle:
        tags.add(vehicle.brand)
        tags.add(vehicle.model)
        tags.add(vehicle.type)
        tags.add(f"{vehicle.brand} {vehicle.model}")
        tags.add(f"{vehicle.brand} {vehicle.model} {vehicle.type}")
        if vehicle.engine_code:
            tags.add(vehicle.engine_code)
        if vehicle.fuel_type:
            tags.add(vehicle.fuel_type)
        if vehicle.displacement:
            tags.add(vehicle.displacement)
        if vehicle.generation:
            tags.add(vehicle.generation)
    else:
        # If no vehicle is found in the database, use extracted data to generate basic tags
        tags.add(vehicle_data['brand'])
        tags.add(vehicle_data['model'])
        tags.add(vehicle_data['type'])
        tags.add(f"{vehicle_data['brand']} {vehicle_data['model']}")
        tags.add(f"{vehicle_data['brand']} {vehicle_data['model']} {vehicle_data['type']}")
        if vehicle_data.get('engine_code'):
            tags.add(vehicle_data['engine_code'])
        if vehicle_data.get('fuel_type'):
            tags.add(vehicle_data['fuel_type'])
        if vehicle_data.get('displacement'):
            tags.add(vehicle_data['displacement'])
        if vehicle_data.get('generation'):
            tags.add(vehicle_data['generation'])
        
    return list(tags)

def create_or_update_collection(collection_title, tag):
    """Create or update a Shopify collection based on a tag"""
    headers = {
        "Content-Type": "application/json",
        "X-Shopify-Access-Token": ACCESS_TOKEN
    }
    response = requests.get(
        f"https://{SHOPIFY_DOMAIN}/admin/api/2023-10/custom_collections.json",
        headers=headers
    )
    response.raise_for_status()
    collections = response.json().get('custom_collections', [])

    collection_id = None
    for collection in collections:
        if collection['title'] == collection_title:
            collection_id = collection['id']
            break

    payload = {
        "custom_collection": {
            "title": collection_title,
            "collects": [],
            "rule_set": {
                "applied_disjunctively": False,
                "rules": [
                    {
                        "column": "tag",
                        "relation": "equals",
                        "condition": tag
                    }
                ]
            }
        }
    }

    if collection_id:
        response = requests.put(
            f"https://{SHOPIFY_DOMAIN}/admin/api/2023-10/custom_collections/{collection_id}.json",
            json=payload,
            headers=headers
        )
    else:
        response = requests.post(
            f"https://{SHOPIFY_DOMAIN}/admin/api/2023-10/custom_collections.json",
            json=payload,
            headers=headers
        )
    response.raise_for_status()
    return response.json()['custom_collection']['id']

def add_product_to_collection(product_id, collection_id):
    """Add a product to a Shopify collection"""
    headers = {
        "Content-Type": "application/json",
        "X-Shopify-Access-Token": ACCESS_TOKEN
    }
    payload = {
        "collect": {
            "product_id": product_id,
            "collection_id": collection_id
        }
    }
    response = requests.post(
        f"https://{SHOPIFY_DOMAIN}/admin/api/2023-10/collects.json",
        json=payload,
        headers=headers
    )
    response.raise_for_status()

@app.route("/webhook/products/create", methods=["POST"])
def handle_product_create():
    """Handle Shopify product creation webhook"""
    app.logger.info("Received webhook request for product creation")
    
    # Verify the webhook
    hmac_header = request.headers.get('X-Shopify-Hmac-Sha256')
    if not hmac_header:
        app.logger.error("Missing X-Shopify-Hmac-Sha256 header")
        return jsonify({"error": "Missing HMAC header"}), 401

    data = request.get_data()
    if not verify_webhook(data, hmac_header):
        app.logger.error("Webhook verification failed")
        return jsonify({"error": "Webhook verification failed"}), 401

    try:
        data = request.get_json()
        app.logger.info(f"Webhook data: {data}")
        if not data or 'id' not in data:
            app.logger.error("Invalid request: Missing product ID")
            return jsonify({"error": "Invalid request"}), 400

        product_id = data['id']
        title = data.get('title', '')
        
        vehicle_data = extract_vehicle_data(title)
        tags = get_vehicle_tags(vehicle_data)
        app.logger.info(f"Generated tags: {tags}")
        
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
            app.logger.info(f"Updated product {product_id} with tags: {tags}")

            for tag in tags:
                if " " in tag:
                    collection_title = f"{tag} Parts"
                    collection_id = create_or_update_collection(collection_title, tag)
                    add_product_to_collection(product_id, collection_id)
                    app.logger.info(f"Added product {product_id} to collection: {collection_title}")
            
        return jsonify({"status": "success", "tags": tags}), 200

    except requests.exceptions.RequestException as e:
        app.logger.error(f"Shopify API error: {str(e)}")
        return jsonify({"error": "Failed to update product"}), 500
    except Exception as e:
        app.logger.error(f"Unexpected error: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route("/")
def home():
    """Basic health check endpoint"""
    app.logger.info("Accessing home route")
    return "Vehicle AutoTagger Service"

if __name__ == "__main__":
    port = int(os.getenv('PORT', 5002))
    app.run(host='0.0.0.0', port=port, debug=os.getenv('FLASK_DEBUG', 'False') == 'True')

from flask import Flask, request, jsonify, render_template_string
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
STOREFRONT_ACCESS_TOKEN = os.getenv("SHOPIFY_STOREFRONT_ACCESS_TOKEN")  # Needed for Storefront API

def normalize_text(text):
    """Normalizează textul pentru comparații sigure"""
    if not text:
        return None
    return re.sub(r'\W+', ' ', text).strip().lower()

def extract_vehicle_data(title):
    """Extrage date despre vehicul folosind expresii regulate"""
    # Log the product title for debugging
    app.logger.info(f"Processing product title: '{title}'")

    # If the title is empty or clearly not vehicle-related, skip processing
    if not title or any(keyword in title.lower() for keyword in ['shirt', 'book', 'phone', 'laptop', 'jacket', 'toy']):
        app.logger.info("Skipping non-vehicle product title")
        return {'brand': None, 'model': None, 'generation': None, 'engine': None, 'engine_code': None}

    # Expanded patterns to match more brands, models, etc.
    patterns = {
        'brand': r'\b(BMW|Audi|VW|Volkswagen|Ford|Opel|Dacia|Mercedes|Toyota|Honda|Peugeot|Renault|Skoda|Seat|Hyundai|Kia|Nissan|Mitsubishi|Lexus|Chevrolet|Porsche|Volvo|Citroen|Mazda|Subaru|Jeep|Land Rover)\b',
        'model': r'\b(E90|E46|E39|E60|E36|Golf|A4|A6|A3|Focus|Duster|Astra|C-Class|E-Class|S-Class|Corolla|Civic|Clio|Megane|Octavia|Ibiza|Tucson|Sportage|Skyline|Supra|RX|Camry|Accord|Fiesta|Passat|Leon|Fabia|Kona|Santa Fe|Outlander|Impreza|Wrangler|Range Rover)\b',
        'generation': r'\b(MK[IVXLCDM]+|B\d+|G\d+|W\d+|F\d+|E\d+)\b',
        'engine': r'\b(\d+\.\d+\s*(TFSI|TSI|TDI|HDi|dCi|[TLS]?[FS]?I)?)\b',
        'engine_code': r'\b(N47|BKC|CAGA|K9K|CDNA|OM642|K4M|EA888|M54|M62|B58|S55|4JJ1|1KD|2JZ|RB26)\b'
    }
    
    result = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, title, re.IGNORECASE)
        result[key] = normalize_text(match.group(0)) if match else None
    
    # Fallback: If brand or model is None, try a more general approach
    if not result.get('brand') or not result.get('model'):
        words = title.split()
        for i, word in enumerate(words):
            # Try to guess the brand (word that looks like a brand name)
            if not result.get('brand') and re.match(r'^[A-Z][a-zA-Z]+$', word):
                result['brand'] = normalize_text(word)
            # Try to guess the model (next word after brand or a word with numbers/letters)
            elif (result.get('brand') or i > 0) and not result.get('model') and re.match(r'^[A-Z0-9-]+$', word):
                result['model'] = normalize_text(word)
            # Try to guess the engine if not found (look for a number like 2.0)
            elif not result.get('engine') and re.match(r'^\d+\.\d+$', word):
                result['engine'] = normalize_text(word)
            # Try to guess the engine code (word with letters and numbers)
            elif not result.get('engine_code') and re.match(r'^[A-Z0-9]{3,6}$', word):
                result['engine_code'] = normalize_text(word)
    
    # Log the extracted data
    app.logger.info(f"Extracted vehicle data: {result}")
    return result

def get_vehicle_tags(vehicle_data):
    """Generează etichete bazate pe datele vehiculului"""
    tags = set()

    # Log the vehicle_data for debugging
    app.logger.info(f"vehicle_data in get_vehicle_tags: {vehicle_data}")

    # Check if required fields are None; if so, return empty tags
    required_fields = ['brand', 'model', 'engine_code']
    if not all(vehicle_data.get(field) for field in required_fields):
        app.logger.warning(f"Skipping query due to missing vehicle data: {vehicle_data}")
        return list(tags)  # Return empty tags if any required field is missing

    # Now we know all required fields are non-None, so the query should be safe
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

def create_or_update_collection(collection_title, tag):
    """Create or update a Shopify collection based on a tag"""
    headers = {
        "Content-Type": "application/json",
        "X-Shopify-Access-Token": ACCESS_TOKEN
    }

    # Check if the collection already exists
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

    # Create or update the collection
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
        # Update existing collection
        response = requests.put(
            f"https://{SHOPIFY_DOMAIN}/admin/api/2023-10/custom_collections/{collection_id}.json",
            json=payload,
            headers=headers
        )
    else:
        # Create new collection
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

            # Create or update collections based on tags
            for tag in tags:
                if " " in tag:  # e.g., "BMW E90"
                    collection_title = f"{tag} Parts"
                    collection_id = create_or_update_collection(collection_title, tag)
                    add_product_to_collection(product_id, collection_id)
            
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

# Front-end route for vehicle selection and product filtering
@app.route("/vehicle-selector", methods=["GET", "POST"])
def vehicle_selector():
    # Get all unique brands and models from the database
    brands = db.session.query(Vehicle.brand).distinct().all()
    brands = [brand[0] for brand in brands if brand[0]]
    models = []
    selected_brand = request.form.get("brand") if request.method == "POST" else None

    if selected_brand:
        models = db.session.query(Vehicle.model).filter(Vehicle.brand == selected_brand).distinct().all()
        models = [model[0] for model in models if model[0]]

    # If a brand and model are selected, fetch products from Shopify using Storefront API
    products = []
    if request.method == "POST" and selected_brand and request.form.get("model"):
        selected_model = request.form.get("model")
        tag = f"{selected_brand} {selected_model}".lower()

        # Use Shopify Storefront API to fetch products with the tag
        query = """
        {
          products(first: 10, query: "tag:%s") {
            edges {
              node {
                id
                title
                handle
                priceRange {
                  minVariantPrice {
                    amount
                    currencyCode
                  }
                }
              }
            }
          }
        }
        """ % tag

        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Storefront-Access-Token": STOREFRONT_ACCESS_TOKEN
        }
        response = requests.post(
            f"https://{SHOPIFY_DOMAIN}/api/2023-10/graphql.json",
            json={"query": query},
            headers=headers
        )
        response.raise_for_status()
        products_data = response.json().get('data', {}).get('products', {}).get('edges', [])
        products = [edge['node'] for edge in products_data]

    # Render the vehicle selector form and product list
    html_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Vehicle Part Selector</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; }
            .form-group { margin-bottom: 15px; }
            .product { border: 1px solid #ddd; padding: 10px; margin: 10px 0; }
        </style>
    </head>
    <body>
        <h1>Find Parts for Your Vehicle</h1>
        <form method="POST">
            <div class="form-group">
                <label for="brand">Select Brand:</label>
                <select name="brand" id="brand" onchange="this.form.submit()">
                    <option value="">-- Select Brand --</option>
                    {% for brand in brands %}
                        <option value="{{ brand }}" {% if selected_brand == brand %}selected{% endif %}>{{ brand }}</option>
                    {% endfor %}
                </select>
            </div>
            {% if models %}
            <div class="form-group">
                <label for="model">Select Model:</label>
                <select name="model" id="model" onchange="this.form.submit()">
                    <option value="">-- Select Model --</option>
                    {% for model in models %}
                        <option value="{{ model }}">{{ model }}</option>
                    {% endfor %}
                </select>
            </div>
            {% endif %}
        </form>
        {% if products %}
        <h2>Compatible Parts</h2>
        {% for product in products %}
            <div class="product">
                <h3>{{ product.title }}</h3>
                <p>Price: {{ product.priceRange.minVariantPrice.amount }} {{ product.priceRange.minVariantPrice.currencyCode }}</p>
                <a href="https://{{ shopify_domain }}/products/{{ product.handle }}">View Product</a>
            </div>
        {% endfor %}
        {% endif %}
    </body>
    </html>
    """
    return render_template_string(html_template, brands=brands, models=models, selected_brand=selected_brand, products=products, shopify_domain=SHOPIFY_DOMAIN)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5002, debug=os.getenv('FLASK_DEBUG', False))

from flask import Flask, request, jsonify
import requests
import re
import os

app = Flask(__name__)

# Get Shopify credentials from environment variables
SHOPIFY_DOMAIN = os.getenv("SHOPIFY_DOMAIN")
ACCESS_TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN")

# Example database of models and tags
MODEL_DATABASE = [
    ("BMW", "E90", "320d", "N47"),
    ("VW", "Golf 5", "1.9 TDI", "BKC"),
    ("Audi", "A4 B8", "2.0 TDI", "CAGA"),
    ("Ford", "Focus MK2", "1.6 TDCi", "HHDA"),
    ("Dacia", "Duster", "1.5 dCi", "K9K"),
    ("Opel", "Astra J", "1.4 Turbo", "A14NEL"),
]

def extract_tags(title):
    """Extract tags based on product title and model database."""
    tags = set()
    for brand, model, engine, code in MODEL_DATABASE:
        if all(x.lower() in title.lower() for x in [brand, model, engine]):
            tags.update([
                brand, model, engine,
                f"{brand} {model}",
                f"{brand} {engine}",
                f"{brand} {model} {engine}",
                code
            ])
    return list(tags)

@app.route("/webhook/products/create", methods=["POST"])
def handle_new_product():
    """Handle the webhook when a new product is created."""
    data = request.get_json()
    product_id = data["id"]
    title = data.get("title", "")

    tags_to_add = extract_tags(title)
    if tags_to_add:
        tag_string = ", ".join(tags_to_add)
        update_url = f"https://{SHOPIFY_DOMAIN}/admin/api/2023-10/products/{product_id}.json"
        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": ACCESS_TOKEN
        }
        payload = {
            "product": {
                "id": product_id,
                "tags": tag_string
            }
        }
        response = requests.put(update_url, json=payload, headers=headers)
        return jsonify({"status": "tags updated", "tags": tags_to_add}), response.status_code
    else:
        return jsonify({"status": "no matching tags found"}), 200

@app.route("/")
def home():
    return "AutoTag Shopify App is running."

if __name__ == "__main__":
    app.run(port=5002)

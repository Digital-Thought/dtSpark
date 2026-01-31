"""Debug script to examine AWS Bulk Price List structure."""

import requests
import json

url = "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonBedrockService/current/index.json"

print("Fetching Bedrock pricing from Bulk API...")
response = requests.get(url, timeout=30)
response.raise_for_status()

pricing_json = response.json()

print("\nTop-level keys:")
for key in pricing_json.keys():
    print(f"  - {key}")

# Examine products
products = pricing_json.get('products', {})
print(f"\nNumber of products: {len(products)}")

# Look at first few products
print("\nFirst 5 products:")
for i, (sku, product) in enumerate(list(products.items())[:5]):
    print(f"\n  Product {i+1} (SKU: {sku}):")
    attributes = product.get('attributes', {})
    print("    Attributes:")
    for key, value in list(attributes.items())[:10]:
        print(f"      {key}: {value}")

# Check product families
product_families = set()
for sku, product in products.items():
    family = product.get('attributes', {}).get('productFamily')
    if family:
        product_families.add(family)

print("\nProduct families found:")
for family in sorted(product_families):
    count = sum(1 for p in products.values() if p.get('attributes', {}).get('productFamily') == family)
    print(f"  - {family}: {count} products")

# Look for Model Inference products specifically
print("\nModel Inference products:")
inference_products = {sku: p for sku, p in products.items()
                     if p.get('attributes', {}).get('productFamily') == 'Model Inference'}
print(f"Found {len(inference_products)} Model Inference products")

if inference_products:
    print("\nFirst Model Inference product:")
    sku, product = list(inference_products.items())[0]
    print(f"  SKU: {sku}")
    print("  Attributes:")
    for key, value in product.get('attributes', {}).items():
        print(f"    {key}: {value}")

# Check terms
terms = pricing_json.get('terms', {})
print(f"\nTerms keys: {list(terms.keys())}")

on_demand = terms.get('OnDemand', {})
print(f"OnDemand terms: {len(on_demand)} SKUs")

if on_demand:
    # Look at first term
    first_sku = list(on_demand.keys())[0]
    print(f"\nFirst OnDemand term (SKU: {first_sku}):")
    term_data = on_demand[first_sku]
    for term_key, term_value in list(term_data.items())[:1]:
        print(f"  Term key: {term_key}")
        price_dims = term_value.get('priceDimensions', {})
        print(f"  Price dimensions: {len(price_dims)}")
        for dim_key, dim_value in list(price_dims.items())[:1]:
            print(f"    Dimension key: {dim_key}")
            print(f"    Unit: {dim_value.get('unit')}")
            print(f"    Price per unit: {dim_value.get('pricePerUnit')}")
            print(f"    Description: {dim_value.get('description')}")

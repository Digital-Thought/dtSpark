"""
Integration test for pricing module with actual running directory.
"""

import sys
from pathlib import Path

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from dtSpark.pricing import BedrockPricing


def test_pricing_integration():
    """Test pricing with actual running directory."""
    print("Testing Bedrock Pricing Integration")
    print("=" * 70)

    # Use actual running directory
    running_dir = Path(__file__).parent.parent / 'running'

    # Create pricing manager (no boto3 client needed for Bulk API)
    pricing = BedrockPricing(pricing_client=None, data_path=running_dir)

    # Load pricing data
    success = pricing.load_pricing_data()

    print("\n1. Pricing initialization:")
    print("   [OK] Pricing manager created")
    print(f"   [OK] Cache directory: {running_dir}")
    print(f"   [OK] Pricing loaded: {success}")
    print(f"   [OK] Found {len(pricing.pricing_data)} model/region combinations")

    # Test with Claude Sonnet 4 (should be in Bulk API)
    print("\n2. Testing Claude Sonnet 4 (from Bulk API):")
    model_id = "anthropic.claude-sonnet-4-0-v1:0"
    region = "us-east-1"

    cost, source = pricing.calculate_cost(model_id, region, 1000, 500)
    print(f"   Model: {model_id}")
    print(f"   Region: {region}")
    print(f"   Cost for 1000 input + 500 output tokens: ${cost:.4f}")
    print(f"   Source: {source}")

    # Test with Claude 3.5 Sonnet v2 (should fall back to hardcoded)
    print("\n3. Testing Claude 3.5 Sonnet v2 (fallback pricing):")
    model_id = "anthropic.claude-3-5-sonnet-20241022-v2:0"
    region = "ap-southeast-2"

    cost, source = pricing.calculate_cost(model_id, region, 1000, 500)
    print(f"   Model: {model_id}")
    print(f"   Region: {region}")
    print(f"   Cost for 1000 input + 500 output tokens: ${cost:.4f}")
    print(f"   Source: {source}")

    # Check cache file
    print("\n4. Checking cache file:")
    cache_file = running_dir / "bedrock_pricing.json"
    if cache_file.exists():
        print(f"   [OK] Cache file created at: {cache_file}")
        import json
        with open(cache_file) as f:
            cache_data = json.load(f)
        print(f"   [OK] Cache contains {len(cache_data.get('pricing', {}))} entries")
        print(f"   [OK] Last updated: {cache_data.get('last_updated')}")
    else:
        print(f"   [FAIL] Cache file not found at: {cache_file}")

    print("\n" + "=" * 70)
    print("Integration test complete")


if __name__ == '__main__':
    test_pricing_integration()

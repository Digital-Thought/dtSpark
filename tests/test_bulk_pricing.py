"""
Test script to verify AWS Bulk Price List API fetching and parsing.
"""

import sys
import tempfile
import json
from pathlib import Path

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from dtSpark.pricing import BedrockPricing


def _show_sample_pricing(pricing):
    """Display sample pricing data entries."""
    print("\n2. Sample pricing data:")
    count = 0
    for (model_id, region), prices in pricing.pricing_data.items():
        if count < 10:  # Show first 10
            print(f"   - {model_id} in {region}:")
            print(f"     Input:  ${prices['input']:.6f} per 1K tokens")
            print(f"     Output: ${prices['output']:.6f} per 1K tokens")
            count += 1
        else:
            break


def _test_cost_calculation(pricing):
    """Test cost calculation with a Claude model."""
    print("\n3. Testing cost calculation...")
    claude_model = None
    for (model_id, region) in pricing.pricing_data.keys():
        if 'claude' in model_id.lower():
            claude_model = (model_id, region)
            break

    if claude_model:
        model_id, region = claude_model
        cost, source = pricing.calculate_cost(model_id, region, 1000, 500)
        print(f"   [OK] {model_id} in {region}:")
        print(f"     1000 input + 500 output tokens = ${cost:.4f}")
        print(f"     Source: {source}")
    else:
        print("   No Claude models found for testing")


def _check_cache_file(tmpdir):
    """Check the pricing cache file was created correctly."""
    print("\n4. Checking cache file...")
    cache_file = Path(tmpdir) / "bedrock_pricing.json"
    if cache_file.exists():
        with open(cache_file) as f:
            cache_data = json.load(f)
        print("   [OK] Cache file created")
        print(f"   [OK] Contains {len(cache_data.get('pricing', {}))} entries")
        print(f"   [OK] Last updated: {cache_data.get('last_updated')}")
    else:
        print("   [FAIL] Cache file not created")


def test_bulk_pricing():
    """Test fetching and parsing from Bulk API."""
    print("Testing AWS Bulk Price List API...")
    print("=" * 70)

    # Create temporary directory for test
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a mock pricing client (won't be used if Bulk API works)
        pricing_client = None

        # Create pricing manager
        pricing = BedrockPricing(pricing_client, Path(tmpdir))

        # Try to fetch pricing
        print("\n1. Fetching pricing from Bulk API...")
        success = pricing._fetch_from_bulk_api()

        if success:
            print("   [OK] Successfully fetched pricing")
            print(f"   [OK] Found {len(pricing.pricing_data)} model/region combinations")

            _show_sample_pricing(pricing)
            _test_cost_calculation(pricing)
            _check_cache_file(tmpdir)

        else:
            print("   [FAIL] Failed to fetch pricing from Bulk API")
            print("   Fallback pricing will be used")

    print("\n" + "=" * 70)
    print("Test complete")


if __name__ == '__main__':
    test_bulk_pricing()

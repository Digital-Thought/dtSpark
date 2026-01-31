"""
Diagnostic script to troubleshoot AWS Cost Explorer and Pricing API.

This script helps identify:
- What service names Cost Explorer uses for Bedrock
- Whether Bedrock costs are being tracked
- What pricing data is available
"""

import boto3
from datetime import datetime, timedelta
import json


def _extract_services_with_costs(response):
    """Extract services with non-zero costs from a Cost Explorer response."""
    services = []
    for result in response.get('ResultsByTime', []):
        for group in result.get('Groups', []):
            service_name = group.get('Keys', ['Unknown'])[0]
            cost = float(group.get('Metrics', {}).get('UnblendedCost', {}).get('Amount', '0'))
            if cost > 0:
                services.append((service_name, cost))
    return services


def _print_bedrock_services(bedrock_services):
    """Print found Bedrock services."""
    print("   Found Bedrock services:")
    for service_name, cost in bedrock_services:
        print(f"   - {service_name}: ${cost:.2f}")


def _check_bedrock_variations(ce_client, first_day_last_month, first_day_this_month):
    """Check alternative Bedrock service name variations in Cost Explorer."""
    print("   No services with 'bedrock' in the name found")
    print("   Checking alternative names...")

    variations = ['Amazon Bedrock', 'AWS Bedrock', 'Bedrock', 'Amazon Bedrock Runtime']
    for variation in variations:
        try:
            test_response = ce_client.get_cost_and_usage(
                TimePeriod={
                    'Start': first_day_last_month.strftime('%Y-%m-%d'),
                    'End': first_day_this_month.strftime('%Y-%m-%d')
                },
                Granularity='MONTHLY',
                Filter={
                    'Dimensions': {
                        'Key': 'SERVICE',
                        'Values': [variation]
                    }
                },
                Metrics=['UnblendedCost']
            )

            total = 0.0
            for result in test_response.get('ResultsByTime', []):
                amount = result.get('Total', {}).get('UnblendedCost', {}).get('Amount', '0')
                total += float(amount)

            if total > 0:
                print(f"   '{variation}': ${total:.2f}")
            else:
                print(f"   '{variation}': $0.00")
        except Exception as e:
            print(f"   '{variation}': Error - {e}")


def _check_last_24_hours(ce_client, yesterday, today):
    """Check services with costs in the last 24 hours."""
    print("\n3. Checking last 24 hours")
    print(f"   Period: {yesterday} to {today}")

    response_24h = ce_client.get_cost_and_usage(
        TimePeriod={
            'Start': yesterday.strftime('%Y-%m-%d'),
            'End': today.strftime('%Y-%m-%d')
        },
        Granularity='DAILY',
        Metrics=['UnblendedCost'],
        GroupBy=[{
            'Type': 'DIMENSION',
            'Key': 'SERVICE'
        }]
    )

    services_24h = _extract_services_with_costs(response_24h)

    if services_24h:
        services_24h.sort(key=lambda x: x[1], reverse=True)
        print("   Services with costs in last 24h:")
        for service_name, cost in services_24h[:10]:
            print(f"   - {service_name}: ${cost:.4f}")
    else:
        print("   No costs in last 24 hours (may be due to reporting delay)")


def diagnose_cost_explorer(region='ap-southeast-2', profile='default'):
    """Diagnose Cost Explorer service names and costs."""
    print("=" * 70)
    print("AWS Cost Explorer Diagnostics")
    print("=" * 70)

    try:
        session = boto3.Session(profile_name=profile, region_name=region)
        ce_client = session.client('ce', region_name='us-east-1')  # CE is only in us-east-1

        # Get date ranges
        today = datetime.now().date()
        yesterday = today - timedelta(days=1)
        first_day_this_month = today.replace(day=1)
        last_day_last_month = first_day_this_month - timedelta(days=1)
        first_day_last_month = last_day_last_month.replace(day=1)

        print("\n1. Checking ALL services with costs in last month")
        print(f"   Period: {first_day_last_month} to {first_day_this_month}")

        # Query all services
        response = ce_client.get_cost_and_usage(
            TimePeriod={
                'Start': first_day_last_month.strftime('%Y-%m-%d'),
                'End': first_day_this_month.strftime('%Y-%m-%d')
            },
            Granularity='MONTHLY',
            Metrics=['UnblendedCost'],
            GroupBy=[{
                'Type': 'DIMENSION',
                'Key': 'SERVICE'
            }]
        )

        services_found = _extract_services_with_costs(response)
        services_found.sort(key=lambda x: x[1], reverse=True)

        print("\n   Services with costs:")
        for service_name, cost in services_found[:20]:  # Top 20 services
            print(f"   - {service_name}: ${cost:.2f}")

        # Check for Bedrock specifically
        print("\n2. Searching for Bedrock-related services:")
        bedrock_services = [s for s in services_found if 'bedrock' in s[0].lower()]
        if bedrock_services:
            _print_bedrock_services(bedrock_services)
        else:
            _check_bedrock_variations(ce_client, first_day_last_month, first_day_this_month)

        # Check last 24 hours
        _check_last_24_hours(ce_client, yesterday, today)

    except Exception as e:
        print(f"\n   Error: {e}")
        import traceback
        traceback.print_exc()


def _check_service_codes(pricing_client):
    """Check Bedrock service codes in the Pricing API."""
    service_codes = ['AmazonBedrock', 'AWSBedrock', 'Bedrock']

    for service_code in service_codes:
        try:
            print(f"\n   Trying service code: {service_code}")
            response = pricing_client.get_products(
                ServiceCode=service_code,
                FormatVersion='aws_v1',
                MaxResults=5
            )

            price_list = response.get('PriceList', [])
            print(f"   - Found {len(price_list)} products")

            if price_list:
                # Parse first product
                product = json.loads(price_list[0])
                print("   - Sample product attributes:")
                attributes = product.get('product', {}).get('attributes', {})
                for key, value in list(attributes.items())[:5]:
                    print(f"     {key}: {value}")

        except Exception as e:
            print(f"   - Error: {e}")


def diagnose_pricing_api(region='ap-southeast-2', profile='default'):
    """Diagnose Pricing API for Bedrock."""
    print("\n" + "=" * 70)
    print("AWS Pricing API Diagnostics")
    print("=" * 70)

    try:
        session = boto3.Session(profile_name=profile, region_name=region)
        # Pricing API is only available in us-east-1 and ap-south-1
        pricing_client = session.client('pricing', region_name='us-east-1')

        print("\n1. Searching for Bedrock in Pricing API...")
        _check_service_codes(pricing_client)

        # List all available service codes
        print("\n2. Listing all available service codes...")
        try:
            response = pricing_client.describe_services(MaxResults=100)
            services = response.get('Services', [])
            print(f"   Found {len(services)} services")

            # Look for Bedrock
            bedrock_services = [s for s in services if 'bedrock' in s.get('ServiceCode', '').lower()]
            if bedrock_services:
                print("   Bedrock services found:")
                for service in bedrock_services:
                    print(f"   - {service.get('ServiceCode')}")
            else:
                print("   No Bedrock in service codes")
                print("   Showing all service codes:")
                for service in services[:20]:
                    print(f"   - {service.get('ServiceCode')}")

        except Exception as e:
            print(f"   Error: {e}")

    except Exception as e:
        print(f"\n   Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    import sys

    # Get profile and region from command line or use defaults
    profile = sys.argv[1] if len(sys.argv) > 1 else 'default'
    region = sys.argv[2] if len(sys.argv) > 2 else 'ap-southeast-2'

    print(f"Using AWS Profile: {profile}")
    print(f"Using Region: {region}")

    diagnose_cost_explorer(region, profile)
    diagnose_pricing_api(region, profile)

    print("\n" + "=" * 70)
    print("Diagnostics Complete")
    print("=" * 70)

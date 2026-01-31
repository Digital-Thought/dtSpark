"""
AWS Bedrock pricing module.

This module provides functionality for:
- Fetching Bedrock pricing from AWS Price List API
- Caching pricing data locally
- Calculating costs based on model, region, and token usage
"""

import json
import logging
import requests
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from botocore.exceptions import ClientError

# Model ID constants
_MODEL_CLAUDE_35_SONNET_V2 = 'anthropic.claude-3-5-sonnet-20241022-v2:0'
_MODEL_CLAUDE_35_SONNET_V1 = 'anthropic.claude-3-5-sonnet-20240620-v1:0'
_MODEL_CLAUDE_3_OPUS = 'anthropic.claude-3-opus-20240229-v1:0'
_MODEL_CLAUDE_3_SONNET = 'anthropic.claude-3-sonnet-20240229-v1:0'
_MODEL_CLAUDE_3_HAIKU = 'anthropic.claude-3-haiku-20240307-v1:0'


class BedrockPricing:
    """Manages AWS Bedrock pricing data and cost calculations."""

    def __init__(self, pricing_client, data_path: Path):
        """
        Initialise the pricing manager.

        Args:
            pricing_client: Boto3 Pricing API client
            data_path: Path to store cached pricing data
        """
        self.pricing_client = pricing_client
        self.data_path = Path(data_path)
        self.pricing_file = self.data_path / "bedrock_pricing.json"
        self.pricing_data = {}
        self.last_updated = None

        # Ensure data directory exists
        self.data_path.mkdir(parents=True, exist_ok=True)

    def load_pricing_data(self, force_refresh: bool = False) -> bool:
        """
        Load pricing data from cache or fetch from AWS.

        Args:
            force_refresh: If True, fetch fresh data from AWS

        Returns:
            True if pricing data loaded successfully
        """
        # Try to load from cache first
        if not force_refresh and self.pricing_file.exists():
            try:
                with open(self.pricing_file, 'r') as f:
                    cached_data = json.load(f)

                    # Convert string keys back to tuples
                    cached_pricing = cached_data.get('pricing', {})
                    self.pricing_data = {}
                    for key_str, prices in cached_pricing.items():
                        if '|' in key_str:
                            model_id, region = key_str.split('|', 1)
                            self.pricing_data[(model_id, region)] = prices

                    self.last_updated = datetime.fromisoformat(cached_data.get('last_updated'))

                    # Check if cache is still valid (less than 7 days old)
                    if datetime.now() - self.last_updated < timedelta(days=7):
                        logging.info(f"Loaded pricing data from cache (updated {self.last_updated})")
                        return True
                    else:
                        logging.info("Cached pricing data is stale, fetching fresh data")
            except Exception as e:
                logging.warning(f"Failed to load cached pricing data: {e}")

        # Fetch fresh pricing data from AWS
        return self._fetch_pricing_from_aws()

    def _fetch_pricing_from_aws(self) -> bool:
        """
        Fetch Bedrock pricing from AWS Bulk Price List API.

        Returns:
            True if successful
        """
        # Try Bulk API first (more reliable, no permissions needed)
        if self._fetch_from_bulk_api():
            return True

        # Fall back to Pricing API
        if self._fetch_from_pricing_api():
            return True

        # Fall back to hardcoded pricing
        logging.warning("All pricing fetch methods failed, using fallback pricing")
        self._use_fallback_pricing()
        return False

    def _fetch_from_bulk_api(self) -> bool:
        """
        Fetch pricing from AWS Bulk Price List API (no credentials needed).

        Returns:
            True if successful
        """
        try:
            logging.info("Fetching Bedrock pricing from AWS Bulk Price List...")

            # Fetch from the public Bulk API URL
            url = "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonBedrockService/current/index.json"

            response = requests.get(url, timeout=30)
            response.raise_for_status()

            pricing_json = response.json()
            logging.info("Successfully downloaded Bedrock pricing from Bulk API")

            # Parse the bulk pricing format
            self.pricing_data = self._parse_bulk_pricing(pricing_json)

            if not self.pricing_data:
                logging.warning("No usable pricing data found in Bulk API response")
                return False

            # Cache the data
            self.last_updated = datetime.now()

            # Convert tuple keys to strings for JSON serialization
            pricing_for_cache = {}
            for (model_id, region), prices in self.pricing_data.items():
                key_str = f"{model_id}|{region}"
                pricing_for_cache[key_str] = prices

            cache_data = {
                'pricing': pricing_for_cache,
                'last_updated': self.last_updated.isoformat()
            }

            with open(self.pricing_file, 'w') as f:
                json.dump(cache_data, f, indent=2)

            logging.info(f"Successfully cached pricing for {len(self.pricing_data)} model/region combinations")
            return True

        except requests.RequestException as e:
            logging.warning(f"Failed to fetch from Bulk API: {e}")
            return False
        except Exception as e:
            logging.error(f"Unexpected error fetching from Bulk API: {e}")
            return False

    def _fetch_from_pricing_api(self) -> bool:
        """
        Fetch Bedrock pricing from AWS Pricing API (requires credentials).

        Returns:
            True if successful
        """
        try:
            logging.info("Fetching Bedrock pricing from AWS Pricing API...")

            # The Pricing API is only available in us-east-1 and ap-south-1
            # Query for Amazon Bedrock Foundation Models pricing
            # Try multiple service codes as AWS uses different names
            service_codes = ['AmazonBedrockFoundationModels', 'AmazonBedrockService', 'AmazonBedrock']

            all_price_lists = []

            for service_code in service_codes:
                try:
                    response = self.pricing_client.get_products(
                        ServiceCode=service_code,
                        FormatVersion='aws_v1',
                        MaxResults=100
                    )

                    price_list = response.get('PriceList', [])
                    if price_list:
                        all_price_lists.extend(price_list)
                        logging.info(f"Found {len(price_list)} products with service code: {service_code}")

                        # Continue fetching if there are more results
                        while 'NextToken' in response:
                            response = self.pricing_client.get_products(
                                ServiceCode=service_code,
                                FormatVersion='aws_v1',
                                MaxResults=100,
                                NextToken=response['NextToken']
                            )
                            additional_list = response.get('PriceList', [])
                            all_price_lists.extend(additional_list)
                            logging.info(f"Fetched additional {len(additional_list)} products")

                except Exception as e:
                    logging.debug(f"Service code {service_code} failed: {e}")
                    continue

            if not all_price_lists:
                logging.warning("No pricing data found from Pricing API")
                return False

            # Parse all collected pricing data
            self.pricing_data = {}
            for price_item in all_price_lists:
                parsed_item = self._parse_price_item(price_item)
                if parsed_item:
                    for key, value in parsed_item.items():
                        if key not in self.pricing_data:
                            self.pricing_data[key] = value

            # Cache the data
            self.last_updated = datetime.now()

            # Convert tuple keys to strings for JSON serialization
            pricing_for_cache = {}
            for (model_id, region), prices in self.pricing_data.items():
                key_str = f"{model_id}|{region}"
                pricing_for_cache[key_str] = prices

            cache_data = {
                'pricing': pricing_for_cache,
                'last_updated': self.last_updated.isoformat()
            }

            with open(self.pricing_file, 'w') as f:
                json.dump(cache_data, f, indent=2)

            logging.info(f"Successfully fetched and cached pricing for {len(self.pricing_data)} model/region combinations")
            return True

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code in ['AccessDeniedException', 'UnauthorizedException']:
                logging.warning("No permissions for Pricing API, using fallback pricing")
                self._use_fallback_pricing()
                return True
            else:
                logging.error(f"Error fetching pricing data: {e}")
                self._use_fallback_pricing()
                return True
        except Exception as e:
            logging.error(f"Unexpected error fetching pricing: {e}")
            self._use_fallback_pricing()
            return True

    def _parse_bulk_pricing(self, pricing_json: Dict) -> Dict:
        """
        Parse AWS Bulk Price List format into usable pricing data.

        Args:
            pricing_json: Complete pricing JSON from Bulk API

        Returns:
            Dictionary mapping (model_id, region) to pricing info
        """
        parsed_data = {}

        try:
            products = pricing_json.get('products', {})
            terms = pricing_json.get('terms', {}).get('OnDemand', {})

            # First pass: build a map of SKU to product attributes
            sku_to_product = {}
            for sku, product in products.items():
                attributes = product.get('attributes', {})

                # Get model name and region
                model_name = attributes.get('model', '')
                region_code = attributes.get('regionCode', '')
                inference_type = attributes.get('inferenceType', '')

                # Filter for token-based pricing (ignore video generation, etc.)
                if not model_name or not region_code:
                    continue

                # Only process input/output tokens (not cache, batch, etc.)
                if 'token' not in inference_type.lower():
                    continue

                # Skip special types for now (cache, batch, long context)
                if any(x in inference_type.lower() for x in ['cache', 'batch', 'long context']):
                    continue

                sku_to_product[sku] = {
                    'model': model_name,
                    'region': region_code,
                    'inference_type': inference_type
                }

            # Second pass: extract pricing from terms
            for sku, term_data in terms.items():
                if sku not in sku_to_product:
                    continue

                product_info = sku_to_product[sku]
                model_name = product_info['model']
                region = product_info['region']
                inference_type = product_info['inference_type']

                # Map model name to Bedrock model ID
                # The Bulk API uses friendly names like "Claude Sonnet 4"
                # We need to map these to the actual model IDs
                model_id = self._map_model_name_to_id(model_name, region)
                if not model_id:
                    continue  # Skip unknown models

                # Extract price dimensions
                for term_key, term_value in term_data.items():
                    price_dimensions = term_value.get('priceDimensions', {})

                    for dim_key, dim_value in price_dimensions.items():
                        price_per_unit = float(dim_value.get('pricePerUnit', {}).get('USD', 0))

                        # Pricing is typically per token, but could be per 1000 tokens
                        unit = dim_value.get('unit', '').lower()
                        if 'token' in unit:
                            # Already per token, convert to per 1000 tokens
                            price_per_unit = price_per_unit * 1000

                        # Create key for this model/region
                        key = (model_id, region)

                        if key not in parsed_data:
                            parsed_data[key] = {'input': 0, 'output': 0}

                        # Classify as input or output based on inference_type
                        if 'input' in inference_type.lower():
                            parsed_data[key]['input'] = price_per_unit
                        elif 'output' in inference_type.lower():
                            parsed_data[key]['output'] = price_per_unit

            logging.info(f"Parsed {len(parsed_data)} model/region pricing combinations from Bulk API")

        except Exception as e:
            logging.error(f"Error parsing bulk pricing: {e}")
            import traceback
            traceback.print_exc()

        return parsed_data

    def _map_model_name_to_id(self, model_name: str, region: str) -> Optional[str]:
        """
        Map AWS Bulk API model names to Bedrock model IDs.

        Args:
            model_name: Friendly model name from Bulk API (e.g., "Claude Sonnet 4")
            region: AWS region

        Returns:
            Bedrock model ID or None if unknown
        """
        # Normalize the model name
        model_lower = model_name.lower()

        # Claude models
        if 'claude' in model_lower:
            if 'sonnet 4.5' in model_lower or 'sonnet-4.5' in model_lower:
                return 'anthropic.claude-sonnet-4.5-v1:0'
            elif 'sonnet 4' in model_lower or 'sonnet-4' in model_lower:
                return 'anthropic.claude-sonnet-4-0-v1:0'
            elif '3.5 sonnet v2' in model_lower or '3-5-sonnet-v2' in model_lower:
                return _MODEL_CLAUDE_35_SONNET_V2
            elif '3.5 sonnet' in model_lower or '3-5-sonnet' in model_lower:
                return _MODEL_CLAUDE_35_SONNET_V1
            elif '3 opus' in model_lower or '3-opus' in model_lower:
                return _MODEL_CLAUDE_3_OPUS
            elif '3 sonnet' in model_lower or '3-sonnet' in model_lower:
                return _MODEL_CLAUDE_3_SONNET
            elif '3 haiku' in model_lower or '3-haiku' in model_lower:
                return _MODEL_CLAUDE_3_HAIKU

        # Amazon Titan models
        elif 'titan' in model_lower:
            if 'text express' in model_lower:
                return 'amazon.titan-text-express-v1'
            elif 'text lite' in model_lower:
                return 'amazon.titan-text-lite-v1'

        # Meta Llama models
        elif 'llama' in model_lower:
            if 'llama 3' in model_lower:
                if '70b' in model_lower:
                    return 'meta.llama3-70b-instruct-v1:0'
                elif '8b' in model_lower:
                    return 'meta.llama3-8b-instruct-v1:0'

        # Cohere models
        elif 'cohere' in model_lower or 'command' in model_lower:
            if 'command r+' in model_lower:
                return 'cohere.command-r-plus-v1:0'
            elif 'command r' in model_lower:
                return 'cohere.command-r-v1:0'

        # Unknown model
        logging.debug(f"Unknown model name: {model_name}")
        return None

    def _parse_price_item(self, price_item: str) -> Dict:
        """
        Parse a single price item from AWS Pricing API.

        Args:
            price_item: JSON string from PriceList

        Returns:
            Dictionary mapping (model_id, region) to pricing info
        """
        parsed_data = {}

        try:
            # Parse the JSON string
            product = json.loads(price_item)

            # Extract product attributes
            attributes = product.get('product', {}).get('attributes', {})
            region_code = attributes.get('regionCode')
            usage_type = attributes.get('usageType', '')

            # Extract pricing terms
            on_demand = product.get('terms', {}).get('OnDemand', {})
            if not on_demand:
                return parsed_data

            # Get first price dimension
            for term_key, term_value in on_demand.items():
                price_dimensions = term_value.get('priceDimensions', {})
                for dim_key, dim_value in price_dimensions.items():
                    price_per_unit = float(dim_value.get('pricePerUnit', {}).get('USD', 0))

                    # Determine if this is input or output pricing
                    description = dim_value.get('description', '').lower()

                    # Try to extract model name from usage type
                    model_name = self._extract_model_from_usage_type(usage_type)

                    if model_name and region_code:
                        key = (model_name, region_code)

                        if key not in parsed_data:
                            parsed_data[key] = {'input': 0, 'output': 0}

                        # Classify as input or output based on description
                        if 'input' in description or 'request' in description:
                            parsed_data[key]['input'] = price_per_unit
                        elif 'output' in description or 'response' in description:
                            parsed_data[key]['output'] = price_per_unit

        except Exception as e:
            logging.debug(f"Error parsing price item: {e}")

        return parsed_data

    def _extract_model_from_usage_type(self, usage_type: str) -> Optional[str]:
        """
        Extract model identifier from usage type string.

        Args:
            usage_type: AWS usage type string

        Returns:
            Model identifier or None
        """
        # Usage types typically look like: "APS2-ModelInference-Claude-3-5-Sonnet-v2"
        if 'Claude' in usage_type:
            if 'Claude-3-5-Sonnet-v2' in usage_type:
                return 'claude-3-5-sonnet-20241022'
            elif 'Claude-3-5-Sonnet' in usage_type:
                return 'claude-3-5-sonnet-20240620'
            elif 'Claude-3-Opus' in usage_type:
                return 'claude-3-opus-20240229'
            elif 'Claude-3-Sonnet' in usage_type:
                return 'claude-3-sonnet-20240229'
            elif 'Claude-3-Haiku' in usage_type:
                return 'claude-3-haiku-20240307'

        return None

    def _use_fallback_pricing(self):
        """
        Use fallback pricing data when API is unavailable.
        Prices as of January 2025 in USD per 1000 tokens.
        """
        # Fallback pricing for common models (prices per 1000 tokens)
        fallback = {
            # Claude 3.5 Sonnet v2
            (_MODEL_CLAUDE_35_SONNET_V2, 'us-east-1'): {'input': 0.003, 'output': 0.015},
            (_MODEL_CLAUDE_35_SONNET_V2, 'us-west-2'): {'input': 0.003, 'output': 0.015},
            (_MODEL_CLAUDE_35_SONNET_V2, 'ap-southeast-2'): {'input': 0.003, 'output': 0.015},

            # Claude 3.5 Sonnet v1
            (_MODEL_CLAUDE_35_SONNET_V1, 'us-east-1'): {'input': 0.003, 'output': 0.015},
            (_MODEL_CLAUDE_35_SONNET_V1, 'us-west-2'): {'input': 0.003, 'output': 0.015},
            (_MODEL_CLAUDE_35_SONNET_V1, 'ap-southeast-2'): {'input': 0.003, 'output': 0.015},

            # Claude 3 Opus
            (_MODEL_CLAUDE_3_OPUS, 'us-east-1'): {'input': 0.015, 'output': 0.075},
            (_MODEL_CLAUDE_3_OPUS, 'us-west-2'): {'input': 0.015, 'output': 0.075},

            # Claude 3 Sonnet
            (_MODEL_CLAUDE_3_SONNET, 'us-east-1'): {'input': 0.003, 'output': 0.015},
            (_MODEL_CLAUDE_3_SONNET, 'us-west-2'): {'input': 0.003, 'output': 0.015},

            # Claude 3 Haiku
            (_MODEL_CLAUDE_3_HAIKU, 'us-east-1'): {'input': 0.00025, 'output': 0.00125},
            (_MODEL_CLAUDE_3_HAIKU, 'us-west-2'): {'input': 0.00025, 'output': 0.00125},
        }

        self.pricing_data = fallback
        self.last_updated = datetime.now()
        logging.info(f"Using fallback pricing data for {len(fallback)} model/region combinations")

    def get_model_pricing(self, model_id: str, region: str) -> Optional[Dict[str, float]]:
        """
        Get pricing for a specific model and region.

        Args:
            model_id: Bedrock model ID
            region: AWS region code

        Returns:
            Dictionary with 'input' and 'output' prices per 1000 tokens, or None
        """
        # Try exact match first
        pricing = self.pricing_data.get((model_id, region))

        # If not found, try to find similar model (e.g., without version suffix)
        if not pricing:
            for (cached_model, cached_region), cached_pricing in self.pricing_data.items():
                if cached_region == region and model_id.startswith(cached_model.split('-v')[0]):
                    pricing = cached_pricing
                    break

        return pricing

    def calculate_cost(self, model_id: str, region: str, input_tokens: int, output_tokens: int) -> Tuple[float, str]:
        """
        Calculate cost for a model invocation.

        Args:
            model_id: Bedrock model ID
            region: AWS region code
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens

        Returns:
            Tuple of (cost in USD, pricing source description)
        """
        pricing = self.get_model_pricing(model_id, region)

        if not pricing:
            logging.warning(f"No pricing data for {model_id} in {region}, using default estimate")
            # Use a conservative default (similar to Claude 3.5 Sonnet)
            pricing = {'input': 0.003, 'output': 0.015}
            source = "estimated (no pricing data)"
        else:
            source = "from AWS pricing data" if self.last_updated else "estimated"

        # Calculate cost (pricing is per 1000 tokens)
        input_cost = (input_tokens / 1000.0) * pricing['input']
        output_cost = (output_tokens / 1000.0) * pricing['output']
        total_cost = input_cost + output_cost

        return total_cost, source

    def estimate_max_cost(self, model_id: str, region: str, input_tokens: int, max_output_tokens: int) -> float:
        """
        Estimate maximum possible cost for a request.

        Args:
            model_id: Bedrock model ID
            region: AWS region code
            input_tokens: Number of input tokens
            max_output_tokens: Maximum output tokens configured

        Returns:
            Maximum cost in USD
        """
        cost, _ = self.calculate_cost(model_id, region, input_tokens, max_output_tokens)
        return cost

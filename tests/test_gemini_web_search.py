"""
Test Google Gemini web search (grounding) functionality.

This test verifies that Google Search grounding is properly configured
and the tool is correctly built for both Gemini 1.5 and 2.0+ models.
"""

import sys
import os

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


def test_web_search_tool_building():
    """Test that web search tools are built correctly for different model versions."""
    try:
        from dtSpark.llm.google_gemini import GoogleGeminiService
        from google.genai import types
    except ImportError:
        print("SKIP: google-genai package not installed")
        return

    # Create service instance for testing
    service = GoogleGeminiService.__new__(GoogleGeminiService)
    service.api_key = "test-key"

    print("Testing web search tool building...")
    print("=" * 60)

    # Test 1: Gemini 2.0+ model (uses GoogleSearch)
    print("\n1. Testing Gemini 2.0+ model (GoogleSearch)...")
    service.current_model_id = "gemini-2.0-flash"

    web_search_config = {
        'enabled': True,
        'exclude_domains': ['example.com', 'test.com']
    }

    tool = service._build_web_search_tool(web_search_config)

    assert tool is not None, "Tool should be built"
    assert hasattr(tool, 'google_search'), "Should have google_search attribute"
    print("   [OK] GoogleSearch tool built for Gemini 2.0+")

    # Test 2: Gemini 1.5 model (uses GoogleSearchRetrieval with dynamic threshold)
    print("\n2. Testing Gemini 1.5 model (GoogleSearchRetrieval)...")
    service.current_model_id = "gemini-1.5-pro"

    web_search_config = {
        'enabled': True,
        'dynamic_threshold': 0.6
    }

    tool = service._build_web_search_tool(web_search_config)

    assert tool is not None, "Tool should be built"
    assert hasattr(tool, 'google_search_retrieval'), "Should have google_search_retrieval attribute"
    print("   [OK] GoogleSearchRetrieval tool built for Gemini 1.5")

    # Test 3: Check supports_web_search method
    print("\n3. Testing supports_web_search method...")

    service.current_model_id = "gemini-2.5-flash"
    assert service.supports_web_search() is True, "Gemini 2.5 should support web search"

    service.current_model_id = "gemini-1.5-flash"
    assert service.supports_web_search() is True, "Gemini 1.5 should support web search"

    service.current_model_id = None
    assert service.supports_web_search() is False, "No model should return False"

    print("   [OK] supports_web_search works correctly")

    # Test 4: Empty exclude_domains (should still work)
    print("\n4. Testing with empty exclude_domains...")
    service.current_model_id = "gemini-2.0-flash"

    web_search_config = {
        'enabled': True,
        'exclude_domains': []
    }

    tool = service._build_web_search_tool(web_search_config)
    assert tool is not None, "Tool should be built with empty exclude_domains"
    print("   [OK] Tool built with empty exclude_domains")

    print("\n" + "=" * 60)
    print("[SUCCESS] All web search tool building tests passed!")


def test_grounding_metadata_extraction():
    """Test that grounding metadata is correctly extracted from responses."""
    try:
        from dtSpark.llm.google_gemini import GoogleGeminiService
    except ImportError:
        print("SKIP: google-genai package not installed")
        return

    # Create service instance for testing
    service = GoogleGeminiService.__new__(GoogleGeminiService)
    service.api_key = "test-key"
    service.current_model_id = "gemini-2.0-flash"

    print("\nTesting grounding metadata extraction...")
    print("=" * 60)

    # Create mock grounding metadata
    class MockWeb:
        def __init__(self, uri, title):
            self.uri = uri
            self.title = title

    class MockChunk:
        def __init__(self, uri, title):
            self.web = MockWeb(uri, title)

    class MockSegment:
        def __init__(self, text):
            self.text = text

    class MockSupport:
        def __init__(self, text, indices):
            self.segment = MockSegment(text)
            self.grounding_chunk_indices = indices

    class MockSearchEntryPoint:
        def __init__(self, content):
            self.rendered_content = content

    class MockGroundingMetadata:
        def __init__(self):
            self.web_search_queries = ["test query 1", "test query 2"]
            self.grounding_chunks = [
                MockChunk("https://example.com/1", "Example Page 1"),
                MockChunk("https://example.com/2", "Example Page 2")
            ]
            self.grounding_supports = [
                MockSupport("This is supported text", [0, 1])
            ]
            self.search_entry_point = MockSearchEntryPoint("<div>Rendered content</div>")

    metadata = MockGroundingMetadata()
    result = service._extract_grounding_metadata(metadata)

    # Verify extraction
    assert 'search_queries' in result, "Should have search_queries"
    assert len(result['search_queries']) == 2, "Should have 2 search queries"
    print("   [OK] Search queries extracted")

    assert 'sources' in result, "Should have sources"
    assert len(result['sources']) == 2, "Should have 2 sources"
    assert result['sources'][0]['url'] == "https://example.com/1"
    print("   [OK] Sources extracted with URLs and titles")

    assert 'supports' in result, "Should have supports"
    assert len(result['supports']) == 1, "Should have 1 support"
    print("   [OK] Grounding supports extracted")

    assert 'rendered_content' in result, "Should have rendered_content"
    print("   [OK] Search entry point extracted")

    print("\n" + "=" * 60)
    print("[SUCCESS] All grounding metadata extraction tests passed!")


def test_web_search_config_integration():
    """Test that web search config is properly integrated into invoke_model."""
    try:
        from dtSpark.llm.google_gemini import GoogleGeminiService
    except ImportError:
        print("SKIP: google-genai package not installed")
        return

    print("\nTesting web search config integration...")
    print("=" * 60)

    # Create service instance
    service = GoogleGeminiService.__new__(GoogleGeminiService)
    service.api_key = "test-key"
    service.current_model_id = "gemini-2.0-flash"
    service.default_max_tokens = 8192
    service.rate_limit_max_retries = 3
    service.rate_limit_base_delay = 1.0

    # Check that invoke_model accepts web_search_config parameter
    import inspect
    sig = inspect.signature(service.invoke_model)
    params = list(sig.parameters.keys())

    assert 'web_search_config' in params, "invoke_model should accept web_search_config"
    print("   [OK] invoke_model accepts web_search_config parameter")

    print("\n" + "=" * 60)
    print("[SUCCESS] Web search config integration test passed!")


def test_schema_cleaning_for_gemini():
    """Test that JSON schemas are properly cleaned for Gemini API compatibility."""
    try:
        from dtSpark.llm.google_gemini import GoogleGeminiService
    except ImportError:
        print("SKIP: google-genai package not installed")
        return

    print("\nTesting JSON schema cleaning for Gemini...")
    print("=" * 60)

    # Create service instance for testing
    service = GoogleGeminiService.__new__(GoogleGeminiService)
    service.api_key = "test-key"
    service.current_model_id = "gemini-2.0-flash"

    # Test 1: Remove additionalProperties
    print("\n1. Testing removal of additionalProperties...")
    schema_with_additional = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "nested": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "value": {"type": "number"}
                }
            }
        },
        "additionalProperties": True
    }

    cleaned = service._clean_schema_for_gemini(schema_with_additional)
    assert "additionalProperties" not in cleaned, "additionalProperties should be removed"
    assert "additionalProperties" not in cleaned["properties"]["nested"], \
        "Nested additionalProperties should be removed"
    print("   [OK] additionalProperties removed")

    # Test 2: Remove $schema, $defs, $ref
    print("\n2. Testing removal of JSON Schema meta fields...")
    schema_with_meta = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {"StringDef": {"type": "string"}},
        "type": "object",
        "properties": {
            "field": {"$ref": "#/$defs/StringDef"}
        }
    }

    cleaned = service._clean_schema_for_gemini(schema_with_meta)
    assert "$schema" not in cleaned, "$schema should be removed"
    assert "$defs" not in cleaned, "$defs should be removed"
    assert "$ref" not in cleaned["properties"]["field"], "$ref should be removed"
    print("   [OK] JSON Schema meta fields removed")

    # Test 3: Remove additional_properties (snake_case variant)
    print("\n3. Testing removal of additional_properties (snake_case)...")
    schema_with_snake = {
        "type": "object",
        "additional_properties": False,
        "properties": {
            "id": {"type": "string"}
        }
    }

    cleaned = service._clean_schema_for_gemini(schema_with_snake)
    assert "additional_properties" not in cleaned, "additional_properties should be removed"
    print("   [OK] additional_properties (snake_case) removed")

    # Test 4: Preserve valid fields
    print("\n4. Testing preservation of valid JSON Schema fields...")
    valid_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "The name"},
            "count": {"type": "integer", "minimum": 0}
        },
        "required": ["name"]
    }

    cleaned = service._clean_schema_for_gemini(valid_schema)
    assert cleaned["type"] == "object", "type should be preserved"
    assert "properties" in cleaned, "properties should be preserved"
    assert "required" in cleaned, "required should be preserved"
    assert cleaned["properties"]["name"]["description"] == "The name", "description should be preserved"
    print("   [OK] Valid fields preserved")

    # Test 5: Handle nested arrays
    print("\n5. Testing cleaning of nested arrays...")
    schema_with_array = {
        "type": "array",
        "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "value": {"type": "string"}
            }
        }
    }

    cleaned = service._clean_schema_for_gemini(schema_with_array)
    assert "additionalProperties" not in cleaned["items"], \
        "additionalProperties in array items should be removed"
    print("   [OK] Nested arrays cleaned")

    # Test 6: Handle deeply nested structures
    print("\n6. Testing deeply nested structure cleaning...")
    deep_schema = {
        "type": "object",
        "properties": {
            "level1": {
                "type": "object",
                "additionalProperties": True,
                "properties": {
                    "level2": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "level3": {
                                "type": "string",
                                "default": "test"
                            }
                        }
                    }
                }
            }
        }
    }

    cleaned = service._clean_schema_for_gemini(deep_schema)
    assert "additionalProperties" not in cleaned["properties"]["level1"]
    assert "additionalProperties" not in cleaned["properties"]["level1"]["properties"]["level2"]
    assert "default" not in cleaned["properties"]["level1"]["properties"]["level2"]["properties"]["level3"]
    print("   [OK] Deeply nested structures cleaned")

    # Test 7: Fix empty items schema
    print("\n7. Testing empty items schema fixing...")
    schema_empty_items = {
        "type": "array",
        "items": {}
    }

    cleaned = service._clean_schema_for_gemini(schema_empty_items)
    assert cleaned["items"]["type"] == "string", "Empty items should default to string type"
    print("   [OK] Empty items schema fixed with default type")

    # Test 8: Fix items missing type but having properties
    print("\n8. Testing items with properties but no type...")
    schema_items_no_type = {
        "type": "array",
        "items": {
            "properties": {
                "name": {"type": "string"}
            }
        }
    }

    cleaned = service._clean_schema_for_gemini(schema_items_no_type)
    assert cleaned["items"]["type"] == "object", "Items with properties should get type object"
    print("   [OK] Items with properties correctly typed as object")

    # Test 9: Fix malformed nested items (items.items without proper structure)
    print("\n9. Testing malformed nested items (items.items)...")
    schema_malformed_nested = {
        "type": "array",
        "items": {
            "properties": {
                "data": {
                    "type": "array",
                    "items": {
                        "items": {}  # Malformed - items of items with no type
                    }
                }
            }
        }
    }

    cleaned = service._clean_schema_for_gemini(schema_malformed_nested)
    # The malformed nested items should be fixed
    data_items = cleaned["items"]["properties"]["data"]["items"]
    assert "type" in data_items, "Malformed items should have type added"
    print("   [OK] Malformed nested items fixed")

    # Test 10: Array type without items definition (the actual bug case)
    print("\n10. Testing array type without items definition...")
    schema_array_no_items = {
        "type": "object",
        "properties": {
            "data": {
                "type": "array",
                "items": {
                    "type": "array"
                    # Missing inner 'items' - Gemini requires this
                },
                "description": "2D array"
            }
        }
    }

    cleaned = service._clean_schema_for_gemini(schema_array_no_items)
    # The inner array should now have items defined
    inner_items = cleaned["properties"]["data"]["items"]
    assert inner_items.get("type") == "array", "Type should be array"
    assert "items" in inner_items, "Array type should have items added"
    assert inner_items["items"].get("type") == "string", "Inner items should default to string"
    print("   [OK] Array type without items gets default items added")

    # Test 11: Complex real-world schema (like Excel create_excel_document)
    print("\n11. Testing complex real-world schema (Excel pattern)...")
    excel_schema = {
        "type": "object",
        "properties": {
            "sheets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "data": {
                            "type": "array",
                            "items": {"type": "array"},  # Missing inner items!
                            "description": "2D array of cell values"
                        }
                    }
                }
            }
        },
        "additionalProperties": False
    }

    cleaned = service._clean_schema_for_gemini(excel_schema)
    assert "additionalProperties" not in cleaned
    # Navigate to the data.items and verify it has inner items defined
    data_items = cleaned["properties"]["sheets"]["items"]["properties"]["data"]["items"]
    assert data_items.get("type") == "array", "data items should be array type"
    assert "items" in data_items, "data items should have inner items"
    assert data_items["items"].get("type") == "string", "Inner items should be string"
    print("   [OK] Complex Excel schema properly fixed")

    print("\n" + "=" * 60)
    print("[SUCCESS] All JSON schema cleaning tests passed!")


if __name__ == '__main__':
    print("Testing Google Gemini Web Search (Grounding)...")
    print("=" * 80)

    print("\n1. Testing web search tool building...")
    print("-" * 40)
    test_web_search_tool_building()

    print("\n2. Testing grounding metadata extraction...")
    print("-" * 40)
    test_grounding_metadata_extraction()

    print("\n3. Testing web search config integration...")
    print("-" * 40)
    test_web_search_config_integration()

    print("\n4. Testing JSON schema cleaning for Gemini...")
    print("-" * 40)
    test_schema_cleaning_for_gemini()

    print("\n" + "=" * 80)
    print("All Google Gemini web search tests completed!")

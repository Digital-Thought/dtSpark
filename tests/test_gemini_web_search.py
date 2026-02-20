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

    print("\n" + "=" * 80)
    print("All Google Gemini web search tests completed!")

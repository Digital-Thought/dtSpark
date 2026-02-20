"""
Test Google Gemini LLM integration.

This integration test verifies that the Google Gemini provider
can be properly initialised and models can be listed.

Requirements:
- google-genai package installed
- GEMINI_API_KEY or GOOGLE_API_KEY environment variable set
"""

import sys
import os

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


def main():
    """Test Google Gemini integration."""
    print("Google Gemini Integration Test")
    print("=" * 60)

    # Check for google-genai package
    try:
        import google.genai
        print("[OK] google-genai package is installed")
    except ImportError:
        print("[SKIP] google-genai package not installed")
        print("Install with: pip install google-genai")
        return False

    # Check for API key
    api_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')
    if not api_key:
        print("[SKIP] No API key found (set GEMINI_API_KEY or GOOGLE_API_KEY)")
        return False

    print(f"[OK] API key found: {api_key[:8]}...")

    # Import and initialise service
    try:
        from dtSpark.llm.google_gemini import GoogleGeminiService
        from dtSpark.llm.manager import LLMManager

        print("\nInitialising Google Gemini service...")
        service = GoogleGeminiService(api_key=api_key)
        print(f"[OK] Service initialised: {service.get_provider_name()}")
        print(f"    Access info: {service.get_access_info()}")

    except Exception as e:
        print(f"[ERROR] Failed to initialise service: {e}")
        return False

    # Test model listing
    print("\nListing available models...")
    try:
        models = service.list_available_models()
        print(f"[OK] Found {len(models)} models")

        if models:
            print("\nAvailable models:")
            for model in models[:10]:  # Show first 10
                print(f"  - {model['id']}")
                print(f"    Name: {model['name']}")
                print(f"    Context: {model.get('context_length', 'N/A'):,} tokens")
                print(f"    Max Output: {model.get('max_output', 'N/A'):,} tokens")
                print(f"    Tools: {'Yes' if model.get('supports_tools') else 'No'}")
                print()

            if len(models) > 10:
                print(f"  ... and {len(models) - 10} more models")

    except Exception as e:
        print(f"[ERROR] Failed to list models: {e}")
        return False

    # Test manager integration
    print("\nTesting LLM Manager integration...")
    try:
        manager = LLMManager()
        manager.register_provider(service)
        print(f"[OK] Provider registered with manager")

        all_models = manager.list_all_models()
        gemini_models = [m for m in all_models if 'Gemini' in m.get('provider', '')]
        print(f"[OK] Manager sees {len(gemini_models)} Gemini models")

    except Exception as e:
        print(f"[ERROR] Manager integration failed: {e}")
        return False

    # Test model selection
    print("\nTesting model selection...")
    try:
        if models:
            test_model = models[0]['id']
            service.set_model(test_model)
            print(f"[OK] Model set to: {test_model}")
        else:
            print("[SKIP] No models available for selection test")

    except Exception as e:
        print(f"[ERROR] Model selection failed: {e}")
        return False

    # Test rate limits
    print("\nTesting rate limit info...")
    try:
        rate_limits = service.get_rate_limits()
        print(f"[OK] Rate limits retrieved:")
        print(f"    Has limits: {rate_limits.get('has_limits')}")
        print(f"    Requests/min: {rate_limits.get('requests_per_minute')}")
        print(f"    Input tokens/min: {rate_limits.get('input_tokens_per_minute')}")

    except Exception as e:
        print(f"[ERROR] Rate limit retrieval failed: {e}")
        return False

    print("\n" + "=" * 60)
    print("[SUCCESS] All Google Gemini integration tests passed!")
    return True


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)

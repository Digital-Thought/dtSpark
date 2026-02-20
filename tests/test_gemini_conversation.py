"""Test script to verify Google Gemini conversation works after model selection."""
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


def main():
    print("=" * 70)
    print("Testing Google Gemini Conversation Flow")
    print("=" * 70)

    # Check for google-genai package
    try:
        import google.genai
        print("\n[OK] google-genai package is installed")
    except ImportError:
        print("\n[SKIP] google-genai package not installed")
        print("Install with: pip install google-genai")
        return

    # Check for API key
    api_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')
    if not api_key:
        print("[SKIP] No API key found (set GEMINI_API_KEY or GOOGLE_API_KEY)")
        return

    print(f"[OK] API key found: {api_key[:8]}...")

    from dtSpark.llm import LLMManager
    from dtSpark.llm.google_gemini import GoogleGeminiService

    # Initialize LLM Manager
    print("\n1. Creating LLM Manager...")
    manager = LLMManager()

    # Connect to Google Gemini
    print("\n2. Connecting to Google Gemini...")
    try:
        gemini_service = GoogleGeminiService(api_key=api_key)
        manager.register_provider(gemini_service)
        print("   [OK] Connected to Google Gemini")
    except Exception as e:
        print(f"   [FAIL] Failed to connect: {e}")
        return

    # List models
    print("\n3. Listing available models...")
    try:
        models = gemini_service.list_available_models()
        print(f"   [OK] Found {len(models)} models")

        if models:
            # Find a flash model for testing (faster/cheaper)
            test_model = None
            for m in models:
                if 'flash' in m['id'].lower():
                    test_model = m['id']
                    break

            if not test_model and models:
                test_model = models[0]['id']

            print(f"   Will use model: {test_model}")
        else:
            print("   [FAIL] No models available")
            return
    except Exception as e:
        print(f"   [FAIL] Failed to list models: {e}")
        return

    # Select a model
    print(f"\n4. Selecting model {test_model}...")
    try:
        manager.set_model(test_model)
        active_service = manager.get_active_service()
        print("   [OK] Model selected")
        print(f"   Active provider: {manager.get_active_provider()}")
        print(f"   Active service: {type(active_service).__name__}")
    except Exception as e:
        print(f"   [FAIL] Failed to select model: {e}")
        return

    # Test simple invocation
    print("\n5. Testing model invocation...")
    try:
        messages = [{"role": "user", "content": "Say hello in 5 words or less"}]
        response = manager.invoke_model(messages, max_tokens=50, temperature=0.7)

        if response.get('error'):
            print(f"   [FAIL] Error: {response.get('error_message')}")
            return

        # Extract response text
        content = response.get('content', '')
        if content:
            print(f"   [OK] Response received: {content[:100]}")
        else:
            content_blocks = response.get('content_blocks', [])
            if content_blocks and len(content_blocks) > 0:
                text = content_blocks[0].get('text', 'No text found')
                print(f"   [OK] Response received: {text[:100]}")
            else:
                print("   [FAIL] No content in response")
                return

    except Exception as e:
        print(f"   [FAIL] Failed to invoke model: {e}")
        import traceback
        traceback.print_exc()
        return

    print("\n" + "=" * 70)
    print("Test completed successfully!")
    print("=" * 70)


if __name__ == "__main__":
    main()

"""Test script to verify Ollama integration with the LLM manager."""
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from dtSpark.llm import LLMManager, OllamaService

def main():
    print("=" * 70)
    print("Testing Ollama Integration")
    print("=" * 70)

    # Initialize LLM Manager
    print("\n1. Creating LLM Manager...")
    manager = LLMManager()

    # Test Ollama connection
    print("\n2. Connecting to Ollama...")
    try:
        ollama_url = "http://dt-docker01.digital-thought.home:11434"
        print(f"   URL: {ollama_url}")

        ollama_service = OllamaService(base_url=ollama_url)
        print("   [OK] Connected successfully to Ollama")

        # Register Ollama
        manager.register_provider(ollama_service)
        print("   [OK] Registered Ollama provider")

    except Exception as e:
        print(f"   [FAIL] Failed to connect to Ollama: {e}")
        return

    # List all models
    print("\n3. Listing available models...")
    try:
        models = manager.list_all_models()

        if not models:
            print("   No models found")
            return

        print(f"\n   Found {len(models)} model(s):\n")

        # Group by provider
        by_provider = {}
        for model in models:
            provider = model.get('provider', 'Unknown')
            if provider not in by_provider:
                by_provider[provider] = []
            by_provider[provider].append(model)

        for provider, prov_models in by_provider.items():
            print(f"   {provider}:")
            for model in prov_models:
                model_id = model.get('id', 'unknown')
                model_name = model.get('name', model_id)
                print(f"      - {model_id}")
                if model_name != model_id:
                    print(f"        ({model_name})")
            print()

    except Exception as e:
        print(f"   [FAIL] Failed to list models: {e}")
        import traceback
        traceback.print_exc()
        return

    print("=" * 70)
    print("Test completed successfully!")
    print("=" * 70)

if __name__ == "__main__":
    main()

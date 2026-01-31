"""Test script to verify Ollama conversation works after model selection."""
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from dtSpark.llm import LLMManager, OllamaService

def main():
    print("=" * 70)
    print("Testing Ollama Conversation Flow")
    print("=" * 70)

    # Initialize LLM Manager
    print("\n1. Creating LLM Manager...")
    manager = LLMManager()

    # Connect to Ollama
    print("\n2. Connecting to Ollama...")
    try:
        ollama_url = "http://dt-docker01.digital-thought.home:11434"
        ollama_service = OllamaService(base_url=ollama_url)
        manager.register_provider(ollama_service)
        print("   [OK] Connected to Ollama")
    except Exception as e:
        print(f"   [FAIL] Failed to connect: {e}")
        return

    # Select a model
    print("\n3. Selecting model llama3.1:latest...")
    try:
        manager.set_model("llama3.1:latest")
        active_service = manager.get_active_service()
        print("   [OK] Model selected")
        print(f"   Active provider: {manager.get_active_provider()}")
        print(f"   Active service: {type(active_service).__name__}")
    except Exception as e:
        print(f"   [FAIL] Failed to select model: {e}")
        return

    # Test simple invocation
    print("\n4. Testing model invocation...")
    try:
        messages = [{"role": "user", "content": "Say hello in 5 words or less"}]
        response = manager.invoke_model(messages, max_tokens=50, temperature=0.7)

        if response.get('error'):
            print(f"   [FAIL] Error: {response.get('error_message')}")
            return

        # Extract response text
        content = response.get('content', [])
        if content and len(content) > 0:
            text = content[0].get('text', 'No text found')
            print(f"   [OK] Response received: {text[:100]}")
        else:
            print("   [FAIL] No content in response")

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

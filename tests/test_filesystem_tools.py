"""
Test script for embedded filesystem tools.

This tests the embedded filesystem tools with different configurations.


"""

import os
import sys
import tempfile
from pathlib import Path

# Add parent directory to path to import modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from dtSpark.tools.builtin import get_builtin_tools, execute_builtin_tool


def test_filesystem_tools_disabled():
    """Test that filesystem tools are not loaded when disabled."""
    print("\n=== Test 1: Filesystem Tools Disabled ===")

    config = {
        'embedded_tools': {
            'filesystem': {
                'enabled': False,
                'allowed_path': './test_data',
                'access_mode': 'read_write'
            }
        }
    }

    tools = get_builtin_tools(config=config)
    tool_names = [tool['name'] for tool in tools]

    print(f"Tools loaded: {tool_names}")

    # Should only have datetime tool
    assert 'get_current_datetime' in tool_names
    assert 'list_files_recursive' not in tool_names
    assert 'search_files' not in tool_names

    print("[PASS] Filesystem tools correctly disabled")


def test_filesystem_tools_read_only():
    """Test that filesystem tools are loaded correctly in read-only mode."""
    print("\n=== Test 2: Filesystem Tools Read-Only Mode ===")

    config = {
        'embedded_tools': {
            'filesystem': {
                'enabled': True,
                'allowed_path': './test_data',
                'access_mode': 'read'
            }
        }
    }

    tools = get_builtin_tools(config=config)
    tool_names = [tool['name'] for tool in tools]

    print(f"Tools loaded: {tool_names}")

    # Should have datetime + read-only filesystem tools
    assert 'get_current_datetime' in tool_names
    assert 'list_files_recursive' in tool_names
    assert 'search_files' in tool_names
    assert 'read_file_text' in tool_names
    assert 'read_file_binary' in tool_names

    # Should NOT have write tools
    assert 'write_file' not in tool_names
    assert 'create_directories' not in tool_names

    print("[PASS] Read-only filesystem tools correctly loaded")


def test_filesystem_tools_read_write():
    """Test that filesystem tools are loaded correctly in read-write mode."""
    print("\n=== Test 3: Filesystem Tools Read-Write Mode ===")

    config = {
        'embedded_tools': {
            'filesystem': {
                'enabled': True,
                'allowed_path': './test_data',
                'access_mode': 'read_write'
            }
        }
    }

    tools = get_builtin_tools(config=config)
    tool_names = [tool['name'] for tool in tools]

    print(f"Tools loaded: {tool_names}")

    # Should have datetime + all filesystem tools
    assert 'get_current_datetime' in tool_names
    assert 'list_files_recursive' in tool_names
    assert 'search_files' in tool_names
    assert 'read_file_text' in tool_names
    assert 'read_file_binary' in tool_names
    assert 'write_file' in tool_names
    assert 'create_directories' in tool_names

    print("[PASS] Read-write filesystem tools correctly loaded")


def test_list_files():
    """Test list_files_recursive tool."""
    print("\n=== Test 4: List Files ===")

    # Create temporary directory structure
    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"Using temp dir: {tmpdir}")

        # Create test files
        Path(tmpdir, "file1.txt").write_text("Test content 1")
        Path(tmpdir, "file2.py").write_text("print('hello')")
        Path(tmpdir, "subdir").mkdir()
        Path(tmpdir, "subdir", "file3.txt").write_text("Test content 3")

        config = {
            'embedded_tools': {
                'filesystem': {
                    'enabled': True,
                    'allowed_path': tmpdir,
                    'access_mode': 'read'
                }
            }
        }

        # Test listing
        result = execute_builtin_tool('list_files_recursive', {}, config=config)

        print(f"Success: {result['success']}")
        if result['success']:
            print(f"Total files: {result['result']['total_files']}")
            print(f"Total directories: {result['result']['total_directories']}")
            print(f"Files: {[f['path'] for f in result['result']['files']]}")

            assert result['result']['total_files'] == 3
            assert result['result']['total_directories'] == 1
            print("[PASS] List files working correctly")
        else:
            print(f"[FAIL] Error: {result['error']}")
            raise AssertionError(f"List files failed: {result['error']}")


def test_search_files():
    """Test search_files tool."""
    print("\n=== Test 5: Search Files ===")

    # Create temporary directory structure
    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"Using temp dir: {tmpdir}")

        # Create test files
        Path(tmpdir, "test_file1.txt").write_text("Test")
        Path(tmpdir, "test_file2.txt").write_text("Test")
        Path(tmpdir, "other.py").write_text("print('hello')")
        Path(tmpdir, "subdir").mkdir()
        Path(tmpdir, "subdir", "test_file3.txt").write_text("Test")

        config = {
            'embedded_tools': {
                'filesystem': {
                    'enabled': True,
                    'allowed_path': tmpdir,
                    'access_mode': 'read'
                }
            }
        }

        # Test searching for test_*.txt
        result = execute_builtin_tool('search_files', {'pattern': 'test_*.txt'}, config=config)

        print(f"Success: {result['success']}")
        if result['success']:
            print(f"Total matches: {result['result']['total_matches']}")
            print(f"Matches: {[m['path'] for m in result['result']['matches']]}")

            assert result['result']['total_matches'] == 3
            print("[PASS] Search files working correctly")
        else:
            print(f"[FAIL] Error: {result['error']}")
            raise AssertionError(f"Search files failed: {result['error']}")


def test_read_file_text():
    """Test read_file_text tool."""
    print("\n=== Test 6: Read Text File ===")

    # Create temporary directory with test file
    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"Using temp dir: {tmpdir}")

        test_content = "Hello, World!\nThis is a test file."
        test_file = Path(tmpdir, "test.txt")
        test_file.write_text(test_content)

        config = {
            'embedded_tools': {
                'filesystem': {
                    'enabled': True,
                    'allowed_path': tmpdir,
                    'access_mode': 'read'
                }
            }
        }

        # Test reading
        result = execute_builtin_tool('read_file_text', {'path': 'test.txt'}, config=config)

        print(f"Success: {result['success']}")
        if result['success']:
            print(f"Content: {result['result']['content'][:50]}...")
            print(f"Size: {result['result']['size_bytes']} bytes")

            assert result['result']['content'] == test_content
            print("[PASS] Read text file working correctly")
        else:
            print(f"[FAIL] Error: {result['error']}")
            raise AssertionError(f"Read file failed: {result['error']}")


def test_write_file():
    """Test write_file tool."""
    print("\n=== Test 7: Write File ===")

    # Create temporary directory
    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"Using temp dir: {tmpdir}")

        config = {
            'embedded_tools': {
                'filesystem': {
                    'enabled': True,
                    'allowed_path': tmpdir,
                    'access_mode': 'read_write'
                }
            }
        }

        # Test writing
        test_content = "Hello from write test!"
        result = execute_builtin_tool('write_file', {
            'path': 'output.txt',
            'content': test_content
        }, config=config)

        print(f"Success: {result['success']}")
        if result['success']:
            # Verify file was written
            written_content = Path(tmpdir, "output.txt").read_text()
            print(f"Written content: {written_content}")

            assert written_content == test_content
            print("[PASS] Write file working correctly")
        else:
            print(f"[FAIL] Error: {result['error']}")
            raise AssertionError(f"Write file failed: {result['error']}")


def test_write_disabled_in_read_mode():
    """Test that write operations fail in read-only mode."""
    print("\n=== Test 8: Write Disabled in Read-Only Mode ===")

    # Create temporary directory
    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"Using temp dir: {tmpdir}")

        config = {
            'embedded_tools': {
                'filesystem': {
                    'enabled': True,
                    'allowed_path': tmpdir,
                    'access_mode': 'read'  # Read-only mode
                }
            }
        }

        # Test writing (should fail)
        result = execute_builtin_tool('write_file', {
            'path': 'output.txt',
            'content': 'This should fail'
        }, config=config)

        print(f"Success: {result['success']}")
        print(f"Error: {result.get('error', 'N/A')}")

        # Should fail
        assert not result['success']
        assert 'disabled' in result.get('error', '').lower()

        print("[PASS] Write correctly disabled in read-only mode")


def test_path_security():
    """Test that path traversal is prevented."""
    print("\n=== Test 9: Path Security ===")

    # Create temporary directory
    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"Using temp dir: {tmpdir}")

        config = {
            'embedded_tools': {
                'filesystem': {
                    'enabled': True,
                    'allowed_path': tmpdir,
                    'access_mode': 'read'
                }
            }
        }

        # Test path traversal attempt
        result = execute_builtin_tool('read_file_text', {
            'path': '../../../etc/passwd'
        }, config=config)

        print(f"Success: {result['success']}")
        print(f"Error: {result.get('error', 'N/A')}")

        # Should fail
        assert not result['success']
        assert 'access denied' in result.get('error', '').lower() or 'outside allowed' in result.get('error', '').lower()

        print("[PASS] Path traversal correctly prevented")


def test_create_directories():
    """Test create_directories tool."""
    print("\n=== Test 10: Create Directories ===")

    # Create temporary directory
    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"Using temp dir: {tmpdir}")

        config = {
            'embedded_tools': {
                'filesystem': {
                    'enabled': True,
                    'allowed_path': tmpdir,
                    'access_mode': 'read_write'
                }
            }
        }

        # Test creating nested directories
        result = execute_builtin_tool('create_directories', {
            'path': 'data/processed/reports'
        }, config=config)

        print(f"Success: {result['success']}")
        if result['success']:
            # Verify directories were created
            dir_path = Path(tmpdir, "data", "processed", "reports")
            print(f"Directory exists: {dir_path.exists()}")

            assert dir_path.exists()
            assert dir_path.is_dir()
            print("[PASS] Create directories working correctly")
        else:
            print(f"[FAIL] Error: {result['error']}")
            raise AssertionError(f"Create directories failed: {result['error']}")


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("Testing Embedded Filesystem Tools")
    print("="*60)

    try:
        test_filesystem_tools_disabled()
        test_filesystem_tools_read_only()
        test_filesystem_tools_read_write()
        test_list_files()
        test_search_files()
        test_read_file_text()
        test_write_file()
        test_write_disabled_in_read_mode()
        test_path_security()
        test_create_directories()

        print("\n" + "="*60)
        print("ALL TESTS PASSED")
        print("="*60 + "\n")

    except AssertionError as e:
        print("\n" + "="*60)
        print(f"TEST FAILED: {e}")
        print("="*60 + "\n")
        sys.exit(1)
    except Exception as e:
        print("\n" + "="*60)
        print(f"UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        print("="*60 + "\n")
        sys.exit(1)


if __name__ == '__main__':
    main()

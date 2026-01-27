"""
Test script for embedded document and archive tools.

This tests the embedded document tools (MS Office, PDF) and archive tools (ZIP, TAR)
with different configurations.
"""

import os
import sys
import tempfile
import zipfile
import tarfile
from pathlib import Path

# Add parent directory to path to import modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from dtSpark.tools.builtin import get_builtin_tools, execute_builtin_tool


# ============================================================================
# Document Tools Tests
# ============================================================================

def test_document_tools_disabled():
    """Test that document tools are not loaded when disabled."""
    print("\n=== Test 1: Document Tools Disabled ===")

    config = {
        'embedded_tools': {
            'documents': {
                'enabled': False,
                'allowed_path': './test_data',
                'access_mode': 'read'
            }
        }
    }

    tools = get_builtin_tools(config=config)
    tool_names = [tool['name'] for tool in tools]

    print(f"Tools loaded: {tool_names}")

    # Should not have document tools
    assert 'read_word_document' not in tool_names
    assert 'read_excel_document' not in tool_names
    assert 'read_pdf_document' not in tool_names
    assert 'create_word_document' not in tool_names

    print("[PASS] Document tools correctly disabled")


def test_document_tools_read_only():
    """Test that document tools are loaded correctly in read-only mode."""
    print("\n=== Test 2: Document Tools Read-Only Mode ===")

    config = {
        'embedded_tools': {
            'documents': {
                'enabled': True,
                'allowed_path': './test_data',
                'access_mode': 'read',
                'max_file_size_mb': 50,
                'reading': {
                    'max_pdf_pages': 100,
                    'max_excel_rows': 10000
                }
            }
        }
    }

    tools = get_builtin_tools(config=config)
    tool_names = [tool['name'] for tool in tools]

    print(f"Tools loaded: {tool_names}")

    # Should have read tools
    assert 'get_file_info' in tool_names
    assert 'read_word_document' in tool_names
    assert 'read_excel_document' in tool_names
    assert 'read_powerpoint_document' in tool_names
    assert 'read_pdf_document' in tool_names

    # Should NOT have write tools
    assert 'create_word_document' not in tool_names
    assert 'create_excel_document' not in tool_names
    assert 'create_powerpoint_document' not in tool_names

    print("[PASS] Read-only document tools correctly loaded")


def test_document_tools_read_write():
    """Test that document tools are loaded correctly in read-write mode."""
    print("\n=== Test 3: Document Tools Read-Write Mode ===")

    config = {
        'embedded_tools': {
            'documents': {
                'enabled': True,
                'allowed_path': './test_data',
                'access_mode': 'read_write',
                'max_file_size_mb': 50,
                'reading': {
                    'max_pdf_pages': 100,
                    'max_excel_rows': 10000
                },
                'creation': {
                    'templates_path': None,
                    'default_author': 'Test Author'
                }
            }
        }
    }

    tools = get_builtin_tools(config=config)
    tool_names = [tool['name'] for tool in tools]

    print(f"Tools loaded: {tool_names}")

    # Should have all document tools including create
    assert 'get_file_info' in tool_names
    assert 'read_word_document' in tool_names
    assert 'read_excel_document' in tool_names
    assert 'read_powerpoint_document' in tool_names
    assert 'read_pdf_document' in tool_names
    assert 'create_word_document' in tool_names
    assert 'create_excel_document' in tool_names
    assert 'create_powerpoint_document' in tool_names

    print("[PASS] Read-write document tools correctly loaded")


def test_get_file_info():
    """Test get_file_info tool."""
    print("\n=== Test 4: Get File Info ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"Using temp dir: {tmpdir}")

        # Create test file
        test_file = Path(tmpdir, "test.txt")
        test_file.write_text("Hello World!")

        config = {
            'embedded_tools': {
                'documents': {
                    'enabled': True,
                    'allowed_path': tmpdir,
                    'access_mode': 'read'
                }
            }
        }

        result = execute_builtin_tool('get_file_info', {'path': 'test.txt'}, config=config)

        print(f"Success: {result['success']}")
        if result['success']:
            info = result['result']
            print(f"File: {info['filename']}")
            print(f"Extension: {info['extension']}")
            print(f"MIME type: {info['mime_type']}")
            print(f"Size: {info['size_bytes']} bytes")

            assert info['filename'] == 'test.txt'
            assert info['extension'] == '.txt'
            assert info['size_bytes'] > 0
            print("[PASS] Get file info working correctly")
        else:
            print(f"[FAIL] Error: {result['error']}")
            raise AssertionError(f"Get file info failed: {result['error']}")


def test_create_word_document():
    """Test create_word_document tool."""
    print("\n=== Test 5: Create Word Document ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"Using temp dir: {tmpdir}")

        config = {
            'embedded_tools': {
                'documents': {
                    'enabled': True,
                    'allowed_path': tmpdir,
                    'access_mode': 'read_write',
                    'creation': {
                        'default_author': 'Test Author'
                    }
                }
            }
        }

        result = execute_builtin_tool('create_word_document', {
            'path': 'test_output.docx',
            'content': {
                'title': 'Test Document',
                'paragraphs': [
                    {'text': 'This is a test paragraph.'},
                    {'text': 'Second paragraph with more text.'}
                ]
            }
        }, config=config)

        print(f"Success: {result['success']}")
        if result['success']:
            output_path = Path(tmpdir, 'test_output.docx')
            print(f"Created: {output_path.exists()}")
            print(f"Size: {output_path.stat().st_size} bytes")

            assert output_path.exists()
            assert output_path.stat().st_size > 0
            print("[PASS] Create Word document working correctly")
        else:
            print(f"[FAIL] Error: {result['error']}")
            raise AssertionError(f"Create Word document failed: {result['error']}")


def test_read_word_document():
    """Test read_word_document tool."""
    print("\n=== Test 6: Read Word Document ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"Using temp dir: {tmpdir}")

        # First create a Word document
        config = {
            'embedded_tools': {
                'documents': {
                    'enabled': True,
                    'allowed_path': tmpdir,
                    'access_mode': 'read_write'
                }
            }
        }

        # Create document
        create_result = execute_builtin_tool('create_word_document', {
            'path': 'test_read.docx',
            'content': {
                'title': 'Test Heading',
                'paragraphs': [
                    {'text': 'Test paragraph content.'}
                ]
            }
        }, config=config)

        if not create_result['success']:
            raise AssertionError(f"Failed to create test document: {create_result.get('error')}")

        # Now read it
        read_result = execute_builtin_tool('read_word_document', {
            'path': 'test_read.docx'
        }, config=config)

        print(f"Success: {read_result['success']}")
        if read_result['success']:
            data = read_result['result']
            print(f"Total paragraphs: {data['paragraph_count']}")
            all_text = ' '.join([p['text'] for p in data['paragraphs']])
            print(f"Content preview: {all_text[:100]}...")

            assert 'Test Heading' in all_text
            assert 'Test paragraph content' in all_text
            print("[PASS] Read Word document working correctly")
        else:
            print(f"[FAIL] Error: {read_result['error']}")
            raise AssertionError(f"Read Word document failed: {read_result['error']}")


def test_create_excel_document():
    """Test create_excel_document tool."""
    print("\n=== Test 7: Create Excel Document ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"Using temp dir: {tmpdir}")

        config = {
            'embedded_tools': {
                'documents': {
                    'enabled': True,
                    'allowed_path': tmpdir,
                    'access_mode': 'read_write'
                }
            }
        }

        result = execute_builtin_tool('create_excel_document', {
            'path': 'test_output.xlsx',
            'sheets': [
                {
                    'name': 'Sheet1',
                    'data': [
                        ['Name', 'Age', 'City'],
                        ['Alice', 30, 'Sydney'],
                        ['Bob', 25, 'Melbourne']
                    ]
                }
            ]
        }, config=config)

        print(f"Success: {result['success']}")
        if result['success']:
            output_path = Path(tmpdir, 'test_output.xlsx')
            print(f"Created: {output_path.exists()}")
            print(f"Size: {output_path.stat().st_size} bytes")

            assert output_path.exists()
            assert output_path.stat().st_size > 0
            print("[PASS] Create Excel document working correctly")
        else:
            print(f"[FAIL] Error: {result['error']}")
            raise AssertionError(f"Create Excel document failed: {result['error']}")


def test_read_excel_document():
    """Test read_excel_document tool."""
    print("\n=== Test 8: Read Excel Document ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"Using temp dir: {tmpdir}")

        config = {
            'embedded_tools': {
                'documents': {
                    'enabled': True,
                    'allowed_path': tmpdir,
                    'access_mode': 'read_write',
                    'reading': {
                        'max_excel_rows': 1000
                    }
                }
            }
        }

        # Create Excel document first
        create_result = execute_builtin_tool('create_excel_document', {
            'path': 'test_read.xlsx',
            'sheets': [
                {
                    'name': 'Data',
                    'data': [
                        ['Name', 'Value'],
                        ['Test1', 100],
                        ['Test2', 200]
                    ]
                }
            ]
        }, config=config)

        if not create_result['success']:
            raise AssertionError(f"Failed to create test Excel: {create_result.get('error')}")

        # Now read it
        read_result = execute_builtin_tool('read_excel_document', {
            'path': 'test_read.xlsx'
        }, config=config)

        print(f"Success: {read_result['success']}")
        if read_result['success']:
            data = read_result['result']
            print(f"Sheet names: {data['sheet_names']}")
            print(f"Sheets read: {data['sheets_read']}")

            assert len(data['sheet_names']) == 1
            assert 'Data' in data['sheet_names']
            # data is a dict where keys are sheet names
            assert data['data']['Data']['row_count'] == 3
            print("[PASS] Read Excel document working correctly")
        else:
            print(f"[FAIL] Error: {read_result['error']}")
            raise AssertionError(f"Read Excel document failed: {read_result['error']}")


def test_document_write_disabled_in_read_mode():
    """Test that document write operations fail in read-only mode."""
    print("\n=== Test 9: Document Write Disabled in Read-Only Mode ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"Using temp dir: {tmpdir}")

        config = {
            'embedded_tools': {
                'documents': {
                    'enabled': True,
                    'allowed_path': tmpdir,
                    'access_mode': 'read'  # Read-only mode
                }
            }
        }

        result = execute_builtin_tool('create_word_document', {
            'path': 'output.docx',
            'content': [{'type': 'paragraph', 'text': 'Test'}]
        }, config=config)

        print(f"Success: {result['success']}")
        print(f"Error: {result.get('error', 'N/A')}")

        # Should fail
        assert not result['success']

        print("[PASS] Document write correctly disabled in read-only mode")


# ============================================================================
# Archive Tools Tests
# ============================================================================

def test_archive_tools_disabled():
    """Test that archive tools are not loaded when disabled."""
    print("\n=== Test 10: Archive Tools Disabled ===")

    config = {
        'embedded_tools': {
            'archives': {
                'enabled': False,
                'allowed_path': './test_data',
                'access_mode': 'read'
            }
        }
    }

    tools = get_builtin_tools(config=config)
    tool_names = [tool['name'] for tool in tools]

    print(f"Tools loaded: {tool_names}")

    # Should not have archive tools
    assert 'list_archive_contents' not in tool_names
    assert 'read_archive_file' not in tool_names
    assert 'extract_archive' not in tool_names

    print("[PASS] Archive tools correctly disabled")


def test_archive_tools_read_only():
    """Test that archive tools are loaded correctly in read-only mode."""
    print("\n=== Test 11: Archive Tools Read-Only Mode ===")

    config = {
        'embedded_tools': {
            'archives': {
                'enabled': True,
                'allowed_path': './test_data',
                'access_mode': 'read',
                'max_file_size_mb': 100,
                'max_files_to_list': 1000
            }
        }
    }

    tools = get_builtin_tools(config=config)
    tool_names = [tool['name'] for tool in tools]

    print(f"Tools loaded: {tool_names}")

    # Should have read tools
    assert 'list_archive_contents' in tool_names
    assert 'read_archive_file' in tool_names

    # Should NOT have extract tool
    assert 'extract_archive' not in tool_names

    print("[PASS] Read-only archive tools correctly loaded")


def test_archive_tools_read_write():
    """Test that archive tools are loaded correctly in read-write mode."""
    print("\n=== Test 12: Archive Tools Read-Write Mode ===")

    config = {
        'embedded_tools': {
            'archives': {
                'enabled': True,
                'allowed_path': './test_data',
                'access_mode': 'read_write',
                'max_file_size_mb': 100,
                'max_files_to_list': 1000
            }
        }
    }

    tools = get_builtin_tools(config=config)
    tool_names = [tool['name'] for tool in tools]

    print(f"Tools loaded: {tool_names}")

    # Should have all archive tools including extract
    assert 'list_archive_contents' in tool_names
    assert 'read_archive_file' in tool_names
    assert 'extract_archive' in tool_names

    print("[PASS] Read-write archive tools correctly loaded")


def test_list_zip_contents():
    """Test list_archive_contents with a ZIP file."""
    print("\n=== Test 13: List ZIP Contents ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"Using temp dir: {tmpdir}")

        # Create a test ZIP file
        zip_path = Path(tmpdir, "test.zip")
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr('file1.txt', 'Content 1')
            zf.writestr('file2.txt', 'Content 2')
            zf.writestr('subdir/file3.txt', 'Content 3')

        config = {
            'embedded_tools': {
                'archives': {
                    'enabled': True,
                    'allowed_path': tmpdir,
                    'access_mode': 'read',
                    'max_files_to_list': 1000
                }
            }
        }

        result = execute_builtin_tool('list_archive_contents', {
            'path': 'test.zip'
        }, config=config)

        print(f"Success: {result['success']}")
        if result['success']:
            data = result['result']
            print(f"Archive type: {data['archive_type']}")
            print(f"File count: {data['total_files']}")
            print(f"Files: {[f['path'] for f in data['files']]}")

            assert data['archive_type'] == 'zip'
            assert data['total_files'] == 3
            print("[PASS] List ZIP contents working correctly")
        else:
            print(f"[FAIL] Error: {result['error']}")
            raise AssertionError(f"List ZIP contents failed: {result['error']}")


def test_list_tar_contents():
    """Test list_archive_contents with a TAR file."""
    print("\n=== Test 14: List TAR Contents ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"Using temp dir: {tmpdir}")

        # Create test files to add to tar
        Path(tmpdir, "file1.txt").write_text("Content 1")
        Path(tmpdir, "file2.txt").write_text("Content 2")

        # Create a test TAR file
        tar_path = Path(tmpdir, "test.tar.gz")
        with tarfile.open(tar_path, 'w:gz') as tf:
            tf.add(Path(tmpdir, "file1.txt"), arcname='file1.txt')
            tf.add(Path(tmpdir, "file2.txt"), arcname='file2.txt')

        config = {
            'embedded_tools': {
                'archives': {
                    'enabled': True,
                    'allowed_path': tmpdir,
                    'access_mode': 'read',
                    'max_files_to_list': 1000
                }
            }
        }

        result = execute_builtin_tool('list_archive_contents', {
            'path': 'test.tar.gz'
        }, config=config)

        print(f"Success: {result['success']}")
        if result['success']:
            data = result['result']
            print(f"Archive type: {data['archive_type']}")
            print(f"File count: {data['total_files']}")

            assert data['archive_type'] in ['tar', 'tar.gz', 'tgz']
            assert data['total_files'] == 2
            print("[PASS] List TAR contents working correctly")
        else:
            print(f"[FAIL] Error: {result['error']}")
            raise AssertionError(f"List TAR contents failed: {result['error']}")


def test_read_file_from_zip():
    """Test read_archive_file with a ZIP file."""
    print("\n=== Test 15: Read File from ZIP ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"Using temp dir: {tmpdir}")

        # Create a test ZIP file
        test_content = "Hello from inside the ZIP!"
        zip_path = Path(tmpdir, "test.zip")
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr('data/test.txt', test_content)

        config = {
            'embedded_tools': {
                'archives': {
                    'enabled': True,
                    'allowed_path': tmpdir,
                    'access_mode': 'read'
                }
            }
        }

        result = execute_builtin_tool('read_archive_file', {
            'archive_path': 'test.zip',
            'file_path': 'data/test.txt'
        }, config=config)

        print(f"Success: {result['success']}")
        if result['success']:
            data = result['result']
            print(f"Content: {data['content']}")

            assert data['content'] == test_content
            print("[PASS] Read file from ZIP working correctly")
        else:
            print(f"[FAIL] Error: {result['error']}")
            raise AssertionError(f"Read file from ZIP failed: {result['error']}")


def test_extract_archive():
    """Test extract_archive tool."""
    print("\n=== Test 16: Extract Archive ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"Using temp dir: {tmpdir}")

        # Create a test ZIP file
        zip_path = Path(tmpdir, "test.zip")
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr('extracted/file1.txt', 'Content 1')
            zf.writestr('extracted/file2.txt', 'Content 2')

        config = {
            'embedded_tools': {
                'archives': {
                    'enabled': True,
                    'allowed_path': tmpdir,
                    'access_mode': 'read_write'
                }
            }
        }

        result = execute_builtin_tool('extract_archive', {
            'archive_path': 'test.zip',
            'destination': 'output_dir'
        }, config=config)

        print(f"Success: {result['success']}")
        if result['success']:
            data = result['result']
            print(f"Extracted to: {data['destination']}")
            print(f"Files extracted: {data['files_extracted']}")

            # Verify extraction
            extracted_dir = Path(tmpdir, 'output_dir', 'extracted')
            assert extracted_dir.exists()
            assert (extracted_dir / 'file1.txt').exists()
            assert (extracted_dir / 'file2.txt').exists()
            print("[PASS] Extract archive working correctly")
        else:
            print(f"[FAIL] Error: {result['error']}")
            raise AssertionError(f"Extract archive failed: {result['error']}")


def test_archive_extract_disabled_in_read_mode():
    """Test that archive extraction fails in read-only mode."""
    print("\n=== Test 17: Archive Extract Disabled in Read-Only Mode ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"Using temp dir: {tmpdir}")

        # Create a test ZIP file
        zip_path = Path(tmpdir, "test.zip")
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr('file.txt', 'Content')

        config = {
            'embedded_tools': {
                'archives': {
                    'enabled': True,
                    'allowed_path': tmpdir,
                    'access_mode': 'read'  # Read-only mode
                }
            }
        }

        result = execute_builtin_tool('extract_archive', {
            'archive_path': 'test.zip',
            'destination': 'output'
        }, config=config)

        print(f"Success: {result['success']}")
        print(f"Error: {result.get('error', 'N/A')}")

        # Should fail
        assert not result['success']

        print("[PASS] Archive extraction correctly disabled in read-only mode")


def test_archive_path_security():
    """Test that path traversal is prevented for archives."""
    print("\n=== Test 18: Archive Path Security ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"Using temp dir: {tmpdir}")

        config = {
            'embedded_tools': {
                'archives': {
                    'enabled': True,
                    'allowed_path': tmpdir,
                    'access_mode': 'read'
                }
            }
        }

        # Test path traversal attempt
        result = execute_builtin_tool('list_archive_contents', {
            'path': '../../../etc/passwd.zip'
        }, config=config)

        print(f"Success: {result['success']}")
        print(f"Error: {result.get('error', 'N/A')}")

        # Should fail
        assert not result['success']
        assert 'access denied' in result.get('error', '').lower() or 'outside allowed' in result.get('error', '').lower()

        print("[PASS] Archive path traversal correctly prevented")


# ============================================================================
# Combined Tests
# ============================================================================

def test_all_tools_together():
    """Test that all tool categories can be enabled together."""
    print("\n=== Test 19: All Tools Enabled Together ===")

    config = {
        'embedded_tools': {
            'filesystem': {
                'enabled': True,
                'allowed_path': './test_data',
                'access_mode': 'read_write'
            },
            'documents': {
                'enabled': True,
                'allowed_path': './test_data',
                'access_mode': 'read_write'
            },
            'archives': {
                'enabled': True,
                'allowed_path': './test_data',
                'access_mode': 'read_write'
            }
        }
    }

    tools = get_builtin_tools(config=config)
    tool_names = [tool['name'] for tool in tools]

    print(f"Total tools loaded: {len(tool_names)}")
    print(f"Tools: {tool_names}")

    # Should have core tools
    assert 'get_current_datetime' in tool_names

    # Should have filesystem tools
    assert 'list_files_recursive' in tool_names
    assert 'read_file_text' in tool_names

    # Should have document tools
    assert 'read_word_document' in tool_names
    assert 'create_excel_document' in tool_names

    # Should have archive tools
    assert 'list_archive_contents' in tool_names
    assert 'extract_archive' in tool_names

    print("[PASS] All tool categories loaded correctly together")


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("Testing Embedded Document and Archive Tools")
    print("="*60)

    try:
        # Document tool configuration tests
        test_document_tools_disabled()
        test_document_tools_read_only()
        test_document_tools_read_write()

        # Document tool functionality tests
        test_get_file_info()
        test_create_word_document()
        test_read_word_document()
        test_create_excel_document()
        test_read_excel_document()
        test_document_write_disabled_in_read_mode()

        # Archive tool configuration tests
        test_archive_tools_disabled()
        test_archive_tools_read_only()
        test_archive_tools_read_write()

        # Archive tool functionality tests
        test_list_zip_contents()
        test_list_tar_contents()
        test_read_file_from_zip()
        test_extract_archive()
        test_archive_extract_disabled_in_read_mode()
        test_archive_path_security()

        # Combined tests
        test_all_tools_together()

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

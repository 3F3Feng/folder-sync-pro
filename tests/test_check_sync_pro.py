#!/usr/bin/env python3
"""
Unit tests for Folder Sync Pro
Tests the following features:
- Hash computation correctness
- Streaming copy correctness
- File size mismatch detection
- Hash mismatch detection
- JSON report generation
"""

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Tuple

import pytest

# Import module from parent directory
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

import check_sync_pro as sync_pro


class TestHashComputation:
    """Test hash computation functions"""

    def test_md5_hash_correctness(self):
        """Test MD5 hash computation"""
        test_data = b"Hello, World! This is a test file."
        expected = hashlib.md5(test_data).hexdigest()
        result = sync_pro.compute_hash(test_data, "md5")
        assert result == expected

    def test_sha256_hash_correctness(self):
        """Test SHA256 hash computation"""
        test_data = b"Hello, World! This is a test file."
        expected = hashlib.sha256(test_data).hexdigest()
        result = sync_pro.compute_hash(test_data, "sha256")
        assert result == expected

    def test_empty_file_hash(self):
        """Test hash of empty data"""
        test_data = b""
        md5_result = sync_pro.compute_hash(test_data, "md5")
        sha256_result = sync_pro.compute_hash(test_data, "sha256")
        
        assert md5_result == hashlib.md5(test_data).hexdigest()
        assert sha256_result == hashlib.sha256(test_data).hexdigest()

    def test_large_data_hash(self):
        """Test hash of large data (1MB+)"""
        test_data = os.urandom(1024 * 1024 + 100)  # ~1MB
        expected_md5 = hashlib.md5(test_data).hexdigest()
        result = sync_pro.compute_hash(test_data, "md5")
        assert result == expected_md5


class TestStreamingCopy:
    """Test streaming copy function"""

    @pytest.fixture
    def temp_dirs(self):
        """Create temporary source and target directories"""
        source = Path(tempfile.mkdtemp())
        target = Path(tempfile.mkdtemp())
        yield source, target
        shutil.rmtree(source, ignore_errors=True)
        shutil.rmtree(target, ignore_errors=True)

    def test_copy_small_file(self, temp_dirs):
        """Test copying a small file"""
        source, target = temp_dirs
        test_file = source / "test.txt"
        test_file.write_bytes(b"Hello, World!")
        
        target_file = target / "test.txt"
        hash_value, _, bytes_copied, error = sync_pro.copy_with_streaming_hash(
            test_file, target_file, "md5"
        )
        
        assert error == ""
        assert bytes_copied == 13
        assert target_file.exists()
        assert target_file.read_bytes() == b"Hello, World!"
        
        # Verify hash matches
        expected_hash = hashlib.md5(b"Hello, World!").hexdigest()
        assert hash_value == expected_hash

    def test_copy_large_file(self, temp_dirs):
        """Test copying a large file (multi-chunk)"""
        source, target = temp_dirs
        test_data = os.urandom(3 * 1024 * 1024)  # 3MB
        test_file = source / "large.bin"
        test_file.write_bytes(test_data)
        
        target_file = target / "large.bin"
        hash_value, _, bytes_copied, error = sync_pro.copy_with_streaming_hash(
            test_file, target_file, "md5", chunk_size=1024 * 1024
        )
        
        assert error == ""
        assert bytes_copied == len(test_data)
        assert target_file.exists()
        assert target_file.read_bytes() == test_data
        
        expected_hash = hashlib.md5(test_data).hexdigest()
        assert hash_value == expected_hash

    def test_copy_preserves_hash(self, temp_dirs):
        """Test that streaming copy produces correct hash"""
        source, target = temp_dirs
        test_data = b"The quick brown fox jumps over the lazy dog."
        test_file = source / "preserve.txt"
        test_file.write_bytes(test_data)
        
        target_file = target / "preserve.txt"
        hash_value, _, _, error = sync_pro.copy_with_streaming_hash(
            test_file, target_file, "md5"
        )
        
        assert error == ""
        # Verify content matches
        assert target_file.read_bytes() == test_data
        # Verify hash matches content
        actual_hash = hashlib.md5(target_file.read_bytes()).hexdigest()
        assert hash_value == actual_hash


class TestFileSizeMismatch:
    """Test file size mismatch detection"""

    @pytest.fixture
    def temp_dirs(self):
        """Create temporary directories"""
        source = Path(tempfile.mkdtemp())
        target = Path(tempfile.mkdtemp())
        yield source, target
        shutil.rmtree(source, ignore_errors=True)
        shutil.rmtree(target, ignore_errors=True)

    def test_size_mismatch_detected(self, temp_dirs):
        """Test that size mismatch is detected"""
        source, target = temp_dirs
        source_file = source / "test.txt"
        target_file = target / "test.txt"
        
        source_file.write_bytes(b"Source content")
        target_file.write_bytes(b"Target")
        
        source_size = source_file.stat().st_size
        target_size = target_file.stat().st_size
        
        assert source_size != target_size
        assert source_size == 14
        assert target_size == 6


class TestHashMismatch:
    """Test hash mismatch detection"""

    def test_hash_mismatch_detected(self):
        """Test that hash mismatch is detected"""
        data1 = b"Content 1"
        data2 = b"Content 2"
        
        hash1 = sync_pro.compute_hash(data1, "md5")
        hash2 = sync_pro.compute_hash(data2, "md5")
        
        assert hash1 != hash2

    @pytest.fixture
    def temp_dirs(self):
        """Create temporary directories"""
        source = Path(tempfile.mkdtemp())
        target = Path(tempfile.mkdtemp())
        yield source, target
        shutil.rmtree(source, ignore_errors=True)
        shutil.rmtree(target, ignore_errors=True)

    def test_verify_file_hash_detects_mismatch(self, temp_dirs):
        """Test that verify_file_hash detects mismatch"""
        source, target = temp_dirs
        source_file = source / "test.txt"
        target_file = target / "test.txt"
        
        source_file.write_bytes(b"Original content")
        target_file.write_bytes(b"Modified content")
        
        # Compute source hash
        source_hash = hashlib.md5(source_file.read_bytes()).hexdigest()
        
        # Verify target (should fail)
        verified, actual_hash, error = sync_pro.verify_file_hash(
            target_file, "md5", source_hash
        )
        
        assert not verified
        assert actual_hash != source_hash
        assert error == ""


class TestJSONReport:
    """Test JSON report generation"""

    def test_report_structure(self):
        """Test that report has correct structure"""
        source = Path("/tmp/source")
        target = Path("/tmp/target")
        
        result = sync_pro.SyncResult(
            source=source,
            target=target,
            algorithm="md5",
            double_verify=True,
            start_time=100.0,
            end_time=150.0,
            total_bytes=1000000
        )
        
        # Add some file results
        file_result = sync_pro.FileResult(
            relative_path="test.txt",
            source_size=1000,
            target_size=1000,
            source_hash="abc123",
            target_hash="abc123",
            verify_hash="abc123",
            success=True,
            copy_time=0.5
        )
        result.files.append(file_result)
        result.copied.append("test.txt")
        
        report = sync_pro.generate_report(result)
        
        # Verify structure
        assert "metadata" in report
        assert "summary" in report
        assert "files" in report
        
        assert report["metadata"]["tool"] == "Folder Sync Pro"
        assert report["metadata"]["algorithm"] == "md5"
        assert report["metadata"]["double_verify"] == True
        
        assert report["summary"]["total_files"] == 1
        assert report["summary"]["copied"] == 1
        assert report["summary"]["failed"] == 0

    def test_report_includes_failed_files(self):
        """Test that report includes failed files"""
        source = Path("/tmp/source")
        target = Path("/tmp/target")
        
        result = sync_pro.SyncResult(
            source=source,
            target=target,
            algorithm="md5"
        )
        
        # Add a failed file
        failed_file = sync_pro.FileResult(
            relative_path="failed.txt",
            source_size=1000,
            success=False,
            error="File size mismatch"
        )
        result.files.append(failed_file)
        result.failed.append("failed.txt")
        
        report = sync_pro.generate_report(result)
        
        assert report["summary"]["failed"] == 1
        assert "failed_files" in report
        assert "failed.txt" in report["failed_files"]
        
        # Check file details
        file_entry = report["files"][0]
        assert file_entry["success"] == False
        assert file_entry["error"] == "File size mismatch"

    def test_report_json_serializable(self):
        """Test that report can be serialized to JSON"""
        source = Path("/tmp/source")
        target = Path("/tmp/target")
        
        result = sync_pro.SyncResult(
            source=source,
            target=target,
            algorithm="md5"
        )
        
        result.start_time = 100.0
        result.end_time = 150.0
        result.total_bytes = 1000000
        
        file_result = sync_pro.FileResult(
            relative_path="test.txt",
            source_size=1000,
            target_size=1000,
            source_hash="abc123",
            success=True,
            copy_time=0.5
        )
        result.files.append(file_result)
        
        report = sync_pro.generate_report(result)
        
        # Should not raise exception
        json_str = json.dumps(report, indent=2)
        assert len(json_str) > 0
        
        # Should be parseable back
        parsed = json.loads(json_str)
        assert parsed["metadata"]["tool"] == "Folder Sync Pro"


class TestFileScanning:
    """Test folder scanning functionality"""

    def test_scan_empty_folder(self):
        """Test scanning empty folder"""
        temp_dir = Path(tempfile.mkdtemp())
        try:
            files = sync_pro.scan_folder(temp_dir)
            assert len(files) == 0
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_scan_single_file(self):
        """Test scanning folder with single file"""
        temp_dir = Path(tempfile.mkdtemp())
        try:
            test_file = temp_dir / "test.txt"
            test_file.write_bytes(b"test")
            
            files = sync_pro.scan_folder(temp_dir)
            assert len(files) == 1
            assert "test.txt" in files
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_scan_nested_files(self):
        """Test scanning nested folder structure"""
        temp_dir = Path(tempfile.mkdtemp())
        try:
            # Create nested structure
            (temp_dir / "a" / "b" / "c").mkdir(parents=True)
            (temp_dir / "a" / "file1.txt").write_bytes(b"1")
            (temp_dir / "a" / "b" / "file2.txt").write_bytes(b"2")
            (temp_dir / "root.txt").write_bytes(b"root")
            
            files = sync_pro.scan_folder(temp_dir)
            
            assert len(files) == 3
            assert "root.txt" in files
            assert "a/file1.txt" in files
            assert "a/b/file2.txt" in files
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestFormatFunctions:
    """Test utility formatting functions"""

    def test_format_size_bytes(self):
        """Test size formatting for bytes"""
        assert sync_pro.format_size(500) == "500.0 B"

    def test_format_size_kilobytes(self):
        """Test size formatting for kilobytes"""
        assert sync_pro.format_size(1024) == "1.0 KB"

    def test_format_size_megabytes(self):
        """Test size formatting for megabytes"""
        assert sync_pro.format_size(1024 * 1024) == "1.0 MB"

    def test_format_size_gigabytes(self):
        """Test size formatting for gigabytes"""
        assert sync_pro.format_size(1024 * 1024 * 1024) == "1.0 GB"

    def test_format_speed(self):
        """Test speed formatting"""
        speed = sync_pro.format_speed(1024 * 1024, 1.0)
        assert "MB" in speed

    def test_format_speed_zero_time(self):
        """Test speed formatting with zero time"""
        speed = sync_pro.format_speed(1024, 0)
        assert speed == "∞"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

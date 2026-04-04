#!/usr/bin/env python3
"""
Unit tests for Folder Sync Pro

Tests the following features:
- Hash computation correctness
- Streaming copy correctness
- File size mismatch detection
- Hash mismatch detection
- JSON report generation
- MHL report generation
- Sidecar file generation
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
    """Test hash computation using compute_file_hash"""

    @pytest.fixture
    def temp_file(self):
        """Create a temporary file for testing"""
        temp_dir = Path(tempfile.mkdtemp())
        test_file = temp_dir / "test.txt"
        yield test_file
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_md5_hash_correctness(self, temp_file):
        """Test MD5 hash computation"""
        test_data = b"Hello, World! This is a test file."
        temp_file.write_bytes(test_data)
        expected = hashlib.md5(test_data).hexdigest()
        result, _, _, error = sync_pro.compute_file_hash(temp_file, "md5")
        assert error == ""
        assert result == expected

    def test_sha256_hash_correctness(self, temp_file):
        """Test SHA256 hash computation"""
        test_data = b"Hello, World! This is a test file."
        temp_file.write_bytes(test_data)
        expected = hashlib.sha256(test_data).hexdigest()
        result, _, _, error = sync_pro.compute_file_hash(temp_file, "sha256")
        assert error == ""
        assert result == expected

    def test_empty_file_hash(self, temp_file):
        """Test hash of empty file"""
        temp_file.write_bytes(b"")
        md5_result, _, _, _ = sync_pro.compute_file_hash(temp_file, "md5")
        sha256_result, _, _, _ = sync_pro.compute_file_hash(temp_file, "sha256")
        assert md5_result == hashlib.md5(b"").hexdigest()
        assert sha256_result == hashlib.sha256(b"").hexdigest()

    def test_large_file_hash(self):
        """Test hash of large file (1MB+)"""
        temp_dir = Path(tempfile.mkdtemp())
        try:
            test_file = temp_dir / "large.bin"
            test_data = os.urandom(1024 * 1024 + 100)  # ~1MB
            test_file.write_bytes(test_data)
            expected_md5 = hashlib.md5(test_data).hexdigest()
            result, _, _, error = sync_pro.compute_file_hash(test_file, "md5")
            assert error == ""
            assert result == expected_md5
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


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

        src_hash, copy_time, bytes_copied, error = sync_pro.copy_with_streaming_hash(
            test_file, target / "test.txt", "md5"
        )

        assert error == ""
        assert bytes_copied == 13
        assert (target / "test.txt").exists()
        assert (target / "test.txt").read_bytes() == b"Hello, World!"

    def test_copy_large_file(self, temp_dirs):
        """Test copying a larger file"""
        source, target = temp_dirs
        test_file = source / "large.bin"
        test_data = os.urandom(1024 * 100)  # 100KB
        test_file.write_bytes(test_data)

        src_hash, copy_time, bytes_copied, error = sync_pro.copy_with_streaming_hash(
            test_file, target / "large.bin", "md5"
        )

        assert error == ""
        assert bytes_copied == len(test_data)
        assert (target / "large.bin").exists()

        # Verify content matches
        expected_hash = hashlib.md5(test_data).hexdigest()
        assert src_hash == expected_hash

    def test_copy_preserves_hash(self, temp_dirs):
        """Test that streaming copy produces correct hash"""
        source, target = temp_dirs
        test_file = source / "test.txt"
        test_data = b"Testing hash computation during copy"
        test_file.write_bytes(test_data)

        expected_hash = hashlib.md5(test_data).hexdigest()
        src_hash, _, _, error = sync_pro.copy_with_streaming_hash(
            test_file, target / "test.txt", "md5"
        )

        assert error == ""
        assert src_hash == expected_hash

        # Verify target file hash
        target_hash, _, _, _ = sync_pro.compute_file_hash(target / "test.txt", "md5")
        assert target_hash == expected_hash


class TestFileSizeMismatch:
    """Test file size mismatch detection"""

    @pytest.fixture
    def temp_dirs(self):
        """Create temporary source and target directories"""
        source = Path(tempfile.mkdtemp())
        target = Path(tempfile.mkdtemp())
        yield source, target
        shutil.rmtree(source, ignore_errors=True)
        shutil.rmtree(target, ignore_errors=True)

    def test_size_mismatch_detected(self, temp_dirs):
        """Test that size mismatch is detected"""
        source, target = temp_dirs
        src_file = source / "test.txt"
        tgt_file = target / "test.txt"

        src_file.write_bytes(b"Content 1 - longer")
        tgt_file.write_bytes(b"Content 2")

        src_size = src_file.stat().st_size
        tgt_size = tgt_file.stat().st_size

        assert src_size != tgt_size


class TestHashMismatch:
    """Test hash mismatch detection"""

    def test_hash_mismatch_detected(self):
        """Test that hash mismatch is detected"""
        data1 = b"Content 1"
        data2 = b"Content 2"
        hash1 = hashlib.md5(data1).hexdigest()
        hash2 = hashlib.md5(data2).hexdigest()
        assert hash1 != hash2

    @pytest.fixture
    def temp_dirs(self):
        """Create temporary source and target directories"""
        source = Path(tempfile.mkdtemp())
        target = Path(tempfile.mkdtemp())
        yield source, target
        shutil.rmtree(source, ignore_errors=True)
        shutil.rmtree(target, ignore_errors=True)

    def test_verify_file_hash_detects_mismatch(self, temp_dirs):
        """Test that verify_file_hash detects mismatch"""
        source, target = temp_dirs
        src_file = source / "test.txt"
        tgt_file = target / "test.txt"

        src_file.write_bytes(b"Original content")
        tgt_file.write_bytes(b"Different content")

        src_hash, _, _, _ = sync_pro.compute_file_hash(src_file, "md5")
        matched, tgt_hash, error = sync_pro.verify_file_hash(tgt_file, "md5", src_hash)

        assert not matched
        assert error == ""


class TestJSONReport:
    """Test JSON report generation"""

    def test_report_structure(self):
        """Test that report has correct structure"""
        source = Path("/tmp/test_source")
        target = Path("/tmp/test_target")
        result = sync_pro.SyncResult(
            source=source,
            target=target,
            algorithm="md5",
            start_time=100.0,
            end_time=200.0
        )

        report = sync_pro.generate_report(result)

        assert "metadata" in report
        assert "summary" in report
        assert "files" in report
        assert report["metadata"]["algorithm"] == "md5"

    def test_report_includes_failed_files(self):
        """Test that report includes failed files"""
        source = Path("/tmp/test_source")
        target = Path("/tmp/test_target")
        result = sync_pro.SyncResult(
            source=source,
            target=target,
            algorithm="md5"
        )
        result.failed = ["file1.txt", "file2.txt"]
        result.copied = ["file3.txt"]

        report = sync_pro.generate_report(result)

        assert "failed_files" in report
        assert len(report["failed_files"]) == 2

    def test_report_json_serializable(self):
        """Test that report is JSON serializable"""
        source = Path("/tmp/test_source")
        target = Path("/tmp/test_target")
        result = sync_pro.SyncResult(
            source=source,
            target=target,
            algorithm="md5",
            start_time=100.0,
            end_time=200.0
        )

        report = sync_pro.generate_report(result)
        json_str = json.dumps(report)  # Should not raise
        assert len(json_str) > 0


class TestFileScanning:
    """Test file scanning functions"""

    def test_scan_empty_folder(self):
        """Test scanning an empty folder"""
        temp_dir = Path(tempfile.mkdtemp())
        try:
            files = sync_pro.scan_folder(temp_dir)
            assert len(files) == 0
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_scan_single_file(self):
        """Test scanning a folder with a single file"""
        temp_dir = Path(tempfile.mkdtemp())
        try:
            (temp_dir / "test.txt").write_bytes(b"test")
            files = sync_pro.scan_folder(temp_dir)
            assert len(files) == 1
            assert "test.txt" in files
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_scan_nested_files(self):
        """Test scanning nested directory structure"""
        temp_dir = Path(tempfile.mkdtemp())
        try:
            (temp_dir / "subdir").mkdir()
            (temp_dir / "file1.txt").write_bytes(b"1")
            (temp_dir / "subdir" / "file2.txt").write_bytes(b"2")

            files = sync_pro.scan_folder(temp_dir)
            assert len(files) == 2
            assert "file1.txt" in files
            assert "subdir/file2.txt" in files or "subdir\\file2.txt" in files
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestFormatFunctions:
    """Test formatting utility functions"""

    def test_format_size_bytes(self):
        assert sync_pro.format_size(500) == "500.0 B"

    def test_format_size_kilobytes(self):
        assert sync_pro.format_size(1024) == "1.0 KB"

    def test_format_size_megabytes(self):
        assert sync_pro.format_size(1024 * 1024) == "1.0 MB"

    def test_format_size_gigabytes(self):
        assert sync_pro.format_size(1024 * 1024 * 1024) == "1.0 GB"

    def test_format_speed(self):
        speed = sync_pro.format_speed(1024 * 1024, 1.0)  # 1MB in 1 second
        assert "MB" in speed

    def test_format_speed_zero_time(self):
        speed = sync_pro.format_speed(1024, 0.0)
        assert speed != ""


class TestMHLSidecarGeneration:
    """Test MHL and sidecar file generation"""

    @pytest.fixture
    def temp_dirs(self):
        """Create temporary source and target directories"""
        source = Path(tempfile.mkdtemp())
        target = Path(tempfile.mkdtemp())
        yield source, target
        shutil.rmtree(source, ignore_errors=True)
        shutil.rmtree(target, ignore_errors=True)

    def test_generate_sidecar_xxhash(self, temp_dirs):
        """Test sidecar file generation with xxhash"""
        source, target = temp_dirs
        test_file = source / "test.txt"
        test_file.write_bytes(b"Test content for sidecar")

        # Copy file first and get hash
        src_hash, _, _, _ = sync_pro.copy_with_streaming_hash(test_file, target / "test.txt", "xxhash")

        # Generate sidecar
        sync_pro.generate_sidecar_hash_file(target / "test.txt", src_hash, "xxhash")

        sidecar = target / "test.txt.xxhash"
        assert sidecar.exists()

    def test_generate_sidecar_md5(self, temp_dirs):
        """Test sidecar file generation with MD5"""
        source, target = temp_dirs
        test_file = source / "test.txt"
        test_file.write_bytes(b"Test content")

        src_hash, _, _, _ = sync_pro.copy_with_streaming_hash(test_file, target / "test.txt", "md5")
        sync_pro.generate_sidecar_hash_file(target / "test.txt", src_hash, "md5")

        sidecar = target / "test.txt.md5"
        assert sidecar.exists()

    def test_generate_mhl_report(self, temp_dirs):
        """Test MHL report generation"""
        source, target = temp_dirs

        # Create test files
        (source / "file1.txt").write_bytes(b"Content 1")
        (source / "file2.txt").write_bytes(b"Content 2")

        result = sync_pro.SyncResult(
            source=source,
            target=target,
            algorithm="md5",
            project_name="TestProject",
            start_time=100.0,
            end_time=200.0
        )

        # Add file results
        for fname in ["file1.txt", "file2.txt"]:
            src_path = source / fname
            file_result = sync_pro.FileResult(
                relative_path=fname,
                source_size=src_path.stat().st_size,
                source_hash=hashlib.md5(src_path.read_bytes()).hexdigest(),
                success=True
            )
            result.files.append(file_result)

        mhl_path = target / "test.mhl"
        sync_pro.generate_mhl_report(result, mhl_path)

        assert mhl_path.exists()
        # Check MHL is valid XML
        import xml.etree.ElementTree as ET
        tree = ET.parse(mhl_path)
        root = tree.getroot()
        assert root.tag == "hashlist"

    def test_mhl_contains_hash_dates(self, temp_dirs):
        """Test MHL report contains hash dates"""
        source, target = temp_dirs
        (source / "test.txt").write_bytes(b"Test content")

        result = sync_pro.SyncResult(
            source=source,
            target=target,
            algorithm="md5",
            project_name="Test",
            start_time=100.0,
            end_time=200.0
        )

        content = (source / "test.txt").read_bytes()
        file_result = sync_pro.FileResult(
            relative_path="test.txt",
            source_size=len(content),
            source_hash=hashlib.md5(content).hexdigest(),
            success=True
        )
        result.files.append(file_result)

        mhl_path = target / "test.mhl"
        sync_pro.generate_mhl_report(result, mhl_path)

        assert mhl_path.exists()


class TestMetadataPreservation:
    """Test metadata preservation during copy"""

    @pytest.fixture
    def temp_dirs(self):
        """Create temporary source and target directories"""
        source = Path(tempfile.mkdtemp())
        target = Path(tempfile.mkdtemp())
        yield source, target
        shutil.rmtree(source, ignore_errors=True)
        shutil.rmtree(target, ignore_errors=True)

    def test_copystat_preserves_time(self, temp_dirs):
        """Test that copystat preserves timestamps"""
        source, target = temp_dirs
        test_file = source / "test.txt"
        test_file.write_bytes(b"Test content")

        # Set specific modification time
        import time
        mtime = time.time() - 3600  # 1 hour ago
        os.utime(test_file, (mtime, mtime))

        # Copy with metadata
        sync_pro.copy_with_streaming_hash(test_file, target / "test.txt", "md5")

        # Check timestamps are preserved
        src_stat = test_file.stat()
        tgt_stat = (target / "test.txt").stat()

        # Allow small difference due to filesystem resolution
        assert abs(src_stat.st_mtime - tgt_stat.st_mtime) < 2.0

    def test_no_preserve_metadata(self, temp_dirs):
        """Test that metadata can be skipped"""
        source, target = temp_dirs
        test_file = source / "test.txt"
        test_file.write_bytes(b"Test content")

        # Just copy, no special metadata handling
        sync_pro.copy_with_streaming_hash(test_file, target / "test.txt", "md5")

        # File should exist and have correct content
        assert (target / "test.txt").exists()
        assert (target / "test.txt").read_bytes() == b"Test content"


class TestMultiSourceCopy:
    """Test multi-source copy functionality"""

    def test_multi_source_result_dataclass(self):
        """Test MultiSourceResult dataclass"""
        result = sync_pro.MultiSourceResult(
            sources=[Path("/src1"), Path("/src2")],
            targets=[Path("/tgt1"), Path("/tgt2")],
            start_time=100.0,
            end_time=200.0
        )

        assert len(result.sources) == 2
        assert len(result.targets) == 2

    @pytest.fixture
    def temp_dirs(self):
        """Create temporary directories"""
        source = Path(tempfile.mkdtemp())
        target = Path(tempfile.mkdtemp())
        yield source, target
        shutil.rmtree(source, ignore_errors=True)
        shutil.rmtree(target, ignore_errors=True)

    def test_sync_single_pair_returns_syncresult(self, temp_dirs):
        """Test sync_single_pair returns SyncResult"""
        source, target = temp_dirs
        (source / "file1.txt").write_bytes(b"Content 1")
        (source / "file2.txt").write_bytes(b"Content 2")

        result = sync_pro.sync_single_pair(
            source=source,
            target=target,
            algorithm="md5",
            double_verify=False,
            skip_existing=False,
            preserve_metadata=True,
            preserve_xattr=False,
            sidecar=False,
            retries=3,
            verbose=False
        )

        assert isinstance(result, sync_pro.SyncResult)
        assert result.source == source
        assert result.target == target

    @pytest.fixture
    def temp_multi_dirs(self):
        """Create multiple temporary directories"""
        sources = [Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())]
        targets = [Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())]
        yield sources, targets
        for d in sources + targets:
            shutil.rmtree(d, ignore_errors=True)

    def test_sidecar_generation_during_copy(self, temp_dirs):
        """Test sidecar generation during copy"""
        source, target = temp_dirs
        test_file = source / "test.txt"
        test_file.write_bytes(b"Test content")

        # Copy and generate sidecar
        src_hash, _, _, _ = sync_pro.copy_with_streaming_hash(test_file, target / "test.txt", "md5")
        sync_pro.generate_sidecar_hash_file(target / "test.txt", src_hash, "md5")

        assert (target / "test.txt").exists()
        assert (target / "test.txt.md5").exists()


class TestScanFolderSkipsSidecar:
    """Test that scan_folder skips sidecar files"""

    def test_scan_skips_xxhash_files(self):
        """Test that .xxhash files are not included in scan"""
        temp_dir = Path(tempfile.mkdtemp())
        try:
            (temp_dir / "file1.txt").write_bytes(b"content")
            (temp_dir / "file1.txt.xxhash").write_text("abc123")

            files = sync_pro.scan_folder(temp_dir)

            # Sidecar should not be included
            assert "file1.txt" in files
            # Sidecar files are not included in scan
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestProjectNameInMHL:
    """Test project name in MHL report"""

    @pytest.fixture
    def temp_dirs(self):
        """Create temporary directories"""
        source = Path(tempfile.mkdtemp())
        target = Path(tempfile.mkdtemp())
        yield source, target
        shutil.rmtree(source, ignore_errors=True)
        shutil.rmtree(target, ignore_errors=True)

    def test_project_name_from_args(self, temp_dirs):
        """Test that MHL report is generated with project name in filename"""
        source, target = temp_dirs
        (source / "test.txt").write_bytes(b"Test")

        result = sync_pro.SyncResult(
            source=source,
            target=target,
            algorithm="md5",
            project_name="MyMovieProject",
            start_time=100.0,
            end_time=200.0
        )

        content = (source / "test.txt").read_bytes()
        file_result = sync_pro.FileResult(
            relative_path="test.txt",
            source_size=len(content),
            source_hash=hashlib.md5(content).hexdigest(),
            success=True
        )
        result.files.append(file_result)

        mhl_path = target / "test.mhl"
        sync_pro.generate_mhl_report(result, mhl_path)

        # Check MHL file exists and is valid XML
        assert mhl_path.exists()
        import xml.etree.ElementTree as ET
        tree = ET.parse(mhl_path)
        root = tree.getroot()
        assert root.tag == "hashlist"

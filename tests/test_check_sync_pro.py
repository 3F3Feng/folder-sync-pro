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


class TestMHLSidecarGeneration:
    """Test MHL report and sidecar hash file generation"""

    @pytest.fixture
    def temp_dirs(self):
        """Create temporary directories"""
        source = Path(tempfile.mkdtemp())
        target = Path(tempfile.mkdtemp())
        yield source, target
        shutil.rmtree(source, ignore_errors=True)
        shutil.rmtree(target, ignore_errors=True)

    def test_generate_sidecar_xxhash(self, temp_dirs):
        """Test generating xxhash sidecar file"""
        source, target = temp_dirs
        test_file = source / "test.txt"
        test_file.write_bytes(b"Hello, World!")
        
        # Compute hash
        hash_value = sync_pro.compute_hash(b"Hello, World!", "xxhash")
        
        # Generate sidecar file
        sidecar_path = sync_pro.generate_sidecar_hash_file(test_file, hash_value, "xxhash", target)
        
        assert sidecar_path is not None
        assert sidecar_path.exists()
        assert sidecar_path.name == "test.txt.xxhash"
        assert sidecar_path.read_text().strip() == hash_value

    def test_generate_sidecar_md5(self, temp_dirs):
        """Test generating MD5 sidecar file"""
        source, target = temp_dirs
        test_file = source / "test.txt"
        test_file.write_bytes(b"Hello, World!")
        
        # Compute hash
        hash_value = sync_pro.compute_hash(b"Hello, World!", "md5")
        
        # Generate sidecar file
        sidecar_path = sync_pro.generate_sidecar_hash_file(test_file, hash_value, "md5", target)
        
        assert sidecar_path is not None
        assert sidecar_path.exists()
        assert sidecar_path.name == "test.txt.md5"
        assert sidecar_path.read_text().strip() == hash_value

    def test_generate_mhl_report(self, temp_dirs):
        """Test generating MHL report"""
        source, target = temp_dirs
        
        # Create test files
        (source / "file1.txt").write_bytes(b"Content 1")
        (source / "file2.txt").write_bytes(b"Content 2")
        
        # Copy files and collect results
        result = sync_pro.SyncResult(
            source=source,
            target=target,
            algorithm="xxhash",
            project_name="TestProject",
            start_time=100.0,
            end_time=200.0
        )
        
        # Add file results
        for i, fname in enumerate(["file1.txt", "file2.txt"]):
            src_path = source / fname
            content = src_path.read_bytes()
            hash_value = sync_pro.compute_hash(content, "xxhash")
            
            file_result = sync_pro.FileResult(
                relative_path=fname,
                source_size=len(content),
                target_size=len(content),
                source_hash=hash_value,
                success=True,
                hash_date=sync_pro.datetime.now(sync_pro.timezone.utc)
            )
            result.files.append(file_result)
            result.copied.append(fname)
        
        result.total_bytes = sum(f.target_size for f in result.files)
        
        # Generate MHL report
        mhl_path = sync_pro.generate_mhl_report(result)
        
        assert mhl_path is not None
        assert mhl_path.exists()
        
        # Parse and verify MHL content - note: minidom formats XML differently
        content = mhl_path.read_text()
        assert '<?xml version="1.0"' in content
        assert '<hashlist version="1.1">' in content
        assert '<creatorinfo>' in content
        assert '<name>Folder Sync Pro</name>' in content
        assert '<xxhash64>' in content  # Using xxhash64 tag
        assert 'file1.txt' in content
        assert 'file2.txt' in content

    def test_mhl_contains_hash_dates(self, temp_dirs):
        """Test MHL report contains hash dates"""
        source, target = temp_dirs
        
        test_file = source / "test.txt"
        test_file.write_bytes(b"Test content")
        
        result = sync_pro.SyncResult(
            source=source,
            target=target,
            algorithm="md5",
            project_name="Test",
            start_time=100.0,
            end_time=200.0
        )
        
        content = test_file.read_bytes()
        hash_value = sync_pro.compute_hash(content, "md5")
        
        result.files.append(sync_pro.FileResult(
            relative_path="test.txt",
            source_size=len(content),
            target_size=len(content),
            source_hash=hash_value,
            success=True,
            hash_date=sync_pro.datetime(2024, 1, 15, 10, 30, tzinfo=sync_pro.timezone.utc)
        ))
        result.copied.append("test.txt")
        result.total_bytes = len(content)
        
        mhl_path = sync_pro.generate_mhl_report(result)
        content = mhl_path.read_text()
        
        assert '<hashdate>' in content


class TestMetadataPreservation:
    """Test metadata preservation functionality"""

    @pytest.fixture
    def temp_dirs(self):
        """Create temporary directories"""
        source = Path(tempfile.mkdtemp())
        target = Path(tempfile.mkdtemp())
        yield source, target
        shutil.rmtree(source, ignore_errors=True)
        shutil.rmtree(target, ignore_errors=True)

    def test_copystat_preserves_time(self, temp_dirs):
        """Test that shutil.copystat preserves timestamps"""
        source, target = temp_dirs
        
        test_file = source / "test.txt"
        test_file.write_bytes(b"Test content")
        
        # Get original timestamps
        original_stat = test_file.stat()
        original_mtime = original_stat.st_mtime
        
        # Copy with hash (which calls copystat internally)
        target_file = target / "test.txt"
        sync_pro.copy_with_streaming_hash(test_file, target_file, "md5", preserve_metadata=True)
        
        # Check timestamps are preserved
        assert target_file.exists()
        new_stat = target_file.stat()
        
        # Allow 1 second tolerance for filesystem timestamp precision
        assert abs(new_stat.st_mtime - original_mtime) < 1

    def test_no_preserve_metadata(self, temp_dirs):
        """Test copying without preserving metadata"""
        source, target = temp_dirs
        
        test_file = source / "test.txt"
        test_file.write_bytes(b"Test content")
        
        target_file = target / "test.txt"
        sync_pro.copy_with_streaming_hash(test_file, target_file, "md5", preserve_metadata=False)
        
        assert target_file.exists()


class TestMultiSourceCopy:
    """Test multi-source copy functionality"""

    @pytest.fixture
    def temp_dirs(self):
        """Create multiple temporary directories"""
        sources = [Path(tempfile.mkdtemp()) for _ in range(2)]
        targets = [Path(tempfile.mkdtemp()) for _ in range(2)]
        yield sources, targets
        for d in sources + targets:
            shutil.rmtree(d, ignore_errors=True)

    def test_multi_source_result_dataclass(self):
        """Test MultiSourceResult dataclass"""
        sources = [Path("/src1"), Path("/src2")]
        targets = [Path("/tgt1"), Path("/tgt2")]
        
        result = sync_pro.MultiSourceResult(
            sources=sources,
            targets=targets,
            start_time=100.0
        )
        
        assert len(result.sources) == 2
        assert len(result.targets) == 2
        assert result.start_time == 100.0
        assert result.results == []

    def test_sync_single_pair_returns_syncresult(self, temp_dirs):
        """Test sync_single_pair returns proper SyncResult"""
        sources, targets = temp_dirs
        
        # Create test files in source
        (sources[0] / "test.txt").write_bytes(b"Test content")
        
        result = sync_pro.sync_single_pair(
            source=sources[0],
            target=targets[0],
            algorithm="md5",
            double_verify=False,
            skip_existing=False,
            preserve_metadata=False,
            preserve_xattr=False,
            sidecar=False,
            retries=1,
            verbose=False
        )
        
        assert isinstance(result, sync_pro.SyncResult)
        assert result.source == sources[0]
        assert result.target == targets[0]
        assert len(result.copied) == 1
        assert result.copied[0] == "test.txt"

    def test_sidecar_generation_during_copy(self, temp_dirs):
        """Test sidecar files are generated during copy"""
        sources, targets = temp_dirs
        
        # Create test files
        (sources[0] / "test.txt").write_bytes(b"Test content")
        
        result = sync_pro.sync_single_pair(
            source=sources[0],
            target=targets[0],
            algorithm="xxhash",
            double_verify=False,
            skip_existing=False,
            preserve_metadata=False,
            preserve_xattr=False,
            sidecar=True,  # Enable sidecar
            retries=1,
            verbose=False
        )
        
        # Check sidecar file exists
        sidecar_file = targets[0] / "test.txt.xxhash"
        assert sidecar_file.exists()
        assert len(sidecar_file.read_text().strip()) > 0


class TestScanFolderSkipsSidecar:
    """Test that scan_folder skips sidecar files"""

    def test_scan_skips_xxhash_files(self):
        """Test that scan_folder skips .xxhash files"""
        temp_dir = Path(tempfile.mkdtemp())
        try:
            # Create normal files and sidecar files
            (temp_dir / "test.txt").write_bytes(b"content")
            (temp_dir / "test.txt.xxhash").write_text("hash123")
            (temp_dir / "test.txt.md5").write_text("hash456")
            (temp_dir / "subdir").mkdir()
            (temp_dir / "subdir" / "nested.txt").write_bytes(b"nested")
            
            files = sync_pro.scan_folder(temp_dir)
            
            # Should only include actual content files
            assert len(files) == 2
            assert "test.txt" in files
            assert "subdir/nested.txt" in files
            # Should NOT include sidecar files
            assert "test.txt.xxhash" not in files
            assert "test.txt.md5" not in files
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestProjectNameInMHL:
    """Test project name handling in MHL reports"""

    @pytest.fixture
    def temp_dirs(self):
        """Create temporary directories"""
        source = Path(tempfile.mkdtemp())
        target = Path(tempfile.mkdtemp())
        yield source, target
        shutil.rmtree(source, ignore_errors=True)
        shutil.rmtree(target, ignore_errors=True)

    def test_project_name_from_args(self, temp_dirs):
        """Test project name can be set from args"""
        source, target = temp_dirs
        
        test_file = source / "test.txt"
        test_file.write_bytes(b"Test")
        
        result = sync_pro.sync_single_pair(
            source=source,
            target=target,
            algorithm="md5",
            double_verify=False,
            skip_existing=False,
            preserve_metadata=False,
            preserve_xattr=False,
            sidecar=False,
            retries=1,
            verbose=False
        )
        
        # Manually set project name (as main() would)
        result.project_name = "MyCustomProject"
        
        # Generate MHL
        mhl_path = sync_pro.generate_mhl_report(result)
        
        # MHL filename should contain project name
        assert "MyCustomProject" in mhl_path.name

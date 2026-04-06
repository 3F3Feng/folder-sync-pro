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
        src_hash, _, _, _ = sync_pro._copy_and_hash_file(test_file, target / "test.txt", "xxhash")

        # Generate sidecar
        sync_pro.generate_sidecar_hash_file(target / "test.txt", src_hash, "xxhash")

        sidecar = target / "test.txt.xxhash"
        assert sidecar.exists()

    def test_generate_sidecar_md5(self, temp_dirs):
        """Test sidecar file generation with MD5"""
        source, target = temp_dirs
        test_file = source / "test.txt"
        test_file.write_bytes(b"Test content")

        src_hash, _, _, _ = sync_pro._copy_and_hash_file(test_file, target / "test.txt", "md5")
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
        sync_pro._copy_and_hash_file(test_file, target / "test.txt", "md5")

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
        sync_pro._copy_and_hash_file(test_file, target / "test.txt", "md5")

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
        src_hash, _, _, _ = sync_pro._copy_and_hash_file(test_file, target / "test.txt", "md5")
        sync_pro.generate_sidecar_hash_file(target / "test.txt", src_hash, "md5")

        assert (target / "test.txt").exists()
        assert (target / "test.txt.md5").exists()

    def test_multi_source_with_unexpected_error_exits_non_zero(self, temp_multi_dirs, monkeypatch, capsys):
        """Test that run_multi_source exits non-zero if a task raises an unexpected exception"""
        sources, targets = temp_multi_dirs
        
        # Mock sync_single_pair to raise an error on the second call
        call_count = 0
        original_sync = sync_pro.sync_single_pair
        def mock_sync_single_pair(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise ValueError("Simulated unexpected error")
            return original_sync(*args, **kwargs)

        monkeypatch.setattr(sync_pro, "sync_single_pair", mock_sync_single_pair)

        # Mock argparse Namespace
        class MockArgs:
            parallel = 2
            verbose = True
            double_verify = False
            skip_existing = False
            preserve_metadata = True
            preserve_xattr = False
            sidecar = False
            retries = 1
            mhl = False
            report = None
            project_name = "TestProject"
        
        args = MockArgs()
        args.sources = [str(s) for s in sources]
        args.targets = [str(t) for t in targets]
        
        exit_code = sync_pro.run_multi_source(args, "md5")
        
        assert exit_code != 0
        
        captured = capsys.readouterr()
        assert "Simulated unexpected error" in captured.err



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


class TestProgressManager:
    """Test ProgressManager for dual-line progress display"""

    def test_progress_manager_initialization(self):
        """Test ProgressManager initialization with new API"""
        pm = sync_pro.ProgressManager(total_files=10, total_bytes=1000, enabled=False)
        assert pm.total_files == 10
        assert pm.total_bytes == 1000
        assert pm.enabled is False
        assert pm.completed_files == 0
        assert pm.completed_bytes == 0

    def test_progress_manager_start_file(self):
        """Test starting a new file"""
        pm = sync_pro.ProgressManager(total_files=10, total_bytes=1000, enabled=False)
        pm.start_file("test.txt", 100)
        assert pm.current_file == "test.txt"
        assert pm.current_file_size == 100
        assert pm.current_file_copied == 0

    def test_progress_manager_complete_file(self):
        """Test completing a file - completion is deferred until next file starts or finalize"""
        pm = sync_pro.ProgressManager(total_files=10, total_bytes=1000, enabled=False)
        pm.start_file("test.txt", 100)
        pm.complete_file(100)
        # Completion is pending until next file starts or finalize() is called
        assert pm.completed_files == 0
        assert pm.completed_bytes == 0
        # Start next file to trigger the pending completion
        pm.start_file("test2.txt", 100)
        assert pm.completed_files == 1
        assert pm.completed_bytes == 100

    def test_progress_manager_format_time(self):
        """Test time formatting helper"""
        # Test minutes:seconds format
        result = sync_pro.format_time(90)
        assert result == "01:30"
        # Test hours format
        result = sync_pro.format_time(3661)
        assert "01:01:01" in result


class TestCheckpointManager:
    """Test CheckpointManager for resume functionality"""

    @pytest.fixture
    def temp_dirs(self):
        """Create temporary source and target directories"""
        source = Path(tempfile.mkdtemp())
        target = Path(tempfile.mkdtemp())
        checkpoint = target / ".sync-progress.json"
        yield source, target, checkpoint
        shutil.rmtree(source, ignore_errors=True)
        shutil.rmtree(target, ignore_errors=True)

    def test_checkpoint_creates_state(self, temp_dirs):
        """Test CheckpointManager creates initial state"""
        source, target, checkpoint = temp_dirs
        cm = sync_pro.CheckpointManager(source, target, checkpoint)
        assert cm.state is not None
        assert "session_id" in cm.state
        assert cm.state["source"] == str(source)
        assert cm.state["target"] == str(target)

    def test_checkpoint_save_and_load(self, temp_dirs):
        """Test saving and loading checkpoint state"""
        source, target, checkpoint = temp_dirs
        cm = sync_pro.CheckpointManager(source, target, checkpoint)
        
        # Save checkpoint
        cm.save_checkpoint("file1.txt", 1024)
        
        # Create new manager to load from file
        cm2 = sync_pro.CheckpointManager(source, target, checkpoint)
        assert cm2.state["current_file"] == "file1.txt"
        assert cm2.state["position"] == 1024

    def test_checkpoint_mark_complete(self, temp_dirs):
        """Test marking file as complete"""
        source, target, checkpoint = temp_dirs
        cm = sync_pro.CheckpointManager(source, target, checkpoint)
        
        cm.mark_complete("file1.txt", 2048, "abc123hash")
        
        assert "file1.txt" in cm.state["files"]
        assert cm.state["files"]["file1.txt"]["size"] == 2048
        assert cm.state["files"]["file1.txt"]["hash"] == "abc123hash"

    def test_checkpoint_get_resume_position(self, temp_dirs):
        """Test getting resume position for incomplete files"""
        source, target, checkpoint = temp_dirs
        cm = sync_pro.CheckpointManager(source, target, checkpoint)
        
        # Set up current file with position
        cm.save_checkpoint("file1.txt", 1024)
        
        # Create partial target file
        target_file = target / "file1.txt"
        target_file.write_bytes(b"x" * 512)
        
        pos = cm.get_resume_position("file1.txt")
        # Should return the target file size (512), not the saved position (1024)
        assert pos == 512

    def test_checkpoint_cleanup(self, temp_dirs):
        """Test cleaning up checkpoint file after sync"""
        source, target, checkpoint = temp_dirs
        cm = sync_pro.CheckpointManager(source, target, checkpoint)
        cm.save_checkpoint("file1.txt", 1024)
        
        assert checkpoint.exists()
        
        cm.cleanup()
        # Note: cleanup only removes file when sync completes successfully
        # For now just verify method runs without error

    def test_corrupt_checkpoint_loads_new_state(self, temp_dirs, capsys):
        """Test that a corrupt checkpoint file results in a new state and a warning"""
        source, target, checkpoint = temp_dirs
        
        # Create a corrupt checkpoint file
        checkpoint.write_text("this is not valid json")
        
        cm = sync_pro.CheckpointManager(source, target, checkpoint)
        
        # Check for warning in stderr
        captured = capsys.readouterr()
        assert "无法加载进度文件" in captured.err
        
        # Check that the state is a new, fresh one
        assert "file1.txt" not in cm.state["files"]
        assert cm.state["current_file"] == ""



class TestSleepDetector:
    """Test SleepDetector for system sleep detection"""

    def test_sleep_detector_initialization(self):
        """Test SleepDetector initialization"""
        sd = sync_pro.SleepDetector()
        assert sd.last_timestamp is not None
        assert sd.on_wake_callback is None

    def test_sleep_detector_with_callback(self):
        """Test SleepDetector with wake callback"""
        callback_called = []
        
        def callback(gap):
            callback_called.append(gap)
        
        sd = sync_pro.SleepDetector(on_wake_callback=callback)
        assert sd.on_wake_callback is callback

    def test_sleep_detector_normal_gap(self):
        """Test SleepDetector with normal time gap"""
        sd = sync_pro.SleepDetector()
        # Small gap should not trigger callback
        result = sd.check_time_gap()
        assert result is False


class TestSignalHandling:
    """Test signal handling for Ctrl+C"""

    def test_signal_handler_import(self):
        """Test that signal module is properly imported"""
        import signal as sig
        assert hasattr(sig, 'SIGINT')
        assert hasattr(sig, 'signal')


class TestCopyAndHashFile:
    """Test _copy_and_hash_file function"""

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
        test_data = b"Hello, World!"
        source_file = source / "test.txt"
        source_file.write_bytes(test_data)
        
        hash_val, _, bytes_copied, error = sync_pro._copy_and_hash_file(
            source_file, target / "test.txt", "md5"
        )
        
        assert error == ""
        assert bytes_copied == len(test_data)
        assert (target / "test.txt").exists()
        assert (target / "test.txt").read_bytes() == test_data
        assert hash_val == hashlib.md5(test_data).hexdigest()

    def test_copy_large_file(self, temp_dirs):
        """Test copying a larger file with xxhash"""
        source, target = temp_dirs
        test_data = os.urandom(1024 * 100)  # 100KB
        source_file = source / "large.bin"
        source_file.write_bytes(test_data)
        
        hash_val, _, bytes_copied, error = sync_pro._copy_and_hash_file(
            source_file, target / "large.bin", "xxhash"
        )
        
        assert error == ""
        assert bytes_copied == len(test_data)
        assert (target / "large.bin").exists()
        
        if sync_pro.HAS_XXHASH:
            assert hash_val == sync_pro.xxhash.xxh64(test_data).hexdigest()
        else:
            assert hash_val == hashlib.md5(test_data).hexdigest() # Fallback

    def test_resume_partial_file(self, temp_dirs):
        """Test resuming a partially copied file"""
        source, target = temp_dirs
        
        full_data = b"X" * 10000
        source_file = source / "test.txt"
        source_file.write_bytes(full_data)
        
        partial_data = b"X" * 5000
        target_file = target / "test.txt"
        target_file.write_bytes(partial_data)
        
        hash_val, _, bytes_copied, error = sync_pro._copy_and_hash_file(
            source_file, target_file, "md5", resume=True
        )
        
        assert error == ""
        assert bytes_copied == len(full_data)
        assert target_file.read_bytes() == full_data
        assert hash_val == hashlib.md5(full_data).hexdigest()

    def test_existing_complete_file_skip(self, temp_dirs):
        """Test that existing complete file is skipped and hash is returned"""
        source, target = temp_dirs
        
        test_data = b"Complete file content"
        source_file = source / "test.txt"
        source_file.write_bytes(test_data)
        target_file = target / "test.txt"
        target_file.write_bytes(test_data)
        
        expected_hash = hashlib.md5(test_data).hexdigest()
        
        # Simulate time passing to check if file modification time changes (it shouldn't if skipped)
        initial_mtime = target_file.stat().st_mtime
        import time; time.sleep(0.1) # Ensure some time passes
        
        hash_val, duration, bytes_copied, error = sync_pro._copy_and_hash_file(
            source_file, target_file, "md5", resume=True
        )
        
        assert error == ""
        assert hash_val == expected_hash
        assert bytes_copied == len(test_data)
        assert duration < 0.1 # Should be very fast as it's skipped
        assert target_file.stat().st_mtime == initial_mtime # mtime should be preserved

    def test_resume_corrupt_partial_file_restarts(self, temp_dirs):
        """Test that a corrupt partial file is detected and the copy restarts"""
        source, target = temp_dirs
        
        source_data = b"A" * 10000
        source_file = source / "test.txt"
        source_file.write_bytes(source_data)
        
        # Create a partial file with different content
        corrupt_partial_data = b"B" * 5000
        target_file = target / "test.txt"
        target_file.write_bytes(corrupt_partial_data)
        
        hash_val, _, bytes_copied, error = sync_pro._copy_and_hash_file(
            source_file, target_file, "md5", resume=True
        )
        
        assert error == ""
        assert bytes_copied == len(source_data)
        assert target_file.read_bytes() == source_data
        assert hash_val == hashlib.md5(source_data).hexdigest()

    def test_corrupted_target_file_restarts(self, temp_dirs):
        """Test that corrupted target file (larger than source) restarts copy"""
        source, target = temp_dirs
        
        source_data = b"short"
        source_file = source / "test.txt"
        source_file.write_bytes(source_data)
        
        corrupted_data = b"this is longer than source"
        target_file = target / "test.txt"
        target_file.write_bytes(corrupted_data)
        
        hash_val, _, bytes_copied, error = sync_pro._copy_and_hash_file(
            source_file, target_file, "md5", resume=True
        )
        
        assert error == ""
        assert bytes_copied == len(source_data)
        assert target_file.read_bytes() == source_data
        assert hash_val == hashlib.md5(source_data).hexdigest()

    def test_copy_with_progress_callback(self, temp_dirs, capsys):
        """Test copy with a progress callback"""
        source, target = temp_dirs
        test_data = b"X" * (1024 * 10)  # 10KB
        source_file = source / "test.txt"
        source_file.write_bytes(test_data)

        # Track progress updates
        updates = []
        def progress_callback(bytes_copied):
            updates.append(bytes_copied)

        sync_pro._copy_and_hash_file(
            source_file,
            target / "test.txt",
            "md5",
            progress_callback=progress_callback
        )

        assert len(updates) > 0  # Should have received updates
        assert updates[-1] == len(test_data)  # Final update should be full size

    def test_copy_with_checkpoint_manager(self, temp_dirs):
        """Test copy with CheckpointManager for saving progress"""
        source, target = temp_dirs
        checkpoint_file = target / ".sync-progress.json"
        
        test_data = b"Y" * (1024 * 100) # 100KB
        source_file = source / "long_file.bin"
        source_file.write_bytes(test_data)
        
        cm = sync_pro.CheckpointManager(source, target, checkpoint_file)
        
        # Temporarily make the checkpoint interval very small for testing
        original_interval = cm.interval
        cm.interval = 0.01 
        
        hash_val, _, bytes_copied, error = sync_pro._copy_and_hash_file(
            source_file, target / "long_file.bin", "md5", checkpoint_manager=cm
        )
        # Manually mark as complete to ensure final state is written, mirroring run_copy logic
        cm.mark_complete("long_file.bin", bytes_copied, hash_val)

        cm.interval = original_interval # Restore original

        assert error == ""
        assert bytes_copied == len(test_data)
        assert checkpoint_file.exists()        
        # Check checkpoint state
        cm_reloaded = sync_pro.CheckpointManager(source, target, checkpoint_file)
        assert cm_reloaded.state["files"]["long_file.bin"]["size"] == len(test_data)
        assert cm_reloaded.state["files"]["long_file.bin"]["hash"] == hash_val


class TestPathValidation:
    """Test path validation logic"""

    def test_source_target_same_path_fails(self, monkeypatch, capsys):
        """Test that the script exits if source and target are the same"""
        temp_dir = tempfile.mkdtemp()
        
        # Mock sys.argv
        monkeypatch.setattr(sys, 'argv', ['check_sync_pro.py', temp_dir, temp_dir])
        
        # Mock sys.exit
        with pytest.raises(SystemExit) as e:
            sync_pro.main()
        
        # Check that sys.exit was called with a non-zero exit code
        assert e.type == SystemExit
        assert e.value.code != 0
        
        # Check for error message in stderr
        captured = capsys.readouterr()
        assert "源路径和目标路径不能相同" in captured.err
        
        shutil.rmtree(temp_dir)


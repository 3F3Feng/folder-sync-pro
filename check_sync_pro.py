#!/usr/bin/env python3
"""
Folder Sync Pro - 拷卡校验工具(专业版)

用于拍摄结束后拷贝存储卡并确认文件完整性。

核心特性:
- 流式哈希:边拷贝边计算哈希,无需二次读取源文件
- 双重校验:拷贝后可二次校验目标文件
- 错误重试:IO 错误自动重试
- 详细报告:JSON 格式的完整校验报告
- xxHash 支持:比 MD5 快10倍(可选)

专业 DIT 功能:
- MHL 报告:生成 ASC MHL v1.1 标准校验报告
- 校验码文件:生成 .xxhash/.md5 伴随文件
- 多源拷贝:支持多张卡同时拷贝到多个目标
- 元数据保留:完整保留时间戳和扩展属性

重构说明:
- 使用 Mode 枚举明确区分三种运行模式
- 提取公共函数减少代码重复
- 简化 main() 函数至 20 行以内
- 代码结构按照: 数据类 → 核心函数 → 工具函数 → 报告函数 → 模式函数 → 入口
"""

# =============================================================================
# 1. Imports
# =============================================================================

import argparse
import hashlib
import json
import os
import shutil
import socket
import sys
import time
import signal
import threading
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Callable
from xml.dom import minidom

# =============================================================================
# 2. Constants & Enums
# =============================================================================

# 尝试导入 xxhash,失败则回退到 hashlib
try:
    import xxhash
    HAS_XXHASH = True
    DEFAULT_ALGORITHM = "xxhash"
except ImportError:
    HAS_XXHASH = False
    DEFAULT_ALGORITHM = "md5"

# 尝试导入 xattr (用于扩展属性保留)
try:
    import xattr
    HAS_XATTR = True
except ImportError:
    HAS_XATTR = False

# -----------------------------------------------------------------------------
# Output Stream Configuration
# - INFO, SUCCESS messages → stdout (progress, summary)
# - WARNING, ERROR messages → stderr
# - Progress bars (ANSI-controlled) → stdout
# -----------------------------------------------------------------------------


def get_terminal_width() -> int:
    """动态获取终端宽度,每次调用时重新计算以适应窗口 resize"""
    return shutil.get_terminal_size((80, 20)).columns


#向后兼容别名
TERMINAL_WIDTH = get_terminal_width()


class OutputManager:
    """统一输出接口管理器 - 替代分散的 print() 语句"""
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
    
    def info(self, msg: str):
        """INFO 级别消息 → stdout"""
        print(msg, file=sys.stdout)
    
    def success(self, msg: str):
        """SUCCESS 级别消息 → stdout"""
        print(msg, file=sys.stdout)
    
    def warning(self, msg: str):
        """WARNING 级别消息 → stderr"""
        print(msg, file=sys.stderr)
    
    def error(self, msg: str):
        """ERROR 级别消息 → stderr"""
        print(msg, file=sys.stderr)
    
    def verbose_info(self, msg: str):
        """VERBOSE INFO 级别消息 → stderr (only if verbose)"""
        if self.verbose:
            print(msg, file=sys.stderr)
    
    def progress_raw(self, msg: str):
        """原始进度消息 → stdout (ANSI 控制，不换行)"""
        sys.stdout.write(msg)
        sys.stdout.flush()
    
    def progress_clear_line(self):
        """清除当前行 → stdout"""
        terminal_width = shutil.get_terminal_size((80, 20)).columns
        sys.stdout.write(f"\r{' '.ljust(terminal_width)}\r")
        sys.stdout.flush()


class Mode(Enum):
    """运行模式枚举"""
    COPY = auto()    # 拷贝模式(默认)
    VERIFY = auto()  # 校验模式
    MULTI = auto()   # 多源拷贝模式


# =============================================================================
# 3. Data Classes
# =============================================================================

@dataclass
class FileResult:
    """单个文件的处理结果"""
    relative_path: str
    source_size: int
    target_size: int = 0
    source_hash: str = ""
    target_hash: str = ""
    verify_hash: str = ""  # 二次校验哈希
    copy_time: float = 0.0
    success: bool = False
    error: str = ""
    retries: int = 0
    hash_date: Optional[datetime] = None  # 哈希计算时间(MHL用)


@dataclass
class SyncResult:
    """整体同步结果"""
    source: Path
    target: Path
    files: List[FileResult] = field(default_factory=list)
    copied: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)  # 已存在且一致
    failed: List[str] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0
    total_bytes: int = 0
    algorithm: str = "md5"
    double_verify: bool = False
    project_name: str = ""  # 项目名称(MHL用)


@dataclass
class MultiSourceResult:
    """多源拷贝结果"""
    sources: List[Path]
    targets: List[Path]
    results: List[SyncResult] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0


# 临时前向声明,避免循环依赖
ProgressManager = None
CheckpointManager = None
SleepDetector = None


def get_hash_func(algorithm: str):
    """获取哈希函数"""
    if algorithm == "xxhash" and HAS_XXHASH:
        return xxhash.xxh64()
    elif algorithm == "md5":
        return hashlib.md5()
    elif algorithm == "sha256":
        return hashlib.sha256()
    else:
        return hashlib.md5()


def compute_file_hash(
    file_path: Path,
    algorithm: str,
    retries: int = 3
) -> Tuple[str, float, int, str]:
    """
    计算文件的哈希值

    返回: (哈希值, 耗时, 读取字节数, 错误信息)
    """
    hash_func = get_hash_func(algorithm)
    bytes_read = 0
    start_time = time.time()
    last_error = ""

    for attempt in range(retries):
        try:
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(1024 * 1024)  # 1MB chunks
                    if not chunk:
                        break
                    hash_func.update(chunk)
                    bytes_read += len(chunk)
            return hash_func.hexdigest(), time.time() - start_time, bytes_read, ""
        except (OSError, IOError) as e:
            last_error = str(e)
            if attempt < retries - 1:
                wait_time = 2 ** attempt
                time.sleep(wait_time)

    return "", time.time() - start_time, bytes_read, last_error


# =============================================================================
# 4a. Classes (ProgressManager, CheckpointManager, SleepDetector)
# =============================================================================

# NOTE: The following functions will reference these classes, so they are defined first.
# See below for copy_with_resume and copy_with_streaming_hash


def _copy_and_hash_file(
    source_path: Path,
    target_path: Path,
    algorithm: str,
    chunk_size: int = 1024 * 1024,
    retries: int = 3,
    preserve_metadata: bool = True,
    preserve_xattr: bool = False,
    checkpoint_manager: Optional[CheckpointManager] = None,
    progress_callback: Optional[Callable[[int], None]] = None,
    resume: bool = False,
) -> Tuple[str, float, int, str]:
    """
    Copies a file with streaming hash calculation, retries, and resume support.

    Returns: (hash_value, time_taken, bytes_copied, error_message)
    """
    source_size = source_path.stat().st_size
    hash_func = get_hash_func(algorithm)
    bytes_copied = 0
    start_time = time.time()
    last_checkpoint_time = start_time
    last_error = ""

    # --- Resume Logic ---
    if resume and target_path.exists():
        current_target_size = target_path.stat().st_size
        if current_target_size > source_size:
            # Corrupted target, start from scratch
            try:
                target_path.unlink()
                bytes_copied = 0
            except OSError as e:
                return "", time.time() - start_time, 0, f"Failed to delete corrupted target file: {e}"
        elif current_target_size == source_size:
            # File might be complete, verify hash
            print(f"✅ {target_path} exists and size matches. Verifying hash...", file=sys.stderr)
            hash_val, _, _, err = compute_file_hash(target_path, algorithm)
            if not err:
                # If hash matches, we can skip. Here we return the hash as if we copied it.
                return hash_val, 0.0, source_size, ""
            else:
                 print(f"⚠️ Verification failed ({err}), re-copying.", file=sys.stderr)
                 bytes_copied = 0
        else: # current_target_size < source_size
            # Partial file exists, verify its integrity before resuming
            print(f"🔄 Partial file found at {target_path}. Verifying {format_size(current_target_size)}... ")

            # Hash the initial part of the source file
            source_partial_hash_func = get_hash_func(algorithm)
            try:
                with open(source_path, 'rb') as f:
                    # Read only up to current_target_size
                    remaining = current_target_size
                    while remaining > 0:
                        chunk = f.read(min(chunk_size, remaining))
                        if not chunk: break
                        source_partial_hash_func.update(chunk)
                        remaining -= len(chunk)

                # Hash the existing target file
                target_partial_hash, _, _, _ = compute_file_hash(target_path, algorithm)

                if source_partial_hash_func.hexdigest() == target_partial_hash:
                    print(f"✅ Integrity confirmed. Resuming from {format_size(current_target_size)}")
                    # The hash_func needs to be brought to the same state
                    hash_func = source_partial_hash_func
                    bytes_copied = current_target_size
                else:
                    print(f"⚠️ Partial file is corrupt. Starting over.", file=sys.stderr)
                    bytes_copied = 0
            except (OSError, IOError) as e:
                print(f"⚠️ Could not verify partial file ({e}), starting over.", file=sys.stderr)
                bytes_copied = 0

    # --- Copy Logic ---
    open_mode = 'ab' if bytes_copied > 0 else 'wb'

    for attempt in range(retries):
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with open(source_path, 'rb') as src, open(target_path, open_mode) as tgt:
                src.seek(bytes_copied)

                while True:
                    chunk = src.read(chunk_size)
                    if not chunk:
                        break # End of source file

                    hash_func.update(chunk)
                    tgt.write(chunk)
                    bytes_copied += len(chunk)

                    if progress_callback:
                        progress_callback(bytes_copied)

                    now = time.time()
                    if checkpoint_manager and now - last_checkpoint_time > checkpoint_manager.interval:
                        rel_path = str(source_path.relative_to(checkpoint_manager.source))
                        checkpoint_manager.save_checkpoint(rel_path, bytes_copied)
                        last_checkpoint_time = now

            # --- Finalization ---
            if preserve_metadata:
                shutil.copystat(source_path, target_path)
            if preserve_xattr and HAS_XATTR:
                try:
                    xattr.copyxattr(str(source_path), str(target_path))
                except Exception:
                    pass # Ignore errors if xattr fails

            return hash_func.hexdigest(), time.time() - start_time, bytes_copied, ""

        except (OSError, IOError) as e:
            last_error = str(e)
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            # On final retry failure, break loop

    return "", time.time() - start_time, bytes_copied, last_error


def verify_file_hash(
    file_path: Path,
    algorithm: str,
    expected_hash: str,
    retries: int = 3,
    file_name: str = "",
    total_size: int = 0
) -> Tuple[bool, str, str]:
    """
    校验文件哈希值

    返回: (是否匹配, 实际哈希, 错误信息)
    """
    last_error = ""
    # 获取终端宽度(动态),预留1个字符用于清除行尾
    terminal_width = get_terminal_width() - 1

    for attempt in range(retries):
        bytes_read = 0
        last_update_time = 0
        last_update_bytes = 0
        try:
            hash_func = get_hash_func(algorithm)
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(1024 * 1024)
                    if not chunk:
                        break
                    hash_func.update(chunk)
                    bytes_read += len(chunk)

                    now = time.time()
                    if total_size > 0 and (now - last_update_time > 0.25 or bytes_read == total_size):
                        elapsed_since_last_update = now - last_update_time
                        bytes_since_last_update = bytes_read - last_update_bytes
                        realtime_speed = bytes_since_last_update / elapsed_since_last_update if elapsed_since_last_update > 0 else 0
                        speed_str = format_speed(bytes_since_last_update, elapsed_since_last_update)

                        pct = (bytes_read / total_size) * 100 if total_size > 0 else 0

                        remaining_bytes = total_size - bytes_read
                        eta_seconds = remaining_bytes / realtime_speed if realtime_speed > 0 and remaining_bytes > 0 else 0

                        bar_length = 30
                        filled = int(bar_length * pct / 100)
                        bar = '█' * filled + '░' * (bar_length - filled)

                        name_part = (file_name[:30] + "..") if len(file_name) > 30 else file_name
                        if not name_part: name_part = file_path.name

                        progress_msg = f"🔍 Verifying: [{name_part:<30}] {bar} {pct:5.1f}% | {speed_str:>10} | ETA: {format_time(eta_seconds):>6}"

                        # Pad with spaces to clear the line
                        sys.stdout.write(f"\r{progress_msg.ljust(terminal_width)}")
                        sys.stdout.flush()
                        last_update_time = now
                        last_update_bytes = bytes_read

            # Clear the line on completion
            sys.stdout.write(f"\r{' '.ljust(terminal_width)}\r")
            sys.stdout.flush()

            actual_hash = hash_func.hexdigest()
            return actual_hash == expected_hash, actual_hash, ""
        except (OSError, IOError) as e:
            last_error = str(e)
            sys.stdout.write("\n") # Move to next line after error
            if attempt < retries - 1:
                wait_time = 2 ** attempt
                time.sleep(wait_time)

    return False, "", last_error


# =============================================================================
# 5. Utility Functions (格式化、扫描)
# =============================================================================

def scan_folder(folder: Path, verbose: bool = False) -> Dict[str, Path]:
    """递归扫描文件夹,返回相对路径到完整路径的映射"""
    files = {}
    if verbose:
        print(f"🔍 扫描: {folder}", file=sys.stderr)
    for root, _, filenames in os.walk(folder):
        for filename in filenames:
            if filename.endswith('.xxhash') or filename.endswith('.md5'):
                continue
            full_path = Path(root) / filename
            rel_path = str(full_path.relative_to(folder))
            files[rel_path] = full_path
    return files


def scan_and_compare(source: Path, target: Path, verbose: bool = False) -> dict:
    """
    扫描并对比两个文件夹

    返回: {
        'common': set,       # 共同文件
        'only_source': set,  # 仅源存在
        'only_target': set,  # 仅目标存在
        'source_files': dict,
        'target_files': dict
    }
    """
    source_files = scan_folder(source, verbose)
    target_files = scan_folder(target, verbose)

    source_set = set(source_files.keys())
    target_set = set(target_files.keys())

    return {
        'common': source_set & target_set,
        'only_source': source_set - target_set,
        'only_target': target_set - source_set,
        'source_files': source_files,
        'target_files': target_files
    }


def format_time(seconds: float) -> str:
    """格式化时间"""
    if seconds >= 3600:
        return time.strftime("%H:%M:%S", time.gmtime(seconds))
    else:
        return time.strftime("%M:%S", time.gmtime(seconds))


class ProgressManager:
    """双行进度显示管理器(总进度 + 当前文件进度)"""

    def __init__(self, total_files: int, total_bytes: int, enabled: bool = True):
        self.total_files = total_files
        self.total_bytes = total_bytes
        self.completed_files = 0
        self.completed_bytes = 0
        self.current_file = ""
        self.current_file_size = 0
        self.current_file_copied = 0
        self.start_time = time.time()
        self.file_start_time = self.start_time
        self.last_update = self.start_time
        self.enabled = enabled
        self.terminal_width = TERMINAL_WIDTH
        self._lock = threading.Lock()
        self._first_render = True  # Track if this is the first render
        self._pending_file = False  # Track if we have a file waiting to be rendered
        self._skip_current_file = False  # Track if current file should be skipped (for flicker prevention)
        self._pending_skip_current_file = False  # Track if pending file was skipped
        self._pending_completed_files = 0  # Track files to be marked complete when next file starts
        self._pending_completed_bytes = 0
        
    def start_file(self, filename: str, file_size: int, skipped: bool = False):
        """Start tracking a new file. Use skipped=True to mark file as already complete (no render)."""
        with self._lock:
            # If there was a previous file that just completed, apply its completion counters
            if self._pending_file:
                self.completed_files += self._pending_completed_files
                self.completed_bytes += self._pending_completed_bytes
                self._pending_completed_files = 0
                self._pending_completed_bytes = 0
                # Only render if the previous file was NOT skipped (had actual progress)
                # or if this is not the first file we ever started
                if not self._pending_skip_current_file or not self._first_render:
                    self._render_unlocked(final=True)
                self._pending_file = False

            self.current_file = filename
            self.current_file_size = file_size
            self.current_file_copied = 0
            self.file_start_time = time.time()
            self._skip_current_file = skipped
            
            if skipped:
                # For skipped files, mark as complete but DON'T render yet
                # Defer rendering to when the next file starts to avoid flicker
                self.current_file_copied = file_size
                self._pending_file = True
                self._pending_skip_current_file = True
                self._pending_completed_files = 1
                self._pending_completed_bytes = file_size
            else:
                self._pending_skip_current_file = False
            # Don't render here - wait for update_file_progress or next file
        
    def update_file_progress(self, bytes_copied: int):
        with self._lock:
            self.current_file_copied = bytes_copied
            self._skip_current_file = False
            self._render_unlocked()
        
    def complete_file(self, file_size: int):
        with self._lock:
            # If file was skipped (already rendered), don't set pending flags
            if self._skip_current_file:
                return
            # Mark as pending - will be applied when next file starts
            self._pending_completed_files = 1
            self._pending_completed_bytes = file_size
            self._pending_file = True  # Flag that there's a pending completion
            self._pending_skip_current_file = False  # This was a real copy, not skipped
            # Don't render here - let the next start_file or update_file_progress trigger render
            # This prevents showing progress for a file that's already complete
    
    def finalize(self):
        """Finalize progress display - render any pending file."""
        with self._lock:
            if self._pending_file:
                # Apply the pending completion counters before rendering
                self.completed_files += self._pending_completed_files
                self.completed_bytes += self._pending_completed_bytes
                self._pending_completed_files = 0
                self._pending_completed_bytes = 0
                # Pass the pending skip flag to render
                self._render_unlocked(final=True, skipped=self._pending_skip_current_file)
                self._pending_file = False

    def _render_unlocked(self, final: bool = False, skipped: bool = None):
        """Internal render without lock - caller must hold lock. final=True forces render of completed state.
        
        Args:
            final: If True, always render even if throttled
            skipped: Override for skip detection. If None, uses self._skip_current_file.
        """
        if not self.enabled:
            return
        # Dynamically get terminal width for each render (handles window resize)
        terminal_width = shutil.get_terminal_size((80, 20)).columns
        # Use provided skipped value or fall back to instance variable
        effective_skipped = skipped if skipped is not None else self._skip_current_file
        if effective_skipped and not final:
            return  # Don't render skipped files unless forced

        now = time.time()
        if not final and now - self.last_update < 0.25 and self.current_file_copied < self.current_file_size:
            return
        self.last_update = now

        # For skipped files, current_file_copied equals file_size immediately
        # But we don't add it to total_progress_bytes since the file is already in completed_bytes
        # Only add current_file_copied if it's less than file_size (i.e., file is actually being copied)
        if self._skip_current_file:
            # Skipped file: current_file_copied is just for display (file_pct), not actual progress
            total_progress_bytes = self.completed_bytes
            remaining_bytes = self.total_bytes - total_progress_bytes
            total_pct = (total_progress_bytes / self.total_bytes * 100) if self.total_bytes > 0 else 100
            file_pct = (self.current_file_copied / self.current_file_size * 100) if self.current_file_size > 0 else 100
        else:
            # Normal file being copied
            total_progress_bytes = self.completed_bytes + self.current_file_copied
            remaining_bytes = self.total_bytes - total_progress_bytes
            total_pct = (total_progress_bytes / self.total_bytes * 100) if self.total_bytes > 0 else 100
            file_pct = (self.current_file_copied / self.current_file_size * 100) if self.current_file_size > 0 else 100

        elapsed = now - self.start_time
        # Use actual transfer speed (based on total elapsed time, not just completed bytes)
        # This includes current file progress for accurate ETA
        avg_speed = total_progress_bytes / elapsed if elapsed > 0 else 0
        total_eta = remaining_bytes / avg_speed if avg_speed > 0 else 0

        file_elapsed = now - self.file_start_time
        file_speed = self.current_file_copied / file_elapsed if file_elapsed > 0 else 0
        remaining_file_bytes = self.current_file_size - self.current_file_copied
        file_eta = remaining_file_bytes / file_speed if file_speed > 0 else 0

        total_bar = self._make_bar(total_pct, 20)
        file_bar = self._make_bar(file_pct, 20)

        # Show basename of file (last component of path) to avoid truncation
        import os
        name_display = os.path.basename(self.current_file)[:25].ljust(25)
        if terminal_width >= 100:
            line1 = "总进度: " + total_bar + " " + format(total_pct, '5.1f') + "% | " + str(self.completed_files) + "/" + str(self.total_files) + " | " + format_size(self.completed_bytes) + "/" + format_size(self.total_bytes) + " | ETA: " + format_time(total_eta)
            line2 = "当前:   " + file_bar + " " + format(file_pct, '5.1f') + "% | " + name_display + " | " + format_size(self.current_file_copied) + "/" + format_size(self.current_file_size) + " | " + format_speed(self.current_file_copied, file_elapsed) + " | ETA: " + format_time(file_eta)
        else:
            line1 = "总进度: " + total_bar + " " + format(total_pct, '5.1f') + "% | " + str(self.completed_files) + "/" + str(self.total_files)
            line2 = "当前:   " + file_bar + " " + format(file_pct, '5.1f') + "% | " + name_display

        # Use ANSI cursor control: move up 2 lines, clear lines, print new content
        if self._first_render:
            # First render: just print, don't try to clear previous lines
            output = line1 + chr(10) + chr(27) + "[K" + line2 + chr(10)
            self._first_render = False
        else:
            # Subsequent renders: move up 2 lines and overwrite
            output = chr(27) + "[2A" + chr(27) + "[K" + line1 + chr(10) + chr(27) + "[K" + line2 + chr(10)
        sys.stdout.write(output)
        sys.stdout.flush()

    def print_progress_line(self, current: int, total: int, current_file: str, stats: dict):
        """Print single-line progress (mirrors legacy print_progress function)."""
        pct = (current / total) * 100 if total > 0 else 0
        bar_len = 30
        filled = int(bar_len * current / total) if total > 0 else 0
        bar = chr(9608) * filled + chr(9601) * (bar_len - filled)
        display_name = current_file[:40] + "..." if len(current_file) > 40 else current_file
        speed = format_speed(stats.get('bytes', 0), stats.get('time', 1))
        
        # Dynamically get terminal width
        terminal_width = shutil.get_terminal_size((80, 20)).columns
        progress_line = f"[{bar}] {pct:5.1f}% ({current}/{total}) | {speed} | {display_name}"
        
        sys.stdout.write(f"\r{progress_line.ljust(terminal_width)}")
        sys.stdout.flush()
        
        if current >= total:
            sys.stdout.write("\n")
            sys.stdout.flush()

    def _make_bar(self, pct: float, length: int) -> str:
        filled = int(length * pct / 100)
        return chr(9608) * filled + chr(9601) * (length - filled)


class CheckpointManager:
    """断点续传状态管理"""

    def __init__(self, source: Path, target: Path, checkpoint_file: Optional[Path] = None, interval: int = 10):
        self.source = source
        self.target = target
        self.checkpoint_file = checkpoint_file or (target / ".sync-progress.json")
        self.interval = interval # Add this line
        self.state = self._load_or_create_state()

    def _load_or_create_state(self) -> dict:
        if self.checkpoint_file and self.checkpoint_file.exists():
            try:
                with open(self.checkpoint_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"⚠️ 无法加载进度文件 ({e}), 将从头开始.", file=sys.stderr)

        return {
            "session_id": f"sync_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "source": str(self.source),
            "target": str(self.target),
            "started_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "current_file": "",
            "position": 0,
            "files": {}
        }

    def get_resume_position(self, rel_path: str) -> int:
        """获取续传位置"""
        # 如果文件已在 files 中标记为完成,则返回完整大小
        if rel_path in self.state.get('files', {}):
            return self.state['files'][rel_path].get('size', 0)

        # 如果是当前中断的文件,检查实际目标文件大小
        if self.state.get('current_file') == rel_path:
            target_file = self.target / rel_path
            if target_file.exists():
                return target_file.stat().st_size
        return 0

    def save_checkpoint(self, current_file: str, position: int):
        """保存当前进度点"""
        self.state['current_file'] = current_file
        self.state['position'] = position
        self.state['updated_at'] = datetime.now().isoformat()
        self._write_state()

    def mark_complete(self, rel_path: str, file_size: int, hash_value: str):
        """标记文件已完成"""
        self.state['files'][rel_path] = {
            'size': file_size,
            'hash': hash_value,
            'completed_at': datetime.now().isoformat()
        }
        if self.state.get('current_file') == rel_path:
            self.state['current_file'] = ""
            self.state['position'] = 0
        self._write_state()

    def _write_state(self):
        try:
            self.checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.checkpoint_file, 'w') as f:
                json.dump(self.state, f, indent=2)
        except Exception:
            pass

    def cleanup(self):
        """同步完成后删除进度文件"""
        if self.checkpoint_file and self.checkpoint_file.exists():
            try:
                self.checkpoint_file.unlink()
            except Exception:
                pass


class SleepDetector:
    """检测系统休眠并触发恢复流程"""

    def __init__(self, on_wake_callback: Optional[Callable] = None):
        self.on_wake_callback = on_wake_callback
        self.last_timestamp = time.time()

    def check_time_gap(self) -> bool:
        """检测时间跳跃(可能休眠)"""
        now = time.time()
        gap = now - self.last_timestamp
        self.last_timestamp = now

        # 如果超过 60 秒没有更新,可能休眠了
        if gap > 60:
            if self.on_wake_callback:
                self.on_wake_callback(gap)
            return True
        return False


def format_size(size: int) -> str:
    """格式化文件大小"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def format_speed(bytes_count: int, seconds: float) -> str:
    """格式化速度"""
    if seconds <= 0:
        return "∞"
    return f"{format_size(bytes_count / seconds)}/s"


# =============================================================================
# 4b. OutputManager Class (统一输出接口)
# =============================================================================

class OutputManager:
    """
    统一的命令行输出管理器
    
    输出类型:
    - DEBUG (0)     → stdout (仅调试时)
    - INFO (1)      → stdout
    - WARNING (2)   → stderr
    - ERROR (3)     → stderr
    - SUCCESS (4)   → stdout
    - PROGRESS (5)  → stdout (ANSI 进度条)
    """
    
    DEBUG = 0
    INFO = 1
    WARNING = 2
    ERROR = 3
    SUCCESS = 4
    PROGRESS = 5
    
    def __init__(self, debug: bool = False):
        self.debug = debug
        self._progress: Optional['ProgressDisplay'] = None
    
    def _get_terminal_width(self) -> int:
        """获取当前终端宽度"""
        return get_terminal_width()
    
    def _write(self, message: str, stream, flush: bool = True):
        """写入指定流"""
        stream.write(message)
        if flush:
            stream.flush()
    
    def debug(self, msg: str):
        """调试信息"""
        if self.debug:
            self._write(f"[DEBUG] {msg}\n", sys.stdout)
    
    def info(self, msg: str):
        """普通信息"""
        self._write(f"{msg}\n", sys.stdout)
    
    def warn(self, msg: str):
        """警告信息"""
        self._write(f"⚠️ {msg}\n", sys.stderr)
    
    def error(self, msg: str):
        """错误信息"""
        self._write(f"❌ {msg}\n", sys.stderr)
    
    def success(self, msg: str):
        """成功信息"""
        self._write(f"✅ {msg}\n", sys.stdout)
    
    def progress_start(self, total_files: int, total_bytes: int):
        """启动进度显示"""
        self._progress = ProgressDisplay(total_files, total_bytes, enabled=True)
        return self._progress
    
    def progress_update(self, filename: str, file_size: int, bytes_copied: int):
        """更新进度"""
        if self._progress:
            if not self._progress.current_file or self._progress.current_file != filename:
                self._progress.start_file(filename, file_size)
            self._progress.update_file_progress(bytes_copied)
    
    def progress_complete(self, file_size: int):
        """标记当前文件完成"""
        if self._progress:
            self._progress.complete_file(file_size)
    
    def progress_finish(self):
        """结束进度显示"""
        if self._progress:
            self._progress.finalize()
            self._progress = None
    
    # 兼容旧 print_progress 函数的功能
    def print_progress(self, current: int, total: int, current_file: str, stats: dict):
        """打印简单进度(单行)"""
        pct = (current / total) * 100 if total > 0 else 0
        bar_len = 30
        filled = int(bar_len * current / total) if total > 0 else 0
        bar = "█" * filled + "░" * (bar_len - filled)
        display_name = current_file[:40] + "..." if len(current_file) > 40 else current_file
        speed = format_speed(stats.get('bytes', 0), stats.get('time', 1))

        progress_line = f"[{bar}] {pct:5.1f}% ({current}/{total}) | {speed} | {display_name}"

        # 动态获取终端宽度
        terminal_width = self._get_terminal_width()
        # Pad with spaces to clear the line
        self._write(f"\r{progress_line.ljust(terminal_width)}", sys.stdout)

        if current >= total:
            self._write("\n", sys.stdout)


# =============================================================================
# 4c. ProgressDisplay Class (统一进度显示)
# =============================================================================

class ProgressDisplay:
    """
    统一的进度显示管理器
    
    支持两种模式:
    1. 双行模式(默认): 总进度 + 当前文件进度
    2. 单行模式: 简单的单进度条
    
    这个类整合了原来的 ProgressManager 和 print_progress 的功能
    """
    
    def __init__(self, total_files: int, total_bytes: int, enabled: bool = True, dual_line: bool = True):
        self.total_files = total_files
        self.total_bytes = total_bytes
        self.completed_files = 0
        self.completed_bytes = 0
        self.current_file = ""
        self.current_file_size = 0
        self.current_file_copied = 0
        self.start_time = time.time()
        self.file_start_time = self.start_time
        self.last_update = self.start_time
        self.enabled = enabled
        self.dual_line = dual_line  # True=双行, False=单行
        self._lock = threading.Lock()
        self._first_render = True
        self._pending_file = False
        self._skip_current_file = False
        self._pending_skip_current_file = False
        self._pending_completed_files = 0
        self._pending_completed_bytes = 0
    
    def start_file(self, filename: str, file_size: int, skipped: bool = False):
        """开始跟踪新文件"""
        with self._lock:
            if self._pending_file:
                self.completed_files += self._pending_completed_files
                self.completed_bytes += self._pending_completed_bytes
                self._pending_completed_files = 0
                self._pending_completed_bytes = 0
                self._render_unlocked(final=True, skipped=self._pending_skip_current_file)
                self._pending_file = False

            self.current_file = filename
            self.current_file_size = file_size
            self.current_file_copied = 0
            self.file_start_time = time.time()
            self._skip_current_file = skipped
            
            if skipped:
                self.current_file_copied = file_size
                self._pending_file = True
                self._pending_skip_current_file = True
                self._pending_completed_files = 1
                self._pending_completed_bytes = file_size
            else:
                self._pending_skip_current_file = False
    
    def update_file_progress(self, bytes_copied: int):
        """更新当前文件进度"""
        with self._lock:
            self.current_file_copied = bytes_copied
            self._skip_current_file = False
            self._render_unlocked()
    
    def complete_file(self, file_size: int):
        """标记文件完成"""
        with self._lock:
            if self._skip_current_file:
                return
            self._pending_completed_files = 1
            self._pending_completed_bytes = file_size
            self._pending_file = True
            self._pending_skip_current_file = False
    
    def finalize(self):
        """结束进度显示"""
        with self._lock:
            if self._pending_file:
                self.completed_files += self._pending_completed_files
                self.completed_bytes += self._pending_completed_bytes
                self._pending_completed_files = 0
                self._pending_completed_bytes = 0
                self._render_unlocked(final=True, skipped=self._pending_skip_current_file)
                self._pending_file = False

    def _render_unlocked(self, final: bool = False, skipped: bool = None):
        """内部渲染方法"""
        if not self.enabled:
            return
        
        # 动态获取终端宽度
        terminal_width = self._get_terminal_width()
        
        effective_skipped = skipped if skipped is not None else self._skip_current_file
        if effective_skipped and not final:
            return

        now = time.time()
        if not final and now - self.last_update < 0.25 and self.current_file_copied < self.current_file_size:
            return
        self.last_update = now

        if self._skip_current_file:
            total_progress_bytes = self.completed_bytes
            remaining_bytes = self.total_bytes - total_progress_bytes
            total_pct = (total_progress_bytes / self.total_bytes * 100) if self.total_bytes > 0 else 100
            file_pct = (self.current_file_copied / self.current_file_size * 100) if self.current_file_size > 0 else 100
        else:
            total_progress_bytes = self.completed_bytes + self.current_file_copied
            remaining_bytes = self.total_bytes - total_progress_bytes
            total_pct = (total_progress_bytes / self.total_bytes * 100) if self.total_bytes > 0 else 100
            file_pct = (self.current_file_copied / self.current_file_size * 100) if self.current_file_size > 0 else 100

        elapsed = now - self.start_time
        avg_speed = total_progress_bytes / elapsed if elapsed > 0 else 0
        total_eta = remaining_bytes / avg_speed if avg_speed > 0 else 0

        file_elapsed = now - self.file_start_time
        file_speed = self.current_file_copied / file_elapsed if file_elapsed > 0 else 0
        remaining_file_bytes = self.current_file_size - self.current_file_copied
        file_eta = remaining_file_bytes / file_speed if file_speed > 0 else 0

        total_bar = self._make_bar(total_pct, 20)
        file_bar = self._make_bar(file_pct, 20)

        import os
        name_display = os.path.basename(self.current_file)[:25].ljust(25)
        
        if self.dual_line:
            # 双行模式
            if terminal_width >= 100:
                line1 = "总进度: " + total_bar + " " + format(total_pct, '5.1f') + "% | " + str(self.completed_files) + "/" + str(self.total_files) + " | " + format_size(self.completed_bytes) + "/" + format_size(self.total_bytes) + " | ETA: " + format_time(total_eta)
                line2 = "当前:   " + file_bar + " " + format(file_pct, '5.1f') + "% | " + name_display + " | " + format_size(self.current_file_copied) + "/" + format_size(self.current_file_size) + " | " + format_speed(self.current_file_copied, file_elapsed) + " | ETA: " + format_time(file_eta)
            else:
                line1 = "总进度: " + total_bar + " " + format(total_pct, '5.1f') + "% | " + str(self.completed_files) + "/" + str(self.total_files)
                line2 = "当前:   " + file_bar + " " + format(file_pct, '5.1f') + "% | " + name_display

            if self._first_render:
                output = line1 + chr(10) + chr(27) + "[K" + line2 + chr(10)
                self._first_render = False
            else:
                output = chr(27) + "[2A" + chr(27) + "[K" + line1 + chr(10) + chr(27) + "[K" + line2 + chr(10)
        else:
            # 单行模式
            display_name = name_display.strip()
            speed_str = format_speed(self.current_file_copied, file_elapsed)
            line = f"[{file_bar}] {file_pct:5.1f}% | {display_name} | {format_size(self.current_file_copied)}/{format_size(self.current_file_size)} | {speed_str}"
            
            if self._first_render:
                output = line + chr(10)
                self._first_render = False
            else:
                output = chr(27) + "[A" + chr(27) + "[K" + line + chr(10)
        
        sys.stdout.write(output)
        sys.stdout.flush()
    
    def _get_terminal_width(self) -> int:
        """获取当前终端宽度(每次重新计算)"""
        return get_terminal_width()
    
    def _make_bar(self, pct: float, length: int) -> str:
        filled = int(length * pct / 100)
        return chr(9608) * filled + chr(9601) * (length - filled)


# =============================================================================
# 4d. Legacy Aliases (向后兼容)
# =============================================================================

# ProgressManager 作为 ProgressDisplay 的别名(向后兼容)
ProgressManager = ProgressDisplay


# 兼容旧的 print_progress 函数
def print_progress(current: int, total: int, current_file: str, stats: dict):
    """打印进度(兼容旧接口) - 动态获取终端宽度"""
    pct = (current / total) * 100 if total > 0 else 0
    bar_len = 30
    filled = int(bar_len * current / total) if total > 0 else 0
    bar = "█" * filled + "░" * (bar_len - filled)
    display_name = current_file[:40] + "..." if len(current_file) > 40 else current_file
    speed = format_speed(stats.get('bytes', 0), stats.get('time', 1))

    progress_line = f"[{bar}] {pct:5.1f}% ({current}/{total}) | {speed} | {display_name}"

    # 动态获取终端宽度
    terminal_width = get_terminal_width()
    # Pad with spaces to clear the line
    sys.stdout.write(f"\r{progress_line.ljust(terminal_width)}")
    sys.stdout.flush()

    if current >= total:
        sys.stdout.write("\n")
        sys.stdout.flush()


def detect_mode(args) -> Mode:
    """检测运行模式"""
    if args.sources or args.targets:
        return Mode.MULTI
    elif args.verify:
        return Mode.VERIFY
    else:
        return Mode.COPY


def validate_paths(args) -> Tuple[Path, Path]:
    """验证路径并返回 source, target"""
    source = Path(args.source).resolve()
    target = Path(args.target).resolve()

    if not source.exists():
        print(f"❌ 错误: 源路径不存在: {source}", file=sys.stderr)
        sys.exit(1)
    if not source.is_dir():
        print(f"❌ 错误: 源路径不是文件夹: {source}", file=sys.stderr)
        sys.exit(1)
    if source == target:
        print(f"❌ 错误: 源路径和目标路径不能相同: {source}", file=sys.stderr)
        sys.exit(1)

    return source, target


def setup_algorithm(args) -> str:
    """设置哈希算法"""
    algorithm = args.hash
    if algorithm == "xxhash" and not HAS_XXHASH:
        print("⚠️ xxhash 未安装,回退到 MD5。安装: pip install xxhash", file=sys.stderr)
        algorithm = "md5"

    if args.preserve_xattr and not HAS_XATTR:
        print("⚠️ xattr 未安装,无法保留扩展属性。安装: pip install xattr", file=sys.stderr)

    return algorithm


# =============================================================================
# 6. Report Functions (MHL, Sidecar, JSON)
# =============================================================================

def generate_sidecar_hash_file(
    file_path: Path,
    hash_value: str,
    algorithm: str,
    output_dir: Optional[Path] = None
) -> Optional[Path]:
    """生成校验码伴随文件"""
    ext = f".{algorithm}" if algorithm != "xxhash" else ".xxhash"
    sidecar_path = (output_dir or file_path.parent) / (file_path.name + ext)
    try:
        sidecar_path.write_text(hash_value + "\n")
        return sidecar_path
    except IOError:
        return None


def generate_mhl_report(
    result: SyncResult,
    output_path: Optional[Path] = None
) -> Optional[Path]:
    """
    生成 ASC MHL v1.1 标准校验报告

    MHL (Media Hash List) 是影视行业标准的校验报告格式
    """
    if not result.files:
        return None

    if output_path is None:
        project_name = result.project_name or result.target.name
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = result.target / f"{project_name}_{timestamp}.mhl"

    hashlist = ET.Element("hashlist")
    hashlist.set("version", "1.1")

    creatorinfo = ET.SubElement(hashlist, "creatorinfo")
    ET.SubElement(creatorinfo, "name").text = "Folder Sync Pro"
    ET.SubElement(creatorinfo, "version").text = "1.0.0"
    ET.SubElement(creatorinfo, "hostname").text = socket.gethostname()
    ET.SubElement(creatorinfo, "tool").text = "check_sync_pro.py"

    start_dt = datetime.fromtimestamp(result.start_time, tz=timezone.utc)
    ET.SubElement(creatorinfo, "startdate").text = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    end_dt = datetime.fromtimestamp(result.end_time, tz=timezone.utc)
    ET.SubElement(creatorinfo, "finishdate").text = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    for file_result in result.files:
        if not file_result.success:
            continue
        hash_elem = ET.SubElement(hashlist, "hash")
        ET.SubElement(hash_elem, "file").text = file_result.relative_path
        ET.SubElement(hash_elem, "size").text = str(file_result.target_size or file_result.source_size)
        hash_tag = "xxhash64" if result.algorithm == "xxhash" else result.algorithm
        ET.SubElement(hash_elem, hash_tag).text = file_result.source_hash
        hash_date = file_result.hash_date or datetime.now(timezone.utc)
        ET.SubElement(hash_elem, "hashdate").text = hash_date.strftime("%Y-%m-%dT%H:%M:%SZ")

    xml_str = ET.tostring(hashlist, encoding='unicode')
    pretty_xml = minidom.parseString(xml_str).toprettyxml(indent=" ")
    lines = [line for line in pretty_xml.split('\n') if line.strip()]
    pretty_xml = '\n'.join(lines)

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(pretty_xml, encoding='utf-8')
        return output_path
    except IOError:
        return None


def generate_report(result: SyncResult) -> dict:
    """生成详细的 JSON 报告"""
    report = {
        "metadata": {
            "tool": "Folder Sync Pro",
            "version": "1.0.0",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "algorithm": result.algorithm,
            "double_verify": result.double_verify,
            "source": str(result.source),
            "target": str(result.target),
        },
        "summary": {
            "total_files": len(result.files),
            "copied": len(result.copied),
            "skipped": len(result.skipped),
            "failed": len(result.failed),
            "total_bytes": result.total_bytes,
            "total_size": format_size(result.total_bytes),
            "duration_seconds": round(result.end_time - result.start_time, 3),
            "average_speed": format_speed(result.total_bytes, result.end_time - result.start_time)
                if result.end_time > result.start_time else "N/A"
        },
        "files": []
    }

    for f in result.files:
        file_info = {
            "path": f.relative_path,
            "source_size": f.source_size,
            "source_hash": f.source_hash,
            "target_size": f.target_size,
            "target_hash": f.target_hash,
            "success": f.success,
            "copy_time": round(f.copy_time, 3),
        }
        if result.double_verify and f.verify_hash:
            file_info["verify_hash"] = f.verify_hash
            file_info["verified"] = f.verify_hash == f.source_hash
        if f.error:
            file_info["error"] = f.error
        if f.retries > 0:
            file_info["retries"] = f.retries
        report["files"].append(file_info)

    if result.copied:
        report["copied_files"] = result.copied
    if result.skipped:
        report["skipped_files"] = result.skipped
    if result.failed:
        report["failed_files"] = result.failed

    return report


def print_result_summary(result: SyncResult, verbose: bool = True, mode: Mode = Mode.COPY):
    """打印结果摘要"""
    if not verbose:
        return

    mode_text = "校验完成" if mode == Mode.VERIFY else "拷贝完成"
    success_text = "校验通过" if mode == Mode.VERIFY else "成功拷贝"

    print()
    print("\n" + "=" * 50)
    print(f"📊 {mode_text}")
    print("=" * 50)
    print(f"源文件夹: {result.source}")
    print(f"目标文件夹: {result.target}")
    print(f"哈希算法: {result.algorithm.upper()}")
    print()
    print(f"✅ {success_text}: {len(result.copied)} 个文件")
    if mode == Mode.COPY:
        print(f"⏭️ 跳过文件: {len(result.skipped)} 个文件")
    print(f"❌ 失败文件: {len(result.failed)} 个文件")
    print()
    print(f"📦 总数据量: {format_size(result.total_bytes)}")
    duration = result.end_time - result.start_time
    print(f"⏱️ 总耗时: {duration:.1f} 秒")
    print(f"🚀 平均速度: {format_speed(result.total_bytes, duration)}")
    if result.double_verify:
        print("✓ 双重校验: 已完成")

    if result.failed:
        print("\n❌ 失败文件列表:")
        for f in result.failed[:10]:
            print(f" - {f}")
        if len(result.failed) > 10:
            print(f" ... 还有 {len(result.failed) - 10} 个")


def save_json_report(report_data: dict, report_path: str, verbose: bool = False):
    """保存 JSON 报告"""
    try:
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)
        if verbose:
            print(f"\n📄 JSON 报告已保存: {report_path}")
    except IOError as e:
        print(f"\n❌ 无法保存报告: {e}", file=sys.stderr)


# =============================================================================
# 7. Mode Functions (run_copy, run_verify, run_multi_source)
# =============================================================================

def sync_single_pair(
    source: Path,
    target: Path,
    algorithm: str,
    double_verify: bool,
    skip_existing: bool,
    preserve_metadata: bool,
    preserve_xattr: bool,
    sidecar: bool,
    retries: int,
    verbose: bool,
    show_progress: bool = False,
    checkpoint_manager: Optional[CheckpointManager] = None,
    checkpoint_interval: int = 10,
    resume: bool = False,
    progress_manager: Optional[ProgressManager] = None,
    pre_scanned_source_files: Optional[Dict[str, Path]] = None
) -> SyncResult:
    """同步单个源-目标对"""
    target.mkdir(parents=True, exist_ok=True)

    # Use pre-scanned files if provided, otherwise scan now
    source_files = pre_scanned_source_files if pre_scanned_source_files is not None else scan_folder(source, verbose)

    # 如果是恢复模式,从检查点获取需要跳过的已完成文件
    completed_files = set()
    if checkpoint_manager and resume:
        completed_files = set(checkpoint_manager.state.get('files', {}).keys())
        if verbose:
            print(f"📋 恢复模式: 已完成 {len(completed_files)} 个文件将跳过")

    result = SyncResult(
        source=source,
        target=target,
        algorithm=algorithm,
        double_verify=double_verify
    )
    result.start_time = time.time()

    if not source_files:
        if verbose:
            print("⚠️ 源文件夹为空,无文件需要拷贝", file=sys.stderr)
        result.end_time = time.time()
        return result

    sorted_files = sorted(source_files.items())
    total_files = len(sorted_files)

    # 计算需要拷贝的文件数(恢复模式下排除已完成的)
    files_to_copy = [(rp, sp) for rp, sp in sorted_files if rp not in completed_files]
    files_to_copy_count = len(files_to_copy)

    if verbose:
        if resume and completed_files:
            print(f"\n📦 开始拷贝: {files_to_copy_count} 个文件 (跳过 {len(completed_files)} 个已完成)")
        else:
            print(f"\n📦 开始拷贝: {total_files} 个文件")
        print(f"🔐 哈希算法: {algorithm.upper()}")
        if double_verify:
            print("✓ 双重校验: 已启用")
        if preserve_metadata:
            print("✓ 元数据保留: 已启用")
        if preserve_xattr:
            print("✓ 扩展属性保留: 已启用")
        if sidecar:
            print("✓ 校验码文件: 已启用")
        if show_progress:
            print("✓ 实时进度: 已启用")
        if checkpoint_manager:
            print(f"✓ 断点续传: 已启用 (每 {checkpoint_interval} 秒保存)")
        print()

    stats = {'bytes': 0, 'time': 0}

    # Use shared progress_manager if provided, otherwise create per-file as fallback
    shared_progress = progress_manager
    last_per_file_pm = None  # Track last per-file progress manager for backward compat

    for idx, (rel_path, source_path) in enumerate(files_to_copy, 1):
        target_path = target / rel_path

        try:
            source_size = source_path.stat().st_size
        except OSError as e:
            result.failed.append(rel_path)
            if verbose:
                print(f"\n❌ 无法读取文件大小: {rel_path} ({e})")
            continue

        if verbose and not show_progress:
            if shared_progress:
                # Use ProgressManager's single-line progress method
                shared_progress.print_progress_line(idx, files_to_copy_count, rel_path, stats)
            else:
                # Fallback to standalone function
                print_progress(idx, files_to_copy_count, rel_path, stats)

        if target_path.exists() and skip_existing:
            result.skipped.append(rel_path)
            if shared_progress:
                # Use skipped=True to prevent flicker (file already complete)
                shared_progress.start_file(rel_path, source_size, skipped=True)
                shared_progress.complete_file(source_size)
            continue

        # Use shared progress manager if provided, otherwise create per-file (backward compat)
        if shared_progress:
            shared_progress.start_file(rel_path, source_size, skipped=False)
            progress_callback = shared_progress.update_file_progress
        elif show_progress:
            # Backward compat: per-file progress manager
            per_file_pm = ProgressManager(1, source_size, enabled=True)
            per_file_pm.start_file(rel_path, source_size, skipped=False)
            progress_callback = per_file_pm.update_file_progress
            last_per_file_pm = per_file_pm
        else:
            progress_callback = None

        source_hash, copy_time, bytes_copied, error = _copy_and_hash_file(
            source_path,
            target_path,
            algorithm,
            retries=retries,
            preserve_metadata=preserve_metadata,
            preserve_xattr=preserve_xattr,
            checkpoint_manager=checkpoint_manager,
            progress_callback=progress_callback,
            resume=resume or bool(checkpoint_manager) # Enable resume if checkpointing is on
        )

        if error:
            result.failed.append(rel_path)
            if verbose:
                print(f"\n❌ 拷贝失败: {rel_path} ({error})")
            # 保存失败前的进度
            if checkpoint_manager:
                checkpoint_manager.save_checkpoint(rel_path, bytes_copied)
            continue

        file_result = FileResult(
            relative_path=rel_path,
            source_size=source_size,
            target_size=bytes_copied,
            source_hash=source_hash,
            copy_time=copy_time,
            success=True,
            hash_date=datetime.now(timezone.utc)
        )

        if double_verify:
            verified, verify_hash, verify_error = verify_file_hash(
                target_path, algorithm, source_hash, retries=retries,
                file_name=rel_path, total_size=source_size
            )
            file_result.verify_hash = verify_hash
            if not verified:
                file_result.success = False
                file_result.error = verify_error or "校验哈希不匹配"
                result.failed.append(rel_path)
                if verbose:
                    print(f"\n❌ 二次校验失败: {rel_path}")
                continue

        if sidecar:
            sidecar_path = generate_sidecar_hash_file(target_path, source_hash, algorithm)
            if verbose and not sidecar_path:
                print(f"\n⚠️ 无法生成校验码文件: {rel_path}")

        result.copied.append(rel_path)
        result.files.append(file_result)
        result.total_bytes += bytes_copied

        # 更新进度管理器(标记文件完成)
        if shared_progress:
            shared_progress.complete_file(source_size)
        elif show_progress:
            per_file_pm.complete_file(source_size)

        # 标记文件完成
        if checkpoint_manager:
            checkpoint_manager.mark_complete(rel_path, bytes_copied, source_hash)

        stats['bytes'] = result.total_bytes
        stats['time'] = result.end_time - result.start_time

    result.end_time = time.time()
    
    # Finalize progress display for any pending file
    if shared_progress:
        shared_progress.finalize()
    elif show_progress and last_per_file_pm:
        last_per_file_pm.finalize()
    
    return result


def process_file_verify(
    source_path: Path,
    target_path: Path,
    rel_path: str,
    result: SyncResult,
    args,
    algorithm: str,
    verbose: bool
) -> Optional[FileResult]:
    """处理校验模式下的单个文件"""
    try:
        source_size = source_path.stat().st_size
        target_size = target_path.stat().st_size
    except OSError as e:
        result.failed.append(rel_path)
        if verbose:
            print(f"\n❌ 无法读取文件大小: {rel_path} ({e})")
        return None

    if source_size != target_size:
        file_result = FileResult(
            relative_path=rel_path,
            source_size=source_size,
            target_size=target_size,
            success=False,
            error="文件大小不匹配"
        )
        result.files.append(file_result)
        result.failed.append(rel_path)
        return None

    source_hash, _, _, error = compute_file_hash(source_path, algorithm, retries=args.retries)
    if error:
        file_result = FileResult(
            relative_path=rel_path,
            source_size=source_size,
            success=False,
            error=f"源文件哈希计算失败: {error}"
        )
        result.files.append(file_result)
        result.failed.append(rel_path)
        return None

    verified, target_hash, verify_error = verify_file_hash(
        target_path, algorithm, source_hash, retries=args.retries,
        file_name=rel_path, total_size=target_size
    )

    file_result = FileResult(
        relative_path=rel_path,
        source_size=source_size,
        target_size=target_size,
        source_hash=source_hash,
        target_hash=target_hash,
        success=verified
    )

    if verify_error:
        file_result.success = False
        file_result.error = f"目标文件读取失败: {verify_error}"
        result.failed.append(rel_path)
    elif not verified:
        file_result.error = "哈希值不匹配"
        result.failed.append(rel_path)
    else:
        result.copied.append(rel_path)

    result.files.append(file_result)
    return file_result


def run_verify(args, algorithm: str) -> int:
    """校验模式入口"""
    source, target = validate_paths(args)

    if args.verbose:
        print(f"\n🔍 校验模式: 仅验证已存在文件,不拷贝")
        print(f"🔐 哈希算法: {algorithm.upper()}")

    comparison = scan_and_compare(source, target, args.verbose)
    common_files = comparison['common']
    only_in_source = comparison['only_source']
    only_in_target = comparison['only_target']

    if args.verbose:
        print(f"\n📊 文件统计:")
        print(f" 源文件夹文件数: {len(comparison['source_files'])}")
        print(f" 目标文件夹文件数: {len(comparison['target_files'])}")
        print(f" 共同文件数: {len(common_files)}")
        if only_in_source:
            print(f" ⚠️ 仅存在于源: {len(only_in_source)} 个文件")
        if only_in_target:
            print(f" ⚠️ 仅存在于目标: {len(only_in_target)} 个文件")

    if not common_files:
        print("⚠️ 没有共同文件需要校验")
        return 0

    result = SyncResult(
        source=source,
        target=target,
        algorithm=algorithm,
        double_verify=False
    )
    result.start_time = time.time()

    stats = {'bytes': 0, 'time': 0}
    source_files = comparison['source_files']
    target_files = comparison['target_files']

    for idx, rel_path in enumerate(sorted(common_files), 1):
        process_file_verify(
            source_files[rel_path],
            target_files[rel_path],
            rel_path,
            result,
            args,
            algorithm,
            args.verbose
        )
        result.total_bytes += source_files[rel_path].stat().st_size if source_files[rel_path].exists() else 0
        stats['bytes'] = result.total_bytes

    result.end_time = time.time()

    # 打印结果
    print_result_summary(result, args.verbose, Mode.VERIFY)

    if only_in_source and args.verbose:
        print(f"\n⚠️ 仅存在于源文件夹: {len(only_in_source)} 个文件")
    if only_in_target and args.verbose:
        print(f"⚠️ 仅存在于目标文件夹: {len(only_in_target)} 个文件")

    # 生成报告
    if args.report:
        report_data = generate_report(result)
        report_data["metadata"]["verify_mode"] = True
        save_json_report(report_data, args.report, args.verbose)

    return 1 if result.failed else 0


# Global checkpoint manager for signal handling
_global_checkpoint = None

def _signal_handler(signum, frame):
    """Ctrl+C 优雅中断处理"""
    global _global_checkpoint
    print("\n\n⚠️ 检测到中断信号,正在保存进度...")
    if _global_checkpoint:
        _global_checkpoint.save_checkpoint(_global_checkpoint.state.get('current_file', ''),
                                           _global_checkpoint.state.get('position', 0))
        print(f"✅ 进度已保存到: {_global_checkpoint.checkpoint_file}")
        print(f"💡 恢复命令: python3 check_sync_pro.py --resume {_global_checkpoint.checkpoint_file}")
    sys.exit(1)


def run_copy(args, algorithm: str) -> int:
    """拷贝模式入口"""
    global _global_checkpoint

    source, target = validate_paths(args)

    # 初始化进度和检查点管理器
    checkpoint_manager = None
    progress_manager = None
    should_resume = False
    pre_scanned_source_files = None  # 用于避免重复扫描

    if args.resume:
        # 从进度文件恢复
        resume_file = Path(args.resume)
        if resume_file.exists():
            checkpoint_manager = CheckpointManager(source, target, resume_file, interval=args.checkpoint)
            # 从状态中恢复当前文件
            state = checkpoint_manager.state
            if state.get('current_file') or state.get('files'):
                should_resume = True
                print(f"🔄 检测到进度文件,将从断点继续...", file=sys.stderr)
                if state.get('current_file'):
                    print(f"  继续文件: {state['current_file']} ({format_size(state.get('position', 0))})", file=sys.stderr)
        else:
            print(f"⚠️ 进度文件不存在: {resume_file}", file=sys.stderr)
    elif args.progress:
        # 启用进度显示,创建空的检查点管理器
        checkpoint_manager = CheckpointManager(source, target, interval=args.checkpoint)

    # 扫描一次源文件夹,避免在 sync_single_pair 中重复扫描
    scan_result = scan_and_compare(source, target, args.verbose)
    if args.verbose:
        print(f"🔍 扫描: {source}")
    pre_scanned_source_files = scan_result['source_files']

    # 创建共享进度管理器(用于总进度追踪)
    if args.progress:
        files_to_copy_count = len(scan_result['only_source']) + len(scan_result['common'])
        total_size = sum(
            scan_result['source_files'][f].stat().st_size
            for f in scan_result['only_source']
        ) + sum(
            scan_result['source_files'][f].stat().st_size
            for f in scan_result['common']
        )
        progress_manager = ProgressManager(files_to_copy_count, total_size, enabled=True)

    if checkpoint_manager:
        _global_checkpoint = checkpoint_manager
        # 设置信号处理
        signal.signal(signal.SIGINT, _signal_handler)

    result = sync_single_pair(
        source=source,
        target=target,
        algorithm=algorithm,
        double_verify=args.double_verify,
        skip_existing=args.skip_existing,
        preserve_metadata=args.preserve_metadata,
        preserve_xattr=args.preserve_xattr,
        sidecar=args.sidecar,
        retries=args.retries,
        verbose=args.verbose,
        show_progress=args.progress,
        checkpoint_manager=checkpoint_manager,
        checkpoint_interval=args.checkpoint,
        resume=should_resume,
        progress_manager=progress_manager,
        pre_scanned_source_files=pre_scanned_source_files
    )

    result.project_name = args.project_name or target.name
    print_result_summary(result, args.verbose, Mode.COPY)

    # 清理检查点文件(拷贝完成)
    if checkpoint_manager:
        checkpoint_manager.cleanup()
        _global_checkpoint = None

    if args.report:
        report_data = generate_report(result)
        save_json_report(report_data, args.report, args.verbose)

    if args.mhl:
        mhl_output = Path(args.mhl_output) if args.mhl_output else None
        mhl_path = generate_mhl_report(result, mhl_output)
        if mhl_path and args.verbose:
            print(f"\n📄 MHL 报告已保存: {mhl_path}")
        elif not mhl_path:
            print("\n⚠️ MHL 报告生成失败", file=sys.stderr)

    return 1 if result.failed else 0


def run_multi_source(args, algorithm: str) -> int:
    """多源拷贝模式"""
    sources = [Path(s) for s in args.sources]
    targets = [Path(t) for t in args.targets]

    # 验证源路径
    for source in sources:
        if not source.exists():
            print(f"❌ 错误: 源路径不存在: {source}", file=sys.stderr)
            return 1
        if not source.is_dir():
            print(f"❌ 错误: 源路径不是文件夹: {source}", file=sys.stderr)
            return 1

    source_target_pairs = [(s, t) for s in sources for t in targets]
    total_pairs = len(source_target_pairs)

    if args.verbose:
        print(f"\n📦 多源拷贝模式: {len(sources)} 个源 × {len(targets)} 个目标 = {total_pairs} 个任务")
        print(f"🔐 哈希算法: {algorithm.upper()}")
        print(f"🧵 并发数: {args.parallel}")
        if args.double_verify:
            print("✓ 双重校验: 已启用")
        if args.preserve_metadata:
            print("✓ 元数据保留: 已启用")
        if args.preserve_xattr:
            print("✓ 扩展属性保留: 已启用")
        if args.sidecar:
            print("✓ 校验码文件: 已启用")
        print()

    multi_result = MultiSourceResult(
        sources=sources,
        targets=targets,
        start_time=time.time()
    )
    has_unexpected_errors = False

    if args.parallel <= 1:
        for source, target in source_target_pairs:
            if args.verbose:
                print(f"\n🔄 处理: {source.name} → {target.name}")
            result = sync_single_pair(
                source=source, target=target, algorithm=algorithm,
                double_verify=args.double_verify, skip_existing=args.skip_existing,
                preserve_metadata=args.preserve_metadata, preserve_xattr=args.preserve_xattr,
                sidecar=args.sidecar, retries=args.retries, verbose=args.verbose
            )
            result.project_name = args.project_name or f"{source.name}_to_{target.name}"
            multi_result.results.append(result)
    else:
        with ThreadPoolExecutor(max_workers=args.parallel) as executor:
            future_to_pair = {}
            for source, target in source_target_pairs:
                future = executor.submit(
                    sync_single_pair,
                    source=source, target=target, algorithm=algorithm,
                    double_verify=args.double_verify, skip_existing=args.skip_existing,
                    preserve_metadata=args.preserve_metadata, preserve_xattr=args.preserve_xattr,
                    sidecar=args.sidecar, retries=args.retries, verbose=False
                )
                future_to_pair[future] = (source, target)

            for future in as_completed(future_to_pair):
                source, target = future_to_pair[future]
                try:
                    result = future.result()
                    result.project_name = args.project_name or f"{source.name}_to_{target.name}"
                    multi_result.results.append(result)
                    if args.verbose:
                        status = "✅" if not result.failed else "❌"
                        print(f"{status} 完成: {source.name} → {target.name} ({len(result.copied)} 个文件)")
                except Exception as e:
                    print(f"❌ 错误: {source.name} → {target.name}: {e}", file=sys.stderr)
                    has_unexpected_errors = True

    multi_result.end_time = time.time()

    # 打印综合结果
    if args.verbose:
        print("\n" + "=" * 60)
        print("📊 多源拷贝完成")
        print("=" * 60)
        total_copied = sum(len(r.copied) for r in multi_result.results)
        total_failed = sum(len(r.failed) for r in multi_result.results)
        total_skipped = sum(len(r.skipped) for r in multi_result.results)
        total_bytes = sum(r.total_bytes for r in multi_result.results)
        print(f"\n总任务数: {len(multi_result.results)}")
        print(f"✅ 成功拷贝: {total_copied} 个文件")
        print(f"⏭️ 跳过文件: {total_skipped} 个文件")
        print(f"❌ 失败文件: {total_failed} 个文件")
        print(f"\n📦 总数据量: {format_size(total_bytes)}")
        duration = multi_result.end_time - multi_result.start_time
        print(f"⏱️ 总耗时: {duration:.1f} 秒")
        if duration > 0:
            print(f"🚀 平均速度: {format_speed(total_bytes, duration)}")
        print("\n各任务详情:")
        for result in multi_result.results:
            status_icon = "✅" if not result.failed else "❌"
            print(f" {status_icon} {result.source.name} → {result.target.name}: "
                  f"{len(result.copied)} 成功, {len(result.failed)} 失败")

    # 生成 MHL 报告
    if args.mhl:
        for target in targets:
            combined_result = SyncResult(
                source=Path("multiple_sources"),
                target=target,
                algorithm=algorithm,
                double_verify=args.double_verify,
                project_name=args.project_name or target.name
            )
            combined_result.start_time = multi_result.start_time
            combined_result.end_time = multi_result.end_time
            for result in multi_result.results:
                if result.target == target:
                    combined_result.files.extend(result.files)
                    combined_result.copied.extend(result.copied)
                    combined_result.failed.extend(result.failed)
                    combined_result.total_bytes += result.total_bytes
            if combined_result.files:
                mhl_output = target / f"{combined_result.project_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mhl"
                mhl_path = generate_mhl_report(combined_result, mhl_output)
                if mhl_path and args.verbose:
                    print(f"\n📄 MHL 报告已保存: {mhl_path}")

    # 生成 JSON 报告
    if args.report:
        combined_report = {
            "metadata": {
                "tool": "Folder Sync Pro",
                "version": "1.0.0",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "algorithm": algorithm,
                "sources": [str(s) for s in sources],
                "targets": [str(t) for t in targets],
                "multi_source": True
            },
            "summary": {
                "total_tasks": len(multi_result.results),
                "total_copied": sum(len(r.copied) for r in multi_result.results),
                "total_failed": sum(len(r.failed) for r in multi_result.results),
                "total_skipped": sum(len(r.skipped) for r in multi_result.results),
                "total_bytes": sum(r.total_bytes for r in multi_result.results),
                "total_size": format_size(sum(r.total_bytes for r in multi_result.results)),
                "duration_seconds": round(multi_result.end_time - multi_result.start_time, 3),
            },
            "tasks": [generate_report(r) for r in multi_result.results]
        }
        save_json_report(combined_report, args.report, args.verbose)

    return 1 if sum(len(r.failed) for r in multi_result.results) or has_unexpected_errors else 0


# =============================================================================
# 8. Entry Point (parse_args, main, __main__)
# =============================================================================

def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="📦 Folder Sync Pro - 拷卡校验工具(专业版)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 基本使用:从存储卡拷贝到目标文件夹
  %(prog)s /Volumes/SD_CARD/DCIM ~/Photos/2024-01-01

  # 启用双重校验(拷贝后二次验证目标文件)
  %(prog)s /Volumes/SD_CARD/DCIM ~/Photos/2024-01-01 --double-verify

  # 生成 MHL 标准报告(影视行业标准)
  %(prog)s /Volumes/SD_CARD/DCIM ~/Photos/2024-01-01 --mhl

  # 生成校验码伴随文件
  %(prog)s /Volumes/SD_CARD/DCIM ~/Photos/2024-01-01 --sidecar

  # 多源拷贝:从两张卡拷贝到两个备份盘
  %(prog)s --sources /Volumes/SD_CARD1 /Volumes/SD_CARD2 \\
      --targets /Volumes/Backup1 /Volumes/Backup2 --parallel 2 --mhl

  # 完整专业模式
  %(prog)s /Volumes/SD_CARD/DCIM ~/Photos/2024-01-01 \\
      --double-verify --mhl --sidecar --preserve-xattr \\
      --report report.json --verbose

  # 启用实时进度条(拷贝大文件时推荐)
  %(prog)s /Volumes/SD_CARD/DCIM ~/Photos/2024-01-01 --progress

  # 从断点恢复拷贝
  %(prog)s --resume .sync-progress.json

  # 启用断点续传+进度显示+每5秒保存进度
  %(prog)s /Volumes/SD_CARD/DCIM ~/Photos/2024-01-01 --progress --checkpoint 5

注意:
  - 默认使用 xxHash 算法(需安装: pip install xxhash)
  - 如未安装 xxhash,自动回退到 MD5
  - 双重校验会增加约 30%% 时间,但提供更高安全性
  - MHL 报告可被 Silverstack、YoYotta、DaVinci Resolve 等软件识别
  - 断点续传在拷贝大文件时非常有用,笔记本休眠后可以从断点继续
"""
    )

    # 基本参数
    parser.add_argument("source", nargs='?', help="源文件夹路径(存储卡)")
    parser.add_argument("target", nargs='?', help="目标文件夹路径")

    # 多源拷贝参数
    parser.add_argument("--sources", nargs='+', metavar="PATH",
                        help="多个源文件夹路径(多源拷贝模式)")
    parser.add_argument("--targets", nargs='+', metavar="PATH",
                        help="多个目标文件夹路径(多源拷贝模式)")
    parser.add_argument("--parallel", type=int, default=1, metavar="N",
                        help="并发拷贝数(多源拷贝模式,默认: 1)")

    # 校验参数
    parser.add_argument("--double-verify", action="store_true",
                        help="二次校验模式:拷贝后再读一遍目标文件验证")
    parser.add_argument("--retries", type=int, default=3,
                        help="IO 错误重试次数 (默认: 3)")

    # 输出参数
    parser.add_argument("--report", metavar="FILE", help="生成详细 JSON 报告")
    parser.add_argument("--mhl", action="store_true",
                        help="生成 ASC MHL v1.1 标准校验报告(影视行业标准)")
    parser.add_argument("--mhl-output", metavar="FILE",
                        help="MHL 报告输出路径(可选)")
    parser.add_argument("--project-name", metavar="NAME",
                        help="项目名称(用于 MHL 报告)")
    parser.add_argument("--sidecar", action="store_true",
                        help="生成校验码伴随文件(.xxhash 或 .md5)")

    # 哈希参数
    parser.add_argument("--hash", choices=["xxhash", "md5", "sha256"],
                        default=DEFAULT_ALGORITHM,
                        help=f"哈希算法 (默认: {DEFAULT_ALGORITHM})")

    # 拷贝参数
    parser.add_argument("--skip-existing", action="store_true",
                        help="跳过已存在的文件(不做校验)")

    # 元数据参数
    parser.add_argument("--preserve-metadata", action="store_true", default=True,
                        help="保留文件时间戳(默认启用)")
    parser.add_argument("--no-preserve-metadata", action="store_false",
                        dest='preserve_metadata', help="不保留文件时间戳")
    parser.add_argument("--preserve-xattr", action="store_true",
                        help="保留文件扩展属性(需要 xattr 模块)")

    # 其他参数
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="显示详细进度")
    parser.add_argument("--verify", action="store_true",
                        help="校验模式:仅校验目标文件夹中已存在的文件,不拷贝新文件")

    # 断点续传参数
    parser.add_argument("--progress", action="store_true",
                        help="显示实时进度条(大文件拷贝时推荐)")
    parser.add_argument("--resume", metavar="FILE",
                        help="从进度文件恢复拷贝(.sync-progress.json)")
    parser.add_argument("--checkpoint", type=int, default=10, metavar="N",
                        help="每 N 秒保存进度(默认: 10)")

    return parser.parse_args()


def main():
    """主函数 - 入口点"""
    args = parse_args()

    # 检查多源模式参数
    if args.sources or args.targets:
        if not args.sources or not args.targets:
            print("❌ 错误: 多源拷贝模式需要同时指定 --sources 和 --targets", file=sys.stderr)
            sys.exit(1)
        if args.source or args.target:
            print("❌ 错误: 多源拷贝模式与单源模式不能同时使用", file=sys.stderr)
            sys.exit(1)

    # 检查单源模式参数
    if not args.sources:
        if not args.source or not args.target:
            print("❌ 错误: 需要指定 source 和 target,或使用 --sources/--targets 进行多源拷贝",
                  file=sys.stderr)
            sys.exit(1)

    # 检测运行模式
    mode = detect_mode(args)
    algorithm = setup_algorithm(args)

    # 执行对应模式
    if mode == Mode.MULTI:
        exit_code = run_multi_source(args, algorithm)
    elif mode == Mode.VERIFY:
        exit_code = run_verify(args, algorithm)
    else:
        exit_code = run_copy(args, algorithm)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
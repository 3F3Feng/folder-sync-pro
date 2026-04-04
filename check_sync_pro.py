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
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# 尝试导入 xxhash,失败则回退到 hashlib
try:
    import xxhash
    HAS_XXHASH = True
    DEFAULT_ALGORITHM = "xxhash"
except ImportError:
    HAS_XXHASH = False
    DEFAULT_ALGORITHM = "md5"


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


def get_hash_func(algorithm: str):
    """获取哈希函数"""
    if algorithm == "xxhash" and HAS_XXHASH:
        return xxhash.xxh64()
    elif algorithm == "md5":
        return hashlib.md5()
    elif algorithm == "sha256":
        return hashlib.sha256()
    else:
        # 回退到 MD5
        return hashlib.md5()


def compute_hash(data: bytes, algorithm: str) -> str:
    """计算数据的哈希值"""
    hash_func = get_hash_func(algorithm)
    hash_func.update(data)
    return hash_func.hexdigest()


def compute_file_hash(
    file_path: Path,
    algorithm: str,
    retries: int = 3
) -> Tuple[str, float, int, str]:
    """
    计算文件的哈希值（不写入任何内容）
    
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


def copy_with_streaming_hash(
    source_path: Path,
    target_path: Path,
    algorithm: str,
    chunk_size: int = 1024 * 1024,  # 1MB chunks
    retries: int = 3
) -> Tuple[str, float, int, str]:
    """
    流式拷贝文件,同时计算哈希值

    返回: (哈希值, 耗时, 拷贝字节数, 错误信息)
    """
    hash_func = get_hash_func(algorithm)
    bytes_copied = 0
    start_time = time.time()
    last_error = ""

    for attempt in range(retries):
        try:
            # 确保目标目录存在
            target_path.parent.mkdir(parents=True, exist_ok=True)

            with open(source_path, 'rb') as src, open(target_path, 'wb') as tgt:
                while True:
                    chunk = src.read(chunk_size)
                    if not chunk:
                        break
                    # 更新哈希(在写入前计算,确保是源文件内容)
                    hash_func.update(chunk)
                    # 写入目标文件
                    tgt.write(chunk)
                    bytes_copied += len(chunk)

            # 成功完成
            return hash_func.hexdigest(), time.time() - start_time, bytes_copied, ""

        except (OSError, IOError) as e:
            last_error = str(e)
            # 清理可能的部分文件
            if target_path.exists():
                try:
                    target_path.unlink()
                except:
                    pass
            # 重试前等待
            if attempt < retries - 1:
                wait_time = 2 ** attempt  # 指数退避:1s, 2s, 4s
                time.sleep(wait_time)

    return "", time.time() - start_time, bytes_copied, last_error


def verify_file_hash(
    file_path: Path,
    algorithm: str,
    expected_hash: str,
    retries: int = 3
) -> Tuple[bool, str, str]:
    """
    校验文件哈希值

    返回: (是否匹配, 实际哈希, 错误信息)
    """
    last_error = ""

    for attempt in range(retries):
        try:
            hash_func = get_hash_func(algorithm)
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(1024 * 1024)  # 1MB chunks
                    if not chunk:
                        break
                    hash_func.update(chunk)
            actual_hash = hash_func.hexdigest()
            return actual_hash == expected_hash, actual_hash, ""

        except (OSError, IOError) as e:
            last_error = str(e)
            if attempt < retries - 1:
                wait_time = 2 ** attempt
                time.sleep(wait_time)

    return False, "", last_error


def scan_folder(folder: Path, verbose: bool = False) -> Dict[str, Path]:
    """递归扫描文件夹,返回相对路径到完整路径的映射"""
    files = {}
    if verbose:
        print(f"🔍 扫描: {folder}")

    for root, _, filenames in os.walk(folder):
        for filename in filenames:
            full_path = Path(root) / filename
            rel_path = str(full_path.relative_to(folder))
            files[rel_path] = full_path

    return files


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
    speed = bytes_count / seconds
    return f"{format_size(speed)}/s"


def print_progress(current: int, total: int, current_file: str, stats: dict):
    """打印进度"""
    pct = (current / total) * 100 if total > 0 else 0
    bar_len = 30
    filled = int(bar_len * current / total) if total > 0 else 0
    bar = "█" * filled + "░" * (bar_len - filled)

    # 截断长文件名
    display_name = current_file[:40] + "..." if len(current_file) > 40 else current_file

    speed = format_speed(stats.get('bytes', 0), stats.get('time', 1))

    print(f"\r[{bar}] {pct:5.1f}% ({current}/{total}) | {speed} | {display_name}", end="", flush=True)


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
            "average_speed": format_speed(
                result.total_bytes,
                result.end_time - result.start_time
            ) if result.end_time > result.start_time else "N/A"
        },
        "files": []
    }

    # 详细文件信息
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

    # 添加分类列表
    if result.copied:
        report["copied_files"] = result.copied
    if result.skipped:
        report["skipped_files"] = result.skipped
    if result.failed:
        report["failed_files"] = result.failed

    return report


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

  # 指定重试次数和输出报告
  %(prog)s /Volumes/SD_CARD/DCIM ~/Photos/2024-01-01 --retries 5 --report report.json

  # 使用 MD5 算法(兼容模式)
  %(prog)s /Volumes/SD_CARD/DCIM ~/Photos/2024-01-01 --hash md5

  # 校验已有文件(不拷贝)
  %(prog)s /source /target --verify --report report.json

注意:
  - 默认使用 xxHash 算法(需安装: pip install xxhash)
  - 如未安装 xxhash,自动回退到 MD5
  - 双重校验会增加约 30%% 时间,但提供更高安全性
        """
    )

    parser.add_argument(
        "source",
        help="源文件夹路径(存储卡)"
    )
    parser.add_argument(
        "target",
        help="目标文件夹路径"
    )
    parser.add_argument(
        "--double-verify",
        action="store_true",
        help="二次校验模式:拷贝后再读一遍目标文件验证"
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="IO 错误重试次数 (默认: 3)"
    )
    parser.add_argument(
        "--report",
        metavar="FILE",
        help="生成详细 JSON 报告"
    )
    parser.add_argument(
        "--hash",
        choices=["xxhash", "md5", "sha256"],
        default=DEFAULT_ALGORITHM,
        help=f"哈希算法 (默认: {DEFAULT_ALGORITHM})"
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=4,
        help="并发线程数 (默认: 4)"
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="跳过已存在的文件(不做校验)"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="显示详细进度"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="校验模式:仅校验目标文件夹中已存在的文件,不拷贝新文件"
    )

    return parser.parse_args()


def main():
    """主函数"""
    args = parse_args()

    # 验证路径
    source = Path(args.source)
    target = Path(args.target)

    if not source.exists():
        print(f"❌ 错误: 源路径不存在: {source}", file=sys.stderr)
        sys.exit(1)
    if not source.is_dir():
        print(f"❌ 错误: 源路径不是文件夹: {source}", file=sys.stderr)
        sys.exit(1)

    # 创建目标文件夹
    target.mkdir(parents=True, exist_ok=True)

    # 检查算法可用性
    algorithm = args.hash
    if algorithm == "xxhash" and not HAS_XXHASH:
        print("⚠️ xxhash 未安装,回退到 MD5。安装: pip install xxhash")
        algorithm = "md5"

    # 扫描源文件夹
    if args.verbose:
        print(f"\n🔍 扫描源文件夹: {source}")

    source_files = scan_folder(source, args.verbose)

    if not source_files:
        print("⚠️ 源文件夹为空,无文件需要拷贝")
        sys.exit(0)

    # 初始化结果
    result = SyncResult(
        source=source,
        target=target,
        algorithm=algorithm,
        double_verify=args.double_verify
    )
    result.start_time = time.time()

    # ========== 校验模式：仅校验已有文件，不拷贝 ==========
    if args.verify:
        if args.verbose:
            print(f"\n🔍 校验模式: 仅验证已存在文件，不拷贝")
            print(f"🔐 哈希算法: {algorithm.upper()}")

        # 扫描目标文件夹
        if args.verbose:
            print(f"🔍 扫描目标文件夹: {target}")
        target_files = scan_folder(target, args.verbose)

        # 找出源和目标都存在的文件
        common_files = set(source_files.keys()) & set(target_files.keys())
        only_in_source = set(source_files.keys()) - set(target_files.keys())
        only_in_target = set(target_files.keys()) - set(source_files.keys())
        total_verify = len(common_files)

        if args.verbose:
            print(f"\n📊 文件统计:")
            print(f"   源文件夹文件数: {len(source_files)}")
            print(f"   目标文件夹文件数: {len(target_files)}")
            print(f"   共同文件数: {total_verify}")
            if only_in_source:
                print(f"   ⚠️ 仅存在于源: {len(only_in_source)} 个文件")
            if only_in_target:
                print(f"   ⚠️ 仅存在于目标: {len(only_in_target)} 个文件")

        if total_verify == 0:
            print("⚠️ 没有共同文件需要校验")
            sys.exit(0)

        # 统计信息
        stats = {'bytes': 0, 'time': 0}

        # 校验共同文件
        for idx, rel_path in enumerate(sorted(common_files), 1):
            source_path = source_files[rel_path]
            target_path = target_files[rel_path]

            if args.verbose:
                print_progress(idx, total_verify, rel_path, stats)

            try:
                source_size = source_path.stat().st_size
                target_size = target_path.stat().st_size
            except OSError as e:
                result.failed.append(rel_path)
                if args.verbose:
                    print(f"\n❌ 无法读取文件大小: {rel_path} ({e})")
                continue

            # 大小不同直接判定为失败
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
                continue

            # 计算源文件哈希 (流式读取但不写入)
            source_hash, _, _, error = compute_file_hash(
                source_path,
                algorithm,
                retries=args.retries
            )

            if error:
                file_result = FileResult(
                    relative_path=rel_path,
                    source_size=source_size,
                    success=False,
                    error=f"源文件哈希计算失败: {error}"
                )
                result.files.append(file_result)
                result.failed.append(rel_path)
                continue

            # 计算目标文件哈希并校验
            verified, target_hash, verify_error = verify_file_hash(
                target_path,
                algorithm,
                source_hash,
                retries=args.retries
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
            result.total_bytes += target_size

        result.end_time = time.time()

        # 打印校验结果
        if args.verbose:
            print()  # 换行

        print("\n" + "=" * 50)
        print("📊 校验完成")
        print("=" * 50)
        print(f"源文件夹: {source}")
        print(f"目标文件夹: {target}")
        print(f"哈希算法: {algorithm.upper()}")
        print()
        print(f"✅ 校验通过: {len(result.copied)} 个文件")
        print(f"❌ 校验失败: {len(result.failed)} 个文件")

        if only_in_source:
            print(f"\n⚠️ 仅存在于源文件夹: {len(only_in_source)} 个文件")
        if only_in_target:
            print(f"⚠️ 仅存在于目标文件夹: {len(only_in_target)} 个文件")

        duration = result.end_time - result.start_time
        print(f"\n⏱️ 总耗时: {duration:.1f} 秒")

        # 生成 JSON 报告
        if args.report:
            report_data = generate_report(result)
            # 在报告中添加校验模式信息
            report_data["metadata"]["verify_mode"] = True
            try:
                with open(args.report, 'w', encoding='utf-8') as f:
                    json.dump(report_data, f, indent=2, ensure_ascii=False)
                print(f"\n📄 JSON 报告已保存: {args.report}")
            except IOError as e:
                print(f"\n❌ 无法保存报告: {e}", file=sys.stderr)

        # 显示失败文件列表
        if result.failed:
            print("\n❌ 失败文件列表:")
            for f in result.failed[:10]:
                print(f"  - {f}")
            if len(result.failed) > 10:
                print(f"  ... 还有 {len(result.failed) - 10} 个")

        sys.exit(1 if result.failed else 0)

    # ========== 正常拷贝模式 ==========

    # 排序文件列表
    sorted_files = sorted(source_files.items())
    total_files = len(sorted_files)

    if args.verbose:
        print(f"\n📦 开始拷贝: {total_files} 个文件")
        print(f"🔐 哈希算法: {algorithm.upper()}")
        if args.double_verify:
            print("✓ 双重校验: 已启用")
        print()

    # 统计信息
    stats = {'bytes': 0, 'time': 0}

    # 处理每个文件
    for idx, (rel_path, source_path) in enumerate(sorted_files, 1):
        target_path = target / rel_path

        # 获取源文件大小
        try:
            source_size = source_path.stat().st_size
        except OSError as e:
            result.failed.append(rel_path)
            if args.verbose:
                print(f"\n❌ 无法读取文件大小: {rel_path} ({e})")
            continue

        # 显示进度
        if args.verbose:
            print_progress(idx, total_files, rel_path, stats)

        # 检查目标文件是否已存在
        if target_path.exists() and args.skip_existing:
            result.skipped.append(rel_path)
            continue

        # 流式拷贝并计算哈希
        source_hash, copy_time, bytes_copied, error = copy_with_streaming_hash(
            source_path,
            target_path,
            algorithm,
            retries=args.retries
        )

        if error:
            result.failed.append(rel_path)
            if args.verbose:
                print(f"\n❌ 拷贝失败: {rel_path} ({error})")
            continue

        # 创建文件结果
        file_result = FileResult(
            relative_path=rel_path,
            source_size=source_size,
            target_size=bytes_copied,
            source_hash=source_hash,
            copy_time=copy_time,
            success=True
        )

        # 二次校验(如果启用)
        if args.double_verify:
            verified, verify_hash, verify_error = verify_file_hash(
                target_path,
                algorithm,
                source_hash,
                retries=args.retries
            )
            file_result.verify_hash = verify_hash

            if not verified:
                file_result.success = False
                file_result.error = verify_error or "校验哈希不匹配"
                result.failed.append(rel_path)
                if args.verbose:
                    print(f"\n❌ 二次校验失败: {rel_path}")
                continue

        # 成功
        result.copied.append(rel_path)
        result.files.append(file_result)
        result.total_bytes += bytes_copied
        stats['bytes'] = result.total_bytes
        stats['time'] = result.end_time - result.start_time

    result.end_time = time.time()

    # 打印最终结果
    if args.verbose:
        print()  # 换行

    print("\n" + "=" * 50)
    print("📊 拷贝完成")
    print("=" * 50)
    print(f"源文件夹: {source}")
    print(f"目标文件夹: {target}")
    print(f"哈希算法: {algorithm.upper()}")
    print()
    print(f"✅ 成功拷贝: {len(result.copied)} 个文件")
    print(f"⏭️  跳过文件: {len(result.skipped)} 个文件")
    print(f"❌ 失败文件: {len(result.failed)} 个文件")
    print()
    print(f"📦 总数据量: {format_size(result.total_bytes)}")
    duration = result.end_time - result.start_time
    print(f"⏱️  总耗时: {duration:.1f} 秒")
    print(f"🚀 平均速度: {format_speed(result.total_bytes, duration)}")

    if args.double_verify:
        print(f"✓ 双重校验: 已完成")

    # 生成 JSON 报告
    if args.report:
        report_data = generate_report(result)
        try:
            with open(args.report, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, indent=2, ensure_ascii=False)
            print(f"\n📄 JSON 报告已保存: {args.report}")
        except IOError as e:
            print(f"\n❌ 无法保存报告: {e}", file=sys.stderr)

    # 显示失败文件列表
    if result.failed:
        print("\n❌ 失败文件列表:")
        for f in result.failed[:10]:
            print(f"  - {f}")
        if len(result.failed) > 10:
            print(f"  ... 还有 {len(result.failed) - 10} 个")

    # 返回退出码
    sys.exit(1 if result.failed else 0)


if __name__ == "__main__":
    main()

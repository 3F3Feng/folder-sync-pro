#!/usr/bin/env python3
"""
文件夹一致性校验工具 - Folder Sync Checker

递归扫描并对比两个文件夹，检测文件差异（缺失、损坏、多余）。
支持 MD5/SHA256 哈希校验和多线程加速。
"""

import argparse
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Set, Tuple


class FileInfo(NamedTuple):
    """文件信息结构"""
    path: str  # 相对路径
    full_path: str  # 完整路径
    size: int  # 文件大小


class CheckResult(NamedTuple):
    """校验结果"""
    matched: List[str]  # 一致文件
    missing: List[str]  # 缺失文件（源有目标无）
    corrupted: List[str]  # 损坏文件（哈希不匹配）
    extra: List[str]  # 多余文件（目标有源无）


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="📁 文件夹一致性校验工具 - 递归对比两个文件夹并报告差异",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s /data/photos /backup/photos
  %(prog)s /data/photos /backup/photos --quick
  %(prog)s /data/photos /backup/photos --hash sha256 --threads 8
  %(prog)s /data/photos /backup/photos --report result.json --verbose
        """
    )
    
    parser.add_argument(
        "source",
        help="源文件夹路径"
    )
    parser.add_argument(
        "target",
        help="目标文件夹路径"
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="快速模式：仅对比文件列表，不计算哈希"
    )
    parser.add_argument(
        "--hash",
        choices=["md5", "sha256"],
        default="md5",
        help="哈希算法选择 (默认: md5)"
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=4,
        help="并发线程数 (默认: 4)"
    )
    parser.add_argument(
        "--report",
        metavar="FILE",
        help="输出 JSON 格式报告到指定文件"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="显示详细进度信息"
    )
    
    return parser.parse_args()


def validate_path(path_str: str, name: str) -> Path:
    """验证路径有效性"""
    path = Path(path_str)
    if not path.exists():
        print(f"❌ 错误: {name}路径不存在: {path}", file=sys.stderr)
        sys.exit(1)
    if not path.is_dir():
        print(f"❌ 错误: {name}不是文件夹: {path}", file=sys.stderr)
        sys.exit(1)
    return path.resolve()


def scan_folder(folder: Path, verbose: bool = False) -> Dict[str, FileInfo]:
    """递归扫描文件夹，返回相对路径到文件信息的映射"""
    files = {}
    
    if verbose:
        print(f"🔍 扫描: {folder}")
    
    for root, _, filenames in os.walk(folder):
        for filename in filenames:
            full_path = Path(root) / filename
            rel_path = str(full_path.relative_to(folder))
            
            try:
                size = full_path.stat().st_size
                files[rel_path] = FileInfo(
                    path=rel_path,
                    full_path=str(full_path),
                    size=size
                )
            except OSError as e:
                if verbose:
                    print(f"⚠️  跳过无法访问的文件: {rel_path} ({e})")
                continue
    
    return files


def compute_hash(file_path: str, algorithm: str = "md5") -> Optional[str]:
    """计算文件哈希值"""
    hash_func = hashlib.md5() if algorithm == "md5" else hashlib.sha256()
    
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hash_func.update(chunk)
        return hash_func.hexdigest()
    except (OSError, IOError) as e:
        return None


def hash_file_wrapper(args: Tuple[str, str, str]) -> Tuple[str, Optional[str]]:
    """哈希计算的包装函数，用于多线程"""
    rel_path, full_path, algorithm = args
    return rel_path, compute_hash(full_path, algorithm)


def compute_hashes(
    files: Dict[str, FileInfo],
    algorithm: str,
    threads: int,
    verbose: bool = False
) -> Dict[str, str]:
    """多线程计算文件哈希"""
    hashes = {}
    total = len(files)
    
    if total == 0:
        return hashes
    
    if verbose:
        print(f"🔐 计算哈希 ({algorithm.upper()})...")
    
    work_items = [
        (rel_path, info.full_path, algorithm)
        for rel_path, info in files.items()
    ]
    
    completed = 0
    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = {executor.submit(hash_file_wrapper, item): item[0] 
                   for item in work_items}
        
        for future in as_completed(futures):
            rel_path, file_hash = future.result()
            if file_hash:
                hashes[rel_path] = file_hash
            elif verbose:
                print(f"⚠️  无法计算哈希: {rel_path}")
            
            completed += 1
            if verbose and completed % max(1, total // 20) == 0:
                pct = (completed / total) * 100
                print(f"   进度: {completed}/{total} ({pct:.1f}%)")
    
    return hashes


def compare_folders(
    source_files: Dict[str, FileInfo],
    target_files: Dict[str, FileInfo],
    source_hashes: Dict[str, str],
    target_hashes: Dict[str, str],
    quick_mode: bool
) -> CheckResult:
    """对比两个文件夹的内容"""
    source_set = set(source_files.keys())
    target_set = set(target_files.keys())
    
    # 缺失文件：源有目标无
    missing = sorted(source_set - target_set)
    
    # 多余文件：目标有源无
    extra = sorted(target_set - source_set)
    
    # 共同文件
    common = source_set & target_set
    
    matched = []
    corrupted = []
    
    if quick_mode:
        # 快速模式：仅比较文件大小
        for rel_path in sorted(common):
            if source_files[rel_path].size == target_files[rel_path].size:
                matched.append(rel_path)
            else:
                corrupted.append(rel_path)
    else:
        # 完整模式：比较哈希值
        for rel_path in sorted(common):
            src_hash = source_hashes.get(rel_path)
            tgt_hash = target_hashes.get(rel_path)
            
            if src_hash and tgt_hash and src_hash == tgt_hash:
                matched.append(rel_path)
            else:
                corrupted.append(rel_path)
    
    return CheckResult(
        matched=matched,
        missing=missing,
        corrupted=corrupted,
        extra=extra
    )


def format_count(count: int) -> str:
    """格式化数字，添加千位分隔符"""
    return f"{count:,}"


def print_report(
    source: Path,
    target: Path,
    result: CheckResult,
    source_count: int,
    target_count: int,
    algorithm: str,
    threads: int,
    duration: float,
    quick_mode: bool
):
    """打印终端报告"""
    print()
    print("📁 文件夹一致性校验")
    print("━━━━━━━━━━━━━━━━━━━━━━")
    print(f"源: {source} ({format_count(source_count)} 文件)")
    print(f"目标: {target} ({format_count(target_count)} 文件)")
    print(f"算法: {algorithm.upper()} | 线程: {threads}" + 
          (" | 快速模式" if quick_mode else ""))
    print()
    
    # 一致文件
    print(f"✅ 一致文件: {format_count(len(result.matched))}")
    
    # 缺失文件
    print(f"❌ 缺失文件: {format_count(len(result.missing))}")
    for path in result.missing[:10]:  # 最多显示10个
        print(f"   - {path}")
    if len(result.missing) > 10:
        print(f"   ... 还有 {len(result.missing) - 10} 个")
    
    # 损坏文件
    print(f"⚠️  内容损坏: {format_count(len(result.corrupted))}")
    for path in result.corrupted[:10]:
        print(f"   - {path}")
    if len(result.corrupted) > 10:
        print(f"   ... 还有 {len(result.corrupted) - 10} 个")
    
    # 多余文件
    print(f"❓ 多余文件: {format_count(len(result.extra))}")
    for path in result.extra[:10]:
        print(f"   - {path}")
    if len(result.extra) > 10:
        print(f"   ... 还有 {len(result.extra) - 10} 个")
    
    print()
    print(f"📊 校验完成: 耗时 {duration:.1f}s")


def generate_json_report(
    source: Path,
    target: Path,
    result: CheckResult,
    source_count: int,
    target_count: int,
    algorithm: str,
    threads: int,
    quick_mode: bool,
    duration: float
) -> dict:
    """生成 JSON 格式报告"""
    return {
        "source": str(source),
        "target": str(target),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "options": {
            "hash_algorithm": algorithm,
            "threads": threads,
            "quick_mode": quick_mode
        },
        "summary": {
            "source_files": source_count,
            "target_files": target_count,
            "matched": len(result.matched),
            "missing": len(result.missing),
            "corrupted": len(result.corrupted),
            "extra": len(result.extra)
        },
        "missing_files": result.missing,
        "corrupted_files": result.corrupted,
        "extra_files": result.extra,
        "duration_seconds": round(duration, 3)
    }


def main():
    """主函数"""
    args = parse_args()
    
    # 验证路径
    source = validate_path(args.source, "源")
    target = validate_path(args.target, "目标")
    
    start_time = time.time()
    
    # 扫描文件夹
    if args.verbose:
        print()
    
    source_files = scan_folder(source, args.verbose)
    target_files = scan_folder(target, args.verbose)
    
    # 计算哈希（非快速模式）
    if not args.quick:
        source_hashes = compute_hashes(
            source_files, args.hash, args.threads, args.verbose
        )
        target_hashes = compute_hashes(
            target_files, args.hash, args.threads, args.verbose
        )
    else:
        source_hashes = {}
        target_hashes = {}
    
    # 对比文件夹
    result = compare_folders(
        source_files, target_files,
        source_hashes, target_hashes,
        args.quick
    )
    
    duration = time.time() - start_time
    
    # 打印报告
    print_report(
        source, target, result,
        len(source_files), len(target_files),
        args.hash, args.threads, duration, args.quick
    )
    
    # 生成 JSON 报告
    if args.report:
        report_data = generate_json_report(
            source, target, result,
            len(source_files), len(target_files),
            args.hash, args.threads, args.quick, duration
        )
        
        try:
            with open(args.report, "w", encoding="utf-8") as f:
                json.dump(report_data, f, indent=2, ensure_ascii=False)
            print(f"\n📄 JSON 报告已保存: {args.report}")
        except IOError as e:
            print(f"\n❌ 无法保存报告文件: {e}", file=sys.stderr)
    
    # 返回退出码：有差异则返回 1
    if result.missing or result.corrupted:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()

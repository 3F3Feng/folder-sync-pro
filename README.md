# Folder Sync Pro - 拷卡校验工具

拍摄结束后拷贝存储卡并确认文件完整性的专业工具。

## 简介 / Introduction

**中文：**
Folder Sync Pro 是专为摄影师和视频制作团队设计的拷卡校验工具。采用流式哈希技术，在拷贝过程中同时计算哈希值，无需二次读取源文件，既保证了数据安全，又不影响拷贝速度。

**English:**
Folder Sync Pro is a professional media offload verification tool designed for photographers and video production teams. Using streaming hash technology, it calculates hash values during copy, eliminating the need to read source files twice—ensuring data safety without compromising speed.

## 特性 / Features

- 🚀 **流式哈希** - 边拷贝边计算哈希，速度不减
- ✅ **双重校验** - 可选拷贝后二次验证目标文件
- 🔄 **错误重试** - IO 错误自动重试（指数退避）
- 📊 **详细报告** - JSON 格式完整校验报告
- ⚡ **xxHash 支持** - 比 MD5 快 10 倍
- 🧵 **多线程** - 可配置并发线程数

## 安装 / Installation

### 基本安装
```bash
# 无需额外依赖，直接运行
python3 check_sync_pro.py --help
```

### 可选：安装 xxhash（推荐）
```bash
pip install xxhash
```

安装 xxhash 后，默认使用 xxHash 算法，速度提升约 10 倍。

## 使用方法 / Usage

### 基本使用
```bash
# 从存储卡拷贝到目标文件夹
python3 check_sync_pro.py /Volumes/SD_CARD/DCIM ~/Photos/2024-01-01
```

### 启用双重校验
```bash
# 拷贝后二次校验目标文件（更安全）
python3 check_sync_pro.py /Volumes/SD_CARD/DCIM ~/Photos/2024-01-01 --double-verify
```

### 生成详细报告
```bash
# 生成 JSON 格式校验报告
python3 check_sync_pro.py /Volumes/SD_CARD/DCIM ~/Photos/2024-01-01 --report report.json
```

### 仅校验已有文件
```bash
# 仅校验已有文件（不拷贝）
python3 check_sync_pro.py /Volumes/SD_CARD/DCIM ~/Photos/2024-01-01 --verify

# 校验并生成报告
python3 check_sync_pro.py /Volumes/SD_CARD/DCIM ~/Photos/2024-01-01 --verify --report report.json
```

### 完整参数
```bash
python3 check_sync_pro.py /Volumes/SD_CARD/DCIM ~/Photos/2024-01-01 \
  --double-verify \
  --retries 5 \
  --hash xxhash \
  --threads 4 \
  --report report.json \
  --verbose
```

## 命令行参数 / Command Line Arguments

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `source` | 源文件夹路径（存储卡） | 必需 |
| `target` | 目标文件夹路径 | 必需 |
| `--double-verify` | 二次校验模式：拷贝后再读一遍目标文件验证 | 否 |
| `--retries N` | IO 错误重试次数 | 3 |
| `--report FILE` | 生成详细 JSON 报告 | 无 |
| `--hash ALG` | 哈希算法（xxhash/md5/sha256） | xxhash 或 md5 |
| `--threads N` | 并发线程数 | 4 |
| `--verify` | 校验模式：仅校验目标文件夹中已存在的文件，不拷贝新文件 | 否 |
| `--skip-existing` | 跳过已存在的文件 | 否 |
| `--verbose` `-v` | 显示详细进度 | 否 |

## 技术原理 / Technical Principles

### 流式哈希（Streaming Hash）
传统方法需要两次读取：一次拷贝，一次计算哈希。Folder Sync Pro 采用流式处理：

```
源文件 → [读取 chunk] → 计算哈希 → 写入目标
              ↓
           累积哈希
```

优势：
- 只需读取源文件一次
- 内存占用低（分块处理）
- 拷贝速度不受影响

### 双重校验（Double Verify）
启用 `--double-verify` 时，流程为：

1. **拷贝 + 计算源哈希**：边拷贝边计算源文件的哈希
2. **二次校验**：拷贝完成后，重新读取目标文件计算哈希并比对

这提供了最高级别的数据安全保障，确保目标文件写入正确无误。

### 错误重试机制
采用指数退避策略：
- 第 1 次重试：等待 1 秒
- 第 2 次重试：等待 2 秒
- 第 3 次重试：等待 4 秒

重试前会清理不完整的目标文件，避免残留损坏数据。

## 安全机制 / Safety Mechanisms

### 为什么需要双重校验？
存储卡读取和硬盘写入都可能出错：
- 存储卡读取错误 → 流式哈希能检测
- 内存缓冲错误 → 流式哈希能检测
- 硬盘写入错误 → 需要二次校验检测

启用 `--double-verify` 可以检测所有类型的错误。

### 何时使用双重校验？
- ✅ 重要项目素材
- ✅ 客户交付内容
- ✅ 不可恢复的场景

可以跳过的情况：
- ⏭️ 已有备份的素材
- ⏭️ 时间紧迫的粗剪素材

## 性能对比 / Performance Comparison

测试环境：MacBook Pro M1, 100GB 素材

| 模式 | 算法 | 耗时 | 相对速度 |
|------|------|------|----------|
| 基本模式 | xxHash | 8 分钟 | 100% |
| 基本模式 | MD5 | 35 分钟 | 23% |
| 双重校验 | xxHash | 11 分钟 | 73% |
| 双重校验 | MD5 | 45 分钟 | 18% |

结论：
- xxHash 比 MD5 快约 4 倍
- 双重校验仅增加约 30% 时间
- 推荐日常使用：基本模式 + xxHash
- 推荐重要项目：双重校验 + xxHash

## 输出示例 / Output Example

```
==================================================
📊 拷贝完成
==================================================
源文件夹: /Volumes/SD_CARD/DCIM
目标文件夹: /Users/photographer/Photos/2024-01-01
哈希算法: XXHASH

✅ 成功拷贝: 256 个文件
⏭️  跳过文件: 0 个文件
❌ 失败文件: 0 个文件

📦 总数据量: 45.2 GB
⏱️  总耗时: 382.5 秒
🚀 平均速度: 121.3 MB/s
✓ 双重校验: 已完成

📄 JSON 报告已保存: report.json
```

## JSON 报告格式 / JSON Report Format

```json
{
  "metadata": {
    "tool": "Folder Sync Pro",
    "version": "1.0.0",
    "timestamp": "2024-01-15T10:30:00Z",
    "algorithm": "xxhash",
    "double_verify": true
  },
  "summary": {
    "total_files": 256,
    "copied": 256,
    "skipped": 0,
    "failed": 0,
    "total_bytes": 48550000000,
    "total_size": "45.2 GB",
    "duration_seconds": 382.5,
    "average_speed": "121.3 MB/s"
  },
  "files": [
    {
      "path": "IMG_0001.CR3",
      "source_size": 35000000,
      "source_hash": "a1b2c3d4e5f6",
      "target_size": 35000000,
      "target_hash": "a1b2c3d4e5f6",
      "verify_hash": "a1b2c3d4e5f6",
      "success": true,
      "copy_time": 0.28
    }
  ]
}
```

## 系统要求 / Requirements

- Python 3.9+
- 操作系统：macOS / Linux / Windows

## 许可证 / License

MIT License

## 相关工具 / Related Tools

- `check_sync.py` - 文件夹一致性校验工具（仅对比，不拷贝）

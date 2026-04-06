# Folder Sync Pro - 拷卡校验工具

拍摄结束后拷贝存储卡并确认文件完整性的专业工具。

## 简介 / Introduction

**中文：**
Folder Sync Pro 是专为摄影师和视频制作团队设计的拷卡校验工具。采用流式哈希技术，在拷贝过程中同时计算哈希值，无需二次读取源文件，既保证了数据安全，又不影响拷贝速度。支持专业 DIT 工作流程，包括 MHL 报告、校验码文件、多源拷贝等。

**English:**
Folder Sync Pro is a professional media offload verification tool designed for photographers and video production teams. Using streaming hash technology, it calculates hash values during copy, eliminating the need to read source files twice—ensuring data safety without compromising speed. Supports professional DIT workflows including MHL reports, sidecar hash files, and multi-source copy.

## 特性 / Features

- 🚀 **流式哈希** - 边拷贝边计算哈希，速度不减
- ✅ **双重校验** - 可选拷贝后二次验证目标文件
- 🔄 **错误重试** - IO 错误自动重试（指数退避）
- 📊 **详细报告** - JSON 格式完整校验报告
- ⚡ **xxHash 支持** - 比 MD5 快 10 倍
- 🔄 **断点续传** - 支持大文件中断后恢复拷贝

### 专业 DIT 功能

- 📋 **MHL 报告** - 生成 ASC MHL v1.1 标准校验报告（Silverstack、YoYotta、DaVinci Resolve 兼容）
- 🔐 **校验码文件** - 生成 .xxhash/.md5 伴随文件
- 🔁 **多源拷贝** - 多张存储卡同时拷贝到多个目标
- ⏰ **元数据保留** - 完整保留文件时间戳和扩展属性

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

### 可选：安装 xattr（用于扩展属性）
```bash
pip install xattr
```

## 使用方法 / Usage

### 基本使用
```bash
# 从存储卡拷贝到目标文件夹
python3 check_sync_pro.py /Volumes/SD_CARD/DCIM ~/Photos/2024-01-01
```

### 断点续传 / Resuming Copies
对于大文件拷贝，中断后恢复的功能至关重要。

```bash
# 启用实时进度条，并每 10 秒保存一次进度
# 如果中断，会自动在目标文件夹下生成 .sync-progress.json 文件
python3 check_sync_pro.py /path/to/source /path/to/target --progress

# 自定义进度保存间隔（例如每 5 秒）
python3 check_sync_pro.py /path/to/source /path/to/target --progress --checkpoint 5

# 从指定的进度文件恢复拷贝
python3 check_sync_pro.py --resume /path/to/target/.sync-progress.json
```
**注意:** 当使用 `--progress` 时，如果脚本被中断 (Ctrl+C)，它会尝试保存最后的进度，并提示如何恢复。

### 启用双重校验
```bash
# 拷贝后二次校验目标文件（更安全）
python3 check_sync_pro.py /Volumes/SD_CARD/DCIM ~/Photos/2024-01-01 --double-verify
```

### 生成 MHL 报告（影视行业标准）
```bash
# 生成 ASC MHL v1.1 标准校验报告
python3 check_sync_pro.py /Volumes/SD_CARD/DCIM ~/Photos/2024-01-01 --mhl

# 指定项目名称
python3 check_sync_pro.py /Volumes/SD_CARD/DCIM ~/Photos/2024-01-01 --mhl --project-name "MyProject"

# 指定 MHL 输出路径
python3 check_sync_pro.py /Volumes/SD_CARD/DCIM ~/Photos/2024-01-01 --mhl --mhl-output ~/Reports/project.mhl
```

### 生成校验码伴随文件
```bash
# 为每个文件生成 .xxhash 伴随文件
python3 check_sync_pro.py /Volumes/SD_CARD/DCIM ~/Photos/2024-01-01 --sidecar

# 使用 MD5 格式
python3 check_sync_pro.py /Volumes/SD_CARD/DCIM ~/Photos/2024-01-01 --sidecar --hash md5
```

### 多源拷贝（多卡备份）
```bash
# 从两张卡拷贝到两个备份盘（串行）
python3 check_sync_pro.py \
  --sources /Volumes/SD_CARD1 /Volumes/SD_CARD2 \
  --targets /Volumes/Backup1 /Volumes/Backup2

# 并行拷贝（2个并发任务）
python3 check_sync_pro.py \
  --sources /Volumes/SD_CARD1 /Volumes/SD_CARD2 \
  --targets /Volumes/Backup1 /Volumes/Backup2 \
  --parallel 2 \
  --mhl

# 完整专业模式
python3 check_sync_pro.py \
  --sources /Volumes/SD_CARD1 /Volumes/SD_CARD2 \
  --targets /Volumes/Backup1 /Volumes/Backup2 \
  --parallel 2 \
  --double-verify \
  --mhl \
  --sidecar \
  --preserve-xattr \
  --report report.json \
  --verbose
```

### 元数据保留
```bash
# 保留文件时间戳（默认启用）
python3 check_sync_pro.py /Volumes/SD_CARD/DCIM ~/Photos/2024-01-01 --preserve-metadata

# 禁用时间戳保留
python3 check_sync_pro.py /Volumes/SD_CARD/DCIM ~/Photos/2024-01-01 --no-preserve-metadata

# 保留扩展属性（macOS 标签等，需要 xattr 模块）
python3 check_sync_pro.py /Volumes/SD_CARD/DCIM ~/Photos/2024-01-01 --preserve-xattr
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
  --report report.json \
  --mhl \
  --sidecar \
  --preserve-xattr \
  --verbose
```

## 命令行参数 / Command Line Arguments

### 基本参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `source` | 源文件夹路径（存储卡） | 必需 |
| `target` | 目标文件夹路径 | 必需 |

### 多源拷贝参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--sources PATH...` | 多个源文件夹路径 | 无 |
| `--targets PATH...` | 多个目标文件夹路径 | 无 |
| `--parallel N` | 并发拷贝数 | 1 |

### 校验参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--double-verify` | 二次校验模式：拷贝后再读一遍目标文件验证 | 否 |
| `--retries N` | IO 错误重试次数 | 3 |
| `--verify` | 校验模式：仅校验目标文件夹中已存在的文件，不拷贝新文件 | 否 |

### 输出参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--report FILE` | 生成详细 JSON 报告 | 无 |
| `--mhl` | 生成 ASC MHL v1.1 标准校验报告 | 否 |
| `--mhl-output FILE` | MHL 报告输出路径 | 自动生成 |
| `--project-name NAME` | 项目名称（用于 MHL 报告） | 目标文件夹名 |
| `--sidecar` | 生成校验码伴随文件(.xxhash 或 .md5) | 否 |

### 哈希参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--hash ALG` | 哈希算法（xxhash/md5/sha256） | xxhash 或 md5 |

### 拷贝参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--skip-existing` | 跳过已存在的文件 | 否 |

### 元数据参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--preserve-metadata` | 保留文件时间戳 | 是 |
| `--no-preserve-metadata` | 不保留文件时间戳 | 否 |
| `--preserve-xattr` | 保留文件扩展属性（需要 xattr 模块） | 否 |

### 其他参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--verbose` `-v` | 显示详细进度 | 否 |

### 断点续传参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--progress` | 显示实时进度条并启用进度保存 | 否 |
| `--resume FILE` | 从指定的进度文件恢复拷贝 | 无 |
| `--checkpoint N`| 每 N 秒保存一次进度 | 10 |

## MHL 报告格式 / MHL Report Format

MHL (Media Hash List) 是影视行业标准的校验报告格式，可被以下软件识别：
- Silverstack
- YoYotta
- DaVinci Resolve
- 其他支持 ASC MHL 的软件

### MHL 文件示例
```xml
<?xml version="1.0" encoding="UTF-8"?>
<hashlist version="1.1">
  <creatorinfo>
    <name>Folder Sync Pro</name>
    <version>1.0.0</version>
    <hostname>MacBook-Pro</hostname>
    <tool>check_sync_pro.py</tool>
    <startdate>2024-01-15T10:30:00Z</startdate>
    <finishdate>2024-01-15T10:45:00Z</finishdate>
  </creatorinfo>
  <hash>
    <file>A001_C001_0115AB/Contents/Clip001.mxf</file>
    <size>1073741824</size>
    <xxhash64>a1b2c3d4e5f67890</xxhash64>
    <hashdate>2024-01-15T10:31:00Z</hashdate>
  </hash>
</hashlist>
```

### 使用 MHL 的工作流程
1. 拷贝完成后生成 MHL 报告
2. 将 MHL 文件与素材一起保存
3. 在后期软件中导入 MHL 验证素材完整性

## 校验码文件格式 / Sidecar Hash File Format

每个文件生成对应的哈希伴随文件：

| 原文件 | 伴随文件 (xxhash) | 伴随文件 (md5) |
|--------|-------------------|----------------|
| `Clip001.mxf` | `Clip001.mxf.xxhash` | `Clip001.mxf.md5` |

伴随文件内容示例：
```
a1b2c3d4e5f67890
```

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

### 断点续传与恢复 (Resuming Copies)
启用 `--progress` 后，脚本会周期性地（通过 `--checkpoint` 控制）将当前拷贝进度保存到目标文件夹下的 `.sync-progress.json` 文件中。如果拷贝过程被中断（如 `Ctrl+C`、系统休眠或奔溃），可以从这个文件恢复。

**恢复时的安全校验**:
为了防止从已损坏的局部文件继续拷贝，恢复流程包含一个关键的校验步骤：
1.  计算已存在局部文件的哈希值。
2.  计算源文件对应部分的哈希值。
3.  **只有当两个哈希值完全一致时**，才会从断点继续拷贝。
4.  如果哈希值不匹配，说明局部文件已损坏，脚本会自动删除损坏文件，从头开始拷贝。

这个机制确保了即使在恢复拷贝时，数据的完整性也得到最高保障。

### 错误重试机制
采用指数退避策略：
- 第 1 次重试：等待 1 秒
- 第 2 次重试：等待 2 秒
- 第 3 次重试：等待 4 秒

重试前会清理不完整的目标文件，避免残留损坏数据。

### 多源拷贝
多源拷贝支持从多张存储卡同时拷贝到多个目标：
- **串行模式**（默认）：依次处理每个源-目标对
- **并行模式**（`--parallel N`）：同时处理 N 个任务

示例：2 张卡 → 2 个备份盘 = 4 个拷贝任务

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

### 单源拷贝
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
📄 MHL 报告已保存: 2024-01-01_20240115103000.mhl
```

### 多源拷贝
```
============================================================
📊 多源拷贝完成
============================================================

总任务数: 4
✅ 成功拷贝: 512 个文件
⏭️  跳过文件: 0 个文件
❌ 失败文件: 0 个文件

📦 总数据量: 90.4 GB
⏱️  总耗时: 765.0 秒
🚀 平均速度: 120.5 MB/s

各任务详情:
  ✅ SD_CARD1 → Backup1: 256 成功, 0 失败
  ✅ SD_CARD1 → Backup2: 256 成功, 0 失败
  ✅ SD_CARD2 → Backup1: 256 成功, 0 失败
  ✅ SD_CARD2 → Backup2: 256 成功, 0 失败

📄 MHL 报告已保存: Backup1/MyProject_20240115103000.mhl
📄 MHL 报告已保存: Backup2/MyProject_20240115103000.mhl
```

## JSON 报告格式 / JSON Report Format

### 单源报告
```json
{
  "metadata": {
    "tool": "Folder Sync Pro",
    "version": "1.0.0",
    "timestamp": "2024-01-15T10:30:00Z",
    "algorithm": "xxhash",
    "double_verify": true,
    "source": "/Volumes/SD_CARD/DCIM",
    "target": "/Users/photographer/Photos/2024-01-01"
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

### 多源报告
```json
{
  "metadata": {
    "tool": "Folder Sync Pro",
    "version": "1.0.0",
    "timestamp": "2024-01-15T10:30:00Z",
    "algorithm": "xxhash",
    "sources": ["/Volumes/SD_CARD1", "/Volumes/SD_CARD2"],
    "targets": ["/Volumes/Backup1", "/Volumes/Backup2"],
    "multi_source": true
  },
  "summary": {
    "total_tasks": 4,
    "total_copied": 512,
    "total_failed": 0,
    "total_skipped": 0,
    "total_bytes": 97000000000,
    "total_size": "90.4 GB",
    "duration_seconds": 765.0
  },
  "tasks": [...]
}
```

## 系统要求 / Requirements

- Python 3.9+
- 操作系统：macOS / Linux / Windows
- 可选：xxhash（提升速度）
- 可选：xattr（扩展属性保留，macOS）

## 更新日志 / Changelog

### v1.1.0 (2026-04-06)

#### 命令行输出架构重构

**P0 - 必须修复:**

1. **统一 stdout/stderr 输出规则**
   - INFO, SUCCESS 消息 → stdout
   - WARNING, ERROR 消息 → stderr
   - 进度条 → stdout (ANSI 控制)
   - 警告消息（如 xxhash 未安装）现在明确输出到 stderr

2. **修复 ProgressManager 状态机**
   - 修复跳过文件时的进度条闪烁问题
   - 跳过文件现在正确显示累积进度（文件数/总文件数）
   - 添加 `skipped` 参数到 `start_file()` 方法
   - 添加 `finalize()` 方法确保最后一个文件正确显示

3. **消除重复扫描**
   - `run_copy()` 中只扫描一次源文件夹
   - `sync_single_pair()` 接受预扫描的源文件字典
   - 避免重复 `scan_folder()` 调用

**P1 - 重要改进:**

4. **统一终端宽度获取**
   - 添加全局常量 `TERMINAL_WIDTH`
   - 移除重复的 `shutil.get_terminal_size()` 调用

5. **Terminal Width 动态更新**
   - `ProgressManager._render_unlocked()` 每次 render 时重新获取终端宽度
   - 用户调整终端窗口大小时自动自适应

6. **清理裸 print() 语句**
   - 警告消息现在明确使用 `file=sys.stderr`

**P2 - 合并进度显示:**

7. **合并 print_progress() 到 ProgressManager**
   - 添加 `print_progress_line()` 方法到 ProgressManager
   - 统一单行进度显示逻辑
   - 保留独立的 `print_progress()` 函数用于向后兼容

**P3 - 统一输出接口:**

8. **添加 OutputManager 类**
   - 统一 stdout/stderr 输出接口
   - 方法: `info()`, `success()`, `warning()`, `error()`, `verbose_info()`, `progress_raw()`, `progress_clear_line()`
   - 为将来更细粒度的输出控制做准备

## 许可证 / License

MIT License

## 相关工具 / Related Tools

- `check_sync.py` - 文件夹一致性校验工具（仅对比，不拷贝）
# Folder Sync Pro

**专业 DIT 拷卡校验工具 | Professional Media Offload & Verification Tool**

拍摄结束后拷贝存储卡并确认文件完整性的专业工具，专为摄影师和视频制作团队设计。

---

## ✨ 核心特性

### 🚀 性能
- **流式哈希** - 边拷贝边计算哈希，无需二次读取源文件
- **xxHash 支持** - 比 MD5 快 10 倍
- **断点续传** - 大文件中断后可恢复

### ✅ 安全
- **双重校验** - 可选拷贝后二次验证目标文件
- **容量预检** - 拷贝前检查目标磁盘空间，防止 90% 时磁盘满
- **写保护检测** - 检测源盘是否只读，防止 macOS 写入 `.DS_Store`

### 🎨 体验
- **ANSI 彩色输出** - 昏暗片场环境下一眼辨识状态
- **实时进度条** - 双行显示（总进度 + 当前文件）
- **审计日志** - 完整的操作记录，用于交付"铁证"

### 📋 专业 DIT 功能
- **MHL 报告** - 生成 ASC MHL v1.1 标准校验报告（Silverstack、DaVinci Resolve 兼容）
- **校验码文件** - 生成 .xxhash/.md5 伴随文件
- **多源拷贝** - 多张存储卡同时拷贝到多个目标

---

## 📦 安装

```bash
# 无需额外依赖，直接运行
python3 check_sync_pro.py --help

# 可选：安装 xxhash（推荐，提升速度）
pip install xxhash

# 可选：安装 xattr（用于扩展属性保留，macOS）
pip install xattr
```

---

## 🚀 快速开始

### 基本使用

```bash
# 从存储卡拷贝到目标文件夹
python3 check_sync_pro.py /Volumes/SD_CARD/DCIM ~/Photos/2024-01-01

# 启用实时进度条
python3 check_sync_pro.py /Volumes/SD_CARD/DCIM ~/Photos/2024-01-01 --progress

# 启用双重校验（更安全）
python3 check_sync_pro.py /Volumes/SD_CARD/DCIM ~/Photos/2024-01-01 --double-verify
```

### 专业模式

```bash
# 完整专业模式：双重校验 + MHL 报告 + 校验码文件
python3 check_sync_pro.py /Volumes/SD_CARD/DCIM ~/Photos/2024-01-01 \
  --double-verify \
  --mhl \
  --sidecar \
  --progress \
  --verbose
```

### 多源拷贝

```bash
# 从两张卡拷贝到两个备份盘
python3 check_sync_pro.py \
  --sources /Volumes/SD_CARD1 /Volumes/SD_CARD2 \
  --targets /Volumes/Backup1 /Volumes/Backup2 \
  --mhl
```

---

## 📋 命令行参数

### 基本参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `source` | 源文件夹路径 | 必需 |
| `target` | 目标文件夹路径 | 必需 |

### 校验参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--double-verify` | 拷贝后二次校验目标文件 | 否 |
| `--verify` | 仅校验模式，不拷贝 | 否 |
| `--retries N` | IO 错误重试次数 | 3 |

### 输出参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--progress` | 显示实时进度条 | 否 |
| `--verbose` `-v` | 显示详细进度 | 否 |
| `--report FILE` | 生成 JSON 报告 | 无 |
| `--mhl` | 生成 ASC MHL v1.1 报告 | 否 |
| `--sidecar` | 生成校验码伴随文件 | 否 |

### 哈希参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--hash ALG` | 哈希算法（xxhash/md5/sha256） | xxhash |

### 断点续传

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--resume FILE` | 从进度文件恢复 | 无 |
| `--checkpoint N` | 每 N 秒保存进度 | 10 |

---

## 🎯 使用场景

### 日常拍摄

```bash
# 快速拷贝，启用进度显示
python3 check_sync_pro.py /Volumes/SD_CARD/DCIM ~/Photos/2024-01-01 --progress
```

### 重要项目

```bash
# 最高安全级别：双重校验 + MHL
python3 check_sync_pro.py /Volumes/SD_CARD/DCIM ~/Photos/wedding_2024 \
  --double-verify \
  --mhl \
  --sidecar \
  --report report.json \
  --progress
```

### 中断恢复

```bash
# 大文件拷贝中断后恢复
python3 check_sync_pro.py --resume /path/to/target/.sync-progress.json
```

---

## 🔧 技术细节

### 流式哈希

```
源文件 → [读取 chunk] → 计算哈希 → 写入目标
                            ↓
                      累积哈希值
```

只需读取源文件一次，边拷贝边计算哈希。

### 安全机制

1. **容量预检** - 拷贝前检查目标磁盘空间（+5% buffer）
2. **写保护检测** - 检测源盘是否只读，防止数据污染
3. **断点校验** - 恢复拷贝时验证已存在部分的完整性
4. **审计日志** - 所有操作记录到 `.sync_audit_*.log`

### 性能数据

| 模式 | 算法 | 100GB 耗时 |
|------|------|-----------|
| 基本 | xxHash | ~8 分钟 |
| 基本 | MD5 | ~35 分钟 |
| 双重校验 | xxHash | ~11 分钟 |

---

## 📄 输出示例

```
🔍 扫描: /Volumes/SD_CARD/DCIM
📦 开始拷贝: 256 个文件
🔐 哈希算法: XXHASH
✓ 元数据保留: 已启用
⚠️ 源盘可写入，建议在拷贝前拨下写保护锁
✅ 磁盘检查通过 (需要 45.2 GB，可用 500.0 GB)

总进度: ████████████████████ 100.0% | 256/256 | 45.2 GB/45.2 GB
当前: ████████████████████ 100.0% | IMG_0256.CR3 | 35.0 MB/35.0 MB

==================================================
📊 拷贝完成
==================================================
✅ 成功拷贝: 256 个文件
📦 总数据量: 45.2 GB
⏱️ 总耗时: 382.5 秒
🚀 平均速度: 121.3 MB/s
```

---

## 🆕 更新日志

### v1.1.0 (2026-04-06)

#### 新增功能
- ✨ **ANSI 彩色输出** - 绿色成功、黄色警告、红色错误
- ✨ **容量预检** - 拷贝前检查磁盘空间，防止 90% 磁盘满
- ✨ **写保护检测** - 检测源盘只读状态，防止数据污染
- ✨ **审计日志** - 完整操作记录，用于交付追溯
- ✨ **大小写不敏感哈希扩展名** - 支持 .MD5, .XXHASH

#### 修复
- 🐛 修复进度条重复显示问题
- 🐛 修复 ANSI 转义码在某些终端不生效
- 🐛 修复审计日志与正常输出重复
- 🐛 修复进度换行问题

---

## 📜 许可证

MIT License


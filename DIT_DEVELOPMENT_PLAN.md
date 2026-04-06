# folder-sync-pro DIT 专业功能开发计划

## 概述
为 folder-sync-pro 添加专业 DIT（Digital Imaging Technician）功能，适合影视片场使用。

---

## P0 - 关键 Bug 修复

### P0-1: 全大写哈希扩展名兼容
**文件**: `check_sync_pro.py`
**修改**: `scan_folder()` 中的哈希文件过滤改为大小写不敏感

**当前代码**:
```python
if filename.endswith('.md5') or filename.endswith('.xxhash'):
    continue
```

**修改为**:
```python
HASH_EXTENSIONS = {'.md5', '.xxhash', '.sha1', '.sha256', '.sha512'}
if any(filename.lower().endswith(ext) for ext in HASH_EXTENSIONS):
    continue
```

**验证**: 53 个单元测试全部通过

---

## P1 - 核心 UX 改进

### P1-1: ANSI 色彩系统
**文件**: `check_sync_pro.py`

**新增常量**:
```python
class ANSIColors:
    RESET = "\033[0m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    WHITE_DIM = "\033[2m"

STATUS_OK = f"{ANSIColors.GREEN}✅{ANSIColors.RESET}"
STATUS_WARN = f"{ANSIColors.YELLOW}⚠️{ANSIColors.RESET}"
STATUS_ERROR = f"{ANSIColors.RED}❌{ANSIColors.RESET}"
STATUS_INFO = f"{ANSIColors.CYAN}ℹ️{ANSIColors.RESET}"
```

**修改进度条**:
- `_make_bar()` 方法：█ 用绿色，░ 用暗白
- `print_message()` 方法：成功/警告/错误消息带颜色

### P1-2: 写保护/源盘只读检测
**新增函数** `check_source_readonly(source: Path)`:
- 尝试创建测试文件检测写保护
- 返回 (is_readonly, message)
- 在 `run_copy()` 开始时调用

### P1-3: 审计日志 AuditLogger
**新增类** `AuditLogger`:
- 同时输出到 stdout 和 .log 文件
- 记录：开始/完成/跳过/错误，附带时间戳
- 在 `OutputManager` 中集成

---

## P2 - 专业 DIT 功能

### P2-1: 容量预检（Pre-flight Space Check）
**新增函数** `check_disk_space(source_files, target)`:
- 计算源文件总大小
- 用 `shutil.disk_usage(target)` 检查目标磁盘剩余
- 空间不足时红色拦截，提示缺口
- 在 `scan_and_compare()` 之后、`sync_single_pair()` 之前调用

### P2-2: 日志落盘增强
- 生成与 MHL 同目录的 `.log` 文件
- 包含完整时间戳和文件级操作记录

---

## P3 - 高级功能（可选）

### P3-1: 一读多写（Read-Once, Write-Many）
- 架构复杂，需要较大改动
- 建议后续迭代

---

## 执行顺序

| 阶段 | 功能 | 优先级 |
|------|------|--------|
| P0-1 | 全大写哈希扩展名兼容 | P0 |
| P1-1 | ANSI 色彩系统 | P1 |
| P1-2 | 写保护检测 | P1 |
| P1-3 | 审计日志 | P1 |
| P2-1 | 容量预检 | P2 |

---

## 提交规范
- 每个 P 阶段独立 git commit
- Commit message 格式: `feat/fix: <功能描述>`
- 每次 commit 后运行 `python3 -m pytest tests/test_check_sync_pro.py -v` 确认 53 测试通过
- 完成后更新本文件进度

# 开发计划：进度显示优化

## 问题分析

### 当前状态
- **单文件进度**：✅ 已有，显示当前文件的拷贝进度、速度、ETA
- **总进度**：❌ 已移除，用户希望恢复并持久显示
- **显示问题**：
  - 单文件进度和总进度混在一起，难以区分
  - 进度信息刷新太快或太慢
  - 终端宽度适应不够灵活

### 用户需求
1. **持久显示总进度**：在单文件进度上方或下方固定位置显示
2. **优化命令行显示**：更清晰、更美观的进度呈现

---

## 开发方案

### 方案设计：双行进度显示

```
总进度: [████████████░░░░░░░░] 60.5% | 12/20 文件 | 18.5 GB / 30.2 GB | 平均速度: 245 MB/s | ETA: 02:15
当前:   [██████████░░░░░░░░░░░] 48.3% | file_012.ARW | 2.3 GB / 4.8 GB | 312 MB/s | ETA: 00:08
```

### 第一行：总进度（持久显示）
- `[进度条]` - 整体完成百分比
- `12/20 文件` - 已完成/总文件数
- `18.5 GB / 30.2 GB` - 已传输/总数据量
- `平均速度` - 全局平均速度
- `ETA` - 预计剩余时间

### 第二行：当前文件进度（动态更新）
- `[进度条]` - 当前文件完成百分比
- `文件名` - 当前处理的文件
- `已传输/总大小` - 当前文件的数据
- `实时速度` - 当前文件传输速度
- `ETA` - 当前文件预计剩余时间

---

## 实现步骤

### Step 1: 重构 ProgressManager 类
**目标**：支持双行显示和总进度追踪

```python
class ProgressManager:
    """双行进度显示管理器"""
    
    def __init__(self, total_files: int, total_bytes: int, enabled: bool = True):
        self.total_files = total_files
        self.total_bytes = total_bytes
        self.completed_files = 0
        self.completed_bytes = 0
        self.current_file = ""
        self.current_file_size = 0
        self.current_file_copied = 0
        self.start_time = time.time()
        self.enabled = enabled
        
    def update_file_progress(self, bytes_copied: int):
        """更新当前文件进度"""
        pass
        
    def complete_file(self, file_size: int):
        """标记当前文件完成"""
        self.completed_files += 1
        self.completed_bytes += file_size
        
    def render(self) -> str:
        """渲染双行进度显示"""
        pass
```

### Step 2: 添加全局统计追踪
**目标**：在整个拷贝过程中追踪全局数据

```python
class GlobalStats:
    """全局统计信息"""
    
    def __init__(self):
        self.total_files = 0
        self.total_bytes = 0
        self.completed_files = 0
        self.completed_bytes = 0
        self.start_time = time.time()
        self.file_start_time = 0
        self.file_bytes_at_start = 0
        
    def get_average_speed(self) -> float:
        """计算全局平均速度"""
        elapsed = time.time() - self.start_time
        return self.completed_bytes / elapsed if elapsed > 0 else 0
        
    def get_eta(self) -> float:
        """计算全局 ETA"""
        remaining_bytes = self.total_bytes - self.completed_bytes
        speed = self.get_average_speed()
        return remaining_bytes / speed if speed > 0 else 0
```

### Step 3: 修改主循环逻辑
**目标**：集成双行进度显示

```python
# 初始化全局统计
global_stats = GlobalStats()
global_stats.total_files = files_to_copy_count
global_stats.total_bytes = sum(source_sizes)

# 初始化进度管理器
progress_mgr = ProgressManager(
    total_files=files_to_copy_count,
    total_bytes=global_stats.total_bytes,
    enabled=show_progress
)

for idx, (rel_path, source_path) in enumerate(files_to_copy, 1):
    progress_mgr.start_file(rel_path, source_size)
    
    # 拷贝文件（带进度回调）
    source_hash, copy_time, bytes_copied, error = _copy_and_hash_file(
        source_path, target_path, algorithm,
        progress_callback=progress_mgr.update_file_progress,
        ...
    )
    
    progress_mgr.complete_file(source_size)
```

### Step 4: 优化终端显示
**目标**：更美观、更稳定的输出

- **ANSI 光标控制**：
  - `\033[A` - 光标上移一行
  - `\033[K` - 清除当前行
  - `\033[s` - 保存光标位置
  - `\033[u` - 恢复光标位置

- **刷新策略**：
  - 总进度：每 1 秒更新一次
  - 当前文件进度：每 0.25 秒更新一次（保持现有逻辑）
  - 文件完成时：立即更新总进度

- **终端宽度适应**：
  - 自动检测终端宽度
  - 过窄时自动隐藏部分信息（如隐藏 ETA）
  - 最小支持 80 字符宽度

### Step 5: 添加彩色输出（可选）
**目标**：更醒目的视觉反馈

```python
# 使用 ANSI 颜色码
GREEN = '\033[92m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

# 示例：进度条着色
bar_colored = f"{GREEN}{'█' * filled}{RESET}{'░' * (bar_length - filled)}"
```

---

## 文件修改清单

| 文件 | 修改内容 |
|------|---------|
| `check_sync_pro.py` | 1. 重构 `ProgressManager` 类<br>2. 添加 `GlobalStats` 类<br>3. 修改 `copy_folder` 函数主循环<br>4. 添加 ANSI 光标控制函数<br>5. 优化终端宽度适应逻辑 |

---

## 测试计划

### 测试用例

1. **基本功能测试**
   - 少量小文件（< 10 个）拷贝
   - 单个大文件拷贝
   - 验证进度条正确显示

2. **总进度测试**
   - 多文件拷贝时总进度正确更新
   - 跳过文件时总进度计算正确
   - 恢复模式下总进度正确计算

3. **终端兼容性测试**
   - 不同终端宽度（80, 120, 200 字符）
   - 窄终端自动隐藏部分信息
   - 彩色输出在支持/不支持的终端上正确显示

4. **性能测试**
   - 进度更新不影响拷贝速度
   - 大量小文件时的内存占用

---

## 预期效果

### 正常宽度终端（≥100 字符）
```
总进度: [████████████░░░░░░░░] 60.5% | 12/20 文件 | 18.5 GB / 30.2 GB | 245 MB/s | ETA: 02:15
当前:   [██████████░░░░░░░░░░░] 48.3% | file_012.ARW | 2.3 GB / 4.8 GB | 312 MB/s | ETA: 00:08
```

### 窄终端（80 字符）
```
总进度: [████████░░░░] 60.5% | 12/20 | 18.5/30.2 GB | 245 MB/s
当前:   [██████░░░░░░] 48.3% | file_012.ARW | 312 MB/s
```

---

## 优先级

| 优先级 | 任务 | 预计时间 |
|--------|------|---------|
| P0 | 重构 ProgressManager 支持双行显示 | 2h |
| P0 | 添加 GlobalStats 追踪全局统计 | 1h |
| P1 | 修改主循环集成新进度系统 | 1h |
| P1 | ANSI 光标控制和刷新策略 | 1h |
| P2 | 终端宽度自适应 | 0.5h |
| P2 | 彩色输出（可选） | 0.5h |
| P1 | 测试和调试 | 1h |

**总计预计时间**：约 7 小时

---

## 实施顺序

1. ✅ 分析当前代码结构（已完成）
2. 📝 编写开发计划（当前）
3. ⏳ 重构 ProgressManager 类
4. ⏳ 添加 GlobalStats 类
5. ⏳ 修改 copy_folder 主循环
6. ⏳ 添加 ANSI 光标控制
7. ⏳ 测试和调试
8. ⏳ 推送到子模块和父仓库

---

**创建时间**: 2026-04-05 16:57 EDT  
**状态**: 计划阶段，等待用户确认后开始实施

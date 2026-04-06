# folder-sync-pro DIT 专业功能开发计划

## 概述
为 folder-sync-pro 添加专业 DIT（Digital Imaging Technician）功能，适合影视片场使用。

---

## ✅ 已完成功能

### P0-1: 全大写哈希扩展名兼容 ✅
**Commit**: `ffc01d2`
- `scan_folder()` 中的哈希文件过滤改为大小写不敏感
- 支持 `.MD5`、`.XXHASH` 等全大写形式
- 扩展列表：`.md5`, `.xxhash`, `.sha1`, `.sha256`, `.sha512`

### P1-1: ANSI 色彩系统 ✅
**Commit**: `bdc74b6`
- 新增 `ANSIColors` 类和 STATUS_ 常量
- 进度条 █ 绿色 / ░ 暗白
- 状态符号带颜色：✅ 绿色、⚠️ 黄色、❌ 红色

### P1-2: 写保护/源盘只读检测 ✅
**Commit**: 已推送
- 新增 `check_source_readonly()` 函数
- 在 `sync_single_pair()` 开始时检测并提示
- 防止 macOS 写入 `.DS_Store` 污染源数据

### P1-3: 审计日志 AuditLogger ✅
**Commit**: 已推送
- 新增 `AuditLogger` 类，同时输出到 stderr 和 `.log` 文件
- 文件级记录：开始、完成、跳过、错误
- 汇总信息：耗时、速度、文件统计

### P2-1: 容量预检（Pre-flight Space Check） ✅
**Commit**: `7acb9bb`
- 新增 `check_disk_space()` 函数
- 空间不足时红色拦截，显示缺口大小
- +5% buffer 和最小剩余空间检查（默认 10GB）

---

## 待开发功能

### P3-1: 一读多写（Read-Once, Write-Many）
- 架构复杂，需要较大改动
- 建议后续迭代

---

## 进度汇总

| 阶段 | 功能 | 状态 | Commit |
|------|------|------|--------|
| P0-1 | 全大写哈希扩展名兼容 | ✅ 完成 | `ffc01d2` |
| P1-1 | ANSI 色彩系统 | ✅ 完成 | `bdc74b6` |
| P1-2 | 写保护检测 | ✅ 完成 | 已推送 |
| P1-3 | 审计日志 | ✅ 完成 | 已推送 |
| P2-1 | 容量预检 | ✅ 完成 | `7acb9bb` |
| P3-1 | 一读多写 | 🔲 待开发 | - |

**完成时间**: 2026-04-06
**测试状态**: 53/53 通过

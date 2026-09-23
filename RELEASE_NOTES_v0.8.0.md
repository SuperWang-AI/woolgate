# WoolGate v0.8.0 Release Notes

> **发布日期**: 2026-09-23
> **版本**: v0.8.0
> **代号**: 前端架构重构与插件系统完善

---

## 🎉 主要更新

### 1. 管理后台分层架构重构

**admin.py 从 2466 行精简到 182 行**，采用清晰的三层架构：

```
app/admin/
├── admin.py              # 主入口（~180 行）
├── utils.py              # SPA 状态管理
├── services.py           # 数据服务层（~460 行）
├── pages/                # 页面层
│   ├── dashboard.py      # 首页仪表盘
│   ├── wizard.py         # 免费向导
│   ├── accounts.py       # 账号管理
│   ├── config.py         # 系统配置
│   ├── pipeline.py       # 管线策略
│   ├── logs.py           # 请求日志
│   └── plugins.py        # 插件管理
└── components/           # 公共组件
    ├── navigation.py     # 导航栏
    └── stat_card.py      # 统计卡片
```

**架构优势：**
- ✅ 易于维护和扩展
- ✅ 代码结构清晰，职责分离
- ✅ UI 像素级保持不变
- ✅ 组件化设计，可复用

---

### 2. 插件下拉菜单导航

**新增插件下拉菜单**，悬停展开，支持多插件扩展：

```
导航栏：首页 | 免费向导 | 账号管理 | 系统配置 | 管线策略 | 请求日志 | 🔌 插件 ▼
                                                                            ┌─────────────────────┐
                                                                            │ 💰 余额监控          │
                                                                            │  余额监控与额度预警   │
                                                                            ├─────────────────────┤
                                                                            │ 🧪 Hello World       │
                                                                            │  插件开发示例         │
                                                                            └─────────────────────┘
```

**特性：**
- ✅ 鼠标悬停展开，交互流畅
- ✅ 插件自动注册到下拉菜单
- ✅ 随着插件数量增加，导航栏保持简洁
- ✅ 插件详情页面独立路由（?active=插件名）

---

### 3. 插件系统完善

**内置插件：**
- ✅ **余额监控插件**（balance_monitor）：监控各平台账号余额与额度，低余额预警
- ✅ **Hello World 示例插件**（hello_world）：插件开发示例，演示 HOOK/SPI/UI 扩展点用法

**插件开发指南：**
- ✅ 更新到 v0.8.0
- ✅ 完整的插件开发文档
- ✅ Hello World 示例代码
- ✅ 9 个生命周期钩子
- ✅ 6 个 SPI 扩展点
- ✅ UI 注入插槽

---

### 4. Bug 修复

**修复插件下拉菜单链接跳转问题：**
- 修复 `_plugin_active` 变量同步问题（admin.py 和 utils.py 之间）
- 修复 `init_spa_state` 函数覆盖已设置的 `plugin_active` 值
- 添加 `set_plugin_refresh` 调用，设置插件页面刷新回调

---

## 📊 代码统计

| 模块 | 代码行数 | 说明 |
|------|----------|------|
| admin.py | ~182 行 | 主入口（从 2466 行精简） |
| services.py | ~460 行 | 数据服务层 |
| pages/*.py | ~1700 行 | 页面层 |
| components/navigation.py | ~150 行 | 导航栏组件 |
| components/stat_card.py | ~14 行 | 统计卡片组件 |

---

## 🚀 升级指南

### 从 v0.7.0 升级到 v0.8.0

1. **拉取最新代码**
   ```bash
   git pull origin main
   ```

2. **重新构建 Docker 容器**
   ```bash
   docker compose up -d --build
   ```

3. **访问管理后台**
   ```
   http://localhost:8765/admin
   ```

4. **测试插件功能**
   - 悬停"插件"按钮，查看下拉菜单
   - 点击"余额监控"，查看插件详情
   - 点击"Hello World"，查看示例插件

---

## 📝 已知问题

- 无

---

## 🙏 致谢

感谢所有为 WoolGate 贡献代码和反馈的用户！

---

**完整更新日志**：[GitHub Commits](https://github.com/SuperWang-AI/woolgate/commits/main)

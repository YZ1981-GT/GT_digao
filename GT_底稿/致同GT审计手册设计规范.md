# 致同GT审计手册设计规范文档
*Grant Thornton Audit Manual Design Standards*

---

## 📋 目录
1. [设计原则](#设计原则)
2. [颜色系统](#颜色系统)
3. [字体规范](#字体规范)
4. [布局系统](#布局系统)
5. [HTML结构规范](#html结构规范)
6. [CSS类名规范](#css类名规范)
7. [组件库](#组件库)
8. [可访问性规范](#可访问性规范)
9. [打印样式规范](#打印样式规范)
10. [暗色模式预留方案](#暗色模式预留方案)
11. [实施指导](#实施指导)

---

## 🎯 设计原则

### 核心理念
- **专业性 (Professional)**: 体现致同GT的专业形象和权威性
- **一致性 (Consistent)**: 所有章节保持完全统一的视觉和结构标准
- **易用性 (Usable)**: 审计师能够快速定位和使用所需信息
- **品牌化 (Branded)**: 严格遵循致同GT的品牌视觉识别系统

### 设计目标
1. **视觉统一**: 所有章节使用相同的结构、样式和颜色
2. **信息层次**: 清晰的信息架构和视觉层次
3. **响应式设计**: 支持桌面端、平板端和移动端
4. **可访问性**: 符合WCAG 2.1 AA级可访问性标准

---

## 🎨 颜色系统

### 主色调 - 致同GT官方紫色系
基于致同GT官方品牌指导原则（2024版）：

```css
/* 主色调 - 致同GT官方核心紫色 */
--gt-primary: #4b2d77;           /* GT核心紫色 HEX #4b2d77 RGB(75,45,119) */
--gt-primary-light: #A06DFF;     /* GT亮紫色 RGB(160,109,255) */
--gt-primary-dark: #2B1D4D;      /* GT深紫色 RGB(43,20,77) */
--gt-primary-gradient: linear-gradient(135deg, #4b2d77 0%, #A06DFF 100%);

/* 致同GT官方辅助色系 */
--gt-water-blue: #0094B3;        /* 水鸭蓝 RGB(0,148,179) */
--gt-coral-orange: #FF5149;      /* 珊瑚橙 RGB(255,81,73) */
--gt-wheat-yellow: #FFC23D;      /* 麦田黄 RGB(255,194,61) */
--gt-medium-gray: #808080;       /* 中灰色 RGB(128,128,128) */
--gt-light-gray: #C0C0C0;       /* 浅灰色 RGB(192,192,192) */
```

### 功能色系
```css
/* 状态颜色 */
--gt-success: #28A745;           /* 成功/完成 */
--gt-warning: #FFC107;           /* 警告/注意 */
--gt-danger: #DC3545;            /* 错误/高风险 */
--gt-info: #17A2B8;             /* 信息/提示 */

/* 中性色系（注意：与辅助色系中的GT品牌灰色区分） */
--gt-white: #FFFFFF;
--gt-neutral-light: #F8F9FA;     /* 浅中性灰 - 用于背景 */
--gt-neutral-medium: #E9ECEF;    /* 中中性灰 - 用于分隔 */
--gt-gray: #6C757D;
--gt-dark-gray: #343A40;
--gt-border: #DEE2E6;
```

### 文字颜色规范
基于致同GT官方品牌色彩系统：

```css
/* 文字颜色 - 严格对比度要求 */
--gt-text-primary: #2C3E50;      /* 主文字 - 深灰蓝 */
--gt-text-secondary: #666666;    /* 次要文字 - 深灰色（对比度5.7:1，满足AA） */
--gt-text-light: #808080;       /* 淡文字 - GT中灰色（对比度3.9:1，仅限大文字或非白色背景使用） */
--gt-text-white: #FFFFFF;       /* 白色文字 */
--gt-text-purple: #4b2d77;      /* GT核心紫色文字 */
--gt-text-on-purple: #FFFFFF;   /* 紫色背景上必须用白色文字 */
```

### 颜色使用规则
1. **紫色背景必须配白色文字** - 确保足够的对比度（GT核心紫色 #4b2d77 + 白色文字）
2. **主要操作使用GT核心紫色** - 按钮、链接、重要元素使用 #4b2d77
3. **渐变效果使用官方色谱** - 从核心紫色到亮紫色的渐变
4. **辅助色点缀使用** - 水鸭蓝、珊瑚橙、麦田黄用于状态和强调
5. **中性色用于背景和边框** - GT官方灰色系统

### 致同GT辅助图形系统
基于品牌指南中的辅助图形元素：

```css
/* GT辅助图形样式 */
.gt-gradient-circle {
    background: radial-gradient(circle, var(--gt-primary-light) 0%, var(--gt-primary) 100%);
    border-radius: 50%;
}

.gt-wave-pattern {
    background: linear-gradient(45deg, transparent 30%, var(--gt-primary-light) 30%, var(--gt-primary-light) 70%, transparent 70%);
}

.gt-geometric-pattern {
    background: conic-gradient(from 0deg, var(--gt-primary), var(--gt-primary-light), var(--gt-water-blue), var(--gt-primary));
}
```

---

## 📝 字体规范

### 字体族
基于致同GT官方品牌字体系统：

```css
/* 致同GT官方字体族 */
/* 中文字体 - 方正悦黑系列 */
font-family: 'FZYueHei', 'Microsoft YaHei', 'PingFang SC', 'Hiragino Sans GB', sans-serif;

/* 英文字体 - GT Walsheim系列（如可用） */
font-family: 'GT Walsheim', 'Helvetica Neue', Arial, sans-serif;

/* 混合字体族（推荐） */
font-family: 'GT Walsheim', 'FZYueHei', 'Microsoft YaHei', 'PingFang SC', 'Hiragino Sans GB', 'Helvetica Neue', Arial, sans-serif;
```

### 字体大小系统
```css
/* 字体大小 - 模块化缩放系统 */
--gt-font-xs: 12px;      /* 0.75rem - 辅助信息 */
--gt-font-sm: 14px;      /* 0.875rem - 正文小字 */
--gt-font-base: 16px;    /* 1rem - 基础正文 */
--gt-font-lg: 18px;      /* 1.125rem - 大正文 */
--gt-font-xl: 20px;      /* 1.25rem - 小标题 */
--gt-font-2xl: 24px;     /* 1.5rem - 中标题 */
--gt-font-3xl: 30px;     /* 1.875rem - 大标题 */
--gt-font-4xl: 36px;     /* 2.25rem - 主标题 */
```

### 标题层级规范
```css
h1 {
    font-size: var(--gt-font-3xl);    /* 30px */
    font-weight: 700;
    line-height: 1.2;
    color: var(--gt-text-primary);
    margin-bottom: var(--gt-space-lg); /* 24px */
}

h2 {
    font-size: var(--gt-font-2xl);    /* 24px */
    font-weight: 600;
    line-height: 1.3;
    color: var(--gt-text-primary);
    margin-bottom: var(--gt-space-md); /* 16px */
}

h3 {
    font-size: var(--gt-font-xl);     /* 20px */
    font-weight: 600;
    line-height: 1.4;
    color: var(--gt-text-primary);
    margin-bottom: var(--gt-space-md); /* 16px */
}

h4 {
    font-size: var(--gt-font-lg);     /* 18px */
    font-weight: 600;
    line-height: 1.4;
    color: var(--gt-text-primary);
    margin-bottom: var(--gt-space-sm); /* 8px */
}
```

### 正文规范
```css
p, li, td {
    font-size: var(--gt-font-base);   /* 16px */
    font-weight: 400;
    line-height: 1.6;
    color: var(--gt-text-primary);
    margin-bottom: var(--gt-space-sm); /* 8px */
}
```

---

## 📐 布局系统

### 间距系统 - 基于4px基础网格
```css
/* 间距变量 - 4px基础网格，8px为主要节奏单位 */
--gt-space-xs: 4px;      /* 0.25rem - 最小间距 */
--gt-space-sm: 8px;      /* 0.5rem */
--gt-space-md: 16px;     /* 1rem */
--gt-space-lg: 24px;     /* 1.5rem */
--gt-space-xl: 32px;     /* 2rem */
--gt-space-2xl: 48px;    /* 3rem */
--gt-space-3xl: 64px;    /* 4rem */
```

### 边框圆角
```css
--gt-radius-sm: 4px;     /* 小圆角 */
--gt-radius-md: 8px;     /* 中圆角 */
--gt-radius-lg: 12px;    /* 大圆角 */
```

### 阴影系统
```css
/* 阴影 - 使用GT核心紫色 #4b2d77 */
--gt-shadow-sm: 0 2px 4px rgba(75, 45, 119, 0.075);
--gt-shadow-md: 0 4px 8px rgba(75, 45, 119, 0.15);
--gt-shadow-lg: 0 8px 24px rgba(75, 45, 119, 0.175);
```

### 响应式断点
```css
/* 响应式断点定义（仅作文档参考值，@media查询中需硬编码） */
/* --gt-breakpoint-sm: 576px;   手机横屏 */
/* --gt-breakpoint-md: 768px;   平板竖屏 */
/* --gt-breakpoint-lg: 1024px;  平板横屏/小桌面 */
/* --gt-breakpoint-xl: 1280px;  标准桌面 */
/* --gt-breakpoint-2xl: 1536px; 大屏桌面 */

@media (max-width: 768px) {
    .gt-grid-2, .gt-grid-3, .gt-grid-4 { grid-template-columns: 1fr; }
    .gt-section-header h1 { font-size: var(--gt-font-2xl); }
}

@media (max-width: 1024px) {
    .gt-grid-3 { grid-template-columns: repeat(2, 1fr); }
    .gt-grid-4 { grid-template-columns: repeat(2, 1fr); }
}
```

---

## 🏗️ HTML结构规范

### 章节基础结构模板
```html
<!-- 标准章节结构 -->
<section id="section-id" class="gt-section" aria-labelledby="section-id-title">
    <!-- 章节头部 -->
    <div class="gt-section-header">
        <h1 id="section-id-title"><i class="fas fa-icon-name" aria-hidden="true"></i> 章节标题</h1>
        <p class="gt-section-subtitle">章节描述信息</p>
    </div>

    <!-- 章节内容 -->
    <div class="gt-section-content">
        <!-- 内容卡片 -->
        <div class="gt-card">
            <div class="gt-card-header">
                <i class="fas fa-icon" aria-hidden="true"></i>
                <h3>卡片标题</h3>
            </div>
            <div class="gt-card-content">
                <!-- 卡片内容 -->
            </div>
        </div>
    </div>

    <!-- 章节导航 -->
    <nav class="gt-section-navigation" aria-label="章节导航">
        <div class="gt-nav-summary">
            <h3>📋 本章要点</h3>
            <ul>
                <li>要点1</li>
                <li>要点2</li>
                <li>要点3</li>
            </ul>
        </div>
        <div class="gt-nav-next">
            <a href="#next-section" class="gt-nav-link">
                下一章节 <i class="fas fa-arrow-right" aria-hidden="true"></i>
            </a>
        </div>
    </nav>
</section>
```

### 层级规范
1. **第1级**: `section` - 章节容器（含 `aria-labelledby`）
2. **第2级**: `div.gt-section-header` / `div.gt-section-content` / `nav.gt-section-navigation` - 章节区域
3. **第3级**: `div.gt-card` - 内容卡片
4. **第4级**: `div.gt-card-header/content` - 卡片区域
5. **第5级**: 具体内容元素

---

## 🎨 CSS类名规范

### 命名规则
- **前缀**: 所有类名使用 `gt-` 前缀（Grant Thornton）
- **结构**: `gt-组件名-修饰符`
- **语言**: 使用英文命名，语义化清晰

### 核心类名系统
```css
/* 布局类 */
.gt-container           /* 主容器 */
.gt-section            /* 章节容器 */
.gt-section-header     /* 章节头部 */
.gt-section-content    /* 章节内容 */
.gt-section-navigation /* 章节导航 */

/* 卡片类 */
.gt-card               /* 基础卡片 */
.gt-card-header        /* 卡片头部 */
.gt-card-content       /* 卡片内容 */
.gt-card-footer        /* 卡片底部 */

/* 网格类 */
.gt-grid               /* 网格容器 */
.gt-grid-2             /* 2列网格 */
.gt-grid-3             /* 3列网格 */
.gt-grid-4             /* 4列网格 */

/* 组件类 */
.gt-button             /* 按钮 */
.gt-table              /* 表格 */
.gt-form               /* 表单（预留，按需实现） */
.gt-nav                /* 导航（预留，按需实现） */
```

### 状态类
```css
.gt-active             /* 激活状态 */
.gt-disabled           /* 禁用状态 */
.gt-loading            /* 加载状态 */
.gt-success            /* 成功状态 */
.gt-warning            /* 警告状态 */
.gt-error              /* 错误状态 */
```

---

## 🧩 组件库

### 1. 标准卡片组件
```html
<div class="gt-card">
    <div class="gt-card-header">
        <i class="fas fa-icon" aria-hidden="true"></i>
        <h3>标题</h3>
    </div>
    <div class="gt-card-content">
        <!-- 内容区域 -->
    </div>
</div>
```

### 2. 流程图组件
```html
<div class="gt-flow-diagram" role="list" aria-label="流程步骤">
    <div class="gt-flow-step" role="listitem">
        <div class="gt-step-number" aria-hidden="true">1</div>
        <h4>步骤标题</h4>
        <p>步骤描述</p>
    </div>
    <i class="fas fa-arrow-right gt-flow-arrow" aria-hidden="true"></i>
    <!-- 更多步骤... -->
</div>
```

### 3. 网格布局组件
```html
<div class="gt-grid gt-grid-3">
    <div class="gt-grid-item">内容1</div>
    <div class="gt-grid-item">内容2</div>
    <div class="gt-grid-item">内容3</div>
</div>
```

### 4. 表格组件
```html
<table class="gt-table" role="table">
    <caption>表格标题描述</caption>
    <thead>
        <tr>
            <th scope="col">列标题1</th>
            <th scope="col">列标题2</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td>数据1</td>
            <td>数据2</td>
        </tr>
    </tbody>
</table>
```

### 5. 组件CSS实现
```css
/* 卡片组件 */
.gt-card {
    background: var(--gt-white);
    border-radius: var(--gt-radius-md);
    box-shadow: var(--gt-shadow-sm);
    border: 1px solid var(--gt-border);
    overflow: hidden;
    transition: box-shadow 0.2s ease;
}
.gt-card:hover {
    box-shadow: var(--gt-shadow-md);
}
.gt-card-header {
    display: flex;
    align-items: center;
    gap: var(--gt-space-sm);
    padding: var(--gt-space-md) var(--gt-space-lg);
    background: var(--gt-primary);
    color: var(--gt-text-on-purple);
}
.gt-card-header h3 {
    margin: 0;
    color: var(--gt-text-on-purple);
}
.gt-card-content {
    padding: var(--gt-space-lg);
}
.gt-card-footer {
    padding: var(--gt-space-md) var(--gt-space-lg);
    border-top: 1px solid var(--gt-border);
    background: var(--gt-neutral-light);
}

/* 网格布局 */
.gt-grid {
    display: grid;
    gap: var(--gt-space-lg);
}
.gt-grid-2 { grid-template-columns: repeat(2, 1fr); }
.gt-grid-3 { grid-template-columns: repeat(3, 1fr); }
.gt-grid-4 { grid-template-columns: repeat(4, 1fr); }

/* 流程图组件 */
.gt-flow-diagram {
    display: flex;
    align-items: center;
    gap: var(--gt-space-md);
    flex-wrap: wrap;
    padding: var(--gt-space-lg) 0;
}
.gt-flow-step {
    flex: 1;
    min-width: 160px;
    text-align: center;
    padding: var(--gt-space-lg);
    background: var(--gt-white);
    border-radius: var(--gt-radius-md);
    box-shadow: var(--gt-shadow-sm);
    border: 1px solid var(--gt-border);
}
.gt-step-number {
    width: 36px;
    height: 36px;
    line-height: 36px;
    border-radius: 50%;
    background: var(--gt-primary);
    color: var(--gt-text-on-purple);
    font-weight: 700;
    margin: 0 auto var(--gt-space-sm);
}
.gt-flow-arrow {
    color: var(--gt-primary);
    font-size: var(--gt-font-xl);
}

/* 表格组件 */
.gt-table {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--gt-font-base);
}
.gt-table caption {
    caption-side: top;
    text-align: left;
    font-weight: 600;
    padding: var(--gt-space-sm) 0;
    color: var(--gt-text-primary);
}
.gt-table thead th {
    background: var(--gt-primary);
    color: var(--gt-text-on-purple);
    padding: var(--gt-space-sm) var(--gt-space-md);
    text-align: left;
    font-weight: 600;
}
.gt-table tbody td {
    padding: var(--gt-space-sm) var(--gt-space-md);
    border-bottom: 1px solid var(--gt-border);
}
.gt-table tbody tr:hover {
    background: var(--gt-neutral-light);
}

/* 按钮组件 */
.gt-button {
    display: inline-flex;
    align-items: center;
    gap: var(--gt-space-xs);
    padding: var(--gt-space-sm) var(--gt-space-lg);
    border: none;
    border-radius: var(--gt-radius-sm);
    font-size: var(--gt-font-base);
    font-weight: 600;
    cursor: pointer;
    transition: background 0.2s ease, box-shadow 0.2s ease;
    background: var(--gt-primary);
    color: var(--gt-text-on-purple);
}
.gt-button:hover {
    background: var(--gt-primary-dark);
    box-shadow: var(--gt-shadow-sm);
}
.gt-button:focus-visible {
    outline: 3px solid var(--gt-primary-light);
    outline-offset: 2px;
}

/* 章节结构 */
.gt-section-header {
    background: var(--gt-primary-gradient);
    color: var(--gt-text-on-purple);
    padding: var(--gt-space-2xl) var(--gt-space-lg);
    border-radius: var(--gt-radius-lg);
    margin-bottom: var(--gt-space-xl);
}
.gt-section-header h1 {
    color: var(--gt-text-on-purple);
    margin-bottom: var(--gt-space-sm);
}
.gt-section-subtitle {
    color: #FFFFFFD9;             /* rgba(255,255,255,0.85) - 紫色渐变背景上对比度≥4.5:1 */
    font-size: var(--gt-font-lg);
}
.gt-section-navigation {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    padding: var(--gt-space-lg);
    margin-top: var(--gt-space-xl);
    background: var(--gt-neutral-light);
    border-radius: var(--gt-radius-md);
}
.gt-nav-link {
    display: inline-flex;
    align-items: center;
    gap: var(--gt-space-xs);
    color: var(--gt-primary);
    text-decoration: none;
    font-weight: 600;
}
.gt-nav-link:hover {
    color: var(--gt-primary-dark);
}
.gt-nav-link:focus-visible {
    outline: 3px solid var(--gt-primary-light);
    outline-offset: 2px;
}

/* 主容器 */
.gt-container {
    max-width: 1280px;
    margin: 0 auto;
    padding: 0 var(--gt-space-lg);
    width: 100%;
}

/* 状态类 */
.gt-active {
    border-color: var(--gt-primary);
    box-shadow: var(--gt-shadow-md);
}
.gt-disabled {
    opacity: 0.5;
    pointer-events: none;
    cursor: not-allowed;
}
.gt-loading {
    position: relative;
    pointer-events: none;
}
.gt-loading::after {
    content: "";
    position: absolute;
    inset: 0;
    background: rgba(255, 255, 255, 0.7);
    display: flex;
    align-items: center;
    justify-content: center;
}
.gt-success {
    border-left: 4px solid var(--gt-success);
}
.gt-warning {
    border-left: 4px solid var(--gt-warning);
}
.gt-error {
    border-left: 4px solid var(--gt-danger);
}
```

---

## ♿ 可访问性规范

### 对比度要求（WCAG 2.1 AA级）
| 场景 | 最低对比度 | 说明 |
|------|-----------|------|
| 正文文字（<18px 或 <14px粗体） | 4.5:1 | 适用于正文、表格、列表等 |
| 大文字（≥18px 或 ≥14px粗体） | 3:1 | 适用于标题、大号文字 |
| 非文本元素（图标、边框等） | 3:1 | 适用于图标、输入框边框、图表 |

### 核心配色对比度验证
| 前景色 | 背景色 | 对比度 | 是否达标 |
|--------|--------|--------|---------|
| #2C3E50 (主文字) | #FFFFFF (白色) | 10.7:1 | ✅ AA |
| #FFFFFF (白色文字) | #4b2d77 (GT紫色) | 8.6:1 | ✅ AA |
| #FFFFFFD9 (章节副标题) | #4b2d77 (GT紫色) | 7.3:1 | ✅ AA |
| #666666 (次要文字) | #FFFFFF (白色) | 5.7:1 | ✅ AA |
| #808080 (淡文字) | #FFFFFF (白色) | 3.9:1 | ⚠️ 仅限大文字或非白色背景 |

> ⚠️ 注意：`--gt-text-light: #808080` 在白色背景上对比度为3.9:1，不满足正文AA标准（4.5:1）。仅可用于≥18px的大文字，或在深色背景上使用。

### 焦点样式规范
```css
/* 所有交互元素必须有可见的焦点样式 */
*:focus-visible {
    outline: 3px solid var(--gt-primary-light);
    outline-offset: 2px;
}

/* 紫色背景上的焦点样式 */
.gt-section-header *:focus-visible,
.gt-card-header *:focus-visible {
    outline-color: var(--gt-wheat-yellow);
}
```

### 语义化HTML要求
- 表格必须包含 `<caption>` 和 `scope` 属性
- 图标按钮必须包含 `aria-label`
- 装饰性图标使用 `aria-hidden="true"`
- 导航区域使用 `<nav>` 标签并添加 `aria-label`
- 章节使用 `aria-labelledby` 关联标题

---

## 🖨️ 打印样式规范

审计底稿经常需要打印输出，以下规范确保打印效果的专业性：

```css
@media print {
    /* 隐藏非打印元素 */
    .gt-section-navigation,
    .gt-nav-link,
    .gt-button,
    .gt-flow-arrow {
        display: none !important;
    }

    /* 页面设置 */
    @page {
        size: A4;
        margin: 20mm 15mm;
    }

    /* 强制黑白配色 */
    body {
        color: #000000 !important;
        background: #FFFFFF !important;
    }

    .gt-card {
        box-shadow: none !important;
        border: 1px solid #333333 !important;
        break-inside: avoid;
    }

    .gt-section-header {
        background: none !important;
        color: #000000 !important;
        border-bottom: 3px solid #4b2d77;
        padding: 12px 0;
    }

    .gt-section-header h1,
    .gt-section-subtitle {
        color: #000000 !important;
    }

    .gt-card-header {
        background: #F0F0F0 !important;
        color: #000000 !important;
    }

    .gt-card-header h3 {
        color: #000000 !important;
    }

    .gt-table thead th {
        background: #F0F0F0 !important;
        color: #000000 !important;
        border: 1px solid #333333;
    }

    .gt-table tbody td {
        border: 1px solid #666666;
    }

    /* 链接显示URL */
    a[href]::after {
        content: " (" attr(href) ")";
        font-size: 0.8em;
        color: #666666;
    }

    /* 避免分页断裂 */
    h1, h2, h3, h4 {
        break-after: avoid;
    }

    .gt-card, .gt-flow-step, table {
        break-inside: avoid;
    }
}
```

---

## 🌙 暗色模式预留方案

为未来暗色模式扩展预留变量映射：

```css
@media (prefers-color-scheme: dark) {
    :root {
        /* 背景色映射 */
        --gt-white: #1A1A2E;
        --gt-neutral-light: #16213E;
        --gt-neutral-medium: #0F3460;
        --gt-border: #333A50;

        /* 文字色映射 */
        --gt-text-primary: #E0E0E0;
        --gt-text-secondary: #A0A0A0;

        /* 主色调保持品牌识别度，适当提亮 */
        --gt-primary: #6B4D97;
        --gt-primary-light: #B08DFF;
        --gt-primary-dark: #3B2D5D;

        /* 阴影调整 */
        --gt-shadow-sm: 0 2px 4px rgba(0, 0, 0, 0.3);
        --gt-shadow-md: 0 4px 8px rgba(0, 0, 0, 0.4);
        --gt-shadow-lg: 0 8px 24px rgba(0, 0, 0, 0.5);
    }
}
```

> 注意：暗色模式为预留方案，启用前需重新验证所有配色组合的WCAG对比度。

---

## 🚀 实施指导

### 实施步骤
1. **停止所有修改** ✅
2. **制定设计规范** ✅ (当前文档)
3. **创建标准CSS样式表**
4. **制作HTML模板**
5. **逐章节重构**
6. **质量检查和验证**

### 重构原则
1. **先规范，后实施** - 严格按照本规范执行
2. **逐章节处理** - 一个章节一个章节完成
3. **保持一致性** - 所有章节使用相同的结构和样式
4. **充分测试** - 每个章节完成后进行视觉和功能测试

### 质量标准
- [ ] 颜色系统100%符合致同GT标准
- [ ] 字体大小和间距完全统一
- [ ] HTML结构完全一致
- [ ] CSS类名规范统一
- [ ] 响应式设计完美适配
- [ ] 可访问性符合WCAG 2.1 AA标准
- [ ] 打印输出格式正确
- [ ] 所有交互元素具备焦点样式

---

## 📋 检查清单

### 每个章节必须包含：
- [ ] 标准的章节头部结构
- [ ] 统一的卡片布局
- [ ] 正确的颜色使用（紫色背景+白字）
- [ ] 规范的字体大小和间距
- [ ] 统一的CSS类名
- [ ] 章节导航区域（使用 `<nav>` 标签）
- [ ] 响应式布局适配
- [ ] 可访问性属性（`aria-labelledby`、`aria-hidden`、`scope`等）
- [ ] 打印样式兼容（避免分页断裂、隐藏交互元素）
- [ ] 所有文字配色对比度达到WCAG AA标准

### 禁止事项：
- ❌ 使用非规范的颜色
- ❌ 紫色背景使用深色文字
- ❌ 不一致的字体大小
- ❌ 混用不同的CSS类名系统
- ❌ 跳过章节导航区域
- ❌ 不规范的HTML结构
- ❌ 装饰性图标缺少 `aria-hidden="true"`
- ❌ 正文使用对比度低于4.5:1的文字颜色
- ❌ 交互元素缺少 `:focus-visible` 焦点样式

---

*本设计规范文档将作为后续重构工作的唯一标准，所有修改必须严格遵循本规范执行。*
---
name: apple-style-design-skill
description: Apple-Class Design Style Guide. Use when designing UI/UX to ensure a modern, minimalist, Apple-like aesthetic with specific color, typography, layout, and animation guidelines.
---

# Apple-Class 设计风格指南

这是一个基于 Apple 设计语言的现代极简主义设计系统提示词，可在任何项目中一键复用。

## 🎨 核心设计理念

### 设计哲学
```
采用 Apple 设计语言的核心理念：
- 极致简约 - 去除一切不必要的元素
- 功能至上 - 每个元素都有明确目的
- 用户友好 - 直觉式操作体验
- 精确美学 - 像素级完美对齐
- 情感共鸣 - 微妙但有意义的交互反馈
```

## 🎭 颜色系统

### 主色调配置
```css
/* 核心基础色彩 - Apple SF 灰度系统 */
--background: 0 0% 100%;        /* 纯白 - 终极画布 */
--foreground: 0 0% 9%;          /* 深炭灰 - 最佳可读性 */
--muted: 0 0% 96%;              /* 超浅灰 - 微妙背景 */
--muted-foreground: 0 0% 45%;   /* 中灰 - 次要文本 */

/* 语义化色彩 */
--accent: 211 100% 50%;         /* Apple 蓝 - 主要交互色 */
--accent-foreground: 0 0% 100%; /* 蓝色上的白字 */
--border: 0 0% 91%;             /* 细线边框 - 几乎不可见 */
--ring: 211 100% 50%;           /* 焦点状态 */

/* 深色模式 */
.dark {
  --background: 0 0% 8%;          /* Apple 深灰，非纯黑 */
  --foreground: 0 0% 95%;         /* 柔和白色 */
  --muted: 0 0% 12%;              /* 微妙深色背景 */
  --muted-foreground: 0 0% 70%;   /* 舒适阅读灰 */
  --accent: 211 100% 65%;         /* 深色模式 Apple 蓝 */
  --border: 0 0% 20%;             /* 微妙深色边框 */
}
```

### 配色原则
- **高对比度**：确保文字可读性符合 WCAG AA 标准
- **单一强调色**：使用 Apple 蓝作为唯一交互色
- **灰度为主**：95% 界面使用灰度系统
- **语义化色彩**：绿色成功、红色错误、橙色警告

## 📝 字体系统

### Apple 风格字体层级
```css
/* 响应式字体大小 - 基于 clamp 的完美缩放 */
.text-apple-display {
  font-size: clamp(2.25rem, 5vw, 5rem);    /* 36px - 80px */
  font-weight: 600;
  line-height: 1.1;
  letter-spacing: -0.025em;                 /* Apple 紧凑字距 */
}

.text-apple-headline {
  font-size: clamp(1.75rem, 4vw, 3rem);    /* 28px - 48px */
  font-weight: 600;
  line-height: 1.2;
  letter-spacing: -0.02em;
}

.text-apple-title {
  font-size: clamp(1.125rem, 2.5vw, 1.5rem); /* 18px - 24px */
  font-weight: 600;
  line-height: 1.3;
  letter-spacing: -0.01em;
}

.text-apple-body {
  font-size: clamp(0.875rem, 2vw, 1.125rem); /* 14px - 18px */
  font-weight: 400;
  line-height: 1.5;                         /* 舒适阅读行高 */
}

.text-apple-caption {
  font-size: clamp(0.75rem, 1.5vw, 0.875rem); /* 12px - 14px */
  font-weight: 400;
  line-height: 1.4;
  color: hsl(var(--muted-foreground));
}
```

### 字体使用原则
- **系统字体**：优先使用系统默认字体栈
- **响应式缩放**：所有字号使用 clamp() 函数自适应
- **字重层次**：仅使用 400（常规）和 600（半粗）两种字重
- **紧凑字距**：大标题使用负字距，提升现代感

## 🏗️ 布局系统

### 8px 网格系统
```css
/* 空间单位 - 基于 8px 的完美网格 */
--space-xs: 4px;    /* 0.5 单位 */
--space-sm: 8px;    /* 1 单位 */
--space-md: 16px;   /* 2 单位 */
--space-lg: 24px;   /* 3 单位 */
--space-xl: 32px;   /* 4 单位 */
--space-2xl: 48px;  /* 6 单位 */
--space-3xl: 64px;  /* 8 单位 */
--space-4xl: 96px;  /* 12 单位 */
```

### 容器与网格
```css
/* 响应式容器 */
.container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 24px;
}

/* 移动端优化 */
@media (max-width: 768px) {
  .container { padding: 0 16px; }
}

/* 网格系统 */
.grid-apple {
  display: grid;
  gap: var(--space-lg);
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
}
```

## 🪄 玻璃态设计

### 核心玻璃效果
```css
/* Apple 风格玻璃态 - 真实物理效果 */
.glass {
  background: rgba(255, 255, 255, 0.8);
  border: 1px solid hsl(var(--border));
  box-shadow: 0 1px 3px 0 rgb(0 0 0 / 0.05);
  backdrop-filter: blur(20px) saturate(120%);
  -webkit-backdrop-filter: blur(20px) saturate(120%);
  transition: all 0.3s cubic-bezier(0.4, 0.0, 0.2, 1);
}

.glass:hover {
  box-shadow: 0 4px 12px 0 rgb(0 0 0 / 0.08);
  transform: translateY(-0.5px);
}

/* 卡片变体 */
.glass-card {
  @apply glass;
  border-radius: 12px;    /* Apple 偏爱的圆角 */
  padding: 32px;
}

/* 按钮变体 */
.glass-button {
  @apply glass;
  border-radius: 12px;
  padding: 12px 16px;
  transition: all 0.2s cubic-bezier(0.4, 0.0, 0.2, 1);
}

.glass-button:hover {
  transform: translateY(-0.5px);
  background: hsl(var(--muted));
}

/* 主要按钮 */
.glass-button-primary {
  background: hsl(var(--accent));
  color: hsl(var(--accent-foreground));
  border: 1px solid hsl(var(--accent));
}

.glass-button-primary:hover {
  background: hsl(var(--accent) / 0.9);
  transform: translateY(-0.5px);
  box-shadow: 0 4px 12px 0 hsl(var(--accent) / 0.3);
}
```

### 深色模式玻璃效果
```css
.dark .glass {
  background: rgba(20, 20, 20, 0.8);
  border: 1px solid rgba(255, 255, 255, 0.08);
  box-shadow: 0 1px 3px 0 rgb(0 0 0 / 0.3);
}
```

## ✨ 动画系统

### Apple 风格动画
```css
/* iOS 缓动函数 */
--ease-in-out: cubic-bezier(0.4, 0.0, 0.2, 1);
--ease-out: cubic-bezier(0.0, 0.0, 0.2, 1);
--ease-spring: cubic-bezier(0.175, 0.885, 0.32, 1.275);

/* 核心动画 */
@keyframes apple-fade-in {
  from { 
    opacity: 0; 
    transform: translateY(8px); 
  }
  to { 
    opacity: 1; 
    transform: translateY(0); 
  }
}

@keyframes apple-scale-in {
  from {
    opacity: 0;
    transform: scale(0.95);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}

/* 动画类 */
.animate-apple-fade-in {
  animation: apple-fade-in 0.6s var(--ease-out) forwards;
}

.animate-apple-scale-in {
  animation: apple-scale-in 0.4s var(--ease-out) forwards;
}
```

### 交互动画原则
- **微妙上升**：hover 时元素向上移动 0.5px
- **阴影加深**：hover 时增强阴影效果
- **平滑过渡**：所有状态变化 0.3s 以内
- **尊重偏好**：支持 `prefers-reduced-motion`

## 🧩 组件模式

### 区块交替背景
```css
/* Apple 经典的区块交替 */
.bg-apple-section-primary {
  background: hsl(var(--background));
}

.bg-apple-section-secondary {
  background: hsl(var(--muted));
}
```

### 渐进式显示
```jsx
{/* 组件级渐显动画 - 带延迟 */}
<div className="animate-apple-fade-in [animation-delay:0.1s]">
  <Card />
</div>
<div className="animate-apple-fade-in [animation-delay:0.2s]">
  <Card />
</div>
```

### 响应式网格
```jsx
{/* Apple 风格的响应式布局 */}
<div className="grid grid-cols-1 lg:grid-cols-3 gap-12">
  <div className="lg:col-span-2">主内容</div>
  <div className="space-y-6">侧边栏</div>
</div>
```

## 📱 移动端优化

### 触摸目标
```css
/* 44px 最小触摸目标 - Apple HIG 标准 */
@media (max-width: 768px) {
  .glass-button {
    min-height: 44px;
    padding: 12px 16px;
  }
}
```

### 空间调整
```css
/* 移动端空间压缩 */
@media (max-width: 768px) {
  .space-apple-lg { padding: var(--space-md); }
  .space-apple-xl { padding: var(--space-lg); }
  section { padding: 16px; }
}
```

## 🔧 实现提示词

### 创建新项目时使用此提示词：

```
请使用 Apple-Class 设计系统创建一个现代极简的网站/应用，具体要求：

1. **颜色系统**：使用纯白背景(#FFFFFF)，深炭灰文字(#171717)，Apple蓝(#007AFF)作为唯一强调色，96%灰度(#F5F5F5)作为次要背景。支持深色模式。

2. **字体系统**：使用响应式clamp()字体大小，Display(36-80px)、Headline(28-48px)、Title(18-24px)、Body(14-18px)。仅使用400和600两种字重，大标题使用负字距。

3. **布局系统**：基于8px网格系统，容器最大宽度1200px，移动端16px边距，桌面端24px边距。使用CSS Grid和Flexbox。

4. **玻璃态设计**：所有卡片和按钮使用backdrop-filter: blur(20px)，白色80%透明度背景，微妙边框和阴影。hover时向上移动0.5px并加深阴影。

5. **动画系统**：使用iOS缓动函数cubic-bezier(0.4, 0.0, 0.2, 1)，渐显动画从透明+8px下移到不透明+原位置，持续0.6s。支持动画偏好设置。

6. **组件模式**：区块交替使用纯白和96%灰背景，渐进式显示带0.1s递增延迟，移动端44px最小触摸目标。

7. **交互反馈**：微妙但有意义，hover状态明显但不突兀，使用transform和box-shadow而非颜色变化。

请确保每个元素都体现Apple的极简美学和用户体验原则。
```

## 💡 设计原则总结

1. **少即是多** - 删除不必要的装饰元素
2. **功能第一** - 设计服务于功能，而非相反  
3. **一致性** - 整个系统使用相同的视觉语言
4. **可访问性** - 支持无障碍访问和用户偏好
5. **性能优先** - 优雅的视觉效果不应影响性能
6. **情感设计** - 微妙的交互让用户感到愉悦

---

*此设计系统基于 Apple Human Interface Guidelines 和现代 Web 标准，适用于任何需要专业、简洁、现代感的数字产品。*
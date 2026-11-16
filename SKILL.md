---
name: metre
title: 格律 Metre
version: 4.3.0
codename: 格律
description: 我的 PPT 设计插件。给它每页要说什么，它按我的风格排出来：真实字体度量断行、图色驱动配色、圆角与留白有规矩、出片前自审。默认就是我的风格，5 种设计语言只是变奏。
---

# 格律 Metre · 4.3

**一句话**：这是我的设计插件——**默认出品就是我的风格**，不是通用模板。
你（Agent）决定每页说什么，引擎按我的规矩排；`language` 只是换一种语气。

风格存在 `style/me.json`：纸色、墨色、强调色、字体气质、圆角、阴影、对齐倾向、
边距、布局偏好、以及几条硬规矩。**改那一份文件 = 改我的默认出品**，不用改代码。

```bash
python3 -m studio.cli style      # 看当前默认风格
```

## 什么时候用 / 不用

| 用 | 不用 |
| --- | --- |
| 要做 5–60 页、需要现场改文案的提案 / 汇报 / 复盘 | 要 1 页海报（直接用画布工具更快） |
| 需要中文断行正确、数字对齐、多册风格统一 | 需要逐像素微调（本引擎不暴露坐标） |
| 需要「先审后发」：不重叠、不溢出、对比度达标 | 要套现成公司模板（请给 `style` 覆盖） |

## 30 秒上手

```bash
python3 -m studio.cli spec --json                 # 机器可读契约（语言/页型/字段）
python3 -m studio.cli build deck.json out.pptx    # 出片；有硬伤退出码 1
python3 -m studio.cli build deck.json out.pptx --png preview/   # 顺带出图（Keynote）
python3 -m studio.cli fetch assets/ "coffee roasting" --n 6     # 联网取图 + 来源.json
python3 -m studio.cli selftest                    # 矩阵自检
```

```json
{"language": "sweet", "variation": 7, "assets": "assets/",
 "pages": [
   {"kind": "cover", "title": "一句话说清这册讲什么", "sub": "副题", "image": "assets/cover.jpg"},
   {"kind": "points", "title": "三条就够", "items": ["一", "二", "三"]},
   {"kind": "closing", "title": "下一步", "sub": "联系人"}
 ]}
```

## 四个旋钮（都可不填）

| 旋钮 | 取值 | 不填时 |
| --- | --- | --- |
| `language` | `me`（我的风格）/ `sweet` 甜本 / `iron` 铁报 / `paper` 纸案 / `grid` 格物 / `manifesto` 宣言 | `me` |
| `variation` | 整数 / 字符串 / `auto` | 用内容自身做种子：**同稿可复现，不同稿不同脸** |
| `fonts` | `auto` 或 `{ea_display, ea_body, ea_micro}` | 按语言气质从字体池取一组 |
| `color_mode` | `language` / `image`（+ `accent_from_image`） | 语言纸色；有图时仍会被图轻染 |

**默认不要写 `language`**：不写就是我的风格。只有要「铁报那种冲击力」或「宣言那种安静」时，
才显式指定一个变奏。

**选语言看密度，不看行业**：信息密、要冲击 → 铁报；留白多、要安静 → 宣言；
书卷气 → 纸案；报告感 → 格物；温和品牌 → 甜本。

**字体不要手写**：`auto` 会从同气质的池子里选（霞鹜文楷 / 思源宋体 / 思源黑体 /
阿里巴巴普惠体 / 得意黑），同一册只用两族；要指定就写 `fonts`。

**颜色不要写死**：`color_mode: "image"` + `accent_from_image: true` 会让纸、底板、
强调色跟着封面图走；单页还能用 `accent` / `panel` 覆盖。

## 页型速查（15 种，必填键）

| kind | 必填 | 常用于 |
| --- | --- | --- |
| `cover` | `title` | 封面（可 `image`，可 `variant: poster` 居中） |
| `section` | `title` | 章节（`index` 可选） |
| `statement` | `statement` | 一句主张（可 `align: center`） |
| `points` | `title` `items` ≤5 | 要点 |
| `metrics` | `title` `metrics[{v,l}]` ≤4 | 指标 |
| `band` | `title` `metrics` | 色带数字 |
| `cards` | `title` `cards[{v,h,t,image}]` ≤4 | 卡片 |
| `split` | `title` + `items` 或 `image` | 图文 |
| `imagepanel` | `title` | 图叠字面板 |
| `compare` | `title` `columns[{head,body}]` | 两栏对比 |
| `table` | `title` `columns` `rows` | 表（放不下会报错） |
| `chart` | `title` `values` | 柱/折线 |
| `gallery` | `title` `images[]` | 图集 |
| `quote` | `quote` | 引语（`by` 出处） |
| `closing` | `title` | 结尾（`full`/`block`/`split`/`quiet` 轮换） |

## 硬规则（违反会报错或体检不过）

1. 内容里**不写坐标**；位置由引擎算。
2. 一页一观点：`items` ≤5，`metrics` ≤4。
3. 字号层级 2–5 级；标题/正文比 1.6–3.2（引擎自动满足）。
4. 正文不用纯黑；中文一行 ≤44 字。
5. 图必须**cover 裁切**；缺图会报错，不伪造。
6. 文字压图必须带渐变遮罩（引擎自动加）。
7. 不出现样板水印、吉祥物、固定照片、巨型首字母。
8. 表格/正文放不下 → **报错退出码 2**，请拆页，不要硬塞。

## 报错对照

| 报错 | 处理 |
| --- | --- |
| `未知页型 kind=...` | 用上表 15 种之一（拼错最常见：`galary`→`gallery`） |
| `第 N 页的 image 不存在` | 路径相对内容文件；或改用 `assets` 池 |
| `表格放不下：N 行需要 Xpt` | 删行 / 拆两页 / 换 `table` 为 `points` |
| `正文放不下（需要 Xpt）` | 精简文字或拆页；不要靠缩小字号硬塞 |
| `合规分 < 100` 且有硬伤 | 看 `-体检.md` 的具体页与原因 |

## 交付前

```bash
python3 -m studio.cli selftest            # 矩阵：5 语言 × 15 页型 × 有图/无图
python3 -m studio.cli build … --png …     # 目视一遍 preview/
```

体检报告的「合规分」= 100 − 硬伤×12 − 待调×3，衡量**没犯多少规矩**，不是设计质量分。

## 文档索引

| 想知道 | 看 |
| --- | --- |
| 五种语言各自的气质 | `design/设计语言.md` |
| 断行与字号怎么算 | `design/度量与断行.md` |
| 纵向怎么分布、留白几档 | `design/纵向分布与填空.md` |
| 圆角 / 阴影 / 卡片 / 图片布置 | `design/图形与装饰.md` |
| 选图、图像处理、图色取色 | `design/选图与图像处理.md` |
| 中文字体配对 | `design/字体与中文排印.md` |
| 审计项与分数 | `design/审计.md` |

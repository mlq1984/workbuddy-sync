# 海报文案生成提示词模板库

## 美业/护肤风格

**适用场景**：护肤品、美容院、医美、个人护理、高端日化
**视觉特征**：米白柔光、左文右图、亚洲女性人像占右半脸部完整、左侧留白给文字、绿叶白花大理石台面、金色细线装饰、橄榄墨绿/金棕配色

**系统提示词**：
```
你是高端美业/护肤品牌的资深文案策划。擅长"左文右图"编辑版式，文案需配合人像留白区域，信息层级清晰：小副标→粗大主标→细体副标→金色分割线+英文→3-4条带圆环图标的卖点(主副两行)→引号金句→墨绿胶囊CTA→联系信息。
```

**用户提示词模板**：
```
主题: {theme}
品牌: {brand}
产品: {product}
核心成分: {ingredients}
目标人群: {audience}
补充: {extra}

输出严格 JSON：
{
  "title": "主标题(8-12字,粗体视觉重心)",
  "subtitle": "小副标(10-16字,细体,功能/场景导向)",
  "slogan": "引号金句(15-25字,情感共鸣/品牌主张)",
  "selling_points": [
    {"main": "核心卖点1(4-6字)", "sub": "支撑细节(8-12字)"},
    {"main": "核心卖点2", "sub": "支撑细节"},
    {"main": "核心卖点3", "sub": "支撑细节"},
    {"main": "核心卖点4", "sub": "支撑细节"}
  ],
  "cta": "行动号召(4-6字,如:立即预约/领取体验/咨询专家)",
  "contact": "400-xxx-xxxx | www.brand.com | 城市 区 街道 号",
  "image_prompt": "英文提示词: Commercial beauty poster, ivory soft lighting, Asian woman portrait occupying right half with full face visible, left side negative space for text overlay, green leaves and white flowers on marble surface, golden thin line accents, olive green #46523C and gold #B2935C color palette, high-end skincare photography style, no text, clean composition, 8k quality"
}
```

---

## 节庆/国潮风格

**适用场景**：传统节日(春节/中秋/国庆/端午)、国潮品牌、文创礼品、旅游文旅、政府/国企宣传
**视觉特征**：深红/朱红底、烫金毛笔书法、对称居中、灯笼/烟花/祥云/梅花/瑞兽、金色/渐变金装饰、电影级布光

**系统提示词**：
```
你是节庆/国潮品牌的资深文案策划。擅长"全屏居中烫金"版式，文案配合对称构图，信息层级：节日氛围副标→超大烫金主标→金句slogan→2-3核心卖点→金色胶囊CTA→品牌署名。
```

**用户提示词模板**：
```
主题: {theme}
品牌: {brand}
节日: {festival}
补充: {extra}

输出严格 JSON：
{
  "title": "主标题(6-10字,烫金书法感,如:盛世华诞/花好月圆/瑞启新春)",
  "subtitle": "节日副标(8-16字,如:中华人民共和国成立77周年/中秋佳节阖家团圆)",
  "slogan": "金句(12-20字,如:山河无恙烟火寄相思/月圆人团圆万事胜意)",
  "selling_points": [
    {"main": "核心价值1", "sub": "展开描述"},
    {"main": "核心价值2", "sub": "展开描述"},
    {"main": "核心价值3", "sub": "展开描述"}
  ],
  "cta": "行动号召(4-8字,如:共庆佳节/领取福利/参与活动)",
  "contact": "品牌官方 | 共贺华诞",
  "image_prompt": "英文提示词: Chinese festival celebration, deep red background #8B0000, gold calligraphy brush strokes, traditional elements: lanterns fireworks auspicious clouds plum blossoms, golden foil texture, cinematic lighting, symmetrical composition, 8k ultra detailed, no text"
}
```

---

## 极简/通用风格

**适用场景**：科技产品、极简品牌、现代服务、B2B、APP推广、通用营销
**视觉特征**：大面积留白、无衬线字体、单色/双色配色、几何分割、功能导向

**系统提示词**：
```
你是极简风格品牌的文案策划。擅长"少即是多"版式，文案精炼有力，信息层级扁平：主标→副标→2-3核心点→CTA，无冗余装饰。
```

**用户提示词模板**：
```
主题: {theme}
品牌: {brand}
产品: {product}
核心价值: {value}
补充: {extra}

输出严格 JSON：
{
  "title": "主标题(6-10字,简洁有力)",
  "subtitle": "副标题(8-16字,补充说明)",
  "slogan": "一句话金句(10-20字,击中痛点)",
  "selling_points": [
    {"main": "核心功能1", "sub": "用户收益"},
    {"main": "核心功能2", "sub": "用户收益"},
    {"main": "核心功能3", "sub": "用户收益"}
  ],
  "cta": "行动号召(4-6字,如:免费试用/立即体验/了解更多)",
  "contact": "brand.com | 联系我们",
  "image_prompt": "英文提示词: Minimalist poster design, clean white background, elegant typography layout, geometric shapes, soft shadows, high-end commercial photography, plenty of negative space, 8k quality, no text"
}
```

---

## 图生图/编辑模式提示词结构

**图生图**：
```
[改变要求] + [新风格/场景] + [需添加/移除元素] + [需保留元素]
示例: "Transform the scene into a rain-soaked cyberpunk night with neon reflections while preserving the original composition and main subject"
```

**多图合成**：
```
[参考图1角色] + [参考图2角色] + [目标场景] + [图像间关系] + [风格/光照/构图]
示例: "Use first image as main character, second as product reference, generate a cinematic event poster preserving character identity and product shape, natural lighting, clean commercial composition"
```

**高信息密度优化**：
```
清晰描述视觉层级: 主体、背景环境、重要次要细节、风格、光照、构图约束
示例: "Cliff-side fantasy port city, hundreds of small boats, layered stone bridges, glowing windows, distant mountains, cloudy sunset sky, cinematic fantasy realism, wide angle, rich architectural details, high visual density"
```

---

## 质量检查清单

生成文案后自检：
- [ ] JSON 格式有效，无多余字符
- [ ] 中文字数在建议范围内
- [ ] selling_points 数量 2-4 条，每条含 main+sub
- [ ] image_prompt 为纯英文，结构完整 [主体]+[场景]+[风格]+[光照]+[构图]+[质量]
- [ ] image_prompt 末尾含 "no text"
- [ ] 风格关键词与模板匹配(美业:ivory/olive green/marble; 节庆:deep red/gold/calligraphy; 极简:minimal/white/geometric)
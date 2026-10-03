---
description: 处理图片扫描型PDF（无法提取文字）的OCR总结流程：渲染页面→关键页OCR→生成摘要
trigger: 当用户要求总结、阅读或提取扫描件PDF内容时
---

# PDF OCR 总结 Skill

处理图片扫描型PDF（文字提取为空时），通过渲染+OCR获取内容并总结。

## 步骤

### 1. 确认PDF类型
```python
from pdfminer.high_level import extract_text
text = extract_text(pdf_path)
# 如果只有广告/页眉水印，说明是扫描版PDF，需要OCR
```

### 2. 渲染PDF页面为图片
```python
import pypdfium2 as pdfium
pdf = pdfium.PdfDocument(pdf_path)
print(f'Pages: {len(pdf)}')
for i in range(min(num_pages, len(pdf))):
    page = pdf[i]
    bitmap = page.render(scale=2.0)
    image = bitmap.to_pil()
    image.save(f'path/page_{i+1}.png')
```
- scale=2.0 保证OCR精度，根据页数控制渲染范围（先渲染关键页）

### 3. OCR关键页
使用已安装的 `ocr-space` skill 的 `ocr_image()` 函数：
```python
import sys
sys.path.insert(0, r'C:\Users\king\.workbuddy\skills\ocr-space')
from ocr_space import ocr_image
result = ocr_image(path, language='chs')
```

**策略**：不要OCR全部页面，优先选取：
- 前5页（封面、前言、目录）
- 每隔30-50页选1页（了解章节结构）
- 后5页（结论、附录）

### 4. 生成总结
基于OCR结果撰写结构化总结。

## 注意事项
- OCR.space 免费版每日500次限制，关键页采样即可
- 中文PDF用 `language='chs'`
- 444页PDF建议渲染前30页+关键采样页，共约50-60张图
- 删除临时渲染图片时注意批量删除的安全限制（单次超过50个会触发确认）

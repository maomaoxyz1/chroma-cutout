---
name: chroma-cutout
description: 把实拍照片里的人物、动物、物件、植被或毛发主体抠出来，输出带真 alpha 通道的透明 PNG。只有两步：① 用生图模型把背景换成透明背景；② 本地验收并导出成品。适用于背景复杂的照片（室内、地板、笼子、墙面、文字、水印）。Triggers: 抠图, 去背景, 抠透明背景, 透明底, 透明 PNG, 素材去背, cutout, transparent background, remove background, background removal, transparent PNG, alpha channel, subject isolation.
license: MIT
---

# 透明背景抠图（chroma-cutout）

背景复杂时**不要**用阈值、魔棒或多边形硬抠——边缘一定脏。这个技能只有两步：

```
原图 ──① 生图模型换透明背景──> 真 alpha PNG ──② 本地验收并导出──> 成品
```

> 名字里的 "chroma" 是历史遗留：早期版本用单色幕 keying，现在直接依赖生图模型的真 alpha 输出，不再需要换幕。

## 第一步：让生图模型直接输出透明背景

用**你环境里已有的生图/改图能力**，把原图作为参考图传进去。不要新建 API 客户端或封装脚本。

| 环境 | 怎么调 |
|---|---|
| 宿主机内置生图 | 传原图 + 下面的提示词，输出 PNG |
| OpenAI Images API（`gpt-image-1` / `gpt-image-2`） | `POST /v1/images/edits`，带 `background: "transparent"`、`output_format: "png"`，原图放在 `image` |
| 其他生图服务 | 同一思路：传原图 + 提示词；若该服务有「透明背景」开关，一并打开 |

提示词模板：

```text
Edit the supplied image into a clean cutout. Preserve the subject's identity,
pose, silhouette, colors, texture, and fine edge details. Remove the entire
background and all unrelated objects, including any text or watermark. Output
the subject only on a genuinely transparent background with a real alpha
channel. Do not draw a checkerboard pattern, white or gray matte, glow, shadow,
outline, or replacement background. Keep the subject fully inside the canvas
with a small transparent margin. Export PNG.
```

四个要点：
- **明确要真 alpha 通道**，并点名不要棋盘格、白/灰底、光晕——否则模型常画一张假的棋盘格糊弄你
- **逐项列出要删的东西**：文字、水印、地板、笼子、另一只动物
- **要求主体不变**：keep unchanged / no repaint，否则表情、姿势、花纹会漂
- **别让主体贴边**，留一点透明余量

## 第二步：本地验收并导出

```bash
python3 scripts/alpha_check.py cutout.png -o preview.png
```

四件事，任一不过就以非 0 退出（可接批处理）：

1. 文件真的有 alpha 通道（不是全不透明的 RGB）
2. 四角 alpha 接近 0
3. 透明像素不为 0（背景确实被去掉了）
4. 没有把棋盘格**画进 RGB** 里

`-o` 会在**棋盘格背景**上合成一张 preview。必须亲眼看一遍：

- 透明区应该显示棋盘格，而不是一片纯色
- 主体边缘没有色圈、白边或半透明光晕
- 该在的细节还在（发丝、胡须、眼镜框、首饰）

数值通过只是必要条件，不够充分——它判断不了主体被重画、被裁掉或抠空。

## 实测

用 `gpt-image-2` + 一张 1773×2364 的竖版插画（含「豆包 AI 生成」水印、深色室内背景）：

- 输出为真 RGBA，四角 alpha = 0，透明区占 **46.8%**
- 人物姿势、眼镜、项链、发丝全部保留，水印被去掉
- 合成到深色和浅色背景上看都没有可见色圈
- 单张生成约 50 秒

注意生图服务可能**不遵守你传的尺寸参数**：同一次请求要 1024×1792，实际回来 1086×1448。别假设输出尺寸等于输入尺寸，按实际结果处理。

## 局限

- 生图不是像素保持的：模型会轻微重画主体，同一角色多次生成花纹可能微变。要求像素级一致时，改用确定性的分割工具。
- 真 alpha 支持取决于模型和接口。拿不到就说明这条路走不通，不要用画出来的棋盘格顶替。
- 一次只能处理一张原图。批量时逐张跑，注意接口限流和付费次数。
- 保留原图；输出写到新路径，不要覆盖源文件。

## 依赖

- Python 3 + NumPy + Pillow（仅第二步需要）
- 第一步依赖你环境里的生图模型

## 出处与许可

MIT 许可，见 [LICENSE](LICENSE)。

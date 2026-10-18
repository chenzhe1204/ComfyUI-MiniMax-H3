# ComfyUI MiniMax H3（非官方）

在 Apple Silicon 上通过原生 Metal [`h3.c`](https://github.com/antirez/h3.c) CLI
运行 **MiniMax H3** 的非官方 ComfyUI 节点。

> **模型许可证/地域提示**
>
> 本仓库**不包含** MiniMax H3 模型权重。权重需单独下载，并受 **MiniMax H3
> Community License Agreement** 约束；该许可证的 Applicable Territory 排除
> **欧盟、英国、韩国、美国**，同时包含商业使用、可接受使用和再分发条件。
> 下载前请阅读官方许可证：
> <https://www.modelscope.cn/models/MiniMax/MiniMax-H3/file/view/master/LICENSE>。

> **非官方项目**：与 MiniMax、ComfyUI、h3.c 作者无隶属、背书或赞助关系。

[English README](README.md)

## 功能

- **`MiniMax H3 FL2VA`**：文生视频、首帧、尾帧、首尾帧。
- **`MiniMax H3 Ref2VA`**：有序参考图 + 可选 2–15 秒参考音频，支持 `match`/`max`。
- 生成 24fps H.264 + 32kHz 立体声 AAC 的 MP4。
- 直接保存到 `ComfyUI/output`，节点内显示预览，同时输出 `VIDEO` 和 `saved_path`。
- 暴露完整 H3 参数：分辨率、帧数/时长、steps、layers、reuse、token reduction、
  SSD streaming、int8 FC2、内部渲染尺寸、seed、profile。
- 进度解析、取消、超时、失败输出清理。
- 跨进程执行锁，避免两个 ComfyUI 实例同时启动 H3。
- 路径通过环境变量/配置文件管理，带 preflight 和 doctor 脚本。

## 环境要求

| 项目 | 说明 |
|---|---|
| Apple Silicon Mac | 仅 Metal；不支持 Intel Mac、Windows、Linux。 |
| macOS | 在 macOS 26.x + M5 Max 上验证。 |
| 统一内存 | 128GB 为已验证配置；更低内存可尝试 `ssd_streaming`，但未验证。 |
| 磁盘 | 当前模型目录约 464GB，建议预留 500GB+。 |
| ComfyUI | `>= 0.41.2`（测试 0.41.2）；需要 V3 节点 API 和 `VIDEO` 类型。 |
| Python | 3.10+。 |
| h3.c | 按固定 commit 构建，见下文。 |
| FFmpeg / FFprobe | h3.c 必需；`brew install ffmpeg`。 |
| Python 包 | `torch`、`numpy`、`Pillow` 由 ComfyUI 提供；本包没有额外运行时 pip 依赖。 |

## 安装

### 1. 安装节点

```sh
cd /path/to/ComfyUI/custom_nodes
git clone https://gitee.com/chenzhe1204/ComfyUI-MiniMax-H3.git
```

开发目录也可以软链：

```sh
cd /path/to/ComfyUI-MiniMax-H3
./install.sh /path/to/ComfyUI
```

`pyproject.toml` 已包含 ComfyUI Registry 元数据（`PublisherId = chenzhe1204`）。

### 2. 构建 h3.c

本适配器不内置 h3.c。按固定 commit 构建到 `third_party/h3.c`：

```sh
./scripts/bootstrap_h3_cn.sh
```

需要 Xcode Command Line Tools、macOS SDK 和 `make`。如果已有 h3.c checkout，
也可以把 `H3_BIN` 指向它的 `h3`。二进制必须和 `h3_shaders.metal` 在同一目录，
不要只复制二进制。

固定 commit：`8974cc055ea9c02fcd14cc27dfda3e1027c05153`（`h3-metal 0.1.0-dev`）。
`scripts/doctor.py` 会检查 CLI 参数契约。

### 3. 下载模型

先接受官方许可证，再按官方命令下载：

```sh
modelscope download MiniMaxAI/MiniMax-H3 \
  --include "model_index.json" "FL2VA/*" "Ref2VA/*" \
  --local-dir /path/to/MiniMax-H3
```

FL2VA 节点需要 `FL2VA/transformer`；Ref2VA 节点还需要 `Ref2VA/transformer`。
本项目不镜像或再分发权重。

### 4. 配置路径

环境变量优先级最高：

| 变量 | 作用 |
|---|---|
| `H3_DIR` | 包含 `h3` 和 `model/` 的目录，自动推导两个路径。 |
| `H3_MODEL_DIR` | 显式模型目录。 |
| `H3_BIN` | 显式 `h3` 可执行文件。 |
| `H3_FFMPEG` / `H3_FFPROBE` | 显式 FFmpeg 工具。 |
| `H3_CONFIG` | 显式 JSON 配置文件。 |
| `H3_SERIALIZE` | `1`（默认）串行执行；`0` 关闭执行锁。 |
| `H3_KEEP_TEMP` | `1` 保留临时图片/音频，便于排查。 |
| `H3_AUTO_DETECT` | `0` 关闭对 `third_party/h3.c` 的自动探测。 |

或创建 `ComfyUI/user/default/comfyui-minimax-h3.json`：

```json
{
  "h3_dir": "/absolute/path/to/h3.c",
  "model_dir": "/absolute/path/to/MiniMax-H3"
}
```

只写 `h3_dir` 时默认模型在 `<h3_dir>/model`；如果权重下载在别处，请设置
`model_dir`。

完整配置也可设置 `model_dir`、`h3_binary`、`ffmpeg`、`ffprobe`、`serialize`、
`keep_temp`、`auto_detect`，示例见 [config.example.json](config.example.json)。
在 ComfyUI 外运行时，默认配置路径是
`~/.config/comfyui-minimax-h3/config.json`。

### 5. 重启并自检

```sh
python scripts/doctor.py --mode ref2va
```

重启 ComfyUI 后搜索 `MiniMax H3` 分类。

> **从 0.1 之前的开发版升级**：节点 ID 不变，但 `model_dir` 和 `h3_binary`
> 已不再是节点 widget。旧工作流请删除并重新添加节点，然后通过环境变量或 JSON
> 配置文件设置路径。

## 节点

### FL2VA：文生视频/首尾帧

| 输入 | 必需 | 说明 |
|---|---|---|
| `prompt` | 是 | Context-IR 风格：场景、动作、镜头、光线、声音。 |
| `first_frame` | 否 | 首帧条件图，拉伸到画布。 |
| `last_frame` | 否 | 尾帧条件图，aspect-cover 缩放并居中裁剪。 |

不接图片就是纯文生视频（T2VA），仍使用 FL2VA checkpoint。

### Ref2VA：参考图/音频

| 输入 | 必需 | 说明 |
|---|---|---|
| `prompt` | 是 | 可用 `<Picture 1>`、`<Picture 2>` 引用参考图。 |
| `ref_images` | 是 | 有序 batch，第 1 张是 `<Picture 1>`，最多 9 张。 |
| `ref_audio` | 否 | 2–15 秒参考音频，必须和参考图一起使用。 |
| `ref_image_size` | 是 | `match` 保持宽高比，`max` 使用最大参考画布。 |

FL2VA 与 Ref2VA 互斥；H3 不允许首尾帧和有序参考图混用。

### 通用参数

| 参数 | 默认 | 说明 |
|---|---:|---|
| `width` / `height` | 512 / 512 | 32 的倍数；`width*height <= 768*1344`。 |
| `frames` | 56 | 向上对齐到 `5+17n`。22≈0.92s，56≈2.33s，107≈4.46s，243≈10.1s，362≈15.08s。 |
| `seconds` | 0 | 大于 0 时覆盖 `frames`，按 24fps 换算。 |
| `steps` | 20 | 4–7 做草稿，50 接近参考质量。 |
| `layers` | 45 | 50 精确，45 快，40 激进。 |
| `reuse` | 2 | 1 精确，2 快，3 激进。 |
| `core_reuse` | 1 | 1 精确，4 快，6 激进；不能和 `reuse>1` 同用。 |
| `token_reduction` | 关 | 更快，可能改变构图。 |
| `ssd_streaming` | 关 | 更省内存、更慢；不能和 `int8_row_fc2` 同用。 |
| `int8_row_fc2` | 关 | M5 专用更快的 int8 FC2。 |
| `use_reference_rope` | 关 | 恢复发布版空间 RoPE。 |
| `render_width` / `render_height` | 0 / 0 | 内部渲染尺寸；0 表示输出尺寸。 |
| `seed` | 42 | 原生 H3 随机种子。 |
| `filename_prefix` | `minimax_h3/H3` | `ComfyUI/output` 下的前缀。 |

`timeout_seconds` 和 `profile` 是高级参数。生成的 MP4 自带音频；需要单独音频时
接 `GetVideoComponents`。

### 输出

- `video`：标准 `VIDEO`，可接 `SaveVideo`、`GetVideoComponents` 等。
- `saved_path`：自保存 MP4 的绝对路径。
- 节点是 output node，排队执行即可保存视频。

## 提示词与媒体注意事项

- 推荐结构化提示词：`Scene: ... Action: ... Camera: ... Look: ... Audio: ...`
- 多张参考图按 **batch 顺序**传入；先用 `ImageBatch` 等节点合并。
- 参考音频必须 **2–15 秒**；可用 `TrimAudioDuration` 裁剪。H3 不支持只有音频
  没有图像/视频参考，所以 `ref_audio` 必须配合 `ref_images`。
- H3 输出 24fps，帧数向上对齐；请求 23 帧会生成 39 帧。

## 性能

在 M5 Max / 128GB / ComfyUI 0.41.2 上验证：

| 测试 | 配置 | 结果 |
|---|---|---|
| 原生标准 | 512×512，22 帧，20 步，layers 45，reuse 2 | 约 52 秒 |
| ComfyUI FL2VA | 256×256，22 帧，4 步，layers 50，reuse 1 | 约 35–45 秒 |
| ComfyUI Ref2VA | 256×256，22 帧，4 步 + 参考图 + 3 秒音频 | 约 55–60 秒 |

每次执行都会启动新的 h3 进程，因此每次都有冷启动成本；进程结束后释放统一内存。
`H3_SERIALIZE=1` 防止两个任务同时启动。

## 故障排查

先运行：

```sh
python scripts/doctor.py --mode ref2va
```

常见问题：

- **`h3_shaders.metal is missing`**：`H3_BIN` 必须指向包含 shader 的构建目录。
- **`ffmpeg not found`**：安装 FFmpeg，或设置 `H3_FFMPEG` / `H3_FFPROBE`。
- **缺少 `FL2VA/transformer` / `Ref2VA/transformer`**：模型下载不完整，或
  `H3_MODEL_DIR` 指错。
- **ComfyUI 版本太旧**：需要 V3 节点 API 和 `VIDEO` 类型，请升级。
- **内存不足**：关闭其他模型、降低分辨率/帧数，或使用 `ssd_streaming`。
- **h3 退出码错误**：错误信息会带最后几十行 h3 输出，检查画布、帧数、音频时长
  和内存。

## 安全

- `h3` 以当前用户权限作为本地进程运行，没有沙箱。
- `h3_binary` 故意**不是**节点 widget；二进制/模型路径只由管理员配置，避免不可信
  工作流指向任意可执行文件。
- prompt/媒体通过 argv 传递，不经过 shell；临时文件默认在结束后删除。
- 不要运行不可信工作流，也不要加载不可信模型文件。详见 [SECURITY.md](SECURITY.md)。

## 兼容性

| 组件 | 版本 |
|---|---|
| 节点 | 0.1.0 |
| ComfyUI | >= 0.41.2，测试 0.41.2 |
| h3.c | `8974cc055ea9c02fcd14cc27dfda3e1027c05153` |
| 模型 | MiniMax-H3（FL2VA / Ref2VA） |
| macOS | 测试 26.x |
| 硬件 | 测试 M5 Max / 128GB |

h3.c 仍在活跃开发；升级时请显式更新固定 commit，并重新运行 doctor。

## 开发与测试

使用 fake h3 的单元测试（不加载模型）。IMAGE/AUDIO 测试需要 `torch`、`numpy`、
`Pillow`，建议用 ComfyUI 的 Python：

```sh
python -m unittest discover -s tests -t . -v
```

ComfyUI 节点集成测试（fake h3 + 真实 ComfyUI import）：

```sh
COMFYUI_DIR=/path/to/ComfyUI \
  python -m unittest tests.check_nodes_integration -v
```

可选真实模型冒烟测试：

```sh
python tests/smoke_generate.py --frames 22 --steps 4
```

更多见 [CONTRIBUTING.md](CONTRIBUTING.md)。请勿在 issue/PR 中包含模型权重、
生成素材或私有路径。

## 许可证与第三方声明

本仓库代码使用 [GPL-3.0-or-later](LICENSE)，与 ComfyUI 的 GPL-3.0 保持一致。

- MiniMax H3 权重：MiniMax H3 Community License Agreement；不包含。
- h3.c：MIT，Copyright (c) 2026 Salvatore Sanfilippo；不包含。
- ccv Metal FlashAttention 部分：BSD-3-Clause；见 h3.c 的 notices。
- Qwen3-VL-32B 编码器：Apache-2.0；属于模型，不包含。
- ComfyUI：GPL-3.0；运行时宿主，不包含。
- FFmpeg/FFprobe：外部命令，不打包。

完整声明见 [NOTICE](NOTICE) 和 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
这不是法律意见；发布或商业使用前请自行确认模型许可证和分发义务。

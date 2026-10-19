# 运行记录

| 动效 | 结束方式 | 动作数 | 版本数 | 快检 | 完整检查 |
|---|---|---:|---:|---:|---:|
| [browser](browser) | 自己交付（第 23 步） | 23 | 15 | 13 | 2（自动） |
| [payment](payment) | 自己交付（第 24 步） | 24 | 20 | 18 | 2（自动） |
| [trophy](trophy) | 用完 24 步 | 24 | 15 | 15 | 0 |
| [x_pop](x_pop) | 自己交付（第 24 步） | 24 | 21 | 21 | 0 |

trophy 和 x_pop 跑在加入“自动完整检查”之前，所以没有完整检查。

每个文件夹：

- `run.json`：模型、结束方式、动作统计
- `final_ir.json`：交付的动画；`versions/`：每一个被接受的版本
- `checks/`：检查 Agent 看到的图（`quick_*.png`、`review_*_strip_*.png`、`review_*_curves.png`、`review_*_zoom.png`）和它的原话（`*.txt`），以及主 Agent 请求的预览（`preview_*.png`）
- `trace.jsonl`：主 Agent 每一步的回复和环境返回的文字（文中的图片文件名对应 `checks/`）
- `final_strip.png`：目标与结果的 16 帧对比

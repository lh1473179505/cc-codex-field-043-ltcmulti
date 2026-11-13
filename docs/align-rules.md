# align 规则

默认策略见 `fixtures/policy.json`。公开夹具是 25 fps、非丢帧、48 kHz 单声道导轨。

## 输入

- `fixtures/shoot.json` 列出若干机位，每条有 `id`、`path`、`nominal_fps`。`master` 指向主机位 id（夹具里是 `camA`）。
- LTC 是双相标记码，80 bit 一帧，同步字为 bit 64–79 的 `0011111111111101`。解码请走已有的 `ltc.decode_bmc`。
- 用户位（binary groups）按 4 字节原样保留到 map 里，不对齐过程做解释。

## 对齐

- 以主机位解码出的时间码为参考时钟。对每个从机位，估计：
  - `offset_frames`：从机位第一条可靠 LTC 相对主机位同一时间码的帧差（从机减主机，负值表示从机画面更早）。
  - `offset_samples`：把该帧差换到该机位采样率上的采样偏移，再加该 LTC 帧在文件内的采样位置差。
  - `drift_ppm`：用最小二乘对“从机时间码帧号 vs 文件采样位置”和主机做线性拟合，斜率差换成 ppm。正值表示从机时钟偏快。
- 不可读或校验失败的帧（解码器跳过的间隙）不得参与拟合。夹具里 `camC` 开头约 1 秒是噪声，中间还有一次时间码跳变（摄像机重启）。跳变前后要分成两段：`segments` 数组里每段各自有 offset 和 drift，不能用一条直线硬穿过去。
- `camB` 相对主机既有固定的入点延迟（12 帧），又有大约 +80 ppm 的时钟偏差。align 必须把这两项分开报告，误差：offset 允许 ±0.5 帧，drift 允许 ±15 ppm。
- 丢帧与非丢帧不能混算。若某机位的 `drop_frame` 与主机不一致，该机位 `decision` 为 `reject`，`reason_codes` 含 `dropframe_mismatch`，不要强行换算后当成功。公开夹具全部是 25 NDF，这条是给隐藏夹具准备的。

## 输出 map

`--map` 写一份 JSON，列出每个机位：

- `id`
- `segments`: `[{ "start_tc", "end_tc", "start_sample", "end_sample", "offset_frames", "offset_samples", "drift_ppm" }]`
- `readable_ratio`: 成功解码帧数 / 按时长期望的帧数

## 退出码

- 全部机位都得到至少一段可靠对齐：退出 0，`decision` 为 `ok`。
- 某从机位可读帧少于策略 `min_readable_ratio`（默认 0.5）：该机位记 `insufficient_lock`，整体 `decision` 为 `reject`，退出 1，但仍写出 map 与报告。
- 清单或 WAV 读失败：退出 2。

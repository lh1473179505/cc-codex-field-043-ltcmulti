# ltcmulti

多机位外拍素材的 LTC 对齐工具。`probe` 能从音频导轨里解出 SMPTE LTC 帧；`align` 以主机位解码出的时间码为参考时钟，按段估计每个从机位的入点偏移（帧/采样）和时钟漂移（ppm），并写出对齐 map 与报告。

不要引入 NumPy、sox 或 ffmpeg-python，也不要使用 Docker。请复用 `ltcmulti.ltc`、`ltcmulti.timecode` 和 `ltcmulti.wavio`。

## 命令

```
python -m ltcmulti probe --manifest fixtures/shoot.json
python -m ltcmulti align \
  --manifest fixtures/shoot.json \
  --policy fixtures/policy.json \
  --report /tmp/ltcmulti-report.json \
  --map /tmp/ltcmulti-map.json
```

规则见 `docs/align-rules.md`，报告与 map 字段见 `docs/report-schema.md`。

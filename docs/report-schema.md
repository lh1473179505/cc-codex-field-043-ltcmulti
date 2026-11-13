# 报告 schema

| 字段 | 类型 | 含义 |
|---|---|---|
| manifest | string | 输入清单 |
| decision | string | `ok` 或 `reject` |
| reason_codes | string[] | 全局原因 |
| master | string | 主机位 id |
| cameras | object[] | 每机位的可读比、段数、主偏移和漂移 |
| map | string | 对齐 map 路径 |

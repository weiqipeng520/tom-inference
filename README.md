# Tom推演系统

科技风手机仪表盘，GitHub Actions统一训练，SQLite统一存库，GitHub Pages统一发布。仅特码候选：36/24/16/8/4码，9/6/4/2肖。

**手机上传和上线步骤见 [DEPLOY.md](DEPLOY.md)。**

## 架构

```text
指定来源已完成开奖
       ↓
GitHub Actions（唯一串行写者）
       ↓
SQLite数据库 → 按期冻结预测 / 核验 / 训练轨迹
       ↓
同一次工作流提交数据、发布site静态快照
       ↓
所有访客只读同一data.json，不本地推算
```

数据库在 `database/tom.sqlite`；按期JSON在 `database/forecasts/`。SQL触发器禁止UPDATE/DELETE已冻结预测。相同输入重复运行不会新建预测或重复观察同一实际期。

网页发布数据是一份自包含JSON，带Snapshot ID、目标期号、digest、训练指纹。Pages/CDN或离线缓存允许显示明确标注的旧版；同一期不会因访客设备生成不同候选。

## 模型升级

保留原三种统计模型：Dirichlet长短窗、90期半衰指数频率、一阶Markov先验回退。新增真正的 **在线多项逻辑回归SGD**，使用148维特征（bias+49上期one-hot+49短窗频率+49长窗频率）；另加入均匀专家抑制无证据的过度拟合，Hedge使用此前真实对数损失自动分配权重。

每个新实际开奖都执行“先预测/计分，再观察标签/更新SGD、统计量和Hedge权重”；权重矩阵、训练指纹、traceHash与逐期事件存入数据库。断次后从已存状态继续；经维护者审核的历史更正会触发重放，已冻结预测仍不改。

## 实测比较，不是命中承诺

同一最近365期逐期回测：

- 旧版融合logLoss：3.936820。
- 新版融合logLoss：约3.891079。
- 独立均匀基准logLoss：3.891820。

logLoss越低越好。新版比旧版误差更低，与均匀基准差距极小；这只是同一历史区间的描述性结果，未证明显著或可持续预测优势。未来自动训练不保证每期更准。页面公开各模型全部层级成绩，不用单个较高命中层宣传稳定能力。

初始2,372期源数据含已知异常标注；不验证该站开奖真实性。来源按用户指定，不称具有运营方归属认证的“官方”。原始openTime无时区声明，业务配置按UTC+8解释，预计每日21:32:32，倒计时显著标预计。

## 原冻结结果兼容

原发布种子第2026323期原样入库，仍使用其原version、候选和digest；不因新模型而覆盖。新模型只对以后未锁定且仍未到截止的目标生效。旧种子生成时间不是公开时间证明，不计中央已验证前瞻成绩。

实时成绩要求：中央生成、生成早于实际开奖、成功Pages部署回执早于实际开奖、目标与digest相符。历史回测、导入预测、迟到记录均分开展示。

## 本地运行

Python3.12，仅标准库；网页无CDN或生产Node依赖。

```bash
python3 -m scripts.pipeline --offline
python3 -m scripts.verify
python3 -m http.server 8000
```

浏览器打开 `http://127.0.0.1:8000/site/`。

同步指定来源：

```bash
python3 -m scripts.pipeline
```

只在数据变化时训练，网络错误或冲突不覆盖已确认记录；来源异常进入audit/冲突表。新前向期有缺口时阻断错误向前发布。

## 测试

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
npm install --prefix .test-tools jsdom@26.1.0
node --test tests/test_site.cjs
python3 -m scripts.verify
```

UI测试在Node/jsdom执行，像素级真机浏览器视觉另需部署后检查。GitHub Actions／Pages尚未在用户账号实际启用，打包成功不代表已上线。

## 数据权限

访客没有写库入口，不接收访客上传预测，不把浏览器缓存当权威账本。仓库维护者仍掌握提交权限，SQLite与digest不等同于不可篡改第三方时间戳。数据库公开下载，别存秘密。

运行中请保留仓库数据库；Actions cache不是数据库。每次部署从同一个已提交中央快照导出artifact，部署失败后可重跑，不强推或合并二进制数据库。

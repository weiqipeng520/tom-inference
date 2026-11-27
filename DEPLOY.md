# 手机部署到GitHub：Tom推演系统

这次不再是只上传一个HTML。系统包含中央SQLite数据库、训练代码、网页和定时工作流。网页只读取统一发布结果，访客不再各自生成预测。

## 推荐：手机“两文件安装”

交付目录中有两个直接上传用的文件：

1. `tom-repository.zip`：中央数据库、训练程序和网页。**保持ZIP原样上传，不用手机逐个传文件夹。**
2. `tom-workflow.yml`：在GitHub网页创建工作流时粘贴其全部内容。

### 第一步：准备公开仓库

- 手机浏览器登录 https://github.com/new
- 仓库名推荐 `tom-inference`，也可继续用之前的仓库。
- 选择 **Public**；开启 **Add README** 后创建。
- 以下教程假设主分支叫 **main**。
- 若手机看不到设置或文件按钮，开启浏览器“电脑版网站”。

### 第二步：上传ZIP

进入仓库，点 **Add file → Upload files**，选择 `tom-repository.zip`，提交到main。

仓库根目录必须直接看到这个文件名，不要改名，不用上传整个外层交付ZIP。GitHub自己不会解压ZIP，下面的安装工作流会自动检查路径并解压。

### 第三步：建立唯一工作流

进入 **Add file → Create new file**，文件名填：

```text
.github/workflows/tom.yml
```

用文本查看器打开本次提供的 `tom-workflow.yml`，复制**全部内容**，粘贴到GitHub编辑框，提交。

注意：工作流内容从 `name:` 开始，直接粘贴YAML，不要加Markdown的三个反引号。

第一次提交可能先出现Pages未开启导致的红色失败，不影响已保存数据库；完成下面设置后手动再运行即可。

### 第四步：配置权限和Pages

仓库 **Settings → Actions → General → Workflow permissions**：

- 选择 **Read and write permissions**。
- 点击Save。

仓库 **Settings → Pages → Build and deployment → Source**：

- 选择 **GitHub Actions**。
- 不是旧教程的Deploy from a branch；本系统会在同一次Actions里提交中央数据并部署。
- Custom domain留空，不需要买域名。

若仓库有main分支保护，需确保机器人可提交数据；默认新公开仓库通常没有分支保护。如果规则禁止工作流push，先按仓库规则允许这条数据提交路径，再重新运行，别强推覆盖数据库。

### 第五步：运行首次安装

进入仓库 **Actions → Tom · 训练与统一发布 → Run workflow → main → Run workflow**。

流程会依次：

1. 发现程序尚未解压时，从根目录ZIP安装代码和初始数据库；
2. 执行回归测试；
3. 同步指定数据源，读取已完成开奖；
4. 新开奖才训练，已有预测仍保持冻结；
5. 把数据库及JSON快照提交回main；
6. 部署site目录到Pages；
7. 保存实际成功公开部署回执。

等 `更新数据库与训练`、`发布 GitHub Pages`、`保存已公开部署回执` 都变绿。

**地址示例：**

```text
https://你的GitHub用户名.github.io/tom-inference/
```

以Settings → Pages显示的Visit site地址为准。初次发布和CDN传播会需要几分钟。部署尚未执行之前，这只是预期地址，不代表已上线。

## 定时自动化

定时规则采用UTC写法，折合北京时间每天：

- **21:37 至 22:57**：每 10 分钟安排一次检查；
- **23:17、次日00:17**：源数据延迟时补查；
- **08:17**：次日恢复检查。

指定来源默认每日21:32:32开奖，倒计时仍明确标“预计”。GitHub定时任务可能延迟，不是秒级实时服务；来源变更时间时需相应调整。

每次运行都会查缺失新期，没有新数据不重复训练、也不改同期预测。漏过的历史只补入训练，**不会补造已开奖前的公开预测成绩**。

公开仓库长期无活动时，GitHub可能停用定时工作流；遇到停用提示需在Actions里重新启用。公开仓库标准GitHub托管runner通常免费，私有仓库额度和收费依账户计划而定，费用以GitHub实际页面为准。

## 普通完整仓库上传方式

完整仓库包中有：

```text
.github/workflows/tom.yml
scripts/
models/
site/
database/
seed/
tests/
README.md
DEPLOY.md
.gitignore
```

若用电脑Git，可解压后把这些内容放入仓库根目录并提交，保持隐藏的 `.github` 目录。Pages同样选GitHub Actions。已有完整程序时，工作流自动跳过ZIP安装步骤。

## 如何确认全站同一结果

- 打开网页，在“发布与数据”查看 **Snapshot ID**。
- 在“冻结候选”的核验区查看 **目标期号＋Forecast digest**。
- 两台设备读取同一个Snapshot ID时，数据内容相同；同一期已冻结digest也保持相同。
- Pages/CDN传播和离线缓存可能短暂让某人看到旧快照，页面会显示发布版本、时间和离线状态。旧快照不会在浏览器生成另一套预测。

## 重要更新方式

- 不再只替换首页HTML；程序、数据库和工作流需要一起保留。
- **首次成功安装后，不要反复上传旧数据库覆盖仓库中的新数据库。**
- 后续升级只提交需要变化的程序／界面文件，保留 `database/tom.sqlite` 和已冻结预测JSON。
- 数据库和训练记录是公开数据；不要把GitHub令牌、密码或私人信息写入其中。工作流使用GitHub自动提供的 `GITHUB_TOKEN`，不需要给网页填写密钥。
- 修改源数据时需要维护者审核更正；正常采集发现同期开奖冲突会隔离，不自动改写。更正脚本保留旧值并重放模型，原预测仍不改。

## 失败排查

| 看到的情况 | 检查位置 |
|---|---|
| 403 / push denied | Settings → Actions → Workflow permissions；main保护规则 |
| Pages not enabled | Settings → Pages → Source选GitHub Actions，回到Actions重跑 |
| data.json 404 | 是否完整部署site目录，别把repo根目录当site artifact |
| ZIP not found | `tom-repository.zip`是否原名放在仓库根目录 |
| Commit成功、Deploy失败 | 修好Pages配置后手动重跑；无新开奖也会再次部署现有快照 |
| 页面仍旧版本 | 对照Snapshot ID和发布时刻，刷新并等待CDN传播 |
| 来源接口失败 | Actions运行日志与页面warnings；保留旧预测，不生成猜测数据 |
| 工作流两次并发 | 固定concurrency串行处理，不同时写SQLite；若push遇新提交会明确失败，更新最新分支后重跑 |

## 官方参考

- https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages
- https://docs.github.com/en/actions/concepts/security/github_token
- https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onschedule

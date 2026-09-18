# radiumwmpf-versions

自动收集微信 Windows 版 RadiumWMPF 小程序容器插件（`WeChatAppEx.exe` 所在组件）的历史版本包，存档到 GitHub Release。

**数据来源**（微信客户端硬编码的 XPlugin 更新配置，与 `plugin_info.ini` / 本地 `xwechat\xplugin\Plugins\` 对应）：

| 来源 | 配置 | 说明 |
|------|------|------|
| `uni4` | `https://dldir1v6.qq.com/weixin/Universal/Windows/XPlugin/updateConfigUniWin.xml` | 微信 4.x（UniWeChatWin 新架构，4.1+） |
| `win3` | `https://dldir1.qq.com/weixin/Windows/XPlugin/updateConfigWin.xml` | 微信 3.x 经典架构 |

## 工作方式

GitHub Action（`.github/workflows/collect.yml`）每天定时运行 `scripts/collect.py`：

1. 拉取两份更新配置，按 `configVer` 存档到 `configs/`（保留配置演变历史）；
2. 解析出 RadiumWMPF 全量包条目（build / semver / fullurl / md5）；
3. 与 Release 现有 tag（`RadiumWMPF-<build>`）对比：
   - 没有 → 下载 zip、校验 md5、创建 Release 并上传；
   - 有但 asset 缺失 → 只补传；
   - 有 → 忽略；
4. 更新 `versions.json` 索引并提交回仓库。

只收**全量 zip**（配置里 `fullurl`），增量 patch 不下载（信息记录在配置存档里）。
注意：随主程序分发的版本（如 4.1.15.9 自带的 25710，`RadiumWMPF.bin`）不在这两份配置里，本仓库收不到，需解对应主程序安装包。

## 本地使用

```bash
python scripts/collect.py --dry-run      # 只解析打印, 不下载
python scripts/collect.py --skip-upload  # 下载+校验到 downloads/, 不动 Release
python scripts/collect.py                # 全流程(需 gh CLI + GH_TOKEN)
```

无第三方依赖（标准库 + curl + gh）。

## 手动触发

Actions → collect → Run workflow（`workflow_dispatch`）。
GitHub 的 schedule 在仓库 60 天无提交活动后会被自动禁用，收到提醒邮件后手动触发一次即可重新激活。

## 合规说明

RadiumWMPF 版权归腾讯所有。本仓库仅作版本留档用于测试

## 免责声明

本仓库及自动化脚本仅用于个人学习、技术研究和软件兼容性测试，不作任何商业用途，
不提供任何形式的明示或默示保证。仓库内归档的软件组件版权归腾讯（Tencent）所有，
本仓库与腾讯公司无关，未获得腾讯公司任何授权或背书。

任何组织或个人不得将本仓库内容用于商业分发、二次售卖或其他违法违规用途；
因下载、使用或传播本仓库内容而产生的一切后果由行为人自行承担。

如有侵权或合规问题，请通过 GitHub Issue 或仓库所有者主页显示的联系方式告知，
确认后我们将第一时间删除相关内容并下架对应 Release。


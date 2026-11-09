# Autovisor ThreePlatform

智慧树、学习通、Polymas 三平台课程浏览器工具。当前版本 **3.18.4+mixue.3**，基于 [CXRunfree/Autovisor](https://github.com/CXRunfree/Autovisor)。本仓库提供完整源码、测试、资源和操作说明；Windows 发布包提供可直接启动的程序。

> **使用前请阅读[免责声明与使用风险说明](DISCLAIMER.md)。相关辅助功能可能不符合学校或平台规则，不能替代本人学习与独立作答。**

## 二次开发与许可

本项目是在 **CXRunfree/Autovisor 基础上的三平台扩展和二次开发**，不是从零独立编写。维护者账号为 [OxMianBaoxO](https://github.com/OxMianBaoxO)，上游与第三方作者保留各自版权。

以 `3.18.4+mixue.2` 与借鉴源码基线 `5c715623030877d1daac0eaa14ac91f0abb2d003` 对比，按核心 Python 功能代码的非空行统计：

| 来源 | 非空行数 | 占 mixue.2 核心 Python 代码 |
| --- | ---: | ---: |
| 原项目直接沿用 | 3,118 | 约 74% |
| 本项目后续新增或改写 | 1,104 | 约 26% |

统计范围为 `Autovisor.py`、`GUI.py` 与 `modules/*.py`；不含空行、测试、构建脚本、文档、字体表和第三方 JS 资源。注释行计入非空行，逐行文本匹配统计保留与变更，因此这是代码沿用比例，**不是严格的原创率或版权份额**。官方 `3.18.4` 标签与上述基线的差异仅涉及说明文档与图片，不影响这项 Python 统计。

后续扩展主要包括学习通适配、Polymas 适配、三平台统一调度、蜜雪接入和打包发布；在 mixue.2 统计时另外新增约 822 行非空测试代码。蜜雪及字体解码等部分引用或改编第三方成果，不能全部认定为本维护者独立原创，详见 [来源声明](NOTICE.md) 和 [第三方声明](resources/mixue/NOTICE.md)。

**继续采用 MIT 许可证，允许商用、修改和再分发。分发软件副本或重要部分时，须保留相应版权及许可声明。** 上游许可证全文保留在 [LICENSE](LICENSE)，第三方组件依各自附带许可使用。

## 下载和使用

1. 到 [Releases](https://github.com/OxMianBaoxO/Autovisor-ThreePlatform/releases) 下载 `Autovisor-3.18.4+mixue.3-Windows-x64.zip`。GitHub 的 `Source code` 下载仅含源码，没有 Windows 程序。
2. 完整解压到可写文件夹，保留 `internal`、`resources`、`data`，不要只复制 exe。系统要求 Windows 10/11 x64，已安装 Edge 或 Chrome。
3. 双击 `Edit-config.cmd`，在 `config.ini` 最下方 `[course-url] URL1` 填入实际课程学习页完整 HTTPS 地址并保存。账号密码可以留空。
4. 双击 `Start.cmd`，在程序新开的浏览器里扫码或登录。其他浏览器或内置浏览器的登录不会自动同步到这个窗口。
5. 保留运行窗口与浏览器，电脑不要休眠。同一文件夹不要同时运行多个实例。按 Ctrl+C 或关闭运行窗口停止，重开后按平台进度继续。

默认 Edge，使用 Chrome 时将 `driver = Edge` 改为 `driver = Chrome`。不需要安装 Python。完整设置、登录、操作和排错见 [使用说明](DISTRIBUTION.md)。

## 可以处理什么

| 平台 | 内容和目录 | 课中交互与练习辅助 | 速度 |
| --- | --- | --- | --- |
| 智慧树 | 原版支持的共享课、融合课、翻转课；按平台进度筛选、续播和切换视频 | **课中弹窗自动处理（不保证正确）**：旧版按官方 3.18.4 尝试前两个选项并关闭弹窗；原版不支持的新版页面仍等待人工处理 | 0.5–1.8，默认 1 |
| 学习通 | 视频、电子书、原生播放控制和任务完成标记 | 默认**答案提示**；**自动填答**和自动提交须手动开启。独立蜜雪题库／AI、字体解码及面板；第三方服务尚未真实 Key 验证 | 原生 1 / 1.25 / 1.5 / 1.75 / 2 |
| Polymas | AI 教学中心视频目录、进度和绿色完成标记 | 锁定、验证或人工任务等待用户处理 | 1 |

智慧树与学习通是两套课中交互与练习辅助流程。智慧树使用 `modules/tasks.py` 的上游 `skip_questions`；学习通使用 `modules/mixue.py` 和 `resources/mixue/helper.js`。智慧树任务限制在智慧树课程域名内，不操作学习通或 Polymas 页面。

以上是代码支持范围，不代表所有学校课程均已真实验证。视频播完不等于课程完成，以平台任务标记为准。安全验证仍由用户完成。不会安装开机启动、守护重启、定时监控或休眠计划。

## 配置入口

模板见 [config.ini.example](config.ini.example)。账号段可以留空；专用账号段分别为 `[zhihuishu-account]`、`[chaoxing-account]`。`URL1`、`URL2`、`URL3` 可混用平台，逐门处理，上一门出错会停止队列。

| 配置 | 含义 |
| --- | --- |
| `driver` / `EXE_PATH` | Edge 或 Chrome；浏览器路径通常留空，自定义时不加引号 |
| `limitMaxTime` | 每门课运行分钟数，0 表示不限时 |
| `limitSpeed` / `soundOff` | 播放倍速／是否静音，倍速按平台范围处理 |
| `chaoxingVideosOnly` | 可选，True 时学习通只播放视频；其他任务不因此视为完成 |
| 蜜雪 `enabled` / `apiKey` | 模块开关／蜜雪服务 Key |
| `useTiku` / `useAI` / `model` | 题库、AI 回退和服务支持的模型 |
| `hintsOnly` | 答案提示，默认 True，只展示、不点选或填入 |
| `autoAnswer` | 自动填答，默认 False；需手动开启并关闭答案提示 |
| `autoSubmit` | 自动提交，默认 False；需另行手动开启，且自动填答已开启、答案提示已关闭 |
| `decrypt` | 本地字体解码 |

学习通蜜雪的用法、面板、F9 快捷键、接口和限制见 [蜜雪说明](MIXUE_UPDATE.md)。查询会将题目、选项及 Key 发送给 `tk.mixuelo.cc`。未知题型、缺少明确答案的题目留给用户处理；不生成随机答案。蜜雪真实题库／AI 服务尚未验证可用。

## 默认模式与开启风险

新版本学习通默认 `hintsOnly=True`、`autoAnswer=False`、`autoSubmit=False`。点击“查询本页参考答案”仅展示提示；即使单独关闭答案提示，未开启自动填答时也不会点选或填入。答案提示开启时，填答和提交均不执行。

自动填答须用户明确开启 `autoAnswer=True` 并关闭 `hintsOnly`；参考答案可能错误，自动点选或填入可能影响成绩和课程记录。自动提交须另外开启 `autoSubmit=True`，且自动填答已开启；提交可能无法撤回。两者均可能违反学校或平台规则，使用前须确认授权并阅读[免责声明](DISCLAIMER.md)。新默认不会强制覆盖旧配置中已显式填写的值，升级时请自行检查旧配置。

## 常见问题

- 登录过期：在程序浏览器重新登录；不要把旧日志的错误当成本轮状态。
- 卡在题目：先辨认平台。智慧树新版／不支持页面仍需人工处理；学习通检查蜜雪开关、Key、查询错误及自动填答开关。
- 浏览器启动失败：检查 Edge/Chrome 安装、driver 与 EXE_PATH，运行 `Check-environment.cmd`。
- 找不到目录：填写有访问权限、能看到视频和章节目录的实际学习页，不要填平台首页或课程宣传页。不同学校页面可能需要适配。
- 进度问题：查看 `logs/Log*.txt`；学习通还可看 `logs/chaoxing-status.json`。程序按平台完成标记筛选，不伪造完成记录。
- 分享与反馈：不要上传已运行的文件夹。移除账号、Cookie、Key、私人截图、日志与课程访问参数。

## 源码、测试和打包

需要 Python 3.10–3.13。Windows 发布版不需要 Python；系统默认的 Python 3.14/3.15 不在源码声明的兼容范围内。

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e .
Copy-Item config.ini.example config.ini
# 编辑课程地址后运行
.venv\Scripts\python Autovisor.py --config config.ini
# 本地回归和打包
.venv\Scripts\python -m unittest discover -s tests -v
.venv\Scripts\python -m tests.polymas_offline_check
.venv\Scripts\python -m tests.native_controls_browser_check
.venv\Scripts\python -m pip install pyinstaller
.venv\Scripts\python package_release.py --output releases
```

浏览器测试需要本机 Chrome/Edge，测试页面是本地模拟内容。发布脚本运行测试、构建 exe、生成空白配置与源码快照，再检查冻结程序和 ZIP。源码 GUI.py 是上游可选界面，需要 gui 额外依赖；Windows 发布包使用控制台入口。保留上游 macOS 启动脚本，本改版未验证 macOS 三平台兼容性。

## 原始项目与修复记录

- [官方 3.18.4 发布页](https://github.com/CXRunfree/Autovisor/releases/tag/3.18.4)，原始文件 `Autovisor-3.18.4-windows-amd64.zip`。
- 官方原始 ZIP SHA-256：`11cea9e9ac1d9f122041cd82c7e6befcc891487396f16e82386f06cf2f8ea32d`。
- 三平台改版基线：`5c715623030877d1daac0eaa14ac91f0abb2d003`。
- mixue.2 从官方 3.18.4 标签恢复智慧树旧版课中弹题任务，并增加平台隔离；学习通蜜雪和 Polymas 代码保留各自行为。
- [上游原始说明（历史）](docs/UPSTREAM_README.md)，改版功能以本页和 DISTRIBUTION.md 为准。
- [验证范围](docs/VALIDATION.md)；每份发布包在 release-info.json 记录实际构建检查结果。
- [MIT 许可证](LICENSE)及[第三方来源](resources/mixue/NOTICE.md)。这是本地修改发行版，非上游作者官方发布。

公开仓库及发行包不含真实课程地址、账号密码、Cookie、Key、私人日志和浏览器资料。

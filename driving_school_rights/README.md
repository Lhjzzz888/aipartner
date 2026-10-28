# 山东学车权益助手

同仓库独立运行的 Streamlit 应用，面向山东驾培学员的合同、退费、培训安排和教练服务争议。原贵金属助手入口不变。

首页可以直接像聊天一样输入问题，也可点击“没有合同”或“没留证据”的示例问题。配置 API Key 后，发送文字问题会直接调用 DeepSeek；未配置或服务暂不可用时会明确标示并给出基础指引。合同、聊天截图等文件是可选项，文件摘录需由用户校对并确认后才发送。连续追问会带入本次会话最近三条用户问题；刷新或清除会话后不保证继续保留。AI 只可引用本地已核验的法规条目，实际返回给用户的法规标题、条文摘要和链接由本地数据覆盖模型输出。

## 本地运行

```powershell
python -m pip install -r requirements.txt
$env:DEEPSEEK_API_KEY = "在本机环境变量中配置"
python -m streamlit run driving_school_rights/app.py
```

也可以先不配置 API Key 查看材料整理、法规来源、协商路径和官方联系方式；分析功能只有服务端配置密钥后才可用。不要把真实密钥提交到代码仓库或发在聊天中。

部署时需安装仓库根目录 `packages.txt` 中列出的系统包（Tesseract OCR 与简体中文、英文语言包），并将仓库根目录作为 Streamlit 工作目录。平台环境变量支持：

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `DEEPSEEK_API_KEY` | 无 | 必需；仅服务端环境变量/Secrets |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | DeepSeek OpenAI 兼容接口地址 |
| `DEEPSEEK_MODEL` | `deepseek-flash` | 模型名；请在部署前核对 DeepSeek 当前支持列表 |
| `MAX_UPLOAD_MB` | `10` | 单文件大小上限 |
| `MAX_PDF_PAGES` | `30` | PDF 页数上限 |
| `MAX_TEXT_CHARS` | `15000` | 单份材料提取字符上限 |
| `MAX_CALLS_PER_SESSION` | `5` | 每个会话的分析调用上限 |
| `MAX_CALLS_PER_DAY` | `100` | 当前 Python 进程每日调用上限 |

## 数据和隐私

- 支持 PDF、DOCX、TXT、PNG、JPG；解析在内存中执行，不把上传原文件写入项目目录。
- OCR 识别内容可能有误，用户需校对；发送前显示可编辑摘录，并由用户确认。
- 当前会话状态在用户清除或会话终止前保留于 Streamlit 会话内存。托管平台的日志、内存快照和第三方 API 数据处理策略应在上线前逐项核验。
- 不向日志写入 API Key、材料文本或模型输出。每日限额是单进程内存计数，多实例部署时不能代替 DeepSeek 账户侧预算/限额。
- 法律条目含官方来源和核验日期，但法规可能变化；城市级专属号码未核验时只展示已核验的通用官方渠道，并明确提示。
- 面向中国境内公众上线前，须核实生成式人工智能应用的属地登记/备案及模型公示要求、互联网服务相关手续与用户投诉处理要求；义务取决于服务形态和主管部门认定，本项目代码不构成合规结论。
- 文书均为待核对草稿，未知信息保留占位符；发送前请检查事实、金额、合同约定及法律适用性。

## 测试

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -p no:cacheprovider -q
```

测试使用本地 OCR mock 和 DeepSeek mock，不会调用真实模型或上传真实个人材料。实际 OCR 需要系统安装 Tesseract。


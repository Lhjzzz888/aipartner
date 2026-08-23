import streamlit as st
import os
from openai import OpenAI
from datetime import datetime
import json
import logging
import yfinance as yf   # 实时价格获取

logging.basicConfig(level=logging.INFO)

st.set_page_config(
    page_title="AI",
    page_icon="🪙",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        'Get Help': 'https://www.deepseek.com/',
        'Report a bug': "https://www.doubao.com/",
        'About': "我的名字是财财金银分析助手!"
    }
)

# ---------- 会话管理函数 ----------
def generate_session_name():
    return datetime.now().strftime("%Y-%m-%d-%H-%M-%S")

def save_session():
    if st.session_state.current_session and st.session_state.messages:
        session_data = {
            'nick_name': st.session_state.nick_name,
            'nature': st.session_state.nature,
            'current_session': st.session_state.current_session,
            'message': st.session_state.messages
        }
        if not os.path.exists('sessions'):
            os.mkdir('sessions')
        with open(f'sessions/{st.session_state.current_session}.json', 'w', encoding='utf-8') as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)

@st.cache_data(ttl=60)
def load_sessions():
    session_list = []
    if os.path.exists("sessions"):
        for filename in os.listdir("sessions"):
            if filename.endswith(".json"):
                session_list.append(filename[:-5])
    session_list.sort(reverse=True)
    return session_list

def load_session(session_name):
    try:
        with open(f'sessions/{session_name}.json', 'r', encoding='utf-8') as f:
            session_data = json.load(f)
            st.session_state.messages = session_data['message']
            st.session_state.nick_name = session_data['nick_name']
            st.session_state.nature = session_data['nature']
            st.session_state.current_session = session_name
    except Exception as e:
        st.error(f"加载会话信息失败: {e}")

def delete_session(session_name):
    try:
        file_path = f'sessions/{session_name}.json'
        if os.path.exists(file_path):
            os.remove(file_path)
            if session_name == st.session_state.current_session:
                st.session_state.messages = []
                st.session_state.current_session = None
            st.cache_data.clear()
    except Exception as e:
        st.error(f"删除会话失败: {e}")

# ---------- 实时价格获取 ----------
def get_gold_price():
    """获取黄金参考价格（基于GLD ETF估算），失败返回None"""
    try:
        gld = yf.Ticker("GLD")
        hist = gld.history(period="1d")
        if hist.empty:
            return None
        gld_close = hist['Close'].iloc[-1]
        return gld_close * 10   # 1份GLD≈1/10盎司黄金
    except Exception as e:
        logging.error(f"获取金价失败: {e}")
        return None

# ---------- 完整系统提示词（已包含通俗化要求） ----------
system_prompt = '''
你是{nick}，一位{nature}的贵金属定价资深策略分析师。你的分析底层逻辑基于**三因子定价模型**：黄金以“实际利率”为唯一核心锚，白银在此基础上叠加“工业需求弹性”，而“资金拥挤度”仅作为赔率修正项介入决策。

**重要输出要求**：所有分析结论必须用**通俗易懂的语言**向普通投资者阐述，避免堆砌专业术语，但核心逻辑必须严谨、数据必须有据可查。

针对黄金和白银的分析，你必须严格执行以下【三步聚焦法则】。

**数据公信力铁律**：
- 所有结论性数据（TIPS利率、PMI、CFTC持仓、ETF持仓、金银比）必须标注具体数据来源（机构名称+发布日期）。
- 禁止使用“据市场消息”、“据了解”等模糊表述。
- 无法获取的实时数据项，必须明确标注“[数据待核实]”，**严禁AI依据历史数据填充或估算**。

---

### 第一步：黄金的定价锚——实际利率（方向判断的充分必要条件）

**核心逻辑**：黄金作为无息资产，其持有成本等于实际利率（名义利率－通胀预期）。实证上，1971年至今黄金价格月度变动约80%可由该变量解释。

**必须完成的数据抓取与计算项（共4项，缺一不可）**：

1. **当前实际利率值**：
   - 抓取美国10年期通胀保值国债（TIPS）收益率，精确至小数点后两位（单位：%）。
   - 来源指定：Bloomberg代码 `USGG10YR Index` 或 美国财政部官网Daily Treasury Real Yield Curve。

2. **历史分位数定位**：
   - 计算当前TIPS利率在**近20年（2006年至今）** 数据区间内的历史百分位。
   - 分位阈值判定：< 20%分位定义为“极低”；20%-80%定义为“中性区间”；> 80%定义为“极高”。

3. **边际弹性系数校准（关键）**：
   - 抓取**最近30个交易日（T日收盘 vs T-30日收盘）** 的黄金现货价格变动（ΔGold，单位：美元/盎司）与TIPS利率变动（ΔTIPS，单位：bp）。
   - 计算弹性系数 β = |ΔGold / (ΔTIPS × 10)|，即TIPS每变动10bp所对应的金价反向波动幅度（美元/盎司）。
   - **输出格式示例**：“近30日校准弹性为 TIPS每+10bp → 金价约 -XX美元/盎司”。

4. **预期差定位（市场一致性检验）**：
   - 抓取CME FedWatch Tool当前定价所隐含的**2026年底联邦基金利率区间**（或累计降息/加息bp数）。
   - 对比Bloomberg发布的**机构经济学家一致预期中位数**（或高盛/摩根大通最新预测）。
   - 若市场定价与机构预期存在显著偏离（≥25bp），在分析中明确标注“预期差方向”及对TIPS利率的潜在修正方向。

**分析输出规范**：
- **方向结论**：TIPS趋势向下 → 黄金看多；趋势向上 → 黄金看空；周度波动≤5bp → 判为区间震荡，无趋势性机会。
- **置信度标记**：若TIPS利率处于近20年历史后20%分位，标记为“高置信度利多”；若处于前20%分位，标记为“高置信度利空”。

---

### 第二步：白银的弹性乘数——工业需求景气度（跑赢/跑输黄金的判定依据）

**核心逻辑**：白银走势方向与黄金一致，但弹性由工业需求决定。当前白银工业需求占比已超过总需求的55%，其中光伏用银是边际增量最大的单项。

**必须完成的数据抓取与计算项（共3项）**：

1. **全球制造业景气度加权值**：
   - 抓取**美国ISM制造业PMI**（来源：ISM官网）与**中国官方制造业PMI**（来源：国家统计局）。
   - 计算加权PMI = 0.5 × 美国ISM + 0.5 × 中国官方（输出保留一位小数）。
   - 趋势判定：对比**前三个月加权PMI均值**，判断当前值较三个月均值是“上升（>+0.5）”、“下降（<-0.5）”还是“持平（±0.5以内）”。

2. **金银比（Gold/Silver Ratio）**：
   - 计算金银比 = 伦敦现货金价 ÷ 伦敦现货银价。
   - 抓取其**近5年历史分位数**（来源：Wind或Bloomberg）。
   - 分位阈值判定：> 80%分位 = 白银相对黄金被显著低估；< 20%分位 = 白银相对被显著高估。

3. **白银弹性方向综合判定规则**：
   - **跑赢黄金的条件**（同时满足）：加权PMI > 50 **且** 趋势判定为“上升”。
   - **跑输黄金的条件**：加权PMI < 50 **且** 趋势判定为“下降”。
   - **中性/跟随条件**：PMI在50附近震荡，或方向与金银比分位信号冲突时，判定白银弹性与黄金持平，无超额收益机会。
   - **光伏用银校正条款**：仅当最新全球光伏装机量预估同比增速**较上季度预测偏离超过±5个百分点**时，作为额外修正因素纳入结论文字中。否则视为已知常量，不参与核心判定。

---

### 第三步：资金拥挤度与赔率校验（不改变方向，但修正仓位与盈亏比）

**核心逻辑**：资金面不决定趋势方向，但决定了当前价格水平下的风险收益比（赔率）。

**必须完成的数据抓取项（共2项）**：

1. **CFTC非商业净多头持仓分位数**：
   - 抓取黄金非商业（投机）净多头持仓合约数，及该数值在**近5年数据区间**内的历史百分位。
   - 来源指定：CFTC官网每周五发布的《Commitments of Traders》报告（COT）。
   - 分位阈值判定及操作映射：
     - > 80%分位 → 标记“极度拥挤（低赔率）”，多头仓位上修至“轻仓/谨慎”。
     - 20%-80%分位 → 标记“中性（正常赔率）”，维持基准仓位。
     - < 20%分位 → 标记“极度冷清（高赔率）”，多头仓位可上修至“超配/积极”。

2. **黄金ETF（SPDR GLD）持仓动量**：
   - 抓取GLD最新持仓总量（吨），并计算**最近30个自然日**的累计持仓变化（吨）。
   - 判定阈值：累计变化 > +15吨 = 确认多头趋势；累计变化 < -15吨 = 确认空头趋势；介于±15吨之间 = 资金面无明确方向指引。

---

### 最终综合决策矩阵（强制执行）

将以上三步结论填入下表，并依据规则生成最终策略：

| 分析步骤 | 核心变量 | 当前数据与判定 | 数据来源 |
| :--- | :--- | :--- | :--- |
| **第一步** | TIPS实际利率 | [数值]% / [趋势：上升/下降/震荡] / [置信度] | [来源+日期] |
| **第二步** | 加权PMI | [数值] / [趋势：上升/下降/持平] | [来源+日期] |
| **第三步-黄金** | CFTC黄金净多头分位 | [数值]% / [拥挤度判定] | [来源+日期] |
| **第三步-白银** | 金银比历史分位 | [数值]% / [被低估/高估/中性] | [来源+日期] |

**决策规则**：
- **黄金最终方向**：直接继承第一步TIPS的判定结论（下降→看多；上升→看空；震荡→观望）。
- **黄金仓位调整**：根据第三步拥挤度判定，在基准仓位基础上调整（低赔率→减仓；高赔率→加仓）。
- **白银相对方向**：第二步判定跑赢黄金 → 优先配置白银ETF或银矿股；判定跑输黄金 → 优先配置黄金资产或做空金银比。
- **白银仓位调整**：如果第一步看多黄金且第二步判定白银跑赢 → 最强配置信号；如果第一步看空黄金且第二步判定白银跑输 → 最强做空信号。

---

### 输出格式要求

**严格按以下三级标题结构输出（总字数1000-1800字），但语言必须通俗易懂，避免过度使用专业术语，要像给朋友解释一样清晰**：

### 一、核心结论（不超过150字）
- 黄金方向与关键支撑/阻力逻辑（一句话，用比喻或常识解释）。
- 白银相对弹性判断（跑赢/跑输/持平）及理由（一句话，用日常例子说明）。
- 综合策略评级（超配/中性/低配）及仓位提示（基于赔率，用百分比或“轻仓/重仓”表述）。

### 二、三因子数据面板（表格形式）
| 核心变量 | 当前数值 | 历史分位 | 趋势判定 | 数据来源 |
| :--- | :--- | :--- | :--- | :--- |
| TIPS实际利率 | X.XX% | X%分位 | 上升/下降/震荡 | XXX |
| 加权制造业PMI | X.X | - | 上升/下降/持平 | XXX |
| CFTC黄金净多头分位 | X% | X%分位 | 拥挤/中性/冷清 | XXX |
| 金银比 | XX.X | X%分位 | 银被低估/高估/中性 | XXX |
| GLD持仓30日变化 | +X吨 | - | 流入/流出/持平 | XXX |

### 三、策略建议与风险提示（用“大白话”写）
- **黄金策略**：入场参考区间（基于β弹性反推TIPS利率对应的价格区间）、止损参考（基于ATR%）、目标位（基于当前TIPS利率向历史均值回归的假设）。尽量用“如果价格跌到XXX，可以考虑买”这种句式。
- **白银策略**：若判定跑赢 → 建议做多金银比回归；若判定跑输 → 建议做空或观望。解释什么是“做多金银比”用一句话。
- **风险清单（仅列前3大尾部风险）**：
  1. [具体事件] → 对TIPS利率的潜在冲击方向与幅度（用“利率可能会涨/跌多少”表达）。
  2. [具体事件] → 对工业需求的潜在冲击方向。
  3. [具体事件] → 对资金拥挤度的突发逆转风险。

### 四、数据来源与验证状态
- 已验证数据项（来源+发布时间）。
- 待核实数据项（标注“近期数据尚未发布，待后续更新”）。

---

**性格设定**：{nature}、数据洁癖、坚持“方向源于利率、弹性源于景气、仓位源于赔率”的三层决策链，不做模糊的“中性”建议（若确实无方向则明确建议“离场观望”）。

**执行指令**：用户提问后立即按上述三步框架生成分析。若用户仅问黄金或仅问白银，仍需完整执行第一步和第三步（黄金相关的数据项），第二步仅当问题涉及白银或金银比时才需完整展开。

**最后强调**：**所有分析结论必须用通俗易懂的语言输出，就像向非专业人士解释一样，避免堆砌术语，但核心逻辑必须严谨。**
'''

# ---------- 初始化状态 ----------
if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'nick_name' not in st.session_state:
    st.session_state.nick_name = '财财金银分析助手'
if 'nature' not in st.session_state:
    st.session_state.nature = '专业严谨'
if 'current_session' not in st.session_state:
    st.session_state.current_session = None

if st.session_state.current_session:
    st.text(f'Session ID: {st.session_state.current_session}')
for message in st.session_state.messages:
    st.chat_message(message['role']).write(message['content'])

# ---------- 创建客户端 ----------
api_key = st.secrets.get("DEEPSEEK_API_KEY", os.environ.get("DEEPSEEK_API_KEY"))
if not api_key:
    st.error("未找到 API Key，请在 secrets 或环境变量中设置 DEEPSEEK_API_KEY")
    st.stop()
client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

# ---------- 侧边栏 ----------
with st.sidebar:
    st.subheader('Control Panel')
    if st.button('新建对话', width='stretch', icon='🌐'):
        if st.session_state.current_session and st.session_state.messages:
            save_session()
        st.session_state.messages = []
        st.session_state.current_session = generate_session_name()
        save_session()
        st.rerun()

    st.text('会话历史')
    session_list = load_sessions()
    if not session_list:
        st.caption("暂无历史会话")
    for session in session_list:
        col1, col2 = st.columns([5, 1])
        with col1:
            if st.button(session, width='stretch',
                         type='primary' if session == st.session_state.current_session else 'secondary'):
                load_session(session)
                st.rerun()
        with col2:
            if st.button('', width='stretch', icon='🗑️', key=f'delete_{session}'):
                delete_session(session)
                st.rerun()

    st.subheader('ChatBot 配置')
    nick_name = st.text_input('昵称', placeholder='请输入昵称', value=st.session_state.nick_name)
    if nick_name:
        st.session_state.nick_name = nick_name
    nature = st.text_area('性格', placeholder='请输入性格', value=st.session_state.nature)
    if nature:
        st.session_state.nature = nature

# ---------- 消息输入 ----------
prompt = st.chat_input("请输入你的问题")
if prompt:
    st.chat_message("user").write(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    if not st.session_state.current_session:
        st.session_state.current_session = generate_session_name()

    # ---- 获取实时金价并注入 ----
    price = get_gold_price()
    if price is not None:
        price_msg = {
            "role": "system",
            "content": f"当前实时数据：国际现货黄金参考价格（基于 GLD ETF 估算）约为 {price:.2f} 美元/盎司，数据时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}（来源：GLD ETF 最新收盘价）。请务必基于此价格进行分析，不要使用内部训练数据中的历史价格。"
        }
    else:
        price_msg = {
            "role": "system",
            "content": "注意：实时金价获取失败，请基于你的内部知识给出分析，但需在回答中明确说明价格数据为历史参考而非实时行情。"
        }

    messages_for_api = [
        {"role": "system", "content": system_prompt.format(nick=st.session_state.nick_name, nature=st.session_state.nature)},
        price_msg,
        *st.session_state.messages
    ]

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages_for_api,
            stream=True
        )
        response_message = st.empty()
        full_response = ""
        for chunk in response:
            if chunk.choices[0].delta.content is not None:
                content = chunk.choices[0].delta.content
                full_response += content
                response_message.chat_message("assistant").write(full_response)

        st.session_state.messages.append({"role": "assistant", "content": full_response})
        save_session()
    except Exception as e:
        st.error(f"调用 AI 服务失败，请检查网络或 API 密钥。错误详情：{e}")
        logging.error(f"API 调用异常: {e}")
        st.session_state.messages.pop()  # 移除用户消息

import streamlit as st
import os
from openai import OpenAI
from datetime import datetime
import json
import logging
import urllib.request
import yfinance as yf   # 国际盘兜底数据源

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

# ---------- 融通金口径实时行情获取 ----------
# 数据源说明：融通金平台行情与上海黄金交易所现货/延期报价同步显示，
# 这里经由新浪财经行情接口获取同一基准价：
#   黄金 Au99.99 / Au(T+D)（元/克）、白银 Ag(T+D) / Ag99.99（元/千克），
#   纽约金银（美元/盎司）、美元指数、在岸人民币汇率；
# 并据此计算国内理论折算价、黄金升贴水与金银比。
# 任一单项失败只置 None 并逐级兜底，绝不虚构价格。

_SINA_QUOTE_CODES = {
    "au9999": "SGE_AU9999",   # 上金所黄金现货 Au99.99（元/克）
    "autd": "SGE_AUTD",       # 上金所黄金延期 Au(T+D)（元/克）
    "agtd": "SGE_AGTD",       # 上金所白银延期 Ag(T+D)（元/千克）
    "ag9999": "SGE_AG9999",   # 上金所白银现货 Ag99.99（元/千克）
    "intl_gold": "hf_GC",     # 纽约黄金（美元/盎司）
    "intl_silver": "hf_SI",   # 纽约白银（美元/盎司）
    "usdcny": "fx_susdcny",   # 美元/在岸人民币
    "dxy": "DINIW",           # 美元指数
}

_OZ_TO_GRAM = 31.1034768     # 1 金衡盎司 = 31.1034768 克
_GRAMS_PER_KG = 1000.0

def _to_float(text):
    """行情字段转 float；缺失值（如 '--'）返回 None。"""
    try:
        return float(text)
    except (TypeError, ValueError):
        return None

def _fetch_sina_quotes():
    """获取新浪财经行情原始数据，返回 {code: [字段,...]}；失败返回 {}。"""
    url = "https://hq.sinajs.cn/list=" + ",".join(_SINA_QUOTE_CODES.values())
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://finance.sina.com.cn",
    })
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read().decode("gbk", errors="ignore")
    except Exception as exc:
        logging.warning("新浪行情接口获取失败: %s", exc)
        return {}
    quotes = {}
    for line in raw.splitlines():
        if '="' not in line:
            continue
        try:
            code = line.split("=", 1)[0].replace("var hq_str_", "").strip()
            body = line.split('="', 1)[1].rsplit('"', 1)[0]
            quotes[code] = body.split(",")
        except Exception:
            continue
    return quotes

def _yfinance_fallback(ticker):
    """国际盘/汇率兜底数据源（yfinance），失败返回 None。"""
    try:
        data = yf.Ticker(ticker).history(period="1d")
        if data.empty:
            return None
        return float(data["Close"].iloc[-1])
    except Exception as exc:
        logging.warning("yfinance %s 获取失败: %s", ticker, exc)
        return None

@st.cache_data(ttl=60, show_spinner=False)
def get_market_quotes():
    """获取融通金口径行情快照；任何单项失败仅置 None，不影响其余字段。

    字段说明：
      au9999 / autd / agtd / ag9999   上金所现货与延期最新价（元/克、元/千克）
      *_prev                           对应品种昨收价
      intl_gold / intl_silver          纽约金银（美元/盎司）
      usdcny / dxy                     在岸汇率 / 美元指数
      domestic_theoretical             国际金价×汇率折算的理论国内金价（元/克）
      premium_pct                      黄金升贴水（%）：(国内 − 理论) / 理论 × 100
      gsr_intl / gsr_domestic          金银比（国际盘 / 国内盘）
      sge_time / intl_time             数据时间
    """
    quotes = {
        "au9999": None, "au9999_prev": None, "autd": None, "autd_prev": None,
        "agtd": None, "agtd_prev": None, "ag9999": None, "ag9999_prev": None,
        "intl_gold": None, "intl_silver": None, "usdcny": None, "dxy": None,
        "domestic_theoretical": None, "premium_pct": None,
        "gsr_intl": None, "gsr_domestic": None,
        "sge_time": None, "intl_time": None,
    }
    raw = _fetch_sina_quotes()

    # 上金所字段映射：最新价=idx3，昨收=idx9，行情时间=idx16
    def read_sge(key, price_idx=3, prev_idx=9, time_idx=16):
        fields = raw.get(_SINA_QUOTE_CODES[key])
        if not fields or len(fields) <= max(price_idx, time_idx):
            return
        price = _to_float(fields[price_idx])
        if price is None:
            return
        quotes[key] = price
        if prev_idx is not None:
            quotes[key + "_prev"] = _to_float(fields[prev_idx])
        quotes["sge_time"] = quotes["sge_time"] or fields[time_idx].strip()

    read_sge("au9999")
    read_sge("autd")
    read_sge("agtd")
    read_sge("ag9999")

    # 纽约金银字段映射：最新价=idx0，时间=idx6，日期=idx12
    gold = raw.get(_SINA_QUOTE_CODES["intl_gold"])
    if gold and len(gold) > 12:
        price = _to_float(gold[0])
        if price is not None:
            quotes["intl_gold"] = price
            quotes["intl_time"] = f"{gold[12]} {gold[6]}".strip()
    silver = raw.get(_SINA_QUOTE_CODES["intl_silver"])
    if silver and len(silver) > 12:
        price = _to_float(silver[0])
        if price is not None:
            quotes["intl_silver"] = price

    # 汇率 / 美元指数字段映射：最新值=idx1
    fx = raw.get(_SINA_QUOTE_CODES["usdcny"])
    if fx and len(fx) > 1:
        quotes["usdcny"] = _to_float(fx[1])
    dxy = raw.get(_SINA_QUOTE_CODES["dxy"])
    if dxy and len(dxy) > 1:
        quotes["dxy"] = _to_float(dxy[1])

    # ── 国际盘兜底：yfinance ──
    if quotes["intl_gold"] is None:
        fallback = _yfinance_fallback("GC=F") or _yfinance_fallback("GLD")
        if fallback is not None:
            # GLD 一份约等于 1/10 金衡盎司
            quotes["intl_gold"] = fallback * 10 if fallback < 1000 else fallback
            quotes["intl_time"] = "yfinance 最新收盘"
    if quotes["intl_silver"] is None:
        quotes["intl_silver"] = _yfinance_fallback("SI=F")
    if quotes["usdcny"] is None:
        quotes["usdcny"] = _yfinance_fallback("CNY=X")

    # ── 衍生计算：升贴水 / 金银比 ──
    if quotes["intl_gold"] and quotes["usdcny"]:
        theoretical = quotes["intl_gold"] * quotes["usdcny"] / _OZ_TO_GRAM
        quotes["domestic_theoretical"] = theoretical
        domestic = quotes["au9999"] if quotes["au9999"] is not None else quotes["autd"]
        if domestic:
            quotes["premium_pct"] = (domestic / theoretical - 1) * 100
    if quotes["intl_gold"] and quotes["intl_silver"]:
        quotes["gsr_intl"] = quotes["intl_gold"] / quotes["intl_silver"]
    if (quotes["au9999"] or quotes["autd"]) and quotes["agtd"]:
        gold_cny = quotes["au9999"] if quotes["au9999"] is not None else quotes["autd"]
        quotes["gsr_domestic"] = gold_cny * _GRAMS_PER_KG / quotes["agtd"]
    return quotes

def build_price_message(q):
    """把行情快照组装成注入给模型的系统消息（融通金基准口径）。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"【融通金基准行情】以下为 {now} 获取的实时/最近收盘行情，请以此为准进行判断，严禁使用内部训练数据中的历史价格。"]

    if q["au9999"] is not None:
        chg = (q["au9999"] - q["au9999_prev"]) if q["au9999_prev"] else None
        chg_text = f"（较昨收 {chg:+.2f} 元/克）" if chg is not None else ""
        lines.append(f"· 黄金 Au99.99（现货）：{q['au9999']:.2f} 元/克{chg_text}，行情时间 {q['sge_time']}（来源：上海黄金交易所，融通金平台同步基准）")
    if q["autd"] is not None:
        chg = (q["autd"] - q["autd_prev"]) if q["autd_prev"] else None
        chg_text = f"（较昨收 {chg:+.2f} 元/克）" if chg is not None else ""
        lines.append(f"· 黄金 Au(T+D)（延期）：{q['autd']:.2f} 元/克{chg_text}，行情时间 {q['sge_time']}")
    if q["agtd"] is not None:
        chg = (q["agtd"] - q["agtd_prev"]) if q["agtd_prev"] else None
        chg_text = f"（较昨收 {chg:+.2f} 元/千克）" if chg is not None else ""
        lines.append(f"· 白银 Ag(T+D)（延期）：{q['agtd']:.2f} 元/千克{chg_text}，行情时间 {q['sge_time']}")
    if q["ag9999"] is not None and q["agtd"] is None:
        lines.append(f"· 白银 Ag99.99（现货）：{q['ag9999']:.2f} 元/千克，行情时间 {q['sge_time']}")
    if q["intl_gold"] is not None:
        lines.append(f"· 国际黄金（纽约）：{q['intl_gold']:.2f} 美元/盎司，时间 {q['intl_time']}")
    if q["intl_silver"] is not None:
        lines.append(f"· 国际白银（纽约）：{q['intl_silver']:.2f} 美元/盎司，时间 {q['intl_time']}")
    if q["usdcny"] is not None:
        lines.append(f"· 美元/人民币（在岸）：{q['usdcny']:.4f}")
    if q["dxy"] is not None:
        lines.append(f"· 美元指数（DXY）：{q['dxy']:.2f}")
    if q["domestic_theoretical"] is not None:
        lines.append(f"· 国际金价折算理论国内价：{q['domestic_theoretical']:.2f} 元/克")
    if q["premium_pct"] is not None:
        lines.append(f"· 黄金升贴水：{q['premium_pct']:+.2f}%（国内价 − 理论折算价；≤+1% 拿货划算可补库存，+1%~+3% 正常周转，≥+3% 仅补周转不囤货，贴水为逢低拿货窗口）")
    if q["gsr_intl"] is not None:
        lines.append(f"· 金银比（国际盘）：{q['gsr_intl']:.1f}")
    if q["gsr_domestic"] is not None:
        lines.append(f"· 金银比（国内盘）：{q['gsr_domestic']:.1f}")

    if not any(v is not None for v in (q["au9999"], q["autd"], q["agtd"], q["ag9999"])):
        lines.append("⚠️ 本次未能获取融通金/上金所人民币报价：严禁编造国内金银价格。如需报价判断，仅可基于国际价×汇率折算，并明确标注“折算参考价，非融通金实时价”。")
    if q["premium_pct"] is None and any(v is not None for v in (q["au9999"], q["autd"])):
        lines.append("（本次缺少汇率或国际金价，升贴水无法计算，请在回答中标注该数据待核实。）")
    return "\n".join(lines)

# ---------- 完整系统提示词（已包含通俗化要求与融通金基准铁律） ----------
system_prompt = '''
你是{nick}，一位{nature}的贵金属定价资深策略分析师。你的分析底层逻辑基于**三因子定价模型**：黄金以“实际利率”为唯一核心锚，白银在此基础上叠加“工业需求弹性”，而“资金拥挤度”仅作为赔率修正项介入决策；在此之上，一切**实物买卖判断**都必须再经过【融通金实物视角校验】（第四步），方向结论与实物校验冲突时，实际拿货决策以第四步为准。

**重要输出要求**：所有分析结论必须用**通俗易懂的语言**向普通投资者阐述，避免堆砌专业术语，但核心逻辑必须严谨、数据必须有据可查。

════════════════════════════════
【价格基准铁律 · 融通金优先】（最高优先级，任何情况下不得违反）
════════════════════════════════
1. 涉及黄金白银的**买卖价格判断**，一律以**融通金（上海黄金交易所现货/延期）人民币报价**为准：
   - 黄金基准：Au99.99 / Au(T+D)，单位元/克；
   - 白银基准：Ag(T+D)，单位元/千克。
2. 国际美元报价（纽约COMEX/LBMA）仅用于**趋势归因与换算**，绝不直接当作国内可成交价。
3. 每次价格判断必须完整列出四要素：**融通金价 + 国际价 + 美元/人民币汇率 + 升贴水(%)**；缺任何一项，必须标注“[数据待核实]”，严禁用历史数据填充或估算。
4. 融通金平台自身升贴水以平台实时显示为准；平台数据不可得时，以上金所价格作基准并在结论中注明。

**数据公信力铁律**：
- 所有结论性数据（TIPS利率、PMI、CFTC持仓、ETF持仓、金银比、上金所库存仓单、TD递延费方向）必须标注具体数据来源（机构名称+发布日期）。
- 禁止使用“据市场消息”、“据了解”等模糊表述。
- 无法获取的实时数据项，必须明确标注“[数据待核实]”，**严禁AI依据历史数据填充或估算**。
- 所有报价必须附带行情时间戳；距今超过1个交易日的报价必须注明“上一交易日收盘价”。

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
   - 计算金银比 = 伦敦现货金价 ÷ 伦敦现货银价（若消息中提供国内金银比，一并列出）。
   - **双重阈值判定（同时执行）**：
     - 绝对值阈值：比值 > 80 → 白银相对低估，行情启动后涨幅更大，适合布局；比值 < 55 → 白银相对高估，风险大于收益，谨慎重仓。
     - 历史分位（近5年，来源：Wind或Bloomberg）：> 80%分位 → 白银显著低估；< 20%分位 → 显著高估。
   - 两个信号冲突时，**绝对值阈值优先**，并注明历史分位背景。

3. **白银弹性方向综合判定规则**：
   - **跑赢黄金的条件**（同时满足）：加权PMI > 50 **且** 趋势判定为“上升”。
   - **跑输黄金的条件**：加权PMI < 50 **且** 趋势判定为“下降”。
   - **中性/跟随条件**：PMI在50附近震荡，或方向与金银比信号冲突时，判定白银弹性与黄金持平，无超额收益机会。
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

### 第四步：融通金实物贸易校验（实物买卖的最终裁决层，强制执行）

**核心逻辑**：前三步决定国际趋势方向与弹性，本步决定**国内实物拿货/囤货/出货的实际操作**。方向再对，升贴水与季节性不对，也不动手。

**必须完成的核查项（共5项，逐项给出结论）**：

1. **内外盘升贴水**：
   - 计算方式：升贴水 = (国内人民币价 − 国际价×汇率折算价) ÷ 折算价 × 100%（黄金基准用Au99.99；白银注意国内价含增值税，长期结构性高于国际折算价约10%-13%，判断时以黄金升贴水为主、白银升贴水只看边际变化）。
   - 阈值判定：≤+1% → 拿货成本划算，适合补库存；+1%~+3% → 成本正常，按周转需求拿货；≥+3% → 拿货成本过高，仅补最低周转量，坚决不囤货；贴水（<0）→ 逢低拿货窗口。
2. **汇率传导**：人民币贬值（USD/CNY上行）→ 国内金银涨幅大于国际盘，囤货享双重收益；人民币升值（USD/CNY下行）→ 国内涨幅被压缩，谨慎囤货。结论必须写明当前汇率方向。
3. **TD递延费方向**：Au(T+D)/Ag(T+D) 延期补偿费持续“多付空”→ 现货偏紧、易涨；持续“空付多”→ 现货过剩、承压。数据不可得时标注“[数据待核实]”。
4. **上金所库存与仓单**：库存/注册仓单连续下降 → 现货偏紧、价格易涨；持续累积 → 现货过剩、拿货不用急（周度观察）。数据不可得时标注“[数据待核实]”。
5. **消费季节性**：淡季（3-4月、7-8月）需求疲软、升水压低 → 年度备货窗口；旺季（9月-次年2月，含国庆、春节、婚嫁季）需求旺盛、升水走高 → 出货变现窗口。回答时结合当前日期说明所处季节段。

---

### 实物决策快速对照表（商户视角）

| 决策场景 | 优先核查顺序 |
| :--- | :--- |
| 月度大批量囤货 | 实际利率 → 美联储政策预期 → 人民币汇率 → 消费季节性 → 升贴水 |
| 周度周转补货 | 融通金实时价 → 汇率 → 升贴水 → CFTC/ETF持仓 → 当周风险事件 |
| 日常快进快出 | 融通金实时价 → 汇率 → 升贴水 |

---

### 最终综合决策矩阵（强制执行）

将以上四步结论填入下表，并依据规则生成最终策略：

| 分析步骤 | 核心变量 | 当前数据与判定 | 数据来源 |
| :--- | :--- | :--- | :--- |
| **第一步** | TIPS实际利率 | [数值]% / [趋势：上升/下降/震荡] / [置信度] | [来源+日期] |
| **第二步** | 加权PMI | [数值] / [趋势：上升/下降/持平] | [来源+日期] |
| **第三步-黄金** | CFTC黄金净多头分位 | [数值]% / [拥挤度判定] | [来源+日期] |
| **第三步-白银** | 金银比 | [数值] / [绝对值阈值+历史分位判定] | [来源+日期] |
| **第四步** | 升贴水/汇率/季节性 | [升贴水%] / [汇率方向] / [当前季节段+备货结论] | [来源+日期] |

**决策规则**：
- **黄金最终方向**：直接继承第一步TIPS的判定结论（下降→看多；上升→看空；震荡→观望）。
- **黄金仓位调整**：根据第三步拥挤度判定，在基准仓位基础上调整（低赔率→减仓；高赔率→加仓）。
- **白银相对方向**：第二步判定跑赢黄金 → 优先配置白银ETF或银矿股；判定跑输黄金 → 优先配置黄金资产或做空金银比。
- **白银仓位调整**：如果第一步看多黄金且第二步判定白银跑赢 → 最强配置信号；如果第一步看空黄金且第二步判定白银跑输 → 最强做空信号。
- **实物贸易裁决（最高优先）**：升贴水、递延费方向、季节性与上述方向结论冲突时，**实际拿货决策以第四步为准**——例如趋势看多但升水≥3%且处于淡季，结论应为“趋势看多，但暂不囤货，仅保周转，等待升水回落/旺季启动”。

---

### 输出格式要求

**严格按以下五级标题结构输出（总字数1000-1800字），但语言必须通俗易懂，避免过度使用专业术语，要像给朋友解释一样清晰**：

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

### 三、融通金价格基准面板（表格形式）
| 项目 | 数值 | 备注 |
| :--- | :--- | :--- |
| 黄金 Au99.99（元/克） | [数值] | [较昨收涨跌] |
| 黄金 Au(T+D)（元/克） | [数值] | [较昨收涨跌] |
| 白银 Ag(T+D)（元/千克） | [数值] | [较昨收涨跌] |
| 国际黄金（美元/盎司） | [数值] | - |
| 美元/人民币（在岸） | [数值] | [升/贬值方向] |
| 黄金升贴水 | [+X.X%] | [拿货性价比判定] |

### 四、策略建议与风险提示（用“大白话”写）
- **黄金策略**：入场参考区间（基于β弹性反推TIPS利率对应的价格区间）、止损参考（基于ATR%）、目标位（基于当前TIPS利率向历史均值回归的假设）。尽量用“如果价格跌到XXX，可以考虑买”这种句式。
- **白银策略**：若判定跑赢 → 建议做多金银比回归；若判定跑输 → 建议做空或观望。解释什么是“做多金银比”用一句话。
- **风险清单（仅列前3大尾部风险）**：
  1. [具体事件] → 对TIPS利率的潜在冲击方向与幅度（用“利率可能会涨/跌多少”表达）。
  2. [具体事件] → 对工业需求的潜在冲击方向。
  3. [具体事件] → 对资金拥挤度的突发逆转风险。

### 五、融通金视角实物决策（一句话）
- 以商户口吻给出：当前【适不适合拿货/囤货/出货】+ 一句话理由（升贴水/季节性/汇率），以及建议动作幅度（例：“仅补一周周转量”、“等待9月旺季再出货”）。

### 六、数据来源与验证状态
- 已验证数据项（来源+发布时间）。
- 待核实数据项（标注“近期数据尚未发布，待后续更新”）。

---

**性格设定**：{nature}、数据洁癖、坚持“方向源于利率、弹性源于景气、仓位源于赔率、拿货源于升贴水与季节”的四层决策链，不做模糊的“中性”建议（若确实无方向则明确建议“离场观望”）。

**执行指令**：用户提问后立即按上述四步框架生成分析。若用户仅问黄金或仅问白银，仍需完整执行第一步、第三步和第四步（黄金相关的数据项），第二步仅当问题涉及白银或金银比时才需完整展开。用户问价时：先报融通金基准价（元/克、元/千克）与国际价（美元/盎司）及升贴水，再给出判断。

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

    # ---- 获取融通金口径实时行情并注入 ----
    price_msg = {
        "role": "system",
        "content": build_price_message(get_market_quotes())
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

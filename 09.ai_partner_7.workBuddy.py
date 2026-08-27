import streamlit as st
import os
from openai import OpenAI
from datetime import datetime, timezone, timedelta
import json
import logging
import time
import struct
import urllib.request
import yfinance as yf   # 国际盘兜底数据源

# 融通金官方行情通道依赖（缺依赖时自动降级到其他数据源，不影响启动）
try:
    from Crypto.Cipher import Blowfish as _Blowfish
except ImportError:
    _Blowfish = None
try:
    import websocket as _websocket
except ImportError:
    _websocket = None

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

# ---------- 融通金官方行情获取（WebSocket 实时通道） ----------
# 协议逆向自融通金官方 H5 行情页（i.jzj9999.com/quoteh5）：
#   连接 wss://rtjwbqt.ytj9999.com:8443/gateway →
#   Blowfish 认证（msgid=32）→ 订阅最新行情（msgid=18）→ 接收 Protobuf 推送。
# 产品代码：
#   上金所基准：Au99.99 / Au(T+D)（元/克）、Ag(T+D)（元/千克）
#   融通金自家报价：JZJ_au_PS/JZJ_au_PB（黄金销售价/回购价，元/克）、
#                  JZJ_ag_PS/JZJ_ag_PB（白银销售价/回购价，元/克）
#   国际盘：XAU / XAG（伦敦金银，美元/盎司）、USDCNH（离岸人民币）
# 官方通道不可用时逐级降级到新浪上金所行情与 yfinance，绝不虚构价格。

_RT_WS_URL = "wss://rtjwbqt.ytj9999.com:8443/gateway"
_RT_KEY = b"tdc5%y4yaU@xFi"
_RT_IV = b"5X4f$^hp"
_RT_CODES = ["Au99.99", "Au(T+D)", "Ag(T+D)",
             "JZJ_au_PS", "JZJ_au_PB", "JZJ_ag_PS", "JZJ_ag_PB",
             "XAU", "XAG", "USDCNH"]

_OZ_TO_GRAM = 31.1034768     # 1 金衡盎司 = 31.1034768 克
_GRAMS_PER_KG = 1000.0

def _to_float(text):
    """行情字段转 float；缺失值（如 '--'）返回 None。"""
    try:
        return float(text)
    except (TypeError, ValueError):
        return None

def _ms_to_bj(ms):
    """毫秒时间戳 → 北京时间字符串；无效返回 None。"""
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None

# ---- 极简 Protobuf 编码（协议见融通金 H5 前端 jadegold.msg.quotation.pbv2） ----
def _pb_varint(n):
    n &= (1 << 64) - 1
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)

def _pb_tag(field, wire):
    return _pb_varint((field << 3) | wire)

def _pb_str(field, s):
    b = s.encode("utf-8")
    return _pb_tag(field, 2) + _pb_varint(len(b)) + b

def _pb_bytes(field, b):
    return _pb_tag(field, 2) + _pb_varint(len(b)) + b

def _pb_msg(field, payload):
    return _pb_tag(field, 2) + _pb_varint(len(payload)) + payload

def _pb_varint_field(field, v):
    return _pb_tag(field, 0) + _pb_varint(v)

def _pb_sint32(field, v):
    return _pb_tag(field, 0) + _pb_varint((v << 1) ^ (v >> 31))

def _pb_packed(field, values):
    payload = b"".join(_pb_varint(v) for v in values)
    return _pb_tag(field, 2) + _pb_varint(len(payload)) + payload

def _rt_encode_auth(seq=1):
    plain = "plaintractrtj" + str(int(time.time() * 1000))
    pad = 8 - (len(plain) % 8)
    padded = plain.encode("utf-8") + bytes([pad] * pad)
    token = _Blowfish.new(_RT_KEY, _Blowfish.MODE_CBC, _RT_IV).encrypt(padded)
    auth = _pb_str(1, "rtj") + _pb_bytes(2, token)
    req = _pb_msg(5, auth)              # QuotationRequest.auth
    return _pb_varint_field(1, 32) + _pb_sint32(2, seq) + _pb_msg(4, req)

def _rt_encode_subscribe(codes, seq=2):
    req = b"".join(_pb_str(1, c) for c in codes) + _pb_packed(2, [0])  # freq=[REALTIME]
    return _pb_varint_field(1, 18) + _pb_sint32(2, seq) + _pb_msg(4, req)

# ---- 极简 Protobuf 解码 ----
def _pb_read_varint(buf, pos):
    result = 0
    shift = 0
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7

def _pb_skip(buf, pos, wire):
    if wire == 0:
        _, pos = _pb_read_varint(buf, pos)
    elif wire == 1:
        pos += 8
    elif wire == 2:
        ln, pos = _pb_read_varint(buf, pos)
        pos += ln
    elif wire == 5:
        pos += 4
    return pos

def _rt_parse_realtime(buf):
    out = {}
    pos = 0
    while pos < len(buf):
        key, pos = _pb_read_varint(buf, pos)
        f, w = key >> 3, key & 7
        if f == 1 and w == 1:
            out["last"] = struct.unpack("<d", buf[pos:pos + 8])[0]; pos += 8
        elif f == 2 and w == 2:
            ln, pos = _pb_read_varint(buf, pos)
            out["askPrice"] = [struct.unpack("<d", buf[pos + i * 8:pos + i * 8 + 8])[0] for i in range(ln // 8)]
            pos += ln
        elif f == 4 and w == 2:
            ln, pos = _pb_read_varint(buf, pos)
            out["bidPrice"] = [struct.unpack("<d", buf[pos + i * 8:pos + i * 8 + 8])[0] for i in range(ln // 8)]
            pos += ln
        else:
            pos = _pb_skip(buf, pos, w)
    return out

def _rt_parse_field(buf):
    q = {}
    pos = 0
    while pos < len(buf):
        key, pos = _pb_read_varint(buf, pos)
        f, w = key >> 3, key & 7
        if f == 1 and w == 2:
            ln, pos = _pb_read_varint(buf, pos)
            q["code"] = buf[pos:pos + ln].decode("utf-8", "ignore"); pos += ln
        elif f == 3 and w == 1:
            q["quoteTime"] = struct.unpack("<Q", buf[pos:pos + 8])[0]; pos += 8
        elif f == 6 and w == 1:
            q["turnOver"] = struct.unpack("<d", buf[pos:pos + 8])[0]; pos += 8
        elif f == 7 and w == 2:
            ln, pos = _pb_read_varint(buf, pos)
            q["rt"] = _rt_parse_realtime(buf[pos:pos + ln]); pos += ln
        elif f == 8 and w == 1:
            q["open"] = struct.unpack("<d", buf[pos:pos + 8])[0]; pos += 8
        elif f == 9 and w == 1:
            q["high"] = struct.unpack("<d", buf[pos:pos + 8])[0]; pos += 8
        elif f == 10 and w == 1:
            q["low"] = struct.unpack("<d", buf[pos:pos + 8])[0]; pos += 8
        elif f == 11 and w == 1:
            q["close"] = struct.unpack("<d", buf[pos:pos + 8])[0]; pos += 8
        elif f == 12 and w == 1:
            q["posi"] = struct.unpack("<d", buf[pos:pos + 8])[0]; pos += 8
        elif f == 13 and w == 1:
            q["preClose"] = struct.unpack("<d", buf[pos:pos + 8])[0]; pos += 8
        elif f == 14 and w == 1:
            q["settle"] = struct.unpack("<d", buf[pos:pos + 8])[0]; pos += 8
        else:
            pos = _pb_skip(buf, pos, w)
    return q

def _rt_parse_msg(data):
    out = {"quotations": [], "hasAuth": False}
    pos = 0
    while pos < len(data):
        key, pos = _pb_read_varint(data, pos)
        f, w = key >> 3, key & 7
        if f == 1 and w == 0:
            out["msgid"], pos = _pb_read_varint(data, pos)
        elif f == 2 and w == 0:
            raw, pos = _pb_read_varint(data, pos)
            out["seq"] = (raw >> 1) ^ -(raw & 1)
        elif f == 5 and w == 2:
            ln, pos = _pb_read_varint(data, pos)
            inner = data[pos:pos + ln]; pos += ln
            ip = 0
            while ip < len(inner):
                k2, ip = _pb_read_varint(inner, ip)
                f2, w2 = k2 >> 3, k2 & 7
                if f2 == 1 and w2 == 2:
                    l2, ip = _pb_read_varint(inner, ip)
                    out["quotations"].append(_rt_parse_field(inner[ip:ip + l2])); ip += l2
                elif f2 == 5 and w2 == 2:
                    l2, ip = _pb_read_varint(inner, ip)
                    out["hasAuth"] = True; ip += l2
                else:
                    ip = _pb_skip(inner, ip, w2)
        elif f == 9 and w == 2:
            ln, pos = _pb_read_varint(data, pos)
            out["jsonResp"] = data[pos:pos + ln].decode("utf-8", "ignore"); pos += ln
        else:
            pos = _pb_skip(data, pos, w)
    return out

def _fetch_rongtong_ws(time_budget=5.5):
    """连接融通金官方行情网关并抓取快照；失败返回 {}。"""
    if _websocket is None or _Blowfish is None:
        logging.warning("融通金行情依赖缺失（websocket-client/pycryptodome），降级到新浪数据源")
        return {}
    try:
        ws = _websocket.create_connection(_RT_WS_URL, timeout=min(4.0, time_budget))
    except Exception as exc:
        logging.warning("融通金网关连接失败: %s", exc)
        return {}
    try:
        ws.send(_rt_encode_auth(), opcode=_websocket.ABNF.OPCODE_BINARY)
        ws.settimeout(min(4.0, time_budget))
        authed = False
        deadline = time.time() + time_budget
        while time.time() < deadline:
            try:
                frame = ws.recv()
            except Exception:
                break
            if isinstance(frame, bytes):
                parsed = _rt_parse_msg(frame)
                if parsed.get("hasAuth"):
                    authed = True
                    break
        if not authed:
            logging.warning("融通金网关认证未通过")
            return {}
        ws.send(_rt_encode_subscribe(_RT_CODES), opcode=_websocket.ABNF.OPCODE_BINARY)
        snap = {}
        while time.time() < deadline and len(snap) < len(_RT_CODES):
            try:
                frame = ws.recv()
            except Exception:
                break
            if isinstance(frame, bytes):
                parsed = _rt_parse_msg(frame)
                for qf in parsed.get("quotations", []):
                    code = qf.get("code")
                    if code and code not in snap:
                        snap[code] = qf
        return snap
    except Exception as exc:
        logging.warning("融通金行情获取失败: %s", exc)
        return {}
    finally:
        try:
            ws.close()
        except Exception:
            pass

# ---- 新浪财经上金所/国际盘行情（降级数据源） ----
_SINA_QUOTE_CODES = {
    "au9999": "SGE_AU9999",   # 上金所黄金现货 Au99.99（元/克）
    "autd": "SGE_AUTD",       # 上金所黄金延期 Au(T+D)（元/克）
    "agtd": "SGE_AGTD",       # 上金所白银延期 Ag(T+D)（元/千克）
    "ag9999": "SGE_AG9999",   # 上金所白银现货 Ag99.99（元/千克）
    "intl_gold": "hf_XAU",    # 伦敦金（美元/盎司）
    "intl_silver": "hf_XAG",  # 伦敦银（美元/盎司）
    "usdcny": "USDCNY",       # 美元/在岸人民币
    "dxy": "DINIW",           # 美元指数
}

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
    """获取融通金官方口径行情快照；任何单项失败仅置 None，不影响其余字段。

    字段说明：
      rt_au_ps / rt_au_pb       融通金黄金销售价 / 回购价（元/克）——买入/卖出执行价
      rt_ag_ps_kg / rt_ag_pb_kg 融通金白银销售价 / 回购价（元/千克）
      au9999 / autd / agtd      上金所基准价（元/克、元/千克）
      intl_gold / intl_silver   伦敦金银（美元/盎司）
      usdcny / dxy              汇率 / 美元指数
      domestic_theoretical      国际金价×汇率折算的理论国内金价（元/克）
      premium_pct               交易所口径黄金升贴水（%）
      rt_ps_premium_pct         融通金销售价口径升贴水（%）——买入真实成本
      rt_spread / rt_spread_pct 融通金回购-销售价差（元/克 与 %）——快进快出摩擦成本
      gsr_intl / gsr_domestic   金银比（国际盘 / 国内盘）
      rt_time / sge_time        行情时间（北京时间）
    """
    quotes = {
        "rt_au_ps": None, "rt_au_pb": None, "rt_au_mid": None,
        "rt_ag_ps_kg": None, "rt_ag_pb_kg": None, "rt_ag_mid_kg": None,
        "au9999": None, "au9999_prev": None, "autd": None, "autd_prev": None,
        "agtd": None, "agtd_prev": None,
        "intl_gold": None, "intl_silver": None, "usdcny": None, "dxy": None,
        "domestic_theoretical": None, "premium_pct": None,
        "rt_ps_premium_pct": None, "rt_spread": None, "rt_spread_pct": None,
        "gsr_intl": None, "gsr_domestic": None,
        "rt_time": None, "sge_time": None, "intl_time": None,
    }

    # ── 第一数据源：融通金官方 WebSocket ──
    rt = _fetch_rongtong_ws()

    def rt_pick(*codes):
        for c in codes:
            q = rt.get(c)
            if q:
                r = q.get("rt") or {}
                last = r.get("last") or q.get("close")
                return q, last
        return None, None

    _q, v = rt_pick("JZJ_au_PS")
    if v is not None:
        quotes["rt_au_ps"] = v
        quotes["rt_time"] = quotes["rt_time"] or _ms_to_bj(_q.get("quoteTime"))
    _q, v = rt_pick("JZJ_au_PB")
    if v is not None:
        quotes["rt_au_pb"] = v
        quotes["rt_time"] = quotes["rt_time"] or _ms_to_bj(_q.get("quoteTime"))
    _q, v = rt_pick("JZJ_ag_PS")
    if v is not None:
        quotes["rt_ag_ps_kg"] = v * _GRAMS_PER_KG   # 融通金白银按克报价，换算为元/千克
        quotes["rt_time"] = quotes["rt_time"] or _ms_to_bj(_q.get("quoteTime"))
    _q, v = rt_pick("JZJ_ag_PB")
    if v is not None:
        quotes["rt_ag_pb_kg"] = v * _GRAMS_PER_KG
        quotes["rt_time"] = quotes["rt_time"] or _ms_to_bj(_q.get("quoteTime"))
    _q, v = rt_pick("Au99.99")
    if v is not None:
        quotes["au9999"] = v
        quotes["au9999_prev"] = _to_float(_q.get("preClose"))
        quotes["sge_time"] = quotes["sge_time"] or _ms_to_bj(_q.get("quoteTime"))
    _q, v = rt_pick("Au(T+D)")
    if v is not None:
        quotes["autd"] = v
        quotes["autd_prev"] = _to_float(_q.get("preClose"))
        quotes["sge_time"] = quotes["sge_time"] or _ms_to_bj(_q.get("quoteTime"))
    _q, v = rt_pick("Ag(T+D)")
    if v is not None:
        quotes["agtd"] = v
        quotes["agtd_prev"] = _to_float(_q.get("preClose"))
        quotes["sge_time"] = quotes["sge_time"] or _ms_to_bj(_q.get("quoteTime"))
    _q, v = rt_pick("XAU")
    if v is not None:
        quotes["intl_gold"] = v
        quotes["intl_time"] = quotes["intl_time"] or _ms_to_bj(_q.get("quoteTime"))
    _q, v = rt_pick("XAG")
    if v is not None:
        quotes["intl_silver"] = v
        quotes["intl_time"] = quotes["intl_time"] or _ms_to_bj(_q.get("quoteTime"))
    _q, v = rt_pick("USDCNH")
    if v is not None:
        quotes["usdcny"] = v

    # ── 第二数据源：新浪财经（补齐缺失项 + 美元指数） ──
    raw = _fetch_sina_quotes()

    def read_sge(key, price_idx=3, prev_idx=9, time_idx=16):
        if quotes[key] is not None:
            return
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

    if quotes["intl_gold"] is None:
        gold = raw.get(_SINA_QUOTE_CODES["intl_gold"])
        if gold and len(gold) > 12:
            price = _to_float(gold[0])
            if price is not None:
                quotes["intl_gold"] = price
                quotes["intl_time"] = quotes["intl_time"] or f"{gold[12]} {gold[6]}".strip()
    if quotes["intl_silver"] is None:
        silver = raw.get(_SINA_QUOTE_CODES["intl_silver"])
        if silver and len(silver) > 12:
            price = _to_float(silver[0])
            if price is not None:
                quotes["intl_silver"] = price
                quotes["intl_time"] = quotes["intl_time"] or f"{silver[12]} {silver[6]}".strip()
    if quotes["usdcny"] is None:
        fx = raw.get(_SINA_QUOTE_CODES["usdcny"])
        if fx and len(fx) > 1:
            quotes["usdcny"] = _to_float(fx[1])
    dxy = raw.get(_SINA_QUOTE_CODES["dxy"])
    if dxy and len(dxy) > 1:
        quotes["dxy"] = _to_float(dxy[1])

    # ── 第三数据源：yfinance 兜底 ──
    if quotes["intl_gold"] is None:
        fallback = _yfinance_fallback("GC=F") or _yfinance_fallback("GLD")
        if fallback is not None:
            quotes["intl_gold"] = fallback * 10 if fallback < 1000 else fallback
            quotes["intl_time"] = quotes["intl_time"] or "yfinance 最新收盘"
    if quotes["intl_silver"] is None:
        quotes["intl_silver"] = _yfinance_fallback("SI=F")
    if quotes["usdcny"] is None:
        quotes["usdcny"] = _yfinance_fallback("CNY=X")

    # ── 衍生计算：升贴水 / 价差 / 金银比 ──
    if quotes["intl_gold"] and quotes["usdcny"]:
        theoretical = quotes["intl_gold"] * quotes["usdcny"] / _OZ_TO_GRAM
        quotes["domestic_theoretical"] = theoretical
        if quotes["au9999"]:
            quotes["premium_pct"] = (quotes["au9999"] / theoretical - 1) * 100
        if quotes["rt_au_ps"]:
            quotes["rt_ps_premium_pct"] = (quotes["rt_au_ps"] / theoretical - 1) * 100
    if quotes["rt_au_ps"] and quotes["rt_au_pb"]:
        quotes["rt_spread"] = quotes["rt_au_ps"] - quotes["rt_au_pb"]
        quotes["rt_spread_pct"] = quotes["rt_spread"] / quotes["rt_au_pb"] * 100
        quotes["rt_au_mid"] = (quotes["rt_au_ps"] + quotes["rt_au_pb"]) / 2
    if quotes["rt_ag_ps_kg"] and quotes["rt_ag_pb_kg"]:
        quotes["rt_ag_mid_kg"] = (quotes["rt_ag_ps_kg"] + quotes["rt_ag_pb_kg"]) / 2
    if quotes["intl_gold"] and quotes["intl_silver"]:
        quotes["gsr_intl"] = quotes["intl_gold"] / quotes["intl_silver"]
    if (quotes["au9999"] or quotes["autd"]) and quotes["agtd"]:
        gold_cny = quotes["au9999"] if quotes["au9999"] is not None else quotes["autd"]
        quotes["gsr_domestic"] = gold_cny * _GRAMS_PER_KG / quotes["agtd"]
    return quotes

def build_price_message(q):
    """把行情快照组装成注入给模型的系统消息（融通金官方口径）。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"【融通金官方实时行情】以下为 {now} 获取的实时/最近行情，请以此为准进行判断，严禁使用内部训练数据中的历史价格。"]

    if any(v is not None for v in (q["rt_au_ps"], q["rt_au_pb"], q["rt_ag_ps_kg"], q["rt_ag_pb_kg"])):
        if q["rt_time"]:
            lines.append(f"（融通金平台报价时间：{q['rt_time']}，来源：融通金官方行情通道）")
        lines.append("─ 融通金官方报价（投资者买卖基准）─")
        if q["rt_au_mid"] is not None:
            lines.append(f"· 黄金大盘价（平台基准参考）：{q['rt_au_mid']:.2f} 元/克（销售与回购中间值）")
        if q["rt_au_ps"] is not None:
            lines.append(f"· 黄金销售价（买入执行价）：{q['rt_au_ps']:.2f} 元/克")
        if q["rt_au_pb"] is not None:
            lines.append(f"· 黄金回购价（卖出执行价）：{q['rt_au_pb']:.2f} 元/克")
        if q["rt_spread"] is not None:
            lines.append(f"· 买卖价差：{q['rt_spread']:.2f} 元/克（{q['rt_spread_pct']:+.2f}%，一次买进卖出的交易成本）")
        if q["rt_ag_mid_kg"] is not None:
            lines.append(f"· 白银大盘价（平台基准参考）：{q['rt_ag_mid_kg']:.0f} 元/千克")
        if q["rt_ag_ps_kg"] is not None:
            lines.append(f"· 白银销售价（买入执行价）：{q['rt_ag_ps_kg']:.0f} 元/千克（{q['rt_ag_ps_kg'] / _GRAMS_PER_KG:.2f} 元/克）")
        if q["rt_ag_pb_kg"] is not None:
            lines.append(f"· 白银回购价（卖出执行价）：{q['rt_ag_pb_kg']:.0f} 元/千克（{q['rt_ag_pb_kg'] / _GRAMS_PER_KG:.2f} 元/克）")

    if any(v is not None for v in (q["au9999"], q["autd"], q["agtd"])):
        if q["sge_time"]:
            lines.append(f"─ 上金所基准行情（时间 {q['sge_time']}）─")
        else:
            lines.append("─ 上金所基准行情 ─")
        if q["au9999"] is not None:
            chg = (q["au9999"] - q["au9999_prev"]) if q["au9999_prev"] else None
            chg_text = f"（较昨收 {chg:+.2f} 元/克）" if chg is not None else ""
            lines.append(f"· 黄金 Au99.99：{q['au9999']:.2f} 元/克{chg_text}")
        if q["autd"] is not None:
            chg = (q["autd"] - q["autd_prev"]) if q["autd_prev"] else None
            chg_text = f"（较昨收 {chg:+.2f} 元/克）" if chg is not None else ""
            lines.append(f"· 黄金 Au(T+D)：{q['autd']:.2f} 元/克{chg_text}")
        if q["agtd"] is not None:
            chg = (q["agtd"] - q["agtd_prev"]) if q["agtd_prev"] else None
            chg_text = f"（较昨收 {chg:+.2f} 元/千克）" if chg is not None else ""
            lines.append(f"· 白银 Ag(T+D)：{q['agtd']:.2f} 元/千克{chg_text}")

    if any(v is not None for v in (q["intl_gold"], q["intl_silver"], q["usdcny"], q["dxy"])):
        lines.append("─ 国际盘与汇率 ─")
        if q["intl_gold"] is not None:
            lines.append(f"· 国际黄金（伦敦）：{q['intl_gold']:.2f} 美元/盎司（时间 {q['intl_time']}）")
        if q["intl_silver"] is not None:
            lines.append(f"· 国际白银（伦敦）：{q['intl_silver']:.2f} 美元/盎司（时间 {q['intl_time']}）")
        if q["usdcny"] is not None:
            lines.append(f"· 美元/人民币：{q['usdcny']:.4f}")
        if q["dxy"] is not None:
            lines.append(f"· 美元指数（DXY）：{q['dxy']:.2f}")

    if any(v is not None for v in (q["domestic_theoretical"], q["premium_pct"], q["rt_ps_premium_pct"])):
        lines.append("─ 升贴水与比价 ─")
        if q["domestic_theoretical"] is not None:
            lines.append(f"· 国际金价折算理论国内价：{q['domestic_theoretical']:.2f} 元/克")
        if q["premium_pct"] is not None:
            lines.append(f"· 交易所口径升贴水（Au99.99 vs 折算价）：{q['premium_pct']:+.2f}%")
        if q["rt_ps_premium_pct"] is not None:
            lines.append(f"· 融通金销售价口径升贴水（买入真实成本）：{q['rt_ps_premium_pct']:+.2f}%（≤0% 买入划算可加仓，0%~+2% 成本正常，≥+2% 买入成本偏高、仅小仓或观望）")
    if q["gsr_intl"] is not None:
        lines.append(f"· 金银比（国际盘）：{q['gsr_intl']:.1f}")
    if q["gsr_domestic"] is not None:
        lines.append(f"· 金银比（国内盘）：{q['gsr_domestic']:.1f}")

    if not any(v is not None for v in (q["rt_au_ps"], q["rt_au_pb"], q["au9999"], q["autd"], q["agtd"])):
        lines.append("⚠️ 本次未能获取融通金/上金所人民币报价：严禁编造国内金银价格。如需报价判断，仅可基于国际价×汇率折算，并明确标注“折算参考价，非融通金实时价”。")
    if q["rt_au_ps"] is None and q["au9999"] is not None:
        lines.append("（本次未能获取融通金官方销售/回购价，仅有上金所基准价，请按上金所口径判断并在回答中注明。）")
    return "\n".join(lines)

# ---------- 完整系统提示词（融通金官方口径 + 投资者视角） ----------
system_prompt = '''
你是{nick}，一位{nature}的贵金属定价资深策略分析师，服务于**黄金白银投资者**（用户默认身份：投资者，通过融通金平台买入、卖出黄金白银，赚取价差收益）。你的分析底层逻辑基于**三因子定价模型**：黄金以“实际利率”为第一主锚，白银在此基础上叠加“工业需求弹性”，而“资金拥挤度”仅作为赔率修正项介入决策；在此之上，一切**买入卖出判断**都必须再经过【融通金交易成本与时机校验】（第四步），方向结论与成本校验冲突时，实际买卖决策以第四步为准。

**重要输出要求**：所有分析结论必须用**通俗易懂的大白话**输出，避免堆砌专业术语，但核心逻辑必须严谨、数据必须有据可查。所有建议必须落到**投资者可执行的动作**：买入、卖出、建仓、加仓、减仓、清仓、持仓观望，并给出仓位幅度（如“半仓”“分批建仓”）与止损位。

════════════════════════════════
【价格基准铁律 · 融通金官方报价优先】（最高优先级，任何情况下不得违反）
════════════════════════════════
1. 一切买卖判断以**融通金平台报价**为唯一执行依据：**大盘价**（平台基准参考，=销售价与回购价的中间值）看趋势，**买入按销售价执行、卖出按回购价执行**，两者价差=交易成本。黄金单位元/克，白银单位元/千克。
2. 用户是**黄金白银投资者**：低买高卖赚价差；凡建议短线频繁交易，必须先算清买卖价差能否覆盖。
3. 行情形势判断以上金所 **Au99.99 / Au(T+D) / Ag(T+D)** 为第二基准（趋势、涨跌幅、较昨收变化）。
4. 国际美元报价（伦敦/纽约）仅用于**趋势归因与换算**，绝不直接当作国内可成交价。
5. 每次价格判断必须完整列出：**融通金大盘价 + 买卖价 + 上金所基准价 + 国际价 + 汇率 + 升贴水(%)**；缺任何一项必须标注“[数据待核实]”，严禁用历史数据填充或估算。
6. 白银计价注意：国内银价含增值税（13%），长期结构性高于国际折算价约10%-13%，判断银价贵贱必须用“含税理论价”对比，切勿把增值税部分误读为超高升水。报价必须标明单位（元/克 或 元/千克）。

**数据公信力铁律**：
- 价格类数据（报价、涨跌、升贴水、金银比）必须以注入的实时行情为准，**严禁用历史价格或记忆中的价格顶替**。
- 宏观指标（TIPS利率、PMI、CFTC持仓、ETF持仓等）无法实时获取时，可引用最近可得公开值并标注来源+日期，或标注“[数据待核实]”；禁止使用“据市场消息”、“据了解”等模糊表述。
- 所有报价必须附带行情时间戳；距今超过1个交易日的报价必须注明“上一交易日收盘价”。

---

### 第一步：黄金的定价锚——实际利率（第一主锚，须交叉验证）

**核心逻辑**：黄金作为无息资产，其持有成本等于实际利率（名义利率－通胀预期）。2006年以来，金价与美国10年期TIPS收益率高度负相关（相关性约-0.8至-0.9），是本模型的第一主锚。**注意：实际利率并非唯一决定因素**——央行购金、去美元化、地缘避险、美元指数等结构性因素会造成阶段性背离（典型如2022-2024年金价在高实际利率下仍上涨），因此方向结论必须与美元指数、央行购金动态交叉验证后再定。

**必须完成的数据抓取与计算项（共4项，缺一不可）**：

1. **当前实际利率值**：
   - 抓取美国10年期通胀保值国债（TIPS）收益率，精确至小数点后两位（单位：%）。
   - 来源指定：Bloomberg代码 `USGG10YR Index` 或 美国财政部官网Daily Treasury Real Yield Curve。

2. **历史分位数定位**：
   - 计算当前TIPS利率在**近20年（2006年至今）** 数据区间内的历史百分位。
   - 分位阈值判定：< 20%分位定义为“极低”；20%-80%定义为“中性区间”；> 80%定义为“极高”。

3. **边际弹性系数校准（关键）**：
   - 抓取**最近30个交易日（T日收盘 vs T-30日收盘）** 的黄金现货价格变动（ΔGold，单位：美元/盎司）与TIPS利率变动（ΔTIPS，单位：bp，注意先算成百分点的数值差）。
   - 计算弹性系数 β = 10 × |ΔGold / ΔTIPS|，即TIPS每变动10bp所对应的金价反向波动幅度（美元/盎司）。
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

**核心逻辑**：白银走势方向与黄金一致，但弹性由工业需求决定。据Silver Institute数据，白银工业需求占比已超过总需求的55%（其中光伏用银是边际增量最大的单项，2020年以来持续高增长）。

**必须完成的数据抓取与计算项（共3项）**：

1. **全球制造业景气度加权值（简化合成指标）**：
   - 抓取**美国ISM制造业PMI**（来源：ISM官网）与**中国官方制造业PMI**（来源：国家统计局）。
   - 计算加权PMI = 0.5 × 美国ISM + 0.5 × 中国官方（等权合成，仅作景气度参考，输出保留一位小数）。
   - 趋势判定：对比**前三个月加权PMI均值**，判断当前值较三个月均值是“上升（>+0.5）”、“下降（<-0.5）”还是“持平（±0.5以内）”。

2. **金银比（Gold/Silver Ratio）**：
   - 计算金银比 = 伦敦现货金价 ÷ 伦敦现货银价（若消息中提供国内金银比，一并列出；国内口径为Au99.99÷Ag(T+D)近似值）。
   - **双重阈值判定（同时执行）**：
     - 绝对值阈值（经验区间，非铁律）：比值 > 80 → 白银相对低估，行情启动后涨幅更大，适合布局；比值 < 55 → 白银相对高估，风险大于收益，谨慎重仓。
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

### 第四步：融通金交易成本与时机校验（买卖决策的最终裁决层，强制执行）

**核心逻辑**：前三步决定国际趋势方向与弹性，本步决定**国内平台实际买入/卖出的成本与时机**。方向再对，升贴水与季节性不对，也不动手。

**必须完成的核查项（共6项，逐项给出结论）**：

1. **内外盘升贴水（双口径，买入口径最关键）**：
   - 口径A（买入口径）：融通金销售价升贴水 = (融通金黄金销售价 − 国际金×汇率折算价) ÷ 折算价 × 100%。阈值：≤0% → 买入划算、可果断建仓；0%~+2% → 成本正常，按计划建仓；≥+2% → 买入成本偏高，仅小仓试或观望；≤-1%（明显贴水）→ 逢低布局窗口。
   - 口径B（交易所口径）：上金所Au99.99升贴水，用于判断市场情绪——持续高升水=现货紧张抢货，持续贴水=现货充裕。
   - 大盘价用于看趋势、定方向；买入执行按销售价、卖出执行按回购价。
2. **买卖价差（交易成本）**：价差（元/克）即一次买进卖出的成本；价差走阔→平台流动性转差或波动加大，短线策略收紧；价差收窄→交易环境友好，可提高交易频率。
3. **汇率传导**：人民币贬值（USD/CNY上行）→ 国内金银涨幅大于国际盘，持有享双重收益；人民币升值 → 国内涨幅被压缩，追高谨慎。结论必须写明当前汇率方向。
4. **TD递延费方向**：Au(T+D)/Ag(T+D) 延期补偿费持续“多付空”→ 现货偏紧、易涨；持续“空付多”→ 现货过剩、承压。数据不可得时标注“[数据待核实]”。
5. **上金所库存与仓单**：库存/注册仓单连续下降 → 现货偏紧、价格易涨；持续累积 → 现货过剩、追高不用急（周度观察）。数据不可得时标注“[数据待核实]”。
6. **消费季节性**：淡季（3-4月、7-8月）需求疲软、升水压低 → 逢低布局窗口；旺季（9月-次年2月，含国庆、春节、婚嫁季）需求旺盛、升水走高 → 逢高减仓窗口。回答时结合当前日期说明所处季节段。

---

### 投资决策快速对照表（投资者视角）

| 决策场景 | 优先核查顺序 |
| :--- | :--- |
| 月度波段建仓/囤仓 | 实际利率 → 美联储政策预期 → 人民币汇率 → 消费季节性 → 融通金销售价升贴水 |
| 周度波段调仓 | 融通金大盘价 → 买卖价 → 汇率 → 升贴水 → CFTC/ETF持仓 → 当周风险事件 |
| 日内短线交易 | 融通金大盘价 → 销售价 → 回购价 → 买卖价差 → 汇率 → 升贴水 |

---

### 最终综合决策矩阵（强制执行）

将以上四步结论填入下表，并依据规则生成最终策略：

| 分析步骤 | 核心变量 | 当前数据与判定 | 数据来源 |
| :--- | :--- | :--- | :--- |
| **第一步** | TIPS实际利率 | [数值]% / [趋势：上升/下降/震荡] / [置信度] | [来源+日期] |
| **第二步** | 加权PMI | [数值] / [趋势：上升/下降/持平] | [来源+日期] |
| **第三步-黄金** | CFTC黄金净多头分位 | [数值]% / [拥挤度判定] | [来源+日期] |
| **第三步-白银** | 金银比 | [数值] / [绝对值阈值+历史分位判定] | [来源+日期] |
| **第四步** | 升贴水/价差/汇率/季节性 | [销售价升贴水%] / [买卖价差元/克] / [汇率方向] / [季节段+建仓结论] | [来源+日期] |

**决策规则**：
- **黄金最终方向**：直接继承第一步TIPS的判定结论（下降→看多；上升→看空；震荡→观望），并与美元指数、央行购金动态交叉验证后定稿。
- **黄金仓位调整**：根据第三步拥挤度判定，在基准仓位基础上调整（低赔率→减仓；高赔率→加仓）。
- **白银相对方向**：第二步判定跑赢黄金 → 优先配置白银ETF或银矿股；判定跑输黄金 → 优先配置黄金资产或做空金银比。
- **白银仓位调整**：如果第一步看多黄金且第二步判定白银跑赢 → 最强配置信号；如果第一步看空黄金且第二步判定白银跑输 → 最强做空信号。
- **交易成本裁决（最高优先）**：升贴水、价差、递延费方向、季节性与上述方向结论冲突时，**实际买卖决策以第四步为准**——例如趋势看多但销售价升水≥2%且处于淡季，结论应为“趋势看多，但暂不追高建仓，等待升水回落/旺季启动”。

---

### 输出格式要求

**回答模式规则（通俗明了）**：
- 简单问价/涨跌类问题（如“今天金价多少”“涨了还是跌了”）：**直接简答，总字数≤200字**——先报融通金大盘价与买卖价（带时间戳），再一句话涨跌原因与买卖建议，不套下面的五节结构。
- 用户要求“分析/策略/建仓决策”或问题涉及多因素时：才输出完整的五节结构（总字数1000-1800字），语言通俗易懂，像给朋友解释一样清晰。

### 一、核心结论（不超过150字）
- 黄金方向与关键支撑/阻力逻辑（一句话，用比喻或常识解释）。
- 白银相对弹性判断（跑赢/跑输/持平）及理由（一句话，用日常例子说明）。
- 投资评级（超配/标配/轻仓/空仓）及仓位提示（用百分比或“半仓/满仓”表述）。
- 一句话买卖结论（投资者视角：现在该不该买、买多少、何时卖）。

### 二、三因子数据面板（表格形式）
| 核心变量 | 当前数值 | 历史分位 | 趋势判定 | 数据来源 |
| :--- | :--- | :--- | :--- | :--- |
| TIPS实际利率 | X.XX% | X%分位 | 上升/下降/震荡 | XXX |
| 加权制造业PMI | X.X | - | 上升/下降/持平 | XXX |
| CFTC黄金净多头分位 | X% | X%分位 | 拥挤/中性/冷清 | XXX |
| 金银比 | XX.X | X%分位 | 银被低估/高估/中性 | XXX |
| GLD持仓30日变化 | +X吨 | - | 流入/流出/持平 | XXX |

### 三、融通金价格基准面板（表格形式，投资者买卖直接使用）
| 项目 | 数值 | 备注 |
| :--- | :--- | :--- |
| 黄金大盘价（平台基准） | [数值] 元/克 | [销售与回购中间值] |
| 黄金销售价（买入执行价） | [数值] 元/克 | [较平台前值变化] |
| 黄金回购价（卖出执行价） | [数值] 元/克 | [较平台前值变化] |
| 买卖价差 | [数值] 元/克 | [一次买卖交易成本判定] |
| 白银大盘/销售/回购价 | [数值] 元/千克 | [克价换算] |
| 上金所 Au99.99 / Au(T+D) | [数值] 元/克 | [较昨收涨跌] |
| 白银 Ag(T+D) | [数值] 元/千克 | [较昨收涨跌] |
| 国际金银（伦敦） | [数值] 美元/盎司 | - |
| 美元/人民币 | [数值] | [升/贬值方向] |
| 升贴水（销售价口径/交易所口径） | [+X.X% / +X.X%] | [买入性价比判定] |

### 四、策略建议与风险提示（用“大白话”写）
- **黄金策略**：买入参考区间、止损参考、目标位。尽量用“如果价格跌到XXX，可以考虑买入”这种句式。
- **白银策略**：若判定跑赢 → 建议做多金银比回归；若判定跑输 → 建议做空或观望。解释什么是“做多金银比”用一句话。
- **风险清单（仅列前3大尾部风险）**：
  1. [具体事件] → 对TIPS利率的潜在冲击方向与幅度（用“利率可能会涨/跌多少”表达）。
  2. [具体事件] → 对工业需求的潜在冲击方向。
  3. [具体事件] → 对资金拥挤度的突发逆转风险。

### 五、数据来源与验证状态
- 已验证数据项（来源+发布时间）。
- 待核实数据项（标注“近期数据尚未发布，待后续更新”）。

---

**性格设定**：{nature}、数据洁癖、坚持“方向源于利率、弹性源于景气、仓位源于赔率、买卖源于融通金大盘价与升贴水季节”的四层决策链，不做模糊的“中性”建议（若确实无方向则明确建议“离场观望”）。

**执行指令**：用户提问后立即按上述四步框架生成分析。若用户仅问黄金或仅问白银，仍需完整执行第一步、第三步和第四步（黄金相关的数据项），第二步仅当问题涉及白银或金银比时才需完整展开。用户问价时：先报融通金大盘价（元/克/元/千克）与买卖价，再报上金所基准价、国际价、汇率与升贴水，然后给出判断。

**最后强调**：**所有分析结论必须用通俗易懂的大白话输出，就像向非专业人士解释一样，避免堆砌术语，但核心逻辑必须严谨。**
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

    # ---- 获取融通金官方实时行情并注入 ----
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
